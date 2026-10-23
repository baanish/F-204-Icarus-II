"""Native-grid acceptance contracts; run with python -m unittest discover -s art/textures -p test_companion_maps.py."""
import json
import unittest

import numpy as np
from scipy.ndimage import shift

from companion_maps import validate_companion, _match_centres, _islands


def sample_maps(kind='height'):
    base = np.full((192, 224, 3), .14)
    base[16:176, 18:206] = .65
    marks = np.zeros(base.shape[:2], bool)
    marks[47:49, 42:139] = True
    marks[65:132, 156:158] = True
    for y, x in ((76, 61), (108, 88), (140, 129), (143, 53)):
        marks[y:y + 2, x:x + 2] = True
    base[marks] = .22
    companion = np.full(marks.shape, .14 if kind == 'roughness' else 128 / 255)
    companion[16:176, 18:206] = .65 if kind == 'roughness' else 128 / 255
    companion[marks] = .22
    return base, companion, marks


def wider_maps(kind='height'):
    base, companion, _ = sample_maps(kind)
    companion[47:49, 42:139] = .65 if kind == 'roughness' else 128 / 255
    companion[65:132, 156:158] = .65 if kind == 'roughness' else 128 / 255
    companion[45:51, 42:139] = .22
    companion[65:132, 154:160] = .22
    for y, x in ((76, 61), (108, 88), (140, 129), (143, 53)):
        companion[y-2:y+4, x-2:x+4] = .22
    return base, companion


class CompanionMapsTests(unittest.TestCase):
    def test_uv_holes_remain_outside_painted_island_evidence(self):
        candidate = np.zeros((128, 128), bool)
        candidate[16:112, 16:112] = True
        candidate[40:88, 40:88] = False
        islands = _islands(candidate)
        self.assertTrue(islands[20, 64])
        self.assertFalse(islands[64, 64])
        np.testing.assert_array_equal(islands[48:80, 48:80], np.zeros((32, 32), bool))

    def test_exact_congruent_height_and_roughness_pass(self):
        for kind in ('height', 'roughness'):
            with self.subTest(kind=kind):
                base, companion, _ = sample_maps(kind)
                before = companion.copy()
                report = validate_companion(base, companion, kind)
                self.assertTrue(report['accepted'], report['reasons'])
                self.assertEqual(report['precision'], 1.0)
                self.assertEqual(report['recall'], 1.0)
                self.assertEqual(report['position_precision'], 1.0)
                self.assertEqual(report['position_recall'], 1.0)
                self.assertAlmostEqual(report['offset_xy'][0], 0, delta=.05)
                self.assertAlmostEqual(report['offset_xy'][1], 0, delta=.05)
                np.testing.assert_array_equal(companion, before)
                json.dumps(report, allow_nan=False)

    def test_threshold_policy_and_counts_are_pinned(self):
        base, companion, _ = sample_maps()
        report = validate_companion(base, companion, 'height')
        self.assertEqual(report['thresholds']['minimum_precision'], .75)
        self.assertEqual(report['thresholds']['minimum_recall'], .75)
        self.assertEqual(report['thresholds']['boundary_exclusion_px'], 8)
        self.assertEqual(report['thresholds']['feature_tolerance_px'], 1)
        self.assertEqual(report['thresholds']['offset_magnitude_exclusive_px'], 1)
        self.assertEqual(report['thresholds']['offset_guard_band_px'], .10)
        self.assertEqual(report['counts']['base_components'], 6)
        self.assertEqual(report['counts']['base_pixels'], 712)
        self.assertEqual(report['counts']['base_positions'], 332)
        self.assertEqual(report['counts']['matched_base_positions'], 332)
        self.assertEqual(report['position_precision'], 1)
        self.assertEqual(report['position_recall'], 1)
        self.assertEqual(report['groups']['fasteners']['counts']['base_components'], 4)
        self.assertEqual(report['thresholds']['minimum_seam_pixels'], 32)
        self.assertEqual(report['thresholds']['minimum_fastener_components'], 3)
        self.assertEqual(report['thresholds']['feature_prefilter_sigma_px'], .8)
        self.assertEqual(report['thresholds']['minimum_component_pixels'], 4)
        self.assertEqual(report['thresholds']['maximum_fastener_span_px'], 12)

    def test_two_pixel_displacement_fails_with_correct_sign(self):
        base, companion, _ = sample_maps()
        for dy, dx in ((0, 2), (-2, 0), (2, -2)):
            with self.subTest(dy=dy, dx=dx):
                moved = shift(companion, (dy, dx), order=1, mode='constant', cval=128 / 255)
                report = validate_companion(base, moved, 'height')
                self.assertFalse(report['accepted'])
                np.testing.assert_allclose(report['offset_xy'], [dx, dy], atol=.06)
                self.assertIn('global offset must be less than one native texel', report['reasons'])

    def test_same_centre_wider_strokes_and_fasteners_pass(self):
        for kind in ('height', 'roughness'):
            base, companion = wider_maps(kind)
            report = validate_companion(base, companion, kind)
            self.assertTrue(report['accepted'], report['reasons'])
            self.assertLess(report['groups']['fasteners']['precision'], .75)
            self.assertGreaterEqual(report['position_precision'], .75)
            self.assertGreaterEqual(report['position_recall'], .75)
            self.assertEqual(report['groups']['fasteners']['position_precision'], 1)
            self.assertEqual(report['groups']['fasteners']['position_recall'], 1)
            self.assertEqual(report['groups']['fasteners']['counts']['matched_base_positions'], 4)

    def test_two_pixel_shift_of_wider_strokes_still_fails(self):
        base, companion = wider_maps()
        moved = shift(companion, (2, 2), order=1, mode='constant', cval=128/255)
        report = validate_companion(base, moved, 'height')
        self.assertFalse(report['accepted'])
        self.assertLess(report['groups']['seams']['position_precision'], .75)
        self.assertEqual(report['groups']['fasteners']['position_precision'], 0)

    def test_displaced_rivet_centre_fails_while_global_offset_stays_small(self):
        base, companion, _ = sample_maps()
        companion[76:78, 61:63] = 128/255
        companion[76:78, 63:65] = .22
        report = validate_companion(base, companion, 'height')
        self.assertFalse(report['accepted'])
        self.assertLess(report['offset_magnitude'], .1)
        self.assertEqual(report['groups']['fasteners']['position_precision'], .75)
        self.assertEqual(report['groups']['fasteners']['position_recall'], .75)
        self.assertEqual(report['groups']['fasteners']['counts']['matched_base_positions'], 3)
        self.assertTrue(any('missing or misplaced' in reason for reason in report['reasons']))

    def test_fastener_matching_is_one_to_one_and_maximizes_valid_pairs(self):
        reference = np.array([[0., 0.], [1.5, 0.], [20., 0.]])
        moving = np.array([[.75, 0.], [20., 0.]])
        matches = _match_centres(reference, moving)
        self.assertEqual(len(matches), 2)
        self.assertEqual(len({pair[1] for pair in matches}), 2)
        matches = _match_centres(reference[:2], np.array([[.75, 0.], [-.9, 0.]]))
        self.assertEqual(len(matches), 2)
        self.assertEqual({(i,j) for i,j,_ in matches}, {(0,1),(1,0)})

    def test_fractional_displacements_and_radial_cutoff(self):
        base, companion, _ = sample_maps()
        for dy, dx, accepted in ((0, .35, True), (-.4, .3, True), (.8, .8, False), (0, 1.2, False)):
            with self.subTest(dy=dy, dx=dx):
                moved = shift(companion, (dy, dx), order=1, mode='constant', cval=128 / 255)
                report = validate_companion(base, moved, 'height')
                np.testing.assert_allclose(report['offset_xy'], [dx, dy], atol=.12)
                self.assertEqual(report['accepted'], accepted, report['reasons'])

    def test_exactly_one_texel_and_near_limit_reject_in_every_direction(self):
        base, companion, _ = sample_maps()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (0, .97)):
            with self.subTest(dy=dy, dx=dx):
                moved = shift(companion, (dy, dx), order=1, mode='constant', cval=128 / 255)
                report = validate_companion(base, moved, 'height')
                self.assertFalse(report['accepted'])
                self.assertTrue(any('global offset' in reason for reason in report['reasons']))

    def test_missing_and_hallucinated_features_fail_even_when_combined_score_is_high(self):
        base, companion, _ = sample_maps()
        missing = companion.copy()
        missing[76:78, 61:63] = 128 / 255
        hallucinated = companion.copy()
        hallucinated[118:120, 119:121] = .22
        for candidate in (missing, hallucinated):
            report = validate_companion(base, candidate, 'height')
            self.assertFalse(report['accepted'])
            self.assertGreater(report['precision'], .75)
            self.assertGreater(report['recall'], .75)
            self.assertTrue(any('feature' in reason for reason in report['reasons']))

    def test_missing_seams_fail(self):
        base, companion, _ = sample_maps()
        companion[47:49, 42:139] = 128 / 255
        report = validate_companion(base, companion, 'height')
        self.assertFalse(report['accepted'])
        self.assertLess(report['groups']['seams']['recall'], .75)

    def test_seams_alone_do_not_substitute_for_fastener_evidence(self):
        base, companion, _ = sample_maps()
        for y, x in ((76, 61), (108, 88), (140, 129), (143, 53)):
            base[y:y + 2, x:x + 2] = .65
            companion[y:y + 2, x:x + 2] = 128 / 255
        report = validate_companion(base, companion, 'height')
        self.assertFalse(report['accepted'])
        self.assertEqual(report['precision'], 1)
        self.assertEqual(report['recall'], 1)
        self.assertIn('insufficient base fasteners components', report['reasons'])

    def test_roughness_fractional_and_two_pixel_offsets(self):
        base, companion, _ = sample_maps('roughness')
        for dx, accepted in ((.4, True), (-2, False)):
            moved = shift(companion, (0, dx), order=1, mode='constant', cval=.14)
            report = validate_companion(base, moved, 'roughness')
            self.assertEqual(report['accepted'], accepted, report['reasons'])
            np.testing.assert_allclose(report['offset_xy'], [dx, 0], atol=.12)

    def test_featureless_painted_base_rejects(self):
        base, companion, _ = sample_maps()
        base[16:176, 18:206] = .65
        self.assertFalse(validate_companion(base, companion, 'height')['accepted'])

    def test_dimension_mismatch_is_not_resized(self):
        base, companion, _ = sample_maps()
        report = validate_companion(base, companion[::2, ::2], 'height')
        self.assertFalse(report['accepted'])
        self.assertIsNone(report['offset_xy'])
        self.assertIn('native dimensions differ; resizing is forbidden', report['reasons'])

    def test_constant_noise_and_outline_only_reject(self):
        base, _, _ = sample_maps()
        outline = np.full(base.shape[:2], .14)
        outline[16:176, 18:206] = .8
        outline[19:173, 21:203] = 128 / 255
        rng = np.random.default_rng(17)
        for kind in ('height', 'roughness'):
            for candidate in (np.full(base.shape[:2], 128 / 255), outline,
                              rng.uniform(.15, .85, base.shape[:2])):
                with self.subTest(kind=kind):
                    self.assertFalse(validate_companion(base, candidate, kind)['accepted'])

    def test_roughness_requires_same_silhouette(self):
        base, companion, _ = sample_maps('roughness')
        companion[16:176, 180:206] = .14
        report = validate_companion(base, companion, 'roughness')
        self.assertFalse(report['accepted'])
        self.assertLess(report['silhouette_iou'], .95)

    def test_boundary_marks_are_excluded(self):
        base, companion, _ = sample_maps()
        companion[17:23, 20:204] = .1
        report = validate_companion(base, companion, 'height')
        self.assertTrue(report['accepted'], report['reasons'])
        self.assertEqual(report['precision'], 1)

    def test_grey_background_is_not_an_island(self):
        _, companion, _ = sample_maps()
        report = validate_companion(np.full((192, 224, 3), .5), companion, 'height')
        self.assertFalse(report['accepted'])
        self.assertEqual(report['counts']['interior_pixels'], 0)

    def test_rgb_companion_and_raised_marks(self):
        base, companion, marks = sample_maps()
        companion[marks] = .82
        report = validate_companion(base, np.repeat(companion[..., None], 3, axis=2), 'height')
        self.assertTrue(report['accepted'], report['reasons'])

    def test_single_pixel_paint_grain_is_not_fastener_evidence(self):
        base, companion, _ = sample_maps()
        # These isolated dark grains exceeded the old .045 residual threshold.
        for y in range(59, 150, 9):
            for x in range(39, 146, 9):
                if np.all(base[y-2:y+3, x-2:x+3] == .65):
                    base[y, x] = .55
        report = validate_companion(base, companion, 'height')
        self.assertTrue(report['accepted'], report['reasons'])
        self.assertEqual(report['groups']['fasteners']['counts']['base_components'], 4)
        self.assertEqual(report['groups']['seams']['counts']['base_components'], 2)

    def test_offset_grey_plane_is_not_structural_height(self):
        base, companion, marks = sample_maps()
        companion[:] = .55
        companion[marks] = .22
        report = validate_companion(base, companion, 'height')
        self.assertTrue(report['accepted'], report['reasons'])
        self.assertEqual(report['height_plane_median'], .55)
        self.assertAlmostEqual(report['height_plane_offset_from_flush'], .55 - 128/255)
        self.assertEqual(report['groups']['fasteners']['counts']['companion_components'], 4)
        self.assertEqual(report['groups']['seams']['counts']['companion_components'], 2)
        self.assertEqual(report['precision'], 1)

    def test_white_raised_core_and_dark_rim_are_one_fastener(self):
        base, companion, _ = sample_maps()
        yy, xx = np.indices(companion.shape)
        for y, x in ((76, 61), (108, 88), (140, 129), (143, 53)):
            radius = np.hypot(xx - x, yy - y)
            local = radius <= 4
            ring = (radius >= 2) & (radius <= 3.5)
            core = radius <= 1.5
            base[local] = .65
            base[ring] = .22
            companion[local] = .55
            companion[ring] = .22
            companion[core] = .9
        report = validate_companion(base, companion, 'height')
        self.assertTrue(report['accepted'], report['reasons'])
        self.assertEqual(report['groups']['fasteners']['counts']['base_components'], 4)
        self.assertEqual(report['groups']['fasteners']['counts']['companion_components'], 4)

    def test_invalid_arrays_reject_with_json_safe_reports(self):
        base, companion, _ = sample_maps()
        invalid = companion.copy()
        invalid[40, 40] = np.nan
        for candidate, kind in ((invalid, 'height'), (companion * 256, 'height'),
                                (companion.astype(np.uint8), 'height'), (companion, 'normal')):
            report = validate_companion(base, candidate, kind)
            self.assertFalse(report['accepted'])
            json.dumps(report, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
