"""Matched bright-daylight runway views of round one, prior full pass and revised metal."""
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'art/blender'))
FOLDER = ROOT / '.cache/review/wave2/p9b-round2/full/bare-metal'
os.environ['OPTIX_CACHE_PATH'] = str(FOLDER.parent / 'renders/optix-cache')

import bpy
from mathutils import Vector
import full_skin_review as review


def ground(name, location, scale, colour):
    bpy.ops.mesh.primitive_plane_add(size=2, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*colour, 1)
    bsdf.inputs['Roughness'].default_value = .82
    obj.data.materials.append(mat)
    if name == 'Runway':
        noise = mat.node_tree.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 420
        ramp = mat.node_tree.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (.075, .08, .085, 1)
        ramp.color_ramp.elements[1].color = (.16, .17, .18, 1)
        mat.node_tree.links.new(noise.outputs['Fac'], ramp.inputs[0])
        mat.node_tree.links.new(ramp.outputs[0], bsdf.inputs['Base Color'])


def render():
    FOLDER.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(review.BAKE / 'skin.blend'))
    scene = review.configure_scene(bpy)
    scene.cycles.samples = 64
    scene.render.resolution_x, scene.render.resolution_y = 1200, 1400
    visible = review.visible_meshes(bpy.context.view_layer.layer_collection)
    corners = np.array([tuple(obj.matrix_world @ Vector(corner))
                        for obj in visible for corner in obj.bound_box])
    target = Vector((corners.min(axis=0) + corners.max(axis=0)) / 2)
    basis = review.camera_basis((14, -20, 24))
    projected = (corners - np.asarray(target)) @ basis.T
    span = np.ptp(projected, axis=0)
    scale = max(float(span[1]), float(span[0]) * 1400 / 1200) * 1.1
    scene.camera.location = target + Vector(basis[2] * 40)
    scene.camera.rotation_euler = (scene.camera.location - target).to_track_quat('Z', 'Y').to_euler()
    scene.camera.data.ortho_scale = scale
    floor_z = float(corners[:, 2].min()) - .015
    ground('Runway', (0, 0, floor_z), (35, 70, 1), (.12, .13, .14))
    ground('Yellow_line', (3.2, 0, floor_z + .002), (.10, 65, 1), (.8, .48, .015))
    ground('White_line', (-4.5, 0, floor_z + .003), (.09, 65, 1), (.78, .8, .79))
    world_nodes = scene.world.node_tree.nodes
    sky = world_nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'HOSEK_WILKIE'
    sky.sun_direction = Vector((-8, -5, 12)).normalized()
    sky.turbidity = 2.4
    sky.ground_albedo = .2
    scene.world.node_tree.links.new(sky.outputs[0], world_nodes['Background'].inputs[0])
    world_nodes['Background'].inputs[1].default_value = .3
    sun = bpy.data.objects['Skin_sun']
    sun.rotation_euler = Vector((-8, -5, 12)).to_track_quat('Z', 'Y').to_euler()
    sun.data.energy = 3.5
    sun.data.angle = np.deg2rad(.53)
    report = {'status': 'incomplete', 'view': 'top front three-quarter; runway; inferred from owner screenshot',
              'screenshot': 'owner screenshot',
              'lighting': {'sun_outward': [-8, -5, 12], 'energy': 3.5, 'sky': 'Hosek-Wilkie clear daylight', 'sky_strength': .3},
              'camera': {'location': list(scene.camera.location), 'target': list(target), 'ortho_scale': scale,
                         'mesh_projection_frame_fraction': (span[:2] / [scale * 1200 / 1400, scale]).tolist()},
              'resolution': [1200, 1400], 'samples': 64,
              'material': 'verified D3D11 undamaged opaque-livery max(alpha,gloss); shared metallic R; approximate Blender GGX floor',
              'limitations': 'inferred daylight/camera, no exact game sky, reflection probes, tone mapping, compression or runtime claim',
              'renders': []}
    variants = [('round1', ROOT / 'art/export/textures', .45, 'Icarus_skin_m.png'),
                ('full_before', FOLDER / 'before/art/export/textures', .45, 'Icarus_skin_m.png'),
                ('dielectric_before', FOLDER / 'dielectric-before/art/export/textures', 1., 'Icarus_skin_m.png'),
                ('full_after', FOLDER.parent / 'art/export/textures', 0., 'Icarus_livery_4_m.png')]
    for name, textures, gloss, metallic_map in variants:
        review.TEXTURES = textures
        # Each version has the same image names but different bytes.
        for image in list(bpy.data.images):
            if image.source == 'FILE':
                bpy.data.images.remove(image)
        review.preview_material(bpy, 4, False, glossiness=gloss, metallic_map=metallic_map)
        output = FOLDER / (name + '_daylight.png')
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        report['renders'].append({'variant': name, 'path': output.as_posix(), 'sha256': review.sha256(output),
                                  'glossiness': gloss, 'metallic_map': metallic_map,
                                  'maps': {n: review.sha256(textures / n) for n in review.MAPS if (textures / n).is_file()}})
    report['status'] = 'complete'
    (FOLDER / 'render_manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print('BARE METAL DAYLIGHT PASS', len(report['renders']), flush=True)


if __name__ == '__main__':
    render()
