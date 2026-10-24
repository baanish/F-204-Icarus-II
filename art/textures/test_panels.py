"""The airframe layout keeps panel faces flat and puts fasteners on their rows."""
import unittest

import numpy as np

from panels import FASTENERS, SEAM_HALF_WIDTH, bump, chord_fraction, nearest_line, offset_to_line, row_distance
from panel_checks import plane_deviation
from rasterize import extend_geometry


class LayoutTests(unittest.TestCase):
    def test_offset_is_signed_to_the_nearest_line_with_its_cell(self):
        offset, cell = offset_to_line(np.array([.1, .45, .55, 2.0]), [0, 1])
        np.testing.assert_allclose(offset, [.1, .45, -.45, 1.0])
        self.assertEqual(cell.tolist(), [1, 1, 1, 2])

    def test_faces_between_features_are_exactly_flat(self):
        self.assertEqual(bump(np.array(SEAM_HALF_WIDTH), SEAM_HALF_WIDTH), 0)
        self.assertEqual(bump(np.array(0.), SEAM_HALF_WIDTH), 1)

    def test_a_texel_on_a_line_belongs_to_that_line(self):
        offset, index = nearest_line(np.array([13.0, 12.999, 13.001, 12.3]), [11.8, 13.0, 14.2])
        np.testing.assert_allclose(offset, [0, -.001, .001, .5], atol=1e-9)
        self.assertEqual(index.tolist(), [1, 1, 1, 0])

    def test_constant_chord_fraction_is_a_straight_line(self):
        rng = np.random.default_rng(1)
        span = rng.uniform(0, 2, 20000)
        le, te = .5 * span, 3 - .2 * span
        y = le + rng.uniform(0, 1, len(span)) * (te - le)
        fraction, _ = chord_fraction(span, y)
        on = abs(fraction - .2) < .0005
        fit = np.polyfit(span[on], y[on], 1)
        self.assertLess(abs(np.polyval(fit, span[on]) - y[on]).max(), .003)

    def test_fasteners_sit_on_the_row_at_its_pitch(self):
        pitch = FASTENERS['rivet']['pitch']
        along = np.array([0, pitch / 2, pitch, 3 * pitch])
        distance = row_distance(np.full(4, .015), along, .015, pitch)
        np.testing.assert_allclose(distance, [0, pitch / 2, 0, 0], atol=1e-12)


class StraightnessTests(unittest.TestCase):
    def test_clustered_samples_of_a_plane_measure_within_their_band(self):
        rng = np.random.default_rng(2)
        along = np.concatenate((rng.uniform(0, .5, 120), rng.uniform(1.04, 1.18, 15)))
        across = rng.uniform(-.0005, .0005, len(along))  # the centreline band
        points = np.stack((along, .02 * along ** 2, across), -1) @ np.linalg.qr(rng.normal(size=(3, 3)))[0]
        self.assertLessEqual(plane_deviation(points), .0005)

    def test_a_curved_seam_measures_its_sag(self):
        t = np.linspace(-.6, .6, 200)
        points = np.stack((t, .2 * t * t, .2 * t ** 3), -1)  # a twisted cubic: about 11 mm out of every plane
        self.assertGreater(plane_deviation(points), .01)


class GeometryExtensionTests(unittest.TestCase):
    def test_band_continues_each_island_linearly(self):
        part = np.zeros((12, 12), np.uint8)
        part[3:9, 3:9] = 1
        yy, xx = np.mgrid[:12, :12]
        position = np.stack((xx * .01, yy * .02, np.zeros_like(xx, float)), -1).astype(np.float32)
        position[part == 0] = 0
        normal = np.zeros_like(position)
        normal[..., 2] = 1
        extended, _, extended_part, domain, dx, dy = extend_geometry(position, normal, part, width=2)
        band = domain & (part == 0)
        self.assertTrue(band.any() and np.all(extended_part[band] == 1))
        np.testing.assert_allclose(extended[band][:, 0], xx[band] * .01, atol=1e-6)
        np.testing.assert_allclose(extended[band][:, 1], yy[band] * .02, atol=1e-6)


if __name__ == '__main__':
    unittest.main()
