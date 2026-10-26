"""Offline full-skin checks and paged PNG review sheets. No owner acceptance is implied."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

from companion_maps import THRESHOLDS
from rasterize import GUTTER_PX, PAINT_SIZE, SIZE, sample


ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / '.cache/review/wave2/p9b-round2/full'
BAKE = ROOT / '.cache/review/wave2/p9b/02'
MAPS = [f'Icarus_livery_{i}.png' for i in range(1, 5)] + [
    f'Icarus_skin_{suffix}.png' for suffix in ('n', 'm', 'ao', 'dmg_b', 'dmg_n')] + ['Icarus_livery_4_m.png']
STITCHED_GROUPS = {'canopy_all', 'skin_forward_L_lower',
                   'pylon_inner_plug_L_all', 'wing_skin_L_lower_front'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def resolve(value, directory):
    path = Path(value)
    return path if path.is_absolute() else directory / path


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def evidence(path):
    path = Path(path)
    return {'path': path.as_posix(), 'sha256': sha256(path), 'bytes': path.stat().st_size}


def check_inputs(manifest, directory, required=()):
    hashes = {resolve(value, directory).resolve(): digest
              for value, digest in manifest['input_sha256'].items()}
    require(all(Path(path).resolve() in hashes for path in required), 'Missing required manifest input hash')
    for path, digest in hashes.items():
        require(sha256(path) == digest, f'Manifest input changed: {path}')


def image_evidence(path):
    record = evidence(path)
    with Image.open(path) as image:
        require(image.format == 'PNG', f'Expected PNG: {path}')
        record.update(size=list(image.size), mode=image.mode)
        image.verify()
    return record


def pixels(path, mode=None):
    with Image.open(path) as image:
        return np.asarray(image.convert(mode) if mode else image).copy()


def failed(record):
    return bool(record.get('error') or record.get('generation_error') or
                record.get('status') in ('failed', 'error', 'generation_failed') or
                record.get('success') is False)


def native_generation(path, record_path):
    """Check original bytes, including pilot bases recorded in a shared generation file."""
    path, record_path = Path(path), Path(record_path)
    if not record_path.is_file():
        record_path = path.parent / 'generation.json'
    record = read_json(record_path)
    result = {'record': evidence(record_path), 'generation': record}
    if not path.is_file():
        require(failed(record), f'Missing native image without generation failure: {path}')
        result['status'] = 'generation_failed'
        return result
    require(not failed(record), f'Native image exists despite failed generation record: {path}')
    native = image_evidence(path)
    original = record.get('original')
    if 'outputs' in record:
        original = Path(record['original_directory']) / record['outputs'][path.stem]
    require(original is not None, f'Missing original native path: {record_path}')
    original = resolve(original, record_path.parent)
    require(native['sha256'] == sha256(original), f'Native bytes changed: {path}')
    declared_hash = record.get('sha256')
    require(declared_hash is None or native['sha256'] == declared_hash,
            f'Native hash differs from generation record: {path}')
    declared_size = record.get('native_size', record.get('native_resolution'))
    require(declared_size is not None and native['size'] == list(declared_size),
            f'Native dimensions differ from generation record: {path}')
    result.update(status='native_unchanged', image=native, original=evidence(original))
    return result


def call_context(name, group, sources, full, companion=False):
    call_path = full / f'{name}.call.json'
    call = read_json(call_path)
    prompt = resolve(call.get('prompt', sources / f'{name}.prompt.txt'), full)
    context = resolve(sources / f'{name}.context.md' if companion else
                      group.get('context_path', sources / f'{name}.context.md'), full)
    require(prompt.read_text(encoding='utf-8').strip(), f'Empty prompt: {prompt}')
    require(context.read_text(encoding='utf-8').strip(), f'Empty context: {context}')
    return {'call': evidence(call_path), 'prompt': evidence(prompt), 'context': evidence(context),
            'references': [evidence(resolve(value, full)) for value in call.get('references', [])]}


def source_checks(manifest, alignment, full, report):
    sources = resolve(manifest.get('companion_dir', ROOT / 'art/textures/generated/full'), full)
    style_path = resolve(manifest['shared_style'], full)
    style = style_path.read_text(encoding='utf-8').strip()
    require(style, 'Empty shared style block')
    report['shared_style'] = evidence(style_path)
    stitched = set()
    for name, group in manifest['groups'].items():
        source = resolve(group['source_path'], full)
        base = image_evidence(source)
        registered = alignment[name]
        require(base['size'] == registered['native_size'] and base['sha256'] == registered['sha256'],
                f'Alignment base size/hash differs: {name}')
        require(resolve(registered['source_path'], full).resolve() == source.resolve(),
                f'Alignment source path differs: {name}')
        context = call_context(name, group, sources, full)
        prompt = Path(context['prompt']['path']).read_text(encoding='utf-8')
        require(style in prompt, f'Shared style missing from base prompt: {name}')
        entry = {'base': base, 'context': context, 'companions': {}}
        report['groups'][name] = entry
        entry['failed_attempts'] = [
            {'record': evidence(path), 'generation': read_json(path)}
            for path in sorted(full.glob(f'{name}.failed*.json'))]
        if group.get('source_stitch'):
            stitched.add(name)
            stitch = group['source_stitch']
            require(source.name == f'{name}.stitched.png', f'Expected named stitched base: {name}')
            require(read_json(full / f'{name}.source-stitch.json') == stitch,
                    f'Source stitch metadata differs: {name}')
            origin = resolve(stitch['source'], full)
            require(sha256(origin) == stitch['source_sha256'], f'Stitch source changed: {name}')
            require(base['sha256'] == stitch['output_sha256'] and base['size'] == stitch['native_size'],
                    f'Stitched base size/hash differs: {name}')
            require(resolve(stitch['output'], full).resolve() == source.resolve(),
                    f'Stitch output path differs: {name}')
            entry.update(source_stitch=stitch, freshly_generated=False,
                         source_policy='recorded raw-source or style-anchor composition')
            entry['generation'] = native_generation(origin, full / f'{name}.generation.json') if (
                origin.parent == sources) else native_generation(origin, origin.parent / 'generation.json')
            entry['stitch_record'] = evidence(full / f'{name}.source-stitch.json')
            generation_path = full / f'{name}.generation.json'
            entry['base_attempt'] = {'record': evidence(generation_path), 'generation': read_json(generation_path)}
        else:
            require(not source.name.endswith('.stitched.png'), f'Unrecorded stitched source: {name}')
            entry['generation'] = native_generation(source, full / f'{name}.generation.json')
            entry['source_policy'] = 'unchanged native generated base'
        for kind in ('height', 'roughness'):
            key = f'{name}_{kind}'
            path = sources / f'{key}.png'
            saved = registered['companions'][kind]
            companion = {'context': call_context(key, group, sources, full, True),
                         'provenance': native_generation(path, full / f'{key}.generation.json')}
            companion['failed_attempts'] = [
                {'record': evidence(attempt), 'generation': read_json(attempt)}
                for attempt in sorted(full.glob(f'{key}.failed*.json'))]
            if path.is_file():
                native = image_evidence(path)
                require(native['sha256'] == saved.get('sha256') and native['size'] == saved.get('native_size'),
                        f'Alignment companion size/hash differs: {key}')
                # Assembly measured these exact native bytes before applying any field.
                # The two hashes bind its evidence; do not repeat the same expensive detector.
                validation = saved['validation']
                require(validation['thresholds'] == THRESHOLDS and validation['kind'] == kind,
                        f'Companion evidence uses another gate: {key}')
                companion['image'] = native
            else:
                validation = saved['validation']
                require(validation.get('accepted') is False and saved['status'] == 'fallback',
                        f'Absent companion accepted: {key}')
                require('companion generation failed' in validation.get('reasons', []),
                        f'Missing companion failure reason: {key}')
            accepted = validation.get('accepted') is True
            require(saved['status'] == ('accepted' if accepted else 'fallback'),
                    f'Companion status differs from acceptance: {key}')
            if accepted:
                require(validation['thresholds'] == THRESHOLDS, f'Acceptance thresholds changed: {key}')
                require(companion['image']['size'] == base['size'], f'Accepted companion resized: {key}')
                require(not validation['reasons'] and validation['confidence']['verifiable'] and
                        validation['offset_magnitude'] + THRESHOLDS['offset_guard_band_px'] < 1,
                        f'Accepted companion fails offset/confidence evidence: {key}')
                require(all(validation['groups'][feature]['position_precision'] >= THRESHOLDS['minimum_precision'] and
                            validation['groups'][feature]['position_recall'] >= THRESHOLDS['minimum_recall']
                            for feature in ('seams', 'fasteners')), f'Accepted companion fails positions: {key}')
            else:
                require(saved.get('fallback_policy'), f'Missing fallback policy: {key}')
            require(resolve(saved['path'], full).resolve() == path.resolve(), f'Companion path differs: {key}')
            companion.update(status=saved['status'], validation=validation,
                             fallback_policy=saved.get('fallback_policy'))
            entry['companions'][kind] = companion
        registrations = registered['registration']
        require(len(registrations) == len(group['charts']), f'Incomplete chart registration: {name}')
        require(all(c['normalized_silhouette_iou'] >= .70 and c['native_px_per_m_min_axis'] >= 180
                    for c in registrations), f'Chart registration below existing gates: {name}')
        entry['registration'] = registrations
    require(stitched == STITCHED_GROUPS, f'Expected four recorded stitched groups, found {sorted(stitched)}')


def coverage_checks(manifest, alignment, coverage, stitch, full, part, names, report):
    shape = part.shape
    used = part > 0
    assigned = np.zeros(shape, bool)
    owner = np.full(shape, -1, np.int16)
    valid = {kind: np.zeros(shape, bool) for kind in ('height', 'roughness')}
    for index, (name, group) in enumerate(manifest['groups'].items()):
        mask = pixels(resolve(group['mask'], full), 'L') > 0
        require(mask.shape == shape, f'Wrong mask dimensions: {name}')
        require(not np.any(mask & (~used | assigned)), f'Group mask overlaps or leaves skin: {name}')
        source_ids = [names.index(source) + 1 for source in group['source_parts']]
        require(np.isin(part[mask], source_ids).all(), f'Group mask includes another source part: {name}')
        require(int(mask.sum()) == group['skin_texels'] == alignment[name]['skin_texels'],
                f'Group mask count differs: {name}')
        assigned |= mask
        owner[mask] = index
        for kind in valid:
            valid[kind][mask] = alignment[name]['companions'][kind]['status'] == 'accepted'
        report['groups'][name]['mask'] = image_evidence(resolve(group['mask'], full))
    direct_count = int(assigned.sum())
    transfers = []
    for rule in coverage['rules']:
        path = resolve(rule['map'], full)
        with np.load(path, allow_pickle=False) as data:
            target, source = data['target_indices'], data['source_indices']
            require(target.ndim == 1 and source.shape == target.shape and
                    np.issubdtype(target.dtype, np.integer) and np.issubdtype(source.dtype, np.integer),
                    f'Invalid transfer indices: {rule["name"]}')
            require(np.all((target >= 0) & (target < part.size)) and
                    np.all((source >= 0) & (source < part.size)), f'Transfer indices outside atlas: {rule["name"]}')
            require(np.unique(target).size == target.size and assigned.ravel()[source].all(),
                    f'Transfer duplicate targets or unassigned source: {rule["name"]}')
            require(not assigned.ravel()[target].any() and used.ravel()[target].all(),
                    f'Transfer overlaps assignment or leaves skin: {rule["name"]}')
            require(len(target) == rule['target_texels'], f'Transfer count differs: {rule["name"]}')
            target_mask = pixels(resolve(rule['target_mask'], full), 'L') > 0
            require(target_mask.shape == shape and int(target_mask.sum()) == len(target) and
                    target_mask.ravel()[target].all(), f'Transfer mask differs: {rule["name"]}')
            assigned.ravel()[target] = True
            owner.ravel()[target] = owner.ravel()[source]
            for field in valid.values():
                field.ravel()[target] = field.ravel()[source]
            transfers.append({**rule, 'evidence': evidence(path)})
    require(np.array_equal(assigned, used), 'Full manifest does not cover precisely the current skin bake')
    with np.load(resolve(coverage['owner_map'], full), allow_pickle=False) as data:
        require(list(data['group_names']) == list(manifest['groups']) and
                np.array_equal(data['group_index'], np.where(used, owner + 1, 0)),
                'Saved ownership differs from reconstructed assignment')
    require(len(names) == 56 and np.unique(part[used]).size == 56, 'Expected all 56 canonical parts')
    require(int(used.sum()) == 2354657, 'Expected 2354657 current canonical skin texels')
    require(direct_count == coverage['direct_texels'] and
            int(used.sum()) == coverage['assigned_texels'] == coverage['canonical_texels'] == stitch['assigned_texels'],
            'Coverage report counts differ from reconstructed assignment')
    parts = {}
    for index, name in enumerate(names, 1):
        count = int((part == index).sum())
        saved = coverage['parts'][name]
        require(count == saved['canonical_texels'] == saved['assigned_texels'], f'Part coverage differs: {name}')
        parts[name] = {'canonical_texels': count, 'assigned_texels': count}
    require(coverage['unassigned_texels'] == 0 and coverage['transferred_texels'] == int(used.sum()) - direct_count,
            'Unassigned or transferred count differs')
    report['coverage'] = {'parts': parts, 'part_count': len(parts), 'assigned_texels': int(used.sum()),
                          'direct_texels': direct_count, 'transfers': transfers,
                          'old_quadrant_fallback_texels': 0}
    for kind, field in valid.items():
        require(int(field.sum()) == stitch[f'{kind}_accepted_texels'], f'Accepted {kind} texel count differs')
        report['coverage'][f'{kind}_accepted_texels'] = int(field.sum())
        report['coverage'][f'{kind}_fallback_texels'] = int((used & ~field).sum())
    return used, owner


def current_coverage_checks(manifest, alignment, coverage, stitch, full, part, names, report,
                            source_manifest, source_part, source_names, source_owner):
    """Source indices address the immutable atlas, even when both atlases have equal sizes."""
    from source_atlas_mapping import FIELDS, validate_indices

    source_directory = resolve(manifest['source_atlas_manifest'], full).parent
    source_coverage = read_json(source_directory / 'coverage.json')
    require(list(manifest['groups']) == list(source_manifest['groups']), 'Source group names/order changed')
    require(coverage['schema_version'] == 2 and coverage['field_contract'] == list(FIELDS),
            'Current mapping field contract differs')
    require(names and len(set(names)) == len(names) and set(coverage['parts']) == set(names) and
            np.array_equal(np.unique(part[part > 0]), np.arange(1, len(names) + 1)),
            'Current canonical part inventory differs from bake')
    check_inputs(manifest, full, [resolve(manifest['bake'], full),
        resolve(manifest['bake'], full).with_name('atlas_triangles.json'),
        source_directory / 'parts.json', source_directory / 'coverage.json',
        resolve(source_coverage['owner_map'], source_directory),
        *(resolve(rule['map'], full) for rule in coverage['rules'])])
    used = part > 0
    owner = np.full(part.shape, -1, np.int16)
    transfers, parts = [], {}
    reused = 0
    for rule in coverage['rules']:
        name = rule['target_part']
        require(name in names and name not in parts and rule['source_space'] == 'generation_atlas',
                f'Invalid current transfer part/source space: {name}')
        path = resolve(rule['map'], full)
        with np.load(path, allow_pickle=False) as data:
            target, source, matched = (data[key] for key in ('target_indices', 'source_indices', 'matched'))
            validate_indices(target, source, part.size, source_part.size)
            require(matched.shape == target.shape and matched.dtype == np.bool_, f'Invalid match mask: {name}')
            require(np.all(owner.ravel()[target] == -1) and
                    np.all(part.ravel()[target] == names.index(name) + 1),
                    f'Current transfer overlaps or leaves named part: {name}')
            require(rule['source_part'] in source_names and
                    np.all(source_part.ravel()[source] == source_names.index(rule['source_part']) + 1) and
                    np.all(source_owner.ravel()[source] >= 0), f'Invalid generation-atlas donor: {name}')
            require(len(target) == rule['target_texels'] and
                    int(matched.sum()) == rule['native_reuse_texels'] == rule['geometric_matches'] and
                    int((~matched).sum()) == rule['unmatched_surface_texels'], f'Transfer counts differ: {name}')
            require(rule['match_tolerance_m'] == .015 and rule['normal_cosine_min'] == .95,
                    f'World reuse thresholds changed: {name}')
            split_wing = name in ('wing_skin_R', 'flap_R_visible', 'aileron_R_visible')
            if split_wing:
                require(rule['source_part'] == name.replace('_R', '_L') and rule['reflect_world_x'] is True,
                        f'Split wing must reuse its reflected physical twin: {name}')
                require(np.all(data['distance_m'][matched] <= .015) and
                        np.all(data['normal_cosine'][matched] >= .95),
                        f'Reflected wing reuse exceeds world tolerances: {name}')
            if name.startswith(('gear_door_', 'speed_brake_')) or (name != rule['source_part'] and not split_wing):
                require(not matched.any(), f'Replaced surface claims native mechanical detail: {name}')
            mask = pixels(resolve(rule['target_mask'], full), 'L') > 0
            require(mask.shape == part.shape and int(mask.sum()) == len(target) and
                    mask.ravel()[target].all(), f'Current transfer mask differs: {name}')
            owner.ravel()[target] = source_owner.ravel()[source]
            source_groups = [list(source_manifest['groups'])[int(index)]
                             for index in np.unique(source_owner.ravel()[source])]
            require(source_groups == rule['source_groups'], f'Transfer source groups differ: {name}')
            saved = coverage['parts'][name]
            count = int((part == names.index(name) + 1).sum())
            require(count == len(target) == saved['canonical_texels'] == saved['assigned_texels'] and
                    saved['native_reuse_texels'] == int(matched.sum()) and
                    saved['parent_paint_texels'] == int((~matched).sum()) and saved['groups'] == source_groups,
                    f'Current part coverage differs: {name}')
            parts[name] = saved
            reused += int(matched.sum())
        transfers.append({**rule, 'evidence': evidence(path),
                          'mask': image_evidence(resolve(rule['target_mask'], full))})
    require(np.array_equal(owner >= 0, used), 'Current mapping leaves holes or assigns unused texels')
    require(set(parts) == set(names) and coverage['unassigned_texels'] == 0 and
            coverage['unassigned_islands'] == [] and coverage['direct_texels'] == 0 and
            int(used.sum()) == coverage['transferred_texels'] == coverage['assigned_texels'] ==
            coverage['canonical_texels'] == stitch['assigned_texels'], 'Current coverage totals differ')
    require(reused == coverage['native_reuse_texels'] and
            int(used.sum()) - reused == coverage['unmatched_surface_texels'], 'Current reuse totals differ')
    with np.load(resolve(coverage['owner_map'], full), allow_pickle=False) as data:
        require(list(data['group_names']) == list(manifest['groups']) and
                np.array_equal(data['group_index'], np.where(used, owner + 1, 0)),
                'Current saved ownership differs from generation-atlas transfers')
    for index, (name, group) in enumerate(manifest['groups'].items()):
        mask_path = resolve(group['mask'], full)
        mask = pixels(mask_path, 'L') > 0
        require(np.array_equal(mask, owner == index) and int(mask.sum()) == group['skin_texels'],
                f'Current group mask differs: {name}')
        require(group['parts'] == [part_name for i, part_name in enumerate(names, 1)
                                   if np.any(mask & (part == i))], f'Current group parts differ: {name}')
        source_group = source_manifest['groups'][name]
        require(group['generation_atlas_charts'] == source_group['charts'] and
                sha256(resolve(group['generation_atlas_mask'], full)) ==
                sha256(resolve(source_group['mask'], source_directory)), f'Native group registration changed: {name}')
        report['groups'][name]['mask'] = image_evidence(mask_path)
    report['coverage'] = {'parts': parts, 'part_count': len(parts), 'assigned_texels': int(used.sum()),
        'direct_texels': 0, 'transfers': transfers, 'old_quadrant_fallback_texels': 0,
        'native_reuse_texels': reused, 'nearest_parent_texels': int(used.sum()) - reused}
    for kind in ('height', 'roughness'):
        accepted = np.array([alignment[name]['companions'][kind]['status'] == 'accepted'
                             for name in manifest['groups']])
        count = int(accepted[owner[used]].sum())
        require(count == stitch[f'{kind}_accepted_texels'], f'Remapped {kind} acceptance differs')
        report['coverage'][f'{kind}_accepted_texels'] = count
        report['coverage'][f'{kind}_fallback_texels'] = int(used.sum()) - count
    return used, owner


def mapping_geometry_checks(coverage, full, current_bake, source_bake, report):
    """Native reuse is measured on geometry, not inferred from recorded match flags."""
    from source_atlas_mapping import validate_indices

    geometry = []
    for path in (current_bake, source_bake):
        with np.load(path, allow_pickle=False) as data:
            shape = data['part'].shape
            fields = [data[key][..., :3] for key in ('position', 'normal')]
        require(all(field.shape == (*shape, 3) for field in fields), 'Invalid mapping geometry dimensions')
        geometry.append([field.reshape(-1, 3) for field in fields])
    (position, normal), (source_position, source_normal) = geometry
    parts = {}
    report['mapping_geometry'] = {'current_bake': evidence(current_bake), 'source_bake': evidence(source_bake),
        'position_tolerance_m': .015, 'normal_cosine_min': .95,
        'serialization_policy': 'saved float32 measurements must lie within half an ULP of recomputed values',
        'parts': parts}
    for rule in coverage['rules']:
        name = rule['target_part']
        with np.load(resolve(rule['map'], full), allow_pickle=False) as data:
            target, source = data['target_indices'], data['source_indices']
            validate_indices(target, source, len(position), len(source_position))
            query, query_normal = position[target].copy(), normal[target].copy()
            if rule['reflect_world_x']:
                query[:, 0] *= -1
                query_normal[:, 0] *= -1
            distance = np.linalg.norm(query - source_position[source], axis=1)
            cosine = np.einsum('ij,ij->i', query_normal, source_normal[source])
            require(len(distance) > 0 and np.isfinite(distance).all() and np.isfinite(cosine).all(),
                    f'Nonfinite or empty mapping geometry: {name}')
            matched = (distance <= .015) & (cosine >= .95)
            reflected_twin = (name in ('wing_skin_R', 'flap_R_visible', 'aileron_R_visible') and
                              rule['source_part'] == name.replace('_R', '_L') and rule['reflect_world_x'] is True)
            parent_paint = (name.startswith(('gear_door_', 'speed_brake_')) or
                            (name != rule['source_part'] and not reflected_twin))
            if parent_paint:
                matched[:] = False
            parts[name] = {'texels': len(distance), 'native_reuse_texels': int(matched.sum()),
                'parent_paint_texels': int((~matched).sum()), 'forced_parent_paint': parent_paint,
                'maximum_distance_m': float(distance.max()), 'p95_distance_m': float(np.quantile(distance, .95)),
                'minimum_normal_cosine': float(cosine.min())}
            for key, actual in (('distance_m', distance), ('normal_cosine', cosine)):
                saved = data[key]
                require(saved.shape == actual.shape and saved.dtype == np.float32 and np.isfinite(saved).all(),
                        f'Invalid saved geometry measurement: {name} {key}')
                rounding = np.spacing(np.abs(saved)).astype(np.float64) / 2
                require(np.isfinite(rounding).all() and
                        np.all(np.abs(actual.astype(np.float64) - saved.astype(np.float64)) <= rounding),
                        f'Mapping geometry measurement differs: {name} {key}')
            require(data['matched'].dtype == np.bool_ and np.array_equal(data['matched'], matched),
                    f'Mapping native reuse differs from measured geometry: {name}')


def map_checks(full, bake, composition, report):
    folder = full / 'art/export/textures'
    with np.load(bake / 'atlas_geometry.npz', allow_pickle=False) as atlas:
        used = atlas['part'] > 0
    require({p.name for p in folder.glob('*.png')} == set(MAPS), 'Expected exactly ten full skin PNGs')
    distance, nearest = distance_transform_edt(~used, return_indices=True)
    gutter = (~used) & (distance <= GUTTER_PX)
    outside = (~used) & ~gutter
    for name in MAPS:
        path = folder / name
        record = image_evidence(path)
        report['maps'][name] = record
        mode = 'RGBA' if name in ('Icarus_skin_m.png', 'Icarus_skin_dmg_b.png', 'Icarus_livery_4_m.png') else 'RGB'
        require(record['size'] == [SIZE, SIZE] and record['mode'] == mode, f'Wrong dimensions/mode: {name}')
        if '_dmg_' in name and composition.get('damage_policy') == 'unchanged shipped damage images':
            original = ROOT / 'art/export/textures' / name
            require(record['sha256'] == sha256(original), f'Shipped damage bytes changed: {name}')
            record['shipped_original'] = evidence(original)
            continue
        values = pixels(path)
        mismatches = int(np.any(values[gutter] != values[nearest[0][gutter], nearest[1][gutter]], axis=-1).sum())
        nonzero = int(np.any(values[outside] != 0, axis=-1).sum())
        record['gutter'] = {'width_px': GUTTER_PX, 'texels': int(gutter.sum()), 'mismatched_texels': mismatches,
                             'nonzero_beyond_gutter': nonzero}
        require(mismatches == 0 and nonzero == 0, f'Nearest-skin gutter differs: {name}')
    with np.load(full / 'surface_fields.npz', allow_pickle=False) as fields:
        require({'height', 'cavity', 'groove', 'baked_ao'} <= set(fields.files), 'Missing shared surface fields')
        height, cavity, groove, baked = (fields[key] for key in ('height', 'cavity', 'groove', 'baked_ao'))
    require(all(a.shape == used.shape and np.isfinite(a).all() for a in (height, cavity, groove)),
            'Shared fields must be finite atlas-sized arrays')
    gy, gx = np.gradient(height)
    expected = np.stack((-gx * 1.8, gy * 1.8, np.ones_like(height)), axis=-1)[used].astype(np.float64)
    expected /= np.linalg.norm(expected, axis=-1, keepdims=True)
    actual = pixels(folder / 'Icarus_skin_n.png')[used].astype(np.float64) / 255 * 2 - 1
    actual /= np.maximum(np.linalg.norm(actual, axis=-1, keepdims=True), 1e-12)
    angle = np.degrees(np.arccos(np.clip((expected * actual).sum(axis=-1), -1, 1)))
    report['normal'] = {'height_to_png_max_error_deg': float(angle.max()),
                        'height_to_png_p95_error_deg': float(np.percentile(angle, 95)), 'maximum_allowed_deg': .5,
                        'strength': 1.8, 'method': 'shared height gradient, tangent Y follows image-row convention'}
    require(angle.max() <= .5, 'Tangent normal differs from shared height by more than 0.5 degrees')
    require(baked.shape == used.shape and np.isfinite(baked).all(), 'Invalid baked AO field')
    expected_ao = np.uint8(np.clip(baked * cavity, 0, 1) * 255 + .5)
    actual_ao = pixels(folder / 'Icarus_skin_ao.png')
    error = abs(actual_ao[used].astype(np.int16) - expected_ao[used, None].astype(np.int16))
    # Composition encodes AO before serializing cavity to float32. Bound that
    # rounding explicitly instead of granting every pixel a one-byte tolerance.
    lower = (cavity.astype(np.float64) + np.nextafter(cavity, -np.inf).astype(np.float64)) / 2
    upper = (cavity.astype(np.float64) + np.nextafter(cavity, np.inf).astype(np.float64)) / 2
    lower = np.uint8(np.clip(baked.astype(np.float64) * lower, 0, 1) * 255 + .5)
    upper = np.uint8(np.clip(baked.astype(np.float64) * upper, 0, 1) * 255 + .5)
    invalid = np.any((actual_ao[used] < lower[used, None]) | (actual_ao[used] > upper[used, None]), axis=-1)
    report['ao'] = {'maximum_rgb_byte_error': int(error.max()), 'outside_rounding_interval_texels': int(invalid.sum()),
                    'formula': 'clip(despeckled baked AO upsampled to the atlas * shared cavity, 0, 1)',
                    'serialization_policy': 'only byte values reachable within the saved float32 cavity rounding interval'}
    require(not invalid.any(), 'AO PNG does not equal baked AO times shared cavity')
    overrides = composition['generated_detail_overrides']
    require(overrides.get('old_quadrant_fallback_texels') == 0, 'Composition used old quadrant fallback')
    require(composition.get('damage_policy') in ('unchanged shipped damage images',
            'generated damage sources projected on current geometry'), 'Damage policy differs')
    if composition['damage_policy'] == 'generated damage sources projected on current geometry':
        for path in (ROOT / 'art/textures/generated/damage_source.png', bake / 'atlas_geometry.npz'):
            require(composition['damage_inputs'].get(path.as_posix()) == sha256(path),
                    f'Damage projection input changed: {path}')
        report['damage'] = {'policy': composition['damage_policy'], 'inputs': composition['damage_inputs']}
    require(composition['gutter_dilation_px'] == GUTTER_PX, 'Composition gutter policy differs')
    require(composition['atlas_size'] == SIZE and composition['surface_relief'].get('policy'),
            'Composition lacks the airframe-layout relief policy')
    report['surface_policy'] = composition['surface_relief']


def seam_checks(full, bake, used, owner, groups, report):
    path = bake / 'seam_samples.json'
    coords = np.asarray([entry['uv'] for entry in read_json(path)], dtype=float)
    require(coords.ndim == 3 and coords.shape[1:] == (2, 2) and len(coords) > 0 and
            np.isfinite(coords).all() and np.all((coords >= 0) & (coords <= 1)), 'Invalid current seam samples')

    def lookup(values, uv):
        size = values.shape[0]
        return sample(values, (uv[:, 0] * size - .5) / (size - 1), ((1 - uv[:, 1]) * size - .5) / (size - 1))

    def stats(delta):
        return {'pairs': int(len(delta)), 'median_rgb_levels': float(np.median(delta)) if len(delta) else None,
                'p95_rgb_levels': float(np.percentile(delta, 95)) if len(delta) else None,
                'max_rgb_levels': float(delta.max()) if len(delta) else None}

    report['seams'] = {'samples': evidence(path), 'pilot_median_bar_rgb_levels': 2.26,
                        'policy': 'current smooth world-edge samples; identical bilinear RGB lookup to compose_skin.measure',
                        'liveries': {}}
    selectors = {}
    for index, name in enumerate(groups):
        mask = ((owner == index) & used)[..., None].astype(np.float32)
        selectors[name] = ((lookup(mask, coords[:, 0])[:, 0] > .1) |
                           (lookup(mask, coords[:, 1])[:, 0] > .1))
    failures = []
    for livery in range(1, 5):
        rgb = pixels(full / 'art/export/textures' / f'Icarus_livery_{livery}.png').astype(np.float32)
        delta = abs(lookup(rgb, coords[:, 0]) - lookup(rgb, coords[:, 1])).mean(axis=1)
        entry = stats(delta)
        entry['passes_median_policy'] = entry['median_rgb_levels'] <= 2.26
        entry['groups'] = {name: stats(delta[selected]) for name, selected in selectors.items()}
        report['seams']['liveries'][str(livery)] = entry
        if not entry['passes_median_policy']:
            failures.append(str(livery))
    return failures


def alignment_summary(full, report):
    fields = ['group', 'kind', 'status', 'offset_x_px', 'offset_y_px', 'offset_magnitude_px',
              'seam_position_precision', 'seam_position_recall', 'fastener_position_precision',
              'fastener_position_recall', 'fallback_policy', 'reasons']
    rows = []
    for name, group in report['groups'].items():
        for kind, companion in group['companions'].items():
            validation = companion['validation']
            offset = validation.get('offset_xy') or (None, None)
            scores = validation.get('groups', {})
            rows.append(dict(zip(fields, [name, kind, companion['status'], *offset,
                validation.get('offset_magnitude'), scores.get('seams', {}).get('position_precision'),
                scores.get('seams', {}).get('position_recall'), scores.get('fasteners', {}).get('position_precision'),
                scores.get('fasteners', {}).get('position_recall'), companion.get('fallback_policy') or '',
                '; '.join(validation.get('reasons', []))])))
    with (full / 'alignment-summary.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    lines = ['Native texels; +x right, +y down. Missing measurements are unverifiable, not zero.',
             'Offline evidence only. Owner acceptance remains pending.', '',
             '| ' + ' | '.join(fields) + ' |', '| ' + ' | '.join(['---'] * len(fields)) + ' |']
    for row in rows:
        cells = [f'{v:.6f}' if isinstance(v, float) else '' if v is None else str(v) for v in row.values()]
        lines.append('| ' + ' | '.join(v.replace('|', '\\|').replace('\n', ' ') for v in cells) + ' |')
    (full / 'alignment-summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def measure(full, bake):
    report = {'schema_version': 1, 'status': 'incomplete', 'owner_acceptance': 'pending',
              'note': 'Deterministic offline uncompressed checks only; no live game or owner acceptance.',
              'alignment_measurement_policy': 'measured natively during assembly before use; current base/companion hashes and gate evidence checked here',
              'groups': {}, 'maps': {}, 'companion_thresholds': dict(THRESHOLDS)}
    try:
        manifest, alignment, coverage, stitch, composition = (
            read_json(full / name) for name in ('parts.json', 'alignment.json', 'coverage.json',
                                               'stitch.json', 'composition.json'))
        adapted = 'source_atlas_manifest' in manifest
        require(manifest['schema_version'] == (2 if adapted else 1) and len(manifest['groups']) == 33,
                'Expected 33 full source groups and supported atlas schema')
        require(set(manifest['groups']) == set(alignment) == set(stitch['groups']), 'Incomplete alignment/stitch groups')
        require(alignment == stitch['groups'], 'Alignment and stitch group evidence differs')
        require('error' not in stitch and stitch['old_quadrant_fallback_texels'] == 0, 'Incomplete stitch or old quadrant fallback')
        require(resolve(manifest['bake'], full).resolve() == (bake / 'geometry_maps.npz').resolve(), 'Manifest uses another bake')
        report['inputs'] = {name: evidence(full / name) for name in
                            ('parts.json', 'alignment.json', 'coverage.json', 'stitch.json', 'composition.json', 'surface_fields.npz')}
        check_inputs(manifest, full)
        for name in ('geometry_maps.npz', 'ao_maps.npz', 'atlas_triangles.json'):
            report['inputs'][name] = evidence(bake / name)
        with np.load(bake / 'geometry_maps.npz', allow_pickle=False) as data:
            part = data['part']
        names = read_json(bake / 'atlas_triangles.json')['parts']
        require(part.shape == (PAINT_SIZE, PAINT_SIZE), 'Expected the current paint registration bake')
        if adapted:
            source_path = resolve(manifest['source_atlas_manifest'], full)
            source_directory = source_path.parent
            source_manifest = read_json(source_path)
            source_alignment = read_json(source_directory / 'alignment.json')
            source_stitch = read_json(source_directory / 'stitch.json')
            require(source_manifest['schema_version'] == 1 and len(source_manifest['groups']) == 33 and
                    source_alignment == source_stitch['groups'] == alignment and
                    'error' not in source_stitch and source_stitch['old_quadrant_fallback_texels'] == 0,
                    'Current/native alignment or native stitch evidence differs')
            check_inputs(source_manifest, source_directory)
            generation_inputs = source_manifest['generation_input_sha256']
            source_bakes = [resolve(value, source_directory) for value, digest in generation_inputs.items()
                            if Path(value).name == 'geometry_maps.npz' and
                            digest == source_manifest['source_generation_bake_sha256']]
            require(len(source_bakes) == 1, 'Missing immutable generation geometry bake')
            source_bake = source_bakes[0]
            for value, digest in generation_inputs.items():
                require(sha256(resolve(value, source_directory)) == digest,
                        f'Generation-atlas input changed: {value}')
            with np.load(source_bake, allow_pickle=False) as data:
                source_part = data['part']
            source_names = read_json(source_bake.with_name('atlas_triangles.json'))['parts']
            native_report = {'groups': {}}
            source_checks(source_manifest, source_alignment, source_directory, native_report)
            _, source_owner = coverage_checks(source_manifest, source_alignment,
                read_json(source_directory / 'coverage.json'), source_stitch, source_directory,
                source_part, source_names, native_report)
            report['native_source'] = {**native_report, 'manifest': evidence(source_path),
                'alignment': evidence(source_directory / 'alignment.json'),
                'stitch': evidence(source_directory / 'stitch.json'), 'bake': evidence(source_bake)}
            report['groups'] = {name: dict(group) for name, group in native_report['groups'].items()}
            report['shared_style'] = native_report['shared_style']
            used, owner = current_coverage_checks(manifest, alignment, coverage, stitch, full, part, names,
                report, source_manifest, source_part, source_names, source_owner)
            mapping_geometry_checks(coverage, full, bake / 'geometry_maps.npz', source_bake, report)
        else:
            source_checks(manifest, alignment, full, report)
            used, owner = coverage_checks(manifest, alignment, coverage, stitch, full, part, names, report)
        alignment_summary(full, report)
        map_checks(full, bake, composition, report)
        failed_liveries = seam_checks(full, bake, used, owner, manifest['groups'], report)
        require(not failed_liveries, 'Seam median exceeds unchanged 2.26 policy for liveries: ' + ', '.join(failed_liveries))
        report['status'] = 'pass'
    except (OSError, ValueError, KeyError, TypeError) as error:
        report.update(status='failed', error=str(error))
        write_json(full / 'measurements.json', report)
        raise
    write_json(full / 'measurements.json', report)
    print('FULL SKIN OFFLINE PASS', full / 'measurements.json')


def font(size):
    try:
        return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError:
        return ImageFont.load_default(size=size)


def rebind_alignment(full):
    """Retain renders after a measurement-only correction, requiring identical map bytes."""
    require(read_json(full / 'measurements.json')['status'] == 'pass', 'Measurements must pass before render evidence is rebound')
    manifest_path = full / 'render_manifest.json'
    manifest = read_json(manifest_path)
    require(manifest['requested_complete'], 'Finish all requested renders first')
    previous = full / 'alignment-before-hole-fix.json'
    previous_hash = sha256(previous)
    current_hash = sha256(full / 'alignment.json')
    maps = {name: sha256(full / 'art/export/textures' / name) for name in MAPS}
    for entry in manifest['renders']:
        require(entry['status'] == 'rendered' and entry['map_sha256'] == maps,
                'Changed rendered maps require rerendering: ' + entry['file'])
        require(entry['alignment_sha256'] == previous_hash, 'Unexpected prior alignment report')
        require(sha256(full / 'renders' / entry['file']) == entry['png_sha256'], 'Render bytes changed')
    backup = full / 'render_manifest-before-hole-fix.json'
    require(not backup.exists(), 'Original render evidence already retained')
    backup.write_bytes(manifest_path.read_bytes())
    for entry in manifest['renders']:
        entry['alignment_sha256_at_render'] = entry['alignment_sha256']
        entry['alignment_sha256'] = current_hash
    manifest['alignment_revalidation'] = {
        'reason': 'exclude dark UV holes from native companion feature evidence',
        'previous_report': evidence(previous), 'current_report': evidence(full / 'alignment.json'),
        'policy': 'all nine rendered map SHA-256 hashes are unchanged; retain pixels with revised measurement evidence',
        'retained_renders': len(manifest['renders'])}
    manifest['alignment_sha256'] = current_hash
    manifest['alignment'] = {'path': (full / 'alignment.json').as_posix(), 'status': 'available',
                             'sha256': current_hash, 'report': read_json(full / 'alignment.json')}
    write_json(manifest_path, manifest)
    print('RENDER ALIGNMENT EVIDENCE UPDATED; MAP PIXELS UNCHANGED', len(manifest['renders']))


def sheets(full, overview_only=False):
    manifest = read_json(full / 'parts.json')
    renders = read_json(full / 'render_manifest.json')
    alignment = read_json(full / 'alignment.json')
    require(set(alignment) == set(manifest['groups']), 'Incomplete alignment groups')
    output = full / 'review'
    output.mkdir(parents=True, exist_ok=True)
    maps = {name: sha256(full / 'art/export/textures' / name) for name in MAPS}
    alignment_hash = sha256(full / 'alignment.json')
    selected = renders['renders']
    excluded = []
    if overview_only:
        excluded = [entry['file'] for entry in selected if entry['group'] is not None]
        selected = [entry for entry in selected if entry['group'] is None]
        expected = {(None, 'overview', livery, view) for livery in range(1, 5)
                    for view in ('top', 'side', 'front_quarter', 'rear_quarter')}
        require(len(selected) == 16 and
                {(entry['group'], entry['material'], entry['livery'], entry['view'])
                 for entry in selected} == expected, 'Expected exactly 16 livery overview views')
        require(renders['requested_complete'], 'Overview rendering is incomplete')
        bake = resolve(manifest['bake'], full)
        check_inputs(renders, full, [full / 'parts.json', bake, bake.with_name('atlas_triangles.json')])
        geometry = resolve(renders['geometry'], full)
        require(geometry.resolve() == bake.with_name('skin.blend').resolve(),
                'Overview manifest uses another geometry scene')
        geometry_hash = sha256(geometry)
        require(renders['geometry_sha256'] == geometry_hash and
                all(entry['geometry_sha256'] == geometry_hash for entry in selected),
                'Overview renders use stale geometry')
    records, entries = [], {}
    for entry in selected:
        key = (entry['group'], entry['material'], entry['livery'], entry['view'])
        require(key not in entries, f'Duplicate render entry: {key}')
        path = resolve(entry['file'], full / 'renders')
        record = {'group': entry['group'], 'material': entry['material'], 'livery': entry['livery'],
                  'view': entry['view'], 'declared_status': entry['status'], 'path': path.as_posix()}
        if path.is_file():
            record.update(image_evidence(path))
            require(record['size'] == renders['resolution'], f'Render dimensions differ: {path}')
            record['status'] = 'rendered' if entry['status'] == 'rendered' else 'unconfirmed'
            if record['status'] == 'rendered':
                require(record['sha256'] == entry['png_sha256'], f'Render PNG hash differs: {path}')
                consumed = ['Icarus_skin_n.png', 'Icarus_skin_ao.png']
                if entry['material'] != 'clay':
                    consumed += [('Icarus_livery_4_m.png' if entry['livery'] == 4 else 'Icarus_skin_m.png'),
                                 f'Icarus_livery_{entry["livery"]}.png']
                require(all(entry['map_sha256'].get(name) == maps[name] for name in consumed) and entry['alignment_sha256'] == alignment_hash,
                        f'Render uses stale maps/alignment: {path}')
                record['consumed_map_sha256'] = {name: maps[name] for name in consumed}
                record['changed_unused_maps'] = [name for name in maps
                                                if name not in consumed and entry['map_sha256'].get(name) != maps[name]]
                if entry['group'] is not None:
                    camera = entry['camera']
                    bounds = np.asarray(camera['framing_bounds_m'])
                    corners = np.array([[x, y, z] for x in bounds[:, 0]
                                        for y in bounds[:, 1] for z in bounds[:, 2]])
                    projected = (corners - camera['target']) @ np.asarray(camera['basis_rows']).T
                    half_frame = np.array([camera['ortho_scale'] / 2,
                                           camera['ortho_scale'] * renders['resolution'][1] / renders['resolution'][0] / 2])
                    extent = np.max(abs(projected[:, :2]) / half_frame, axis=0)
                    require(float(extent.max()) <= 1 / 1.2 + 1e-6,
                            f'Visible mesh bounds exceed framing margin: {path}')
                    record['minimum_frame_margin_fraction'] = float((1 - extent.max()) / 2)
        else:
            record['status'] = 'missing'
        entries[key] = (entry, record)
        records.append(record)
    review = {'schema_version': 1, 'owner_acceptance': 'pending', 'render_manifest': evidence(full / 'render_manifest.json'),
              'scope': 'livery overviews only' if overview_only else 'groups and livery overviews',
              'excluded_group_renders': excluded,
              'renders': records, 'pages': [], 'groups': {}, 'missing_required': []}

    def tile(canvas, box, pair, caption):
        x, y, width, height = box
        draw = ImageDraw.Draw(canvas)
        draw.text((x + 10, y + 6), caption, fill='white', font=font(19))
        status = pair[1]['status'] if pair else 'not requested' if caption.startswith('Navy not requested') else 'missing'
        draw.text((x + 10, y + 31), status, fill='#acbbc8' if status in ('rendered', 'not requested') else '#ffca78', font=font(17))
        if pair and Path(pair[1]['path']).is_file():
            with Image.open(pair[1]['path']) as image:
                image = image.convert('RGB')
                image.thumbnail((width - 12, height - 62), Image.Resampling.LANCZOS)
                canvas.paste(image, (x + (width - image.width) // 2, y + 58 + (height - 62 - image.height) // 2))

    def save_page(canvas, filename, members):
        require(max(canvas.size) <= 2000, 'Contact sheet exceeds 2000 pixels')
        path = output / filename
        canvas.save(path)
        review['pages'].append({**image_evidence(path), 'members': members})

    # Two group rows per page leave each primary clay/Navy view about 1000 px wide.
    rows = []
    for name in (() if overview_only else manifest['groups']):
        clay = sorted((pair for key, pair in entries.items() if key[0] == name and key[1] == 'clay'),
                      key=lambda pair: pair[0]['view'])
        navy = {key[3]: pair for key, pair in entries.items() if key[0] == name and key[1] == 'navy'}
        status = ', '.join(f'{kind}: {alignment[name]["companions"][kind]["status"]}' for kind in ('height', 'roughness'))
        review['groups'][name] = {'companion_status': status, 'clay_views': len(clay), 'navy_views': len(navy),
                                  'source_stitch': manifest['groups'][name].get('source_stitch')}
        if not clay or not navy:
            review['missing_required'].append(f'{name}: Clay and Navy required')
        for index, pair in enumerate(clay or [None]):
            view = pair[0]['view'] if pair else 'face_01'
            right = navy.get(view)
            if index == 0 and right is None:
                review['missing_required'].append(f'{name}: matched primary Clay/Navy camera required')
            if right and pair:
                require(pair[0]['camera'] == right[0]['camera'],
                        f'Clay/Navy camera differs: {name} {view}')
            rows.append((name, view, pair, right, status))
    for start in range(0, len(rows), 2):
        page_rows = rows[start:start + 2]
        canvas = Image.new('RGB', (2000, 760 * len(page_rows) + 50), '#161c23')
        draw = ImageDraw.Draw(canvas)
        draw.text((14, 12), 'Full skin review | offline evidence | owner acceptance pending', fill='white', font=font(22))
        members = []
        for row, (name, view, clay, navy, status) in enumerate(page_rows):
            y = 50 + row * 760
            draw.text((12, y + 5), f'{name} | {view} | {status}', fill='white', font=font(20))
            if manifest['groups'][name].get('source_stitch'):
                draw.text((12, y + 32), 'Recorded source stitch; reused art', fill='#ffca78', font=font(18))
            tile(canvas, (0, y + 60, 1000, 690), clay, 'Clay')
            tile(canvas, (1000, y + 60, 1000, 690), navy, 'Navy' if navy else 'Navy not requested for this extra face')
            members.append({'group': name, 'view': view})
        save_page(canvas, f'groups_{start // 2 + 1:02d}.png', members)
    for livery in range(1, 5):
        canvas = Image.new('RGB', (2000, 1450), '#161c23')
        ImageDraw.Draw(canvas).text((14, 12), f'Livery {livery} | owner acceptance pending', fill='white', font=font(24))
        for i, view in enumerate(('top', 'side', 'front_quarter', 'rear_quarter')):
            pair = entries.get((None, 'overview', livery, view))
            if pair is None:
                review['missing_required'].append(f'livery {livery}: {view}')
            tile(canvas, ((i % 2) * 1000, 50 + (i // 2) * 700, 1000, 700), pair, view)
        save_page(canvas, f'livery_{livery}_overviews.png', [{'livery': livery}])
    review['counts'] = {'manifest_renders': len(records), 'rendered': sum(r['status'] == 'rendered' for r in records),
                         'missing': sum(r['status'] == 'missing' for r in records), 'pages': len(review['pages']),
                         'groups': len(review['groups'])}
    review['status'] = 'complete' if not review['missing_required'] and all(r['status'] == 'rendered' for r in records) else 'incomplete'
    write_json(output / 'render_manifest.json', review)
    require(review['status'] == 'complete', 'Review sheets include missing/unconfirmed renders; see review/render_manifest.json')
    print('FULL SKIN SHEETS PASS', len(review['pages']), output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('measure', 'sheets', 'rebind-alignment'))
    parser.add_argument('--full', type=Path, default=FULL)
    parser.add_argument('--bake', type=Path, default=BAKE)
    parser.add_argument('--overview-only', action='store_true', help='sheet only the 16 current livery overviews')
    args = parser.parse_args()
    if args.overview_only and args.mode != 'sheets':
        parser.error('--overview-only applies only to sheets')
    if args.mode == 'measure':
        measure(args.full.resolve(), args.bake.resolve())
    elif args.mode == 'sheets':
        sheets(args.full.resolve(), args.overview_only)
    else:
        rebind_alignment(args.full.resolve())
