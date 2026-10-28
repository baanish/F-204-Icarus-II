"""Solve the Icarus main gear's F-104 fold: the hinge, fold angle and geared wheel swivel that carry the left wheel
from its down position to lie flat in the belly (art/blender/gear.py GEAR["main"] takes the numbers it prints).

Blender axes, left leg: x outboard, y = s - 8 aft, z up. The leg turns about a hinge through the keel pivot P; the
wheel centre goes from C (down) to C2 (stowed), so the hinge is square to C2 - C (a one-parameter family about P,
each member with its own fold angle). Geared to the fold, the wheel carrier swivels 90 degrees about an axis through
the wheel centre, so the axle (+x, outboard, gear down) ends vertical. Each hinge in the family has its own fold angle
and a short list of swivel axes that do it; --fold picks the hinge whose fold is nearest.

With --bundle, every hinge in the family and each of its swivels is swept against what the folding gear must clear
in the built aircraft (clearance_scene): the tyre and the leg line, both linear in the fold as LandingGear moves them,
against the stores (Stores rule 12's 0.05 m) and the airframe no door or well can open (HARD, NO_DOOR). --scan prints
the best.

    python -I tools/gear_fold_solve.py --pivot 9.85,0.20,-0.28 --wheel 9.84,1.24,-0.95 --stow 0.335,-0.085 --fold 109.5
    python -I tools/gear_fold_solve.py --pivot 10.47,0.30,-0.20 --wheel 9.84,1.24,-0.95 --stow 0.335,-0.055 \\
        --bundle build/icarus_0.1.0.nobp --scan
"""
import argparse
import math
import time

import numpy as np

STORE_GAP = 0.05  # Stores rule 12
LEG_R = 0.06  # the leg's half-width about its line, pivot to wheel centre
# Stores the folding gear must keep STORE_GAP from, by hardpoint name part, and the airframe it cannot pass through,
# by mesh name prefix: everything else on its way is skin a door opens or structure a well clears.
STORE_HARDPOINTS = ("innerwing_L", "conformal_L")
HARD = ("wing_skin_inner_upper_L", "wing_skin_inner_lower_L", "wing_skin_outer_upper_L", "wing_skin_outer_lower_L",
        "intake_duct_L", "engine_core")
# And skin no door can open, as (s from, s to, x from, x to) boxes of skin faces wholly inside them below z -0.1: the
# left conformal trough with its rear ramp (art/blender/stations.py), whose faces follow the ramp's moving columns,
# and the ramp's fade inboard of the forward main door's stepped edge, where a door would share an edge with the aft
# door beside its inboard hinge (gear.GEAR["doors"]).
NO_DOOR = ((5.0, 8.96, 0.30, 0.62), (8.95, 9.08, 0.30, 0.66))


def rot(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = math.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * k @ k


def hinge_family(P, C, C2, n=7200):
    """(hinge, signed fold degrees) for hinges through P that turn C onto C2."""
    u, v = C - P, C2 - P
    d = (v - u) / np.linalg.norm(v - u)
    e1 = np.cross(d, [0, 0, 1.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(d, e1)
    for i in range(n):
        phi = math.pi * i / n
        h = math.cos(phi) * e1 + math.sin(phi) * e2
        pu, pv = u - h * h.dot(u), v - h * h.dot(v)
        yield h, math.degrees(math.atan2(h.dot(np.cross(pu, pv)), pu.dot(pv)))


def swivels(w):
    """Unit axes turning +x onto w by +90 degrees."""
    x = np.array([1.0, 0, 0])
    xw = float(x @ w)
    if xw < -1e-9:
        return []
    xw = max(xw, 0.0)
    a = (x + w) / np.linalg.norm(x + w)
    n = np.cross(x, w)
    n = n / np.linalg.norm(n) if np.linalg.norm(n) > 1e-9 else np.array([0, 0, 1.0])
    out = []
    for c in (math.sqrt(xw), -math.sqrt(xw)):
        alpha = c / math.sqrt((1 + xw) / 2)
        if abs(alpha) <= 1:
            for beta in (math.sqrt(1 - alpha * alpha), -math.sqrt(1 - alpha * alpha)):
                t = alpha * a + beta * n
                if np.allclose(rot(t, 90) @ x, w, atol=1e-6):
                    out.append(t)
    return out


def solve(P, C, C2, fold, outboard_up=True):
    """The solution whose fold is nearest `fold` degrees (the hinges form a one-parameter family, each with its own fold
    angle), the swivel axis nearest the leg line among equals, with the outboard face up (the axle stub, and the carrier
    on it, under the tyre) or down."""
    leg = (C - P) / np.linalg.norm(C - P)
    best = None
    up = np.array([0, 0, 1.0 if outboard_up else -1.0])
    for h, ang in hinge_family(P, C, C2):
        if abs(ang - fold) > 6:
            continue
        for t in swivels(rot(h, -ang) @ up):
            score = (round(abs(ang - fold), 1), math.degrees(math.acos(min(1, abs(t @ leg)))))
            if best is None or score < best[0]:
                best = (score, h, ang, t)
    return best


def surface_points(verts, tris, spacing=0.01):
    """Points over a mesh's faces (tris) no further apart than about spacing, their corners included."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    out = [verts[np.unique(tris)]]
    for k in np.unique(np.ceil(np.sqrt(area / spacing ** 2 * 2)).astype(int)):
        if k < 2:
            continue
        sel = np.ceil(np.sqrt(area / spacing ** 2 * 2)).astype(int) == k
        uv = np.array([(i / k, j / k) for i in range(k + 1) for j in range(k + 1 - i)])
        out.append((a[sel, None] * (1 - uv[:, 0] - uv[:, 1])[None, :, None] + b[sel, None] * uv[None, :, 0, None]
                    + c[sel, None] * uv[None, :, 1, None]).reshape(-1, 3))
    return np.concatenate(out)


def clearance_scene(nobp):
    """From a built bundle (tools/store_clearance.py's reading of it), Blender axes: the left tyre's points about its
    centre gear down, and KD-trees over the stores' and the hard airframe's surfaces."""
    import sys
    from pathlib import Path

    from scipy.spatial import cKDTree

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stores import paths

    local = paths.load()
    from stores import meshverts
    from stores.bodies import mesh_path
    from stores.bundle import Aircraft
    from stores.mounts import load_mount
    from stores.prefab_tree import asset_index

    # the aircraft root frame (Unity: +x right, +y up, +z forward) to Blender's
    blender = lambda u: np.stack([-u[:, 0], -(u[:, 2] - 0.375), u[:, 1] + 0.2652], axis=1)
    plane = Aircraft(Path(nobp))
    root = local["game_export"]
    index = asset_index(root, "Mesh")

    def stock_mesh(name):  # the stock mesh a mod mount's renderer shows
        path = mesh_path(index, name)
        return np.array(meshverts.positions(path), float), np.asarray(meshverts.triangles(path), int).reshape(-1, 3)

    tyre, hard = None, []
    for t, (name, _, _) in plane.meshes.items():
        if name == "gear_wheel_L_visible":
            v, tris = plane.posed(t)
            tyre = surface_points(blender(v), np.asarray(tris).reshape(-1, 3), 0.02)
        elif name.startswith(HARD):
            v, tris = plane.posed(t)
            hard.append(surface_points(blender(v), np.asarray(tris).reshape(-1, 3), 0.02))
        elif name.startswith(("skin_forward_L", "skin_mid_L")):
            v, tris = plane.posed(t)
            v, tris = blender(v), np.asarray(tris).reshape(-1, 3)
            c = v[tris]
            keep = np.zeros(len(tris), bool)
            for s0, s1, x0, x1 in NO_DOOR:
                keep |= np.all((c[..., 1] + 8 > s0) & (c[..., 1] + 8 < s1) & (c[..., 0] > x0) & (c[..., 0] < x1)
                               & (c[..., 2] < -0.1), axis=1)
            hard.append(surface_points(v, tris[keep], 0.008))  # the tyre passes these closest
    stores = []
    for s, (_, hardpoints) in enumerate(plane.sets):
        for hp_name, hp in hardpoints:
            if not any(k in hp_name for k in STORE_HARDPOINTS):
                continue
            pos, rotm, _ = plane.world(hp)
            for key in plane.mounts[s]:
                stock = (root / "GameObject" / (key + ".prefab")).exists()
                (verts, tris), _ = load_mount(root, index, key) if stock else plane.mount(key, stock_mesh)
                stores.append(surface_points(blender(pos + verts @ rotm.T), np.asarray(tris).reshape(-1, 3)))
    centre = blender(plane.posed(next(t for t, m in plane.meshes.items() if m[0] == "gear_wheel_L_visible"))[0]).mean(0)
    stores, hard = np.concatenate(stores), np.concatenate(hard)
    return {"tyre": tyre - centre, "centre": centre, "stores": cKDTree(stores), "hard": cKDTree(hard),
            "stores_box": (stores.min(0), stores.max(0)), "hard_box": (hard.min(0), hard.max(0))}


def sweep_gaps(P, h, ang, t, scene, steps=60, coarse=False, pin=None):
    """Least gaps through the fold (0 to 1) of the tyre and leg line to the stores and to the hard airframe, and the
    fold of each: (store gap, fold, hard gap, fold). Coarse takes every eighth tyre point, to rank candidates. The
    wheel swivels about an axis through pin (default its centre), where the leg ends."""
    C = scene["centre"]
    Q = C if pin is None else pin
    points = scene["tyre"][::8] if coarse else scene["tyre"]
    leg = P + np.linspace(0.05, 0.85, 12)[:, None] * (Q - P)
    worst = [9.0, 0.0, 9.0, 0.0]
    for f in np.linspace(0.0, 1.0, steps + 1):
        H = rot(h, ang * f)
        tyre = P + (H @ (Q - P + (rot(t, 90 * f) @ (C - Q + points).T).T).T).T
        legs = P + (H @ (leg - P).T).T
        for key, slot in (("stores", 0), ("hard", 2)):
            lo, hi = scene[key + "_box"]

            def near(q):  # points beyond the cloud's bounds grown 0.3 m are far enough not to ask
                q = q[np.all((q > lo - 0.3) & (q < hi + 0.3), axis=1)]
                return scene[key].query(q, distance_upper_bound=0.3, workers=-1)[0].min() if len(q) else 9.0

            d = min(near(tyre), near(legs) - LEG_R)
            if d < worst[slot]:
                worst[slot], worst[slot + 1] = d, f
    return tuple(worst)


def own_leg_gap(P, pin, t, scene, steps=30, radius=0.035):
    """The tyre's least gap to its own leg, pivot to pin (a beam radius about its line), as the wheel swivels about
    the axis through pin: the leg's own frame, where the hinge drops out. (gap, fold)."""
    C = scene["centre"]
    leg = P + np.linspace(0.0, 1.0, 40)[:, None] * (pin - P)
    from scipy.spatial import cKDTree

    tree, worst = cKDTree(leg), (9.0, 0.0)
    for f in np.linspace(0.0, 1.0, steps + 1):
        tyre = pin + (rot(t, 90 * f) @ (C - pin + scene["tyre"]).T).T
        d = tree.query(tyre)[0].min() - radius
        worst = min(worst, (d, f))
    return worst


def pin_solutions(P, C, Q, stow, folds=(60.0, 140.0), near=None, cone=40.0, starts=12):
    """Hinges, folds and 90 degree swivels about an axis through the pin Q (where the leg ends) that stow the wheel
    centre at stow, (x, z) or (s, x, z), with its axle vertical, outboard face up: given only (x, z) a curve of
    solutions, sampled by least squares from a grid of starts, the hinge within cone degrees of near if given; given
    the station too, the points where the curve meets it. Returns (hinge, fold, swivel, stowed wheel centre)."""
    from scipy.optimize import least_squares

    def unpack(v):
        h = np.array([math.cos(v[0]) * math.cos(v[1]), math.cos(v[0]) * math.sin(v[1]), math.sin(v[0])])
        return h, v[2]

    def stowed(v, which):
        h, ang = unpack(v)
        ts = swivels(rot(h, -ang) @ np.array([0, 0, 1.0]))
        if len(ts) <= which:
            return None, None, None
        t = ts[which]
        return P + rot(h, ang) @ (Q - P + rot(t, 90) @ (C - Q)), h, t

    def residual(v, which):
        w, _, _ = stowed(v, which)
        if w is None:
            return np.ones(len(stow))
        return np.array([w[0] - stow[-2], w[2] - stow[-1]] + ([w[1] + 8 - stow[0]] if len(stow) == 3 else []))

    out = []
    for el in np.linspace(-1.4, 1.4, starts):
        for az in np.linspace(-math.pi, math.pi, 2 * starts, endpoint=False):
            h0 = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
            if near is not None and math.degrees(math.acos(np.clip(h0 @ near, -1, 1))) > cone:
                continue
            for ang0 in np.linspace(folds[0], folds[1], 5):
                for which in (0, 1):
                    r = least_squares(residual, [el, az, ang0], args=(which,), xtol=1e-10, ftol=1e-10)
                    if np.abs(r.fun).max() > 1e-5 or not folds[0] <= r.x[2] <= folds[1]:
                        continue
                    w, h, t = stowed(r.x, which)
                    if w is not None and not any(np.allclose(h, o[0], atol=2e-3) and abs(r.x[2] - o[1]) < 0.2
                                                 for o in out):
                        out.append((h, r.x[2], t, w))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pivot", required=True, help="s,x,z")
    ap.add_argument("--wheel", required=True, help="s,x,z of the wheel centre, gear down")
    ap.add_argument("--stow", required=True, help="x,z of the stowed wheel centre (s follows from the leg length); "
                                                  "with --pin, s,x,z holds the station too")
    ap.add_argument("--fold", type=float, default=125.0, help="branch: fold degrees to stay near")
    ap.add_argument("--bundle", help="a built .nobp: sweep the solution against its stores and airframe")
    ap.add_argument("--scan", action="store_true", help="with --bundle, sweep every hinge in the family")
    ap.add_argument("--hinges", type=int, default=720, help="hinges in the family --scan tries")
    ap.add_argument("--branch", help="lo,hi: only folds in this range of degrees, each swept in full")
    ap.add_argument("--pin", help="dx,dz: the swivel's pin, where the leg ends, from the wheel centre (x outboard, "
                                  "z up), gear down; with --scan, solves hinges for a swivel about it")
    ap.add_argument("--near", help="hx,hy,hz: with --pin, only hinges within --cone degrees of this one")
    ap.add_argument("--cone", type=float, default=40.0)
    ap.add_argument("--solution", help="hx,hy,hz,fold,tx,ty,tz: sweep this hinge, fold and swivel")
    ap.add_argument("--axis-pin", help="lo,hi,n: with --solution, pins along the swivel axis inboard of the wheel, "
                                       "lo to hi metres from its centre")
    a = ap.parse_args()
    ps, px, pz = (float(v) for v in a.pivot.split(","))
    ws, wx, wz = (float(v) for v in a.wheel.split(","))
    stow = tuple(float(v) for v in a.stow.split(","))
    sx, sz = stow[-2:]
    P, C = np.array([px, ps - 8, pz]), np.array([wx, ws - 8, wz])
    reach = np.sum((C - P) ** 2) - (sx - px) ** 2 - (sz - pz) ** 2
    C2 = np.array([sx, P[1] - math.sqrt(reach), sz])
    print("stowed wheel centre s %.4f x %.4f z %.4f, leg %.4f m" % (C2[1] + 8, C2[0], C2[2], np.linalg.norm(C - P)))
    scene = None
    if a.bundle:
        t0 = time.time()
        scene = clearance_scene(a.bundle)
        print("clearance scene in %.1f s; tyre centre s %.3f x %.3f z %.3f" % (
            time.time() - t0, scene["centre"][1] + 8, scene["centre"][0], scene["centre"][2]))
    if a.solution and a.axis_pin:
        v = [float(x) for x in a.solution.split(",")]
        h, ang, t = np.array(v[:3]), v[3], np.array(v[4:])
        h, t = h / np.linalg.norm(h), t / np.linalg.norm(t)
        inboard = t if t[0] < 0 else -t
        lo, hi, n = (float(x) for x in a.axis_pin.split(","))
        for reach in np.linspace(lo, hi, int(n)):
            Q = scene["centre"] + inboard * reach
            sg, sf, hg, hf = sweep_gaps(P, h, ang, t, scene, 60, pin=Q)
            og, of = own_leg_gap(P, Q, t, scene)
            print("pin %.3f m along the axis (s %.3f x %.3f z %.3f): stores %.3f at %.2f, airframe %.3f at %.2f, "
                  "own leg %.3f at %.2f" % (reach, Q[1] + 8, Q[0], Q[2], sg, sf, hg, hf, og, of), flush=True)
        return
    if a.scan and a.pin:
        dx, dz = (float(v) for v in a.pin.split(","))
        Q = C + np.array([dx, 0.0, dz])
        lo, hi = (float(v) for v in (a.branch or "60,140").split(","))
        near = np.array([float(v) for v in a.near.split(",")]) if a.near else None
        t0 = time.time()
        sols = pin_solutions(P, C, Q, stow, (lo, hi), near / np.linalg.norm(near) if near is not None else None,
                             a.cone)
        print("pin s %.3f x %.3f z %.3f: %d solutions in %.0f s" % (Q[1] + 8, Q[0], Q[2], len(sols), time.time() - t0))
        rows = []
        for h, ang, t, w in sols:
            gaps = sweep_gaps(P, h, ang, t, scene, 60, pin=Q)
            rows.append((gaps, own_leg_gap(P, Q, t, scene), h, ang, t, w))
        rank = lambda r: -min(r[0][0] - STORE_GAP, r[0][2], r[1][0] - 0.018)
        for (sg, sf, hg, hf), (og, of), h, ang, t, w in sorted(rows, key=rank)[:12]:
            print('  stores %.3f at %.2f, airframe %.3f at %.2f, own leg %.3f at %.2f, stowed s %.3f: '
                  '"hinge": (%.5f, %.5f, %.5f), "fold_deg": %.3f, "swivel": (%.5f, %.5f, %.5f)'
                  % (sg, sf, hg, hf, og, of, w[1] + 8, *h, ang, *t))
        return
    if a.scan:
        rows = []
        t0 = time.time()
        lo, hi = (float(v) for v in a.branch.split(",")) if a.branch else (-1e9, 1e9)
        for h, ang in hinge_family(P, C, C2, a.hinges):
            if not lo <= ang <= hi:
                continue
            for t in swivels(rot(h, -ang) @ np.array([0, 0, 1.0])):
                rows.append((sweep_gaps(P, h, ang, t, scene, 60, coarse=not a.branch), h, ang, t))
                if len(rows) == 1:
                    print("one coarse candidate swept in %.2f s" % (time.time() - t0), flush=True)
        rank = lambda gaps: -min(gaps[0], gaps[2] + STORE_GAP)  # the stores need STORE_GAP, the airframe only clear
        best = sorted(rows, key=lambda r: rank(r[0]))[:12]
        print("%d candidates in %.0f s; the best, swept again in full:" % (len(rows), time.time() - t0))
        best = sorted(((sweep_gaps(P, h, ang, t, scene), h, ang, t) for _, h, ang, t in best), key=lambda r: rank(r[0]))
        for (sg, sf, hg, hf), h, ang, t in best:
            print('  stores %.3f at %.2f, airframe %.3f at %.2f: "hinge": (%.5f, %.5f, %.5f), "fold_deg": %.3f, '
                  '"swivel": (%.5f, %.5f, %.5f)' % (sg, sf, hg, hf, *h, ang, *t))
        return
    (_, off), h, ang, t = solve(P, C, C2, a.fold)
    R = rot(h, ang) @ rot(t, 90)
    print('"hinge": (%.5f, %.5f, %.5f), "fold_deg": %.3f,' % (*h, ang))
    print('"swivel": (%.5f, %.5f, %.5f), "swivel_deg": 90.0,  # %.1f deg off the leg line' % (*t, off))
    print("stowed axle %s, gear-down aft %s, gear-down up %s" % tuple(np.round(R @ v, 4) for v in np.eye(3)))
    if scene:
        print("sweep: stores %.3f m at fold %.2f, airframe %.3f m at fold %.2f" % sweep_gaps(P, h, ang, t, scene))


if __name__ == "__main__":
    main()
