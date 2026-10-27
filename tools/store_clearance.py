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
- Stores rule 14: both nav lenses outside every tip store's rendered bounds and physical collider envelope, the
  missiles on the Wingtip stations and the tip tanks on the Tip Tank ones. The
  --lights-blockout mode uses tools/review_lights.py's geometry snapshot and the source Wingtip option list, for
  verification before Unity can build. It also checks the entire stock lens stays inboard of the tip face.
- Stores rule 18: every Conformal missile, where its rail ends and the motor lights, at least 1 m from every airframe
  mesh in flight (gear and doors stowed), the intake ducts named apart; and on its way down the rail at least rule 12's
  0.05 m from the stowed gear.

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
EJECT_CLEAR = 1.0  # Stores rule 18
LEG = re.compile(r"^gear_(leg|unsprung|arm|strut|piston)_[NLR](_visible)?$")
TYRE = re.compile(r"^gear_wheel_[NLR]_visible$")
DOOR = re.compile(r"^gear_door_\w+_visible$")
NOT_AIRFRAME = re.compile(r"^gear_(leg|wheel|unsprung|arm|strut|piston)_|chock", re.I)


def euler_x(degrees):
    return ("rot", axis_quat((1, 0, 0), degrees))


def aim_basis(direction, up):
    """Columns: direction, up made square to it, and their cross: the frame an AimConstraint holds a piece in."""
    a = direction / np.linalg.norm(direction)
    u = up - a * (a @ up)
    u /= np.linalg.norm(u)
    return np.column_stack([a, u, np.cross(a, u)])


def suspension(plane, leg):
    """A main leg's swing and strut, when it has them (IcarusAuthor.Gear.cs): the swing under the hinge, aimed at a
    point on the unsprung and turning about its frame's X alone; the strut's cylinder (on the leg's mount) and piston
    (on the swing), each aimed at the other's eye with its up held to the hinge axis at rest."""
    swing = next((t for t, n in plane.nodes.items() if n["name"].endswith("_swing") and plane.under(t, leg["hinge"])), None)
    if swing is None:
        return None
    target = next(t for t, n in plane.nodes.items() if n["name"].endswith("_swing_target") and plane.under(t, leg["unsprung"]))
    piston = next(t for t, n in plane.nodes.items() if n["name"].startswith("gear_piston_") and plane.under(t, swing))
    cylinder = plane.find("gear_strut_" + plane.nodes[piston]["name"][-1])
    up = plane.world(leg["hinge"])[1][:, 0]
    rest = {t: (plane.world(t)[1], aim_basis(plane.world(o)[0] - plane.world(t)[0], up))
            for t, o in ((cylinder, piston), (piston, cylinder))}
    return dict(swing=swing, target=target, pieces=((cylinder, piston), (piston, cylinder)), up=up, rest=rest)


def suspended(plane, leg, pose):
    """pose with a main leg's swing and strut added as the game's AimConstraints set them: the swing's local Euler X
    of its aim at the target (asin of the aim's part across the hinge), each strut piece turned from rest so its eye
    aims at the other's."""
    s = leg["suspension"]
    if s is None:
        return pose
    frame_pos, frame_rot, _ = plane.world(plane.nodes[s["swing"]]["parent"], pose)
    aim = frame_rot.T @ (plane.world(s["target"], pose)[0] - frame_pos)
    pose = dict(pose)
    pose[s["swing"]] = euler_x(np.degrees(np.arcsin(np.clip(-aim[1] / np.linalg.norm(aim), -1, 1))))
    for piece, other in s["pieces"]:
        world_rot, basis = s["rest"][piece]
        turned = aim_basis(plane.world(other, pose)[0] - plane.world(piece, pose)[0], s["up"]) @ basis.T @ world_rot
        parent_rot = plane.world(plane.nodes[piece]["parent"], pose)[1]
        pose[piece] = ("mat", parent_rot.T @ turned)
    return pose


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
        lamps = ([(name, (np.asarray(m["vertices"]), np.asarray(m["triangles"]))) for name, m in snapshot["lamps"].items()]
                 if "lamps" in snapshot else
                 [("navlight_" + side, stock_lens(index, side, anchor)) for side, anchor in snapshot["nav_anchors"].items()])
        stations = [(name, np.asarray(t["position"]), quat_matrix(t["rotation"])) for name, t in snapshot["tip_stations"].items()]
        mounts = {key: load_mount(root, index, key) for key in wingtip_keys(paths.REPO)}
        print("Blender geometry and source Wingtip options; stock 14 triangle lens, centred as PlaceSystems places it")
        passed = check_tip_lamps(stations, lamps, mounts)
        for name, (verts, _) in lamps:
            side = name[-1]
            tip_gap = snapshot["tip_faces"][side] - np.abs(verts[:, 0]).max()
            print(f"{name} tip face {'PASS' if tip_gap > 0.00001 else 'FAIL'}: {tip_gap:.6f} m inboard")
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
        found = suspension(plane, g)
        meshes = [t for t in plane.meshes if plane.under(t, g["hinge"]) or any(plane.under(t, d) for d, _ in g["doors"])
                  or found and t == found["pieces"][0][0]]
        legs.append(dict(g, free=free, rest=rest, meshes=meshes, suspension=found))
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
        return suspended(plane, leg, pose)

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
        leg["clearance"] = [(label, [(name, mesh, bounds(mesh[0])) for name, mesh in meshes
                                    if TYRE.match(name) or LEG.match(name) or DOOR.match(name)])
                            for label, meshes in leg["posed"]]
        print(f"{leg['name']}: tyre r {leg['radius']:.3f} m, travel {leg['travel']:.3f} m, rest {leg['rest']:.3f} m, "
              f"bottomed {leg['max_compression']:.3f} m, fold {leg['fold']:.1f} deg in {n} steps, doors "
              f"{[round(d, 1) for _, d in leg['doors']]} deg closing in {m} steps; meshes "
              f"{sorted(plane.meshes[t][0] for t in leg['meshes'])}")

    def stock_mesh(name):
        """The stock mesh a mod mount's renderer shows, named like its GameObject (aam1 shows AAM1); the tip tank's lenses
        show the stock nav lens (IcarusAuthor.DressTipTank)."""
        path = mesh_path(index, "fighter1_navLight_L" if name.startswith("tip_tank_lens_") else name)
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
                store_bounds = bounds(store[0])
                angle = strike(store[0])
                rule13.append((angle if angle is not None else math.inf, hp_name, key))
                phases = {}
                for leg in legs:
                    if box_gap(store_bounds, (leg["free"] - 3.0, leg["free"] + 3.0)) > 0:
                        continue  # nowhere near this leg in any pose
                    for label, meshes in leg["clearance"]:
                        phase = label.split()[0]
                        best = phases.get(phase, (REACH, None))
                        for name, mesh, mesh_bounds in meshes:
                            if box_gap(store_bounds, mesh_bounds) >= best[0]:
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

    # A rail-launched missile rides its rail with the aircraft, so where its motor lights is fixed in the root frame at
    # any airspeed. It drops past the stowed gear, so its path is held to Stores rule 12's gap from the gear as well.
    print("\n## Eject (Stores rule 18: the motor lights where the rail ends)")
    print("hardpoint | mount | rail m | at ignition, least gap m to the airframe (where) / to the intake ducts | "
          "on the rail, least gap m to the stowed gear (where)")
    flight = {}
    for leg in legs:
        flight.update(leg_pose(leg, 0.0, 1.0, 0.0))
    flown = [(name, plane.posed(t, flight)) for t, (name, _, _) in plane.meshes.items()]
    rule18 = []
    for s, (set_name, hardpoints) in enumerate(plane.sets):
        if set_name != "Conformal":
            continue
        for hp_name, hp in hardpoints:
            pos, rot, _ = plane.world(hp)
            for key in plane.mounts[s]:
                for (verts, tris), direction, length in plane.ejected(key, stock_mesh):
                    body, along = pos + verts @ rot.T, rot @ direction
                    lit = (body + along * length, tris)
                    reach = EJECT_CLEAR + REACH
                    gap, where = min((mesh_distance(lit, mesh, reach), name) for name, mesh in flown)
                    ducts = min(mesh_distance(lit, mesh, reach) for name, mesh in flown if name.startswith("intake_duct"))
                    n = max(1, math.ceil(length / STEP))
                    path = min(((mesh_distance((body + along * (length * i / n), tris), mesh, REACH), f"{name} at {length * i / n:.2f} m")
                                for i in range(n + 1) for name, mesh in flown if LEG.match(name) or TYRE.match(name) or DOOR.match(name)),
                               default=(REACH, None))
                    rule18.append((gap, ducts, path[0], hp_name, key, where))
                    show = lambda g, r: "> %.2f" % r if g >= r else "%.3f" % g
                    print(f"{hp_name} | {key} | {length:.2f} | {show(gap, reach)} ({where}) / {show(ducts, reach)} | "
                          f"{show(path[0], REACH)} ({path[1] or 'all beyond reach'})")

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
    lamps = []
    for side in ("L", "R"):
        for name in ("navlight_" + side, "navlight_lower_" + side):
            pos, rot, scale = plane.world(plane.find(name))
            verts, tris = stock_lens(index, side)
            lamps.append((name, (pos + (verts * scale) @ rot.T, tris)))
        name = "light_nav_mount_" + side
        lamps.append((name, plane.posed(plane.find(name))))
    # Each tip set against its own stores: the missiles on the rolled Wingtip stations, the tanks on the Tip Tank ones.
    for tip_set in ("Wingtip", "Tip Tank"):
        found = [i for i, (name, _) in enumerate(plane.sets) if name == tip_set]
        if not found:
            failed = True
            print(f"Stores rule 14 FAIL: no {tip_set} set in the bundle")
            continue
        tip_stations = [(name, *plane.world(hp)[:2]) for name, hp in plane.sets[found[0]][1]]
        failed |= not check_tip_lamps(tip_stations, lamps, {key: mounts[key] for key in plane.mounts[found[0]]})
    gap, hp, key, where = min(rule12)
    ok = gap >= GAP
    failed |= not ok
    print(f"Stores rule 12 {'PASS' if ok else 'FAIL'}: least gap {gap:.3f} m (need {GAP}), {key} on {hp}, {where}")
    angle, hp, key = min(rule13)
    ok = angle >= tail
    failed |= not ok
    print(f"Stores rule 13 {'PASS' if ok else 'FAIL'}: first store to the ground {key} on {hp} at {angle:.2f} deg, "
          f"airframe tail strike {tail:.2f} deg")
    if rule18:
        gap, ducts, path, hp, key, where = min(rule18)
        ok = all(g >= EJECT_CLEAR and d >= EJECT_CLEAR and p >= GAP for g, d, p, _, _, _ in rule18)
        failed |= not ok
        print(f"Stores rule 18 {'PASS' if ok else 'FAIL'}: least gap at ignition {gap:.3f} m (need {EJECT_CLEAR}), {key} on {hp} "
              f"to {where}; intake ducts {min(r[1] for r in rule18):.3f} m; stowed gear on the rail {min(r[2] for r in rule18):.3f} m "
              f"(need {GAP})")
    else:
        failed = True
        print("Stores rule 18 FAIL: no missile on a Conformal mount in the bundle")
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
