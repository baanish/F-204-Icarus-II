"""Current-atlas ownership and fresh overview evidence contracts."""
import copy
from pathlib import Path
import shutil
import unittest
import uuid

import numpy as np
from PIL import Image

from full_skin_checks import (MAPS, current_coverage_checks, mapping_geometry_checks, read_json, sha256, sheets,
                              write_json)
from source_atlas_mapping import FIELDS


def test_directory(test):
    workspace = Path(__file__).resolve().parents[2]
    directory = (workspace / '.cache/full-skin-check-tests' / uuid.uuid4().hex).resolve()
    if not directory.is_relative_to(workspace):
        raise ValueError('Test scratch escaped workspace')
    directory.mkdir(parents=True)
    test.addCleanup(shutil.rmtree, directory)
    return directory


class CurrentCoverageTests(unittest.TestCase):
    def setUp(self):
        self.full = test_directory(self)
        self.native = self.full / 'native'
        self.native.mkdir()
        self.names = ['oldB', 'oldA', 'gear_door_N2_L_visible']
        self.source_names = ['oldA', 'oldB']
        self.part = np.array([[1, 1, 2, 0], [2, 3, 3, 0]], np.uint16)
        self.source_part = np.array([[1, 1, 1, 0], [2, 2, 2, 0]], np.uint16)
        self.source_owner = np.array([[0, 1, 0, -1], [1, 0, 1, -1]], np.int16)
        self.owner = np.array([[1, 0, 0, -1], [1, 0, 0, -1]], np.int16)
        self.groups = ['group_A', 'group_B']
        np.savez(self.full / 'geometry_maps.npz', part=self.part)
        write_json(self.full / 'atlas_triangles.json', {'parts': self.names})
        np.savez(self.native / 'ownership.npz', group_index=self.source_owner + 1,
                 group_names=self.groups)
        write_json(self.native / 'coverage.json', {'owner_map': 'ownership.npz'})
        self.source_manifest = {'groups': {}}
        current_groups = {}
        self.alignment = {}
        for i, name in enumerate(self.groups):
            old_mask = self.native / (name + '.png')
            Image.fromarray((self.source_owner == i).astype('uint8') * 255).save(old_mask)
            mask = self.owner == i
            Image.fromarray(mask.astype('uint8') * 255).save(self.full / (name + '.png'))
            self.source_manifest['groups'][name] = {'charts': [{'chart': i}], 'mask': str(old_mask)}
            current_groups[name] = {'generation_atlas_charts': [{'chart': i}],
                'generation_atlas_mask': str(old_mask), 'mask': name + '.png',
                'skin_texels': int(mask.sum()),
                'parts': [part_name for j, part_name in enumerate(self.names, 1)
                          if np.any(mask & (self.part == j))]}
            self.alignment[name] = {'skin_texels': 999, 'companions': {
                'height': {'status': 'accepted' if i == 0 else 'fallback'},
                'roughness': {'status': 'fallback' if i == 0 else 'accepted'}}}
        write_json(self.native / 'parts.json', self.source_manifest)
        rules, parts = [], {}
        for name, donor, target, source, matched in (
            ('oldB', 'oldB', [0, 1], [4, 5], [True, True]),
            ('oldA', 'oldA', [2, 4], [0, 1], [True, False]),
            ('gear_door_N2_L_visible', 'oldA', [5, 6], [2, 0], [False, False]),
        ):
            path = self.full / (name + '.npz')
            np.savez(path, target_indices=np.array(target), source_indices=np.array(source),
                     matched=np.array(matched))
            mask = np.zeros(self.part.shape, np.uint8)
            mask.ravel()[target] = 255
            Image.fromarray(mask).save(self.full / (name + '.png'))
            source_groups = [self.groups[i] for i in np.unique(self.source_owner.ravel()[source])]
            rules.append({'name': name, 'target_part': name, 'source_part': donor,
                'source_space': 'generation_atlas', 'map': str(path), 'target_texels': 2,
                'native_reuse_texels': sum(matched), 'geometric_matches': sum(matched),
                'unmatched_surface_texels': 2 - sum(matched), 'match_tolerance_m': .015,
                'normal_cosine_min': .95, 'target_mask': name + '.png', 'source_groups': source_groups})
            parts[name] = {'canonical_texels': 2, 'assigned_texels': 2,
                'native_reuse_texels': sum(matched), 'parent_paint_texels': 2 - sum(matched),
                'groups': source_groups}
        np.savez(self.full / 'ownership.npz', group_index=self.owner + 1, group_names=self.groups)
        self.coverage = {'schema_version': 2, 'field_contract': list(FIELDS), 'rules': rules,
            'parts': parts, 'owner_map': 'ownership.npz', 'unassigned_texels': 0,
            'unassigned_islands': [], 'direct_texels': 0, 'transferred_texels': 6,
            'assigned_texels': 6, 'canonical_texels': 6, 'native_reuse_texels': 3,
            'unmatched_surface_texels': 3}
        inputs = [self.full / 'geometry_maps.npz', self.full / 'atlas_triangles.json',
                  self.native / 'parts.json', self.native / 'coverage.json',
                  self.native / 'ownership.npz', *(Path(rule['map']) for rule in rules)]
        self.manifest = {'groups': current_groups, 'bake': 'geometry_maps.npz',
            'source_atlas_manifest': str(self.native / 'parts.json'),
            'input_sha256': {str(path): sha256(path) for path in inputs}}
        self.stitch = {'assigned_texels': 6, 'height_accepted_texels': 4, 'roughness_accepted_texels': 2}

    def check(self):
        report = {'groups': {name: {} for name in self.groups}}
        used, owner = current_coverage_checks(self.manifest, self.alignment, self.coverage,
            self.stitch, self.full, self.part, self.names, report, self.source_manifest,
            self.source_part, self.source_names, self.source_owner)
        return report, used, owner

    def test_separate_atlases_preserve_acceptance_with_changed_inventory(self):
        report, used, owner = self.check()
        np.testing.assert_array_equal(owner, self.owner)
        np.testing.assert_array_equal(used, self.part > 0)
        self.assertEqual(report['coverage']['part_count'], 3)
        self.assertEqual(report['coverage']['assigned_texels'], 6)
        self.assertEqual(report['coverage']['height_accepted_texels'], 4)
        self.assertEqual(report['coverage']['height_fallback_texels'], 2)
        self.assertEqual(report['coverage']['roughness_accepted_texels'], 2)
        self.assertEqual(report['coverage']['roughness_fallback_texels'], 4)

    def test_changed_geometry_hash_is_rejected(self):
        np.savez(self.full / 'geometry_maps.npz', part=self.part + 1)
        with self.assertRaisesRegex(ValueError, 'Manifest input changed'):
            self.check()

    def test_missing_map_hash_is_rejected(self):
        del self.manifest['input_sha256'][self.coverage['rules'][0]['map']]
        with self.assertRaisesRegex(ValueError, 'Missing required manifest input hash'):
            self.check()

    def test_invalid_indices_are_rejected_even_with_updated_hash(self):
        for target, source in (([0, 0], [4, 5]), ([0, 1], [4, 99]), ([0, 1], [4, 3])):
            with self.subTest(target=target, source=source):
                path = Path(self.coverage['rules'][0]['map'])
                np.savez(path, target_indices=np.array(target), source_indices=np.array(source),
                         matched=np.array([True, True]))
                self.manifest['input_sha256'][str(path)] = sha256(path)
                with self.assertRaises(ValueError):
                    self.check()

    def test_saved_ownership_must_equal_reconstructed_ownership(self):
        np.savez(self.full / 'ownership.npz', group_index=np.zeros_like(self.owner), group_names=self.groups)
        with self.assertRaisesRegex(ValueError, 'saved ownership differs'):
            self.check()

    def test_current_group_mask_must_equal_reconstructed_ownership(self):
        Image.fromarray((self.owner == 1).astype('uint8') * 255).save(self.full / 'group_A.png')
        with self.assertRaisesRegex(ValueError, 'Current group mask differs'):
            self.check()

    def test_companion_acceptance_cannot_change_during_remap(self):
        self.stitch['height_accepted_texels'] = 6
        with self.assertRaisesRegex(ValueError, 'Remapped height acceptance differs'):
            self.check()

    def test_inventory_cannot_hide_a_canonical_part(self):
        del self.coverage['parts'][self.names[-1]]
        with self.assertRaisesRegex(ValueError, 'part inventory differs'):
            self.check()

    def test_replaced_doors_cannot_claim_native_mechanical_detail(self):
        rule = self.coverage['rules'][-1]
        path = Path(rule['map'])
        np.savez(path, target_indices=np.array([5, 6]), source_indices=np.array([2, 0]),
                 matched=np.array([True, False]))
        rule.update(native_reuse_texels=1, geometric_matches=1, unmatched_surface_texels=1)
        self.manifest['input_sha256'][str(path)] = sha256(path)
        with self.assertRaisesRegex(ValueError, 'Replaced surface claims native mechanical detail'):
            self.check()


class MappingGeometryTests(unittest.TestCase):
    def setUp(self):
        self.full = test_directory(self)
        self.current = self.full / 'current.npz'
        self.source = self.full / 'source.npz'
        self.positions = np.array([[[1., 0, 0], [1.01, 0, 0], [1.1, 0, 0]]])
        self.normals = np.array([[[1., 0, 0], [1, 0, 0], [0, 1, 0]]])
        self.save_current()
        np.savez(self.source, part=np.ones((1, 1)), position=np.array([[[-1., 0, 0]]]),
                 normal=np.array([[[-1., 0, 0]]]))
        distance = np.linalg.norm(self.positions.reshape(-1, 3) - [1, 0, 0], axis=1)
        self.values = {'target_indices': np.arange(3), 'source_indices': np.zeros(3, int),
                       'distance_m': distance.astype(np.float32),
                       'normal_cosine': np.array([1, 1, 0], np.float32),
                       'matched': np.array([True, True, False])}
        self.rule = {'target_part': 'panel', 'source_part': 'panel', 'reflect_world_x': True,
                     'map': 'transfer.npz'}

    def save_current(self):
        np.savez(self.current, part=np.ones((1, 3)), position=self.positions, normal=self.normals)

    def check(self):
        np.savez(self.full / 'transfer.npz', **self.values)
        report = {}
        mapping_geometry_checks({'rules': [self.rule]}, self.full, self.current, self.source, report)
        return report['mapping_geometry']['parts'][self.rule['target_part']]

    def test_reflected_geometry_pins_reuse_and_distance_statistics(self):
        part = self.check()
        self.assertEqual(part['native_reuse_texels'], 2)
        self.assertEqual(part['parent_paint_texels'], 1)
        self.assertAlmostEqual(part['maximum_distance_m'], .1)
        self.assertAlmostEqual(part['p95_distance_m'], .091)
        self.assertEqual(part['minimum_normal_cosine'], 0)

    def test_displaced_geometry_cannot_keep_old_distance_record(self):
        self.positions[0, 1, 0] = 1.03
        self.save_current()
        with self.assertRaisesRegex(ValueError, 'geometry measurement differs.*distance_m'):
            self.check()

    def test_forged_native_match_is_rejected(self):
        self.values['matched'][:] = True
        with self.assertRaisesRegex(ValueError, 'native reuse differs from measured geometry'):
            self.check()

    def test_forged_normal_measurement_is_rejected(self):
        self.values['normal_cosine'][0] = .5
        with self.assertRaisesRegex(ValueError, 'geometry measurement differs.*normal_cosine'):
            self.check()

    def test_doors_brakes_and_new_donors_are_always_parent_paint(self):
        for name in ('gear_door_N2_L_visible', 'speed_brake_L_visible', 'new_panel'):
            with self.subTest(name=name):
                self.rule['target_part'] = name
                self.values['matched'][:] = False
                part = self.check()
                self.assertEqual(part['native_reuse_texels'], 0)
                self.assertEqual(part['parent_paint_texels'], 3)
                self.assertTrue(part['forced_parent_paint'])


class OverviewSheetTests(unittest.TestCase):
    def setUp(self):
        self.full = test_directory(self)
        maps = self.full / 'art/export/textures'
        maps.mkdir(parents=True)
        for name in MAPS:
            Image.new('RGB', (8, 8), (45, 60, 90)).save(maps / name)
        self.bake = self.full / 'bake'
        self.bake.mkdir()
        (self.bake / 'skin.blend').write_bytes(b'current geometry fixture')
        (self.bake / 'geometry_maps.npz').write_bytes(b'current atlas fixture')
        write_json(self.bake / 'atlas_triangles.json', {'parts': ['current_part']})
        write_json(self.full / 'parts.json', {'groups': {'source_group': {}},
                                            'bake': str(self.bake / 'geometry_maps.npz')})
        write_json(self.full / 'alignment.json', {'source_group': {'native': True}})
        hashes = {name: sha256(maps / name) for name in MAPS}
        geometry_hash = sha256(self.bake / 'skin.blend')
        entries = []
        for livery in range(1, 5):
            for view in ('top', 'side', 'front_quarter', 'rear_quarter'):
                filename = f'livery_{livery}_{view}.png'
                path = self.full / 'renders' / filename
                path.parent.mkdir(exist_ok=True)
                Image.new('RGB', (16, 16), (50, 80, 100)).save(path)
                entries.append({'group': None, 'material': 'overview', 'livery': livery, 'view': view,
                    'file': filename, 'status': 'rendered', 'png_sha256': sha256(path),
                    'map_sha256': dict(hashes), 'alignment_sha256': sha256(self.full / 'alignment.json'),
                    'geometry_sha256': geometry_hash})
        # Historical close-ups need not exist and cannot contribute current review evidence.
        entries.append({'group': 'source_group', 'file': 'old_closeup.png'})
        inputs = [self.full / 'parts.json', self.bake / 'geometry_maps.npz',
                  self.bake / 'atlas_triangles.json']
        self.renders = {'renders': entries, 'requested_complete': True, 'resolution': [16, 16],
            'geometry': str(self.bake / 'skin.blend'), 'geometry_sha256': geometry_hash,
            'input_sha256': {str(path): sha256(path) for path in inputs}}

    def run_sheets(self):
        write_json(self.full / 'render_manifest.json', self.renders)
        sheets(self.full, overview_only=True)
        return read_json(self.full / 'review/render_manifest.json')

    def test_exact_overviews_exclude_historical_groups_and_track_unused_maps(self):
        self.renders['renders'][0]['map_sha256']['Icarus_livery_4_m.png'] = 'old unused map'
        self.renders['renders'][12]['map_sha256']['Icarus_skin_m.png'] = 'old unused map'
        review = self.run_sheets()
        self.assertEqual(review['status'], 'complete')
        self.assertEqual(review['counts'], {'manifest_renders': 16, 'rendered': 16,
                                          'missing': 0, 'pages': 4, 'groups': 0})
        self.assertEqual(review['excluded_group_renders'], ['old_closeup.png'])
        self.assertEqual(review['groups'], {})
        self.assertIn('Icarus_livery_4_m.png', review['renders'][0]['changed_unused_maps'])
        self.assertIn('Icarus_skin_m.png', review['renders'][12]['changed_unused_maps'])
        self.assertIn('Icarus_livery_4_m.png', review['renders'][12]['consumed_map_sha256'])

    def test_each_livery_requires_its_consumed_maps_and_alignment(self):
        for index, key in ((0, 'Icarus_skin_m.png'), (12, 'Icarus_livery_4_m.png'),
                           (0, 'Icarus_skin_n.png'), (0, 'Icarus_skin_ao.png'),
                           (12, 'Icarus_livery_4.png'), (0, 'alignment')):
            with self.subTest(index=index, key=key):
                original = copy.deepcopy(self.renders['renders'][index])
                if key == 'alignment':
                    self.renders['renders'][index]['alignment_sha256'] = 'stale'
                else:
                    self.renders['renders'][index]['map_sha256'][key] = 'stale'
                with self.assertRaisesRegex(ValueError, 'stale maps/alignment'):
                    self.run_sheets()
                self.renders['renders'][index] = original

    def test_geometry_and_atlas_inputs_must_be_current(self):
        for path in (self.bake / 'skin.blend', self.bake / 'geometry_maps.npz',
                     self.bake / 'atlas_triangles.json', self.full / 'parts.json'):
            with self.subTest(path=path):
                previous = path.read_bytes()
                path.write_bytes(previous + b'changed')
                with self.assertRaises(ValueError):
                    self.run_sheets()
                path.write_bytes(previous)

    def test_overview_requires_every_unique_view(self):
        self.renders['renders'][0] = copy.deepcopy(self.renders['renders'][1])
        with self.assertRaisesRegex(ValueError, 'exactly 16'):
            self.run_sheets()

    def test_render_png_hash_cannot_be_rebound(self):
        self.renders['renders'][0]['png_sha256'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'PNG hash differs'):
            self.run_sheets()


if __name__ == '__main__':
    unittest.main()
