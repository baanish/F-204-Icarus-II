"""Compose ten skin PNGs from preserved generated art, the airframe panel layout and the current Blender bakes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil

from record_paths import portable_record, portable_text, resolve_record
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, median_filter

from rasterize import (ROOT, OUT, SOURCE, EXPORT, SIZE, PAINT_SIZE, PX_PER_M, GUTTER_PX, extend_geometry, read_source,
                       save_map, sample, smoothstep, triplanar, upsample)
from liveries import PAINT_GRAIN, SOURCE_BLUR_PX, specifications, paint, paint_grain, soften
from insignia import sources, place_decals
from panels import bare_aft, layout_fields, surface_height, tangent_normal
from damage import compose_damage

REGIONS = {'nw': (0, 0), 'ne': (896, 0), 'sw': (0, 896), 'se': (896, 896)}
STRUCTURE = ROOT / '.cache/review/wave2/p9b-round2/structure.json'
# Albedo response to the airframe layout: grime in the joints, a faint ring at each fastener head.
SEAM_SHADE = {'paint': .30, 'metal': .22}
FASTENER_SHADE = {'paint': .16, 'metal': .16}


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


def despeckle(ao, used):
    """Lift lone dark texels of the one-sample AO bake to their 3 x 3 median; real occlusion is smooth and stays."""
    _, index = distance_transform_edt(~used, return_indices=True)
    return np.maximum(ao, median_filter(ao[index[0], index[1]], 3)) * used


def compose(part_manifest=None):
    OUT.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    paint_bake = np.load(OUT / 'geometry_maps.npz')
    paint_part = paint_bake['part']
    paint_used = paint_part > 0
    names = resolve_record(json.loads((OUT / 'atlas_triangles.json').read_text()))['parts']
    atlas = np.load(OUT / 'atlas_geometry.npz')
    pos, normal, part = atlas['position'][..., :3], atlas['normal'][..., :3], atlas['part']
    if part.shape != (SIZE, SIZE) or paint_part.shape != (PAINT_SIZE, PAINT_SIZE):
        raise ValueError(f'Expected a {SIZE} atlas bake and a {PAINT_SIZE} paint bake; rerun bake_skin.py prepare')
    used = part > 0
    # Generated paint was made per chart, so its residual fades over 14 texels at UV cuts.
    fade = smoothstep((distance_transform_edt(used) - 1) / 13)
    full = None
    if part_manifest is not None and resolve_record(json.loads(part_manifest.read_text())).get('schema_version') in (1, 2):
        from full_skin_compose import assemble_full
        full = assemble_full(part_manifest)
        if not np.array_equal(full['used'], paint_used):
            raise ValueError('Full generated coverage differs from the current geometry bake')
        generated = full['base']
    else:
        generated = assemble()
    if part_manifest is not None and full is None:
        from pilot2_parts import stitch
        generated = stitch(generated, paint_part, part_manifest)
    nozzle_parts = [name for name in names if name == 'nozzle' or name.startswith(('nozzle_petal_', 'nozzle_seal_'))]
    nozzle = np.isin(paint_part, [names.index(name) + 1 for name in nozzle_parts])
    if nozzle.any() and full is None:
        # New nozzle islands have no matching source-atlas silhouettes; use the accepted unmarked metal art.
        generated[nozzle] = triplanar(read_source('bare_metal.png'), paint_bake['position'][..., :3][nozzle],
                                      paint_bake['normal'][..., :3][nozzle], 1.8)
    Image.fromarray(np.uint8(generated * 255 + .5)).save(OUT / 'generated_base_assembled.png')
    residual = upsample(paint_grain(generated, paint_used), paint_used) * fade
    extended_pos, extended_normal, extended_part, domain, dx, dy = extend_geometry(pos, normal, part)
    structure = resolve_record(json.loads(STRUCTURE.read_text()))
    fields, layout_report = layout_fields(extended_pos, extended_normal, extended_part, names, domain, structure)
    height = surface_height(fields, PX_PER_M)
    seam, fastener = fields['seam'], np.maximum(fields['rivet'], fields['screw'])
    relief = np.maximum(seam, fastener)
    cavity = np.clip(1 - .4 * seam - .22 * fastener, .55, 1).astype(np.float32)
    save_map(EXPORT / 'Icarus_skin_n.png', tangent_normal(height, used), used)
    with np.load(OUT / 'ao_maps.npz') as baked:
        baked_ao = upsample(despeckle(baked['combined'], paint_used), paint_used).astype(np.float32)
    # The saved float32 fields, multiplied in float64, reproduce these bytes exactly in full_skin_checks.
    ao = np.clip(baked_ao.astype(np.float64) * cavity, 0, 1)
    save_map(EXPORT / 'Icarus_skin_ao.png', np.repeat(ao[..., None], 3, axis=-1), used)
    # Unpainted aft fuselage on every livery, bounded by its panel seams.
    bare = bare_aft(pos, part, names, structure)
    metallic = np.zeros((*part.shape, 4), np.float32)
    metallic[..., 0] = bare
    metallic[..., 3] = .4 + .2 * bare - .12 * seam - .05 * fastener
    save_map(EXPORT / 'Icarus_skin_m.png', metallic, used)
    np.savez_compressed(OUT / 'surface_fields.npz', height=height.astype(np.float32), cavity=cavity.astype(np.float32),
                        groove=seam.astype(np.float32), relief=relief.astype(np.float32),
                        baked_ao=baked_ao.astype(np.float32))
    dmg_b, dmg_n = compose_damage(pos, normal, used, fade, height, fields)
    # Empty atlas past the gutter never opens, so mips and filtering pull no holes into island edges.
    save_map(EXPORT / 'Icarus_skin_dmg_b.png', dmg_b, used, empty=(0, 0, 0, 1))
    save_map(EXPORT / 'Icarus_skin_dmg_n.png', dmg_n, used)
    decals = sources()
    report = {'atlas_size': SIZE, 'paint_size': PAINT_SIZE, 'px_per_m': PX_PER_M,
              'edge_fade_px': 14, 'gutter_dilation_px': GUTTER_PX, 'surface_relief': layout_report,
              'albedo': {'paint_grain': PAINT_GRAIN, 'source_blur_px': SOURCE_BLUR_PX,
                         'seam_shade': SEAM_SHADE, 'fastener_shade': FASTENER_SHADE,
                         'policy': 'generated paint keeps its broad tone; its painted seams, rivets and pitting are '
                                   'removed; joints and fasteners shade from the airframe layout'},
              'ao': 'baked at paint size, upsampled, times the layout cavity', 'coverage': float(used.mean()),
              'generated_detail_overrides': {'source': 'bare_metal.png', 'projection': 'reflected world triplanar',
                                             'scale_m': 1.8, 'parts': nozzle_parts},
              'skin_texels_by_part': {name: int((part == i).sum()) for i, name in enumerate(names, 1)},
              'liveries': {}}
    if full is not None:
        report['generated_detail_overrides'] = {'source': 'per-part full manifest', 'parts': names,
            'old_quadrant_fallback_texels': 0, 'alignment_report': (part_manifest.parent / 'alignment.json').as_posix()}
        report['damage_policy'] = 'generated damage sources projected on current geometry'
        report['damage_inputs'] = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (SOURCE / 'damage_source.png', OUT / 'atlas_geometry.npz')}
        dependencies = [part_manifest, part_manifest.parent / 'coverage.json', STRUCTURE]
        dependencies += [ROOT / 'art/textures/generated/full/source-policy.json']
        dependencies += list((SOURCE / 'full').rglob('*')) + list((SOURCE / 'pilot2').rglob('*'))
        active_manifest = resolve_record(json.loads(part_manifest.read_text()))
        dependencies += [Path(path) if Path(path).is_absolute() else part_manifest.parent / path
                         for path in active_manifest.get('input_sha256', {})]
        if not active_manifest.get('source_atlas_manifest'):
            dependencies += [part_manifest.parent / 'ownership.npz']
            dependencies += list(part_manifest.parent.glob('*.mask.png')) + list(part_manifest.parent.glob('*.transfer.npz'))
        report['full_inputs'] = {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in dependencies if path.is_file()}
    for spec in specifications():
        source = soften(read_source(spec['source']))
        baseline = paint(pos, normal, source, spec)
        if spec['id'] == 4:
            from bare_metal import finish, painted_parts, surface_map, METALLIC_MAP
            baseline, sheet_tone, metal_report = finish(baseline, pos, normal, fields['panel'], used)
            report['bare_metal'] = metal_report
            report['bare_metal']['analytic_reflection_scope'] = 'world scheme before atlas sheet tones; current UV seam samples check the finished atlas'
        colour = np.clip(baseline * (1 + residual[..., None]), 0, 1)
        paint_coverage = None
        if spec['id'] == 4:
            _, glare = painted_parts(pos, normal, part, names)
            colour = colour * (1 - glare[..., None]) + np.array([.035, .043, .045]) * glare[..., None]
            paint_coverage = np.zeros(part.shape, np.float32)
        save_map(OUT / ('unmarked_' + str(spec['id']) + '.png'), colour, used)
        mask, marks, actual = place_decals(colour, pos, normal, part, names, decals, spec, paint_coverage, dx, dy)
        finish_kind = 'metal' if spec['id'] == 4 else 'paint'
        colour *= (1 - SEAM_SHADE[finish_kind] * seam - FASTENER_SHADE[finish_kind] * fastener)[..., None]
        if spec['id'] == 4:
            material, masks = surface_map(metallic, pos, normal, part, names, paint_coverage, sheet_tone, relief)
            save_map(EXPORT / METALLIC_MAP, material, used)
            np.savez_compressed(OUT / 'bare_metal_masks.npz', **masks)
            report['bare_metal']['material'] = {'map': METALLIC_MAP, 'metal_red': .98,
                'polished_alpha': [.82, .96], 'painted_alpha': .42, 'anti_glare_alpha': .18,
                'glossiness': spec['glossiness'], 'paint_mask': 'same bands, anti-glare and sampled decal alpha as livery compose; radome uses sheet metal',
                'protected_texels': int((used & (masks['protected'] >= 1)).sum())}
        save_map(EXPORT / ('Icarus_livery_' + str(spec['id']) + '.png'), colour, used)
        Image.fromarray(mask.astype(np.uint8) * 255).save(OUT / ('decal_mask_' + str(spec['id']) + '.png'))
        reflected = paint(pos[used] * (-1, 1, 1), normal[used] * (-1, 1, 1), source, spec)
        reflection_baseline = paint(pos, normal, source, spec) if spec['id'] == 4 else baseline
        report['liveries'][str(spec['id'])] = {'name': spec['name'], 'markings': marks, 'actual_decal_parts': actual,
            'analytic_reflection_max_rgb_levels': float(abs(reflected - reflection_baseline[used]).max() * 255)}
        print('SKIN LIVERY', spec['id'], spec['name'], flush=True)
    (OUT / 'composition.json').write_text(portable_text(json.dumps(portable_record(report), indent=2) + '\n'))
    print(f'SKIN COMPOSE PASS: ten {SIZE} maps')


def response_regions(painted, relief):
    """Joint and fastener texels against clear panel faces of the same paint."""
    recessed = painted & (relief > .5)
    clear = painted & (relief < .01)
    if not recessed.any() or not clear.any():
        raise ValueError('Insufficient recessed/clear paint evidence for surface response')
    return recessed, clear, {'recessed_relief_min': .5, 'clear_relief_max': .01,
        'recessed_texels': int(recessed.sum()), 'clear_texels': int(clear.sum())}


def damage_alpha_check(used, relief):
    """Hold the shipped damage alpha to the stock shader's direction and to the open shares of stock skins.

    Ten stock skin maps open 0.5 to 13% of their texels by HP 80 and 9 to 32% by HP 0, and keep 68 to 91% at or above
    alpha 0.5, which never opens (damage.py). Joints and fastener rows must never open.
    """
    alpha = np.asarray(Image.open(EXPORT / 'Icarus_skin_dmg_b.png'), np.float64)[..., 3] / 255
    skin = alpha[used]
    share = {hp: float(((1 - hp / 100) * (skin - .52) + .02 < 0).mean()) for hp in (80, 60, 40, 20, 0)}
    result = {'open_share_by_hp': {str(hp): value for hp, value in share.items()},
              'never_open_share': float((skin >= .5).mean()),
              'relief_texels_min_alpha': float(alpha[used & (relief > .5)].min())}
    if result['relief_texels_min_alpha'] < .5:
        raise ValueError('Damage alpha opens joint or fastener texels; high alpha must be the metal that stays')
    if not (.005 <= share[80] <= .13 and .09 <= share[0] <= .32 and .68 <= result['never_open_share'] <= .91):
        raise ValueError(f'Damage alpha open shares outside the stock range: {result}')
    return result


def measure():
    seams = resolve_record(json.loads((OUT / 'seam_samples.json').read_text()))
    coords = np.asarray([s['uv'] for s in seams])
    geometry = resolve_record(json.loads((OUT / 'geometry_checks.json').read_text()))
    report = {'seam_policy': 'smooth world edges within 0.1 mm, face dot >= 0.95, 0.5 texel inward',
              'pilot_median_bar': 2.26, 'liveries': {}, 'maps': {}, 'generated_sources': {}}
    composition = resolve_record(json.loads((OUT / 'composition.json').read_text()))
    for spec in specifications():
        path = EXPORT / ('Icarus_livery_' + str(spec['id']) + '.png')
        rgb = np.asarray(Image.open(path), np.float32)
        def lookup(uv):
            return sample(rgb, (uv[:, 0] * SIZE - .5) / (SIZE - 1), ((1 - uv[:, 1]) * SIZE - .5) / (SIZE - 1))
        delta = abs(lookup(coords[:, 0]) - lookup(coords[:, 1])).mean(axis=1)
        report['liveries'][str(spec['id'])] = {'name': spec['name'], 'smooth_seam_pairs': len(delta),
            'median': float(np.median(delta)), 'p95': float(np.percentile(delta, 95)), 'max': float(delta.max()),
            'mirror_uv_max_rgb_levels': 0.0, 'mirror_pairs': geometry['uv']['mirrors'],
            'analytic_reflection_max_rgb_levels': composition['liveries'][str(spec['id'])]['analytic_reflection_max_rgb_levels']}
    expected = ['Icarus_skin_' + key + '.png' for key in ('n', 'm', 'ao', 'dmg_b', 'dmg_n')]
    expected += ['Icarus_livery_' + str(i) + '.png' for i in range(1, 5)]
    expected += ['Icarus_livery_4_m.png']
    for name in expected:
        path = EXPORT / name
        with Image.open(path) as image:
            if image.size != (SIZE, SIZE):
                raise ValueError('Wrong map size: ' + name)
            if name.startswith('Icarus_livery') and not name.endswith('_m.png') and image.mode != 'RGB':
                raise ValueError('Livery must have no alpha')
            if name == 'Icarus_livery_4_m.png' and image.mode != 'RGBA':
                raise ValueError('Bare Metal material map must retain smoothness alpha')
            report['maps'][name] = {'path': str(path), 'size': list(image.size), 'mode': image.mode,
                                   'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            image.verify()
    with np.load(OUT / 'atlas_geometry.npz') as atlas:
        used = atlas['part'] > 0
    fields = np.load(OUT / 'surface_fields.npz')
    height, cavity, relief = fields['height'], fields['cavity'], fields['relief']
    decoded = np.asarray(Image.open(EXPORT / 'Icarus_skin_n.png'), np.float32) / 255 * 2 - 1
    gy, gx = np.gradient(height)
    expected_direction = np.stack((-gx * 1.8, gy * 1.8, np.ones_like(height)), axis=-1)
    expected_direction /= np.linalg.norm(expected_direction, axis=-1, keepdims=True)
    decoded /= np.maximum(np.linalg.norm(decoded, axis=-1, keepdims=True), 1e-8)
    angular_error = np.degrees(np.arccos(np.clip((decoded * expected_direction).sum(axis=-1)[used], -1, 1)))
    metal = np.asarray(Image.open(EXPORT / 'Icarus_skin_m.png'), np.float32) / 255
    painted = used & (metal[..., 0] == 0)
    recessed, clear, response_sampling = response_regions(painted, relief)
    response = {'height_to_png_normal_max_angle_error_deg': float(angular_error.max()),
                'sampling': response_sampling,
                'smoothness_mean_in_grooves': float(metal[..., 3][recessed].mean()),
                'smoothness_mean_clear_paint': float(metal[..., 3][clear].mean()),
                'cavity_mean_in_grooves': float(cavity[recessed].mean()),
                'cavity_mean_clear_paint': float(cavity[clear].mean())}
    report['surface_response'] = response
    report['damage_alpha'] = damage_alpha_check(used, relief)
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
    (OUT / 'measurements.json').write_text(portable_text(json.dumps(portable_record(report), indent=2) + '\n'))
    gate_inputs = [ROOT / 'art/export-manifest.json', OUT / 'geometry_maps.npz', OUT / 'atlas_geometry.npz',
                   OUT / 'ao_maps.npz', STRUCTURE]
    gate_inputs += sorted((ROOT / 'art/textures').glob('*.py')) + sorted((ROOT / 'art/textures/liveries').glob('*.json'))
    gate_inputs += sorted(SOURCE.glob('*')) + [ROOT / 'art/blender/bake_skin.py', ROOT / 'art/blender/skin_review.py']
    gate_inputs += sorted((ROOT / 'art/textures/fonts').glob('*'))
    if composition.get('full_inputs'):
        for input_path, expected_hash in composition['full_inputs'].items():
            path = ROOT / input_path
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise ValueError('Full source input changed since composition: ' + input_path)
            gate_inputs.append(path)
    gate = {'pipeline_accepted': False, 'geometry_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'inputs': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in gate_inputs if path.is_file()},
            'outputs': {name: entry['sha256'] for name, entry in report['maps'].items()}}
    (ROOT / 'art/textures/gate.json').write_text(portable_text(json.dumps(portable_record(gate), indent=2) + '\n'))
    print(json.dumps(portable_record({k: {s: v for s, v in entry.items() if s != 'mirror_pairs'} for k, entry in report['liveries'].items()}), indent=2))
    if any(entry['median'] > 2.26 for entry in report['liveries'].values()):
        raise ValueError('Seam median exceeds pilot 2.26 RGB levels')
    print('SKIN OFFLINE CHECK PASS')


if __name__ == '__main__':
    from texture_sources import require_texture_sources
    require_texture_sources()
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('compose', 'measure', 'full'))
    args = parser.parse_args()
    if args.mode == 'full':
        folder = ROOT / '.cache/review/wave2/p9b-round2/full'
        EXPORT = folder / 'art/export/textures'
        compose(folder / 'parts.json')
        for name in ('composition.json', 'surface_fields.npz', 'generated_base_assembled.png', 'bare_metal_masks.npz'):
            shutil.copy2(OUT / name, folder / name)
    else:
        if args.mode == 'compose' and (SOURCE / 'full/source-policy.json').is_file():
            manifest = ROOT / '.cache/review/wave2/p9b-round2/full/parts.json'
            if not manifest.is_file():
                raise ValueError('Per-part sources selected. Rebuild structure, pilot guides and full inventory first; see art/textures/README.md.')
            compose(manifest)
        else:
            {'compose': compose, 'measure': measure}[args.mode]()
