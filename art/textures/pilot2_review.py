"""Make matched pilot comparison sheets and pin the evidence used in the handback."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pilot2_parts import OUT, SOURCES, BAKE, GROUPS, ROOT, font
from rasterize import sample


def comparisons():
    for material in ('navy', 'clay'):
        rows = []
        for view in ('radome', 'forward', 'wing', 'wing_upper', 'fin'):
            canvas = Image.new('RGB', (3200, 1064), '#161c23')
            draw = ImageDraw.Draw(canvas)
            for i, (version, caption) in enumerate((('round1', 'ROUND 1'), ('pilot2', 'PER-PART PILOT'))):
                path = OUT / (version + '_' + material + '_' + view + '.png')
                image = Image.open(path).convert('RGB')
                if image.size != (1600, 1000):
                    raise ValueError('Wrong render size: ' + str(path))
                canvas.paste(image, (i * 1600, 64))
                draw.text((i * 1600 + 28, 12), caption + ' | ' + view.upper() + ' | ' + material.upper(), fill='white', font=font(31))
            canvas.save(OUT / ('compare_' + material + '_' + view + '.png'))
            rows.append(canvas.resize((1600, 532), Image.Resampling.LANCZOS))
        sheet = Image.new('RGB', (1600, 532 * len(rows)))
        for i, row in enumerate(rows):
            sheet.paste(row, (0, 532 * i))
        sheet.save(OUT / ('comparison_' + material + '_all.png'))


def measurements():
    geometry = np.load(BAKE / 'geometry_maps.npz')
    part = geometry['part']
    pilot_mask = np.logical_or.reduce([np.asarray(Image.open(OUT / (name + '.mask.png'))) > 0 for name in GROUPS])
    names = json.loads((BAKE / 'atlas_triangles.json').read_text())['parts']
    pilot_mask |= (part == names.index('fin_skin') + 1) & (geometry['position'][..., 0] < 0)
    seams = json.loads((BAKE / 'seam_samples.json').read_text())
    coords = np.asarray([s['uv'] for s in seams])
    def lookup(image, uv):
        return sample(image, (uv[:, 0] * 2048 - .5) / 2047, ((1 - uv[:, 1]) * 2048 - .5) / 2047)
    touches_pilot = (lookup(pilot_mask[..., None].astype(float), coords[:, 0])[:, 0] > .1) | (lookup(pilot_mask[..., None].astype(float), coords[:, 1])[:, 0] > .1)
    result = {'geometry_head': 'e9a6167906f12f6e0f554305186a7f6f57b15727', 'seams': {}, 'maps': {},
              'native_sources': json.loads((OUT / 'stitch.json').read_text()),
              'note': 'Offline uncompressed probe only. Pilot approval remains with the owner.'}
    for version in ('round1', 'pilot2'):
        folder = OUT / version / 'art/export/textures'
        result['maps'][version] = {}
        for path in sorted(folder.glob('*.png')):
            with Image.open(path) as img:
                if img.size != (2048, 2048):
                    raise ValueError('Wrong map size: ' + str(path))
                result['maps'][version][path.name] = {'size': list(img.size), 'mode': img.mode,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                img.verify()
        navy = np.asarray(Image.open(folder / 'Icarus_livery_1.png'), np.float32)
        delta = abs(lookup(navy, coords[:, 0]) - lookup(navy, coords[:, 1])).mean(axis=1)
        result['seams'][version] = {}
        for name, selected in (('all', np.ones(len(delta), bool)), ('touching_pilot', touches_pilot)):
            values = delta[selected]
            result['seams'][version][name] = {'pairs': len(values), 'median_rgb_levels': float(np.median(values)),
                'p95_rgb_levels': float(np.percentile(values, 95)), 'max_rgb_levels': float(values.max())}
        # The encoded normal must still agree with the colour-derived shared height field.
        fields = np.load(OUT / (version + '_surface_fields.npz'))
        height = fields['height']
        gy, gx = np.gradient(height)
        expected = np.stack((-gx * 1.8, gy * 1.8, np.ones_like(height)), axis=-1)
        expected /= np.linalg.norm(expected, axis=-1, keepdims=True)
        decoded = np.asarray(Image.open(folder / 'Icarus_skin_n.png'), np.float32) / 255 * 2 - 1
        decoded /= np.maximum(np.linalg.norm(decoded, axis=-1, keepdims=True), 1e-8)
        angle = np.degrees(np.arccos(np.clip((decoded * expected).sum(axis=-1)[part > 0], -1, 1)))
        if angle.max() > .5:
            raise ValueError('Shared height-field normal check failed')
        result['maps'][version]['normal_max_error_deg'] = float(angle.max())
    baseline = np.asarray(Image.open(OUT / 'round1_assembled.png'))
    revised = np.asarray(Image.open(OUT / 'pilot2_assembled.png'))
    changed = np.any(baseline != revised, axis=-1)
    if (changed & ~pilot_mask).any():
        raise ValueError('Source detail changed outside pilot surfaces')
    result['source_change'] = {'changed_texels': int(changed.sum()), 'outside_pilot': int((changed & ~pilot_mask).sum()),
                               'pilot_skin_fraction': float(pilot_mask.sum() / (part > 0).sum())}
    from pilot2_parts import service_relief
    h = np.full(part.shape, -.34, np.float32)
    c = np.full(part.shape, .94, np.float32)
    h, c, _ = service_relief(h, c, part, geometry['position'][..., :3], names, OUT / 'parts.json')
    if not np.allclose(h[pilot_mask], -.102) or not np.allclose(c[pilot_mask], .982):
        raise ValueError('Flush-skin relief policy characterization failed')
    if not np.all(h[~pilot_mask] == np.float32(-.34)) or not np.all(c[~pilot_mask] == np.float32(.94)):
        raise ValueError('Flush-skin policy changed non-pilot surfaces')
    result['relief_policy_characterization'] = {'input_seam_px': -.34, 'output_seam_px': -.102,
                                               'input_cavity': .94, 'output_cavity': .982, 'outside_pilot_unchanged': True}
    generation_path = SOURCES / 'generation.json'
    generation = json.loads(generation_path.read_text())
    shared = (ROOT / 'art/textures/round2_style.txt').read_text().strip()
    for name, original_name in generation['outputs'].items():
        image_path = SOURCES / (name + '.png')
        original = Path(generation['original_directory']) / original_name
        if hashlib.sha256(image_path.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
            raise ValueError('Native generation was modified: ' + name)
        if shared not in (SOURCES / (name + '.prompt.txt')).read_text():
            raise ValueError('Shared style block differs: ' + name)
        if not (SOURCES / (name + '.context.md')).read_text().strip():
            raise ValueError('Missing context pack: ' + name)
    generation['registered_sources'] = result['native_sources']
    generation_path.write_text(json.dumps(generation, indent=2))
    inputs = list(SOURCES.glob('*')) + [ROOT / 'art/textures/round2_style.txt', ROOT / 'art/textures/pilot2_parts.py',
        ROOT / 'art/textures/pilot2_review.py', ROOT / 'art/blender/pilot2_skin.py', ROOT / 'art/textures/compose_skin.py']
    inputs += [BAKE / n for n in ('geometry_maps.npz', 'ao_maps.npz', 'geometry.blend', 'skin.blend')]
    inputs += [OUT / n for n in ('parts.json', 'structure.json', 'stitch.json', 'render_settings.json')]
    inputs += list(OUT.glob('*.png'))
    result['evidence_sha256'] = {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs if p.is_file()}
    (OUT / 'measurements.json').write_text(json.dumps(result, indent=2))
    print('PILOT REVIEW PASS', json.dumps({'seams': result['seams'], 'source_change': result['source_change']}, indent=2))


if __name__ == '__main__':
    comparisons()
    measurements()
