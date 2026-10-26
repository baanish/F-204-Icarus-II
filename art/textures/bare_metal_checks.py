"""Verify dedicated aluminium fields, matched renders and the review handback."""
import hashlib
import json
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from rasterize import ROOT, OUT

FULL = ROOT / '.cache/review/wave2/p9b-round2/full'
FOLDER = FULL / 'bare-metal'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_current_maps():
    """Check exact material masks without comparing atlases from different geometry."""
    maps = FULL / 'art/export/textures'
    with np.load(OUT / 'atlas_geometry.npz') as geometry:
        used = geometry['part'] > 0
        part = geometry['part']
        station = geometry['position'][..., 1] + read(FULL.parent / 'structure.json')['S0']
    shared = np.asarray(Image.open(maps / 'Icarus_skin_m.png'))
    names = read(OUT / 'atlas_triangles.json')['parts']
    fuselage = np.isin(part, [i + 1 for i, name in enumerate(names)
                            if name.startswith(('skin_forward', 'skin_mid', 'skin_aft', 'dorsal_cover'))])
    # Station 14.2 is the last butt joint. Only its final ring and the nozzle are hot metal.
    cold = fuselage & (station < 14.19)
    hot = fuselage & (station > 14.21)
    brakes = np.isin(part, [i + 1 for i, name in enumerate(names) if name.startswith('speed_brake_')])
    nozzle = np.isin(part, [i + 1 for i, name in enumerate(names) if name.startswith('nozzle')])
    assert cold.any() and hot.any() and brakes.any() and nozzle.any()
    assert np.all(shared[..., 0][cold] == 0), 'Livery must cover the fuselage ahead of station 14.2'
    assert np.all(shared[..., 0][hot] == 255), 'The entire final fuselage ring must stay metal'
    assert np.all(shared[..., 0][brakes & (station < 14.19)] == 0), 'Speed brakes ahead of the hot ring must take livery'
    assert np.all(shared[..., 0][nozzle] == 255), 'The nozzle must stay metal'
    metallic = np.asarray(Image.open(maps / 'Icarus_livery_4_m.png'))
    assert metallic.shape == (*used.shape, 4)
    assert Image.open(maps / 'Icarus_livery_4.png').mode == 'RGB'
    assert read(ROOT / 'art/textures/liveries/4_metal.json')['glossiness'] == 0.0
    with np.load(FULL / 'bare_metal_masks.npz') as masks:
        # protected is the exhaust weight: 1 keeps shared values, 0 is polished sheet, between blends.
        paint, protected = masks['paint'], masks['protected']
        paint_core = used & (paint == 1)
        unpainted = used & (paint == 0) & (protected == 0)
        special = used & (protected == 1) & (paint == 0)
        assert np.all(metallic[..., 0][paint_core] == 0)
        assert np.all(metallic[..., 0][unpainted] == 250)
        assert np.array_equal(metallic[special], shared[special])
        expected = np.uint8((protected * shared[..., 0] / 255 + (1 - protected) * .98) * (1 - paint) * 255 + .5)
        error = int(abs(metallic[..., 0][used].astype(int) - expected[used].astype(int)).max())
        assert error <= 1
        glare = used & (masks['anti_glare'] == 1)
        assert np.all(metallic[..., 3][glare] == 46)
        radome_sheet = masks['radome'] & (masks['anti_glare'] == 0)
        assert radome_sheet.any() and np.all(paint[radome_sheet] == 0), 'The radome must keep the bare sheet finish'
        assert np.all(metallic[..., 0][radome_sheet] == 250), 'The radome must use the fuselage aluminium value'
        assert np.all((metallic[..., 3][unpainted] >= 209) & (metallic[..., 3][unpainted] <= 245))
        counts = {key: int((used & (masks[key] == 1)).sum()) for key in masks.files}
    report = {'status': 'pass', 'geometry_sha256': sha(OUT / 'atlas_geometry.npz'),
              'skin_texels': int(used.sum()), 'bare_aluminium_texels': int(unpainted.sum()),
              'paint_core_texels': int(paint_core.sum()), 'protected_unpainted_texels': int(special.sum()),
              'mask_core_counts': counts, 'mask_red_max_byte_error': error,
              'shared_metallic_mean_red': float((shared[..., 0][used] / 255).mean()),
              'dedicated_metallic_mean_red': float((metallic[..., 0][used] / 255).mean()),
              'maps': {path.name: sha(path) for path in maps.glob('*.png')}}
    (FULL / 'bare-metal-current-measurements.json').write_text(json.dumps(report, indent=2) + '\n')
    print('BARE METAL CURRENT MASK CHECK PASS', counts)
    return report


def verify(maps_only=False):
    maps = FULL / 'art/export/textures'
    before = FOLDER / 'dielectric-before/art/export/textures'
    changed = sorted(path.name for path in maps.glob('*.png')
                     if not (before / path.name).exists() or sha(path) != sha(before / path.name))
    assert changed == ['Icarus_livery_4.png', 'Icarus_livery_4_m.png'], changed
    measurement = read(FULL / 'measurements.json')
    assert measurement['status'] == 'pass'
    if not maps_only:
        assert read(FULL / 'review/render_manifest.json')['status'] == 'complete'
    original = read(FOLDER / 'before/render_manifest.json')
    assert original['alignment_sha256'] == sha(FULL / 'alignment.json')
    composition = read(FULL / 'composition.json')
    old_composition = read(FOLDER / 'dielectric-before/composition.json')
    assert composition['liveries']['4']['markings'] == old_composition['liveries']['4']['markings']
    assert read(ROOT / 'art/textures/liveries/4_metal.json')['glossiness'] == 0.0
    with np.load(OUT / 'geometry_maps.npz') as geometry:
        position, used = geometry['position'][..., :3], geometry['part'] > 0
    current = np.asarray(Image.open(maps / 'Icarus_livery_4.png'))
    previous = np.asarray(Image.open(before / 'Icarus_livery_4.png'))
    assert Image.open(maps / 'Icarus_livery_4.png').mode == 'RGB'
    y = position[..., 1]
    unbanded = used & (abs(y + 2.4) > .4) & (abs(y - 4.55) > .4)
    band_core = used & ((abs(y + 2.4) < .33) | (abs(y - 4.55) < .31))
    assert np.array_equal(current[band_core], previous[band_core])
    shared = np.asarray(Image.open(maps / 'Icarus_skin_m.png'))
    metallic = np.asarray(Image.open(maps / 'Icarus_livery_4_m.png'))
    assert metallic.shape == (2048, 2048, 4)
    with np.load(FULL / 'bare_metal_masks.npz') as masks:
        paint, protected = masks['paint'], masks['protected']
        paint_core = used & (paint == 1)
        unpainted = used & (paint == 0) & ~protected
        special = used & protected & (paint == 0)
        assert np.all(metallic[..., 0][paint_core] == 0)
        assert np.all(metallic[..., 0][unpainted] == 250)
        assert np.array_equal(metallic[special], shared[special])
        expected = np.uint8(np.where(protected, shared[..., 0] / 255, .98) * (1 - paint) * 255 + .5)
        assert np.max(abs(metallic[..., 0][used].astype(int) - expected[used].astype(int))) <= 1
        glare = used & (masks['anti_glare'] == 1)
        assert np.all(metallic[..., 3][glare] == 46)
        assert np.all((metallic[..., 3][unpainted] >= 209) & (metallic[..., 3][unpainted] <= 245))
        mask_counts = {key: int((used & (masks[key] == 1)).sum()) for key in masks.files}
    if maps_only:
        print('BARE METAL NATIVE MASK CHECK PASS', mask_counts)
        return
    renders = read(FOLDER / 'render_manifest.json')
    assert renders['status'] == 'complete' and len(renders['renders']) == 4
    assert max(renders['camera']['mesh_projection_frame_fraction']) <= 1 / 1.1 + 1e-6
    for entry in renders['renders']:
        assert sha(entry['path']) == entry['sha256']
        folder = {'round1': ROOT / 'art/export/textures',
                  'full_before': FOLDER / 'before/art/export/textures',
                  'dielectric_before': before, 'full_after': maps}[entry['variant']]
        assert all(sha(folder / name) == digest for name, digest in entry['maps'].items())
    assert renders['renders'][-1]['metallic_map'] == 'Icarus_livery_4_m.png'
    try:
        font = ImageFont.truetype(str(ROOT / 'art/textures/fonts/BarlowCondensed-Regular.ttf'), 34)
    except OSError:
        font = ImageFont.load_default(size=34)
    pairs = []
    for left, caption in [('round1', 'Round 1 / main'), ('full_before', 'Original full pass'),
                          ('dielectric_before', 'Previous shared-map revision')]:
        canvas = Image.new('RGB', (2400, 1464), '#171d23')
        draw = ImageDraw.Draw(canvas)
        for column, (variant, label) in enumerate([(left, caption), ('full_after', 'Dedicated aluminium material map')]):
            with Image.open(FOLDER / (variant + '_daylight.png')) as image:
                assert image.size == (1200, 1400)
                canvas.paste(image, (1200 * column, 64))
            draw.text((1200 * column + 24, 14), label, font=font, fill='white')
        output = FOLDER / (left + '_versus_revised.png')
        canvas.save(output)
        pairs.append(output.as_posix())
    report = {'status': 'pass', 'changed_maps': changed, 'glossiness_before': 1., 'glossiness_after': 0.,
              'before_mean_rgb_unbanded': previous[unbanded].mean(axis=0).tolist(),
              'after_mean_rgb_unbanded': current[unbanded].mean(axis=0).tolist(),
              'statistics_mask': 'skin excluding longitudinal band centres +/-0.4m; includes markings',
              'band_core_texels': int(band_core.sum()), 'band_core_changed_texels': 0,
              'shared_metallic_mean_red': float((shared[..., 0][used] / 255).mean()),
              'dedicated_metallic_mean_red': float((metallic[..., 0][used] / 255).mean()),
              'bare_aluminium_texels': int(unpainted.sum()), 'paint_core_texels': int(paint_core.sum()),
              'protected_unpainted_texels': int(special.sum()), 'mask_core_counts': mask_counts,
              'mask_red_max_byte_error': int(abs(metallic[..., 0][used].astype(int) - expected[used].astype(int)).max()),
              'seams': measurement['seams']['liveries']['4'], 'finish': composition['bare_metal'],
              'comparisons': pairs, 'render_manifest_sha256': sha(FOLDER / 'render_manifest.json'),
              'alignment_sha256_unchanged': sha(FULL / 'alignment.json'),
              'maps': {path.name: sha(path) for path in maps.glob('*.png')}}
    (FOLDER / 'measurements.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def handback(report):
    target = FULL.parent / 'p9b-round2-handback.md'
    previous = target.read_text(encoding='utf-8').split('\n## Bare Metal\n', 1)[0]
    p = lambda value: Path(value).as_posix()
    lines = ['## Bare Metal', '',
        'The current full-pass set includes a dedicated livery-4 metallic map and a reversible runtime swap. This supersedes the previous glossy dielectric approximation. Owner appearance acceptance is pending. Unity B0 was not run.', '',
        '### Material map and albedo', '',
        f'Dedicated map: {p(FULL / "art/export/textures/Icarus_livery_4_m.png")}. It is 2048 square RGBA, intended for linear DXT5 import. Bare sheet red is 0.98, encoded 250/255. Smoothness alpha is near 0.90 with residual variation constrained to 0.82-0.96. Painted regions have red zero; their smoothness is 0.42, or 0.18 on the anti-glare panel. Radome remains dielectric. Original nozzle and exhaust fields retain shared-map values wherever unpainted.', '',
        'The compositor records the exact accumulated sampled decal alpha while placing the original markings. It combines that coverage with the same visibility-band and anti-glare masks used for albedo. Painted coverage takes priority even over protected metal. No separate image threshold guesses where numbers or roundels are. Eight-texel gutter dilation is shared with the other maps.', '',
        f'Checks: {report["bare_aluminium_texels"]} clear aluminium texels have red exactly 250; {report["paint_core_texels"]} fully painted texels have red zero; {report["protected_unpainted_texels"]} protected unpainted texels match the shared RGBA bytes. Maximum red mask encoding error is {report["mask_red_max_byte_error"]} byte. Mask counts and partial-edge checks: {p(FOLDER / "measurements.json")}.', '',
        'Albedo now represents metal reflectance colour, using upper RGB 0.76/0.78/0.80 and lower 0.80/0.81/0.82. This replaces the darker dielectric experiment. Generated sheet boundaries, warm/cool tone differences, brushing and aft staining remain. A dark anti-glare area is authored on the upper forward nose. The orange bands and original lettering placement remain.', '',
        f'Mean unbanded stored RGB including markings: {report["before_mean_rgb_unbanded"]} before and {report["after_mean_rgb_unbanded"]} after. All {report["band_core_texels"]} solid orange-band texels are byte-identical. Only livery 4 albedo changes among the previous nine maps; the tenth PNG is the new material map. Liveries 1-3 and shared normal, AO, metallic and damage maps remain byte-identical. Part source images and native alignment reports are unchanged.', '',
        '### Runtime patch and bundle transport', '',
        f'{p(ROOT / "src/Icarus/BareMetalLivery.cs")}:8 registers the exact UnitPart.SetLivery(LiveryData, MaterialCleanup) postfix. It is gated by FeaturesOff bare-metal-livery and the aircraft definition jsonKey baanish_icarus. Stock SetLivery first creates and registers the renderer material instance. The postfix mutates that existing instance through sharedMaterial, after checking the skin shader and Basecolor identity. It never requests another material instance or modifies the source assets.', '',
        'Texture reference identity against the carrier material identifies Bare Metal. Any other livery, including a custom livery or null texture, selects the original shared map again. This covers switching on an already spawned aircraft in both directions. It does not alter hit points, damage textures or other material properties.', '',
        f'{p(ROOT / "unity/Assets/Icarus/Editor/IcarusAuthor.Materials.cs")}:170 authors root child Icarus_livery_materials, inactive, disabled, layer 3, with no MeshFilter. Its MeshRenderer holds two shared materials: the unchanged skin and Icarus_bare_metal.mat. The latter references the livery-4 albedo and gate-approved dedicated metallic texture. This explicit prefab dependency ships the assets in the bundle and keeps both restoration references reachable from the aircraft root after physics unparents parts. It needs no loose PNG loading, global cache, custom runtime carrier component or additional material instance.', '',
        f'{p(ROOT / "unity/Assets/Icarus/Editor/IcarusAuthor.Checks.Skin.cs")}:14 excludes the mesh-free carrier from actual skin UV/owner checks, then validates its inactive/disabled layer-3 contract, texture identities, linear import, DXT5 alpha and dimensions. Mesh registration also excludes mesh-free renderers. Actual bundle references and Unity authoring compilation still require B0.', '',
        '### Gloss contract', '',
        'VERIFIED installed D3D11 AircraftSkin program 256 computes smoothness = saturate((M + L*(max(M,G)-M))*D), where M is metallic alpha, L is livery alpha, G is Glossiness, and D is damage reduction. Our RGB DXT1 livery has L=1. Gloss 1 would force every undamaged surface to maximum smoothness and defeat the new rough anti-glare alpha. Livery 4 therefore now sends Glossiness 0, letting its dedicated alpha provide polished sheets and rougher paint. Other liveries retain their original gloss settings.', '',
        f'Installed shader disassembly and reproduction: {p(FOLDER / "shader/findings.md")}; decisive instructions {p(FOLDER / "shader/d3d11-256.asm")}:84-90. UnitPart source: NO-Agentic-Framework/.cache/decompiled/Assembly-CSharp/UnitPart.cs:238-246. LiveryData itself has no metallic field; the postfix supplies the per-livery switch. No shader replacement is required.', '',
        '### Verification and matched daylight', '',
        'Plugin Release build passed with zero warnings and zero errors, staged only under .cache/build-staging/dotnet. The linked-production postfix harness passed repeated Bare Metal-to-other/custom/null-texture restoration, aircraft/feature gates, ownership/no material creation, missing carrier handling and damage-property preservation. It uses test doubles and does not establish Harmony execution or bundle behavior inside the game.', '',
        f'45 focused Python tests pass. Full offline checks pass. Livery-4 seam median is {report["seams"]["median_rgb_levels"]:.6f}, p95 {report["seams"]["p95_rgb_levels"]:.6f} RGB levels. Material tests pin exact clear/painted/protected values and fractional decal coverage. The preview uses the dedicated map for livery 4 and the shared map for all others.', '',
        'The same runway camera, hard sun, procedural clear sky, samples and geometry compare the previous shared-map revision directly against the new conductor response. Initial round-1 and pre-darkening comparisons are also retained. The conductor reads dark blue-grey from this camera as it reflects the environment, despite its brighter albedo; strong runway reflections are visible. Camera/lighting are inferred from the screenshot; exact game atmosphere, probes, tone mapping, compression and live appearance remain unverified.', '']
    lines += ['- ' + path for path in report['comparisons']]
    lines += ['', f'Native renders and camera/light/map hashes: {p(FOLDER / "render_manifest.json")}',
              f'Updated livery-4 overviews: {p(FULL / "review/livery_4_overviews.png")}', '',
              'Rebake order after merging: compose current full sources, write the export manifest, run compose_skin.py measure to pin all ten maps, then B0. ImportSkinTexture requires the dedicated map hash in gate.json. Ship the plugin DLL and rebuilt bundle together. Existing serialized Unity assets have not been updated.', '',
              'No Unity launch, game run, deployment, commit or push. The only main-checkout write is this handback. The earlier Full pass section retains pre-Bare-Metal measurements; this section and current measurement JSON describe the latest set.', '',
              '~~~powershell', 'dotnet build src/Icarus -c Release -o .cache/build-staging/dotnet',
              'dotnet run --project .cache/bare-metal-runtime-tests/BareMetalRuntimeTests.csproj -c Release',
              'python art/textures/full_skin_checks.py measure',
              'pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python art/blender/bare_metal_review.py',
              'pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python art/blender/full_skin_review.py -- --overview-only',
              'python art/textures/full_skin_checks.py sheets', 'python art/textures/bare_metal_checks.py', '~~~', '']
    text = previous.rstrip() + '\n\n' + '\n'.join(lines)
    assert '\u2013' not in text and '\u2014' not in text
    target.write_text(text, encoding='utf-8')
    print('BARE METAL MATERIAL HANDBACK PASS', target, sha(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--maps-only', action='store_true')
    selection.add_argument('--current-maps', action='store_true', help='check current masks without historical atlas comparisons')
    args = parser.parse_args()
    if args.current_maps:
        verify_current_maps()
    else:
        report = verify(args.maps_only)
        if not args.maps_only:
            handback(report)
