"""Weapon stations: the inner wing pylon blades and their plugs, and the conformal trough with the Icarus's own
conformal mounts.

One blade hangs under each wing at a fraction of the span from the root row to the tip. Each carries one mount, which
the game hangs from the hardpoint under the middle of the blade's flat lower edge, so every mount's hooks and twin rack
bear on the blade. The blade is a shallow aerofoil shell whose root flares into the wing's lower surface. The wingtip stations have no blade or rail: every mount brings its own
launch rail, which bears straight on the tip face. The game hides an empty station's blade and shows its plug instead,
a stub on the blade's root footprint. The hardpoints themselves are placed by the Unity author
(IcarusAuthor.Stations.cs), which holds them to their measured positions.

The conformal stations hang their missiles partly inside the belly, in a trough cut round each missile's body. The
stock mounts' launch rails would hold a missile 0.04 to 0.11 m under the hardpoint, so these stations take the
Icarus's own mounts (MOUNTS): the stock missile, its stock definition, mass, drag and RCS, on a low shoe. Each mount
sits its missile at its own place fore and aft, ahead of the stowed main wheel; the trough's top is as high as the
intake ducts (over s 6.9 to 7.5) and the aft fuel cells' floor (behind s 7.75) allow, each DUCT_CLEARANCE away. The
trough is the union of every mount's body envelope grown by GAP,
cut out of the skin through build_icarus.blended_ring, so the skin, the fuel cells and the frames all follow it. The
missiles' X fins pass through the skin into the trough's sides, as an F-4's Sparrow fins do; only their bodies and
colliders are kept clear. tools/trough_sections.py draws the sections and measures the fins against the ducts.
"""
import math

from mathutils import Vector
from mathutils.bvhtree import BVHTree

import build_icarus as bi

# The inner blades: span fraction; the hardpoint's chord fraction (forward enough that the twin racks clear the
# bottomed main wheel by Stores rule 12's 0.05 m: 0.074 m here, 0.043 m at 0.37);
# length, which covers the longest inner mount's hooks (the AAM-29, AAM-4, AGM-68 and Genie rails: 0.84 m aft to
# 0.66 m forward of the hardpoint) with the hardpoint centred; depth below the wing's lowest point, shallow so the
# stores ride close to the wing (every store and rack still clears it at rest); and the plan outline's half-width, nose
# and tail, short enough that the rear hook stays under the tail's full width.
PYLONS = {"inner": 0.45, "centre": 0.35, "length": 1.75, "depth": 0.08, "half": 0.053, "nose": 0.10, "tail": 0.12,
          "bury": 0.008, "plug": 0.03}
# The conformal hardpoint (left; the right mirrors it), Blender (x, s, z): x and s held since P0, z raised onto the
# trough floor, INSET above the skin there (Stores rule 9). The floor sits GAP above the highest body.
CONFORMAL = {"x": 0.55, "s": 7.425, "z": -0.188}
INSET = 0.005
# The trough clears each body by CLEAR. It is cut GAP wide: blended_ring samples a section by rays from its centre,
# and a chord between two rays cuts up to 8 mm into a concave cut where it turns (96 rays a ring).
CLEAR, GAP = 0.02, 0.028
DUCT_CLEARANCE = 0.03
# The trough runs on past each missile's ends, narrowing RUNOUT_TAPER per metre, so the skin's ring spacing doesn't cut
# them short.
RUNOUT, RUNOUT_TAPER = 0.15, 0.15
# Half-width of the trough's flat ceiling over the station line, where the shoe bears and the Unity author finds the
# hardpoint: a round top meets the trough's outboard wall close to that line, and a mesh triangulated across that
# corner lands the raycast millimetres off.
FLAT, FLAT_FADE = 0.03, 0.3
# The conformal mounts, by the stock mount each replaces. drop: hardpoint to the body's top at the hardpoint station;
# centre: the missile's own origin forward of the hardpoint; pitch: nose down, degrees (Stores rule 9 allows 3);
# capsule: the stock collider on the missile (centre z, height), resized to the body. body: the envelope radius along
# the missile, nose at +t: the larger of its fin-less body and that capsule (tools/trough_sections.py --profiles).
MOUNTS = {
    "AAM1_single": {
        "key": "baanish_icarus_AAM1_conformal", "missile": "aam1", "drop": 0.033, "centre": -0.15, "pitch": 0.5,
        "capsule": (0.068, 2.83),
        "body": [(-1.367, 0.0), (-1.365, 0.046), (-1.345, 0.063), (1.435, 0.062), (1.455, 0.053), (1.495, 0.016),
                 (1.504, 0.0)]},
    "AAM3_single": {
        "key": "baanish_icarus_AAM3_conformal", "missile": "aam3", "drop": 0.033, "centre": -0.20, "pitch": 0.5,
        "capsule": (0.0, 2.71),
        "body": [(-1.355, 0.0), (-1.193, 0.074), (1.287, 0.074), (1.307, 0.069), (1.327, 0.058), (1.347, 0.034),
                 (1.36, 0.0)]},
    "AAM2_single": {
        "key": "baanish_icarus_AAM2_conformal", "missile": "aam2", "drop": 0.033, "centre": 0.30, "pitch": 0.5,
        "capsule": (-0.13, 3.55),
        "body": [(-1.905, 0.0), (-1.829, 0.112), (-1.789, 0.121), (1.551, 0.118), (1.591, 0.101), (1.611, 0.084),
                 (1.631, 0.058), (1.771, 0.016), (1.799, 0.0)]},
}
SHOE = {"width": 0.04, "length": 0.70, "chamfer": 0.05, "embed": 0.005}  # the low shoe between missile and trough
# Object names the other modules and the Unity author build against.
BLADES = ("pylon_inner_L", "pylon_inner_R")
PLUGS = ("pylon_inner_plug_L", "pylon_inner_plug_R")
# part name -> (parent, dry mass kg); parts.full_tree adds these to its own
TREE = {
    "pylon_inner_L": ("wing_spar_L", 0),
    "pylon_inner_R": ("wing_spar_R", 0),
    "pylon_inner_plug_L": ("wing_spar_L", 0),
    "pylon_inner_plug_R": ("wing_spar_R", 0),
}
# Triangles per component: target and cap (budget.py sums them).
BUDGET = {
    "blades": {"target": 800, "cap": 800, "objects": BLADES},
    "plugs": {"target": 64, "cap": 64, "objects": PLUGS},
}
# The trough's own views, with each conformal store hung, come from tools/trough_sections.py.
CLOSEUPS = {
    "pylon_left": (Vector((3.6, 0.6, -1.3)), Vector((1.85, 2.1, -0.4))),
}


def build(p, mats):
    return pylons(p, mats["body"])


def check(icarus):
    import budget

    problems = budget.over_caps(icarus, BUDGET)
    problems += trough_clearance(icarus)
    problems += collider_overlaps(icarus)
    for name in BLADES + PLUGS:
        if len(icarus.objects[name].data.materials) != 1:
            problems.append("%s carries %d materials, not the skin alone" % (name, len(icarus.objects[name].data.materials)))
    tris = [budget.tris(icarus.objects[n]) for n in PLUGS]
    if not all(14 <= t <= 32 for t in tris):
        problems.append("plugs %s triangles, not 14 to 32" % tris)
    if problems:
        raise ValueError("stations check: " + "; ".join(problems))
    print("stations check PASS: blades %s, plugs %s triangles; trough clear of ducts, fuel cells and colliders" % (
        [budget.tris(icarus.objects[n]) for n in BLADES], tris))


# --- the conformal trough ----------------------------------------------------------------------------------------

def envelope(body, t):
    """Envelope radius at missile coordinate t (0 outside the missile)."""
    if not body[0][0] <= t <= body[-1][0]:
        return 0.0
    for (t0, r0), (t1, r1) in zip(body, body[1:]):
        if t0 <= t <= t1:
            return r0 + (r1 - r0) * (t - t0) / (t1 - t0) if t1 > t0 else max(r0, r1)
    return 0.0


def radius(m):
    return max(r for _, r in m["body"])


def missile_axis(m, s):
    """(t, z) of the missile's axis at station s, left side: t its own coordinate there, z its height."""
    k = math.tan(math.radians(m["pitch"]))
    s_c = CONFORMAL["s"] - m["centre"]
    return s_c - s, CONFORMAL["z"] - m["drop"] - radius(m) + (s - CONFORMAL["s"]) * k


def mount_frame(m):
    """The missile's place in its mount (the hardpoint frame, Unity axes: +y up, +z forward): position, pitch."""
    k = math.tan(math.radians(m["pitch"]))
    return (0.0, -m["drop"] - radius(m) - m["centre"] * k, m["centre"]), m["pitch"]


def export(to_unity):
    """The conformal station and mounts for blockout.json: the left hardpoint (world, Unity axes) and each mount's
    missile place, collider radius and shoe in the mount frame (Unity axes), by the stock mount it replaces."""
    mounts = {}
    for stock, m in MOUNTS.items():
        position, pitch = mount_frame(m)
        mounts[stock] = {"key": m["key"], "missile": m["missile"], "position": [round(c, 5) for c in position],
                         "pitch": pitch, "capsule_radius": round(radius(m), 4), "shoe": shoe(m)}
    return {"hardpoint_unity": to_unity(bi.P(CONFORMAL["s"], CONFORMAL["x"], CONFORMAL["z"])), "mounts": mounts}


def floor_z(s):
    """Height of the trough's top at station s on the station's line, or None where no mount reaches."""
    tops = []
    for m in MOUNTS.values():
        t, a = missile_axis(m, s)
        r = envelope(m["body"], t)
        if r > 0:
            tops.append(a + r + GAP)
    return max(tops) if tops else None


def shoe(m):
    """The shoe's eight corners in the mount frame (Unity axes), bottom four then top four: its foot sunk into the
    missile's top, its top INSET above the trough floor, so it reaches the hardpoint and shows no gap either side."""
    k = math.tan(math.radians(m["pitch"]))
    half, top_half = SHOE["length"] / 2 - SHOE["chamfer"], SHOE["length"] / 2
    w = SHOE["width"] / 2
    bottom = lambda z: -m["drop"] - z * k - SHOE["embed"]
    top = lambda z: floor_z(CONFORMAL["s"] - z) + INSET - CONFORMAL["z"]
    out = [(x, bottom(z), z) for z in (-half, half) for x in (-w, w)]
    out += [(x, top(z), z) for z in (-top_half, top_half) for x in (-w, w)]
    return [tuple(round(c, 5) for c in q) for q in out]


def segment_to_core(c, q, x0, a, f=FLAT):
    """2D distance from the segment c-q to the core: the strip x0 - f to x0 + f running straight down from height a."""
    (cx, cz), (qx, qz) = c, q
    to_core = lambda px, pz: math.hypot(max(x0 - f - px, 0.0, px - x0 - f), max(pz - a, 0.0))
    dx, dz = qx - cx, qz - cz
    for x in (x0 - f, x0 + f):  # the segment crossing either side of the strip below a meets it
        if (cx - x) * (qx - x) <= 0 and cx != qx and cz + dz * (x - cx) / dx <= a:
            return 0.0
    if (cz - a) * (qz - a) <= 0 and cz != qz and abs(cx + dx * (a - cz) / dz - x0) <= f:  # or crossing its top
        return 0.0

    def to_segment(px, pz):
        u = max(0.0, min(1.0, ((px - cx) * dx + (pz - cz) * dz) / (dx * dx + dz * dz or 1.0)))
        return math.hypot(cx + u * dx - px, cz + u * dz - pz)
    return min(to_core(cx, cz), to_core(qx, qz), to_segment(x0 - f, a), to_segment(x0 + f, a))


def carve_shapes(p, s):
    """Fields (x, z) -> negative inside, that build_icarus.blended_ring cuts out of the skin at station s: each
    mount's envelope grown by GAP (round above its axis, straight down below it, both sides), together with what lies
    behind it seen from the ring's centre. blended_ring keeps a ray's outermost crossing, so without that shadow a ray
    through the trough that met the belly again beyond it would bridge the trough's outboard side. Along the shoe the
    round top widens into a flat ceiling FLAT either side of the station line, fading out over FLAT_FADE beyond it: any
    further forward it would bring the trough's inboard corner too close to the forward fuel cell."""
    out = []
    _, zc = bi.fuselage_shapes(p, s)
    reach = abs(s - CONFORMAL["s"]) - SHOE["length"] / 2 - 0.1
    f = FLAT * min(1.0, max(0.0, 1.0 - reach / FLAT_FADE))
    for m in MOUNTS.values():
        t, a = missile_axis(m, s)
        r = max(envelope(m["body"], t + RUNOUT * k / 3) - RUNOUT_TAPER * RUNOUT * abs(k) / 3 for k in range(-3, 4))
        if r <= 0:
            continue
        w = r + GAP
        for side in (1, -1):
            x0 = side * CONFORMAL["x"]
            out.append(lambda x, z, x0=x0, a=a, w=w: segment_to_core((0.0, zc), (x, z), x0, a, f) - w)
    return out


def collider_splits():
    """Planes (point, normal), Blender world space, that no skin collider patch may cross (hulls.groups): the
    trough's centre line each side, and level planes through each body's axis and 45 degrees up its arch, so no
    patch hull spans the trough or cuts the corner of its arch."""
    levels = set()
    for m in MOUNTS.values():
        a = missile_axis(m, CONFORMAL["s"])[1]
        levels |= {round(a, 2), round(a + math.sqrt(0.5) * (radius(m) + GAP), 2)}
    return [(Vector((side * CONFORMAL["x"], 0, 0)), Vector((1, 0, 0))) for side in (1, -1)] + \
        [(Vector((0, 0, z)), Vector((0, 0, 1))) for z in sorted(levels)]


def body_points(m, side, step=0.05):
    """Points round the top half of a mount's envelope, Blender world space, with the envelope radius."""
    out = []
    t0, t1 = m["body"][0][0], m["body"][-1][0]
    s_c = CONFORMAL["s"] - m["centre"]
    n = int((t1 - t0) / step)
    for i in range(n + 1):
        t = t0 + (t1 - t0) * i / n
        s = s_c - t
        _, a = missile_axis(m, s)
        r = envelope(m["body"], t)
        for k in range(9):
            phi = math.pi * k / 8
            out.append(bi.P(s, side * CONFORMAL["x"] + r * math.cos(phi), a + r * math.sin(phi)))
    return out


def tree_of(objs):
    """One BVH over several objects' faces, world space."""
    verts, polys = [], []
    for o in objs:
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [[base + i for i in poly.vertices] for poly in o.data.polygons]
    return BVHTree.FromPolygons(verts, polys)


def trough_clearance(icarus):
    """Every body CLEAR of the skin, and the trough's skin at least DUCT_CLEARANCE from the intake ducts and the
    fuel cells."""
    problems = []
    skins = [o for o in icarus.objects if o.name.startswith("skin_")]
    skin = tree_of(skins)
    inner = tree_of([o for o in icarus.objects if o.name.startswith(("intake_duct", "fuel_"))])
    for key, m in MOUNTS.items():
        for side in (1, -1):
            worst = min((skin.find_nearest(q)[3], q) for q in body_points(m, side))
            if worst[0] < CLEAR:
                problems.append("%s %s body %.3f m from the skin at s %.2f" % (key, "LR"[side < 0], worst[0], worst[1].y + bi.S0))
    trough = []
    for o in skins:
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            fields = carve_shapes(bi.PARAMS, w.y + bi.S0)
            if any(abs(c(w.x, w.z)) < 0.002 for c in fields):
                trough.append(w)
    near = min(((inner.find_nearest(w)[3], w) for w in trough), default=(None, None), key=lambda d: d[0])
    if not trough:
        problems.append("no skin follows the trough")
    elif near[0] < DUCT_CLEARANCE:
        problems.append("trough skin %.3f m from a duct or fuel cell at s %.2f x %.3f z %.3f" % (
            near[0], near[1].y + bi.S0, near[1].x, near[1].z))
    print("stations: trough %d skin vertices, nearest duct or fuel cell %.3f m" % (len(trough), near[0] or 0.0))
    return problems


def capsules(side):
    """Each mount's capsule collider as (key, start, end, radius), Blender world space."""
    out = []
    for key, m in MOUNTS.items():
        cz, h = m["capsule"]
        r = radius(m)
        s_c = CONFORMAL["s"] - m["centre"]
        ends = []
        for t in (cz - (h / 2 - r), cz + (h / 2 - r)):
            _, a = missile_axis(m, s_c - t)
            ends.append(bi.P(s_c - t, side * CONFORMAL["x"], a))
        out.append((key, ends[0], ends[1], r))
    return out


def hull_planes(obj):
    """A convex hull's face planes (point, outward normal), world space."""
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    centre = sum(pts, Vector()) / len(pts)
    planes = []
    for poly in obj.data.polygons:
        c = obj.matrix_world @ poly.center
        n = (obj.matrix_world.to_3x3() @ poly.normal).normalized()
        planes.append((c, n if n.dot(c - centre) > 0 else -n))
    return pts, planes


def collider_overlaps(icarus, limit=0.005):
    """Unity's A14 here: each conformal capsule against every collider hull not on the hardpoint's part
    (fuselage_mid), sampled along its axis: inside a convex hull a point's depth is its nearest face plane, outside
    its distance is the nearest point on the surface."""
    import bpy

    col = bpy.data.collections.get("Colliders")
    if col is None:
        return ["no Colliders collection"]
    bpy.context.view_layer.update()  # the hulls' world matrices follow their parts only after an update
    worst, problems = (0.0, None), []
    hulls = [(o,) + hull_planes(o) + (tree_of([o]),) for o in col.objects
             if o.type == "MESH" and o.parent and o.parent.name != "fuselage_mid"]
    for side in (1, -1):
        for key, a, b, r in capsules(side):
            lo = Vector([min(a[i], b[i]) - r for i in range(3)])
            hi = Vector([max(a[i], b[i]) + r for i in range(3)])
            n = max(2, int((b - a).length / 0.01))
            for o, pts, planes, tree in hulls:
                if any(max(q[i] for q in pts) < lo[i] or min(q[i] for q in pts) > hi[i] for i in range(3)):
                    continue
                depth = 0.0
                for i in range(n + 1):
                    q = a + (b - a) * (i / n)
                    behind = max((q - c).dot(nm) for c, nm in planes)
                    depth = max(depth, r - behind if behind < 0 else r - tree.find_nearest(q)[3])
                if depth > worst[0]:
                    worst = (depth, "%s %s into %s" % (key, "LR"[side < 0], o.name))
                if depth > limit:
                    problems.append("%s %s capsule %.3f m into %s" % (key, "LR"[side < 0], depth, o.name))
    print("stations: conformal capsules, deepest %.3f m (%s)" % (worst[0], worst[1] or "clear"))
    return problems


# --- the inner wing pylons ---------------------------------------------------------------------------------------

def wing_at(w, x):
    """The wing section (s of the leading edge, z of the chord line, chord) at spanwise x, between planform rows."""
    sections = bi.wing_sections(w)
    for (le0, x0, z0, c0), (le1, x1, z1, c1) in zip(sections, sections[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return le0 + t * (le1 - le0), z0 + t * (z1 - z0), c0 + t * (c1 - c0)
    raise ValueError("x %.2f is outside the wing" % x)


def wing_lower(w, s, x):
    """Height of the wing's lower surface at (s, x): the biconvex section of build_icarus.lifting_surface."""
    le, z, chord = wing_at(w, abs(x))
    t = min(1.0, max(0.0, (s - le) / chord))
    return z - bi.airfoil(t) * w["thickness"] * chord


def fixed_box(p, x):
    """Chord fractions (front, back) of the fixed wing box at spanwise x, the same limits build_icarus.box_stations
    leaves between the leading-edge devices and trailing-edge surfaces."""
    gap, cove, front, back = p["surface_gap"], p.get("surface_cove", 0.0), 0.0, 1.0
    for _, a, b, c0, c1 in p["wing_surfaces"]:
        if a - gap / 2 - cove <= x <= b + gap / 2 + cove:
            if c0 == 0.0:
                front = max(front, c1 + gap / 2)
            else:
                back = min(back, c0 - gap / 2)
    return front, back


def outline(front, back, half, nose, tail, n_nose=8, n_tail=4):
    """A blade's plan section, (s, dx) round from the nose: an elliptical nose ahead of front, straight sides, and a
    tail tapering to a 6 mm edge behind back."""
    pts = [(front - nose * math.sin(math.pi * k / n_nose), half * math.cos(math.pi * k / n_nose)) for k in range(n_nose + 1)]
    edge = 0.006
    for k in range(n_tail + 1):
        u = k / n_tail
        pts.append((back + tail * u, -(edge + (half - edge) * math.cos(u * math.pi / 2))))
    for k in range(n_tail, -1, -1):
        u = k / n_tail
        pts.append((back + tail * u, edge + (half - edge) * math.cos(u * math.pi / 2)))
    return pts


def pylons(p, mat):
    """The inner wing pylons and their plugs. The blade's flat lower edge is as long as its root, with the hardpoint
    under the middle of both, and its root flares into the wing in a fillet. The plug is the root footprint, down to
    PYLONS["plug"] below the wing."""
    w, y = p["wing"], PYLONS
    root_x, tip_x = w["planform"][0][1], w["planform"][-1][1]
    parts = []
    for side, suffix in ((1, "_L"), (-1, "_R")):
        x = root_x + y["inner"] * (tip_x - root_x)
        le, z, chord = wing_at(w, x)
        low = z - 0.5 * w["thickness"] * chord
        # The root stays on the fixed box, clear of the moving surfaces and the space they sweep.
        front, back = fixed_box(p, x)
        s0 = le + y["centre"] * chord - y["length"] / 2
        s1 = s0 + y["length"]
        if s0 < le + front * chord or s1 > le + back * chord:
            raise ValueError("pylon_inner%s s %.3f to %.3f leaves the fixed box, s %.3f to %.3f" % (
                suffix, s0, s1, le + front * chord, le + back * chord))
        z_b = low - y["depth"]
        plan = outline(s0 + y["nose"], s1 - y["tail"], y["half"], y["nose"], y["tail"])
        xc = side * x
        on_wing = lambda grow, drop: [bi.P(s, xc + dx * (1 + grow / y["half"]), wing_lower(w, s, xc + dx) - drop)
                                      for s, dx in plan]
        rings = [[bi.P(s, xc + dx, z_b) for s, dx in plan], on_wing(0.0, 0.02), on_wing(0.012, 0.004),
                 on_wing(0.02, -y["bury"])]
        blade = bi.loft("pylon_inner%s" % suffix, rings, cap_back=True, cap_front=True)
        bi.finish(blade, mat, smooth=True)
        blade["role"] = "pylon"
        parts.append(blade)
        # The plug: the root footprint, coarser, from inside the wing to plug metres below it.
        foot = outline(s0 + y["nose"], s1 - y["tail"], y["half"], y["nose"], y["tail"], n_nose=2, n_tail=2)
        plug_rings = [[bi.P(s, xc + dx, wing_lower(w, s, xc + dx) - drop) for s, dx in foot] for drop in (y["plug"], -y["bury"])]
        plug = bi.finish(bi.loft("pylon_inner_plug%s" % suffix, plug_rings, cap_back=True, cap_front=True), mat, smooth=False)
        plug["role"] = "pylon"
        parts.append(plug)
    return parts
