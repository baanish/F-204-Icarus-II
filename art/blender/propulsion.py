"""Intakes and the iris nozzle: the shock cones with their bleed bands, the ducts to the engine face, the nozzle
shroud and its hinged petals and seals.

The nozzle is a fixed shroud, then a ring of hinged petals with seals between them. Each petal hangs on its own hinge
empty (local X along the hinge) under one gimbal empty, so the plugin can open the iris with afterburner and deflect
it for thrust vectoring. The built pose is dry thrust: petals angled inward.
"""
import math

import bpy
from mathutils import Matrix, Vector

import build_icarus as bi

# Triangles per component: target and cap (budget.py sums them).
BUDGET = {
    "intake_L": {"target": 3500, "cap": 4600, "objects": ("intake_duct_L",)},
    "intake_R": {"target": 3500, "cap": 4600, "objects": ("intake_duct_R",)},
    "nozzle": {"target": 3200, "cap": 3900, "objects": ("nozzle", "nozzle_petal_", "nozzle_seal_")},
}
# Review close-ups: name -> (camera location, look-at point), Blender axes.
CLOSEUPS = {
    "intake": (Vector((3.2, -6.6, 1.0)), Vector((0.8, -1.2, 0.2))),
    "intake_head_on": (Vector((0.8, -16.0, 0.22)), Vector((0.8, -1.0, 0.22))),
}


def build(p, mats):
    parts = build_nozzle(p, mats)
    parts += build_shock_cones(p, mats["body"], mats["duct"])
    parts += build_ducts(p, mats["duct"])
    return parts


def check(icarus):
    return None


def build_ducts(p, duct_mat):
    """Intake ducts, faces pointing inward, from just inside the lip to a capped engine face."""
    rows = bi.resample(p["duct"], bi.spaced(p["duct"][0][0], p["duct"][-1][0], 16))
    parts = []
    for side, name in ((1, "duct_L"), (-1, "duct_R")):
        rings = [[bi.P(s, side * (cx + r * math.cos(a)), cz + r * math.sin(a))
                  for a in [2 * math.pi * k / 48 for k in range(48)]] for s, cx, cz, r in rows]
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
        rings = [[bi.P(s, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                  for a in [2 * math.pi * k / bi.RING for k in range(bi.RING)]] for s, r in profile]
        cone = bi.finish(bi.loft(name, rings, tip_front=bi.P(sc["apex_s"], side * sc["x"], zc), cap_back=True), mat)
        parts.append(cone)
        # Bleed slot: a dark band just proud of the cone surface near its base.
        r0 = sc["break_r"] + (sc["radius"] - sc["break_r"]) * (sc["bleed_s"] - sc["break_s"]) / (sc["base_s"] - sc["break_s"])
        band = []
        for ds in (0.0, 0.035):
            r = r0 + (sc["radius"] - sc["break_r"]) * ds / (sc["base_s"] - sc["break_s"]) + 0.003
            band.append([bi.P(sc["bleed_s"] + ds, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                         for a in [2 * math.pi * k / bi.RING for k in range(bi.RING)]])
        slot = bi.loft(name + "_bleed", band)
        if side < 0:
            slot.data.flip_normals()
        parts.append(bi.finish(slot, duct_mat))
    return parts


def ring_points(s, r, z, n=bi.RING):
    return [bi.P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / n for k in range(n)]]


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
    bi.TARGET.objects.link(obj)
    return obj


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
    shroud = bi.loft("nozzle_shroud", [ring_points(n["shroud_start"], n["shroud_r"], z), ring_points(s_ring, n["shroud_r"], z),
                                      ring_points(s_ring, n["duct_r"], z), ring_points(n["shroud_start"], n["duct_r"], z)],
                     cap_back=True)
    bi.finish(shroud, mats["metal"])
    shroud.data.materials.append(mats["duct"])
    shroud.data.polygons[-1].material_index = 1  # engine face up the duct
    gimbal = bi.empty("nozzle_vector", Matrix.Translation(bi.P(s_ring, 0.0, z)))
    parts = [shroud, gimbal]
    count = n["petals"]
    for kind, w0, w1 in (("petal", n["petal_root_w"], n["petal_tip_w"]),
                         ("seal", n["petal_root_w"] * 0.7, n["petal_tip_w"] * 0.7)):
        for i in range(count):
            name = "nozzle_%s_%02d" % (kind, i)
            hinge = bi.empty(name, nozzle_hinge_matrix(p, kind, i), parent=gimbal)
            hinge["hinge_axis"] = "X"
            vis = plate(name + "_visible", w0, w1, n["petal_length"], n["petal_thickness"])
            vis.parent = hinge
            vis.data.materials.append(mats[kind])
            parts += [hinge, vis]
    return parts
