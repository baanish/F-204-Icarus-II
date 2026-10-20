"""F-240 Icarus II exterior generator.

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
    "surface_gap": 0.012,  # metres between a surface and the box, spanwise and chordwise
    "stabilator_pivot_s": 15.45,
    # Speed brakes on the aft fuselage sides: s range and the height band of skin they cover; hinged at the front.
    "speed_brake": {"s0": 12.55, "s1": 13.35, "z0": -0.18, "z1": 0.30},
    # Squared off: the trailing edge runs straight across at the root's trailing edge instead of the F-104's V,
    # with a small 45 degree cut at the tip's trailing corner.
    "stabilator": {
        "sections": [(14.78, 0.0, 2.82, 1.91), (15.342, 1.62, 2.82, 1.348), (15.41, 1.815, 2.82, 1.085)],
        "thickness": 0.045,
    },
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


RING = 144  # vertices around a fuselage section; the intakes span only a fraction of each ring
CHORD = 24  # points along each airfoil surface


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


def body_ring(s, hw, top, bot, e_top, e_bot=2.0, xc=0.0, zmid=None):
    zmid = bot + hw if zmid is None else zmid
    zmid = min(zmid, top)
    ring = []
    for k in range(RING):
        a = 2 * math.pi * k / RING
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


def material(name, rgba, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.metallic = metallic
    mat.roughness = roughness
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if rgba[3] < 1:
            bsdf.inputs["Alpha"].default_value = rgba[3]
    return mat


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

    def field(x, z):
        d = shapes[0](x, z)
        for f in shapes[1:]:
            d = smin(d, f(x, z), k)
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
    stations = (spaced(0.0, 3.0, 14, nose_bias=True)[1:] + spaced(3.0, lip - 0.004, 30)[1:]
                + spaced(lip, lip + 0.6, 8) + spaced(lip + 0.6, table[-1][0], 70)[1:])
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


def build_ducts(p, duct_mat):
    """Intake ducts, faces pointing inward, from just inside the lip to a capped engine face."""
    rows = resample(p["duct"], spaced(p["duct"][0][0], p["duct"][-1][0], 16))
    parts = []
    for side, name in ((1, "duct_L"), (-1, "duct_R")):
        rings = [[P(s, side * (cx + r * math.cos(a)), cz + r * math.sin(a))
                  for a in [2 * math.pi * k / 48 for k in range(48)]] for s, cx, cz, r in rows]
        obj = loft(name, rings, cap_back=True)
        inward_fix(obj, Vector((side * rows[0][1], rows[0][0] - S0, rows[0][2])))
        parts.append(finish(obj, duct_mat))
    return parts


def build_canopy(p, mat):
    rows = resample(p["canopy"], spaced(p["canopy"][0][0], p["canopy"][-1][0], 24))
    rings = [body_ring(s, hw, top, bot, 2.0, e_bot=4.0, zmid=bot + 0.02) for s, hw, top, bot in rows]
    return finish(loft("canopy", rings, cap_back=True, cap_front=True), mat)


def build_probe(p, mat):
    pr = p["probe"]
    z = p["fuselage"][0][2]
    profile = [(-pr["length"], 0.008), (-pr["length"] + 0.05, pr["radius"]), (-pr["base_length"], pr["radius"]),
               (-0.1, pr["base_radius"] * 0.5), (0.05, pr["base_radius"]), (0.30, pr["base_radius"])]
    rings = [[P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / 24 for k in range(24)]]
             for s, r in profile]
    return finish(loft("probe", rings, tip_front=P(-pr["length"] - 0.02, 0.0, z)), mat)


def build_shock_cones(p, mat, duct_mat):
    sc = p["shock_cone"]
    zc = p["intake"][0][2]
    parts = []
    for side, name in ((1, "shock_cone_L"), (-1, "shock_cone_R")):
        profile = [(sc["apex_s"] + (sc["break_s"] - sc["apex_s"]) * i / 6, sc["break_r"] * i / 6) for i in range(1, 7)]
        profile += [(sc["break_s"] + (sc["base_s"] - sc["break_s"]) * i / 5,
                     sc["break_r"] + (sc["radius"] - sc["break_r"]) * i / 5) for i in range(1, 6)]
        rings = [[P(s, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                  for a in [2 * math.pi * k / RING for k in range(RING)]] for s, r in profile]
        cone = finish(loft(name, rings, tip_front=P(sc["apex_s"], side * sc["x"], zc), cap_back=True), mat)
        parts.append(cone)
        # Bleed slot: a dark band just proud of the cone surface near its base.
        r0 = sc["break_r"] + (sc["radius"] - sc["break_r"]) * (sc["bleed_s"] - sc["break_s"]) / (sc["base_s"] - sc["break_s"])
        band = []
        for ds in (0.0, 0.035):
            r = r0 + (sc["radius"] - sc["break_r"]) * ds / (sc["base_s"] - sc["break_s"]) + 0.003
            band.append([P(sc["bleed_s"] + ds, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                         for a in [2 * math.pi * k / RING for k in range(RING)]])
        slot = loft(name + "_bleed", band)
        if side < 0:
            slot.data.flip_normals()
        parts.append(finish(slot, duct_mat))
    return parts


def section_at(sections, u, axis):
    """Section (s_le, x, z, chord) interpolated at span position u (x on a wing, z on a fin)."""
    key = 1 if axis == "x" else 2
    for a, b in zip(sections, sections[1:]):
        if a[key] <= u <= b[key] + 1e-9:
            t = (u - a[key]) / (b[key] - a[key])
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
    raise ValueError("span position %.3f outside the sections" % u)


def strip(name, sections, stations, thickness, axis):
    """A closed piece of a lifting surface. stations: (u, f0, f1) along the span; each ring spans chord fractions
    f0..f1 of the full-chord airfoil, so neighbouring pieces share one airfoil. Two stations at the same u with
    different fractions make the wall at a cutout's end."""
    rings = []
    for u, f0, f1 in stations:
        s_le, x, z, chord = section_at(sections, u, axis)
        ts = [f0 + (f1 - f0) * 0.5 * (1 - math.cos(math.pi * i / (CHORD - 1))) for i in range(CHORD)]
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
    faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
             for j in range(len(rings) - 1) for k in range(n)]
    faces.append(tuple(range(n))[::-1])
    faces.append(tuple((len(rings) - 1) * n + k for k in range(n)))
    return mesh_object(name, verts, faces)


def box_stations(u0, u1, cuts, gap, step=0.12):
    """Stations for the fixed box of a surface: full chord except where a control surface is cut out."""
    edges = sorted({u0, u1} | {c for _, a, b, _, _ in cuts for c in (a - gap / 2, b + gap / 2) if u0 < c < u1})

    def chord_range(u):
        f0, f1 = 0.0, 1.0
        for _, a, b, c0, c1 in cuts:
            if a - gap / 2 <= u <= b + gap / 2:
                if c0 == 0.0:
                    f0 = max(f0, c1 + gap / 2)
                else:
                    f1 = min(f1, c0 - gap / 2)
        return f0, f1

    stations = []
    for a, b in zip(edges, edges[1:]):
        mid = chord_range(0.5 * (a + b))
        count = max(2, int(math.ceil((b - a) / step)) + 1)
        stations += [(a + (b - a) * i / (count - 1),) + mid for i in range(count)]
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


def control_surface(name, sections, cut, thickness, axis, gap, mat):
    _, u0, u1, f0, f1 = cut
    u0, u1 = u0 + gap / 2, u1 - gap / 2
    f0 = f0 + gap / 2 if f0 > 0 else f0
    f1 = f1 - gap / 2 if f1 < 1 else f1
    stations = [(u0 + (u1 - u0) * i / 8, f0, f1) for i in range(9)]
    obj = finish(strip(name, sections, stations, thickness, axis), mat)
    hinge_f = f1 if f0 == 0.0 else f0  # a leading-edge device hinges on its aft edge, the rest on their front edge
    ends = []
    for u in (u0, u1):
        s_le, x, z, chord = section_at(sections, u, axis)
        ends.append(P(s_le + hinge_f * chord, x, z))
    return hinged(name, obj, hinge_frame(*ends))


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
            twin["hinge_axis"] = "X"
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


def build_surfaces(p, mat):
    gap = p["surface_gap"]
    wing = wing_sections(p["wing"])
    cuts = p["wing_surfaces"]
    t = p["wing"]["thickness"]
    left = [finish(strip("wing_L", wing, box_stations(wing[0][1], wing[-1][1], cuts, gap), t, "x"), mat)]
    for cut in cuts:
        left += control_surface(cut[0], wing, cut, t, "x", gap, mat)
    parts = left + mirror_part(left)
    fin, ft = p["fin"]["sections"], p["fin"]["thickness"]
    parts.append(finish(strip("fin", fin, box_stations(fin[0][2], fin[-1][2], p["fin_surfaces"], gap), ft, "z"), mat))
    for cut in p["fin_surfaces"]:
        parts += control_surface(cut[0], fin, cut, ft, "z", gap, mat)
    vf = p["ventral_fin"]
    parts.append(finish(lifting_surface("ventral_fin", vf["sections"], vf["thickness"], "x"), mat))
    st = p["stabilator"]["sections"]
    stab = finish(lifting_surface("stabilator_L", st, p["stabilator"]["thickness"], "z"), mat)
    left = hinged("stabilator_L", stab, Matrix.Translation(P(p["stabilator_pivot_s"], 0.0, st[0][2])))
    return parts + left + mirror_part(left)


def build_speed_brakes(p, mat):
    """Panels lifted 6 mm off the side skin, hinged on their front edge to open outward."""
    sb = p["speed_brake"]
    columns = []
    for i in range(6):
        s = sb["s0"] + (sb["s1"] - sb["s0"]) * i / 5
        side = sorted((v for v in blended_ring(p, s) if v.x > 0.05 and sb["z0"] <= v.z <= sb["z1"]), key=lambda v: v.z)
        columns.append([v + Vector((1.0, 0.0, 0.0)) * 0.006 for v in side])
    n = min(len(c) for c in columns)
    columns = [c[:n] for c in columns]
    outer = [v for c in columns for v in c]
    inner = [v - Vector((1.0, 0.0, 0.0)) * 0.012 for v in outer]
    m = len(outer)
    faces = []
    for j in range(len(columns) - 1):
        for k in range(n - 1):
            a, b, c, d = j * n + k, j * n + k + 1, (j + 1) * n + k + 1, (j + 1) * n + k
            faces += [(d, c, b, a), (a + m, b + m, c + m, d + m)]
    obj = finish(mesh_object("speed_brake_L", outer + inner, faces), mat)
    front = columns[0]
    left = hinged("speed_brake_L", obj, hinge_frame(front[0], front[-1]))
    return left + mirror_part(left)


def ring_points(s, r, z, n=RING):
    return [P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / n for k in range(n)]]


def plate(name, root_w, tip_w, length, thickness):
    """A tapered plate in hinge space: X along the hinge, Y aft, Z outward; the hinge line is the root edge."""
    hw0, hw1, t = root_w / 2, tip_w / 2, thickness
    verts = [(-hw0, 0, 0), (hw0, 0, 0), (hw1, length, 0), (-hw1, length, 0),
             (-hw0, 0, -t), (hw0, 0, -t), (hw1, length, -t), (-hw1, length, -t)]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    obj = bpy.data.objects.new(name, me)
    TARGET.objects.link(obj)
    return obj


def empty(name, matrix, parent=None):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = 0.12
    TARGET.objects.link(obj)
    obj.parent = parent
    obj.matrix_world = matrix
    return obj


def nozzle_hinge_matrix(p, kind, i, open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """World matrix of one petal or seal hinge. Opening adds to every petal; vectoring tilts the exit: a petal at
    ring angle phi gains -pitch*sin(phi) - yaw*cos(phi), so a positive pitch points the exit down (nose-up moment)."""
    n = p["nozzle"]
    count = n["petals"]
    phi = 2 * math.pi * i / count + (math.pi / count if kind == "seal" else 0.0)
    radial = Vector((math.cos(phi), 0.0, math.sin(phi)))
    # X runs clockwise round the ring seen from behind, so X, aft and outward make a right-handed frame; a positive
    # rotation about X closes the petal.
    hinge_x = Vector((math.sin(phi), 0.0, -math.cos(phi)))
    basis = Matrix((hinge_x, Vector((0.0, 1.0, 0.0)), radial)).transposed().to_4x4()
    inset = n["seal_inset"] if kind == "seal" else 0.0
    hinge_at = P(n["ring_s"], 0.0, n["z"]) + radial * (n["ring_r"] - inset)
    angle = n["dry_angle_deg"] + open_deg - pitch_deg * math.sin(phi) - yaw_deg * math.cos(phi)
    return Matrix.Translation(hinge_at) @ basis @ Matrix.Rotation(math.radians(-angle), 4, "X")


def pose_nozzle(open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """Pose the built nozzle, the way the plugin will drive it in game."""
    for kind in ("petal", "seal"):
        for i in range(PARAMS["nozzle"]["petals"]):
            hinge = bpy.data.objects["nozzle_%s_%02d" % (kind, i)]
            hinge.matrix_world = nozzle_hinge_matrix(PARAMS, kind, i, open_deg, pitch_deg, yaw_deg)


def build_nozzle(p, mat, duct_mat):
    n = p["nozzle"]
    z, s_ring, r = n["z"], n["ring_s"], n["ring_r"]
    petal_mat = material("Icarus_Petal", (0.46, 0.44, 0.42, 1.0), 0.85, 0.3)
    seal_mat = material("Icarus_Seal", (0.27, 0.26, 0.25, 1.0), 0.85, 0.4)
    shroud = loft("nozzle_shroud", [ring_points(n["shroud_start"], n["shroud_r"], z), ring_points(s_ring, n["shroud_r"], z),
                                   ring_points(s_ring, n["duct_r"], z), ring_points(n["shroud_start"], n["duct_r"], z)],
                  cap_back=True)
    finish(shroud, mat)
    shroud.data.materials.append(duct_mat)
    shroud.data.polygons[-1].material_index = 1  # engine face up the duct
    gimbal = empty("nozzle_vector", Matrix.Translation(P(s_ring, 0.0, z)))
    parts = [shroud, gimbal]
    count = n["petals"]
    for kind, w0, w1 in (("petal", n["petal_root_w"], n["petal_tip_w"]),
                         ("seal", n["petal_root_w"] * 0.7, n["petal_tip_w"] * 0.7)):
        for i in range(count):
            name = "nozzle_%s_%02d" % (kind, i)
            hinge = empty(name, nozzle_hinge_matrix(p, kind, i), parent=gimbal)
            hinge["hinge_axis"] = "X"
            vis = plate(name + "_visible", w0, w1, n["petal_length"], n["petal_thickness"])
            vis.parent = hinge
            vis.data.materials.append(petal_mat if kind == "petal" else seal_mat)
            parts += [hinge, vis]
    return parts


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


def _build(repo):
    global TARGET
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    TARGET = collection("Icarus")
    body = material("Icarus_Body", (0.56, 0.57, 0.59, 1.0), 1.0, 0.32)  # bare steel for the blockout
    glass = material("Icarus_Glass", (0.10, 0.16, 0.22, 0.6), 0.0, 0.05)
    duct = material("Icarus_Duct", (0.02, 0.02, 0.02, 1.0), 0.0, 0.8)
    metal = material("Icarus_Nozzle", (0.25, 0.22, 0.20, 1.0), 0.9, 0.35)
    p = PARAMS
    parts = [build_fuselage(p, body, duct), build_canopy(p, glass), build_probe(p, metal)]
    parts += build_nozzle(p, metal, duct)
    parts += build_shock_cones(p, body, duct)
    parts += build_ducts(p, duct)
    parts += build_surfaces(p, body)
    parts += build_speed_brakes(p, body)
    import internals  # imports this module back for its helpers, so it loads after them

    inner_mats = {
        "fuel_tank": material("Icarus_Int_Fuel", (0.85, 0.55, 0.12, 1.0), 0.0, 0.6),
        "engine": material("Icarus_Int_Engine", (0.30, 0.28, 0.26, 1.0), 0.9, 0.4),
        "structure": material("Icarus_Int_Structure", (0.70, 0.72, 0.74, 1.0), 0.6, 0.5),
        "avionics": material("Icarus_Int_Avionics", (0.20, 0.45, 0.30, 1.0), 0.1, 0.6),
        "radar": material("Icarus_Int_Avionics", (0.20, 0.45, 0.30, 1.0), 0.1, 0.6),
        "cockpit": material("Icarus_Int_Cockpit", (0.32, 0.33, 0.35, 1.0), 0.2, 0.6),
        "gear_bay": material("Icarus_Int_Bay", (0.10, 0.10, 0.11, 1.0), 0.0, 0.8),
    }
    internals.build(p, collection("Internals"), inner_mats)
    import parts as part_tree

    tree = part_tree.organise(p, TARGET, bpy.data.collections["Internals"], inner_mats["structure"])
    bpy.context.view_layer.update()
    import hulls

    hull_count = hulls.build(TARGET)
    import checks

    checks.fuel_cell_clearance(TARGET)
    checks.internals_inside_skin(TARGET)
    refs = build_references(p, repo)
    bpy.context.view_layer.update()  # children's world matrices follow their new parents only after an update
    out = metrics([o for o in TARGET.objects])
    out["parts"] = len(TARGET.objects)
    out["damage_parts"] = len(tree)
    out.update(hull_count)
    tagged = [o for o in TARGET.all_objects if "mass_kg" in o]
    out["fuel_kg"] = round(sum(o.get("fuel_kg", 0.0) for o in tagged if o.get("role") == "fuel_tank"), 1)
    out["dry_mass_kg"] = round(sum(o["mass_kg"] for o in tagged), 1)
    out["references"] = refs
    return out


if __name__ == "__main__":
    result = build()
    print("icarus:", result)
