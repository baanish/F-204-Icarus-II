"""Matched decal and finish views in Navy and Bare Metal from the saved skin scene.

Run through tools/Run-Blender.ps1 after compose:
    ... --background --factory-startup --python-exit-code 1 --python tools/review_decals.py -- --out <absolute folder>
Writes <out>/livery_<n>_<view>.png at 2560 x 1440. Lit lenses take the Revoker's slimelight_on emission.
Select close-ups with --views tail_side,wing_left_top,wing_right_top,nose_finish.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'art/blender'))
import skin_closeups
import skin_review

# name: (camera location, target, focal length mm); nose is world -Y, left side +X.
VIEWS = {
    'owner_rescue': ((2.3, -3.9, 1.25), (.45, -3.55, .42), 40),
    'owner_fin': ((5.6, 7.6, 1.2), (0, 6.2, 1.75), 50),
    'side_left': ((30, 0, 1.2), (0, 0, .7), 50),
    'side_right': ((-30, 0, 1.2), (0, 0, .7), 50),
    'fin_close': ((5.4, 6.1, 1.85), (0, 6.1, 1.85), 50),
    'fin_strip': ((2.6, 4.7, 2.1), (0, 5.55, 1.7), 50),
    'tail_side': ((8, 5.2, .65), (0, 5.2, .65), 50),
    'nose_finish': ((5, -10.5, 1.7), (0, -6.9, .15), 50),
    'wing_left_top': ((1.98, 1.55, 8.4), (1.98, 1.55, 0), 50),
    'wing_right_top': ((-1.98, 1.55, 8.4), (-1.98, 1.55, 0), 50),
}
STOCK_OFF = (0.473, 0.612, 0.537, 1)  # light_green_off _Color
STOCK_ON = (0.047, 2.996, 0.329)  # slimelight_on _EmissionColor


def lens(lit):
    """The stock off colour, or the stock lit emission, on every formation lens."""
    mat = bpy.data.materials['light_green_off']
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1) if lit else STOCK_OFF
    bsdf.inputs['Roughness'].default_value = .25
    if lit:
        strength = max(STOCK_ON)
        bsdf.inputs['Emission Color'].default_value = (*[c / strength for c in STOCK_ON], 1)
        bsdf.inputs['Emission Strength'].default_value = strength * 4
    links.new(bsdf.outputs[0], output.inputs['Surface'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--livery', type=int, action='append')
    parser.add_argument('--samples', type=int, default=96)
    parser.add_argument('--views', help='Comma-separated view names; omit for the full review including lit lenses')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    skin_closeups.VIEWS.update(VIEWS)
    scene, camera, sun = skin_closeups.setup(args.samples)
    sun.rotation_euler = skin_closeups.Vector((6, -8, 12)).to_track_quat('Z', 'Y').to_euler()
    strips = any(o.name.startswith('light_fin_') for o in bpy.data.objects)
    for livery in args.livery or [1, 4]:
        skin_review.preview_material(livery)
        lens(False)
        for view in args.views.split(',') if args.views else VIEWS:
            skin_closeups.render(scene, camera, view, out / f'livery_{livery}_{view}.png')
        if not args.views:
            lens(True)
            skin_closeups.render(scene, camera, 'fin_strip', out / f'livery_{livery}_fin_strip_lit.png')
            skin_closeups.render(scene, camera, 'side_left', out / f'livery_{livery}_side_left_lit.png')
    print('DECAL REVIEW PASS', out, 'fin strips' if strips else 'no fin strips', flush=True)
    (out / 'render_settings.json').write_text(json.dumps({
        'views': {name: VIEWS[name] for name in (args.views.split(',') if args.views else VIEWS)},
        'resolution': skin_closeups.RESOLUTION, 'samples': args.samples,
        'maps_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in sorted((ROOT / 'art/export/textures').glob('*.png'))}}, indent=2) + '\n')


if __name__ == '__main__':
    main()
