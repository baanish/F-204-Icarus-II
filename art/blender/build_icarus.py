"""F-204 Icarus II exterior generator.

Rebuilds the aircraft from PARAMS into the `Icarus` collection. Run it inside a live Blender session
(exec the file) or headless:

    blender --background --factory-startup --python art/blender/build_icarus.py

Axes follow the export contract the Unity author expects: metres, nose -Y, up +Z, left +X. Positions in PARAMS are
given as station `s` (metres aft of the radome tip), lateral `x` and height `z` above the radome tip.
"""
import math
import os

import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so internals.py imports in a headless run

# Station 0 (the radome tip) sits this far ahead of the origin.
S0 = 8.0

PARAMS = {
    # Fuselage body: (s, half width, z top, z bottom, top exponent). Lower half is a half ellipse whose vertical
    # radius equals the half width; a top exponent below 2 pinches the upper half into the dorsal spine. Intake
    # fairings and the wing-root fillet are blended into these sections (see "blend"), so the outer skin is one surface.
    "fuselage": [
        (0.00, 0.000, 0.03, 0.03, 2.0),
        (0.35, 0.120, 0.14, -0.08, 2.0),
        (1.00, 0.260, 0.34, -0.23, 2.0),
        (2.00, 0.400, 0.59, -0.37, 2.0),
        (3.00, 0.500, 0.72, -0.45, 2.0),
        (4.00, 0.585, 0.86, -0.51, 1.8),
        (4.90, 0.610, 1.00, -0.51, 1.6),
        (6.20, 0.640, 1.04, -0.51, 1.5),
        (8.00, 0.650, 1.04, -0.48, 1.5),
        (10.0, 0.650, 1.06, -0.42, 1.5),
        (12.2, 0.650, 1.07, -0.39, 1.5),
        (13.2, 0.640, 1.02, -0.30, 1.6),
        (14.0, 0.610, 0.94, -0.21, 1.8),  # the boat tail steepens progressively to the nozzle
        (14.6, 0.540, 0.85, -0.11, 1.9),
        (15.0, 0.450, 0.78, -0.04, 2.0),
        (15.2, 0.390, 0.76, -0.02, 2.0),  # a circle just over the nozzle, closed by an end cap
    ],
    "canopy": [  # (s, half width, z top, z bottom)
        (2.32, 0.30, 0.64, 0.50),
        (2.70, 0.34, 0.88, 0.50),
        (3.00, 0.37, 1.04, 0.52),
        (3.35, 0.39, 1.13, 0.55),
        (4.00, 0.39, 1.10, 0.62),
        (4.70, 0.37, 1.07, 0.75),
        (5.10, 0.30, 1.03, 0.85),
    ],
    # Intake fairings: (s, outer half width, z centre, half height). Each is an elliptical lobe whose inner edge sits at
    # intake_inner_x inside the body; the first row is the lip, where the lobe starts and the duct face is drawn.
    "intake": [
        (6.85, 0.955, 0.22, 0.44),
        (7.60, 0.990, 0.22, 0.44),
        (8.60, 0.990, 0.22, 0.43),
        (10.0, 0.940, 0.22, 0.40),
        (11.4, 0.830, 0.22, 0.35),
        (12.6, 0.680, 0.22, 0.26),
        (13.6, 0.090, 0.22, 0.01),  # shrinks to a point inside the body, so the fairing fades with no bulge
    ],
    # With the rows above, a 0.44 m circle at the lip whose centre is buried in the body: it stands 0.31 m proud,
    # a slim profile with the same opening area as a smaller, more protruding intake.
    "intake_inner_x": 0.075,
    "intake_lip_round": 0.15,  # metres over which the lip grows from 90% to full size
    "blend": 0.24,
    # Area-rule waist: the whole cross-section (body, fairings, spine and belly) scales radially by up to depth,
    # a cosine-squared dip over centre_s +/- half_length, so it pinches in plan and in profile. A look only: the
    # game's drag has no cross-section term.
    "area_rule": {"centre_s": 10.8, "half_length": 2.6, "depth": 0.10},  # smooth-union radius between body, intakes and fillets
    "wing_fillet": {"reach": 0.30, "half_thickness": 0.07},  # beyond the body side, along the wing root
    "probe": {"length": 1.15, "radius": 0.022, "base_radius": 0.07, "base_length": 0.40},
    # Two cone angles, like the F-104's "double-shock" centre body: a fine tip, then a steeper base. A full cone
    # sunk into the body side, with a dark bleed slot ring near its base.
    "shock_cone": {"apex_s": 6.15, "break_s": 6.90, "break_r": 0.132, "base_s": 7.40, "radius": 0.30, "x": 0.58,
                   "bleed_s": 7.22},
    # The duct runs from just inside the lip to the engine face, narrowing and turning toward the centreline:
    # (s, centre x, centre z, radius).
    "duct": [(6.86, 0.515, 0.22, 0.386), (7.80, 0.47, 0.24, 0.37), (8.80, 0.38, 0.28, 0.33), (9.60, 0.30, 0.31, 0.30)],
    # Lifting surfaces: list of (s of leading edge, x, z, chord) from root to tip, plus thickness ratio.
    # No wing fence at the crank: considered and left off, since the strake and crank vortices and the leading-edge
    # flaps already keep the outboard panel's flow attached.
    # Cranked arrow: a strake rising from the intake fairing just behind the lip (about 72 degrees), a rounded
    # crank, and a 35 degree outboard panel; trailing edge nearly unswept. The first two rows are buried in the fairing
    # so the wing meets the body without a gap; rows are (s of leading edge, x, trailing edge s) here and expanded
    # with the anhedral below.
    "wing": {
        "planform": [(8.00, 0.58, 12.05), (7.00, 0.92, 12.04), (7.48, 1.10, 12.03), (8.27, 1.40, 12.00),
                     (8.80, 1.60, 11.98), (9.20, 1.75, 11.97), (9.45, 1.93, 11.95), (10.45, 3.40, 11.75)],
        "anhedral_deg": 10.0,
        "root_z": 0.20,
        "thickness": 0.034,
    },
    # The root rows curve the leading edge concavely down into the spine, which is the fin's fillet. The lowest
    # row sits under the tapering tail's top line and ends where the body does, so no gap opens under the fin;
    # the trailing edge ends above the nozzle exit.
    "fin": {
        "sections": [(12.00, 0.0, 0.70, 3.20), (12.25, 0.0, 0.98, 3.40), (12.90, 0.0, 1.30, 2.75),
                     (13.30, 0.0, 1.60, 2.35), (14.68, 0.0, 2.88, 1.00)],
        "thickness": 0.05,
    },
    # Control surfaces cut from the wing and fin: (name, span from, span to, chord fraction from, to). Span is x on
    # the wing, z on the fin; chord fractions are of the local full chord. Each becomes a hinge empty with the
    # surface as its _visible child.
    "wing_surfaces": [
        ("lef_L", 1.95, 3.28, 0.00, 0.16),  # automatic leading-edge flap, outboard of the crank
        ("flap_L", 1.08, 2.02, 0.78, 1.00),
        ("aileron_L", 2.08, 3.28, 0.74, 1.00),
    ],
    "fin_surfaces": [("rudder", 1.15, 2.55, 0.68, 1.00)],
    "surface_gap": 0.012,  # metres between a surface and the box spanwise; a fraction of the local chord chordwise
    # Metres the box's cut-out runs on past each end of its surface: a surface turning on a swept hinge in the
    # drooped wing plane swings its end inboard, through the 6 mm spanwise gap.
    "surface_cove": 0.02,
    # Authored travel in degrees from the built pose, the one source IcarusAuthor.Aero.cs reads (blockout.json,
    # each hinge's deflection_deg): ailerons, rudder and stabilators both ways; flaps and leading-edge flaps droop;
    # the speed brakes open outward.
    "surface_travel": {"aileron": 20, "rudder": 25, "stabilator": 15, "flap": 25, "lef": 20, "speed_brake": 60},
    "stabilator_pivot_s": 15.45,
    # Speed brakes on the aft fuselage sides: s range and the height band of skin they cover; hinged at the front.
    "speed_brake": {"s0": 12.55, "s1": 13.35, "z0": -0.18, "z1": 0.30},
    # Squared off: the trailing edge runs straight across at the root's trailing edge instead of the F-104's V,
    # with a small 45 degree cut at the tip's trailing corner. Left-hand sections; the stabilator is one piece, its
    # sides meeting behind the fin-tip fairing, notch_gap aft of the fairing's tail, and standing just outboard of
    # the fairing beside it, so it pivots clear.
    "stabilator": {
        "sections": [(14.804, 0.07, 2.82, 1.886), (15.342, 1.62, 2.82, 1.348), (15.41, 1.815, 2.82, 1.085)],
        "thickness": 0.045,
        "notch_gap": 0.02,
    },
    # The fin-tip fairing round the stabilator pivot, as on the F-104: a body of revolution about a fore-aft axis at
    # height z, from s0 to s1, hiding the fin tip.
    "fin_fairing": {"z": 2.83, "s0": 14.62, "s1": 15.75, "radius": 0.06},
    "ventral_fin": {
        "sections": [(10.85, 0.0, -0.22, 2.25), (10.95, 0.0, -0.62, 2.05)],  # root buried above the rising belly
        "thickness": 0.05,
    },
    # Iris nozzle: a fixed shroud, then a ring of hinged petals with seals between them. Each petal hangs on its own
    # hinge empty (local X along the hinge) under one gimbal empty, so the plugin can open the iris with afterburner
    # and deflect it for thrust vectoring. The built pose is dry thrust: petals angled inward.
    "nozzle": {"z": 0.37, "shroud_start": 15.0, "ring_s": 15.30, "ring_r": 0.36, "shroud_r": 0.385, "duct_r": 0.33,
               "petals": 16, "petal_length": 0.48, "petal_root_w": 0.141, "petal_tip_w": 0.113,
               "petal_thickness": 0.012, "dry_angle_deg": -9.0, "seal_inset": 0.012},
    # Reference drawings shown as image empties: file, px per metre, pixel of the radome tip, plane.
    "references": {
        "dir": ".cache/reference",
        "top": {"file": "top.png", "px_per_m": 35.8, "nose_px": (55, 130)},
        "side": {"file": "side.png", "px_per_m": 35.5, "nose_px": (27, 127)},
        "front": {"file": "front.png", "px_per_m": 46.5, "centre_px": (159.5, 152)},
    },
}

def wing_sections(w):
    """Planform rows (s_le, x, s_te) to lifting-surface sections (s_le, x, z, chord) with the anhedral applied."""
    x0 = w["planform"][0][1]
    t = math.tan(math.radians(w["anhedral_deg"]))
    return [(le, x, w["root_z"] - (x - x0) * t, te - le) for le, x, te in w["planform"]]


RING = 96  # vertices around a fuselage section; the intakes span only a fraction of each ring
CHORD = 22  # points along each airfoil surface over the full chord; a piece of the chord takes its share, at least 6
SPAN_STEP = 0.4  # most metres between the span stations of a lifting-surface piece


def P(s, x, z):
    return Vector((x, s - S0, z))


# --- interpolation -------------------------------------------------------------------------------------------------

def pchip(xs, ys, x):
    """Monotone cubic interpolation, so stations never overshoot between table rows."""
    n = len(xs)
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    i = max(j for j in range(n - 1) if xs[j] <= x)
    t = (x - xs[i]) / h[i]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]


def resample(table, stations):
    cols = list(zip(*table))
    return [[s] + [pchip(cols[0], col, s) for col in cols[1:]] for s in stations]


def spaced(s0, s1, n, nose_bias=False):
    """n stations from s0 to s1; nose_bias packs them toward s0 for a smooth radome."""
    out = []
    for i in range(n):
        t = i / (n - 1)
        if nose_bias:
            t = 1 - math.cos(t * math.pi / 2)
        out.append(s0 + (s1 - s0) * t)
    return out


# --- mesh builders -------------------------------------------------------------------------------------------------

def superellipse(c, e):
    return math.copysign(abs(c) ** (2.0 / e), c)


def body_ring(s, hw, top, bot, e_top, e_bot=2.0, xc=0.0, zmid=None, count=144):
    """A superellipse section of count points (the canopy's)."""
    zmid = bot + hw if zmid is None else zmid
    zmid = min(zmid, top)
    ring = []
    for k in range(count):
        a = 2 * math.pi * k / count
        c, sn = math.cos(a), math.sin(a)
        e = e_top if sn >= 0 else e_bot
        x = xc + hw * superellipse(c, e)
        z = zmid + (top - zmid if sn >= 0 else zmid - bot) * superellipse(sn, e)
        ring.append(P(s, x, z))
    return ring


def loft(name, rings, tip_front=None, cap_back=False, cap_front=False):
    verts, faces = [], []
    if tip_front is not None:
        verts.append(tip_front)
    base = len(verts)
    n = len(rings[0])
    for r in rings:
        verts.extend(r)
    if tip_front is not None:
        faces += [(0, base + (k + 1) % n, base + k) for k in range(n)]
    for j in range(len(rings) - 1):
        a, b = base + j * n, base + (j + 1) * n
        faces += [(a + k, a + (k + 1) % n, b + (k + 1) % n, b + k) for k in range(n)]
    if cap_back:
        last = base + (len(rings) - 1) * n
        faces.append(tuple(last + k for k in range(n)))
    if cap_front:
        faces.append(tuple(base + k for k in range(n))[::-1])
    return mesh_object(name, verts, faces)


def airfoil(t):
    """Biconvex half thickness at chord fraction t (sharp leading and trailing edges, like the F-104)."""
    return 2.0 * t * (1.0 - t)


def lifting_surface(name, sections, thickness, thick_axis):
    """Sections: (s_le, x, z, chord) root to tip. thick_axis: 'z' for wings, 'x' for a fin."""
    ts = [0.5 * (1 - math.cos(math.pi * i / (CHORD - 1))) for i in range(CHORD)]
    rings = []
    for s_le, x, z, chord in sections:
        upper, lower = [], []
        for t in ts:
            half = airfoil(t) * thickness * chord
            dx, dz = (0.0, half) if thick_axis == "z" else (half, 0.0)
            upper.append(P(s_le + t * chord, x + dx, z + dz))
            lower.append(P(s_le + t * chord, x - dx, z - dz))
        rings.append(upper + lower[-2:0:-1])
    n = len(rings[0])
    verts = [v for r in rings for v in r]
    faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
             for j in range(len(rings) - 1) for k in range(n)]
    faces.append(tuple((len(rings) - 1) * n + k for k in range(n)))
    faces.append(tuple(range(n))[::-1])
    return mesh_object(name, verts, faces)


# --- scene plumbing ------------------------------------------------------------------------------------------------

def collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    for obj in list(col.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    return col


TARGET = None


def mesh_object(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new(name, me)
    TARGET.objects.link(obj)
    return obj


def finish(obj, mat, smooth=True):
    obj.data.materials.append(mat)
    if smooth:
        obj.data.shade_smooth()
        obj.data.set_sharp_from_angle(angle=math.radians(40))
    return obj


# --- parts ---------------------------------------------------------------------------------------------------------

def smin(a, b, k):
    """Polynomial smooth minimum: a union of two fields with a fillet of radius about k."""
    h = max(k - abs(a - b), 0.0) / k
    return min(a, b) - h * h * k * 0.25


def lobe(dx, dz, a, b_top, b_bot, e_top=2.0, e_bot=2.0):
    """Approximate signed distance to a superellipse with separate upper and lower halves."""
    b, e = (b_top, e_top) if dz >= 0 else (b_bot, e_bot)
    q = (abs(dx) / a) ** e + (abs(dz) / b) ** e
    return (q ** (1.0 / e) - 1.0) * min(a, b)


def ramp(s, s0, s1, s2, s3):
    """0 before s0, rising to 1 by s1, falling back to 0 between s2 and s3."""
    if s <= s0 or s >= s3:
        return 0.0
    if s < s1:
        return math.sin(0.5 * math.pi * (s - s0) / (s1 - s0)) ** 2
    if s > s2:
        return math.cos(0.5 * math.pi * (s - s2) / (s3 - s2)) ** 2
    return 1.0


def fuselage_shapes(p, s):
    """The lobes whose smooth union is the outer skin at station s, as (field function, centre z)."""
    hw, top, bot, e_top = [pchip([r[0] for r in p["fuselage"]], [r[i] for r in p["fuselage"]], s) for i in (1, 2, 3, 4)]
    zmid = min(bot + hw, top)
    shapes = [lambda x, z: lobe(x, z - zmid, hw, top - zmid, zmid - bot, e_top)]
    intake = p["intake"]
    if intake[0][0] <= s <= intake[-1][0]:
        _, xo, zc, hh = resample(intake, [s])[0]
        grow = 0.9 + 0.1 * min(1.0, (s - intake[0][0]) / p["intake_lip_round"])
        xi = p["intake_inner_x"]
        a, cx = (xo - xi) / 2 * grow, xi + (xo - xi) / 2
        for side in (1, -1):
            shapes.append(lambda x, z, side=side, a=a, cx=cx, zc=zc, b=hh * grow: lobe(x - side * cx, z - zc, a, b, b))
    (le0, x0, z0, c0), (le1, x1, _, c1) = wing_sections(p["wing"])[:2]
    le_at = le0 + (le1 - le0) * (hw - x0) / (x1 - x0)
    te_at = le0 + c0 + (le1 + c1 - le0 - c0) * (hw - x0) / (x1 - x0)
    f = ramp(s, le_at - 0.1, le_at + 0.6, te_at - 1.2, te_at + 0.4)
    if f > 0:
        wf = p["wing_fillet"]
        a, b = 0.05 + wf["reach"] * f, 0.02 + wf["half_thickness"] * f
        for side in (1, -1):
            # As the fillet fades it also sinks into the body, so the smooth union stops inflating the skin
            # before the lobe is dropped (a lobe resting on the skin would leave a step where it ends).
            cx = hw - 0.05 - 0.5 * (1.0 - f)
            shapes.append(lambda x, z, side=side, a=a, b=b, cx=cx: lobe(x - side * cx, z - z0, a, b, b))
    return shapes, zmid


def blended_ring(p, s):
    shapes, zc = fuselage_shapes(p, s)
    # At the lip the intake meets the body almost sharply, so it reads as a slice of a circle; the fillet fades in
    # behind it.
    behind_lip = s - p["intake"][0][0]
    k = p["blend"] * (0.12 + 0.88 * min(1.0, behind_lip / 1.2)) if behind_lip >= 0 else p["blend"]
    import stations

    carves = stations.carve_shapes(p, s)  # the conformal trough, cut out of the union

    def field(x, z):
        d = shapes[0](x, z)
        for f in shapes[1:]:
            d = smin(d, f(x, z), k)
        for c in carves:
            d = max(d, -c(x, z))
        return d

    ar = p["area_rule"]
    u = (s - ar["centre_s"]) / ar["half_length"]
    squeeze = 1.0 - ar["depth"] * math.cos(0.5 * math.pi * u) ** 2 if abs(u) < 1 else 1.0
    ring = []
    for i in range(RING):
        a = 2 * math.pi * i / RING
        c, sn = math.cos(a), math.sin(a)
        r_out, step, r = 0.0, 0.02, 0.0
        inside = field(0.0, zc) < 0
        while r < 3.0:  # keep the outermost inside-to-outside crossing, so concave fillets resolve
            r_next = r + step
            now = field(r_next * c, zc + r_next * sn) < 0
            if inside and not now:
                lo, hi = r, r_next
                for _ in range(20):
                    mid = 0.5 * (lo + hi)
                    if field(mid * c, zc + mid * sn) < 0:
                        lo = mid
                    else:
                        hi = mid
                r_out = 0.5 * (lo + hi)
            inside, r = now, r_next
        ring.append(P(s, r_out * c * squeeze, zc + r_out * sn * squeeze))
    return ring


def build_fuselage(p, mat, duct_mat):
    table = p["fuselage"]
    lip = p["intake"][0][0]
    stations = (spaced(0.0, 3.0, 14, nose_bias=True)[1:] + spaced(3.0, lip - 0.004, 20)[1:]
                + spaced(lip, lip + 0.6, 8) + spaced(lip + 0.6, table[-1][0], 50)[1:])
    rings = [blended_ring(p, s) for s in stations]
    obj = loft("fuselage", rings, tip_front=P(0.0, 0.0, table[0][2]))  # open at the tail: the nozzle shroud fills it
    finish(obj, mat)
    obj.data.materials.append(duct_mat)
    # The faces between the last ring ahead of the lip and the lip itself would close the intakes; delete them so
    # the openings look into the ducts.
    j = stations.index(lip) - 1
    step = [(Vector((b.x, b.z)) - Vector((a.x, a.z))).length for a, b in zip(rings[j], rings[j + 1])]
    opening = [RING + j * RING + k for k in range(RING) if max(step[k], step[(k + 1) % RING]) > 0.005]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in opening], context="FACES_ONLY")
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def inward_fix(obj, axis_point):
    """Flip the mesh if its first wall face points away from axis_point, so the inside is the visible side."""
    poly = obj.data.polygons[0]
    if poly.normal.dot(axis_point - poly.center) < 0:
        obj.data.flip_normals()


def build_probe(p, mat):
    pr = p["probe"]
    z = p["fuselage"][0][2]
    profile = [(-pr["length"], 0.008), (-pr["length"] + 0.05, pr["radius"]), (-pr["base_length"], pr["radius"]),
               (-0.1, pr["base_radius"] * 0.5), (0.05, pr["base_radius"]), (0.30, pr["base_radius"])]
    rings = [[P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / 24 for k in range(24)]]
             for s, r in profile]
    return finish(loft("probe", rings, tip_front=P(-pr["length"] - 0.02, 0.0, z)), mat)


def section_at(sections, u, axis):
    """Section (s_le, x, z, chord) interpolated at span position u (x on a wing, z on a fin)."""
    key = 1 if axis == "x" else 2
    for a, b in zip(sections, sections[1:]):
        if a[key] <= u <= b[key] + 1e-9:
            t = (u - a[key]) / (b[key] - a[key])
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
    raise ValueError("span position %.3f outside the sections" % u)


def span_stations(sections, axis, u0, u1, breaks=()):
    """Span positions from u0 to u1 (x on a wing, z on a fin): every section row and break between them, so the
    planform's kinks stay exact, with the gaps subdivided to at most SPAN_STEP."""
    key = 1 if axis == "x" else 2
    marks = sorted({u0, u1} | {u for u in [s[key] for s in sections] + list(breaks) if u0 < u < u1})
    out = [u0]
    for a, b in zip(marks, marks[1:]):
        n = max(1, math.ceil((b - a) / SPAN_STEP - 1e-9))
        out += [a + (b - a) * i / n for i in range(1, n + 1)]
    return out


def strip(name, sections, stations, thickness, axis, mats=None, trim_caps=False, count=None, clamp=False):
    """A closed piece of a lifting surface. stations: (u, f0, f1) along the span; each ring spans chord fractions
    f0..f1 of the full-chord airfoil, so neighbouring pieces share one airfoil, with count points a side (by default
    in proportion to the widest span of chord). Two stations at the same u with different fractions make the wall at
    a cutout's end. mats = (skin, trim) finishes the piece: the walls a cut leaves (inside the chord, and at a
    cutout's ends) go on the trim, and the end caps too with trim_caps, so the cove a moving surface opens shows trim,
    not skin. With clamp, every ring samples the full chord and every station's ends, and pulls the points outside its
    own f0..f1 onto those ends, so a ring cut short shares its points with the full rings beside it and one piece
    runs on through the cut."""
    count = count or max(6, round(CHORD * max(f1 - f0 for _, f0, f1 in stations)))
    full = [0.5 * (1 - math.cos(math.pi * i / (count - 1))) for i in range(count)]
    if clamp:
        full = sorted(set(full) | {f for _, f0, f1 in stations for f in (f0, f1)})
    rings = []
    for u, f0, f1 in stations:
        s_le, x, z, chord = section_at(sections, u, axis)
        ts = [min(max(t, f0), f1) for t in full] if clamp else [f0 + (f1 - f0) * t for t in full]
        upper, lower = [], []
        for t in ts:
            half = max(airfoil(t) * thickness * chord, 0.0015)
            d = Vector((0.0, 0.0, half)) if axis == "x" else Vector((half, 0.0, 0.0))
            base = P(s_le + t * chord, x, z)
            upper.append(base + d)
            lower.append(base - d)
        rings.append(upper + lower[::-1])
    n = len(rings[0])
    verts = [v for r in rings for v in r]
    faces, walls = [], []
    for j, ((u, f0, f1), (u_next, _, _)) in enumerate(zip(stations, stations[1:])):
        for k in range(n):
            faces.append((j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k))
            # quad count - 1 is the wall across chord fraction f1, quad n - 1 the wall across f0
            walls.append(u == u_next or (k == count - 1 and f1 < 1.0) or (k == n - 1 and f0 > 0.0))
    faces.append(tuple(range(n))[::-1])
    faces.append(tuple((len(rings) - 1) * n + k for k in range(n)))
    walls += [trim_caps, trim_caps]
    obj = mesh_object(name, verts, faces)
    if mats is not None:
        finish(obj, mats[0])
        obj.data.materials.append(mats[1])
        for poly, wall in zip(obj.data.polygons, walls):
            poly.material_index = 1 if wall else 0
    # Two rings at one u share the chord end their fractions have in common: weld those points, so the wall carries
    # no zero-area faces (the importer drops them and the slot's triangles no longer match the export).
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def box_stations(sections, axis, cuts, gap, cove):
    """Stations for the fixed box of a surface: full chord except where a control surface is cut out, the cut-out
    running cove past the surface's ends."""
    key = 1 if axis == "x" else 2
    u0, u1 = sections[0][key], sections[-1][key]
    reach = gap / 2 + cove
    edges = {c for _, a, b, _, _ in cuts for c in (a - reach, b + reach) if u0 < c < u1}

    def chord_range(u):
        f0, f1 = 0.0, 1.0
        for _, a, b, c0, c1 in cuts:
            if a - reach <= u <= b + reach:
                if c0 == 0.0:
                    f0 = max(f0, c1 + gap / 2)
                else:
                    f1 = min(f1, c0 - gap / 2)
        return f0, f1

    stations = []
    for u in span_stations(sections, axis, u0, u1, edges):
        # at a cut edge the box steps from the chord range on one side to the other's: two rings at one u
        for f in dict.fromkeys([chord_range(u - 1e-6), chord_range(u + 1e-6)]):
            stations.append((u,) + f)
    return stations


def hinge_frame(a, b):
    """Hinge empty matrix: origin at a, X along the hinge a->b, Y as close to aft as the hinge allows.

    Wing hinges run inboard to outboard, so Z is up on the left and down on the right: a positive rotation about X
    raises a left trailing edge and lowers a right one, and droops a right leading-edge flap. The rudder's X runs
    up the fin, so positive moves its trailing edge to the right (-X)."""
    x_axis = (b - a).normalized()
    y_axis = Vector((0.0, 1.0, 0.0))
    y_axis = (y_axis - x_axis * x_axis.dot(y_axis)).normalized()
    z_axis = x_axis.cross(y_axis)
    return Matrix.Translation(a) @ Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()


def hinged(name, mesh_obj, frame, parent=None):
    """Re-express mesh_obj in the hinge frame and hang it from a new hinge empty called name."""
    mesh_obj.name = mesh_obj.data.name = name + "_visible"  # frees the name for the hinge
    hinge = empty(name, frame, parent)
    hinge["hinge_axis"] = "X"
    mesh_obj.data.transform(frame.inverted())
    mesh_obj.parent = hinge
    return [hinge, mesh_obj]


def surface_travel(p, name):
    """The authored travel of a hinged surface, by its name less the side suffix (PARAMS["surface_travel"])."""
    return p["surface_travel"][name[:-2] if name.endswith(("_L", "_R")) else name]


def control_surface(p, name, sections, cut, thickness, axis, gap, mats):
    _, u0, u1, f0, f1 = cut
    u0, u1 = u0 + gap / 2, u1 - gap / 2
    f0 = f0 + gap / 2 if f0 > 0 else f0
    f1 = f1 - gap / 2 if f1 < 1 else f1
    stations = [(u, f0, f1) for u in span_stations(sections, axis, u0, u1)]
    obj = strip(name, sections, stations, thickness, axis, (mats["body"], mats["mechanical"]), trim_caps=True)
    hinge_f = f1 if f0 == 0.0 else f0  # a leading-edge device hinges on its aft edge, the rest on their front edge
    ends = []
    for u in (u0, u1):
        s_le, x, z, chord = section_at(sections, u, axis)
        ends.append(P(s_le + hinge_f * chord, x, z))
    parts = hinged(name, obj, hinge_frame(*ends))
    parts[0]["deflection_deg"] = surface_travel(p, name)
    return parts


def mirror_part(parts):
    """Right-hand twins of left-hand parts, mirrored across x = 0. A twin hinge is rebuilt from the mirrored hinge
    line, so its X still runs inboard to outboard and its frame stays right-handed."""
    flip = Matrix.Scale(-1, 4, (1, 0, 0))
    out = []
    for obj in parts:
        if obj.type == "EMPTY":
            a = obj.matrix_world.translation.copy()
            b = a + obj.matrix_world.col[0].xyz
            twin = empty(obj.name.replace("_L", "_R"), hinge_frame(flip @ a, flip @ b))
            for key in obj.keys():  # hinge_axis, deflection_deg
                twin[key] = obj[key]
            out.append(twin)
    for obj in parts:
        if obj.type != "MESH":
            continue
        twin = obj.copy()
        twin.data = obj.data.copy()
        twin.name = twin.data.name = obj.name.replace("_L", "_R")
        TARGET.objects.link(twin)
        if obj.parent is not None:
            parent = bpy.data.objects[obj.parent.name.replace("_L", "_R")]
            twin.data.transform(parent.matrix_world.inverted() @ flip @ obj.parent.matrix_world)
            twin.parent = parent
        else:
            twin.data.transform(flip)
        twin.data.flip_normals()
        out.append(twin)
    return out


def build_surfaces(p, mats):
    gap = p["surface_gap"]
    wing = wing_sections(p["wing"])
    cuts = p["wing_surfaces"]
    t = p["wing"]["thickness"]
    trimmed = (mats["body"], mats["mechanical"])
    cove = p["surface_cove"]
    left = [strip("wing_L", wing, box_stations(wing, "x", cuts, gap, cove), t, "x", trimmed)]
    for cut in cuts:
        left += control_surface(p, cut[0], wing, cut, t, "x", gap, mats)
    parts = left + mirror_part(left)
    fin, ft = p["fin"]["sections"], p["fin"]["thickness"]
    parts.append(strip("fin", fin, box_stations(fin, "z", p["fin_surfaces"], gap, cove), ft, "z", trimmed))
    for cut in p["fin_surfaces"]:
        parts += control_surface(p, cut[0], fin, cut, ft, "z", gap, mats)
    parts.append(build_fin_fairing(p, mats["body"]))
    vf = p["ventral_fin"]
    parts.append(finish(lifting_surface("ventral_fin", vf["sections"], vf["thickness"], "x"), mats["body"]))
    return parts + build_stabilator(p, mats)


def build_stabilator(p, mats):
    """The all-moving stabilator as one piece, tip to tip, notched round the fin-tip fairing: between the roots the
    chord starts notch_gap behind the fairing's tail."""
    st = p["stabilator"]
    sections = [(s, -x, z, c) for s, x, z, c in reversed(st["sections"])] + st["sections"]
    s_le, root_x, z, chord = st["sections"][0]
    notch = (p["fin_fairing"]["s1"] + st["notch_gap"] - s_le) / chord
    stations = []
    for u in span_stations(sections, "x", -sections[-1][1], sections[-1][1]):
        for f0 in dict.fromkeys([notch if abs(v) < root_x else 0.0 for v in (u - 1e-6, u + 1e-6)]):
            stations.append((u, f0, 1.0))
    obj = strip("stabilator", sections, stations, st["thickness"], "x", (mats["body"], mats["mechanical"]),
                clamp=True)
    parts = hinged("stabilator", obj, Matrix.Translation(P(p["stabilator_pivot_s"], 0.0, z)))
    parts[0]["deflection_deg"] = surface_travel(p, "stabilator")
    return parts


def build_fin_fairing(p, mat):
    """The fin-tip fairing: a round-ended body of revolution round the stabilator pivot, covering the fin tip. It is
    detail of the fin skin and joins that part's mesh (parts.merge_details)."""
    f = p["fin_fairing"]
    zc, r, s0, s1 = f["z"], f["radius"], f["s0"], f["s1"]
    nose, tail = 0.10, 0.10
    profile = [(s0 + nose * (1 - math.cos(math.radians(d))), 0.97 * r * math.sin(math.radians(d))) for d in (25, 50, 70, 90)]
    profile += [(s0 + 0.38, 0.97 * r), (s0 + 0.53, r), (s1 - 0.25, r), (s1 - 0.13, 0.97 * r)]
    profile += [(s1 - tail + tail * math.sin(math.radians(d)), 0.97 * r * math.cos(math.radians(d))) for d in (30, 55, 75)]
    segments = 12
    verts = [P(s0, 0.0, zc), P(s1, 0.0, zc)]
    for s, rad in profile:
        verts += [P(s, rad * math.cos(a), zc + rad * math.sin(a)) for a in [2 * math.pi * k / segments for k in range(segments)]]
    ring = lambda j, k: 2 + j * segments + k % segments
    faces = [(0, ring(0, k + 1), ring(0, k)) for k in range(segments)]
    faces += [(ring(j, k), ring(j, k + 1), ring(j + 1, k + 1), ring(j + 1, k))
              for j in range(len(profile) - 1) for k in range(segments)]
    faces += [(1, ring(len(profile) - 1, k), ring(len(profile) - 1, k + 1)) for k in range(segments)]
    obj = finish(mesh_object("fin_fairing", verts, faces), mat)
    obj["merge_into"] = "fin_skin"
    return obj


def build_speed_brakes(p, mats):
    """Panels lifted 6 mm off the side skin, 3 mm thick, so they clear it shut. Each opens outward on a hinge along
    its front edge, set at the edge's outermost point: the edge follows the round side, and a hinge on its chord
    would swing the middle of the edge into the skin ahead."""
    sb = p["speed_brake"]
    columns = []
    for i in range(6):
        s = sb["s0"] + (sb["s1"] - sb["s0"]) * i / 5
        side = sorted((v for v in blended_ring(p, s) if v.x > 0.05 and sb["z0"] <= v.z <= sb["z1"]), key=lambda v: v.z)
        columns.append([v + Vector((1.0, 0.0, 0.0)) * 0.006 for v in side])
    n = min(len(c) for c in columns)
    columns = [c[:n] for c in columns]
    outer = [v for c in columns for v in c]
    inner = [v - Vector((1.0, 0.0, 0.0)) * 0.003 for v in outer]
    m = len(outer)
    faces = []
    for j in range(len(columns) - 1):
        for k in range(n - 1):
            a, b, c, d = j * n + k, j * n + k + 1, (j + 1) * n + k + 1, (j + 1) * n + k
            faces += [(d, c, b, a), (a + m, b + m, c + m, d + m)]
    obj = finish(mesh_object("speed_brake_L", outer + inner, faces), mats["body"])
    obj.data.materials.append(mats["mechanical"])  # the inner face, seen when open
    for poly in obj.data.polygons:
        poly.material_index = poly.index % 2
    front = columns[0]
    along = (front[-1] - front[0]).normalized()
    out = (Vector((1.0, 0.0, 0.0)) - along * along.x).normalized()
    lift = out * max((q - front[0]).dot(out) for q in front)
    left = hinged("speed_brake_L", obj, hinge_frame(front[0] + lift, front[-1] + lift))
    left[0]["deflection_deg"] = surface_travel(p, "speed_brake_L")
    return left + mirror_part(left)


def empty(name, matrix, parent=None):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = 0.12
    TARGET.objects.link(obj)
    obj.parent = parent
    obj.matrix_world = matrix
    return obj


def build_references(p, repo):
    ref = p["references"]
    col = collection("References")
    folder = os.path.join(repo, ref["dir"])
    placed = []
    for view in ("top", "side", "front"):
        spec = ref[view]
        path = os.path.join(folder, spec["file"])
        if not os.path.exists(path):
            continue
        img = bpy.data.images.load(path, check_existing=True)
        w, h = img.size
        k = spec["px_per_m"]
        emp = bpy.data.objects.new("ref_" + view, None)
        emp.empty_display_type = "IMAGE"
        emp.data = img
        emp.empty_display_size = max(w, h) / k
        emp.empty_image_offset = (-0.5, -0.5)
        emp.color[3] = 0.5
        emp.use_empty_image_alpha = True
        cx, cy = w / 2, h / 2
        if view == "top":
            nx, ny = spec["nose_px"]
            emp.rotation_euler = (0, 0, math.radians(90))
            emp.location = ((cy - ny) / k, -S0 + (cx - nx) / k, -2.5)
        elif view == "side":
            nx, ny = spec["nose_px"]
            emp.rotation_euler = (math.radians(90), 0, math.radians(90))
            emp.location = (-4.0, -S0 + (cx - nx) / k, (ny - cy) / k)
        else:
            ux, uy = spec["centre_px"]
            emp.rotation_euler = (math.radians(90), 0, 0)
            emp.location = ((cx - ux) / k, 10.0, (uy - cy) / k)
        emp.empty_image_side = "FRONT"
        emp.show_empty_image_perspective = False
        col.objects.link(emp)
        placed.append(emp.name)
    return placed


def metrics(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for o in objs:
        if o.type != "MESH":
            continue
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    wing = wing_sections(PARAMS["wing"])
    # Reference area: the exposed panels plus the root chord carried in to the centreline, both sides.
    area = wing[0][3] * wing[0][1]
    for (_, xa, _, ca), (_, xb, _, cb) in zip(wing, wing[1:]):
        area += (ca + cb) / 2 * (xb - xa)
    area *= 2
    sweeps = [round(math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])), 1) for a, b in zip(wing, wing[1:])]
    return {
        "length_m": round(hi.y - lo.y, 3),
        "span_m": round(hi.x - lo.x, 3),
        "height_above_nose_m": round(hi.z, 3),
        "wing_ref_area_m2": round(area, 2),
        "wing_le_sweep_deg": sweeps,
    }


def build(repo=None, overrides=None):
    """Rebuild the aircraft. overrides replaces top-level PARAMS entries for this build only (variant renders)."""
    global TARGET, PARAMS
    base = PARAMS
    if overrides:
        PARAMS = dict(base, **overrides)
    try:
        return _build(repo)
    finally:
        PARAMS = base


# The package modules, in check order. Each carries build(p, mats), check(icarus), a BUDGET (budget.py) and CLOSEUPS
# (review_sheet.py).
MODULES = ("parts", "propulsion", "canopy", "gear", "lights", "stations", "hulls", "cockpit", "uvs")


def modules():
    import importlib

    return [importlib.import_module(name) for name in MODULES]


def _build(repo):
    global TARGET
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    TARGET = collection("Icarus")
    import materials

    mats = materials.build()
    p = PARAMS
    import canopy
    import cockpit
    import gear
    import lights
    import propulsion
    import stations

    fuselage = build_fuselage(p, mats["body"], mats["duct"])
    parts = [fuselage, build_probe(p, mats["body"])]  # the radome part is all skin, probe included
    parts += gear.cut_doors(fuselage)
    parts += canopy.build(p, mats)
    parts += propulsion.build(p, mats)
    parts += build_surfaces(p, mats)
    parts += build_speed_brakes(p, mats)
    parts += gear.build(p, mats)
    parts += lights.build(p, mats)
    parts += stations.build(p, mats)
    import internals  # imports this module back for its helpers, so it loads after them

    internals.build(p, collection("Internals"), mats)
    import parts as part_tree

    tree = part_tree.organise(p, TARGET, bpy.data.collections["Internals"], mats["structure"])
    part_tree.merge_details(TARGET)
    parts += cockpit.build(p, mats)  # hangs from the organised part tree
    bpy.context.view_layer.update()
    import hulls

    hull_count = hulls.build(TARGET)
    part_tree.open_bays(TARGET)  # render meshes only, after the hulls
    import uvs

    uvs.unwrap(TARGET)
    import checks

    checks.fuel_cell_clearance(TARGET)
    checks.internals_inside_skin(TARGET)
    for module in modules():
        module.check(TARGET)
    import budget

    print(budget.report(TARGET))
    refs = build_references(p, repo)
    bpy.context.view_layer.update()  # children's world matrices follow their new parents only after an update
    out = metrics([o for o in TARGET.objects])
    out["parts"] = len(TARGET.objects)
    out["damage_parts"] = len(tree)
    out.update(hull_count)
    tagged = [o for o in TARGET.all_objects if "mass_kg" in o]
    out["fuel_kg"] = round(sum(o.get("fuel_kg", 0.0) for o in TARGET.all_objects), 1)  # tanks and wing spars
    out["dry_mass_kg"] = round(sum(o["mass_kg"] for o in tagged), 1)
    out["references"] = refs
    return out


if __name__ == "__main__":
    # Run as a script this file is __main__, but the other modules import build_icarus: build through that one copy,
    # so TARGET and PARAMS are the ones they read.
    import build_icarus

    print("icarus:", build_icarus.build())
