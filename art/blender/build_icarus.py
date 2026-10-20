"""F-240 Icarus II exterior generator.

Rebuilds the aircraft from PARAMS into the `Icarus` collection. Run it inside a live Blender session
(exec the file) or headless:

    blender --background --factory-startup --python art/blender/build_icarus.py

Axes follow the export contract the Unity author expects: metres, nose -Y, up +Z, left +X. Positions in PARAMS are
given as station `s` (metres aft of the radome tip), lateral `x` and height `z` above the radome tip.
"""
import math
import os

import bpy
from mathutils import Matrix, Vector

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
        (14.2, 0.620, 0.92, -0.20, 1.8),
        (15.0, 0.560, 0.82, -0.05, 2.0),
        (15.45, 0.450, 0.76, -0.01, 2.0),
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
    # Intake fairings: (s, outer half width, z centre, half height). Each is a rounded lobe whose inner edge sits at
    # intake_inner_x inside the body; the first row is the lip, where the lobe starts and the duct face is drawn.
    "intake": [
        (6.85, 1.06, 0.22, 0.42),
        (7.60, 1.12, 0.22, 0.42),
        (8.60, 1.12, 0.22, 0.40),
        (10.0, 1.04, 0.22, 0.36),
        (11.4, 0.90, 0.22, 0.30),
        (12.6, 0.70, 0.22, 0.22),
        (14.2, 0.46, 0.22, 0.12),  # fully inside the body, so the fairing fades out without a step
    ],
    "intake_inner_x": 0.40,
    "intake_lip_round": 0.15,  # metres over which the lip grows from 90% to full size
    "blend": 0.24,  # smooth-union radius between body, intakes and fillets
    "wing_fillet": {"reach": 0.30, "half_thickness": 0.07},  # beyond the body side, along the wing root
    "probe": {"length": 1.15, "radius": 0.022, "base_radius": 0.07, "base_length": 0.40},
    "shock_cone": {"apex_s": 6.38, "base_s": 7.30, "radius": 0.26, "x": 0.63},
    # Lifting surfaces: list of (s of leading edge, x, z, chord) from root to tip, plus thickness ratio.
    "wing": {
        "sections": [(8.55, 0.58, 0.20, 3.58), (9.95, 3.345, 0.20 - 2.765 * math.tan(math.radians(10)), 1.46)],
        "thickness": 0.034,
    },
    # The root rows curve the leading edge concavely down into the spine, which is the fin's fillet.
    "fin": {
        "sections": [(12.25, 0.0, 0.98, 3.75), (12.90, 0.0, 1.30, 3.10), (13.30, 0.0, 1.60, 2.70),
                     (14.68, 0.0, 2.88, 1.00)],
        "thickness": 0.05,
    },
    "stabilator": {
        "sections": [(14.78, 0.0, 2.82, 1.91), (15.41, 1.815, 2.82, 0.59)],
        "thickness": 0.045,
    },
    "ventral_fin": {
        "sections": [(10.85, 0.0, -0.36, 2.25), (10.95, 0.0, -0.62, 2.05)],
        "thickness": 0.05,
    },
    "nozzle": {"s_start": 15.05, "s_end": 15.55, "z": 0.37, "radius": 0.37, "lip": 0.025},
    # Reference drawings shown as image empties: file, px per metre, pixel of the radome tip, plane.
    "references": {
        "dir": ".cache/reference",
        "top": {"file": "top.png", "px_per_m": 35.8, "nose_px": (55, 130)},
        "side": {"file": "side.png", "px_per_m": 35.5, "nose_px": (27, 127)},
        "front": {"file": "front.png", "px_per_m": 46.5, "centre_px": (159.5, 152)},
    },
}

RING = 72  # vertices around a fuselage section
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


def loft(name, rings, tip_front=None, cap_back=False):
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


def mirror_x(obj):
    obj.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    obj.data.flip_normals()
    return obj


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
    (le0, x0, z0, c0), (le1, x1, _, c1) = p["wing"]["sections"][:2]
    le_at = le0 + (le1 - le0) * (hw - x0) / (x1 - x0)
    te_at = le0 + c0 + (le1 + c1 - le0 - c0) * (hw - x0) / (x1 - x0)
    f = ramp(s, le_at - 0.1, le_at + 0.6, te_at - 0.8, te_at + 0.05)
    if f > 0:
        wf = p["wing_fillet"]
        a, b = 0.05 + wf["reach"] * f, 0.02 + wf["half_thickness"] * f
        for side in (1, -1):
            shapes.append(lambda x, z, side=side, a=a, b=b, cx=hw - 0.05: lobe(x - side * cx, z - z0, a, b, b))
    return shapes, zmid


def blended_ring(p, s):
    shapes, zc = fuselage_shapes(p, s)
    k = p["blend"]

    def field(x, z):
        d = shapes[0](x, z)
        for f in shapes[1:]:
            d = smin(d, f(x, z), k)
        return d

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
        ring.append(P(s, r_out * c, zc + r_out * sn))
    return ring


def build_fuselage(p, mat, duct_mat):
    table = p["fuselage"]
    lip = p["intake"][0][0]
    stations = (spaced(0.0, 3.0, 14, nose_bias=True)[1:] + spaced(3.0, lip - 0.004, 30)[1:]
                + spaced(lip, lip + 0.6, 8) + spaced(lip + 0.6, table[-1][0], 70)[1:])
    rings = [blended_ring(p, s) for s in stations]
    obj = loft("fuselage", rings, tip_front=P(0.0, 0.0, table[0][2]))
    finish(obj, mat)
    obj.data.materials.append(duct_mat)
    # The faces between the last ring ahead of the lip and the lip itself are the intake openings.
    j = stations.index(lip) - 1
    for k in range(RING):
        a, b = rings[j][k], rings[j + 1][k]
        if (Vector((b.x, b.z)) - Vector((a.x, a.z))).length > 0.03:
            obj.data.polygons[RING + j * RING + k].material_index = 1
    return obj


def build_canopy(p, mat):
    rows = resample(p["canopy"], spaced(p["canopy"][0][0], p["canopy"][-1][0], 24))
    rings = [body_ring(s, hw, top, bot, 2.0, e_bot=4.0, zmid=bot + 0.02) for s, hw, top, bot in rows]
    return finish(loft("canopy", rings, cap_back=True), mat)


def build_probe(p, mat):
    pr = p["probe"]
    z = p["fuselage"][0][2]
    profile = [(-pr["length"], 0.008), (-pr["length"] + 0.05, pr["radius"]), (-pr["base_length"], pr["radius"]),
               (-0.1, pr["base_radius"] * 0.5), (0.05, pr["base_radius"]), (0.30, pr["base_radius"])]
    rings = [[P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / 24 for k in range(24)]]
             for s, r in profile]
    return finish(loft("probe", rings, tip_front=P(-pr["length"] - 0.02, 0.0, z)), mat)


def build_shock_cones(p, mat):
    sc = p["shock_cone"]
    zc = p["intake"][0][2]
    parts = []
    for side, name in ((1, "shock_cone_L"), (-1, "shock_cone_R")):
        rings = []
        for i in range(1, 12):
            s = sc["apex_s"] + (sc["base_s"] - sc["apex_s"]) * i / 11
            r = sc["radius"] * i / 11
            rings.append([P(s, side * (sc["x"] + r * max(0.0, math.cos(a))), zc + r * math.sin(a))
                          for a in [2 * math.pi * k / RING for k in range(RING)]])
        parts.append(finish(loft(name, rings, tip_front=P(sc["apex_s"], side * sc["x"], zc)), mat))
    return parts


def build_surfaces(p, mat):
    wing = finish(lifting_surface("wing_L", p["wing"]["sections"], p["wing"]["thickness"], "z"), mat)
    wing_r = finish(mirror_x(lifting_surface("wing_R", p["wing"]["sections"], p["wing"]["thickness"], "z")), mat)
    fin = finish(lifting_surface("fin", p["fin"]["sections"], p["fin"]["thickness"], "x"), mat)
    ventral = finish(lifting_surface("ventral_fin", p["ventral_fin"]["sections"], p["ventral_fin"]["thickness"], "x"), mat)
    st = p["stabilator"]["sections"]
    stab_l = finish(lifting_surface("stabilator_L", st, p["stabilator"]["thickness"], "z"), mat)
    stab_r = finish(mirror_x(lifting_surface("stabilator_R", st, p["stabilator"]["thickness"], "z")), mat)
    return [wing, wing_r, fin, ventral, stab_l, stab_r]


def build_nozzle(p, mat):
    n = p["nozzle"]
    rings = []
    for s, r in [(n["s_start"], n["radius"]), (n["s_end"], n["radius"] * 1.02),
                 (n["s_end"], n["radius"] - n["lip"]), (n["s_start"] + 0.2, n["radius"] - n["lip"] * 2)]:
        rings.append([P(s, r * math.cos(a), n["z"] + r * math.sin(a))
                      for a in [2 * math.pi * k / RING for k in range(RING)]])
    return finish(loft("nozzle", rings, cap_back=True), mat)


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
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    wing = PARAMS["wing"]["sections"]
    # Reference area: trapezoid extended to the centreline along the leading and trailing edges.
    (s0, x0, _, c0), (s1, x1, _, c1) = wing
    le_slope = (s1 - s0) / (x1 - x0)
    te_slope = ((s1 + c1) - (s0 + c0)) / (x1 - x0)
    root_c = (s0 + c0 - te_slope * x0) - (s0 - le_slope * x0)
    area = (root_c + c1) * x1
    return {
        "length_m": round(hi.y - lo.y, 3),
        "span_m": round(hi.x - lo.x, 3),
        "height_above_nose_m": round(hi.z, 3),
        "wing_ref_area_m2": round(area, 2),
    }


def build(repo=None):
    global TARGET
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    TARGET = collection("Icarus")
    body = material("Icarus_Body", (0.62, 0.64, 0.66, 1.0), 0.3, 0.45)
    glass = material("Icarus_Glass", (0.10, 0.16, 0.22, 0.6), 0.0, 0.05)
    duct = material("Icarus_Duct", (0.02, 0.02, 0.02, 1.0), 0.0, 0.8)
    metal = material("Icarus_Nozzle", (0.25, 0.22, 0.20, 1.0), 0.9, 0.35)
    p = PARAMS
    parts = [build_fuselage(p, body, duct), build_canopy(p, glass), build_nozzle(p, metal), build_probe(p, metal)]
    parts += build_shock_cones(p, body)
    parts += build_surfaces(p, body)
    refs = build_references(p, repo)
    out = metrics([o for o in TARGET.objects])
    out["parts"] = len(TARGET.objects)
    out["references"] = refs
    return out


if __name__ == "__main__":
    result = build()
    print("icarus:", result)
