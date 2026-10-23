"""Skin geometry and AO bake, seam audit and review renders. Run only through tools/Run-Blender.ps1."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "art/blender"))
import cycles_device
import uvs

OUT = ROOT / ".cache/review/wave2/p9b/02"
VIEWS = {
    "top": ((0, 0, 35), (0, 0, 0), 20),
    "side": ((28, 0, 1), (0, 0, 0.6), 20),
    "front_quarter": ((16, -23, 12), (0, 0, 0.4), 18),
    "rear_quarter": ((-16, 22, 11), (0, 0, 0.4), 18),
    "nose": ((6, -9, 3), (0, -5.35, 0.35), 5.4),
    "wing_root": ((8, -5, 6), (0.85, -0.1, 0.65), 4.3),
}


def render(name, view):
    scene = bpy.context.scene
    cam = bpy.data.objects["Skin_camera"]
    location, target, scale = VIEWS[view]
    cam.location = location
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    if view == "top":
        cam.rotation_euler.rotate_axis("Z", np.pi / 2)
    cam.data.ortho_scale = scale
    scene.camera = cam
    scene.render.filepath = str(OUT / (name + "_" + view + ".png"))
    bpy.ops.render.render(write_still=True)


def preview():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    cycles_device.use_gpu(scene)
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.16, 0.19, 0.24, 1)
    bg.inputs[1].default_value = 0.7
    light = bpy.data.objects.new("Skin_sun", bpy.data.lights.new("Skin_sun", "SUN"))
    scene.collection.objects.link(light)
    light.data.energy = 2.5
    light.rotation_euler = (0.4, -0.5, -0.5)
    cam = bpy.data.objects.new("Skin_camera", bpy.data.cameras.new("Skin_camera"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    for name in ("References", "Colliders", "LOD1"):
        collection = bpy.data.collections.get(name)
        if collection:
            collection.hide_render = True
    mat = bpy.data.materials[uvs.SKIN]
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.28, 0.34, 0.40, 1)
    bsdf.inputs["Metallic"].default_value = 0
    bsdf.inputs["Roughness"].default_value = 0.65


def prepare():
    import build_icarus

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    metrics = build_icarus.build()
    icarus = bpy.data.collections["Icarus"]
    report = uvs.check(icarus)
    (OUT / "geometry_checks.json").write_text(json.dumps({"build": metrics, "uv": report}, indent=2))
    objects = uvs.skin_objects(icarus)
    right = {r for _, r in uvs.MIRROR_PAIRS}
    canonical = [o for o in objects if o.name not in right]
    verts, faces, coords, ids, smooth = [], [], [], [], []
    parts, triangles = [], []
    for part_id, obj in enumerate(canonical, 1):
        parts.append(obj.name)
        offset = len(verts)
        verts.extend(tuple(obj.matrix_world @ v.co) for v in obj.data.vertices)
        skin = set(f.index for f in uvs.skin_faces(obj))
        for f in obj.data.polygons:
            if f.index not in skin:
                continue
            faces.append([offset + i for i in f.vertices])
            coords.extend(tuple(obj.data.uv_layers.active.data[i].uv) for i in f.loop_indices)
            ids.extend([part_id / 64] * len(f.vertices))
            smooth.append(f.use_smooth)
        obj.data.calc_loop_triangles()
        for t in obj.data.loop_triangles:
            if t.polygon_index in skin:
                triangles.append({"part": part_id, "uv": [list(obj.data.uv_layers.active.data[i].uv) for i in t.loops]})
    (OUT / "atlas_triangles.json").write_text(json.dumps({"parts": parts, "triangles": triangles}))
    mesh = bpy.data.meshes.new("Skin_bake_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for loop, co in zip(uv.data, coords):
        loop.uv = co
    attr = mesh.color_attributes.new(name="Skin_part", type="FLOAT_COLOR", domain="CORNER")
    for element, value in zip(attr.data, ids):
        element.color = (value, value, value, 1)
    for f, value in zip(mesh.polygons, smooth):
        f.use_smooth = value
    obj = bpy.data.objects.new("Skin_bake", mesh)
    bpy.context.scene.collection.objects.link(obj)
    mat = bpy.data.materials.new("Skin_bake")
    mat.use_nodes = True
    mesh.materials.append(mat)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    links.new(emit.outputs[0], output.inputs["Surface"])
    geo = nodes.new("ShaderNodeNewGeometry")
    part = nodes.new("ShaderNodeVertexColor")
    part.layer_name = "Skin_part"
    target = nodes.new("ShaderNodeTexImage")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    cycles_device.use_gpu(scene)
    scene.cycles.samples = 1
    scene.render.bake.margin = 0
    scene.render.bake.use_clear = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # geometry_maps.npz feeds the generated paint registration; atlas_geometry.npz is the production atlas.
    for size, filename in ((uvs.PAINT_SIZE, "geometry_maps.npz"), (uvs.ATLAS_SIZE, "atlas_geometry.npz")):
        arrays = {}
        for name, socket in (("position", geo.outputs["Position"]), ("normal", geo.outputs["Normal"]), ("part", part.outputs["Color"])):
            links.new(socket, emit.inputs["Color"])
            img = bpy.data.images.new("Skin_" + name, width=size, height=size, alpha=True, float_buffer=True)
            img.colorspace_settings.name = "Non-Color"
            target.image = img
            nodes.active = target
            bpy.ops.object.bake(type="EMIT")
            pixels = np.empty(size * size * 4, dtype=np.float32)
            img.pixels.foreach_get(pixels)
            arrays[name] = pixels.reshape(size, size, 4)[::-1].copy()
            bpy.data.images.remove(img)
        arrays["part"] = np.rint(arrays["part"][:, :, 0] * 64).astype(np.uint8)
        np.savez_compressed(OUT / filename, **arrays)
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "geometry.blend"))
    bake_ao(canonical)
    preview()
    render("reference", "front_quarter")
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "skin.blend"))
    print("SKIN PREPARE PASS", OUT, flush=True)


def resume_ao():
    bpy.ops.wm.open_mainfile(filepath=str(OUT / "geometry.blend"))
    right = {r for _, r in uvs.MIRROR_PAIRS}
    canonical = [o for o in uvs.skin_objects(bpy.data.collections['Icarus']) if o.name not in right]
    bake_ao(canonical)
    preview()
    render('reference', 'front_quarter')
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'skin.blend'))
    print('SKIN AO RESUME PASS', flush=True)


def audit():
    from collections import defaultdict

    bpy.ops.wm.open_mainfile(filepath=str(OUT / "geometry.blend"))
    right = {r for _, r in uvs.MIRROR_PAIRS}
    edges = defaultdict(list)
    for obj in uvs.skin_objects(bpy.data.collections["Icarus"]):
        if obj.name in right:
            continue
        uv = obj.data.uv_layers.active.data
        for f in uvs.skin_faces(obj):
            centre = sum((uv[i].uv for i in f.loop_indices), Vector((0, 0))) / len(f.loop_indices)
            for j, a in enumerate(f.loop_indices):
                b = f.loop_indices[(j + 1) % len(f.loop_indices)]
                aa, bb = [tuple(round(v, 4) for v in obj.matrix_world @ obj.data.vertices[obj.data.loops[i].vertex_index].co)
                          for i in (a, b)]
                ua, ub = uv[a].uv.copy(), uv[b].uv.copy()
                if aa > bb:
                    aa, bb, ua, ub = bb, aa, ub, ua
                if aa == bb:
                    continue
                edges[(aa, bb)].append((obj.name, ua, ub, centre, obj.matrix_world.to_3x3() @ f.normal))
    samples = []
    for endpoints, pair in edges.items():
        if len(pair) != 2:
            continue
        a, b = pair
        if a[4].dot(b[4]) < 0.95 or max((a[i] - b[i]).length for i in (1, 2)) < 1 / uvs.ATLAS_SIZE:
            continue
        uvsides = []
        for record in pair:
            point = (record[1] + record[2]) / 2
            inward = record[3] - point
            if inward.length > 0:
                point += inward.normalized() * (0.5 / uvs.ATLAS_SIZE)
            uvsides.append(list(point))
        samples.append({"parts": [a[0], b[0]], "world_edge": endpoints, "uv": uvsides})
    (OUT / "seam_samples.json").write_text(json.dumps(samples))
    print("SKIN AUDIT PASS", len(samples), "seam pairs")


from skin_review import bake_ao, review_maps


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "ao", "audit", "review"))
    parser.add_argument('--livery', type=int, choices=range(1, 5))
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        prepare()
    elif args.mode == "ao":
        resume_ao()
    elif args.mode == "audit":
        audit()
    else:
        review_maps(args.livery)
