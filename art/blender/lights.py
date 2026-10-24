"""Stock nav lens anchors, surface-following formation lenses and skin antenna blades."""
import math

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
    "light_formation_L": ("skin_forward_L", 0),
    "light_formation_R": ("skin_forward_R", 0),
    "light_landing": ("gear_leg_N", 0),
}
# The forward formation lights follow the Revoker's (fighter1_slimelights_F; the Chicane's are the same size): two
# 0.35 x 0.098 m lenses a side in a row, centres 0.52 m apart, on the lower flank under the cockpit, facing 27 to 32
# degrees below horizontal. Here they sit under the design eye, straddling the riveted frame at s 4.0 between the
# butt joints at s 3.4 and 4.6; 35 degrees down keeps the rim 2 cm below the NO STEP stencil. A narrow dark rim slopes
# from the lens down to the skin, so each reads as a fitting set into the skin; the lens is slot 0, the one NavLights
# swaps for the lit material.
FORMATION = {"stations": (3.74, 4.26), "length": 0.35, "width": 0.098, "angle_deg": -35.0, "axis_z": 0.07,
             "rim": 0.008, "lens_height": 0.0025, "rim_foot": 0.0012}
STOCK_LENS_AREA = 2 * 0.0341  # m2 a side, the Revoker's two forward lenses
# Lens grid points along and across: the skin still swells at s 3.6, so a lens needs four bays along to stay on it.
# Between grid points the skin's own facets stand up to about 0.9 mm above a chord, under the rim's 1.2 mm foot.
COLUMNS, ROWS = 5, 3
LENS_TRIS = 2 * (COLUMNS - 1) * (ROWS - 1)
RIM_TRIS = 2 * 2 * (COLUMNS + ROWS - 2)  # one quad per perimeter edge
# The nav lenses stay stock references in Unity, 14 triangles each.
BUDGET = {
    "formation_lenses": {"target": 160, "cap": 160, "objects": ("light_formation_",)},
    "antennas": {"target": 36, "cap": 180, "objects": ("dorsal_cover", "skin_mid_L"),
                 "face_attribute": "antenna"},
}
CLOSEUPS = {
    "formation_lenses": (Vector((1.15, -0.35, -0.62)), bi.P(4.0, 0.47, -0.24)),
}


def formation_lens(skin, side):
    """Vertices, UVs, faces and slots of one side's lenses and rims, laid on the skin by rays toward the body axis."""
    f = FORMATION
    angle = math.radians(f["angle_deg"])

    def on_skin(s, theta, height):
        axis = bi.P(s, 0.0, f["axis_z"])
        out = Vector((side * math.cos(theta), 0.0, math.sin(theta)))
        at, normal = solids.must(solids.hit(skin, axis + out * 2.0, -out), "light_formation")
        return at + normal * height, normal, (at - axis).length

    perimeter = ([(0, j) for j in range(ROWS)] + [(i, ROWS - 1) for i in range(1, COLUMNS)]
                 + [(COLUMNS - 1, j) for j in range(ROWS - 2, -1, -1)] + [(i, 0) for i in range(COLUMNS - 2, 0, -1)])
    verts, uvs, faces, slots = [], [], [], []
    for k, centre in enumerate(f["stations"]):
        _, normal, radius = on_skin(centre, angle, 0.0)
        grids = []
        # The lens, then the rim's foot round it; the rim's outer ring spans the lens's whole UV square.
        for grow, height, inset in ((0.0, f["lens_height"], 0.1), (f["rim"], f["rim_foot"], 0.0)):
            base = len(verts)
            for i in range(COLUMNS):
                for j in range(ROWS):
                    ds = (i / (COLUMNS - 1) - 0.5) * (f["length"] + 2 * grow)
                    dw = (j / (ROWS - 1) - 0.5) * (f["width"] + 2 * grow)
                    verts.append(on_skin(centre + ds, angle + side * dw / radius, height)[0])
                    uvs.append(((k + inset + i / (COLUMNS - 1) * (1 - 2 * inset)) / 2,
                                inset + j / (ROWS - 1) * (1 - 2 * inset)))
            grids.append(lambda i, j, base=base: base + i * ROWS + j)
        lens, rim = grids
        quads = [((lens(i, j), lens(i + 1, j), lens(i + 1, j + 1), lens(i, j + 1)), 0)
                 for i in range(COLUMNS - 1) for j in range(ROWS - 1)]
        quads += [((lens(*a), lens(*b), rim(*b), rim(*a)), 1) for a, b in zip(perimeter, perimeter[1:] + perimeter[:1])]
        for quad, slot in quads:
            a, b, c = (verts[i] for i in quad[:3])
            faces.append(quad if (b - a).cross(c - a).dot(normal) > 0 else quad[::-1])
            slots.append(slot)
    return verts, uvs, faces, slots


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
        verts, uvs, faces, slots = formation_lens(skin, side)
        obj = bi.finish(bi.mesh_object(name, verts, faces), bpy.data.materials["light_green_off"])
        obj.data.materials.append(mats["frame"])
        for poly, slot in zip(obj.data.polygons, slots):
            poly.material_index = slot
        # The lens keeps its own smooth curve; the rim breaks sharply from it.
        lens_edges = {tuple(sorted(e)) for p in obj.data.polygons if p.material_index == 0 for e in p.edge_keys}
        rim_edges = {tuple(sorted(e)) for p in obj.data.polygons if p.material_index == 1 for e in p.edge_keys}
        for edge in obj.data.edges:
            if tuple(sorted(edge.vertices)) in lens_edges & rim_edges:
                edge.use_edge_sharp = True
        obj["role"], obj["light"] = "visual", "formation"
        uv = obj.data.uv_layers.new(name="UVMap")
        for loop in obj.data.loops:
            uv.data[loop.index].uv = uvs[loop.vertex_index]
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
    worst, areas = 0.0, []
    for side in ("L", "R"):
        obj = objects["light_formation_" + side]
        if obj.type != "MESH" or obj.get("role") != "visual" or obj.parent != objects["skin_forward_" + side]:
            raise ValueError("lights: formation lenses must be a visual of their skin part")
        if [m.name for m in obj.data.materials] != ["light_green_off", "Icarus_Frame"]:
            raise ValueError("lights: formation lenses must wear the Revoker's off material in slot 0 and the rim slot 1")
        lenses = len(FORMATION["stations"])
        lens_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons if p.material_index == 0)
        if lens_tris != lenses * LENS_TRIS or budget.tris(obj) != lenses * (LENS_TRIS + RIM_TRIS):
            raise ValueError("lights: formation lenses must have %d lens and %d rim triangles"
                             % (lenses * LENS_TRIS, lenses * RIM_TRIS))
        # Pinned to the stock size: the lens area a side within 5% of the Revoker's.
        area = sum(p.area for p in obj.data.polygons if p.material_index == 0)
        if abs(area / STOCK_LENS_AREA - 1) > 0.05:
            raise ValueError("lights: %s lens area %.4f m2 is not the Revoker's %.4f" % (obj.name, area, STOCK_LENS_AREA))
        areas.append(area)
        skin = solids.bvh([objects["skin_forward_" + side]])
        obj.data.calc_loop_triangles()
        # W3's 10 mm skin-distance check, extended from an empty to every lens and rim triangle, and each sample must
        # stand outside the skin, where a chord across the swelling body would sink into it.
        for tri in obj.data.loop_triangles:
            a, b, c = [obj.matrix_world @ obj.data.vertices[i].co for i in tri.vertices]
            for i in range(5):
                for j in range(5 - i):
                    point = a + (b - a) * (i / 4) + (c - a) * (j / 4)
                    at, normal, _, dist = skin.find_nearest(point)
                    if dist is None or dist > 0.010:
                        raise ValueError("%s is %.4f m off the skin" % (obj.name, dist if dist is not None else -1))
                    outward = at - Vector((0, at.y, FORMATION["axis_z"]))
                    if (point - at).dot(normal if normal.dot(outward) > 0 else -normal) <= 0:
                        raise ValueError("%s sinks into the skin at %s" % (obj.name, tuple(round(v, 3) for v in point)))
                    worst = max(worst, dist)
        for collection in ("Colliders", "LOD1"):
            if any(o.parent == obj for o in bpy.data.collections[collection].objects):
                raise ValueError("lights: formation lenses have a " + collection + " mesh")
    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("lights: " + "; ".join(over))
    print("lights.check PASS: nav anchors preserved; 3 merged skin antennas, %d triangles; formation lenses %d "
          "triangles, lens area %.4f m2 a side (Revoker %.4f), max skin gap %.4f m"
          % (budget.measure(icarus, BUDGET["antennas"]), budget.measure(icarus, BUDGET["formation_lenses"]),
             min(areas), STOCK_LENS_AREA, worst))
