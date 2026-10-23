"""Conservative native-grid checks for generated height and roughness companions.

Acceptance deliberately requires both seams and fasteners. Smooth parts without
that evidence need a derived fallback, even when their generated map looks good.
128/255 is flush height; white is raised and black is recessed. No input is
resized or registered. Offset is companion displacement, positive right/down.
"""
import numpy as np
from scipy.ndimage import (
    binary_closing, binary_dilation, binary_erosion, binary_fill_holes, distance_transform_edt, find_objects,
    gaussian_filter, label,
)
from scipy.signal import fftconvolve
from scipy.optimize import linear_sum_assignment


# These are acceptance decisions, not measurements of physical joint dimensions.
THRESHOLDS = {
    'boundary_exclusion_px': 8,
    'feature_tolerance_px': 1.0,
    'offset_magnitude_exclusive_px': 1.0,
    'offset_guard_band_px': 0.10,
    'minimum_precision': 0.75,
    'minimum_recall': 0.75,
    'minimum_seam_pixels': 32,
    'minimum_seam_components': 1,
    'minimum_fastener_pixels': 6,
    'minimum_fastener_components': 3,
    'minimum_interior_pixels': 256,
    'minimum_silhouette_iou': 0.95,
    'minimum_correlation': 0.60,
    'minimum_peak_margin': 0.05,
    'base_dark_residual': 0.045,
    'companion_deviation': 0.045,
    'paint_luminance': 0.32,
    'minimum_island_pixels': 256,
    'roughness_background_contrast': 0.08,
    'feature_prefilter_sigma_px': 0.8,
    'minimum_component_pixels': 4,
    # Native source circles include their rim; panels.py's seven-texel limit
    # describes the final atlas rather than these oversampled source marks.
    'maximum_fastener_span_px': 12,
    'maximum_fastener_aspect': 2.0,
    'minimum_fastener_fill': 0.2,
}


def _scalar(image):
    if image.ndim == 3:
        return image @ np.array((0.2126, 0.7152, 0.0722))
    return image.astype(float, copy=False)


def _islands(candidate):
    silhouette = binary_closing(candidate, iterations=3)
    labels, _ = label(silhouette)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= THRESHOLDS['minimum_island_pixels']
    keep[0] = False
    # The accepted part guides have a dark canvas margin. A uniform grey canvas
    # or a filled background is not a painted island.
    # Closing trims three pixels at the canvas edge, so inspect the whole
    # trimmed band rather than just the now-empty outermost row.
    keep[np.unique(np.concatenate((labels[:4].ravel(), labels[-4:].ravel(),
                                   labels[:, :4].ravel(), labels[:, -4:].ravel())))] = False
    return keep[labels]


def _local_residual(values, islands):
    support = gaussian_filter(islands.astype(float), 18)
    mean = gaussian_filter(np.where(islands, values, 0), 18) / np.maximum(support, 1e-8)
    return values - mean


def _features(candidate, opposite=None):
    masks = {name: np.zeros(candidate.shape, bool) for name in ('seams', 'fasteners')}
    # A raised core and recessed ring belong to one fastener. Classify signed
    # contrast separately, fill compact rings, then merge their overlapping masks.
    for signed_candidate in (candidate,) if opposite is None else (candidate, opposite):
        labels, _ = label(signed_candidate)
        for index, box in enumerate(find_objects(labels), 1):
            if box is None:
                continue
            region = labels[box] == index
            pixels = int(region.sum())
            if pixels < THRESHOLDS['minimum_component_pixels']:
                continue
            height, width = region.shape
            compact = (min(height, width) >= 2
                       and max(height, width) <= THRESHOLDS['maximum_fastener_span_px']
                       and max(height, width) / min(height, width) <= THRESHOLDS['maximum_fastener_aspect']
                       and pixels / (height * width) >= THRESHOLDS['minimum_fastener_fill'])
            group = 'fasteners' if compact else 'seams'
            masks[group][box] |= binary_fill_holes(region) if compact else region
    components = {}
    for group, mask in masks.items():
        # One-pixel gaps between signed rim/core fragments do not create extra
        # fasteners. Dilation groups fragments only; retain original footprint
        # pixels for centroids and secondary area scores.
        labels, _ = label(binary_dilation(mask) if group == 'fasteners' else mask)
        components[group] = []
        for index, box in enumerate(find_objects(labels), 1):
            if box is None:
                continue
            region = (labels[box] == index) & mask[box]
            yy, xx = np.where(region)
            trimmed = (slice(box[0].start + int(yy.min()), box[0].start + int(yy.max()) + 1),
                       slice(box[1].start + int(xx.min()), box[1].start + int(xx.max()) + 1))
            components[group].append((trimmed, region[yy.min():yy.max()+1, xx.min():xx.max()+1]))
    return masks, components


def _structural_features(values, interior, kind):
    # The source art contains single-pixel paint grain. Require coherent native
    # support before thresholding instead of calling every dark grain a rivet.
    sigma = THRESHOLDS['feature_prefilter_sigma_px']
    support = gaussian_filter(interior.astype(float), sigma)
    filtered = gaussian_filter(np.where(interior, values, 0), sigma) / np.maximum(support, 1e-8)
    residual = _local_residual(filtered, interior)
    threshold = THRESHOLDS['base_dark_residual'] if kind == 'base' else THRESHOLDS['companion_deviation']
    # Estimate the plane from flat support. Including the strokes themselves
    # creates opposite-sign halos whose width changes with the stroke width.
    flat = interior & (abs(residual) <= threshold)
    flat_support = gaussian_filter(flat.astype(float), 18)
    plane = gaussian_filter(np.where(flat, filtered, 0), 18) / np.maximum(flat_support, 1e-8)
    residual = np.where(flat_support > 1e-6, filtered - plane, residual)
    dark = interior & (residual < -threshold)
    bright = None if kind == 'base' else interior & (residual > threshold)
    masks, components = _features(dark, bright)
    strength = np.maximum(-residual, 0) if kind == 'base' else abs(residual)
    return strength, masks, components


def _feature_score(expected, actual, expected_components, actual_components):
    tolerance = THRESHOLDS['feature_tolerance_px']
    near_expected = distance_transform_edt(~expected) <= tolerance if expected.any() else expected
    near_actual = distance_transform_edt(~actual) <= tolerance if actual.any() else actual
    expected_pixels, actual_pixels = int(expected.sum()), int(actual.sum())
    recalled, precise = int((expected & near_actual).sum()), int((actual & near_expected).sum())

    def component_reports(components, near, metric):
        return [
            {'box_xyxy': [box[1].start, box[0].start, box[1].stop, box[0].stop],
             'pixels': int(region.sum()), 'matched_pixels': int((region & near[box]).sum()),
             metric: float((region & near[box]).sum() / region.sum())}
            for box, region in components
        ]

    return {
        'precision': precise / actual_pixels if actual_pixels else 0.0,
        'recall': recalled / expected_pixels if expected_pixels else 0.0,
        'counts': {'base_pixels': expected_pixels, 'companion_pixels': actual_pixels,
                   'matched_companion_pixels': precise, 'matched_base_pixels': recalled,
                   'base_components': len(expected_components),
                   'companion_components': len(actual_components)},
        'base_features': component_reports(expected_components, near_actual, 'recall'),
        'companion_features': component_reports(actual_components, near_expected, 'precision'),
    }


def _seam_centrelines(mask):
    # The same morphological medial construction used by panels.py, evaluated
    # on the native grid. Stroke area never contributes positional samples.
    centreline = np.zeros(mask.shape, bool)
    remaining = mask.copy()
    while remaining.any():
        eroded = binary_erosion(remaining)
        centreline |= remaining & ~binary_dilation(eroded)
        remaining = eroded
    return centreline


def _match_centres(expected, actual):
    if not len(expected) or not len(actual):
        return []
    distances = np.linalg.norm(expected[:, None, :] - actual[None, :, :], axis=2)
    tolerance = THRESHOLDS['feature_tolerance_px']
    # An invalid match costs more than all valid matches combined. Assignment
    # therefore maximizes cardinality before minimizing matched displacement.
    cost = np.where(distances <= tolerance, distances, len(expected) + len(actual) + 1)
    rows, columns = linear_sum_assignment(cost)
    return [(int(i), int(j), float(distances[i, j])) for i, j in zip(rows, columns)
            if distances[i, j] <= tolerance]


def _position_score(score, expected, actual, expected_components, actual_components, group):
    if group == 'seams':
        reference, moving = _seam_centrelines(expected), _seam_centrelines(actual)
        positional = _feature_score(reference, moving, [], [])
        counts = positional['counts']
        score['position_precision'], score['position_recall'] = positional['precision'], positional['recall']
        position_counts = {'base_positions': counts['base_pixels'], 'companion_positions': counts['companion_pixels'],
                           'matched_base_positions': counts['matched_base_pixels'],
                           'matched_companion_positions': counts['matched_companion_pixels']}
        for components, records, mask, opposite, metric in (
            (expected_components, score['base_features'], reference, moving, 'recall'),
            (actual_components, score['companion_features'], moving, reference, 'precision'),
        ):
            near = distance_transform_edt(~opposite) <= THRESHOLDS['feature_tolerance_px'] if opposite.any() else opposite
            for (box, region), record in zip(components, records):
                positions = mask[box] & region
                count, matched = int(positions.sum()), int((positions & near[box]).sum())
                record.update(position_count=count, matched_position_count=matched)
                record['position_' + metric] = matched / count if count else 0.0
        score['position_method'] = 'native morphological medial seam pixels'
    else:
        def centres(components):
            result = []
            for box, region in components:
                yy, xx = np.where(region)
                result.append([float(xx.mean() + box[1].start), float(yy.mean() + box[0].start)])
            return np.asarray(result).reshape(-1, 2)

        reference, moving = centres(expected_components), centres(actual_components)
        matches = _match_centres(reference, moving)
        score['position_precision'] = len(matches) / len(moving) if len(moving) else 0.0
        score['position_recall'] = len(matches) / len(reference) if len(reference) else 0.0
        position_counts = {'base_positions': len(reference), 'companion_positions': len(moving),
                           'matched_base_positions': len(matches), 'matched_companion_positions': len(matches)}
        for records, points, side, metric in (
            (score['base_features'], reference, 0, 'recall'),
            (score['companion_features'], moving, 1, 'precision'),
        ):
            matched = {pair[side]: (pair[1 - side], pair[2]) for pair in matches}
            for index, (record, point) in enumerate(zip(records, points)):
                partner, distance = matched.get(index, (None, None))
                record.update(centre_xy=point.tolist(), position_count=1,
                              matched_position_count=int(partner is not None),
                              matched_feature_index=partner, matched_distance_px=distance)
                record['position_' + metric] = float(partner is not None)
        score['position_method'] = 'one-to-one centroids of unified compact core/rim footprints'
    score['counts'].update(position_counts)


def _offset(reference, moving):
    # Smooth correlation signals, never the maps being scored. A quadratic peak
    # fit measures fractional native texels without aligning a failed companion.
    reference = gaussian_filter(reference, .8)
    moving = gaussian_filter(moving, .8)
    norm = float(np.linalg.norm(reference) * np.linalg.norm(moving))
    if norm <= 1e-12:
        return None, 0.0, 0.0
    correlation = fftconvolve(moving, reference[::-1, ::-1], mode='full') / norm
    py, px = np.unravel_index(np.argmax(correlation), correlation.shape)
    peak = float(correlation[py, px])
    fractions = []
    for axis, position in enumerate((py, px)):
        if position == 0 or position == correlation.shape[axis] - 1:
            return None, peak, 0.0
        before, after = [py, px], [py, px]
        before[axis] -= 1
        after[axis] += 1
        left, right = float(correlation[tuple(before)]), float(correlation[tuple(after)])
        denominator = left - 2 * peak + right
        fractions.append(float(.5 * (left - right) / denominator) if denominator < -1e-12 else 0.0)
    # Repeated grids can give a high peak at multiple displacements. Reject that
    # ambiguity rather than reporting the first maximum as a confident offset.
    correlation[max(0, py - 3):py + 4, max(0, px - 3):px + 4] = -np.inf
    margin = peak - float(correlation.max())
    return [float(px - reference.shape[1] + 1 + fractions[1]),
            float(py - reference.shape[0] + 1 + fractions[0])], peak, margin


def validate_companion(base: np.ndarray, companion: np.ndarray, kind: str) -> dict:
    """Return JSON-safe evidence and acceptance; invalid input also returns a rejection.

    RGB arrays and scalar companion fields must be finite floating point 0..1.
    Acceptance uses position_precision/position_recall: medial seam pixels and
    one-to-one compact fastener centres, within one Euclidean native pixel.
    Combined positional scores pool seam pixels and fastener centres; both
    groups independently require 0.75. Legacy precision/recall measure stroke
    area and are secondary diagnostics. A deliberate 0.1 texel guard band rejects
    near-limit quadratic estimates rather than trusting their rounding error.
    Roughness uses local structural contrast of either sign and additionally
    requires a verifiable island silhouette.
    """
    report = {
        'accepted': False, 'kind': kind if isinstance(kind, str) else None,
        'offset_xy': None, 'offset_magnitude': None,
        'offset_convention': 'companion relative to base; +x right, +y down; native texels',
        'precision': 0.0, 'recall': 0.0, 'counts': {}, 'groups': {},
        'position_precision': 0.0, 'position_recall': 0.0,
        'confidence': {'correlation': 0.0, 'peak_margin': 0.0, 'verifiable': False},
        'silhouette_iou': None, 'reasons': [], 'thresholds': dict(THRESHOLDS),
    }
    reasons = report['reasons']
    if not isinstance(kind, str) or kind not in ('height', 'roughness'):
        reasons.append('kind must be height or roughness')
    if not isinstance(base, np.ndarray) or base.ndim != 3 or base.shape[-1] != 3:
        reasons.append('base must be an RGB array')
    if not isinstance(companion, np.ndarray) or not (
        companion.ndim == 2 or (companion.ndim == 3 and companion.shape[-1] == 3)
    ):
        reasons.append('companion must be a scalar field or RGB array')
    if reasons:
        return report
    for name, array in (('base', base), ('companion', companion)):
        if not np.issubdtype(array.dtype, np.floating) or not array.size or not np.isfinite(array).all():
            reasons.append(name + ' must contain finite floating point values')
        elif array.min() < 0 or array.max() > 1:
            reasons.append(name + ' must be in 0..1')
    if base.shape[:2] != companion.shape[:2]:
        reasons.append('native dimensions differ; resizing is forbidden')
    if min(base.shape[:2]) < 24:
        reasons.append('native canvas is too small for the boundary exclusion')
    if reasons:
        return report

    luminance, values = _scalar(base), _scalar(companion)
    islands = _islands(luminance > THRESHOLDS['paint_luminance'])
    interior = distance_transform_edt(islands) > THRESHOLDS['boundary_exclusion_px']
    report['counts'] = {'island_pixels': int(islands.sum()), 'interior_pixels': int(interior.sum()),
                        'excluded_boundary_pixels': int((islands & ~interior).sum())}
    if interior.sum() < THRESHOLDS['minimum_interior_pixels']:
        reasons.append('insufficient painted-island interior; background or outline is not content')
        return report

    base_strength, expected, expected_components = _structural_features(luminance, interior, 'base')
    companion_strength, actual, actual_components = _structural_features(values, interior, kind)
    if kind == 'height':
        # Report the encoding bias, but do not mistake a broad raised plane for
        # thousands of structural features or rewrite its actual height values.
        report['height_plane_median'] = float(np.median(values[interior]))
        report['height_plane_offset_from_flush'] = report['height_plane_median'] - 128 / 255
    else:
        border = np.concatenate((values[0], values[-1], values[:, 0], values[:, -1]))
        background = float(np.median(border))
        companion_islands = _islands(abs(values - background) > THRESHOLDS['roughness_background_contrast'])
        union = int((islands | companion_islands).sum())
        report['silhouette_iou'] = float((islands & companion_islands).sum() / union) if union else 0.0
        if report['silhouette_iou'] < THRESHOLDS['minimum_silhouette_iou']:
            reasons.append('roughness island silhouette differs or cannot be verified')

    for group in ('seams', 'fasteners'):
        score = _feature_score(expected[group], actual[group], expected_components[group], actual_components[group])
        _position_score(score, expected[group], actual[group], expected_components[group], actual_components[group], group)
        report['groups'][group] = score
        singular = 'seam' if group == 'seams' else 'fastener'
        for source in ('base', 'companion'):
            for unit in ('pixels', 'components'):
                if score['counts'][source + '_' + unit] < THRESHOLDS['minimum_' + singular + '_' + unit]:
                    reasons.append(f'insufficient {source} {group} {unit}')
            if group == 'seams' and score['counts'][source + '_positions'] < THRESHOLDS['minimum_seam_pixels']:
                reasons.append(f'insufficient {source} seam centreline positions')
        if score['position_precision'] < THRESHOLDS['minimum_precision']:
            reasons.append(group + ' positional precision below minimum')
        if score['position_recall'] < THRESHOLDS['minimum_recall']:
            reasons.append(group + ' positional recall below minimum')
        if any(item['position_recall'] < THRESHOLDS['minimum_recall'] for item in score['base_features']):
            reasons.append(group + ' contains a missing or misplaced base feature')
        if any(item['position_precision'] < THRESHOLDS['minimum_precision'] for item in score['companion_features']):
            reasons.append(group + ' contains a hallucinated or misplaced companion feature')

    counts = report['counts']
    for key in ('base_pixels', 'companion_pixels', 'matched_base_pixels', 'matched_companion_pixels',
                'base_components', 'companion_components', 'base_positions', 'companion_positions',
                'matched_base_positions', 'matched_companion_positions'):
        counts[key] = sum(group['counts'][key] for group in report['groups'].values())
    report['precision'] = counts['matched_companion_pixels'] / counts['companion_pixels'] if counts['companion_pixels'] else 0.0
    report['recall'] = counts['matched_base_pixels'] / counts['base_pixels'] if counts['base_pixels'] else 0.0
    report['position_precision'] = counts['matched_companion_positions'] / counts['companion_positions'] if counts['companion_positions'] else 0.0
    report['position_recall'] = counts['matched_base_positions'] / counts['base_positions'] if counts['base_positions'] else 0.0
    # Cross-correlate only structural evidence. Broad paint and canvas edges
    # must never dominate an otherwise featureless map's registration score.
    reference = np.where(expected['seams'] | expected['fasteners'], base_strength, 0)
    moving = np.where(actual['seams'] | actual['fasteners'], companion_strength, 0)
    offset, correlation, margin = _offset(reference, moving)
    report['offset_xy'] = offset
    report['confidence'] = {'correlation': correlation, 'peak_margin': margin,
                            'verifiable': bool(correlation >= THRESHOLDS['minimum_correlation']
                                               and margin >= THRESHOLDS['minimum_peak_margin'] and offset is not None)}
    if offset is not None:
        report['offset_magnitude'] = float(np.hypot(*offset))
        if report['offset_magnitude'] >= THRESHOLDS['offset_magnitude_exclusive_px']:
            reasons.append('global offset must be less than one native texel')
        elif report['offset_magnitude'] + THRESHOLDS['offset_guard_band_px'] >= THRESHOLDS['offset_magnitude_exclusive_px']:
            reasons.append('global offset is too close to one native texel to verify')
    if not report['confidence']['verifiable']:
        reasons.append('structural cross-correlation is insufficient or ambiguous')
    report['accepted'] = not reasons
    return report
