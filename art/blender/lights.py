"""Stock nav lens anchors, surface-following formation strips and skin antenna blades."""
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi
import gear
import solids
import stations

LIGHTS = (
    ("light_nav_L", "nav", "red"),
    ("light_nav_R", "nav", "green"),
    ("light_landing", "landing", "white"),
)
# name, station, height, chord, surface, skin owner
ANTENNAS = (
    ("antenna_uhf_top", 7.20, 0.20, 0.30, "top", "dorsal_cover"),
    ("antenna_iff_belly", 6.40, 0.15, 0.22, "belly", "skin_mid_L"),
    ("antenna_datalink_top", 11.60, 0.16, 0.26, "top", "dorsal_cover"),
)
TREE = {
    "light_nav_L": ("wing_skin_L", 0),
    "light_nav_R": ("wing_skin_R", 0),
    "light_formation_L": ("skin_mid_L", 0),
    "light_formation_R": ("skin_mid_R", 0),
    "light_landing": ("gear_leg_N", 0),
}
# The nav lenses stay stock references in Unity, 14 triangles each.
BUDGET = {
    "formation_strips": {"target": 8, "cap": 16, "objects": ("light_formation_",)},
    "antennas": {"target": 36, "cap": 180, "objects": ("dorsal_cover", "skin_mid_L"),
                 "face_attribute": "antenna"},
}
CLOSEUPS = {
    "formation_strip": (Vector((2.4, -2.4, 0.9)), bi.P(6.3, 0.9, 0.3)),
}


def build(p, mats):
    w = p["wing"]
    lamp_x = w["planform"][-1][1] - 0.075
    lamp_le, lamp_z, lamp_chord = stations.wing_at(w, lamp_x)
    made = []
    for name, kind, colour in LIGHTS:
        if kind == "nav":
            side = 1 if name.endswith("_L") else -1
            pos = bi.P(lamp_le + lamp_chord * 0.35, side * lamp_x,
                       lamp_z + bi.airfoil(0.35) * w["thickness"] * lamp_chord)
        else:
            g = gear.GEAR["nose"]
            pos = bi.P(g["wheel_s"] - 0.085, 0.0, gear.GEAR["ground_z"] + g["wheel_d"] + 0.15)
        obj = bi.empty(name, Matrix.Translation(pos))
        obj["light"], obj["colour"] = kind, colour
        made.append(obj)

    skin = solids.bvh([bpy.data.objects["fuselage"]])
    for side, suffix in ((1, "L"), (-1, "R")):
        name = "light_formation_" + suffix
        verts = []
        for s in (6.05, 6.30, 6.55):
            for z in (0.2825, 0.3175):
                at, normal = solids.must(solids.hit(skin, bi.P(s, side * 2.0, z), Vector((-side, 0, 0))), name)
                verts.append(at + normal * 0.002)
        faces = [(0, 2, 3, 1), (2, 4, 5, 3)]
        if side < 0:
            faces = [tuple(reversed(f)) for f in faces]
        obj = bi.finish(bi.mesh_object(name, verts, faces), bpy.data.materials["light_green_off"], smooth=False)
        obj["role"], obj["light"] = "visual", "formation"
        uv = obj.data.uv_layers.new(name="UVMap")
        for loop in obj.data.loops:
            row, col = divmod(loop.vertex_index, 2)
            uv.data[loop.index].uv = (row / 2, col)
        made.append(obj)

    for index, (name, s, h, chord, where, owner) in enumerate(ANTENNAS, 1):
        up = 1 if where == "top" else -1
        # Each root end follows the actual skin, rather than a single station's height.
        verts = []
        for station in (s - chord / 2, s + chord / 2):
            at, _ = solids.must(solids.hit(skin, bi.P(station, 0, up * 3), Vector((0, 0, -up))), name)
            verts.append(at - Vector((0, 0, up * 0.02)))
        at, _ = solids.must(solids.hit(skin, bi.P(s, 0, up * 3), Vector((0, 0, -up))), name)
        verts += [bi.P(s + chord * 0.1, 0, at.z + up * h), bi.P(s - chord * 0.05, 0, at.z + up * h)]
        thick = Vector((0.006, 0, 0))
        v = [q - thick for q in verts] + [q + thick for q in verts]
        f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        obj = bi.finish(bi.mesh_object(name, v, f), mats["body"], smooth=False)
        obj["merge_into"] = owner
        tag = obj.data.attributes.new("antenna", "INT", "FACE")
        for value in tag.data:
            value.value = index
        made.append(obj)
    return made


def check(icarus):
    import budget

    objects = {o.name: o for o in icarus.all_objects}
    if any(n.startswith(("light_beacon_", "antenna_")) for n in objects):
        raise ValueError("lights: beacons or separate antenna parts remain")
    for index, (name, _, _, _, _, owner) in enumerate(ANTENNAS, 1):
        obj = objects[owner]
        tag = obj.data.attributes.get("antenna")
        faces = [f for f in obj.data.polygons if tag and tag.data[f.index].value == index]
        count = sum(len(f.vertices) - 2 for f in faces)
        if not 0 < count <= 60 or any(obj.data.materials[f.material_index].name != "Icarus_Body" for f in faces):
            raise ValueError("lights: %s must be 1 to 60 skin triangles in %s, got %d" % (name, owner, count))
    worst = 0.0
    for side in ("L", "R"):
        obj = objects["light_formation_" + side]
        if obj.type != "MESH" or obj.get("role") != "visual" or obj.parent != objects["skin_mid_" + side]:
            raise ValueError("lights: formation strip must be a visual of its skin part")
        if not 2 <= budget.tris(obj) <= 8:
            raise ValueError("lights: formation strip must have 2 to 8 triangles")
        if [m.name for m in obj.data.materials] != ["light_green_off"]:
            raise ValueError("lights: formation strip must use the Revoker's off material")
        skin = solids.bvh([objects["skin_mid_" + side]])
        obj.data.calc_loop_triangles()
        # W3's 10 mm skin-distance check, extended from an empty to the whole strip.
        for tri in obj.data.loop_triangles:
            a, b, c = [obj.matrix_world @ obj.data.vertices[i].co for i in tri.vertices]
            for i in range(5):
                for j in range(5 - i):
                    point = a + (b - a) * (i / 4) + (c - a) * (j / 4)
                    _, _, _, dist = skin.find_nearest(point)
                    if dist is None or dist > 0.010:
                        raise ValueError("%s is %.4f m off the skin" % (obj.name, dist if dist is not None else -1))
                    worst = max(worst, dist)
        for collection in ("Colliders", "LOD1"):
            if any(o.parent == obj for o in bpy.data.collections[collection].objects):
                raise ValueError("lights: formation strip has a " + collection + " mesh")
    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("lights: " + "; ".join(over))
    print("lights.check PASS: nav anchors preserved; 3 merged skin antennas, %d triangles; formation %d triangles, "
          "max skin gap %.4f m" % (budget.measure(icarus, BUDGET["antennas"]),
                                  budget.measure(icarus, BUDGET["formation_strips"]), worst))
