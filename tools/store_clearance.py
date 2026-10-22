"""Hang every mount the built Icarus offers from its hardpoints and check what the stores clear.

python tools/store_clearance.py [path-to-icarus.nobp]       # default: the newest build/*.nobp
python tools/store_clearance.py --lights-blockout .cache/review/wave2/p7/01/lights-blockout.json

Reads the built bundle for the airframe, the hardpoint sets and the mounts registered on them (twin racks included),
the LandingGear components, the rest pose and the mod's own mounts (the conformal ones), and tools/local-paths.json's
game export for the stock mounts. Prints a verdict per check and exits nonzero on any FAIL:

- Stores rule 12: every store's rendered mesh (rail included) at least 0.05 m from every gear leg, tyre and open gear
  door: with the suspension free, at rest and bottomed (LandingGear.maxCompression, past which the game breaks the
  wheel), through retraction, and while the doors close. Doors stay open with the gear down and through the fold,
  then close (LandingGear.MoveGear). Distances are exact, triangle to triangle; the sweeps step so no gear vertex
  moves more than 0.01 m between poses.
- Stores rule 13: no store touches the ground before the airframe in a nose-up rotation about the main-wheel contact
  from the rest attitude (exact: the first contact of a plane is a vertex).
- Stores rule 5: each wingtip hardpoint on its tip face, 0.005 m in, at mid-thickness, 0.545 of the tip chord back from
  the leading edge (where both hooks of every wingtip mount bear on the face), its mount's -Y outboard.
- Stores rule 14: both nav lenses outside every tip store's rendered bounds and physical collider envelope. The
  --lights-blockout mode uses tools/review_lights.py's geometry snapshot and the source Wingtip option list, for
  verification before Unity can build. It also checks the entire stock lens stays inboard of the tip face.

Mount colliders against the tyres are reported, not judged: store-versus-airframe collider overlap is Unity's check
(A14). Everything is in the aircraft root frame (Unity: +x right, +y up, +z forward).
"""
import math
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stores import paths

LOCAL = paths.load()
from stores.bundle import Aircraft  # noqa: E402
from stores.geometry import axis_quat, bounds, box_gap, mesh_distance, quat_matrix, segment_distance  # noqa: E402
from stores import meshverts  # noqa: E402
from stores.bodies import mesh_path  # noqa: E402
from stores.mounts import load_mount  # noqa: E402
from stores.prefab_tree import asset_index  # noqa: E402
from stores.lights import check_tip_lamps, stock_lens, wingtip_keys  # noqa: E402

GAP = 0.05  # Stores rule 12
STEP = 0.01  # largest gear vertex move between two poses of a sweep
REACH = 0.5  # gaps beyond this are reported as "> REACH"
TIP_INSET, TIP_CHORD, TIP_TOLERANCE = 0.005, 0.545, 0.001  # Stores rule 5
LEG = re.compile(r"^gear_(leg|unsprung|arm)_[NLR](_visible)?$")
TYRE = re.compile(r"^gear_wheel_[NLR]_visible$")
DOOR = re.compile(r"^gear_door_\w+_visible$")
NOT_AIRFRAME = re.compile(r"^gear_(leg|wheel|unsprung|arm)_|chock", re.I)


def euler_x(degrees):
    return ("rot", axis_quat((1, 0, 0), degrees))


def box_mesh(centre, rot, half):
    corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], float) * half
    tris = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                     [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return centre + corners @ rot.T, tris


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--lights-blockout":
        snapshot = json.loads(Path(sys.argv[2]).read_text())
        root = LOCAL["game_export"]
        index = asset_index(root, "Mesh")
        lamps = [("navlight_" + side, stock_lens(index, side, anchor)) for side, anchor in snapshot["nav_anchors"].items()]
        stations = [(name, np.asarray(t["position"]), quat_matrix(t["rotation"])) for name, t in snapshot["tip_stations"].items()]
        mounts = {key: load_mount(root, index, key) for key in wingtip_keys(paths.REPO)}
        print("Blender geometry and source Wingtip options; stock 14 triangle lens, centred as PlaceSystems places it")
        passed = check_tip_lamps(stations, lamps, mounts)
        for side, anchor in snapshot["nav_anchors"].items():
            verts, _ = stock_lens(index, side, anchor)
            tip_gap = snapshot["tip_faces"][side] - np.abs(verts[:, 0]).max()
            print(f"navlight_{side} tip face {'PASS' if tip_gap > 0.00001 else 'FAIL'}: {tip_gap:.6f} m inboard")
            passed &= tip_gap > 0.00001
        sys.exit(0 if passed else 1)
    builds = sorted(Path(paths.REPO / "build").glob("*.nobp"), key=lambda p: p.stat().st_mtime)
    nobp = Path(sys.argv[1]) if len(sys.argv) > 1 else (builds[-1] if builds else None)
    if nobp is None or not nobp.exists():
        raise SystemExit("no built bundle: run tools/Build-Icarus.ps1 or pass a .nobp")
    plane = Aircraft(nobp)
    root, index = LOCAL["game_export"], asset_index(LOCAL["game_export"], "Mesh")
    print(f"# {nobp}: {len(plane.meshes)} rendered meshes; game export {root}")

    # The rest attitude: the root pitched by restRotation.x, spawnOffset.y above the ground. A point's height above the
    # ground is H + y cos a - z sin a; forward along the ground is (0, sin a, cos a).
    a = math.radians(plane.rest_rotation[0])
    up = np.array([0.0, math.cos(a), -math.sin(a)])
    forward = np.array([0.0, math.sin(a), math.cos(a)])
    height = lambda p: plane.spawn_offset[1] + p @ up
    legs = []
    for g in plane.gear:
        pos, rot, _ = plane.world(g["cast"])
        free = pos - rot[:, 1] * g["travel"]  # the tyre's bottom with the spring free
        rest = -height(free) / float(up @ rot[:, 1])  # compression that puts it on the ground at rest
        meshes = [t for t in plane.meshes if plane.under(t, g["hinge"]) or any(plane.under(t, d) for d, _ in g["doors"])]
        legs.append(dict(g, free=free, rest=rest, meshes=meshes))
    nose = max(legs, key=lambda l: l["free"][2])
    mains = [l for l in legs if l is not nose]
    contact = np.mean([l["free"] + plane.world(l["cast"])[1][:, 1] * l["rest"] for l in mains], axis=0)

    def strike(points):
        """Nose-up rotation from the rest attitude about the main contact at which the first point aft of it touches."""
        rel = points - contact
        aft = -(rel @ forward)
        h = rel @ up
        keep = aft > 0.05
        return float(np.degrees(np.arctan2(h[keep], aft[keep])).min()) if keep.any() else None

    airframe = [plane.posed(t) for t, (name, _, _) in plane.meshes.items() if not NOT_AIRFRAME.search(name)]
    tail = min(s for s in (strike(v) for v, _ in airframe) if s is not None)
    print(f"rest: {plane.spawn_offset[1]:.3f} m up, pitch {plane.rest_rotation[0]:+.2f} deg; main contact "
          f"{np.round(contact, 3)}; airframe tail strike {tail:.2f} deg")

    # Every pose a leg takes: suspension free, at rest, bottomed (doors open), the fold (doors open), the doors closing.
    def leg_pose(leg, compression=0.0, fold=0.0, doors=1.0):
        pose = {leg["unsprung"]: ("pos", np.array([0.0, -(leg["travel"] - compression - leg["radius"]), 0.0])),
                leg["hinge"]: euler_x(leg["fold"] * fold)}
        pose.update({t: euler_x(angle * fold) for t, angle in leg["moving"]})
        pose.update({t: euler_x(angle * doors) for t, angle in leg["doors"]})
        return pose

    def reach_of(leg, joints, pose):
        """Largest arc any of leg's mesh vertices sweeps when each joint (transform, degrees) turns fully."""
        total = 0.0
        for joint, degrees in joints:
            pos, rot, _ = plane.world(joint, pose)
            radius = 0.0
            for t in leg["meshes"]:
                if plane.under(t, joint):
                    rel = plane.posed(t, pose)[0] - pos
                    radius = max(radius, float(np.linalg.norm(rel - np.outer(rel @ rot[:, 0], rot[:, 0]), axis=1).max()))
            total += math.radians(abs(degrees)) * radius
        return total

    for leg in legs:
        free_pose = leg_pose(leg)
        leg["states"] = [("free", leg_pose(leg, 0.0)), ("rest", leg_pose(leg, leg["rest"])),
                         ("bottomed", leg_pose(leg, leg["max_compression"]))]
        n = max(1, math.ceil(reach_of(leg, [(leg["hinge"], leg["fold"])] + leg["moving"], free_pose) / STEP))
        leg["states"] += [(f"fold {i / n:.2f}", leg_pose(leg, 0.0, i / n)) for i in range(1, n + 1)]
        stowed = leg_pose(leg, 0.0, 1.0)
        m = max(1, math.ceil(reach_of(leg, leg["doors"], stowed) / STEP))
        leg["states"] += [(f"doors {1 - j / m:.2f}", leg_pose(leg, 0.0, 1.0, 1 - j / m)) for j in range(1, m + 1)]
        leg["posed"] = [(label, [(plane.meshes[t][0], plane.posed(t, pose)) for t in leg["meshes"]]) for label, pose in leg["states"]]
        print(f"{leg['name']}: tyre r {leg['radius']:.3f} m, travel {leg['travel']:.3f} m, rest {leg['rest']:.3f} m, "
              f"bottomed {leg['max_compression']:.3f} m, fold {leg['fold']:.1f} deg in {n} steps, doors "
              f"{[round(d, 1) for _, d in leg['doors']]} deg closing in {m} steps; meshes "
              f"{sorted(plane.meshes[t][0] for t in leg['meshes'])}")

    def stock_mesh(name):
        """The stock mesh a mod mount's renderer shows, named like its GameObject (aam1 shows AAM1)."""
        path = mesh_path(index, name)
        return np.array(meshverts.positions(path), float), np.asarray(meshverts.triangles(path), int).reshape(-1, 3)

    mounts = {}
    rule12, rule13 = [], []
    print("\n## Stores (rendered mesh, rail included)")
    print("hardpoint | mount | pitch strike deg | rest ground clearance m | least gap m: free / rest / bottomed / fold / "
          "doors closing (where) | mount colliders to tyre: free / rest / bottomed")
    for s, (set_name, hardpoints) in enumerate(plane.sets):
        for hp_name, hp in hardpoints:
            pos, rot, _ = plane.world(hp)
            for key in plane.mounts[s]:
                if key not in mounts:
                    # a stock mount from the game export; the mod's own from the bundle, which carries its prefab
                    stock = (root / "GameObject" / (key + ".prefab")).exists()
                    mounts[key] = load_mount(root, index, key) if stock else plane.mount(key, stock_mesh)
                (verts, tris), colliders = mounts[key]
                store = (pos + verts @ rot.T, tris)
                angle = strike(store[0])
                rule13.append((angle if angle is not None else math.inf, hp_name, key))
                phases = {}
                for leg in legs:
                    if box_gap(bounds(store[0]), (leg["free"] - 3.0, leg["free"] + 3.0)) > 0:
                        continue  # nowhere near this leg in any pose
                    for label, meshes in leg["posed"]:
                        phase = label.split()[0]
                        best = phases.get(phase, (REACH, None))
                        for name, mesh in meshes:
                            if not (TYRE.match(name) or LEG.match(name) or DOOR.match(name)):
                                continue
                            d = mesh_distance(store, mesh, best[0])
                            if d < best[0]:
                                best = (d, f"{name} at {label}")
                        phases[phase] = best
                worst = min(phases.values(), key=lambda b: b[0], default=(REACH, None))
                rule12.append((worst[0], hp_name, key, worst[1]))
                cells = " / ".join("> %.2f" % REACH if phases.get(p, (REACH,))[0] >= REACH else "%.3f" % phases[p][0]
                                   for p in ("free", "rest", "bottomed", "fold", "doors"))
                gaps = []
                for label in ("free", "rest", "bottomed"):
                    tyres = [mesh for leg in legs for l, ms in leg["posed"] if l == label for n, mesh in ms if TYRE.match(n)]
                    found = []
                    for c in colliders:
                        if c["trigger"]:
                            continue
                        centre, frame = pos + rot @ np.asarray(c["centre"]), rot @ quat_matrix(c["rot"])
                        for tyre in tyres:
                            if c["kind"] == "Capsule":  # its axis segment, less the radius: negative is overlap
                                half = frame[:, c["axis"]] * c["half_len"]
                                found.append(segment_distance(centre - half, centre + half, tyre) - c["r"])
                            else:
                                found.append(mesh_distance(box_mesh(centre, frame, np.asarray(c["half"])), tyre, REACH))
                    gaps.append(min(found, default=None))
                coll = "none" if not colliders else " / ".join("> %.2f" % REACH if g is None or g >= REACH else "%+.3f" % g for g in gaps)
                clearance = float(height(store[0]).min())
                print(f"{hp_name} | {key} | {'-' if angle is None else f'{angle:.2f}'} | {clearance:.3f} | {cells} "
                      f"({worst[1] or 'all beyond reach'}) | {coll}")

    print("\n## Wingtip stations (Stores rule 5)")
    rule5 = []
    for set_name, hardpoints in plane.sets:
        if set_name != "Wingtip":
            continue
        for hp_name, hp in hardpoints:
            pos, rot, _ = plane.world(hp)
            side = "L" if pos[0] < 0 else "R"
            skin = plane.posed(plane.find("wing_skin_" + side))[0]
            outer = np.abs(skin[:, 0]).max()
            face = skin[np.abs(skin[:, 0]) > outer - 0.001]
            le, te = face[:, 2].max(), face[:, 2].min()
            want = np.array([np.sign(pos[0]) * (outer - TIP_INSET), (face[:, 1].max() + face[:, 1].min()) / 2, le - TIP_CHORD * (le - te)])
            miss = float(np.linalg.norm(pos - want))
            outboard = math.degrees(math.acos(min(1.0, float(-rot[:, 1] @ np.array([np.sign(pos[0]), 0.0, 0.0])))))
            ahead = math.degrees(math.acos(min(1.0, float(rot[:, 2] @ np.array([0.0, 0.0, 1.0])))))
            rule5.append((miss, outboard, ahead, hp_name))
            print(f"{hp_name}: at {np.round(pos, 4)}, rule point {np.round(want, 4)} ({miss * 1000:.1f} mm); mount -Y "
                  f"{outboard:.2f} deg from outboard, +Z {ahead:.2f} deg from forward")

    print("\n## Verdicts")
    failed = False
    print("\n## Tip lamps (Stores rule 14)")
    tip_stations = [(name, *plane.world(hp)[:2]) for set_name, hardpoints in plane.sets if set_name == "Wingtip" for name, hp in hardpoints]
    lamps = []
    for side in ("L", "R"):
        name = "navlight_" + side
        pos, rot, scale = plane.world(plane.find(name))
        verts, tris = stock_lens(index, side)
        lamps.append((name, (pos + (verts * scale) @ rot.T, tris)))
    tip_mounts = {key: mounts[key] for i, (name, _) in enumerate(plane.sets) if name == "Wingtip" for key in plane.mounts[i]}
    failed |= not check_tip_lamps(tip_stations, lamps, tip_mounts)
    gap, hp, key, where = min(rule12)
    ok = gap >= GAP
    failed |= not ok
    print(f"Stores rule 12 {'PASS' if ok else 'FAIL'}: least gap {gap:.3f} m (need {GAP}), {key} on {hp}, {where}")
    angle, hp, key = min(rule13)
    ok = angle >= tail
    failed |= not ok
    print(f"Stores rule 13 {'PASS' if ok else 'FAIL'}: first store to the ground {key} on {hp} at {angle:.2f} deg, "
          f"airframe tail strike {tail:.2f} deg")
    if rule5:
        miss, outboard, ahead, hp = max(rule5)
        ok = all(m <= TIP_TOLERANCE and o <= 0.1 and h <= 0.1 for m, o, h, _ in rule5)
        failed |= not ok
        print(f"Stores rule 5 {'PASS' if ok else 'FAIL'}: worst {hp}, {miss * 1000:.1f} mm from the tip-face point "
              f"(within {TIP_TOLERANCE * 1000:.0f} mm), mount -Y {outboard:.2f} deg from outboard")
    else:
        failed = True
        print("Stores rule 5 FAIL: no Wingtip set in the bundle")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
