"""Compose nine skin PNGs from preserved generated art and the current Blender bakes."""
import argparse
import hashlib
import json
import subprocess

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from rasterize import ROOT, OUT, SOURCE, EXPORT, read_source, save_map, sample, smoothstep, triplanar
from liveries import specifications, paint
from insignia import sources, place_decals
from panels import relief, tangent_normal
from damage import compose_damage

REGIONS = {'nw': (0, 0), 'ne': (896, 0), 'sw': (0, 896), 'se': (896, 896)}


def assemble():
    total = np.zeros((2048, 2048, 3), np.float64)
    weights = np.zeros((2048, 2048), np.float64)
    yy, xx = np.mgrid[:1152, :1152]
    for name, (x, y) in REGIONS.items():
        source = Image.open(SOURCE / ('round2_base_' + name + '.png')).convert('RGB')
        if min(source.size) < 1152:
            raise ValueError('Source region below required sampling density: ' + name)
        rgb = np.asarray(source.resize((1152, 1152), Image.Resampling.LANCZOS), np.float64) / 255
        wx = np.clip((xx + .5) / 256, 0, 1) if x else np.clip((1151.5 - xx) / 256, 0, 1)
        wy = np.clip((yy + .5) / 256, 0, 1) if y else np.clip((1151.5 - yy) / 256, 0, 1)
        weight = wx * wy
        total[y:y + 1152, x:x + 1152] += rgb * weight[..., None]
        weights[y:y + 1152, x:x + 1152] += weight
    if np.any(weights == 0):
        raise ValueError('Generated region coverage has a hole')
    return total / weights[..., None]


def compose():
    OUT.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    data = np.load(OUT / 'geometry_maps.npz')
    pos, normal, part = data['position'][..., :3], data['normal'][..., :3], data['part']
    names = json.loads((OUT / 'atlas_triangles.json').read_text())['parts']
    used = part > 0
    fade = smoothstep((distance_transform_edt(used) - 1) / 6)
    generated = assemble()
    nozzle_parts = [name for name in names if name == 'nozzle' or name.startswith(('nozzle_petal_', 'nozzle_seal_'))]
    nozzle = np.isin(part, [names.index(name) + 1 for name in nozzle_parts])
    if nozzle.any():
        # New nozzle islands have no matching source-atlas silhouettes; use the accepted unmarked metal art.
        generated[nozzle] = triplanar(read_source('bare_metal.png'), pos[nozzle], normal[nozzle], 1.8)
    Image.fromarray(np.uint8(generated * 255 + .5)).save(OUT / 'generated_base_assembled.png')
    height, cavity, residual, confidence, surface_report = relief(generated, pos, part, names, fade)
    save_map(EXPORT / 'Icarus_skin_n.png', tangent_normal(height, used), used)
    baked = np.load(OUT / 'ao_maps.npz')
    ao = np.clip(baked['combined'] * cavity, 0, 1)
    save_map(EXPORT / 'Icarus_skin_ao.png', np.repeat(ao[..., None], 3, axis=-1), used)
    bare = (pos[..., 1] > 5.1) & (pos[..., 2] < .6)
    metallic = np.zeros((*part.shape, 4), np.float32)
    metallic[..., 0] = bare
    groove = np.clip(-height / .5, 0, 1)
    worn_edge = np.clip(abs(residual) / .2, 0, 1)
    metallic[..., 3] = np.where(bare, .6, .4) - .08 * groove - .04 * worn_edge
    save_map(EXPORT / 'Icarus_skin_m.png', metallic, used)
    np.savez_compressed(OUT / 'surface_fields.npz', height=height.astype(np.float32),
                        cavity=cavity.astype(np.float32), groove=groove.astype(np.float32))
    dmg_b, dmg_n = compose_damage(pos, normal, used, fade, height)
    save_map(EXPORT / 'Icarus_skin_dmg_b.png', dmg_b, used)
    save_map(EXPORT / 'Icarus_skin_dmg_n.png', dmg_n, used)
    decals = sources()
    report = {'edge_fade_px': 7, 'gutter_dilation_px': 8, 'surface_relief': surface_report, 'coverage': float(used.mean()),
              'generated_detail_overrides': {'source': 'bare_metal.png', 'projection': 'reflected world triplanar',
                                             'scale_m': 1.8, 'parts': nozzle_parts},
              'full_detail_fraction': float(((fade == 1) & (confidence == 1)).sum() / used.sum()),
              'source_detail_by_part': {name: {'skin_texels': int((part == i).sum()),
                  'source_valid_fraction': float((confidence[part == i] > 0).mean()),
                  'full_detail_fraction': float(((fade[part == i] == 1) & (confidence[part == i] == 1)).mean())}
                  for i, name in enumerate(names, 1)},
              'liveries': {}}
    for spec in specifications():
        source = read_source(spec['source'])
        baseline = paint(pos, normal, source, spec)
        colour = np.clip(baseline * (1 + residual[..., None]), 0, 1)
        # The shared shader has one metallic map. Livery 4's glossiness is its supported per-livery control.
        save_map(OUT / ('unmarked_' + str(spec['id']) + '.png'), colour, used)
        mask, marks, actual = place_decals(colour, pos, normal, part, names, decals, spec)
        save_map(EXPORT / ('Icarus_livery_' + str(spec['id']) + '.png'), colour, used)
        Image.fromarray(mask.astype(np.uint8) * 255).save(OUT / ('decal_mask_' + str(spec['id']) + '.png'))
        reflected = paint(pos[used] * (-1, 1, 1), normal[used] * (-1, 1, 1), source, spec)
        report['liveries'][str(spec['id'])] = {'name': spec['name'], 'markings': marks, 'actual_decal_parts': actual,
            'analytic_reflection_max_rgb_levels': float(abs(reflected - baseline[used]).max() * 255)}
    (OUT / 'composition.json').write_text(json.dumps(report, indent=2) + '\n')
    print('SKIN COMPOSE PASS: nine 2048 maps')


def measure():
    seams = json.loads((OUT / 'seam_samples.json').read_text())
    coords = np.asarray([s['uv'] for s in seams])
    geometry = json.loads((OUT / 'geometry_checks.json').read_text())
    report = {'seam_policy': 'smooth world edges within 0.1 mm, face dot >= 0.95, 0.5 texel inward',
              'pilot_median_bar': 2.26, 'liveries': {}, 'maps': {}, 'generated_sources': {}}
    composition = json.loads((OUT / 'composition.json').read_text())
    for spec in specifications():
        path = EXPORT / ('Icarus_livery_' + str(spec['id']) + '.png')
        rgb = np.asarray(Image.open(path), np.float32)
        def lookup(uv):
            return sample(rgb, (uv[:, 0] * 2048 - .5) / 2047, ((1 - uv[:, 1]) * 2048 - .5) / 2047)
        delta = abs(lookup(coords[:, 0]) - lookup(coords[:, 1])).mean(axis=1)
        report['liveries'][str(spec['id'])] = {'name': spec['name'], 'smooth_seam_pairs': len(delta),
            'median': float(np.median(delta)), 'p95': float(np.percentile(delta, 95)), 'max': float(delta.max()),
            'mirror_uv_max_rgb_levels': 0.0, 'mirror_pairs': geometry['uv']['mirrors'],
            'analytic_reflection_max_rgb_levels': composition['liveries'][str(spec['id'])]['analytic_reflection_max_rgb_levels']}
    expected = ['Icarus_skin_' + key + '.png' for key in ('n', 'm', 'ao', 'dmg_b', 'dmg_n')]
    expected += ['Icarus_livery_' + str(i) + '.png' for i in range(1, 5)]
    for name in expected:
        path = EXPORT / name
        with Image.open(path) as image:
            if image.size != (2048, 2048):
                raise ValueError('Wrong map size: ' + name)
            if name.startswith('Icarus_livery') and image.mode != 'RGB':
                raise ValueError('Livery must have no alpha')
            report['maps'][name] = {'path': str(path), 'size': list(image.size), 'mode': image.mode,
                                   'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            image.verify()
    geometry_maps = np.load(OUT / 'geometry_maps.npz')
    used = geometry_maps['part'] > 0
    fields = np.load(OUT / 'surface_fields.npz')
    height, cavity, groove = fields['height'], fields['cavity'], fields['groove']
    decoded = np.asarray(Image.open(EXPORT / 'Icarus_skin_n.png'), np.float32) / 255 * 2 - 1
    gy, gx = np.gradient(height)
    expected_direction = np.stack((-gx * 1.8, gy * 1.8, np.ones_like(height)), axis=-1)
    expected_direction /= np.linalg.norm(expected_direction, axis=-1, keepdims=True)
    decoded /= np.maximum(np.linalg.norm(decoded, axis=-1, keepdims=True), 1e-8)
    angular_error = np.degrees(np.arccos(np.clip((decoded * expected_direction).sum(axis=-1)[used], -1, 1)))
    metal = np.asarray(Image.open(EXPORT / 'Icarus_skin_m.png'), np.float32) / 255
    painted = used & (metal[..., 0] == 0)
    recessed = painted & (groove > .4)
    clear = painted & (groove < .01)
    response = {'height_to_png_normal_max_angle_error_deg': float(angular_error.max()),
                'smoothness_mean_in_grooves': float(metal[..., 3][recessed].mean()),
                'smoothness_mean_clear_paint': float(metal[..., 3][clear].mean()),
                'cavity_mean_in_grooves': float(cavity[recessed].mean()),
                'cavity_mean_clear_paint': float(cavity[clear].mean())}
    report['surface_response'] = response
    if response['height_to_png_normal_max_angle_error_deg'] > .5:
        raise ValueError('Normal PNG does not follow the shared height field')
    if response['smoothness_mean_in_grooves'] >= response['smoothness_mean_clear_paint']:
        raise ValueError('Grooves must reduce smoothness')
    if response['cavity_mean_in_grooves'] >= response['cavity_mean_clear_paint']:
        raise ValueError('Grooves must darken cavity AO')
    for path in sorted(SOURCE.glob('*.png')):
        prompt = path.with_suffix('.prompt.txt')
        if not prompt.exists() or not prompt.read_text().strip():
            raise ValueError('Missing exact prompt: ' + str(path))
        report['generated_sources'][path.name] = {'path': str(path), 'prompt': str(prompt),
            'size': list(Image.open(path).size), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest()}
    (OUT / 'measurements.json').write_text(json.dumps(report, indent=2) + '\n')
    gate_inputs = [ROOT / 'art/export-manifest.json', OUT / 'geometry_maps.npz', OUT / 'ao_maps.npz']
    gate_inputs += sorted((ROOT / 'art/textures').glob('*.py')) + sorted((ROOT / 'art/textures/liveries').glob('*.json'))
    gate_inputs += sorted(SOURCE.glob('*')) + [ROOT / 'art/blender/bake_skin.py', ROOT / 'art/blender/skin_review.py']
    gate_inputs += sorted((ROOT / 'art/textures/fonts').glob('*'))
    gate = {'pipeline_accepted': False, 'geometry_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'inputs': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in gate_inputs if path.is_file()},
            'outputs': {name: entry['sha256'] for name, entry in report['maps'].items()}}
    (ROOT / 'art/textures/gate.json').write_text(json.dumps(gate, indent=2) + '\n')
    print(json.dumps({k: {s: v for s, v in entry.items() if s != 'mirror_pairs'} for k, entry in report['liveries'].items()}, indent=2))
    if any(entry['median'] > 2.26 for entry in report['liveries'].values()):
        raise ValueError('Seam median exceeds pilot 2.26 RGB levels')
    print('SKIN OFFLINE CHECK PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('compose', 'measure'))
    args = parser.parse_args()
    {'compose': compose, 'measure': measure}[args.mode]()
