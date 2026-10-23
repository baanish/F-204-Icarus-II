"""Render the full pass from the retained round-one comparison cameras."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'art/blender'))
cache = ROOT / '.cache/review/wave2/p9b-round2/full/renders/optix-cache'
cache.mkdir(parents=True, exist_ok=True)
os.environ['OPTIX_CACHE_PATH'] = str(cache)

import bpy
from mathutils import Vector
import bake_skin
import full_skin_review


def render_comparisons():
    folder = full_skin_review.FULL / 'pilot_comparison'
    folder.mkdir(parents=True, exist_ok=True)
    settings = json.loads((folder.parent.parent / 'render_settings.json').read_text())
    bpy.ops.wm.open_mainfile(filepath=str(full_skin_review.BAKE / 'skin.blend'))
    scene = full_skin_review.configure_scene(bpy)
    bake_skin.OUT = folder
    bake_skin.VIEWS = settings['views']
    report = {'cameras': settings['views'], 'maps': {}, 'renders': []}
    for name in full_skin_review.MAPS:
        report['maps'][name] = full_skin_review.sha256(full_skin_review.TEXTURES / name)
    for clay in (False, True):
        material = 'clay' if clay else 'navy'
        full_skin_review.preview_material(bpy, 1, clay)
        direction = settings[material + '_sun']
        bpy.data.objects['Skin_sun'].rotation_euler = Vector(direction).to_track_quat('Z', 'Y').to_euler()
        for view in settings['views']:
            bake_skin.render('full_' + material, view)
            path = folder / ('full_' + material + '_' + view + '.png')
            report['renders'].append({'path': path.as_posix(), 'sha256': full_skin_review.sha256(path)})
    (folder / 'render_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('FULL PILOT COMPARISON PASS', len(report['renders']), flush=True)


if __name__ == '__main__':
    render_comparisons()
