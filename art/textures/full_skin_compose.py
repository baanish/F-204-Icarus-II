"""Assemble generated part fields on one shared registration and atlas transfer map."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, distance_transform_edt, find_objects, gaussian_filter, label
from scipy.optimize import linear_sum_assignment

from companion_maps import validate_companion
from rasterize import ROOT, sample


HEIGHT_FLUSH = 128 / 255
HEIGHT_SPAN_PX = .24
LEGACY_HEIGHT_SCALE = .3


def source_charts(image, count, layout=None):
    """Close dark panel strokes without filling legitimate holes in UV charts."""
    silhouette = binary_closing(image.mean(axis=2) > .32, iterations=3)
    if layout is not None:
        labels = np.zeros(silhouette.shape, np.int32)
        candidates = []
        for source_id, chart in enumerate(layout['charts'], 1):
            x0, y0, x1, y1 = chart['target_box']
            box = (slice(y0, y1), slice(x0, x1))
            local = silhouette[box]
            if not local.any() or np.any(labels[box][local]):
                raise ValueError('Empty or overlapping explicit source chart')
            labels[box][local] = source_id
            candidates.append((source_id, box, int(local.sum())))
        if len(candidates) != count:
            raise ValueError(f'Expected {count} explicit source charts, found {len(candidates)}')
        return labels, candidates
    labels, _ = label(silhouette)
    candidates = [(i, box, int((labels[box] == i).sum())) for i, box in enumerate(find_objects(labels), 1)
                  if box is not None and (labels[box] == i).sum() > 200]
    candidates = sorted(candidates, key=lambda c: -c[2])[:count]
    if len(candidates) != count:
        raise ValueError(f'Expected {count} source silhouettes, found {len(candidates)}')
    candidates.sort(key=lambda c: (c[1][0].start, c[1][1].start))
    return labels, candidates


def _path(value, directory):
    path = Path(value)
    return path if path.is_absolute() else directory / path


def _read_image(path, rgb=False):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB' if rgb else 'L'), np.float32) / 255


def _write_report(path, report):
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')


def _companion(image, name, kind, directory, cache):
    path = directory / f'{name}_{kind}.png'
    record = cache / f'{name}_{kind}.generation.json'
    generation = json.loads(record.read_text()) if record.exists() else None
    report = {'path': str(path), 'status': 'fallback', 'generation': generation,
              'fallback_policy': 'legacy surface relief derived from this generated base'}
    if not path.exists():
        failed = generation and (generation.get('error') or generation.get('generation_error') or generation.get('status') in
                                 ('failed', 'error', 'generation_failed') or generation.get('success') is False)
        if not failed:
            raise ValueError(f'{name} {kind}: missing companion and explicit generation failure record: {record}')
        report['validation'] = {'accepted': False, 'reasons': ['companion generation failed']}
        return None, report
    companion = _read_image(path)
    report['native_size'] = [companion.shape[1], companion.shape[0]]
    report['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    if companion.shape != image.shape[:2]:
        report['validation'] = {'accepted': False, 'reasons': ['native dimensions differ; resizing is forbidden']}
        return None, report
    report['validation'] = validate_companion(image, companion, kind)
    if not report['validation']['accepted']:
        return None, report
    report['status'] = 'accepted'
    report['fallback_policy'] = None
    return companion, report


def _derived_fields(image, inside):
    luminance = image @ np.array((.2126, .7152, .0722))
    support = gaussian_filter(inside.astype(float), 18)
    mean = gaussian_filter(np.where(inside, luminance, 0), 18) / np.maximum(support, 1e-8)
    residual = np.clip((luminance - mean) * 1.65, -.25, .2)
    # Invalid fields are previews of base-derived relief, kept as alignment evidence only;
    # production relief comes from panels.py's airframe layout.
    return (np.clip(HEIGHT_FLUSH + residual * LEGACY_HEIGHT_SCALE / HEIGHT_SPAN_PX, 0, 1),
            np.clip(.6 + .08 * np.clip(-residual / .5, 0, 1) + .04 * np.clip(abs(residual) / .2, 0, 1), 0, 1))


def _chart_mask(name, chart, group_mask, directory):
    x0, y0, x1, y1 = chart['atlas_box']
    if not (0 <= x0 < x1 <= group_mask.shape[1] and 0 <= y0 < y1 <= group_mask.shape[0]):
        raise ValueError(f'{name}: chart atlas_box is outside atlas: {chart["atlas_box"]}')
    selected = group_mask[y0:y1, x0:x1]
    if chart.get('mask'):
        chart_mask = _read_image(_path(chart['mask'], directory)) > 0
        if chart_mask.shape != group_mask.shape or np.any(chart_mask & ~group_mask):
            raise ValueError(f'{name}: chart mask must be an atlas-sized subset of its group mask')
        if int(chart_mask.sum()) != int(chart_mask[y0:y1, x0:x1].sum()):
            raise ValueError(f'{name}: chart mask extends outside atlas_box')
        selected = chart_mask[y0:y1, x0:x1]
    if not selected.any():
        raise ValueError(f'{name}: empty chart mask in {chart["atlas_box"]}')
    return selected


def _registration_metrics(chart, source_id, box, labels, selected):
    x0, y0, x1, y1 = chart['atlas_box']
    sy, sx = box
    sh, sw = sy.stop - sy.start, sx.stop - sx.start
    rotated = chart.get('rotate_ccw', False)
    target_w, target_h = (y1 - y0, x1 - x0) if rotated else (x1 - x0, y1 - y0)
    density = min(sw / target_w, sh / target_h) * 150
    inside = labels[box] == source_id
    silhouette = np.rot90(inside, -1) if rotated else inside
    silhouette = np.asarray(Image.fromarray(silhouette).resize((x1 - x0, y1 - y0), Image.Resampling.NEAREST))
    iou = float((silhouette & selected).sum() / (silhouette | selected).sum())
    return {'chart': chart.get('component', chart.get('chart_key')),
            'atlas_box': chart['atlas_box'], 'guide_box': chart['guide_box'],
            'source_component': int(source_id),
            'source_box': [sx.start, sy.start, sx.stop, sy.stop],
            'rotate_ccw': rotated, 'normalized_silhouette_iou': iou,
            'native_px_per_m_min_axis': density, 'selected_texels': int(selected.sum())}


def _match_charts(name, charts, labels, candidates, group_mask, directory, guide_size):
    """Match whole base components once; topmost pixels do not define guide rows."""
    if len(charts) != len(candidates):
        raise ValueError(f'{name}: expected {len(charts)} source silhouettes, found {len(candidates)}')
    costs = np.empty((len(charts), len(candidates)))
    for row, chart in enumerate(charts):
        selected = _chart_mask(name, chart, group_mask, directory)
        gx0, gy0, gx1, gy1 = chart['guide_box']
        guide_center = np.array((gx0 + gx1, gy0 + gy1)) / (2 * guide_size)
        for column, (source_id, box, _) in enumerate(candidates):
            evidence = _registration_metrics(chart, source_id, box, labels, selected)
            sy, sx = box
            source_center = np.array((sx.start + sx.stop, sy.start + sy.stop)) / (
                2 * np.array(labels.shape[::-1]))
            invalid = (evidence['native_px_per_m_min_axis'] < 180 or
                       evidence['normalized_silhouette_iou'] < .70)
            # A feasible complete assignment always wins. If none exists, retain
            # the best correspondence so the unchanged gates report the rejection.
            costs[row, column] = (invalid * 4 * (len(charts) + 1) +
                                  1 - evidence['normalized_silhouette_iou'] +
                                  np.linalg.norm(source_center - guide_center))
    rows, columns = linear_sum_assignment(costs)
    return [candidates[column] for _, column in sorted(zip(rows, columns))]


def _chart_registration(name, chart, source_id, box, labels, group_mask, directory):
    selected = _chart_mask(name, chart, group_mask, directory)
    evidence = _registration_metrics(chart, source_id, box, labels, selected)
    density = evidence['native_px_per_m_min_axis']
    if density < 180:
        raise ValueError(f'{name}: chart {evidence["chart"]} source {evidence["source_box"]} '
                         f'registered native source density {density:.6f} below 180 px/m')
    iou = evidence['normalized_silhouette_iou']
    if iou < .70:
        raise ValueError(f'{name}: chart {evidence["chart"]} source {evidence["source_box"]} '
                         f'normalized silhouette IoU {iou:.6f} below 0.70')
    x0, y0, x1, y1 = chart['atlas_box']
    rotated = chart.get('rotate_ccw', False)
    inside = labels[box] == source_id
    yy, xx = np.mgrid[:y1 - y0, :x1 - x0]
    u, v = (xx + .5) / (x1 - x0), (yy + .5) / (y1 - y0)
    if rotated:
        u, v = v, 1 - u
    # One nearest-paint extension and one coordinate grid apply to all five channels.
    _, nearest = distance_transform_edt(~inside, return_indices=True)
    return selected, u, v, nearest, evidence


def assemble_full(manifest_path):
    """Return atlas base RGB, raw scalar fields, validity masks and JSON-safe evidence.

    Unused atlas texels are black. Every used texel must originate in a generated
    base or an ordered coverage transfer. An absent companion needs an explicit
    failed-generation record; a rejected native companion uses base-derived relief.
    """
    path = Path(manifest_path)
    directory = path.parent
    manifest = json.loads(path.read_text())
    for input_path, expected in manifest.get('input_sha256', {}).items():
        source_input = _path(input_path, directory)
        if not source_input.is_file() or hashlib.sha256(source_input.read_bytes()).hexdigest() != expected:
            raise ValueError('Stale part inventory; rebuild guides and inventory for changed input: ' + str(source_input))
    if manifest.get('source_atlas_manifest'):
        from source_atlas_mapping import remap_fields
        source_path = _path(manifest['source_atlas_manifest'], directory)
        if source_path.resolve() == path.resolve():
            raise ValueError('Source atlas manifest cannot reference itself')
        source_manifest = json.loads(source_path.read_text())
        if source_manifest.get('source_atlas_manifest'):
            raise ValueError('Source atlas registration must use an immutable native manifest')
        fields = remap_fields(assemble_full(source_path), path)
        _write_report(directory / 'alignment.json', fields['report']['groups'])
        _write_report(directory / 'stitch.json', fields['report'])
        Image.fromarray(np.round(np.clip(fields['base'], 0, 1) * 255).astype('uint8')).save(directory / 'assembled.png')
        return fields
    coverage = json.loads((directory / 'coverage.json').read_text())
    groups = manifest['groups']
    first_mask = _read_image(_path(next(iter(groups.values()))['mask'], directory)) > 0
    shape = first_mask.shape
    if shape != (2048, 2048) and manifest.get('atlas_size') != shape[0]:
        raise ValueError(f'Expected a 2048 atlas or an explicit test atlas_size, got {shape}')
    fields = {'base': np.zeros((*shape, 3), np.float32),
              'height': np.full(shape, HEIGHT_FLUSH, np.float32),
              'roughness': np.full(shape, .6, np.float32),
              'height_valid': np.zeros(shape, bool), 'roughness_valid': np.zeros(shape, bool),
              'used': np.zeros(shape, bool)}
    companion_dir = _path(manifest.get('companion_dir', ROOT / 'art/textures/generated/full'), directory)
    report = {'groups': {}, 'transfers': [], 'atlas_size': list(shape[::-1]),
              'registration_policy': 'one-to-one base silhouettes by guide position and shape after closing 3, '
                                     'preserving UV holes; '
                                     'identical coordinates for every field',
              'minimum_normalized_silhouette_iou': .70, 'minimum_native_px_per_m': 180,
              'outside_used_base': 'black', 'old_quadrant_fallback_texels': 0}
    fields['report'] = report
    try:
        for name, group in groups.items():
            source = _path(group['source_path'], directory)
            if not source.exists():
                raise ValueError(f'{name}: missing generated base: {source}')
            image = _read_image(source, True)
            charts = sorted(group['charts'], key=lambda c: (c['guide_box'][1], c['guide_box'][0]))
            labels, candidates = source_charts(image, len(charts), group.get('source_stitch'))
            mask = _read_image(_path(group['mask'], directory)) > 0
            if mask.shape != shape or np.any(mask & fields['used']):
                raise ValueError(f'{name}: group mask dimensions differ or groups overlap')
            candidates = _match_charts(name, charts, labels, candidates, mask, directory,
                                       manifest.get('guide_size', 1536))
            group_report = {'native_size': list(image.shape[1::-1]), 'source_path': str(source),
                            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                            'registration': [], 'companions': {}, 'skin_texels': int(mask.sum())}
            report['groups'][name] = group_report
            painted = np.isin(labels, [candidate[0] for candidate in candidates])
            derived = _derived_fields(image, painted)
            maps = []
            accepted = []
            for kind, fallback in zip(('height', 'roughness'), derived):
                companion, evidence = _companion(image, name, kind, companion_dir, directory)
                group_report['companions'][kind] = evidence
                maps.append(fallback if companion is None else companion)
                accepted.append(companion is not None)
            packed = np.dstack((image, *maps))
            covered = np.zeros(shape, bool)
            for chart, (source_id, box, _) in zip(charts, candidates):
                selected, u, v, nearest, evidence = _chart_registration(
                    name, chart, source_id, box, labels, mask, directory)
                x0, y0, x1, y1 = chart['atlas_box']
                local_covered = covered[y0:y1, x0:x1]
                if np.any(local_covered & selected):
                    raise ValueError(f'{name}: chart masks overlap')
                padded = packed[box][nearest[0], nearest[1]]
                mapped = sample(padded, u, v)
                fields['base'][y0:y1, x0:x1][selected] = mapped[..., :3][selected]
                for channel, kind, valid in zip((3, 4), ('height', 'roughness'), accepted):
                    fields[kind][y0:y1, x0:x1][selected] = mapped[..., channel][selected]
                    fields[kind + '_valid'][y0:y1, x0:x1][selected] = valid
                local_covered |= selected
                group_report['registration'].append(evidence)
            if not np.array_equal(covered, mask):
                raise ValueError(f'{name}: chart masks leave {int((mask & ~covered).sum())} group texels uncovered')
            fields['used'] |= covered
            group_report['native_px_per_m_min_axis'] = min(
                c['native_px_per_m_min_axis'] for c in group_report['registration'])
            print('FULL SOURCE PASS', name, {kind: evidence['status']
                  for kind, evidence in group_report['companions'].items()}, flush=True)
        for rule in coverage['rules']:
            with np.load(_path(rule['map'], directory)) as transfer:
                target, source = transfer['target_indices'], transfer['source_indices']
                if (target.ndim != 1 or source.shape != target.shape or
                    not np.issubdtype(target.dtype, np.integer) or not np.issubdtype(source.dtype, np.integer) or
                    np.any(target < 0) or np.any(source < 0) or
                    np.any(target >= np.prod(shape)) or np.any(source >= np.prod(shape))):
                    raise ValueError(f'{rule["name"]}: invalid flattened transfer indices')
                if not fields['used'].ravel()[source].all():
                    raise ValueError(f'{rule["name"]}: transfer reads unassigned source texels')
                if np.unique(target).size != target.size:
                    raise ValueError(f'{rule["name"]}: transfer has duplicate target indices')
                for key in ('base', 'height', 'roughness', 'height_valid', 'roughness_valid', 'used'):
                    flat = fields[key].reshape((-1, 3) if key == 'base' else (-1,))
                    flat[target] = flat[source]
                report['transfers'].append({'name': rule['name'], 'mode': rule.get('mode'),
                                            'texels': int(target.size),
                                            'matched_texels': int(transfer['matched'].sum()) if 'matched' in transfer else None})
        report['assigned_texels'] = int(fields['used'].sum())
        if coverage.get('assigned_texels', report['assigned_texels']) != report['assigned_texels']:
            raise ValueError(f'Atlas assigned texels {report["assigned_texels"]} differ from coverage '
                             f'{coverage["assigned_texels"]}')
        report['height_accepted_texels'] = int(fields['height_valid'].sum())
        report['roughness_accepted_texels'] = int(fields['roughness_valid'].sum())
    except (ValueError, OSError) as error:
        report['error'] = str(error)
        _write_report(directory / 'alignment.json', report['groups'])
        _write_report(directory / 'stitch.json', report)
        raise
    _write_report(directory / 'alignment.json', report['groups'])
    _write_report(directory / 'stitch.json', report)
    Image.fromarray(np.round(np.clip(fields['base'], 0, 1) * 255).astype('uint8')).save(directory / 'assembled.png')
    return fields
