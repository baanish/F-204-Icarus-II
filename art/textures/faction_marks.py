"""Paint the game's faction roundels onto the logo-free livery maps, for the textures Unity builds the mod from.

The repository carries no game art. compose_skin.py writes every livery without its roundels to art/export/textures and
records, in art/textures/faction_marks.json, where each roundel goes. This step reads PALA_roundel.png and BDF_roundel.png
from your local asset export (`game_export` in tools/local-paths.json: the folder holding Texture2D), paints them as
compose would have (16 supersamples a texel, the same seam and fastener shading, paint over Bare Metal), and writes:
- unity/Assets/Blueprinter/Mods/icarus/Liveries/Icarus_livery_<id>.png, and _<id>_m.png for each Bare Metal livery
  (gitignored: they hold game art);
- .cache/faction-marks/marks.json, the input and output hashes Unity's import checks before it builds a livery.

  python art/textures/faction_marks.py [--maps DIR] [--out DIR]   paint (Rebuild-Skin.ps1 and Build-Icarus.ps1 run it)
  python art/textures/faction_marks.py verify-marked              the Unity textures are painted and show every roundel
  python art/textures/faction_marks.py check-clean FILE...        no file is game art or shows a roundel (Check-Public.ps1)
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from insignia import SUBSAMPLES, faction_roundel, ink_to_uv, mark_basis
from rasterize import EXPORT, ROOT, sample

sys.path.insert(0, str(ROOT / 'art/blender'))
import atlas_guard  # noqa: E402

RECORD = ROOT / 'art/textures/faction_marks.json'
BLOCKOUT = ROOT / 'art/export/blockout.json'
UNITY = ROOT / 'unity/Assets/Blueprinter/Mods/icarus/Liveries'
HASHES = ROOT / '.cache/faction-marks/marks.json'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def coverage(mark, decal, size):
    """Premultiplied roundel RGBA over the mark's footprint texels, and their flat indices into a size-square atlas."""
    runs = np.array(mark['runs'])
    lengths = runs[:, 2] - runs[:, 1]
    rows = np.repeat(runs[:, 0], lengths)
    cols = np.concatenate([np.arange(c0, c1) for _, c0, c1 in runs])
    coefficients = np.array(mark['coefficients'])
    origin = mark['origin']
    offsets = (np.arange(SUBSAMPLES) + .5) / SUBSAMPLES - .5
    ink = np.zeros((len(rows), 4), np.float32)
    for oy in offsets:
        for ox in offsets:
            basis = mark_basis(cols + ox - origin[0], rows + oy - origin[1], coefficients.shape[1])
            s, t = (basis @ coefficients.T).T
            u, v = ink_to_uv(s, t, decal)
            inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
            ink[inside] += sample(decal, u[inside], v[inside])
    return rows * size + cols, ink / SUBSAMPLES ** 2


def relief(mark, size):
    entries = np.array(mark['relief'], np.float64).reshape(-1, 4)
    return (entries[:, 0] * size + entries[:, 1]).astype(np.int64), entries[:, 2], entries[:, 3]


def stale_footprints(record, blockout=None):
    """Why the record's footprints don't fit the exported meshes' skin atlas (atlas_guard), or None: they are texels of
    the atlas compose saw, and land elsewhere on meshes another UV pack made."""
    atlas = json.loads(Path(blockout or BLOCKOUT).read_text(encoding='utf-8')).get('atlas')
    if atlas is None:
        return 'the export records no skin atlas; rerun tools/export_blockout.py'
    if record.get('skin_uv_sha256') != atlas_guard.whole(atlas['skin_uv_sha256']):
        return (f'the roundel footprints were recorded for other skin UVs than the exported meshes\' (exported on Blender '
                f'{atlas.get("blender")}); rerun the skin bake and compose (tools/Rebuild-Skin.ps1)')
    return None


def paint(record, maps, out):
    stale = stale_footprints(record)
    if stale:
        raise SystemExit('FACTION MARKS FAIL: ' + stale)
    size = record['atlas_size']
    decals = {faction: faction_roundel(faction) for faction in record['roundels']}
    inputs = {'record': sha256(RECORD)}
    inputs.update({faction: sha256(path) for faction, path in roundel_paths(record).items()})
    outputs = {}
    out.mkdir(parents=True, exist_ok=True)
    for livery in record['liveries'].values():
        base = maps / livery['map']
        if sha256(base) != livery['map_sha256']:
            raise SystemExit(f'FACTION MARKS FAIL: {base.name} is not the map compose recorded; rerun compose_skin.py compose')
        colour = np.asarray(Image.open(base).convert('RGB'), np.float64).reshape(-1, 3) / 255
        metallic = None
        if livery['metallic_map']:
            metal_path = maps / livery['metallic_map']
            if sha256(metal_path) != livery['metallic_map_sha256']:
                raise SystemExit(f'FACTION MARKS FAIL: {metal_path.name} is not the map compose recorded; rerun compose_skin.py compose')
            metallic = np.asarray(Image.open(metal_path).convert('RGBA'), np.float64).reshape(-1, 4) / 255
        seam_shade, fastener_shade = (record['shade'][key][livery['finish']] for key in ('seam', 'fastener'))
        for mark in record['marks']:
            if mark['faction'] != livery['faction']:
                continue
            index, ink = coverage(mark, decals[mark['faction']], size)
            shade = np.ones(len(index))
            where, seam, fastener = relief(mark, size)
            lookup = {int(i): k for k, i in enumerate(index)}
            for i, a, b in zip(where, seam, fastener):
                shade[lookup[int(i)]] = 1 - seam_shade * a - fastener_shade * b
            alpha = ink[:, 3:4]
            # The base texel is compose's colour already shaded; the roundel takes the same shade, as in compose.
            colour[index] = colour[index] * (1 - alpha) + ink[:, :3] * shade[:, None]
            if metallic is not None:
                # Paint is dielectric: Bare Metal's map loses its metal under the roundel and takes painted smoothness.
                metallic[index, 0] *= 1 - alpha[:, 0]
                metallic[index, 3] = metallic[index, 3] * (1 - alpha[:, 0]) + record['painted_smoothness'] * alpha[:, 0]
        for name, values, channels in ((livery['map'], colour, 3), (livery['metallic_map'], metallic, 4)):
            if name is None:
                continue
            target = out / name
            pixels = np.uint8(np.clip(values, 0, 1) * 255 + .5).reshape(size, size, channels)
            Image.fromarray(pixels).save(target)
            outputs[name] = sha256(target)
        print('FACTION MARKS', livery['map'], livery['faction'], flush=True)
    return inputs, outputs


def roundel_paths(record):
    paths = ROOT / 'tools/local-paths.json'
    export = json.loads(paths.read_text()).get('game_export') if paths.is_file() else None
    if export is None:
        return {}  # a checkout without the asset export: no roundel to read
    return {faction: ROOT.joinpath(export, 'Texture2D', name + '.png') for faction, name in record['roundels'].items()}


# Correlation of a texture's luminance with the roundel's own at its inked footprint texels. Measured on the 0.4 maps:
# painted roundels 0.985 to 0.998, the logo-free maps -0.27 to 0.09.
MARKED_MIN = .9
CLEAN_MAX = .5
MIN_INK_TEXELS = 50  # footprint fragments with less ink than this say nothing either way
LUMINANCE = np.array((.2126, .7152, .0722))


def roundel_correlations(rgb, record, faction, decal):
    """Per mark of the faction with enough ink: correlation of `rgb` (flat, 0-1) with the roundel at its footprint."""
    found = []
    for mark in record['marks']:
        if mark['faction'] != faction:
            continue
        index, ink = coverage(mark, decal, record['atlas_size'])
        inked = ink[:, 3] > .5
        if inked.sum() < MIN_INK_TEXELS:
            continue
        logo = (ink[inked, :3] / ink[inked, 3:]) @ LUMINANCE
        texture = rgb[index[inked]] @ LUMINANCE
        # A footprint with no variation at all shows no roundel: score it 0, where corrcoef would give NaN.
        found.append(float(np.corrcoef(texture, logo)[0, 1]) if texture.std() > 1e-9 else 0.)
    return found


def read_rgb(path, size):
    image = Image.open(path).convert('RGB')
    if image.size != (size, size):
        return None
    return np.asarray(image, np.float64).reshape(-1, 3) / 255


def verify_marked(record, folder=UNITY, hashes=HASHES):
    """The textures Unity builds from are this record's painted outputs and carry every roundel; returns problems."""
    problems = []
    if not hashes.is_file():
        return [f'no {hashes.name}: run python art/textures/faction_marks.py']
    outputs = json.loads(hashes.read_text())['outputs']
    decals = {faction: faction_roundel(faction) for faction in record['roundels']}
    for livery in record['liveries'].values():
        path = folder / livery['map']
        if not path.is_file() or outputs.get(livery['map']) != sha256(path):
            problems.append(f'{livery["map"]} is not the painted output; run python art/textures/faction_marks.py')
            continue
        scores = roundel_correlations(read_rgb(path, record['atlas_size']), record, livery['faction'], decals[livery['faction']])
        if not scores or min(scores) < MARKED_MIN:
            problems.append(f'{livery["map"]} lacks its {livery["faction"]} roundels (correlation {min(scores, default=0):.2f}, '
                            f'needs {MARKED_MIN})')
    return problems


def check_clean(paths, record, hashes=HASHES):
    """No file is a painted livery or a stock roundel, and no livery-sized map shows a roundel at a footprint.

    Returns problems and a note. Without the asset export the roundels can't be read, so only the painted outputs'
    hashes are checked: a checkout without the export cannot have painted a roundel itself.
    """
    forbidden = {}
    if hashes.is_file():
        forbidden.update({sha: f'the painted {name}' for name, sha in json.loads(hashes.read_text())['outputs'].items()})
    roundels = {faction: path for faction, path in roundel_paths(record).items() if path.is_file()}
    forbidden.update({sha256(path): f'the stock {path.name}' for path in roundels.values()})
    decals = {faction: faction_roundel(faction) for faction in roundels}
    by_map = {livery['map']: livery['faction'] for livery in record['liveries'].values()}
    problems = []
    for path in map(Path, paths):
        digest = sha256(path)
        if digest in forbidden:
            problems.append(f'{path}: is {forbidden[digest]}')
            continue
        # A copied file keeps its name after the last '__' (Check-Public stages blobs that way).
        faction = by_map.get(path.name.split('__')[-1])
        if faction is None or faction not in decals:
            continue
        rgb = read_rgb(path, record['atlas_size'])
        if rgb is None:
            continue
        scores = roundel_correlations(rgb, record, faction, decals[faction])
        if scores and max(scores) > CLEAN_MAX:
            problems.append(f'{path}: shows the {faction} roundel (correlation {max(scores):.2f}, limit {CLEAN_MAX})')
    note = None if len(decals) == len(record['roundels']) else 'no asset export, so only painted-output hashes were checked'
    return problems, note


def main():
    record_path = Path(os.environ.get('ICARUS_FACTION_MARKS_RECORD', RECORD))
    hashes = Path(os.environ.get('ICARUS_FACTION_MARKS_HASHES', HASHES))
    if len(sys.argv) > 1 and sys.argv[1] == 'verify-marked':
        problems = verify_marked(json.loads(record_path.read_text()), hashes=hashes)
        for problem in problems:
            print('FACTION MARKS FAIL:', problem)
        print('FACTION MARKS VERIFY ' + ('FAIL' if problems else 'PASS: every livery Unity builds carries its roundels'))
        return 1 if problems else 0
    if len(sys.argv) > 1 and sys.argv[1] == 'check-clean':
        problems, note = check_clean(sys.argv[2:], json.loads(record_path.read_text()), hashes)
        for problem in problems:
            print('ROUNDEL FAIL:', problem)
        if note:
            print('ROUNDEL NOTE:', note)
        print(f'ROUNDEL CHECK {"FAIL" if problems else "PASS"}: {len(sys.argv) - 2} files')
        return 1 if problems else 0
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--maps', type=Path, default=EXPORT, help='logo-free maps (default art/export/textures)')
    parser.add_argument('--out', type=Path, default=UNITY, help='where the marked textures go (default the Unity Liveries folder)')
    args = parser.parse_args()
    record = json.loads(record_path.read_text())
    inputs, outputs = paint(record, args.maps.resolve(), args.out.resolve())
    if args.out.resolve() == UNITY.resolve():
        hashes.parent.mkdir(parents=True, exist_ok=True)
        hashes.write_text(json.dumps({'inputs': inputs, 'outputs': outputs}, indent=2) + '\n')
    print(f'FACTION MARKS PASS: {len(outputs)} textures with roundels in {args.out}')


if __name__ == '__main__':
    sys.exit(main())
