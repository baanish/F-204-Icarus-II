"""Stock nav lens anchors, surface-following formation lenses and fin strips, and skin antenna blades."""
import math

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

import build_icarus as bi
import gear
import solids
import stations

LIGHTS = (
    ("light_nav_L", "nav", "red"),
    ("light_nav_R", "nav", "green"),
    ("light_nav_lower_L", "nav", "red"),
    ("light_nav_lower_R", "nav", "green"),
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
    "light_nav_lower_L": ("wing_skin_L", 0),
    "light_nav_lower_R": ("wing_skin_R", 0),
    "light_nav_mount_L": ("wing_skin_L", 0),
    "light_nav_mount_R": ("wing_skin_R", 0),
    "light_nav_aft": ("stabilator", 0),
    "light_tail_fairing": ("stabilator", 0),
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
# The paired stock lenses clear the loaded tip missile above and below the wing.
NAV_HEIGHT = 0.074  # lowest clear centre height at 1 mm steps; 0.073 blocks the IRM-S1
# A separate slot keeps these projected wing UVs out of the packed skin atlas.
# Unity maps it to the same livery material as Icarus_Body.
NAV_PAINT = "Icarus_NavFairing"
AFT_STATION = 16.705
AFT_RADIUS = 0.026
# The nav lenses stay stock references in Unity, 14 triangles each.
BUDGET = {
    "nav_lenses": {"target": 56, "cap": 56, "objects": ("light_nav_",), "reference_triangles": True},
    "nav_mounts": {"target": 88, "cap": 88, "objects": ("light_nav_mount_",)},
    "tail_light": {"target": 56, "cap": 56, "exact": ("light_nav_aft", "light_tail_fairing")},
    "formation_lenses": {"target": 160, "cap": 160, "objects": ("light_formation_",)},
    "fin_strips": {"target": 56, "cap": 56, "objects": ("light_fin_",)},
    "antennas": {"target": 36, "cap": 36, "objects": ("dorsal_cover", "skin_mid_L"),
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


def nav_fairing(wing, side, paint, lens, height=NAV_HEIGHT):
    """Two open fairings: skin-following foot, fillet, and the stock lens's eight-edge aperture."""
    w = bi.PARAMS["wing"]
    x = w["planform"][-1][1] - 0.075
    leading, z, chord = stations.wing_at(w, x)
    s = leading + chord * 0.35
    skin = solids.bvh([wing])
    footprint = ((-0.065, -0.075), (-0.012, -0.20), (0.0287, -0.075),
                 (0.0287, 0.105), (-0.012, 0.25), (-0.065, 0.105))
    fillet = ((-0.040, -0.103), (0.025, -0.103), (0.025, 0.103), (-0.040, 0.103))
    base_y = min(v[1] for v in lens[0])
    foot = [Vector((-v[0], -v[2], v[1])) for v in lens[0] if abs(v[1] - base_y) < 0.000002]
    if len(foot) != 8:
        raise ValueError("nav fairing: expected the stock lens's eight-edge aperture")
    verts, faces, roots, surfaces = [], [], [], []
    for up in (1, -1):
        rings = []
        for outline, gap in ((footprint, 0.0001), (fillet, 0.006)):
            ring = []
            for dx, ds in outline:
                at, normal = solids.must(solids.hit(skin, bi.P(s + ds, side * (x + dx), up * 2),
                                                   Vector((0, 0, -up))), "nav fairing foot")
                ring.append((at + normal * gap, normal))
            rings.append(ring)
        rings.append([(bi.P(s + v.y, side * (x + v.x), z + up * (height + v.z)), None) for v in foot])
        indices = []
        for level, ring in enumerate(rings):
            # Equal angles connect directly; the remaining corners form triangles.
            ring.sort(key=lambda item: math.atan2(item[0].y - bi.P(s, 0, 0).y, side * item[0].x - x))
            indices.append(list(range(len(verts), len(verts) + len(ring))))
            for point, normal in ring:
                if level == 0:
                    roots.append(len(verts))
                verts.append(point)
                surfaces.append(up)
        for outer, inner in zip(indices, indices[1:]):
            angles = lambda ids: [math.atan2(verts[i].y - bi.P(s, 0, 0).y, side * verts[i].x - x) for i in ids]
            oa, ia = angles(outer), angles(inner)
            i = j = 0
            while i < len(outer) or j < len(inner):
                advance_outer = j == len(inner) or (i < len(outer) and oa[(i + 1) % len(outer)] + (2 * math.pi if i + 1 == len(outer) else 0)
                                                   <= ia[(j + 1) % len(inner)] + (2 * math.pi if j + 1 == len(inner) else 0))
                if advance_outer:
                    face = (outer[i % len(outer)], outer[(i + 1) % len(outer)], inner[j % len(inner)])
                    i += 1
                else:
                    face = (outer[i % len(outer)], inner[(j + 1) % len(inner)], inner[j % len(inner)])
                    j += 1
                faces.append(face if side * up > 0 else face[::-1])
    suffix = "L" if side == 1 else "R"
    obj = bi.mesh_object("light_nav_mount_" + suffix, verts, faces)
    obj.data.materials.append(paint)
    obj.data.shade_smooth()
    obj["role"] = "visual"
    obj["_nav_root_indices"], obj["_nav_surface_sides"] = roots, surfaces
    return obj


def project_nav_paint(icarus, check=False):
    """Continue the skin paint across the fairings without repacking the atlas."""
    worst = 0.0
    for side in ("L", "R"):
        wing = icarus.all_objects["wing_skin_" + side]
        obj = icarus.all_objects["light_nav_mount_" + side]
        wing.data.calc_loop_triangles()
        triangles = list(wing.data.loop_triangles)
        points = [[wing.matrix_world @ wing.data.vertices[i].co for i in t.vertices] for t in triangles]
        tree = BVHTree.FromPolygons([v for tri in points for v in tri],
                                   [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(triangles))], all_triangles=True)
        source = wing.data.uv_layers["UVMap"].data
        wing_normals = wing.data.corner_normals
        normal_matrix = wing.matrix_world.to_3x3().inverted().transposed()
        target = obj.data.uv_layers.get("UVMap") or obj.data.uv_layers.new(name="UVMap")
        normals = [n.vector.copy() for n in obj.data.corner_normals]
        roots = set(obj["_nav_root_indices"])
        for loop in obj.data.loops:
            point = obj.matrix_world @ obj.data.vertices[loop.vertex_index].co
            up = obj["_nav_surface_sides"][loop.vertex_index]
            at, normal, index, _ = tree.ray_cast(Vector((point.x, point.y, up * 2)), Vector((0, 0, -up)), 5)
            if at is None:
                raise ValueError("nav fairing paint projection missed the wing")
            uv_points = [Vector((*source[i].uv, 0)) for i in triangles[index].loops]
            uv = barycentric_transform(at, *points[index], *uv_points)
            skin_normals = [normal_matrix @ wing_normals[i].vector for i in triangles[index].loops]
            root_normal = barycentric_transform(at, *points[index], *skin_normals).normalized()
            if check:
                worst = max(worst, (target.data[loop.index].uv - Vector((uv.x, uv.y))).length)
                if loop.vertex_index in roots and abs((point - at).length - 0.0001) > 0.00005:
                    raise ValueError("nav fairing fillet moved off the wing skin")
                if loop.vertex_index in roots and (obj.matrix_world.to_3x3().inverted().transposed() @ normals[loop.index]).normalized().dot(root_normal) < 0.99999:
                    raise ValueError("nav fairing fillet no longer follows the wing shading normal")
            else:
                target.data[loop.index].uv = uv.xy
                if loop.vertex_index in roots:
                    normals[loop.index] = (obj.matrix_world.to_3x3().transposed() @ root_normal).normalized()
        if not check:
            obj.data.normals_split_custom_set(normals)
    if "light_tail_fairing" in icarus.all_objects:
        obj = icarus.all_objects["light_tail_fairing"]
        skin = icarus.all_objects["stabilator_visible"]
        skin.data.calc_loop_triangles()
        triangles = list(skin.data.loop_triangles)
        points = [[skin.matrix_world @ skin.data.vertices[i].co for i in t.vertices] for t in triangles]
        tree = BVHTree.FromPolygons([v for tri in points for v in tri],
                                   [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(triangles))], all_triangles=True)
        source = skin.data.uv_layers["UVMap"].data
        target = obj.data.uv_layers.get("UVMap") or obj.data.uv_layers.new(name="UVMap")
        for loop in obj.data.loops:
            point = obj.matrix_world @ obj.data.vertices[loop.vertex_index].co
            at, _, index, _ = tree.find_nearest(point)
            uv = barycentric_transform(at, *points[index],
                                       *[Vector((*source[i].uv, 0)) for i in triangles[index].loops]).xy
            if check:
                worst = max(worst, (target.data[loop.index].uv - uv).length)
            else:
                target.data[loop.index].uv = uv
    if check and worst > 0.000001:
        raise ValueError("nav fairing paint no longer matches the skin UVs")
    return worst


def tail_light(p, mats):
    """A 52 mm white dome in a tapered, skin-following trailing-edge fairing.

    Both visuals ride the stabilator. The separate paint slot projects its existing
    UVs, so this fitting does not repack the skin atlas.
    """
    z = p["stabilator"]["sections"][0][2]
    centre = bi.P(AFT_STATION, 0, z)
    verts = []
    for s, radius in ((AFT_STATION, AFT_RADIUS), (AFT_STATION + 0.024, 0.018)):
        verts += [bi.P(s, radius * math.cos((k + 0.5) * math.tau / 8), z + radius * math.sin((k + 0.5) * math.tau / 8)) for k in range(8)]
    verts.append(bi.P(AFT_STATION + 0.038, 0, z))
    faces = [(k, (k + 1) % 8, 8 + (k + 1) % 8, 8 + k) for k in range(8)]
    faces += [(8 + k, 8 + (k + 1) % 8, 16) for k in range(8)]
    lens = bi.finish(bi.mesh_object("light_nav_aft", [v - centre for v in verts], [f[::-1] for f in faces]),
                     bpy.data.materials["Matte_black"])
    lens.location = centre
    lens["role"], lens["light"], lens["colour"] = "visual", "nav_aft", "white"

    bpy.context.view_layer.update()
    skin = solids.bvh([bpy.data.objects["stabilator_visible"]])
    roots = []
    for k in range(8):
        angle = (k + 0.5) * math.tau / 8
        up = 1 if math.sin(angle) > 0 else -1
        x = 0.060 * math.cos(angle)
        at, normal = solids.must(solids.hit(skin, bi.P(16.43, x, z + up), Vector((0, 0, -up))), "tail fairing foot")
        roots.append(at + normal * 0.0001)
    fillet = [bi.P(16.60, 0.033 * math.cos((k + 0.5) * math.tau / 8),
                  z + 0.027 * math.sin((k + 0.5) * math.tau / 8)) for k in range(8)]
    fairing = bi.finish(bi.mesh_object("light_tail_fairing", roots + fillet + verts[:8],
                                      [(a + k, a + 8 + k, a + 8 + (k + 1) % 8, a + (k + 1) % 8)
                                       for a in (0, 8) for k in range(8)]), mats["nav_fairing"])
    fairing["role"] = "visual"
    return [lens, fairing]


def build(p, mats):
    w = p["wing"]
    lamp_x = w["planform"][-1][1] - 0.075
    lamp_le, lamp_z, lamp_chord = stations.wing_at(w, lamp_x)
    made = []
    for name, kind, colour in LIGHTS:
        if kind == "nav":
            side = 1 if name.endswith("_L") else -1
            up = -1 if "lower" in name else 1
            pos = bi.P(lamp_le + lamp_chord * 0.35, side * lamp_x, lamp_z + up * NAV_HEIGHT)
        else:
            pos = gear.landing_lamp()
        rotation = Matrix.Rotation(math.pi, 4, "Y") if kind == "nav" and up < 0 else Matrix.Identity(4)
        obj = bi.empty(name, Matrix.Translation(pos) @ rotation)
        obj["light"], obj["colour"] = kind, colour
        if kind == "nav":
            obj["reference_triangles"] = 14
        made.append(obj)

    import nav_visibility
    _, lenses = nav_visibility.stock_geometry()
    for side, suffix in ((1, "L"), (-1, "R")):
        made.append(nav_fairing(bpy.data.objects["wing_" + suffix], side, mats["nav_fairing"], lenses[suffix]))
    made += tail_light(p, mats)

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
    import nav_visibility

    objects = {o.name: o for o in icarus.all_objects}
    anchors = [o for o in objects.values() if o.get("light") == "nav"]
    for side in ("L", "R"):
        fairing = objects["light_nav_mount_" + side]
        if [m.name for m in fairing.data.materials] != [NAV_PAINT] or budget.tris(fairing) != 44:
            raise ValueError("lights: each paired fairing must have 44 wing-painted triangles")
    if len(anchors) != 4 or sum(o.get("reference_triangles", 0) for o in anchors) != 56:
        raise ValueError("lights: expected four stock 14 triangle nav lenses")
    aft = objects["light_nav_aft"]
    fairing = objects["light_tail_fairing"]
    if aft.parent != objects["stabilator"] or fairing.parent != objects["stabilator"]:
        raise ValueError("lights: the rear lens and fairing must ride the stabilator")
    if aft.get("colour") != "white" or budget.tris(aft) != 24 or budget.tris(fairing) != 32:
        raise ValueError("lights: expected the white 24 triangle dome and 32 triangle trailing-edge fairing")
    if [m.name for m in fairing.data.materials] != [NAV_PAINT]:
        raise ValueError("lights: the tail fairing must share the stabilator paint")
    for side in ("L", "R"):
        for name in ("light_nav_" + side, "light_nav_lower_" + side):
            obj = objects[name]
            if obj.parent != objects["wing_skin_" + side] or obj["colour"] != ("red" if side == "L" else "green"):
                raise ValueError("lights: nav lens has the wrong wing owner or colour: " + name)
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
    paint_error = project_nav_paint(icarus, check=True)
    nav_visibility.check(icarus)
    print("lights.check PASS: four stock nav lenses, 56 triangles, wing fairings 88; rear dome 24, tail fairing 32; projected skin paint error %.8f; 3 merged skin antennas, %d triangles; formation lenses %d "
          "triangles, lens area %.4f m2 a side (Revoker %.4f); fin strips %d triangles, lens area %.4f m2 a side "
          "(Revoker %.4f); max skin gap %.4f m"
          % (paint_error, budget.measure(icarus, BUDGET["antennas"]), budget.measure(icarus, BUDGET["formation_lenses"]),
             areas["light_formation"], STOCK_LENS_AREA, budget.measure(icarus, BUDGET["fin_strips"]),
             areas["light_fin"], STOCK_FIN_LENS_AREA, worst))
