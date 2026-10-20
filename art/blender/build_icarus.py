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
    # Fuselage body without intakes or canopy: (s, half width, z top, z bottom, top exponent).
    # Lower half is a half ellipse whose vertical radius equals the half width; the top exponent below 2 pinches the
    # upper half into the dorsal spine.
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
        (15.2, 0.540, 0.80, -0.03, 2.0),
        (15.62, 0.420, 0.75, 0.00, 2.0),
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
    # Intake pods: (s, outer half width, z centre, half height). Inner face sits inside the body at intake_inner_x.
    "intake": [
        (6.85, 1.06, 0.22, 0.42),
        (7.60, 1.12, 0.22, 0.42),
        (8.60, 1.12, 0.22, 0.40),
        (10.0, 1.04, 0.22, 0.36),
        (11.4, 0.90, 0.22, 0.30),
        (12.6, 0.70, 0.22, 0.22),
    ],
    "intake_inner_x": 0.58,
    "shock_cone": {"apex_s": 6.38, "base_s": 7.30, "radius": 0.24},
    # Lifting surfaces: list of (s of leading edge, x, z, chord) from root to tip, plus thickness ratio.
    "wing": {
        "sections": [(8.55, 0.58, 0.20, 3.58), (9.95, 3.345, 0.20 - 2.765 * math.tan(math.radians(10)), 1.46)],
        "thickness": 0.034,
    },
    "fin": {
        "sections": [(12.40, 0.0, 1.00, 3.60), (14.70, 0.0, 2.80, 1.00)],
        "thickness": 0.05,
    },
    "stabilator": {
        "sections": [(14.78, 0.0, 2.82, 1.91), (15.41, 1.815, 2.82, 0.59)],
        "thickness": 0.045,
    },
    "nozzle": {"s_start": 15.25, "s_end": 15.85, "z": 0.37, "radius": 0.37, "lip": 0.025},
    # Reference drawings shown as image empties: file, px per metre, pixel of the radome tip, plane.
    "references": {
        "dir": ".cache/reference",
        "top": {"file": "top.png", "px_per_m": 35.8, "nose_px": (55, 130)},
        "side": {"file": "side.png", "px_per_m": 35.5, "nose_px": (27, 127)},
        "front": {"file": "front.png", "px_per_m": 46.5, "centre_px": (159.5, 152)},
    },
}

RING = 48  # vertices around a fuselage section
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

def build_fuselage(p, mat):
    table = p["fuselage"]
    stations = spaced(0.0, 3.0, 14, nose_bias=True)[1:] + spaced(3.0, table[-1][0], 60)[1:]
    rings = [body_ring(s, hw, top, bot, e) for s, hw, top, bot, e in resample(table, stations)]
    return finish(loft("fuselage", rings, tip_front=P(0.0, 0.0, table[0][2])), mat)


def build_canopy(p, mat):
    rows = resample(p["canopy"], spaced(p["canopy"][0][0], p["canopy"][-1][0], 24))
    rings = [body_ring(s, hw, top, bot, 2.0, e_bot=4.0, zmid=bot + 0.02) for s, hw, top, bot in rows]
    return finish(loft("canopy", rings, cap_back=True), mat)


def build_intakes(p, mat, duct_mat):
    xi = p["intake_inner_x"]
    rows = resample(p["intake"], spaced(p["intake"][0][0], p["intake"][-1][0], 30))
    rings = []
    for s, xo, zc, hh in rows:
        hw = (xo - xi) / 2
        rings.append(body_ring(s, hw, zc + hh, zc - hh, 2.6, e_bot=2.6, xc=xi + hw, zmid=zc))
    left = finish(loft("intake_L", rings), mat)
    lip = finish(loft("intake_L_duct", [[v + Vector((0, 0.06, 0)) for v in rings[0]]], cap_back=True), duct_mat, smooth=False)
    sc = p["shock_cone"]
    cone_rings = []
    for i in range(1, 12):
        s = sc["apex_s"] + (sc["base_s"] - sc["apex_s"]) * i / 11
        r = sc["radius"] * i / 11
        zc = rows[0][2]
        cone_rings.append([P(s, xi + 0.04 + r * max(0.0, math.cos(a)), zc + r * math.sin(a))
                           for a in [2 * math.pi * k / RING for k in range(RING)]])
    cone = finish(loft("shock_cone_L", cone_rings, tip_front=P(sc["apex_s"], xi + 0.04, rows[0][2])), mat)
    parts = [left, lip, cone]
    for obj in parts:
        twin = obj.copy()
        twin.data = obj.data.copy()
        twin.name = obj.name.replace("_L", "_R")
        twin.data.name = twin.name
        TARGET.objects.link(twin)
        mirror_x(twin)
    return parts


def build_surfaces(p, mat):
    wing = finish(lifting_surface("wing_L", p["wing"]["sections"], p["wing"]["thickness"], "z"), mat)
    wing_r = finish(mirror_x(lifting_surface("wing_R", p["wing"]["sections"], p["wing"]["thickness"], "z")), mat)
    fin = finish(lifting_surface("fin", p["fin"]["sections"], p["fin"]["thickness"], "x"), mat)
    st = p["stabilator"]["sections"]
    stab_l = finish(lifting_surface("stabilator_L", st, p["stabilator"]["thickness"], "z"), mat)
    stab_r = finish(mirror_x(lifting_surface("stabilator_R", st, p["stabilator"]["thickness"], "z")), mat)
    return [wing, wing_r, fin, stab_l, stab_r]


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
    parts = [build_fuselage(p, body), build_canopy(p, glass), build_nozzle(p, metal)]
    parts += build_intakes(p, body, duct)
    parts += build_surfaces(p, body)
    refs = build_references(p, repo)
    out = metrics([o for o in TARGET.objects])
    out["parts"] = len(TARGET.objects)
    out["references"] = refs
    return out


if __name__ == "__main__":
    result = build()
    print("icarus:", result)
