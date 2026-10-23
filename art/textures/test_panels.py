"""The airframe layout keeps panel faces flat and puts fasteners on their rows."""
import unittest

import numpy as np

from panels import FASTENERS, SEAM_HALF_WIDTH, bump, offset_to_line, row_distance
from rasterize import extend_geometry


class LayoutTests(unittest.TestCase):
    def test_offset_is_signed_to_the_nearest_line_with_its_cell(self):
        offset, cell = offset_to_line(np.array([.1, .45, .55, 2.0]), [0, 1])
        np.testing.assert_allclose(offset, [.1, .45, -.45, 1.0])
        self.assertEqual(cell.tolist(), [1, 1, 1, 2])

    def test_faces_between_features_are_exactly_flat(self):
        self.assertEqual(bump(np.array(SEAM_HALF_WIDTH), SEAM_HALF_WIDTH), 0)
        self.assertEqual(bump(np.array(0.), SEAM_HALF_WIDTH), 1)

    def test_fasteners_sit_on_the_row_at_its_pitch(self):
        pitch = FASTENERS['rivet']['pitch']
        along = np.array([0, pitch / 2, pitch, 3 * pitch])
        distance = row_distance(np.full(4, .015), along, .015, pitch)
        np.testing.assert_allclose(distance, [0, pitch / 2, 0, 0], atol=1e-12)


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
