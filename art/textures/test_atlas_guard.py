"""The export-side guard against a skin baked for another UV pack (art/blender/atlas_guard.py)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender'))
import atlas_guard  # noqa: E402


def record(blender, **parts):
    return {'blender': blender, 'size': 4096, 'skin_uv_sha256': parts}


def test_the_same_uvs_pass():
    uvs = atlas_guard.uv_digest([(0.25, 0.5), (0.75, 0.125)], 4096)
    atlas_guard.require_same(record('5.3.0', fin_skin=uvs), record('5.3.0', fin_skin=uvs), 'compose')


def test_a_bake_for_another_pack_is_refused_naming_its_parts():
    exported = record('5.3.0', fin_skin=atlas_guard.uv_digest([(0.25, 0.5)], 4096), radome=atlas_guard.uv_digest([(0.1, 0.1)], 4096))
    baked = record('5.2.3', fin_skin=atlas_guard.uv_digest([(0.25, 0.5 + 1 / 4096)], 4096), radome=exported['skin_uv_sha256']['radome'])
    with pytest.raises(ValueError, match=r'on 1 parts \(fin_skin\)'):
        atlas_guard.require_same(exported, baked, 'compose')


def test_a_part_one_record_lacks_is_a_mismatch():
    assert atlas_guard.mismatched({'radome': 'x', 'fin_skin': 'y'}, {'radome': 'x'}) == ['fin_skin']


def test_digests_hold_to_an_eighth_of_a_texel():
    texel = 1 / 4096
    assert atlas_guard.uv_digest([(0.5, 0.5)], 4096) == atlas_guard.uv_digest([(0.5 + texel / 32, 0.5)], 4096)
    assert atlas_guard.uv_digest([(0.5, 0.5)], 4096) != atlas_guard.uv_digest([(0.5 + texel / 4, 0.5)], 4096)
