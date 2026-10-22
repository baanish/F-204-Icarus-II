"""Decode and hash proving renders, with compact sheets for visual inspection."""
import hashlib
import json

from PIL import Image, ImageDraw, ImageFont

from rasterize import ROOT, OUT


def sheet(paths, target, columns=2):
    width, height, label = 800, 500, 34
    font = ImageFont.truetype(str(ROOT / 'art/textures/fonts/BarlowCondensed-SemiBold.ttf'), 24)
    canvas = Image.new('RGB', (columns * width, ((len(paths) + columns - 1) // columns) * (height + label)), '#1a2026')
    draw = ImageDraw.Draw(canvas)
    for i, path in enumerate(paths):
        with Image.open(OUT / path) as source:
            if source.size != (1600, 1000):
                raise ValueError('Unexpected render size: ' + path)
            x, y = (i % columns) * width, (i // columns) * (height + label)
            canvas.paste(source.convert('RGB').resize((width, height), Image.Resampling.LANCZOS), (x, y + label))
            draw.text((x + 12, y + 3), path.removesuffix('.png').replace('_', ' '), font=font, fill='white')
    canvas.save(OUT / target)


def review():
    manifest = json.loads((OUT / 'render_manifest.json').read_text())
    hashes = {}
    for name in manifest['renders']:
        path = OUT / name
        with Image.open(path) as source:
            source.verify()
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for i in range(1, 5):
        sheet([p for p in manifest['renders'] if p.startswith('livery_%d_' % i) and '_close_' not in p], 'livery_%d_sheet.png' % i)
    sheet([p for p in manifest['renders'] if p.startswith('clay_')], 'clay_sheet.png')
    sheet([p for p in manifest['renders'] if p.startswith('ao_')], 'ao_states_sheet.png')
    sheet([p for p in manifest['renders'] if p.startswith('damage_')], 'damage_sheet.png')
    sheet(['livery_%d_empty_front_quarter.png' % i for i in range(1, 5)], 'four_liveries.png')
    (OUT / 'render_hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print('RENDER DECODE PASS', len(hashes))


if __name__ == '__main__':
    review()
