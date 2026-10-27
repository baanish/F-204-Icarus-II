"""Fit our generated material to exact part templates before companion generation."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter

from full_skin_compose import _chart_mask, _match_charts, _read_image, source_charts
from record_paths import portable_record, portable_text, resolve_record
from rasterize import ROOT


OUT = ROOT / '.cache/review/wave2/p9b-round2/full'


def stitch_source(name, material_only=False):
    manifest_path = OUT / 'parts.json'
    manifest = resolve_record(json.loads(manifest_path.read_text()))
    group = manifest['groups'][name]
    source = Path(group['references']['style_anchor']) if material_only else ROOT / 'art/textures/generated/full' / (name + '.png')
    image = _read_image(source, True)
    charts = sorted(group['charts'], key=lambda c: (c['guide_box'][1], c['guide_box'][0]))
    mask = _read_image(group['mask']) > 0
    size = 1254
    scale = size / manifest['guide_size']
    guide = np.asarray(Image.open(group['references']['guide']).convert('RGB'))
    result = np.full((size, size, 3), (37, 43, 48), np.uint8)
    records = []
    if material_only:
        # Reuse only bounded fine paint grain. Structural lines come from the part guide.
        grain = image.mean(axis=2) - gaussian_filter(image.mean(axis=2), 2)
        grain = np.clip(grain, -.012, .012)
        grain = np.tile(grain, (2, 2))[:size, :size]
        material = np.repeat((.51 + grain)[..., None], 3, axis=2)
        candidates = [None] * len(charts)
    else:
        labels, candidates = source_charts(image, len(charts))
        candidates = _match_charts(name, charts, labels, candidates, mask, OUT, manifest['guide_size'])
    for chart, candidate in zip(charts, candidates):
        gx0, gy0, gx1, gy1 = chart['guide_box']
        x0, y0, x1, y1 = [round(value * scale) for value in chart['guide_box']]
        target_size = (x1 - x0, y1 - y0)
        local_mask = _chart_mask(name, chart, mask, OUT)
        if chart.get('rotate_ccw', False):
            local_mask = np.rot90(local_mask)
        inside = np.asarray(Image.fromarray(local_mask).resize(target_size, Image.Resampling.NEAREST))
        if material_only:
            paint = material[y0:y1, x0:x1].copy()
            structural = np.all(guide[gy0:gy1, gx0:gx1] == (45, 157, 223), axis=2)
            structural = np.asarray(Image.fromarray(structural).resize(target_size, Image.Resampling.NEAREST))
            paint[structural] = .34
            record = {'source': 'style anchor fine grain', 'structure': 'exact blue frame/spar guide pixels'}
        else:
            source_id, box, _ = candidate
            inside_source = labels[box] == source_id
            _, nearest = distance_transform_edt(~inside_source, return_indices=True)
            padded = image[box][nearest[0], nearest[1]]
            paint = np.asarray(Image.fromarray(np.round(padded * 255).astype('uint8')).resize(
                target_size, Image.Resampling.LANCZOS), np.float32) / 255
            record = {'source_box': [box[1].start, box[0].start, box[1].stop, box[0].stop]}
        region = result[y0:y1, x0:x1]
        region[inside] = np.round(paint[inside] * 255).astype('uint8')
        records.append(dict(record, chart=chart['chart_key'], target_box=[x0, y0, x1, y1]))
    target = source.parent / (name + '.stitched.png') if not material_only else ROOT / 'art/textures/generated/full' / (name + '.stitched.png')
    if target.exists():
        if not np.array_equal(np.asarray(Image.open(target).convert('RGB')), result):
            raise ValueError('Existing stitched source differs; preserve it and author a new version: ' + target.as_posix())
    else:
        Image.fromarray(result).save(target)
    report = {'method': 'style anchor grain and structural guide' if material_only else 'per-chart generated paint fit to exact template',
              'source': source.as_posix(), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'output': target.as_posix(), 'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
              'native_size': [size, size], 'charts': records,
              'limitation': 'material reuse after generation service rejection; no independently generated part detail' if material_only else
              'base-only chart fitting before companion generation; raw generated original remains unchanged'}
    target.with_suffix('.context.md').write_text(portable_text(Path(group['context_path']).read_text() + '\n\nSource stitching: ' + json.dumps(portable_record(report), indent=2)), encoding='utf-8')
    (OUT / (name + '.source-stitch.json')).write_text(json.dumps(portable_record(report), indent=2), encoding='utf-8')
    target.with_name(name + '.source-stitch.json').write_text(json.dumps(portable_record(report), indent=2), encoding='utf-8')
    group['source_path'] = target.as_posix()
    group['source_stitch'] = report
    manifest_path.write_text(json.dumps(portable_record(manifest), indent=2), encoding='utf-8')
    print(json.dumps(portable_record(report)))


if __name__ == '__main__':
    from texture_sources import require_texture_sources
    require_texture_sources()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--material-only', action='store_true')
    args = parser.parse_args()
    stitch_source(args.name, args.material_only)
