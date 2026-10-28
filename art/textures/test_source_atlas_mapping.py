"""Generation-atlas ownership and shared-channel transfer contracts."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

import numpy as np
from PIL import Image

from source_atlas_mapping import FIELDS, donor_part, infer_donor, nearest_parent, remap_fields, restore_inventory, sha256, validate_indices


class SourceAtlasMappingTests(unittest.TestCase):
    def test_changed_bake_rebuilds_from_native_and_covers_unknown_part(self):
        root = Path(__file__).resolve().parents[2] / '.cache/source-atlas-tests' / uuid.uuid4().hex
        sources = root / 'art/textures/generated'
        native = sources / 'full/source-atlas/native'
        frozen = native / 'generation-inputs/old-bake'
        frozen.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        bake = root / '.cache/review/bake'
        bake.mkdir(parents=True)
        part = np.zeros((3, 3), np.uint8)
        part[0, :2] = [1, 2]
        position = np.zeros((3, 3, 4), np.float32)
        position[0, 1, 0] = 10
        normal = np.zeros_like(position)
        normal[..., 2] = 1
        np.savez(frozen / 'geometry_maps.npz', part=part, position=position, normal=normal)
        (frozen / 'atlas_triangles.json').write_text(json.dumps({'parts': ['parent_far', 'parent_near']}))
        np.savez(native / 'ownership.npz', group_index=part)
        groups = {}
        for index, name in enumerate(('far_group', 'near_group'), 1):
            path = native / (name + '.mask.png')
            Image.fromarray((part == index).astype(np.uint8) * 255).save(path)
            groups[name] = {'part': ['parent_far', 'parent_near'][index-1], 'charts': [], 'mask': path.as_posix()}
        (native / 'coverage.json').write_text(json.dumps({'owner_map': (native / 'ownership.npz').as_posix()}))
        frozen_inputs = {path.as_posix(): sha256(path) for path in frozen.iterdir()}
        (native / 'parts.json').write_text(json.dumps({
            'groups': groups, 'guide_size': 1536, 'shared_style': 'frozen style', 'structure': 'frozen structure',
            'source_generation_bake_sha256': sha256(frozen / 'geometry_maps.npz'),
            'generation_input_sha256': frozen_inputs,
            'input_sha256': {(native / 'coverage.json').as_posix(): sha256(native / 'coverage.json'),
                             (native / 'ownership.npz').as_posix(): sha256(native / 'ownership.npz')}}))
        native_hashes = {path: sha256(path) for path in native.rglob('*') if path.is_file()}
        current_part = (part > 0).astype(np.uint8)
        (bake / 'atlas_triangles.json').write_text(json.dumps({'parts': ['new_cove']}))
        current_position = position.copy()
        current_position[0, :2, 0] = [9.9, 10.1]
        np.savez(bake / 'geometry_maps.npz', part=current_part, position=current_position, normal=normal)
        output = root / '.cache/review/full'
        with patch('source_atlas_mapping.ROOT', root), patch('source_atlas_mapping.SOURCE', sources), \
                patch('source_atlas_mapping.ATLAS_SIZE', 3):
            restore_inventory(bake, output)
            coverage = json.loads((output / 'coverage.json').read_text())
            self.assertEqual(coverage['canonical_texels'], 2)
            self.assertEqual(coverage['assigned_texels'], 2)
            self.assertEqual(coverage['unassigned_texels'], 0)
            self.assertEqual(coverage['native_reuse_texels'], 0)
            self.assertEqual(coverage['unmatched_surface_texels'], 2)
            self.assertEqual(coverage['inferred_parent_parts'], ['new_cove'])
            self.assertEqual(coverage['rules'][0]['source_part'], 'parent_near')
            self.assertFalse(coverage['rules'][0]['donor_decision']['matched_detail_claim'])
            self.assertAlmostEqual(coverage['rules'][0]['donor_decision']['score_m'], .1, places=5)
            with patch('source_atlas_mapping.rebuild_inventory', side_effect=AssertionError('Unchanged bake rebuilt')):
                restore_inventory(bake, output)
            current_position[0, :2, 0] = [-.1, .1]
            np.savez(bake / 'geometry_maps.npz', part=current_part, position=current_position, normal=normal)
            restore_inventory(bake, output)
            coverage = json.loads((output / 'coverage.json').read_text())
            self.assertEqual(coverage['rules'][0]['source_part'], 'parent_far')
            self.assertEqual(coverage['unassigned_texels'], 0)
            self.assertEqual(coverage['native_reuse_texels'], 0)
        self.assertEqual({path: sha256(path) for path in native_hashes}, native_hashes)

    def test_inferred_parent_ties_and_normal_weight_are_pinned(self):
        positions = np.zeros((2, 3))
        normals = np.array([[0., 0, -1], [0., 0, 1]])
        donor, decision = infer_donor(positions[:1], normals[1:], ['z_parent', 'a_parent'],
                                      np.array([1, 2]), positions, normals)
        self.assertEqual(donor, 'a_parent')
        self.assertEqual(decision['candidate_scores_m'], {'a_parent': 0., 'z_parent': .04})
        donor, decision = infer_donor(positions[:1], normals[1:], ['z_parent', 'a_parent'],
                                      np.array([1, 2]), positions, np.repeat(normals[1:], 2, axis=0))
        self.assertEqual(donor, 'a_parent')
        self.assertEqual(decision['candidate_scores_m'], {'a_parent': 0., 'z_parent': 0.})

    def test_pilot_guides_restore_current_ownership_without_generation_writes(self):
        import pilot2_parts
        root = Path(__file__).resolve().parents[2] / '.cache/source-atlas-tests' / uuid.uuid4().hex
        sources = root / 'generated'
        pilot = sources / 'pilot2'
        pilot.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        original = pilot / 'radome.png'
        original.write_bytes(b'accepted original')
        current_manifest = sources / 'full/source-atlas/native/parts.json'
        current_manifest.parent.mkdir(parents=True)
        current_manifest.write_text('{}')
        with patch.object(pilot2_parts, 'SOURCE', sources), patch.object(pilot2_parts, 'SOURCES', pilot), \
                patch.object(pilot2_parts, 'OUT', root / 'review'), \
                patch('full_skin_guides.inventory') as inventory, \
                patch('source_atlas_mapping.current_guides') as guides:
            pilot2_parts.guides()
            inventory.assert_called_once_with()
            guides.assert_called_once_with(root / 'review/full/parts.json')
            self.assertEqual(original.read_bytes(), b'accepted original')
            current_manifest.unlink()
            with self.assertRaisesRegex(ValueError, 'immutable'):
                pilot2_parts.guides()

    def test_restore_rebinds_metadata_and_rejects_changed_source_bytes(self):
        root = Path(__file__).resolve().parents[2] / '.cache/source-atlas-tests' / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        sources = root / 'art/textures/generated'
        persistent = sources / 'full/source-atlas'
        native, current = persistent / 'native', persistent / 'current'
        native.mkdir(parents=True)
        current.mkdir()
        bake = root / '.cache/review/bake'
        bake.mkdir(parents=True)
        (bake / 'geometry_maps.npz').write_bytes(b'unchanged prepared geometry')
        source_image = sources / 'full/part.png'
        source_image.write_bytes(b'immutable native image')
        old_root = 'X:/previous-checkout'

        def old(path):
            return old_root + '/' + path.relative_to(root).as_posix()

        def write(path, value):
            path.write_text(json.dumps(value), encoding='utf-8')

        write(native / 'coverage.json', {'owner_map': old(native / 'ownership.npz')})
        write(native / 'parts.json', {'input_sha256': {
            old(native / 'coverage.json'): sha256(native / 'coverage.json'),
            old(source_image): sha256(source_image)}, 'groups': {}})
        write(current / 'coverage.json', {'rules': []})
        write(current / 'parts.json', {
            'source_atlas_manifest': old(native / 'parts.json'),
            'bake': old(bake / 'geometry_maps.npz'), 'coverage': old(current / 'coverage.json'),
            'input_sha256': {old(native / 'parts.json'): sha256(native / 'parts.json'),
                             old(current / 'coverage.json'): sha256(current / 'coverage.json'),
                             old(bake / 'geometry_maps.npz'): sha256(bake / 'geometry_maps.npz')}})
        output = root / '.cache/review/full'
        with patch('source_atlas_mapping.ROOT', root), patch('source_atlas_mapping.SOURCE', sources), \
                patch('source_atlas_mapping.check_inventory'):
            restored = restore_inventory(bake, output)
            self.assertEqual(restored['source_atlas_manifest'], (native / 'parts.json').as_posix())
            self.assertTrue((output / 'parts.json').is_file())
            self.assertEqual(source_image.read_bytes(), b'immutable native image')
            restore_inventory(bake, output)
            source_image.write_bytes(b'altered')
            with self.assertRaisesRegex(ValueError, 'dependency differs'):
                restore_inventory(bake, output)

    def test_restore_rebuilds_a_current_map_older_than_its_manifest(self):
        # A texture-source ZIP older than the committed manifest holds older current/ maps: rebuilt, not refused.
        root = Path(__file__).resolve().parents[2] / '.cache/source-atlas-tests' / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        sources = root / 'art/textures/generated'
        native, current = sources / 'full/source-atlas/native', sources / 'full/source-atlas/current'
        native.mkdir(parents=True)
        current.mkdir()
        bake = root / '.cache/review/bake'
        bake.mkdir(parents=True)
        (bake / 'geometry_maps.npz').write_bytes(b'unchanged prepared geometry')
        stale = current / 'aileron_L_visible.source-transfer.npz'
        stale.write_bytes(b'map from an older pack')
        (native / 'parts.json').write_text(json.dumps({'input_sha256': {}, 'groups': {}}), encoding='utf-8')
        (current / 'parts.json').write_text(json.dumps({'input_sha256': {
            (bake / 'geometry_maps.npz').as_posix(): sha256(bake / 'geometry_maps.npz'),
            stale.as_posix(): '0' * 64}}), encoding='utf-8')
        with patch('source_atlas_mapping.ROOT', root), patch('source_atlas_mapping.SOURCE', sources), \
                patch('source_atlas_mapping.rebuild_inventory', return_value={'rebuilt': True}) as rebuild:
            self.assertEqual(restore_inventory(bake, root / '.cache/review/full'), {'rebuilt': True})
        rebuild.assert_called_once()

    def test_new_door_donors_and_mirror_are_explicit(self):
        names = ['gear_door_N_L_visible', 'gear_door_main_L_visible']
        self.assertEqual(donor_part('gear_door_N2_L_visible', names), ('gear_door_N_L_visible', False))
        self.assertEqual(donor_part('gear_door_N2_R_visible', names), ('gear_door_N_L_visible', True))
        self.assertEqual(donor_part('gear_door_flap_L_visible', names), ('gear_door_main_L_visible', False))
        self.assertEqual(donor_part('gear_door_flap_R_visible', names), ('gear_door_main_L_visible', True))
        self.assertIsNone(donor_part('new_unknown_part', names))

    def test_world_normal_disambiguates_coincident_faces(self):
        source = np.array([[0., 0, 0], [0., 0, 0]])
        normals = np.array([[0., 0, -1], [0., 0, 1]])
        nearest, distance, cosine = nearest_parent(source[:1], normals[1:], source, normals)
        np.testing.assert_array_equal(nearest, [1])
        np.testing.assert_array_equal(distance, [0.])
        np.testing.assert_array_equal(cosine, [1.])

    def test_invalid_and_duplicate_indices_fail_before_sampling(self):
        for target, source in (([0, 0], [1, 2]), ([0], [-1]), ([6], [0])):
            with self.subTest(target=target, source=source), self.assertRaises(ValueError):
                validate_indices(np.array(target), np.array(source), 6, 6)

    def test_all_fields_read_immutable_source_space(self):
        scratch = Path(__file__).resolve().parents[2] / '.cache/source-atlas-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        root = scratch / uuid.uuid4().hex
        root.mkdir()
        self.addCleanup(shutil.rmtree, root)
        with self.subTest('cross-atlas channels'):
            np.savez(root / 'bake.npz', part=np.ones((2, 3), np.uint8))
            np.savez(root / 'first.npz', target_indices=np.array([0, 1, 2]), source_indices=np.array([3, 4, 5]))
            np.savez(root / 'second.npz', target_indices=np.array([3, 4, 5]), source_indices=np.array([0, 1, 2]))
            coverage = {'rules': [{'map': str(root / 'first.npz'), 'name': 'first'},
                                  {'map': str(root / 'second.npz'), 'name': 'second'}],
                        'native_reuse_texels': 4, 'unmatched_surface_texels': 2, 'unassigned_texels': 0}
            (root / 'coverage.json').write_text(json.dumps(coverage))
            (root / 'parts.json').write_text(json.dumps({
                'bake': str(root / 'bake.npz'), 'coverage': str(root / 'coverage.json'),
                'source_atlas_manifest': 'native/parts.json', 'input_sha256': {}}))
            scalar = np.arange(6, dtype=np.float32).reshape(2, 3)
            source = {key: scalar.copy() for key in FIELDS}
            source['base'] = np.repeat(scalar[..., None], 3, axis=-1)
            source['used'] = np.ones((2, 3), bool)
            source['height_valid'] = scalar % 2 == 0
            source['roughness_valid'] = scalar > 2
            source['report'] = {'groups': {'original': {'skin_texels': 99, 'registration': ['native']}}}
            with patch('source_atlas_mapping.check_inventory'):
                result = remap_fields(source, root / 'parts.json')
            order = [3, 4, 5, 0, 1, 2]
            for key in FIELDS:
                shape = (-1, 3) if key == 'base' else (-1,)
                np.testing.assert_array_equal(result[key].reshape(shape), source[key].reshape(shape)[order])
            self.assertEqual(result['report']['groups'], source['report']['groups'])
            self.assertEqual(result['report']['assigned_texels'], 6)
            self.assertEqual(result['report']['height_accepted_texels'], 3)
            self.assertEqual(result['report']['roughness_accepted_texels'], 3)
            self.assertEqual(result['report']['old_quadrant_fallback_texels'], 0)
            np.testing.assert_array_equal(source['height'], scalar)


if __name__ == '__main__':
    unittest.main()
