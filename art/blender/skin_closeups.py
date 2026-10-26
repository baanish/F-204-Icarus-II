"""Full-resolution matched close-ups and overviews of every livery from the saved skin scene.

Run through tools/Run-Blender.ps1 after compose: ... --python art/blender/skin_closeups.py -- [--livery N] [--views a,b]
Writes <out>/livery_<n>_<view>.png and clay_<view>.png (normal and AO only, raking sun) at 2560 x 1440.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'art/blender'))
import skin_review

SCENE = ROOT / '.cache/review/wave2/p9b/02/skin.blend'
RESOLUTION = (2560, 1440)
# name: (camera location, target, focal length mm); nose is world -Y, left side +X.
VIEWS = {
    'front_quarter': ((17, -24, 11), (0, -.4, .5), 50),
    'rear_quarter': ((-17, 23, 10), (0, .4, .6), 50),
    'side': ((30, 0, 1.2), (0, 0, .7), 50),
    'top': ((0, .2, 38), (0, .2, 0), 50),
    'nose_markings': ((5.2, -5.9, 1.4), (.4, -4.5, .25), 50),
    'modex_close': ((1.9, -5.9, .55), (.48, -5.5, .14), 50),
    'roundel_close': ((1.7, -3.55, .6), (.5, -3.3, .25), 50),
    'fuselage_panels': ((3.2, -.4, 1.1), (.7, 1.3, .25), 50),
    'wing_panel': ((3.6, -1.2, 2.9), (2.0, 1.7, .02), 50),
    'aft_fuselage': ((3.4, 2.6, 1.3), (.45, 4.7, .45), 50),
}
CLAY_VIEWS = ('fuselage_panels', 'wing_panel', 'nose_markings')


def setup(samples):
    bpy.ops.wm.open_mainfile(filepath=str(SCENE))
    scene = bpy.context.scene
    cache = ROOT / '.cache/review/wave2/p9b/02/optix-cache'
    cache.mkdir(exist_ok=True)
    os.environ['OPTIX_CACHE_PATH'] = str(cache)
    prefs = bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
        scene.cycles.device = 'GPU' if any(d.use for d in prefs.devices) else 'CPU'
    except (TypeError, RuntimeError):
        scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = 'AgX'
    world = scene.world.node_tree
    world.nodes.clear()
    env = world.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(str(Path(bpy.utils.resource_path('LOCAL')) / 'datafiles/studiolights/world/courtyard.exr'))
    background = world.nodes.new('ShaderNodeBackground')
    background.inputs['Strength'].default_value = .8
    output = world.nodes.new('ShaderNodeOutputWorld')
    world.links.new(env.outputs[0], background.inputs[0])
    world.links.new(background.outputs[0], output.inputs[0])
    sun = bpy.data.objects['Skin_sun']
    sun.data.energy = 3.0
    sun.data.angle = .01
    for side in ('L', 'R'):
        bpy.data.objects['pylon_inner_' + side].hide_render = True
        bpy.data.objects['pylon_inner_plug_' + side].hide_render = False
    camera = bpy.data.objects['Skin_camera']
    camera.data.type = 'PERSP'
    camera.data.sensor_width = 36
    scene.camera = camera
    return scene, camera, sun


def aim(camera, view):
    location, target, lens = VIEWS[view]
    camera.location = location
    camera.rotation_euler = (Vector(target) - Vector(location)).to_track_quat('-Z', 'Y').to_euler()
    if view == 'top' or view.endswith('_top'):
        camera.rotation_euler.rotate_axis('Z', 1.5707963)
    camera.data.lens = lens
    camera.data.clip_start = .05


def render(scene, camera, view, path):
    aim(camera, view)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print('RENDERED', path, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT / '.cache/review/share/texture_art'))
    parser.add_argument('--livery', type=int, action='append')
    parser.add_argument('--views')
    parser.add_argument('--samples', type=int, default=96)
    parser.add_argument('--no-clay', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    # Blender's working folder is not the repository; relative output paths resolve against the repository.
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    views = args.views.split(',') if args.views else list(VIEWS)
    scene, camera, sun = setup(args.samples)
    sun.rotation_euler = Vector((6, -8, 12)).to_track_quat('Z', 'Y').to_euler()
    for livery in args.livery or [1, 2, 3, 4]:
        skin_review.preview_material(livery)
        for view in views:
            render(scene, camera, view, out / f'livery_{livery}_{view}.png')
    if not args.no_clay:
        sun.rotation_euler = Vector((4, -8, 2)).to_track_quat('Z', 'Y').to_euler()
        skin_review.preview_material(1, clay=True)
        for view in [v for v in CLAY_VIEWS if v in views]:
            render(scene, camera, view, out / f'clay_{view}.png')
    (out / 'render_settings.json').write_text(json.dumps({'views': VIEWS, 'resolution': RESOLUTION,
        'samples': args.samples, 'device': scene.cycles.device, 'world': 'Blender courtyard.exr at 0.8',
        'sun': {'livery': [6, -8, 12], 'clay': [4, -8, 2], 'energy': 3.0},
        'maps': str(ROOT / 'art/export/textures'), 'scene': str(SCENE)}, indent=2))


if __name__ == '__main__':
    main()
