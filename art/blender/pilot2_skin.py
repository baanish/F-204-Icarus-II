"""Current structural data and matched cameras for the per-part skin pilot."""
import argparse
import json
import os
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'art/blender'))
import bake_skin as bake
import build_icarus as bi
import internals
import skin_review
import uvs

OUT = ROOT / '.cache/review/wave2/p9b-round2'
VIEWS = {
    'radome': ((6, -7.15, .8), (0, -7.15, .12), 2.4),
    'forward': ((8, -4.9, 2.5), (.35, -4.2, .30), 5.7),
    'wing': ((6, -2, 6), (1.65, 1.1, .15), 4.8),
    'wing_upper': ((4, -3, 10), (1.8, 1.6, .1), 5.8),
    'fin': ((7, 7, 3.2), (0, 5.9, 1.65), 3.7),
}


def structure():
    bpy.ops.wm.open_mainfile(filepath=str(bake.OUT / 'geometry.blend'))
    chosen = {'radome', 'skin_forward_L', 'wing_skin_L', 'skin_mid_L', 'fin_skin'}
    objects = []
    for obj in uvs.skin_objects(bpy.data.collections['Icarus']):
        if obj.name not in chosen:
            continue
        uv = obj.data.uv_layers.active.data
        obj.data.calc_loop_triangles()
        skin = {f.index for f in uvs.skin_faces(obj)}
        triangles = []
        for tri in obj.data.loop_triangles:
            if tri.polygon_index in skin:
                triangles.append({'uv': [list(uv[i].uv) for i in tri.loops],
                                  'world': [list(obj.matrix_world @ obj.data.vertices[i].co) for i in tri.vertices]})
        objects.append({'name': obj.name, 'triangles': triangles})
    sections = []
    table = bi.PARAMS['fuselage']
    for s in np.arange(table[0][0], table[-1][0], .05):
        # The main body lobe only: intake and wing-fillet lobes are separate surfaces in the panel layout.
        hw, top, bot = [bi.pchip([r[0] for r in table], [r[i] for r in table], float(s)) for i in (1, 2, 3)]
        sections.append([float(s), bi.fuselage_shapes(bi.PARAMS, float(s))[1], hw, bot, top])
    # Skin panel layout follows the airframe: frames, spars, ribs, optional stringers and the fuselage sections.
    data = {'frames': internals.INTERNALS['frames'], 'spars': internals.INTERNALS['spars'],
            'stringers': internals.INTERNALS.get('stringers'), 'fuselage_sections': sections,
            'wing_sections': bi.wing_sections(bi.PARAMS['wing']), 'wing_surfaces': bi.PARAMS['wing_surfaces'], 'S0': bi.S0,
            'wing_profile': [list(bi.section_at(bi.wing_sections(bi.PARAMS['wing']), float(x), 'x'))
                             for x in np.linspace(.58, 3.4, 1001)],
            'objects': objects, 'views': VIEWS}
    (OUT / 'structure.json').write_text(json.dumps(data))
    print('PILOT STRUCTURE PASS', [o['name'] for o in objects], flush=True)


def render():
    cache = OUT / 'optix-cache'
    cache.mkdir(exist_ok=True)
    os.environ['OPTIX_CACHE_PATH'] = str(cache)
    bpy.ops.wm.open_mainfile(filepath=str(bake.OUT / 'skin.blend'))
    scene = bpy.context.scene
    prefs = bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
        if any(d.use for d in prefs.devices):
            scene.cycles.device = 'GPU'
    except (TypeError, RuntimeError):
        scene.cycles.device = 'CPU'
    # Review only the airframe. The source geometry, pose and camera stay identical.
    for side in ('L', 'R'):
        bpy.data.objects['pylon_inner_' + side].hide_render = True
        bpy.data.objects['pylon_inner_plug_' + side].hide_render = False
    bake.OUT = OUT
    bake.VIEWS = VIEWS
    for version in ('round1', 'pilot2'):
        skin_review.ROOT = OUT / version
        for clay in (False, True):
            skin_review.preview_material(1, clay=clay)
            direction = (4, -8, 2) if clay else (6, -8, 12)
            bpy.data.objects['Skin_sun'].rotation_euler = Vector(direction).to_track_quat('Z', 'Y').to_euler()
            for view in VIEWS:
                bake.render(version + ('_clay' if clay else '_navy'), view)
    (OUT / 'render_settings.json').write_text(json.dumps({'views': VIEWS, 'samples': scene.cycles.samples,
        'resolution': [scene.render.resolution_x, scene.render.resolution_y], 'device': scene.cycles.device,
        'navy_sun': [6, -8, 12], 'clay_sun': [4, -8, 2], 'clay': 'same normal and AO maps, grey base',
        'versions': ['round1', 'pilot2'], 'geometry': (ROOT / '.cache/review/wave2/p9b/02/skin.blend').as_posix()}, indent=2))
    print('PILOT RENDER PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('structure', 'render'))
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    OUT.mkdir(parents=True, exist_ok=True)
    {'structure': structure, 'render': render}[args.mode]()
