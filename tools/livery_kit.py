"""Assemble the Icarus livery kit: the paint reference pack players and painters use to make their own livery.

  python tools/livery_kit.py --model DIR [--bake DIR] [--version X.Y.Z] [--out ZIP]
  python tools/livery_kit.py --check ZIP [--version X.Y.Z]

tools/Build-LiveryKit.ps1 runs this after the Blender step (tools/livery_kit_model.py writes --model). Nothing here is
tracked as an image: every file comes from the skin pipeline's outputs and is checked against them first.

- maps/: the shipped shared maps, byte for byte (normal, metallic and smoothness, AO).
- examples/: the seven shipped liveries with their faction roundels, painted by art/textures/faction_marks.py exactly as
  the mod ships them. Without the local asset export it stops with faction_marks' own message.
- template/: the UV layout (PNG and SVG), a part map for selecting parts with its names layer and CSV, the panel line and rivet overlay, and per livery the
  two layers compose made it from (the scheme without markings, and the markings), so base, markings and panel lines
  stack back into the shipped map. The stack is held to the shipped maps before anything is written.
- model/: the exterior skin as .blend and .fbx with the atlas UVs, its material reading ../maps and ../examples.
- install/: meta.json for an Icarus livery, and IcarusLiveryBuilder.cs (docs/livery-kit/) for the game developer's livery
  project, which builds the livery bundle with that meta.json.
- README.md (docs/livery-kit/README.md) and LICENSE.txt (docs/livery-kit/LICENSE.txt, then LICENSE).
"""
import argparse
import colorsys
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'art/textures'))
sys.path.insert(0, str(ROOT / 'art/blender'))
import atlas_guard  # noqa: E402
import faction_marks  # noqa: E402
from compose_skin import FASTENER_SHADE, SEAM_SHADE, exported_atlas  # noqa: E402
from liveries import specifications  # noqa: E402
from rasterize import EXPORT, GUTTER_PX, OUT as BAKE, SIZE  # noqa: E402

JSON_KEY = 'baanish_icarus'
DOCS = ROOT / 'docs/livery-kit'
SHARED_MAPS = ('Icarus_skin_n.png', 'Icarus_skin_m.png', 'Icarus_skin_ao.png')
FONT = ROOT / 'art/textures/fonts/BarlowCondensed-SemiBold.ttf'
# The template's layers must stack back into the shipped map: all but this share of the skin's unmarked texels within
# 2 levels. Measured 0.4: 5e-6 off by more than 2 (decal antialiasing just outside the binary decal mask).
STACK_TOLERANCE = 2
STACK_OUTLIERS = 1e-4
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def plugin_version():
    text = (ROOT / 'src/Icarus/IcarusPlugin.cs').read_text(encoding='utf-8')
    return re.search(r'const string Version = "([^"]+)"', text).group(1)


def kit_name(version):
    return f'icarus_livery_kit_{version}'


def slug(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def expected_files(specs):
    """Every file the kit holds, relative to its top folder: the contract tests/test_livery_kit.py pins."""
    files = ['README.md', 'LICENSE.txt', 'install/meta.json', 'install/IcarusLiveryBuilder.cs']
    files += ['maps/' + name for name in SHARED_MAPS]
    for spec in specs:
        stem = 'Icarus_livery_' + str(spec['id'])
        files.append(f'examples/{stem}.png')
        if spec['pattern'] == 'bands':
            files.append(f'examples/{stem}_m.png')
        files += [f'template/layers/{stem}_base.png', f'template/layers/{stem}_markings.png']
    files += ['template/Icarus_uv_layout.png', 'template/Icarus_uv_layout.svg', 'template/Icarus_part_map.png',
              'template/Icarus_part_labels.png', 'template/Icarus_parts.csv', 'template/Icarus_panel_lines.png']
    files += ['model/icarus_paint_model.blend', 'model/icarus_paint_model.fbx']
    return sorted(files)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rgb(path):
    return np.asarray(Image.open(path).convert('RGB'), np.float64)


def require(condition, why):
    if not condition:
        raise SystemExit('LIVERY KIT FAIL: ' + why)


# --- inputs held to the shipped maps -------------------------------------------------------------------------------

def check_inputs(bake, model):
    """The bake and the model describe the skin UVs the export shipped, and the bake made the shipped maps."""
    for name in ('atlas_triangles.json', 'atlas_geometry.npz', 'surface_fields.npz'):
        require((bake / name).is_file(), f'{bake / name} is missing; run tools/Rebuild-Skin.ps1, '
                                         'or pass -Bake with a folder from the run that made the shipped maps')
    exported = exported_atlas()
    baked = json.loads((bake / 'atlas_triangles.json').read_text())
    try:
        atlas_guard.require_same(exported, baked.get('atlas'), 'livery kit bake')
        uv = json.loads((model / 'skin_uv.json').read_text())
        digests = {name: atlas_guard.uv_digest((c for face in faces for c in face), uv['atlas_size'])
                   for name, faces in uv['parts'].items()}
        atlas_guard.require_same(exported, {'size': uv['atlas_size'], 'skin_uv_sha256': digests}, 'livery kit model')
    except ValueError as error:
        raise SystemExit(f'LIVERY KIT FAIL: {error}')
    return uv


def shade_fields(bake):
    """Seam and fastener strength per texel, as compose shaded the albedo (compose_skin.py SEAM_SHADE)."""
    with np.load(bake / 'surface_fields.npz') as fields:
        seam = fields['groove'].astype(np.float64)
        relief = fields['relief'].astype(np.float64)
        cavity = fields['cavity'].astype(np.float64)
    # relief is max(seam, fastener) and cavity 1 - .4 seam - .22 fastener (clipped at .55): together they give the
    # fastener field compose used, exactly except on the few texels where cavity clipped.
    above = relief > seam + 1e-6
    fastener = np.where(above, relief, np.clip((1 - .4 * seam - cavity) / .22, 0, seam))
    return seam, fastener


def shade(seam, fastener, finish):
    return 1 - SEAM_SHADE[finish] * seam - FASTENER_SHADE[finish] * fastener


# --- images ----------------------------------------------------------------------------------------------------------

def save_png(image, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=False, compress_level=9)


def layers(spec, bake, painted, seam, fastener, used):
    """The scheme without markings (compose's unmarked map) and the markings over it, both before panel shading."""
    stem = 'Icarus_livery_' + str(spec['id'])
    finish = 'metal' if spec['pattern'] == 'bands' else 'paint'
    s = shade(seam, fastener, finish)
    base = rgb(bake / f'unmarked_{spec["id"]}.png')
    logo_free = rgb(EXPORT / f'{stem}.png')
    marked = rgb(painted / f'{stem}.png')
    stacked = np.clip(base * s[..., None], 0, 255) + .5
    mask = np.asarray(Image.open(bake / f'decal_mask_{spec["id"]}.png')) > 0
    off = np.abs(np.floor(stacked) - logo_free).max(-1)[used & ~mask]
    outliers = float((off > STACK_TOLERANCE).mean())
    require(outliers <= STACK_OUTLIERS, f'{stem}: the bake\'s unmarked map and panel shading miss the shipped map on '
                                        f'{outliers:.2%} of texels; the bake is not the one that made the shipped maps')
    # Markings: compose's decals plus the roundels faction_marks painted, unshaded so the panel lines go on top.
    markings = mask | (marked != logo_free).any(-1)
    colour = np.zeros((SIZE, SIZE, 4), np.uint8)
    colour[..., :3][markings] = np.uint8(np.clip(marked[markings] / s[markings][:, None], 0, 255) + .5)
    colour[..., 3][markings] = 255
    return Image.fromarray(np.uint8(base)), Image.fromarray(colour), outliers


def panel_lines(seam, fastener, used):
    """Black at the alpha that darkens paint as compose did: over any colour c it gives c * shade. One layer, at the
    painted finish's strength, since a player's livery always gets the painted finish in game; the two Bare Metal
    examples were composed with the lighter metal strength, so this layer over their base darkens their joints a little
    more than their shipped maps (the guide says so)."""
    alpha = (SEAM_SHADE['paint'] * seam + FASTENER_SHADE['paint'] * fastener) * used
    out = np.zeros((*alpha.shape, 4), np.uint8)
    out[..., 3] = np.uint8(np.clip(alpha, 0, 1) * 255 + .5)
    return Image.fromarray(out)


def readable(name):
    """A part's plain name for the map and CSV: skin_mid_L is 'mid fuselage left'."""
    for prefix, plain in (('skin_forward', 'forward fuselage'), ('skin_mid', 'mid fuselage'), ('skin_aft', 'aft fuselage'),
                          ('wing_skin', 'wing'), ('fin_skin', 'fin')):
        if name.startswith(prefix):
            name = plain.replace(' ', '~') + name[len(prefix):]
    words = {'L': 'left', 'R': 'right', 'N': 'nose', 'N2': 'nose aft', 'lef': 'leading-edge flap', 'visible': '',
             'out': 'outer', 'main': 'main', 'duct': 'duct'}
    return ' '.join(p for p in (words.get(w, w) for w in name.split('_')) if p).replace('~', ' ')


def colour_of(index):
    hue = (index * .618034) % 1
    r, g, b = colorsys.hsv_to_rgb(hue, .55 + .3 * (index % 3) / 2, .95 - .25 * (index % 2))
    return int(r * 255 + .5), int(g * 255 + .5), int(b * 255 + .5)


def drawn_parts(uv):
    """Parts that own islands: a mirror pair's right side reuses its left's, so only the left is drawn."""
    shared = {right: left for left, right in uv['mirror_pairs']}
    return [name for name in sorted(uv['parts']) if name not in shared], {v: k for k, v in shared.items()}


def polygons_px(faces, scale):
    return [[(u * scale, (1 - v) * scale) for u, v in face] for face in faces]


def uv_layout(uv):
    """Every skin polygon edge, thin, and each island's outline, heavier, on transparency; drawn at 2x and filtered."""
    names, _ = drawn_parts(uv)
    scale = 2
    edges = Image.new('L', (SIZE * scale, SIZE * scale), 0)
    outlines = Image.new('L', (SIZE * scale, SIZE * scale), 0)
    draw_edges, draw_outlines = ImageDraw.Draw(edges), ImageDraw.Draw(outlines)
    for name in names:
        faces = uv['parts'][name]
        count = {}
        for face in faces:
            for a, b in zip(face, face[1:] + face[:1]):
                key = tuple(sorted((tuple(np.round(a, 7)), tuple(np.round(b, 7)))))
                count[key] = count.get(key, 0) + 1
        for (a, b), n in count.items():
            line = [(a[0] * SIZE * scale, (1 - a[1]) * SIZE * scale), (b[0] * SIZE * scale, (1 - b[1]) * SIZE * scale)]
            (draw_outlines if n == 1 else draw_edges).line(line, fill=255, width=3 if n == 1 else 1)
    edges = np.asarray(edges.resize((SIZE, SIZE), Image.Resampling.BOX), np.float64) / 255
    outlines = np.asarray(outlines.resize((SIZE, SIZE), Image.Resampling.BOX), np.float64) / 255
    out = np.zeros((SIZE, SIZE, 4), np.uint8)
    out[..., :3] = np.where(outlines[..., None] > 0, 0, 70)
    out[..., 3] = np.uint8(np.clip(np.maximum(outlines, .6 * edges), 0, 1) * 255 + .5)
    return Image.fromarray(out)


def uv_svg(uv):
    names, twin = drawn_parts(uv)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">',
             f'<title>F-204 Icarus II skin UV layout, {SIZE} px atlas</title>',
             '<g fill="none" stroke="#202020" stroke-width="0.6" stroke-linejoin="round">']
    for name in names:
        label = name + (' and ' + twin[name] if name in twin else '')
        lines.append(f'<g id="{name}"><desc>{label}</desc>')
        for face in polygons_px(uv['parts'][name], SIZE):
            d = 'M' + 'L'.join(f'{x:.2f} {y:.2f}' for x, y in face) + 'Z'
            lines.append(f'<path d="{d}"/>')
        lines.append('</g>')
    lines += ['</g>', '</svg>', '']
    return '\n'.join(lines)


def part_map(uv, used):
    """Flat colour per part, for selecting a part's islands in a paint program; the part names on a separate transparent
    layer, so text never breaks a selection; and the CSV naming each colour. Colours run GUTTER_PX past each island, as
    the shipped maps' paint does, so a filled selection leaves no seam at island edges."""
    names, twin = drawn_parts(uv)
    index = Image.new('L', (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(index)
    for i, name in enumerate(names, 1):
        for face in polygons_px(uv['parts'][name], SIZE):
            draw.polygon(face, fill=i)
    index = np.asarray(index)
    require(int(((index > 0) & ~used).sum()) <= .01 * used.sum(), 'the UV polygons do not cover the bake\'s islands')
    distance, (iy, ix) = ndimage.distance_transform_edt(index == 0, return_indices=True)
    grown = np.where(distance <= GUTTER_PX, index[iy, ix], 0)
    palette = np.zeros((256, 3), np.uint8)
    for i in range(1, len(names) + 1):
        palette[i] = colour_of(i)
    colours = Image.fromarray(palette[grown])
    labels_image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(labels_image)
    rows = []
    for i, (name, box) in enumerate(zip(names, ndimage.find_objects(index, max_label=len(names))), 1):
        rows.append({'part': name, 'shares_islands_with': twin.get(name, ''), 'description': readable(name)
                     + (' (both sides share these islands)' if name in twin else ''),
                     'colour': '#%02x%02x%02x' % colour_of(i)})
        if box is None:
            continue
        labels, count = ndimage.label(index[box] == i)
        sizes = ndimage.sum(np.ones_like(labels), labels, range(1, count + 1))
        for k, area in enumerate(sizes, 1):
            if area < 1500:
                continue
            ys, xs = np.nonzero(labels == k)
            height, width = np.ptp(ys) + 1, np.ptp(xs) + 1
            text = readable(name)
            size = int(np.clip(height / 3, 12, 64))
            font = ImageFont.truetype(str(FONT), size)
            fit = .9 * width / max(draw.textlength(text, font=font), 1)
            if fit < 1:
                size = int(size * fit)
                if size < 12:
                    continue
                font = ImageFont.truetype(str(FONT), size)
            cx, cy = xs.mean() + box[1].start, ys.mean() + box[0].start
            draw.text((cx, cy), text, fill=(0, 0, 0, 255), font=font, anchor='mm', stroke_width=2,
                      stroke_fill=(255, 255, 255, 255))
    return colours, labels_image, rows


def logo_scores(path, record, faction):
    decal = faction_marks.faction_roundel(faction)
    return faction_marks.roundel_correlations(faction_marks.read_rgb(path, record['atlas_size']), record, faction, decal)


# --- the kit -------------------------------------------------------------------------------------------------------

def meta_example():
    return json.dumps({'DisplayName': 'My Icarus livery', 'Faction': '', 'Aircraft': '', 'AircraftKey': JSON_KEY},
                      indent=2) + '\n'


def stage_kit(stage, bake, model, uv):
    specs = specifications()
    record = json.loads(faction_marks.RECORD.read_text())
    examples = stage / 'examples'
    # faction_marks.paint stops with its own message naming the setting when the asset export is missing.
    faction_marks.paint(record, EXPORT, examples)
    for name in SHARED_MAPS:
        (stage / 'maps').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EXPORT / name, stage / 'maps' / name)
    with np.load(bake / 'atlas_geometry.npz') as atlas:
        used = atlas['part'] > 0
    seam, fastener = shade_fields(bake)
    report = {}
    for spec in specs:
        stem = 'Icarus_livery_' + str(spec['id'])
        scores = logo_scores(examples / f'{stem}.png', record, spec['faction'])
        require(scores and min(scores) >= faction_marks.MARKED_MIN, f'examples/{stem}.png lacks its roundels')
        base, markings, outliers = layers(spec, bake, examples, seam, fastener, used)
        save_png(base, stage / f'template/layers/{stem}_base.png')
        save_png(markings, stage / f'template/layers/{stem}_markings.png')
        clean = logo_scores(stage / f'template/layers/{stem}_base.png', record, spec['faction'])
        require(max(clean, default=0) <= faction_marks.CLEAN_MAX, f'{stem}_base.png shows a roundel')
        report[stem] = {'name': spec['name'], 'faction': spec['faction'], 'stack_outliers': outliers}
        print('LIVERY KIT LAYERS', stem, spec['name'], flush=True)
    save_png(panel_lines(seam, fastener, used), stage / 'template/Icarus_panel_lines.png')
    save_png(uv_layout(uv), stage / 'template/Icarus_uv_layout.png')
    (stage / 'template/Icarus_uv_layout.svg').write_text(uv_svg(uv), encoding='utf-8', newline='\n')
    colours, names, rows = part_map(uv, used)
    save_png(colours, stage / 'template/Icarus_part_map.png')
    save_png(names, stage / 'template/Icarus_part_labels.png')
    with (stage / 'template/Icarus_parts.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['part', 'colour', 'description', 'shares_islands_with'])
        writer.writeheader()
        writer.writerows(rows)
    (stage / 'model').mkdir(parents=True, exist_ok=True)
    for name in ('icarus_paint_model.blend', 'icarus_paint_model.fbx'):
        shutil.copyfile(model / name, stage / 'model' / name)
    (stage / 'install').mkdir(parents=True, exist_ok=True)
    (stage / 'install/meta.json').write_text(meta_example(), encoding='utf-8', newline='\n')
    shutil.copyfile(DOCS / 'IcarusLiveryBuilder.cs', stage / 'install/IcarusLiveryBuilder.cs')
    shutil.copyfile(DOCS / 'README.md', stage / 'README.md')
    licence = (DOCS / 'LICENSE.txt').read_text(encoding='utf-8') + (ROOT / 'LICENSE').read_text(encoding='utf-8')
    (stage / 'LICENSE.txt').write_text(licence, encoding='utf-8', newline='\n')
    return report


def write_zip(stage, path, top):
    """Sorted entries and a fixed timestamp, as the release archives: identical inputs give identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(p for p in stage.rglob('*') if p.is_file()):
            info = zipfile.ZipInfo(top + '/' + file.relative_to(stage).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, file.read_bytes(), compresslevel=9)


# An absolute Windows path stored as text: a drive, a separator and a run of path characters.
DRIVE_PATH = re.compile(rb'[A-Za-z]:[\\/][A-Za-z0-9 _.\\/-]{8,}')


def local_paths(stage, model):
    """Files that name a folder of the machine that built them: the repository, the model step's output or the home
    folder anywhere, and in the model files any absolute drive path."""
    folders = {ROOT, model.resolve(), Path.home()}
    needles = {form.encode() for folder in folders for form in (str(folder), folder.as_posix())}
    found = []
    for path in sorted(p for p in stage.rglob('*') if p.is_file()):
        data = path.read_bytes()
        if any(n in data for n in needles) or (path.parent.name == 'model' and DRIVE_PATH.search(data)):
            found.append(path.relative_to(stage).as_posix())
    return found


def check_zip(path, top, specs):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        expected = [f'{top}/{name}' for name in expected_files(specs)]
        require(sorted(entry.filename for entry in entries) == expected,
                f'{path.name} has missing, extra, or duplicate kit entries')
        require(all(entry.date_time == FIXED_TIME for entry in entries), f'{path.name} needs fixed timestamps')
        bad_entry = archive.testzip()
        require(bad_entry is None, f'{bad_entry} failed the ZIP integrity check')
        for entry in entries:
            require(entry.file_size > 0, f'{entry.filename} is empty')
        for name in expected:
            if name.endswith('.png'):
                try:
                    with archive.open(name) as stream, Image.open(stream, formats=['PNG']) as image:
                        image.verify()
                    # verify() checks the chunks only; a second open decodes the pixels
                    with archive.open(name) as stream, Image.open(stream, formats=['PNG']) as image:
                        image.load()
                except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
                    require(False, f'{name} is not a valid PNG: {error}')
        # Against the export manifest's pinned digests, not the checkout's files, which are Git LFS pointers in a
        # checkout without LFS content.
        pinned = json.loads((ROOT / 'art/export-manifest.json').read_text(encoding='utf-8'))
        for name in SHARED_MAPS:
            entry = f'{top}/maps/{name}'
            require(hashlib.sha256(archive.read(entry)).hexdigest() == pinned.get(f'art/export/textures/{name}'),
                    f'{entry} differs from the shipped map')
        builder = f'{top}/install/IcarusLiveryBuilder.cs'
        # line endings aside: a checkout may hold the script with CRLF
        require(archive.read(builder).replace(b'\r\n', b'\n')
                == (DOCS / 'IcarusLiveryBuilder.cs').read_bytes().replace(b'\r\n', b'\n'),
                f'{builder} differs from the shipped builder')
        meta = f'{top}/install/meta.json'
        try:
            metadata = json.loads(archive.read(meta))
        except ValueError as error:
            require(False, f'{meta} is not valid JSON: {error}')
        require(isinstance(metadata, dict) and metadata.get('AircraftKey') == JSON_KEY,
                f'{meta} must set AircraftKey to {JSON_KEY}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--model', type=Path, help='tools/livery_kit_model.py output folder')
    mode.add_argument('--check', type=Path, help='verify an existing kit archive')
    parser.add_argument('--bake', type=Path, default=BAKE, help='skin bake folder (default the repository\'s)')
    parser.add_argument('--version', default=None, help='default: the plugin version')
    parser.add_argument('--out', type=Path, default=None, help='default: build/icarus_livery_kit_<version>.zip')
    args = parser.parse_args()
    version = args.version or plugin_version()
    top = kit_name(version)
    if args.check:
        check_zip(args.check, top, specifications())
        return
    out = args.out or ROOT / 'build' / (top + '.zip')
    uv = check_inputs(args.bake, args.model)
    stage = ROOT / '.cache/livery-kit/stage' / top
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    report = stage_kit(stage, args.bake, args.model, uv)
    leaks = local_paths(stage, args.model)
    require(not leaks, f'{", ".join(leaks)} name a local folder')
    write_zip(stage, out, top)
    check_zip(out, top, specifications())
    (ROOT / '.cache/livery-kit/report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'LIVERY KIT PASS: {out.relative_to(ROOT).as_posix()} {out.stat().st_size} bytes sha256 {sha256(out)}')


if __name__ == '__main__':
    main()
