"""faction_marks.py on a synthetic 64-texel atlas and a synthetic roundel: no game files are read."""
import hashlib
import json

import numpy as np
import pytest
from PIL import Image

import faction_marks
from insignia import PAD

SIZE = 64


def roundel():
    """A red disc in a black ring with a white core, premultiplied and padded as insignia.faction_roundel returns it."""
    y, x = np.mgrid[:40, :40]
    r = np.hypot(x - 19.5, y - 19.5)
    rgb = np.where((r < 8)[..., None], 1., np.where((r < 16)[..., None], [.57, .02, 0], 0.))
    alpha = (r < 19.5).astype(np.float64)
    rgba = np.dstack((rgb * alpha[..., None], alpha))
    return np.pad(rgba, ((PAD, PAD), (PAD, PAD), (0, 0)))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    maps, out = tmp_path / 'maps', tmp_path / 'out'
    maps.mkdir()
    base = np.full((SIZE, SIZE, 3), 120, np.uint8)
    Image.fromarray(base).save(maps / 'Icarus_livery_1.png')
    logo = tmp_path / 'PALA_roundel.png'
    logo.write_bytes(b'stand-in for the stock file')
    # One footprint, texels 20 to 39 in both axes, mapped linearly onto the ink box: s = 0.5 + 5 x with x = (col - 30) / 100.
    skin = {'fin_skin': 'a' * 64}
    blockout = tmp_path / 'blockout.json'
    blockout.write_text(json.dumps({'atlas': {'blender': '5.3.0', 'size': SIZE, 'skin_uv_sha256': skin}}))
    monkeypatch.setattr(faction_marks, 'BLOCKOUT', blockout)
    record = {'atlas_size': SIZE, 'skin_uv_sha256': faction_marks.atlas_guard.whole(skin), 'roundels': {'PALA': 'PALA_roundel'},
              'shade': {'seam': {'paint': .3}, 'fastener': {'paint': .16}}, 'painted_smoothness': .42,
              'liveries': {'1': {'name': 'PALA Navy', 'faction': 'PALA', 'finish': 'paint', 'map': 'Icarus_livery_1.png',
                                 'map_sha256': hashlib.sha256((maps / 'Icarus_livery_1.png').read_bytes()).hexdigest(),
                                 'metallic_map': None, 'metallic_map_sha256': None}},
              'marks': [{'faction': 'PALA', 'label': 'roundel_fin', 'side': 1, 'island': 1, 'origin': [30., 30.],
                         'coefficients': [[.5, 5., 0.], [.5, 0., 5.]], 'max_residual_texels': 0.,
                         'runs': [[row, 20, 40] for row in range(20, 40)], 'relief': []}]}
    record_path = tmp_path / 'faction_marks.json'
    record_path.write_text(json.dumps(record))
    monkeypatch.setattr(faction_marks, 'RECORD', record_path)
    monkeypatch.setattr(faction_marks, 'faction_roundel', lambda faction: roundel())
    monkeypatch.setattr(faction_marks, 'roundel_paths', lambda record: {'PALA': logo})
    inputs, outputs = faction_marks.paint(record, maps, out)
    hashes = tmp_path / 'marks.json'
    hashes.write_text(json.dumps({'inputs': inputs, 'outputs': outputs}))
    return record, maps, out, hashes, logo


def test_footprints_for_other_skin_uvs_are_refused(setup, tmp_path, monkeypatch):
    record, maps, out, _, _ = setup
    other = tmp_path / 'other_blockout.json'
    other.write_text(json.dumps({'atlas': {'blender': '5.2.3', 'size': SIZE, 'skin_uv_sha256': {'fin_skin': 'b' * 64}}}))
    monkeypatch.setattr(faction_marks, 'BLOCKOUT', other)
    with pytest.raises(SystemExit, match='other skin UVs'):
        faction_marks.paint(record, maps, out)


def test_painted_textures_carry_the_roundel(setup):
    record, maps, out, hashes, _ = setup
    assert faction_marks.verify_marked(record, out, hashes) == []


def test_a_logo_free_build_output_fails(setup):
    record, maps, out, hashes, _ = setup
    (out / 'Icarus_livery_1.png').write_bytes((maps / 'Icarus_livery_1.png').read_bytes())
    hashes.write_text(json.dumps({'inputs': {}, 'outputs': {'Icarus_livery_1.png': faction_marks.sha256(out / 'Icarus_livery_1.png')}}))
    problems = faction_marks.verify_marked(record, out, hashes)
    assert problems and 'lacks its PALA roundels' in problems[0]


def test_logo_free_maps_are_clean(setup):
    record, maps, _, hashes, _ = setup
    assert faction_marks.check_clean([maps / 'Icarus_livery_1.png'], record, hashes) == ([], None)


def test_a_marked_file_in_a_tracked_path_fails(setup, tmp_path):
    record, _, out, hashes, logo = setup
    problems, _ = faction_marks.check_clean([out / 'Icarus_livery_1.png', logo], record, hashes)
    assert [p.split(': is ')[1] for p in problems] == ['the painted Icarus_livery_1.png', 'the stock PALA_roundel.png']
    # Re-encoded, the hash no longer matches, and the roundel itself is found.
    copy = tmp_path / '7__Icarus_livery_1.png'
    Image.open(out / 'Icarus_livery_1.png').save(copy, optimize=True, compress_level=9)
    assert faction_marks.sha256(copy) != faction_marks.sha256(out / 'Icarus_livery_1.png')
    problems, _ = faction_marks.check_clean([copy], record, hashes)
    assert problems and 'shows the PALA roundel' in problems[0]


def test_a_checkout_without_the_export_still_checks_hashes(setup, tmp_path, monkeypatch):
    record, _, out, hashes, _ = setup
    monkeypatch.undo()  # the real roundel_paths, reading tools/local-paths.json under ROOT
    monkeypatch.setattr(faction_marks, 'ROOT', tmp_path / 'fresh-checkout')
    assert faction_marks.roundel_paths(record) == {}
    problems, note = faction_marks.check_clean([out / 'Icarus_livery_1.png'], record, hashes)
    assert [p.split(': is ')[1] for p in problems] == ['the painted Icarus_livery_1.png']
    assert note == 'no asset export, so only painted-output hashes were checked'
