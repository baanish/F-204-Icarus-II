"""The livery kit's paint model and UV record, from the skin bake's scene. Run only through tools/Run-Blender.ps1.

Usage: Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/livery_kit_model.py -- SKIN_BLEND OUT

Writes OUT/icarus_paint_model.blend, OUT/icarus_paint_model.fbx and OUT/skin_uv.json. The model is the exterior skin only:
every face on the skin material, one object per skin part, in world position, with the shipped atlas UVs untouched.
Its material reads the kit's maps at ../maps/ and the first example livery at ../examples/, so a painter swaps one file.
skin_uv.json holds every skin polygon's UV loop per part, which tools/livery_kit.py draws into the layout and part map.
"""
import json
from pathlib import Path
import sys

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'art/blender'))
sys.path.insert(0, str(ROOT / 'tools'))
from scrub_fbx import scrub_file  # noqa: E402
import uvs  # noqa: E402

MODEL = 'icarus_paint_model'
MATERIAL = 'Icarus_livery'
# Relative to the model's folder inside the kit; tools/livery_kit.py lays the kit out to match.
BASE_COLOUR = '../examples/Icarus_livery_1.png'
NORMAL = '../maps/Icarus_skin_n.png'
METALLIC = '../maps/Icarus_skin_m.png'


def image_node(nodes, path, colour):
    image = bpy.data.images.new(Path(path).name, 8, 8)
    image.source = 'FILE'
    image.filepath = '//' + path
    image.colorspace_settings.name = 'sRGB' if colour else 'Non-Color'
    node = nodes.new('ShaderNodeTexImage')
    node.image = image
    return node


def paint_material():
    """Unity's Standard convention, which the game's skin shader follows: metallic in red, smoothness in alpha."""
    mat = bpy.data.materials.new(MATERIAL)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes['Principled BSDF']
    base = image_node(nodes, BASE_COLOUR, True)
    links.new(base.outputs['Color'], bsdf.inputs['Base Color'])
    metal = image_node(nodes, METALLIC, False)
    split = nodes.new('ShaderNodeSeparateColor')
    links.new(metal.outputs['Color'], split.inputs['Color'])
    links.new(split.outputs['Red'], bsdf.inputs['Metallic'])
    rough = nodes.new('ShaderNodeMath')
    rough.operation = 'SUBTRACT'
    rough.inputs[0].default_value = 1.0
    links.new(metal.outputs['Alpha'], rough.inputs[1])
    links.new(rough.outputs['Value'], bsdf.inputs['Roughness'])
    normal = image_node(nodes, NORMAL, False)
    normal_map = nodes.new('ShaderNodeNormalMap')
    links.new(normal.outputs['Color'], normal_map.inputs['Color'])
    links.new(normal_map.outputs['Normal'], bsdf.inputs['Normal'])
    return mat


def skin_copy(obj, collection, mat):
    """The object's skin faces alone, baked to world space, as an unparented object of the same name."""
    mesh = obj.data.copy()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    skin_index = [i for i, m in enumerate(obj.data.materials) if m and m.name == uvs.SKIN]
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in skin_index], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    for f in bm.faces:
        f.material_index = 0
    bm.transform(obj.matrix_world)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.clear()
    mesh.materials.append(mat)
    for layer in list(mesh.uv_layers):
        if layer != mesh.uv_layers.active:
            mesh.uv_layers.remove(layer)
    mesh.uv_layers.active.name = 'UVMap'
    copy = bpy.data.objects.new(obj.name, mesh)
    collection.objects.link(copy)
    return copy


def uv_record(obj):
    uv = obj.data.uv_layers.active.data
    # Full precision: tools/livery_kit.py holds these to the export's atlas record (atlas_guard) before drawing them.
    return [[list(uv[i].uv) for i in f.loop_indices] for f in uvs.skin_faces(obj)]


def main():
    skin_blend, out = Path(sys.argv[sys.argv.index('--') + 1]), Path(sys.argv[sys.argv.index('--') + 2])
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(skin_blend))
    sources = uvs.skin_objects(bpy.data.collections['Icarus'])
    record = {'atlas_size': uvs.ATLAS_SIZE, 'mirror_pairs': [list(p) for p in uvs.MIRROR_PAIRS],
              'parts': {o.name: uv_record(o) for o in sources}}
    (out / 'skin_uv.json').write_text(json.dumps(record, separators=(',', ':')))
    scene = bpy.context.scene
    scene.name = MODEL
    collection = bpy.data.collections.new('Icarus_skin')
    scene.collection.children.link(collection)
    mat = paint_material()
    names = [o.name for o in sources]
    copies = [skin_copy(o, collection, mat) for o in sources]
    for other in [s for s in bpy.data.scenes if s != scene]:
        bpy.data.scenes.remove(other)
    for obj in [o for o in bpy.data.objects if o not in copies]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for other in [c for c in bpy.data.collections if c != collection]:
        bpy.data.collections.remove(other)
    for world in list(bpy.data.worlds):
        bpy.data.worlds.remove(world)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    for copy, name in zip(copies, names):
        copy.name = name
    blend = out / (MODEL + '.blend')
    # The kit names no folder of the machine that built it: the scene alone and what it uses (no window or file browser
    # state, which hold local folders), with the render output path cleared, and the path the file was saved to
    # (FileGlobal.filepath, a NUL-terminated field) blanked. Uncompressed so those bytes can be found; the zip compresses.
    scene.render.filepath = ''
    bpy.data.libraries.write(str(blend), {scene}, path_remap='NONE', fake_user=False, compress=False)
    data = blend.read_bytes()
    for saved in {str(blend).encode(), blend.as_posix().encode()}:
        data = data.replace(saved, bytes(len(saved)))
    blend.write_bytes(data)
    fbx = out / (MODEL + '.fbx')
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=False, object_types={'MESH'},
                             path_mode='RELATIVE', embed_textures=False, mesh_smooth_type='FACE',
                             add_leaf_bones=False, bake_anim=False)
    scrub_file(fbx)
    faces = sum(len(c.data.polygons) for c in copies)
    triangles = sum(len(p.vertices) - 2 for c in copies for p in c.data.polygons)
    print(f'LIVERY KIT MODEL PASS: {len(copies)} skin parts, {faces} faces, {triangles} triangles', flush=True)


main()
