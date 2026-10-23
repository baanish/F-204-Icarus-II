"""One skin atlas, shared only by declared symmetric twins. Run after the part meshes are final."""
import json
import math
import os
import sys
from collections import defaultdict

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

import cycles_device

ATLAS_SIZE = 2048
TEXEL_DENSITY = 150  # Highest density allowed by rule 6; the current skin cannot cover 60% at 128 px/m.
MARGIN_PX = 4
SKIN = "Icarus_Body"
# The single tip-to-tip stabilator and every lettering-bearing part have unique islands.
MIRROR_PAIRS = (
    ("wing_skin_L", "wing_skin_R"),
    ("lef_L_visible", "lef_R_visible"),
    ("flap_L_visible", "flap_R_visible"),
    ("aileron_L_visible", "aileron_R_visible"),
    ("speed_brake_L_visible", "speed_brake_R_visible"),
    ("intake_duct_L", "intake_duct_R"),
    ("gear_door_N_L_visible", "gear_door_N_R_visible"),
    ("gear_door_main_L_visible", "gear_door_main_R_visible"),
    ("pylon_inner_L", "pylon_inner_R"),
    ("pylon_inner_plug_L", "pylon_inner_plug_R"),
)
BUDGET = {}
CLOSEUPS = {}


def skin_faces(obj):
    return [f for f in obj.data.polygons if obj.data.materials[f.material_index].name == SKIN]


def skin_objects(icarus):
    return sorted((o for o in icarus.all_objects if o.type == "MESH" and skin_faces(o)), key=lambda o: o.name)


def mirror_loops(left, right):
    """Match reflected world vertices, then faces and corners, independently of winding and index order."""
    lv = [left.matrix_world @ v.co for v in left.data.vertices]
    tree = KDTree(len(lv))
    for i, v in enumerate(lv):
        tree.insert(v, i)
    tree.balance()
    vertex_map, error = {}, 0.0
    for v in right.data.vertices:
        w = right.matrix_world @ v.co
        w.x = -w.x
        _, index, distance = tree.find(w)
        if distance > 0.001:
            raise ValueError("uvs: %s is not symmetric with %s: %.6f m" % (right.name, left.name, distance))
        vertex_map[v.index] = index
        error = max(error, distance)
    if len(vertex_map) != len(lv) or len(set(vertex_map.values())) != len(lv):
        raise ValueError("uvs: mirror vertices are not one-to-one: %s / %s" % (left.name, right.name))
    faces = {tuple(sorted(f.vertices)): f for f in left.data.polygons}
    if len(faces) != len(left.data.polygons):
        raise ValueError("uvs: duplicate faces in " + left.name)
    loops, seen = [], set()
    for rf in right.data.polygons:
        key = tuple(sorted(vertex_map[v] for v in rf.vertices))
        lf = faces.get(key)
        if lf is None or lf.index in seen:
            raise ValueError("uvs: unmatched mirror face in " + right.name)
        seen.add(lf.index)
        if left.data.materials[lf.material_index] != right.data.materials[rf.material_index]:
            raise ValueError("uvs: mirror material mismatch in " + right.name)
        corners = {left.data.loops[i].vertex_index: i for i in lf.loop_indices}
        loops += [(corners[vertex_map[right.data.loops[i].vertex_index]], i) for i in rf.loop_indices]
    if len(seen) != len(faces) or len(loops) != len(right.data.loops):
        raise ValueError("uvs: unmatched mirror loops in " + right.name)
    return loops, error


def islands(mesh):
    """Faces connected across an uncut edge, in stable face order."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    todo = set(bm.faces)
    groups = []
    while todo:
        seed = min(todo, key=lambda f: f.index)
        todo.remove(seed)
        group, stack = [], [seed]
        while stack:
            f = stack.pop()
            group.append(f.index)
            for e in f.edges:
                if not e.seam:
                    for other in e.link_faces:
                        if other in todo:
                            todo.remove(other)
                            stack.append(other)
        groups.append(sorted(group))
    bm.free()
    return groups


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def triangle_area(points):
    return abs(cross(*points)) / 2


def unwrap_islands(scratch):
    for attempt in range(3):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0)
        bpy.ops.uv.average_islands_scale()
        bpy.ops.object.mode_set(mode="OBJECT")
        folded = 0
        for _, temp, _ in scratch:
            mesh = temp.data
            mesh.calc_loop_triangles()
            uv = mesh.uv_layers.active.data
            for group in islands(mesh):
                selected = set(group)
                ts = [t for t in mesh.loop_triangles if t.polygon_index in selected]
                area = sum(t.area for t in ts)
                uv_area = sum(triangle_area([uv[i].uv for i in t.loops]) for t in ts)
                if not area or not uv_area:
                    raise ValueError("uvs: zero-area unwrap in " + temp.name)
                scale = TEXEL_DENSITY / ATLAS_SIZE * math.sqrt(area / uv_area)
                for fi in group:
                    for i in mesh.polygons[fi].loop_indices:
                        uv[i].uv *= scale
                triangles = [(temp.name, t.polygon_index, tuple(tuple(uv[i].uv) for i in t.loops)) for t in ts]
                overlaps = overlap_count(triangles)
                if overlaps:
                    # ABF can fold a sharp seam back onto a neighbouring panel. Open each folded face's perimeter.
                    bad = {fi for _, a, _, b in overlaps for fi in (a, b)}
                    edges = {tuple(sorted(key)) for fi in bad for key in mesh.polygons[fi].edge_keys}
                    for edge in mesh.edges:
                        if tuple(sorted(edge.vertices)) in edges:
                            edge.use_seam = True
                    folded += len(bad)
        if not folded:
            return
        print("uvs: opened perimeters of %d folded faces" % folded)
    raise ValueError("uvs: angle-based unwrap still folds after opening the affected face perimeters")


def unwrap(icarus):
    import trims

    objects = skin_objects(icarus)
    by_name = {o.name: o for o in objects}
    mappings = [(by_name[a], by_name[b], mirror_loops(by_name[a], by_name[b])[0]) for a, b in MIRROR_PAIRS]
    right_names = {b for _, b in MIRROR_PAIRS}
    scratch = []
    try:
        for obj in objects:
            if obj.name in right_names:
                continue
            faces = skin_faces(obj)
            mesh = bpy.data.meshes.new("uv_scratch_" + obj.name)
            mesh.from_pydata([obj.matrix_world @ v.co for v in obj.data.vertices], [], [tuple(f.vertices) for f in faces])
            temp = bpy.data.objects.new(mesh.name, mesh)
            bpy.context.scene.collection.objects.link(temp)
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.normal_update()
            for edge in bm.edges:
                # Projection boundaries open closed lofts without cutting across a flat panel.
                axes = set()
                for face in edge.link_faces:
                    axis = max(range(3), key=lambda i: abs(face.normal[i]))
                    axes.add((axis, face.normal[axis] < 0))
                edge.seam = (not edge.is_manifold or edge.calc_face_angle(0) > math.radians(40) or len(axes) > 1)
            bm.to_mesh(mesh)
            bm.free()
            mesh.uv_layers.new(name="UVMap")
            scratch.append((obj, temp, faces))
        bpy.ops.object.select_all(action="DESELECT")
        for _, temp, _ in scratch:
            temp.select_set(True)
        bpy.context.view_layer.objects.active = scratch[0][1]
        unwrap_islands(scratch)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.pack_islands(rotate=True, scale=False, margin_method="ADD", margin=MARGIN_PX / ATLAS_SIZE,
                                shape_method="CONCAVE")
        bpy.ops.object.mode_set(mode="OBJECT")
        for obj, temp, faces in scratch:
            dest = obj.data.uv_layers.get("UVMap") or obj.data.uv_layers.new(name="UVMap")
            source = temp.data.uv_layers.active.data
            for sf, df in zip(temp.data.polygons, faces):
                for si, di in zip(sf.loop_indices, df.loop_indices):
                    dest.data[di].uv = source[si].uv
            # Store the actual skin seams on the export mesh too.
            seams = {tuple(sorted(e.vertices)): e.use_seam for e in temp.data.edges}
            for e in obj.data.edges:
                if tuple(sorted(e.vertices)) in seams:
                    e.use_seam = seams[tuple(sorted(e.vertices))]
        for left, right, loops in mappings:
            dest = right.data.uv_layers.get("UVMap") or right.data.uv_layers.new(name="UVMap")
            source = left.data.uv_layers.active.data
            for li, ri in loops:
                dest.data[ri].uv = source[li].uv
        trims.project(icarus)
    finally:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for _, temp, _ in scratch:
            mesh = temp.data
            bpy.data.objects.remove(temp, do_unlink=True)
            bpy.data.meshes.remove(mesh)


def clipped_area(a, b):
    """Triangle intersection area, excluding shared edges and corners."""
    subject = list(a)
    if cross(*b) < 0:
        b = tuple(reversed(b))
    for start, end in zip(b, b[1:] + b[:1]):
        result = []
        for p, q in zip(subject, subject[1:] + subject[:1]):
            dp, dq = cross(start, end, p), cross(start, end, q)
            if dp >= 0:
                result.append(p)
            if (dp > 0 > dq) or (dq > 0 > dp):
                t = dp / (dp - dq)
                result.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        subject = result
        if len(subject) < 3:
            return 0.0
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(subject, subject[1:] + subject[:1]))) / 2


def overlap_count(triangles):
    grid, overlaps = defaultdict(list), []
    for index, (name, face, points) in enumerate(triangles):
        lo = [min(v[a] for v in points) for a in range(2)]
        hi = [max(v[a] for v in points) for a in range(2)]
        cells = [(x, y) for x in range(math.floor(lo[0] * 64), math.floor(hi[0] * 64) + 1)
                 for y in range(math.floor(lo[1] * 64), math.floor(hi[1] * 64) + 1)]
        candidates = {i for cell in cells for i in grid[cell]}
        for other in candidates:
            oname, oface, opoints = triangles[other]
            if clipped_area(points, opoints) * ATLAS_SIZE ** 2 > 0.01:
                overlaps.append((name, face, oname, oface))
        for cell in cells:
            grid[cell].append(index)
    return overlaps


def island_margin(objects):
    edges, boundaries = defaultdict(list), []
    parent = {}

    def root(face):
        while parent[face] != face:
            parent[face] = parent[parent[face]]
            face = parent[face]
        return face

    for obj in objects:
        uv = obj.data.uv_layers.active.data
        for face in skin_faces(obj):
            key = (obj.name, face.index)
            parent[key] = key
            points = [(obj.data.loops[i].vertex_index, tuple(uv[i].uv)) for i in face.loop_indices]
            for (vi, a), (vj, b) in zip(points, points[1:] + points[:1]):
                edge = (obj.name, tuple(sorted(((vi, tuple(round(c, 7) for c in a)),
                                                (vj, tuple(round(c, 7) for c in b))))))
                edges[edge].append((key, a, b))
    for entries in edges.values():
        for face, _, _ in entries[1:]:
            parent[root(face)] = root(entries[0][0])
        if len(entries) == 1:
            boundaries.append(entries[0])

    def point_distance(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / max(dx * dx + dy * dy, 1e-30)))
        return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)

    grid, minimum = defaultdict(list), math.inf
    for index, (face, a, b) in enumerate(boundaries):
        lo = [math.floor(min(a[k], b[k]) * 64) - 1 for k in range(2)]
        hi = [math.floor(max(a[k], b[k]) * 64) + 1 for k in range(2)]
        cells = [(x, y) for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1)]
        for other in {i for cell in cells for i in grid[cell]}:
            oface, c, d = boundaries[other]
            if root(face) == root(oface):
                continue
            distance = min(point_distance(a, c, d), point_distance(b, c, d),
                           point_distance(c, a, b), point_distance(d, a, b))
            minimum = min(minimum, distance)
        for cell in cells:
            grid[cell].append(index)
    return minimum * ATLAS_SIZE


def weighted_percentile(values, fraction):
    target = sum(weight for _, weight in values) * fraction
    cumulative = 0.0
    for value, weight in sorted(values):
        cumulative += weight
        if cumulative >= target:
            return value
    raise ValueError("uvs: no skin samples")


def check(icarus):
    import trims

    objects = skin_objects(icarus)
    by_name = {o.name: o for o in objects}
    mirrors = []
    for a, b in MIRROR_PAIRS:
        left, right = by_name[a], by_name[b]
        loops, error = mirror_loops(left, right)
        lu, ru = left.data.uv_layers.active.data, right.data.uv_layers.active.data
        # Trim faces have their own projection; only skin corners share the atlas.
        skin_loops = {i for f in skin_faces(left) for i in f.loop_indices}
        unmatched = sum((lu[i].uv - ru[j].uv).length > 1e-7 for i, j in loops if i in skin_loops)
        if unmatched:
            raise ValueError("uvs: %s has %d unmatched mirror loops" % (b, unmatched))
        mirrors.append({"left": a, "right": b, "symmetry_error_m": error, "unmatched_loops": unmatched,
                        "skin_loops": len(skin_loops)})
    right_names = {b for _, b in MIRROR_PAIRS}
    values, unique_triangles, zero, outside = [], [], [], []
    area = 0.0
    for obj in objects:
        mesh = obj.data
        if not mesh.uv_layers.active:
            raise ValueError("uvs: no UVMap on " + obj.name)
        uv = mesh.uv_layers.active.data
        faces = {f.index for f in skin_faces(obj)}
        for fi in faces:
            points = [uv[i].uv for i in mesh.polygons[fi].loop_indices]
            if any(not math.isfinite(c) or c < -1e-7 or c > 1 + 1e-7 for p in points for c in p):
                outside.append((obj.name, fi))
        mesh.calc_loop_triangles()
        for tri in mesh.loop_triangles:
            if tri.polygon_index not in faces:
                continue
            points = tuple(tuple(uv[i].uv) for i in tri.loops)
            ua = triangle_area(points)
            if ua < 1e-16:
                zero.append((obj.name, tri.polygon_index))
            world = [obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices]
            wa = (world[1] - world[0]).cross(world[2] - world[0]).length / 2
            if wa > 1e-16:
                values.append((ATLAS_SIZE * math.sqrt(ua / wa), wa))
            if obj.name not in right_names:
                area += ua
                unique_triangles.append((obj.name, tri.polygon_index, points))
    overlaps = overlap_count(unique_triangles)
    margin = island_margin([o for o in objects if o.name not in right_names])
    p10, median, p90 = [weighted_percentile(values, p) for p in (0.1, 0.5, 0.9)]
    report = {"atlas_size": ATLAS_SIZE, "target_px_per_m": TEXEL_DENSITY, "median_px_per_m": median,
              "p10_px_per_m": p10, "p90_px_per_m": p90, "atlas_use": area,
              "mirrors": mirrors, "zero_area_triangles": len(zero), "outside_faces": len(outside),
              "overlap_triangle_pairs": len(overlaps), "skin_objects": len(objects),
              "canonical_triangles": len(unique_triangles), "min_island_margin_px": margin,
              "trim": trims.check(icarus)}
    print("uvs measurements: " + json.dumps(report, sort_keys=True))
    problems = []
    if not (110 <= TEXEL_DENSITY <= 150 and 110 - 0.01 <= median <= 150 + 0.01
            and abs(median / TEXEL_DENSITY - 1) <= 0.1
            and 0.9 * median <= p10 <= p90 <= 1.1 * median):
        problems.append("density %.3f / %.3f / %.3f (p10 / median / p90)" % (p10, median, p90))
    if outside:
        problems.append("%d faces outside atlas: %s" % (len(outside), outside[:5]))
    if zero:
        problems.append("%d zero-area triangles: %s" % (len(zero), zero[:5]))
    if overlaps:
        problems.append("%d undeclared overlaps: %s" % (len(overlaps), overlaps[:5]))
    if margin < MARGIN_PX - 0.01:
        problems.append("island margin %.3f px < %d" % (margin, MARGIN_PX))
    if problems:
        raise ValueError("uvs: " + "; ".join(problems))
    print("uvs check PASS: p10 %.3f, median %.3f, p90 %.3f px/m; atlas %.2f%%; %d mirror pairs"
          % (p10, median, p90, 100 * area, len(mirrors)))
    return report


def render_review(icarus, out_dir):
    """Four metric checker views and a part-coloured atlas with the canonical mirror labels."""
    import colorsys
    import review_sheet

    os.makedirs(out_dir, exist_ok=True)
    cube = bpy.data.objects.get("Cube")
    if cube is not None:
        bpy.data.objects.remove(cube, do_unlink=True)
    report = check(icarus)
    with open(os.path.join(out_dir, "measurements.json"), "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    cycles_device.use_gpu(scene)
    scene.cycles.samples = 24
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.12, 0.15, 0.19, 1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.7
    light = bpy.data.objects.new("UV_review_sun", bpy.data.lights.new("UV_review_sun", "SUN"))
    scene.collection.objects.link(light)
    light.data.energy = 2.5
    light.rotation_euler = (0.4, -0.5, -0.5)
    mat = bpy.data.materials[SKIN]
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.7
    coord = nodes.new("ShaderNodeTexCoord")
    scale = nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    scale.inputs[3].default_value = 128 / TEXEL_DENSITY
    checker = nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = ATLAS_SIZE / 32
    checker.inputs["Color1"].default_value = (0.04, 0.1, 0.18, 1)
    checker.inputs["Color2"].default_value = (0.8, 0.8, 0.72, 1)
    links = mat.node_tree.links
    links.new(coord.outputs["UV"], scale.inputs[0])
    links.new(scale.outputs[0], checker.inputs["Vector"])
    links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs[0], output.inputs["Surface"])
    for name in ("References", "Colliders", "LOD1"):
        collection = bpy.data.collections.get(name)
        if collection:
            collection.hide_render = True
    cam = review_sheet.camera("UV_review_camera")
    cam.data.type = "ORTHO"
    views = {
        "checker_top": ((0, 0, 40), (0, 0, 0), 20),
        "checker_belly": ((0, 0, -40), (0, 0, 0), 20),
        "checker_side": ((40, 0, 0.5), (0, 0, 0.5), 20),
        "checker_three_quarter": ((16, -22, 13), (0, 0, 0.4), 20),
    }
    for name, (location, target, ortho) in views.items():
        cam.location = location
        direction = Vector(target) - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        if name in ("checker_top", "checker_belly"):
            cam.rotation_euler.rotate_axis("Z", math.pi / 2)
        cam.data.ortho_scale = ortho
        review_sheet.render_view(scene, cam, os.path.join(out_dir, name + ".png"), (1800, 1050))
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "FLAT"
    shading.color_type = "MATERIAL"
    shading.show_shadows = False
    shading.show_cavity = False
    shading.show_specular_highlight = False
    shading.show_object_outline = False
    shading.background_type = "WORLD"
    scene.world.color = (0.025, 0.025, 0.025)
    hidden = [(o, o.hide_render) for o in icarus.all_objects]
    for obj, _ in hidden:
        obj.hide_render = True
    created = []
    white = bpy.data.materials.new("UV_label_white")
    white.diffuse_color = (0.95, 0.95, 0.95, 1)

    def label(body, x, y, size, material=white):
        data = bpy.data.curves.new("UV_label", "FONT")
        data.body, data.size = body, size
        obj = bpy.data.objects.new("UV_label", data)
        scene.collection.objects.link(obj)
        obj.location = (x, y, 0.01)
        data.materials.append(material)
        created.append(obj)

    canonical = {b: a for a, b in MIRROR_PAIRS}
    twins = dict(MIRROR_PAIRS)
    objects = [o for o in skin_objects(icarus) if o.name not in canonical]
    for index, obj in enumerate(objects):
        material = bpy.data.materials.new("UV_part_" + obj.name)
        material.diffuse_color = (*colorsys.hsv_to_rgb(index * 0.618034 % 1, 0.55, 0.9), 1)
        uv = obj.data.uv_layers.active.data
        faces = skin_faces(obj)
        verts = [(uv[i].uv.x, uv[i].uv.y, 0) for f in faces for i in f.loop_indices]
        polygons, offset = [], 0
        for face in faces:
            polygons.append(tuple(range(offset, offset + len(face.loop_indices))))
            offset += len(face.loop_indices)
        mesh = bpy.data.meshes.new("UV_layout_" + obj.name)
        mesh.from_pydata(verts, [], polygons)
        layout = bpy.data.objects.new(mesh.name, mesh)
        scene.collection.objects.link(layout)
        mesh.materials.append(material)
        created.append(layout)
        largest = max(faces, key=lambda f: f.area)
        center = sum((uv[i].uv for i in largest.loop_indices), Vector((0, 0))) / len(largest.loop_indices)
        marker = "%02d" % (index + 1)
        label(marker, center.x, center.y, 0.013)
        name = obj.name + (" = " + twins[obj.name] if obj.name in twins else "")
        label(marker + "  " + name, 1.025, 0.94 - index * 0.031, 0.012, material)
    label("2048 skin atlas | %.0f px/m | %.2f%% covered" % (TEXEL_DENSITY, 100 * report["atlas_use"]),
          0.01, 1.025, 0.018)
    label("L is canonical; matching R shares its islands", 1.025, 0.985, 0.013)
    cam.location = (0.84, 0.52, 10)
    cam.rotation_euler = (0, 0, 0)
    cam.data.ortho_scale = 1.78
    review_sheet.render_view(scene, cam, os.path.join(out_dir, "atlas_layout.png"), (3400, 2100))
    for obj in created:
        bpy.data.objects.remove(obj, do_unlink=True)
    for obj, hide in hidden:
        obj.hide_render = hide
    print("uvs review:", out_dir)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_icarus

    build_icarus.build()
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    render_review(bpy.data.collections["Icarus"], os.path.abspath(args[0] if args else ".cache/review/wave2/p9a/01"))
