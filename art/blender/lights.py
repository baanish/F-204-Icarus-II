"""Stock nav lens anchors, surface-following formation lenses and fin strips, and skin antenna blades."""
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
    "light_fin_L": ("fin_skin", 0),
    "light_fin_R": ("fin_skin", 0),
    "light_landing": ("gear_leg_N", 0),
}
# The forward formation lights follow the Revoker's (fighter1_slimelights_F; the Chicane's are the same size): two
# 0.35 x 0.098 m lenses a side in a row, centres 0.52 m apart, on the lower flank under the cockpit, facing 27 to 32
# degrees below horizontal. Here they sit under the design eye, straddling the riveted frame at s 4.0 between the
# butt joints at s 3.4 and 4.6; 35 degrees down keeps the rim below the NO STEP stencil (decal_checks.py). A narrow dark rim slopes
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
# The fin strips follow the Revoker's (fighter1_slimelights_R): one 0.882 x 0.081 m strip a side, 42 degrees up and
# aft along the fin's leading edge (the Vagrant's fin strips are 0.910 x 0.066 m; the Compass carries two 0.46 x
# 0.12 m strips a side on each canted fin). Here each lies parallel to the fin's straight upper leading edge (43
# degrees), le_offset behind it and ahead of the front spar joint, so the fin markings keep the clear panel aft of
# that joint (decal_checks.py holds them FITTING_CLEAR_M off every lens).
FIN_STRIP = {"length": 0.88, "width": 0.08, "le_z": 1.755, "le_offset": 0.075, "rim": 0.008, "lens_height": 0.0025,
             "rim_foot": 0.0012}
STOCK_FIN_LENS_AREA = 0.0713  # m2 a side, the Revoker's fin strip
# The fin is thin and nearly flat along the strip, so grid points 0.22 m apart along it stay on the skin.
FIN_COLUMNS, FIN_ROWS = 5, 2
FIN_LENS_TRIS = 2 * (FIN_COLUMNS - 1) * (FIN_ROWS - 1)
FIN_RIM_TRIS = 2 * 2 * (FIN_COLUMNS + FIN_ROWS - 2)
# The nav lenses stay stock references in Unity, 14 triangles each.
BUDGET = {
    "formation_lenses": {"target": 160, "cap": 160, "objects": ("light_formation_",)},
    "fin_strips": {"target": 56, "cap": 56, "objects": ("light_fin_",)},
    "antennas": {"target": 36, "cap": 180, "objects": ("dorsal_cover", "skin_mid_L"),
                 "face_attribute": "antenna"},
}
CLOSEUPS = {
    "formation_lenses": (Vector((1.15, -0.35, -0.62)), bi.P(4.0, 0.47, -0.24)),
    "fin_strips": (Vector((2.4, 4.6, 2.0)), bi.P(13.55, 0.0, 1.7)),
}


def formation_lens(skin, side):
    """One side's forward lenses and rims, laid on the skin by rays toward the body axis."""
    f = FORMATION
    angle = math.radians(f["angle_deg"])

    def on_skin(s, theta, height):
        axis = bi.P(s, 0.0, f["axis_z"])
        out = Vector((side * math.cos(theta), 0.0, math.sin(theta)))
        at, normal = solids.must(solids.hit(skin, axis + out * 2.0, -out), "light_formation")
        return at + normal * height, normal, (at - axis).length

    def spot(centre):
        radius = on_skin(centre, angle, 0.0)[2]
        return lambda ds, dw, height: on_skin(centre + ds, angle + side * dw / radius, height)[:2]

    return lens_mesh([spot(centre) for centre in f["stations"]], f, COLUMNS, ROWS)


def fin_strip(fin, side):
    """One side's fin strip and rim, laid on the fin by rays square to its plane."""
    f = FIN_STRIP
    (s0, _, z0, _), (s1, _, z1, _) = bi.PARAMS["fin"]["sections"][-2:]
    along = Vector((0.0, s1 - s0, z1 - z0)).normalized()
    across = Vector((0.0, along.z, -along.y))  # in the fin's plane, aft and down from the leading edge
    centre = bi.P(s0 + (f["le_z"] - z0) * (s1 - s0) / (z1 - z0), 0.0, f["le_z"]) + across * f["le_offset"]

    def spot(ds, dw, height):
        q = centre + along * ds + across * dw
        at, normal = solids.must(solids.hit(fin, q + Vector((side, 0.0, 0.0)), Vector((-side, 0.0, 0.0))), "light_fin")
        return at + normal * height, normal

    return lens_mesh([spot], f, FIN_COLUMNS, FIN_ROWS)


def lens_mesh(spots, f, columns, rows):
    """Vertices, UVs, faces and slots of lenses and their rims. spots[k](ds, dw, height) is the point ds along and dw
    across lens k's centre, height off the skin, and the skin normal there."""
    perimeter = ([(0, j) for j in range(rows)] + [(i, rows - 1) for i in range(1, columns)]
                 + [(columns - 1, j) for j in range(rows - 2, -1, -1)] + [(i, 0) for i in range(columns - 2, 0, -1)])
    verts, uvs, faces, slots = [], [], [], []
    for k, spot in enumerate(spots):
        _, normal = spot(0.0, 0.0, 0.0)
        grids = []
        # The lens, then the rim's foot round it; the rim's outer ring spans the lens's whole UV square.
        for grow, height, inset in ((0.0, f["lens_height"], 0.1), (f["rim"], f["rim_foot"], 0.0)):
            base = len(verts)
            for i in range(columns):
                for j in range(rows):
                    ds = (i / (columns - 1) - 0.5) * (f["length"] + 2 * grow)
                    dw = (j / (rows - 1) - 0.5) * (f["width"] + 2 * grow)
                    verts.append(spot(ds, dw, height)[0])
                    uvs.append(((k + inset + i / (columns - 1) * (1 - 2 * inset)) / len(spots),
                                inset + j / (rows - 1) * (1 - 2 * inset)))
            grids.append(lambda i, j, base=base: base + i * rows + j)
        lens, rim = grids
        quads = [((lens(i, j), lens(i + 1, j), lens(i + 1, j + 1), lens(i, j + 1)), 0)
                 for i in range(columns - 1) for j in range(rows - 1)]
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
            pos = gear.landing_lamp()
        obj = bi.empty(name, Matrix.Translation(pos))
        obj["light"], obj["colour"] = kind, colour
        made.append(obj)

    skin = solids.bvh([bpy.data.objects["fuselage"]])
    fin = solids.bvh([bpy.data.objects["fin"]])
    for side, suffix in ((1, "L"), (-1, "R")):
        for name, mesh in (("light_formation_" + suffix, formation_lens(skin, side)),
                           ("light_fin_" + suffix, fin_strip(fin, side))):
            verts, uvs, faces, slots = mesh
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
    worst, areas = 0.0, {}
    for side in ("L", "R"):
        sign = 1 if side == "L" else -1
        # name, skin part, lenses, lens and rim triangles each, stock lens area a side, outward from the skin at a point
        fittings = (("light_formation_" + side, "skin_forward_" + side, len(FORMATION["stations"]), LENS_TRIS,
                     RIM_TRIS, STOCK_LENS_AREA, lambda at: at - Vector((0, at.y, FORMATION["axis_z"]))),
                    ("light_fin_" + side, "fin_skin", 1, FIN_LENS_TRIS, FIN_RIM_TRIS, STOCK_FIN_LENS_AREA,
                     lambda at: Vector((sign, 0, 0))))
        for name, owner, lenses, lens_each, rim_each, stock_area, outward in fittings:
            obj = objects[name]
            if obj.type != "MESH" or obj.get("role") != "visual" or obj.parent != objects[owner]:
                raise ValueError("lights: %s must be a visual of %s" % (name, owner))
            if [m.name for m in obj.data.materials] != ["light_green_off", "Icarus_Frame"]:
                raise ValueError("lights: %s must wear the Revoker's off material in slot 0 and the rim slot 1" % name)
            lens_tris = sum(len(p.vertices) - 2 for p in obj.data.polygons if p.material_index == 0)
            if lens_tris != lenses * lens_each or budget.tris(obj) != lenses * (lens_each + rim_each):
                raise ValueError("lights: %s must have %d lens and %d rim triangles"
                                 % (name, lenses * lens_each, lenses * rim_each))
            # Pinned to the stock size: the lens area a side within 5% of the Revoker's.
            area = sum(p.area for p in obj.data.polygons if p.material_index == 0)
            if abs(area / stock_area - 1) > 0.05:
                raise ValueError("lights: %s lens area %.4f m2 is not the Revoker's %.4f" % (name, area, stock_area))
            areas[name.rsplit("_", 1)[0]] = area
            skin = solids.bvh([objects[owner]])
            obj.data.calc_loop_triangles()
            # W3's 10 mm skin-distance check, extended from an empty to every lens and rim triangle, and each sample
            # must stand outside the skin, where a chord across the swelling body would sink into it.
            for tri in obj.data.loop_triangles:
                a, b, c = [obj.matrix_world @ obj.data.vertices[i].co for i in tri.vertices]
                for i in range(5):
                    for j in range(5 - i):
                        point = a + (b - a) * (i / 4) + (c - a) * (j / 4)
                        at, normal, _, dist = skin.find_nearest(point)
                        if dist is None or dist > 0.010:
                            raise ValueError("%s is %.4f m off the skin" % (name, dist if dist is not None else -1))
                        if (point - at).dot(normal if normal.dot(outward(at)) > 0 else -normal) <= 0:
                            raise ValueError("%s sinks into the skin at %s" % (name, tuple(round(v, 3) for v in point)))
                        worst = max(worst, dist)
            for collection in ("Colliders", "LOD1"):
                if any(o.parent == obj for o in bpy.data.collections[collection].objects):
                    raise ValueError("lights: %s has a %s mesh" % (name, collection))
    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("lights: " + "; ".join(over))
    print("lights.check PASS: nav anchors preserved; 3 merged skin antennas, %d triangles; formation lenses %d "
          "triangles, lens area %.4f m2 a side (Revoker %.4f); fin strips %d triangles, lens area %.4f m2 a side "
          "(Revoker %.4f); max skin gap %.4f m"
          % (budget.measure(icarus, BUDGET["antennas"]), budget.measure(icarus, BUDGET["formation_lenses"]),
             areas["light_formation"], STOCK_LENS_AREA, budget.measure(icarus, BUDGET["fin_strips"]),
             areas["light_fin"], STOCK_FIN_LENS_AREA, worst))
