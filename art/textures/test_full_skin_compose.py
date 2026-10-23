"""Registration, transfer and maintained-skin policy contracts."""
import json
import hashlib
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

import numpy as np
from PIL import Image

from full_skin_compose import _chart_registration, assemble_full, source_charts
from full_skin_registration import check_sources


class FullSkinComposeTests(unittest.TestCase):
    def test_explicit_stitch_layout_keeps_disconnected_chart_pixels(self):
        base = np.zeros((64, 64, 3), np.float32)
        base[10:20, 4:25] = .5
        base[10:20, 35:56] = .5
        layout = {'charts': [{'target_box': [4, 10, 56, 20]}]}
        labels, candidates = source_charts(base, 1, layout)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][1], (slice(10, 20), slice(4, 56)))
        self.assertEqual(candidates[0][2], 420)
        self.assertEqual(int((labels == 1).sum()), 420)

    def setUp(self):
        self.root = (Path(__file__).resolve().parents[2] /
                     '.cache/review/wave2/p9b-round2/full/registration_diagnostics' /
                     ('full-compose-test-' + uuid.uuid4().hex))
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.full = self.root / 'full'
        self.full.mkdir()
        self.generated = self.root / 'generated'
        self.generated.mkdir()
        self.shape = (32, 32)
        self.mask = np.zeros(self.shape, bool)
        self.mask[2:18, 3:19] = True
        self.save(self.full / 'part.mask.png', self.mask.astype('uint8') * 255)
        # A deliberate canvas offset belongs to every field, with no corrective warp.
        y, x = np.mgrid[:64, :64]
        field = (120 + x + y).astype('uint8')
        base = np.zeros((64, 64, 3), 'uint8')
        base[13:45, 19:51] = field[13:45, 19:51, None]
        self.save(self.generated / 'base.png', base)
        height = np.full((64, 64), 128, 'uint8')
        height[13:45, 19:51] = field[13:45, 19:51]
        self.save(self.generated / 'part_height.png', height)
        self.save(self.generated / 'part_roughness.png', height)
        target = np.array([22 * 32 + 24, 22 * 32 + 25])
        source = np.array([5 * 32 + 7, 7 * 32 + 9])
        np.savez(self.full / 'mirror.npz', target_indices=target, source_indices=source)
        np.savez(self.full / 'rotation.npz', target_indices=target + 32,
                 source_indices=target[::-1])
        self.write(self.full / 'coverage.json', {'rules': [
            {'name': 'mirror', 'mode': 'world_mirror_x', 'map': 'mirror.npz'},
            {'name': 'rotation', 'mode': 'world_rotation_y', 'map': 'rotation.npz'},
        ], 'assigned_texels': int(self.mask.sum()) + 4})
        self.manifest = {'atlas_size': 32, 'companion_dir': str(self.generated),
                         'groups': {'part': {'mask': 'part.mask.png',
                            'source_path': str(self.generated / 'base.png'),
                            'charts': [{'component': 1, 'atlas_box': [3, 2, 19, 18],
                                        'guide_box': [0, 0, 32, 32], 'rotate_ccw': False}]}}}
        self.path = self.full / 'parts.json'
        self.write(self.path, self.manifest)

    def save(self, path, array):
        Image.fromarray(array).save(path)

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def assemble(self, validator=None):
        if validator is None:
            validator = lambda *args: {'accepted': True, 'offset_xy': [0., 0.]}
        with patch('full_skin_compose.validate_companion', side_effect=validator):
            return assemble_full(self.path)

    def test_repacked_atlas_registers_native_source_before_shared_remap(self):
        current = self.full / 'current.json'
        self.write(current, {'source_atlas_manifest': self.path.name,
                             'input_sha256': {self.path.name: hashlib.sha256(self.path.read_bytes()).hexdigest()}})
        with patch('full_skin_compose.validate_companion', return_value={'accepted': True}), \
                patch('source_atlas_mapping.remap_fields', side_effect=lambda fields, path: fields) as remap:
            result = assemble_full(current)
        remap.assert_called_once()
        self.assertEqual(remap.call_args.args[1], current)
        self.assertEqual(int(result['used'].sum()), int(self.mask.sum()) + 4)
        self.assertEqual(check_sources(current)['part']['status'], 'passed')

    def test_repacked_inventory_hash_fails_before_source_or_remap(self):
        current = self.full / 'current.json'
        self.write(current, {'source_atlas_manifest': self.path.name,
                             'input_sha256': {self.path.name: 'not-the-native-hash'}})
        with patch('source_atlas_mapping.remap_fields') as remap:
            with self.assertRaisesRegex(ValueError, 'Stale part inventory'):
                assemble_full(current)
        remap.assert_not_called()

    def test_offset_sampling_and_ordered_transfers_use_one_registration(self):
        result = self.assemble()
        # Target [5,7] maps to native x=27.71875, y=19.78125.
        self.assertAlmostEqual(result['base'][5, 7, 0], 167.5 / 255, places=6)
        np.testing.assert_allclose(result['height'][self.mask], result['base'][self.mask, 0])
        np.testing.assert_allclose(result['roughness'][self.mask], result['height'][self.mask])
        for key in ('base', 'height', 'roughness', 'height_valid', 'roughness_valid'):
            np.testing.assert_array_equal(result[key][22, 24:26], result[key][[5, 7], [7, 9]])
            np.testing.assert_array_equal(result[key][23, 24:26], result[key][22, [25, 24]])
        self.assertTrue(np.all(result['base'][~result['used']] == 0))
        self.assertEqual(result['report']['assigned_texels'], 260)
        self.assertTrue((self.full / 'alignment.json').exists())
        self.assertTrue((self.full / 'stitch.json').exists())
        self.assertTrue((self.full / 'assembled.png').exists())
        json.dumps(result['report'], allow_nan=False)

    def test_rotation_keeps_height_and_base_at_exact_same_native_positions(self):
        self.manifest['groups']['part']['charts'][0]['rotate_ccw'] = True
        self.write(self.path, self.manifest)
        result = self.assemble()
        self.assertAlmostEqual(result['height'][5, 7], 181.0625 / 255, places=6)
        np.testing.assert_allclose(result['height'][self.mask], result['base'][self.mask, 0])

    def test_same_guide_row_matches_positions_despite_top_pixel_jitter(self):
        # Identical shapes cannot disambiguate this pair. The right component
        # starts one pixel higher, reversing the source detector's row order.
        base = np.zeros((96, 96, 3), 'uint8')
        base[13:45, 8:40] = 150
        base[12:44, 54:86] = 210
        self.save(self.generated / 'base.png', base)
        self.save(self.generated / 'part_height.png', base[..., 0])
        self.save(self.generated / 'part_roughness.png', base[..., 0])
        self.mask[:] = False
        self.mask[2:18, 3:19] = True
        self.mask[20:28, 3:11] = True
        self.save(self.full / 'part.mask.png', self.mask.astype('uint8') * 255)
        self.manifest['guide_size'] = 96
        self.manifest['groups']['part']['charts'] = [
            {'component': 1, 'atlas_box': [3, 2, 19, 18], 'guide_box': [8, 12, 40, 44]},
            {'component': 2, 'atlas_box': [3, 20, 11, 28], 'guide_box': [54, 12, 86, 44]}]
        self.write(self.path, self.manifest)
        self.write(self.full / 'coverage.json', {'rules': [], 'assigned_texels': 320})
        result = self.assemble()
        registrations = result['report']['groups']['part']['registration']
        self.assertEqual([c['source_box'] for c in registrations], [[8, 13, 40, 45], [54, 12, 86, 44]])
        self.assertEqual([c['normalized_silhouette_iou'] for c in registrations], [1., 1.])
        self.assertEqual([c['native_px_per_m_min_axis'] for c in registrations], [300., 600.])
        self.assertAlmostEqual(result['base'][5, 7, 0], 150 / 255, places=6)
        self.assertAlmostEqual(result['base'][22, 7, 0], 210 / 255, places=6)
        for kind in ('height', 'roughness'):
            np.testing.assert_allclose(result[kind][self.mask], result['base'][self.mask, 0])
        preflight = check_sources(self.path)
        self.assertEqual(preflight['part']['status'], 'passed')
        self.assertEqual([c['source_box'] for c in preflight['part']['charts']],
                         [c['source_box'] for c in registrations])

    def test_overlapping_chart_rectangles_use_only_their_own_masks(self):
        chart_mask = self.mask.copy()
        chart_mask[10:18, 11:19] = False
        self.save(self.full / 'chart.mask.png', chart_mask.astype('uint8') * 255)
        chart = dict(self.manifest['groups']['part']['charts'][0], mask='chart.mask.png')
        labels = np.zeros((64, 64), int)
        labels[13:45, 19:51] = 1
        labels[29:45, 35:51] = 2
        selected, _, _, _, evidence = _chart_registration(
            'part', chart, 1, (slice(13, 45), slice(19, 51)), labels, self.mask, self.full)
        np.testing.assert_array_equal(selected, chart_mask[2:18, 3:19])
        self.assertEqual(evidence['normalized_silhouette_iou'], 1.)
        self.assertEqual(evidence['selected_texels'], 192)

    def test_annular_source_preserves_uv_hole_in_assembly_and_preflight(self):
        y, x = np.mgrid[:16, :16]
        radius = np.hypot(x - 7.5, y - 7.5)
        ring = (radius <= 7.6) & (radius >= 6.5)
        self.mask[:] = False
        self.mask[2:18, 3:19] = ring
        self.save(self.full / 'part.mask.png', self.mask.astype('uint8') * 255)
        base = np.zeros((96, 96, 3), 'uint8')
        base[13:77, 19:83] = np.repeat(np.repeat(ring, 4, axis=0), 4, axis=1)[..., None] * 180
        self.save(self.generated / 'base.png', base)
        for kind in ('height', 'roughness'):
            self.save(self.generated / f'part_{kind}.png', base[..., 0])
        self.write(self.full / 'coverage.json', {'rules': [], 'assigned_texels': int(ring.sum())})
        result = self.assemble()
        evidence = result['report']['groups']['part']['registration'][0]
        self.assertEqual(evidence['normalized_silhouette_iou'], .875)
        self.assertEqual(evidence['native_px_per_m_min_axis'], 600.)
        self.assertEqual(evidence['selected_texels'], 56)
        self.assertFalse(result['used'][9, 10])
        self.assertTrue(np.all(result['base'][~self.mask] == 0))
        preflight = check_sources(self.path)
        self.assertEqual(preflight['part']['status'], 'passed')
        self.assertEqual(preflight['part']['charts'][0]['normalized_silhouette_iou'], .875)

    def test_rejected_companion_retains_native_metrics_and_uses_base_fallback(self):
        def validator(base, companion, kind):
            return {'accepted': kind == 'roughness', 'offset_xy': [2., 0.],
                    'precision': .5, 'reasons': ['misplaced']}
        result = self.assemble(validator)
        self.assertFalse(result['height_valid'].any())
        self.assertTrue(result['roughness_valid'][22, 24])
        report = result['report']['groups']['part']['companions']['height']
        self.assertEqual(report['status'], 'fallback')
        self.assertEqual(report['validation']['offset_xy'], [2., 0.])
        self.assertGreater(result['base'][5, 7, 0], 0)

    def test_explicit_generation_failure_falls_back_but_incomplete_generation_fails(self):
        (self.generated / 'part_height.png').unlink()
        with self.assertRaisesRegex(ValueError, 'generation.*record'):
            self.assemble()
        self.write(self.full / 'part_height.generation.json',
                   {'accepted': False, 'output': None, 'generation_error': 'image tool unavailable'})
        result = self.assemble()
        self.assertFalse(result['height_valid'].any())
        report = result['report']['groups']['part']['companions']['height']
        self.assertEqual(report['generation']['generation_error'], 'image tool unavailable')
        self.assertEqual(report['status'], 'fallback')

    def test_native_mismatch_is_rejected_without_resizing_or_validator(self):
        self.save(self.generated / 'part_height.png', np.full((48, 48), 128, 'uint8'))
        calls = []
        result = self.assemble(lambda b, c, k: calls.append(k) or {'accepted': True})
        self.assertEqual(calls, ['roughness'])
        self.assertFalse(result['height_valid'].any())
        self.assertIn('native dimensions differ', str(result['report']))

    def test_group_mask_crop_excludes_unpainted_chart_corners(self):
        self.mask[2:9, 3:10] = False
        self.save(self.full / 'part.mask.png', self.mask.astype('uint8') * 255)
        image = np.array(Image.open(self.generated / 'base.png'))
        image[13:27, 19:33] = 0
        self.save(self.generated / 'base.png', image)
        coverage = json.loads((self.full / 'coverage.json').read_text())
        coverage['assigned_texels'] = int(self.mask.sum())
        coverage['rules'] = []
        self.write(self.full / 'coverage.json', coverage)
        result = self.assemble()
        self.assertTrue(np.all(result['base'][2:9, 3:10] == 0))
        self.assertFalse(result['height_valid'][2:9, 3:10].any())
        self.assertGreater(result['report']['groups']['part']['registration'][0]['normalized_silhouette_iou'], .7)

    def test_explicit_chart_mask_cannot_select_another_groups_paint(self):
        chart_mask = self.mask.copy()
        chart_mask[20, 20] = True
        self.save(self.full / 'chart.mask.png', chart_mask.astype('uint8') * 255)
        self.manifest['groups']['part']['charts'][0]['mask'] = 'chart.mask.png'
        self.write(self.path, self.manifest)
        with self.assertRaisesRegex(ValueError, 'subset'):
            self.assemble()

    def test_density_and_chart_count_fail_concretely(self):
        self.manifest['groups']['part']['charts'][0]['atlas_box'] = [0, 0, 32, 32]
        self.write(self.path, self.manifest)
        with self.assertRaisesRegex(ValueError, '180'):
            self.assemble()
        self.manifest['groups']['part']['charts'] *= 2
        self.write(self.path, self.manifest)
        with self.assertRaisesRegex(ValueError, 'silhouettes'):
            self.assemble()

    def test_silhouette_layout_mismatch_fails_at_declared_threshold(self):
        self.mask[2:14, 3:15] = False
        self.save(self.full / 'part.mask.png', self.mask.astype('uint8') * 255)
        with self.assertRaisesRegex(ValueError, 'IoU .* below 0.70'):
            self.assemble()


if __name__ == '__main__':
    unittest.main()
