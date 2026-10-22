"""Intakes and the iris nozzle: the shock cones with their bleed bands, the ducts to the engine face, the nozzle
shroud and its hinged petals and seals.

The nozzle is a fixed shroud, then a ring of hinged petals with seals between them. Each petal hangs on its own hinge
empty (local X along the hinge) under one gimbal empty, so the plugin can open the iris with afterburner and deflect
it for thrust vectoring. The built pose is dry thrust: petals angled inward.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi

# Triangles per component: target and cap (budget.py sums them).
BUDGET = {
    "intake_L": {"target": 3500, "cap": 4600, "objects": ("intake_duct_L",)},
    "intake_R": {"target": 3500, "cap": 4600, "objects": ("intake_duct_R",)},
    "nozzle": {"target": 3200, "cap": 3900, "objects": ("nozzle", "nozzle_petal_", "nozzle_seal_")},
}
# The reference establishes the cone's undercut but gives no dimensioned section; this metre value is a silhouette
# assumption, not a measured F-104 dimension. The owner had the splitter plate and stand-off removed.
MOUTH = {"undercut": 0.03}
# Review close-ups: name -> (camera location, look-at point), Blender axes.
CLOSEUPS = {
    "intake": (Vector((3.2, -6.6, 1.0)), Vector((0.8, -1.2, 0.2))),
    "intake_head_on": (Vector((0.8, -16.0, 0.22)), Vector((0.8, -1.0, 0.22))),
}


def build(p, mats):
    parts = build_nozzle(p, mats)
    parts += build_shock_cones(p, mats["body"], mats["mechanical"])
    parts += build_ducts(p, mats["mechanical"])
    parts += build_mouth(p, mats)
    return parts


def check(icarus):
    import budget

    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("propulsion: over triangle caps: " + "; ".join(over))
    ring = bpy.data.objects["nozzle_vector"]
    hinges = list(ring.children)
    if len(hinges) != 32 or any(h.get("hinge_axis") != "X" for h in hinges):
        raise ValueError("propulsion: nozzle_vector must have 32 X hinges")
    for hinge in hinges:
        vis = bpy.data.objects[hinge.name + "_visible"]
        if vis.parent != hinge or vis.get("role") != "visual":
            raise ValueError("propulsion: invalid petal visual " + vis.name)
        if [m.name for m in vis.data.materials] != ["Icarus_Body", "jet_mechanical"]:
            raise ValueError("propulsion: petal skin must be slot 0, inner face stock trim")
        ys = [v.co.y for v in vis.data.vertices]
        if abs(min(ys)) > 1e-6 or abs(max(ys) - bi.PARAMS["nozzle"]["petal_length"]) > 1e-6:
            raise ValueError("propulsion: petal length changed " + vis.name)
    print("propulsion check PASS: 32 X hinges with skin/trim visuals; " + ", ".join(
        "%s %d/%d triangles" % (key, budget.measure(icarus, item), item["cap"]) for key, item in BUDGET.items()))


def build_ducts(p, duct_mat):
    """Intake ducts, faces pointing inward, from just inside the lip to a capped engine face."""
    rows = bi.resample(p["duct"], bi.spaced(p["duct"][0][0], p["duct"][-1][0], 16))
    parts = []
    for side, name in ((1, "duct_L"), (-1, "duct_R")):
        rings = [[bi.P(s, side * (cx + r * math.cos(a)), cz + r * math.sin(a))
                  for a in [2 * math.pi * k / 32 for k in range(32)]] for s, cx, cz, r in rows]
        obj = bi.loft(name, rings, cap_back=True)
        bi.inward_fix(obj, Vector((side * rows[0][1], rows[0][0] - bi.S0, rows[0][2])))
        parts.append(bi.finish(obj, duct_mat))
    return parts


def build_shock_cones(p, mat, duct_mat):
    sc = p["shock_cone"]
    zc = p["intake"][0][2]
    parts = []
    for side, name in ((1, "shock_cone_L"), (-1, "shock_cone_R")):
        profile = [(sc["apex_s"] + (sc["break_s"] - sc["apex_s"]) * i / 6, sc["break_r"] * i / 6) for i in range(1, 7)]
        profile += [(sc["break_s"] + (sc["base_s"] - sc["break_s"]) * i / 5,
                     sc["break_r"] + (sc["radius"] - sc["break_r"]) * i / 5) for i in range(1, 6)]
        # The bleed is a real recess, with the rear ramp overhanging its floor.
        radius = lambda s: sc["break_r"] + (sc["radius"] - sc["break_r"]) * (s - sc["break_s"]) / (sc["base_s"] - sc["break_s"])
        a, b = sc["bleed_s"], sc["bleed_s"] + 0.035
        profile = [row for row in profile if not a <= row[0] <= b]
        profile += [(a, radius(a)), (a, radius(a) - MOUTH["undercut"]),
                    (b, radius(b) - MOUTH["undercut"]), (b, radius(b))]
        profile.sort(key=lambda row: row[0])
        rings = [[bi.P(s, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                  for a in [2 * math.pi * k / 48 for k in range(48)]] for s, r in profile]
        cone = bi.finish(bi.loft(name, rings, tip_front=bi.P(sc["apex_s"], side * sc["x"], zc), cap_back=True), mat)
        parts.append(cone)
        cone.data.materials.append(duct_mat)
        import parts as part_tree

        part_tree.face_outward(cone)
        for poly in cone.data.polygons:
            if a - 1e-5 <= poly.center.y + bi.S0 <= b + 1e-5:
                poly.material_index = 1
        r0 = radius(a) - MOUTH["undercut"] + 0.001
        band = []
        for ds in (0.0, 0.035):
            r = r0 + (sc["radius"] - sc["break_r"]) * ds / (sc["base_s"] - sc["break_s"]) + 0.003
            band.append([bi.P(sc["bleed_s"] + ds, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                         for a in [2 * math.pi * k / 48 for k in range(48)]])
        slot = bi.loft(name + "_bleed", band)
        if side < 0:
            slot.data.flip_normals()
        parts.append(bi.finish(slot, duct_mat))
    return parts


def lip_edge(p, skin):
    s, xo, cz, _ = p["intake"][0]
    cx = (xo + p["intake_inner_x"]) / 2
    bm = bmesh.new()
    bm.from_mesh(skin.data)
    bm.transform(skin.matrix_world)
    points = {v.index: v.co.copy() for e in bm.edges if e.is_boundary
              and all(abs(v.co.y + bi.S0 - s) < 1e-4 for v in e.verts)
              for v in e.verts if v.co.x > 0 and math.hypot(v.co.x - cx, v.co.z - cz) < 0.45}
    bm.free()
    if len(points) < 10:
        raise ValueError("propulsion: no intake opening edge")
    return sorted(points.values(), key=lambda v: math.atan2(v.z - cz, v.x - cx))


def detail_mesh(name, owner, verts, faces, mats, indices, side=1):
    if side < 0:
        verts = [Vector((-v.x, v.y, v.z)) for v in verts]
        faces = [f[::-1] for f in faces]
    obj = bi.mesh_object(name, verts, faces)
    for mat in mats:
        obj.data.materials.append(mat)
    for poly, index in zip(obj.data.polygons, indices):
        poly.material_index = index
    obj["merge_into"] = owner
    return obj


def build_mouth(p, mats):
    s, xo, cz, _ = p["intake"][0]
    cx = (xo + p["intake_inner_x"]) / 2
    ds, dx, dz, dr = p["duct"][0]
    edge = lip_edge(p, bpy.data.objects["fuselage"])
    rings = []
    for v in edge:
        radial = Vector((v.x - cx, 0, v.z - cz)).normalized()
        radius = math.hypot(v.x - cx, v.z - cz)
        profile = [(0.006, -0.003)] + [(-0.006 * math.sin(t), -0.004 + 0.004 * math.cos(t))
                   for t in [math.pi * i / 4 for i in range(5)]] + [(ds - s + 0.006, dr - radius)]
        rings.append([bi.P(s + a, cx + (radius + b) * radial.x, cz + (radius + b) * radial.z)
                      for a, b in profile])
    verts = [v for row in rings for v in row]
    width = len(rings[0])
    faces = [(j * width + k, (j + 1) * width + k, (j + 1) * width + k + 1, j * width + k + 1)
             for j in range(len(rings) - 1) for k in range(width - 1)]
    indices = [1 if k == width - 2 else 0 for j in range(len(rings) - 1) for k in range(width - 1)]
    return [detail_mesh("intake_mouth_" + sd, "intake_duct_" + sd, verts, faces,
                        [mats["body"], mats["mechanical"]], indices, side)
            for side, sd in ((1, "L"), (-1, "R"))]


def ring_points(s, r, z, n=bi.RING):
    return [bi.P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / n for k in range(n)]]


def plate(name, root_w, tip_w, length, thickness):
    """Chamfered petal in hinge space, with a rolled exit edge. Its axial extent stays exactly 0 to length."""
    c, bead = 0.003, 0.008
    half_width = lambda y: (root_w + (tip_w - root_w) * y / length) / 2
    section = lambda y, slope: [Vector((sign * (half_width(y - slope * z) - inset), y - slope * z, z))
                               for sign, inset, z in ((-1, 0, -thickness), (-1, 0, -c), (-1, c, 0),
                                                      (1, c, 0), (1, 0, -c), (1, 0, -thickness))]
    verts, faces = sweep_shape([section(0, 1), section(length - bead, 0)], cap=True)
    rim = [(length - bead + bead * math.cos(a), -thickness / 2 + bead * math.sin(a))
           for a in [math.pi * i / 3 for i in range(6)]]
    width = half_width(length - bead) - c
    v, f = sweep_shape([[Vector((x, y, z)) for y, z in rim] for x in (-width, width)], cap=True)
    offset = len(verts)
    verts += v
    faces += [tuple(offset + i for i in face) for face in f]
    obj = bi.mesh_object(name, verts, faces)
    import parts as part_tree

    part_tree.face_outward(obj)
    return obj


def sweep_shape(rings, closed=False, cap=False):
    n, m = len(rings[0]), len(rings)
    faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) % m * n + (k + 1) % n, (j + 1) % m * n + k)
             for j in range(m if closed else m - 1) for k in range(n)]
    if cap:
        faces += [tuple(range(n))[::-1], tuple((m - 1) * n + k for k in range(n))]
    return [v for row in rings for v in row], faces


def nozzle_lip(n, mats):
    radius = 0.013
    profile = [(n["ring_s"] + radius * math.sin(t), n["shroud_r"] - radius + radius * math.cos(t))
               for t in [2 * math.pi * i / 6 for i in range(6)]]
    rings = [[bi.P(s, r * math.cos(a), n["z"] + r * math.sin(a)) for s, r in profile]
             for a in [2 * math.pi * k / 40 for k in range(40)]]
    verts, faces = sweep_shape(rings, closed=True)
    return detail_mesh("nozzle_lip", "nozzle", verts, faces, [mats["body"]], [0] * len(faces))


def afterburner(n, mats):
    s = n["shroud_start"] + 0.06
    profile = [(s - 0.01, 0.23), (s + 0.01, 0.2425), (s + 0.002, 0.23), (s + 0.01, 0.2175)]
    rings = [[bi.P(t, r * math.cos(a), n["z"] + r * math.sin(a)) for t, r in profile]
             for a in [2 * math.pi * k / 24 for k in range(24)]]
    verts, faces = sweep_shape(rings, closed=True)
    base = len(verts)
    verts += ring_points(n["shroud_start"] + 0.005, 0.09, n["z"], 16)
    verts.append(bi.P(n["shroud_start"] + 0.16, 0, n["z"]))
    faces += [(base + k, base + (k + 1) % 16, base + 16) for k in range(16)]
    faces.append(tuple(base + k for k in reversed(range(16))))
    if sum(len(f) - 2 for f in faces) > 600:
        raise ValueError("propulsion: afterburner exceeds 600 triangles")
    return detail_mesh("nozzle_afterburner", "nozzle", verts, faces, [mats["mechanical"]], [0] * len(faces))


def nozzle_hinge_matrix(p, kind, i, open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """World matrix of one petal or seal hinge. Opening adds to every petal; vectoring tilts the exit: a petal at
    ring angle phi gains -pitch*sin(phi) - yaw*cos(phi), so a positive pitch points the exit down (nose-up moment)."""
    n = p["nozzle"]
    count = n["petals"]
    phi = 2 * math.pi * i / count + (math.pi / count if kind == "seal" else 0.0)
    radial = Vector((math.cos(phi), 0.0, math.sin(phi)))
    # X runs clockwise round the ring seen from behind, so X, aft and outward make a right-handed frame; a positive
    # rotation about X turns aft toward outward, opening the petal.
    hinge_x = Vector((math.sin(phi), 0.0, -math.cos(phi)))
    basis = Matrix((hinge_x, Vector((0.0, 1.0, 0.0)), radial)).transposed().to_4x4()
    inset = n["seal_inset"] if kind == "seal" else 0.0
    hinge_at = bi.P(n["ring_s"], 0.0, n["z"]) + radial * (n["ring_r"] - inset)
    angle = n["dry_angle_deg"] + open_deg - pitch_deg * math.sin(phi) - yaw_deg * math.cos(phi)
    return Matrix.Translation(hinge_at) @ basis @ Matrix.Rotation(math.radians(angle), 4, "X")


def pose_nozzle(open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """Pose the built nozzle, the way the plugin will drive it in game."""
    for kind in ("petal", "seal"):
        for i in range(bi.PARAMS["nozzle"]["petals"]):
            hinge = bpy.data.objects["nozzle_%s_%02d" % (kind, i)]
            hinge.matrix_world = nozzle_hinge_matrix(bi.PARAMS, kind, i, open_deg, pitch_deg, yaw_deg)


def build_nozzle(p, mats):
    n = p["nozzle"]
    z, s_ring, r = n["z"], n["ring_s"], n["ring_r"]
    # The engine's end cap is at shroud_start. Offset this visible face to avoid coplanar flicker in the chase view.
    shroud = bi.loft("nozzle_shroud", [ring_points(n["shroud_start"], n["shroud_r"], z, 64), ring_points(s_ring, n["shroud_r"], z, 64),
                                      ring_points(s_ring, n["duct_r"], z, 64), ring_points(n["shroud_start"] + 0.004, n["duct_r"], z, 64)],
                     cap_back=True)
    bi.finish(shroud, mats["body"])
    shroud.data.materials.append(mats["mechanical"])
    for poly in shroud.data.polygons[128:]:
        poly.material_index = 1
    gimbal = bi.empty("nozzle_vector", Matrix.Translation(bi.P(s_ring, 0.0, z)))
    parts = [shroud, gimbal, nozzle_lip(n, mats), afterburner(n, mats)]
    count = n["petals"]
    for kind, w0, w1 in (("petal", n["petal_root_w"], n["petal_tip_w"]),
                         ("seal", n["petal_root_w"] * 0.7, n["petal_tip_w"] * 0.7)):
        for i in range(count):
            name = "nozzle_%s_%02d" % (kind, i)
            hinge = bi.empty(name, nozzle_hinge_matrix(p, kind, i), parent=gimbal)
            hinge["hinge_axis"] = "X"
            vis = plate(name + "_visible", w0, w1, n["petal_length"], n["petal_thickness"])
            vis.parent = hinge
            vis.data.materials.append(mats["body"])
            vis.data.materials.append(mats["mechanical"])
            for poly in vis.data.polygons:
                poly.material_index = 1 if poly.normal.z < -0.3 else 0
            vis["role"] = "visual"
            parts += [hinge, vis]
    return parts
