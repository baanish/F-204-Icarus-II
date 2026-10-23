import unittest

import numpy as np

from bare_metal import finish, visibility_bands, surface_map


class BareMetalTests(unittest.TestCase):
    def fields(self):
        yy, xx = np.mgrid[:64, :64]
        position = np.stack((xx / 32, yy / 32, np.zeros_like(xx)), axis=-1)
        normal = np.zeros_like(position)
        normal[..., 2] = 1
        colour = np.full_like(position, .46)
        panel = np.where(xx < 32, 1, 2)
        return colour, position, normal, panel, np.ones((64, 64), bool)

    def test_structural_panels_get_their_own_sheet_tone(self):
        result, tone, report = finish(*self.fields())
        self.assertEqual(report['panels'], 2)
        self.assertEqual(len(np.unique(tone[:, :32])), 1)
        self.assertNotEqual(float(tone[24, 16]), float(tone[24, 48]))
        self.assertGreater(abs(float(result[24, 16, 0] - result[24, 48, 0])), .01)

    def test_bands_preserve_input(self):
        fields = list(self.fields())
        fields[1][..., 1] = -2.4
        result, _, _ = finish(*fields)
        np.testing.assert_array_equal(result, fields[0])
        np.testing.assert_array_equal(visibility_bands(np.array([[0., -2.4, 0.], [0., 4.55, 0.]])), [1, 1])

    def test_aft_staining_and_mirror_policy(self):
        fields = list(self.fields())
        fields[1][..., 1] += 6
        aft, _, _ = finish(*fields)
        self.assertLess(float(aft.mean()), .46 * .9)
        fields[1][..., 0] *= -1
        reflected, _, _ = finish(*fields)
        np.testing.assert_array_equal(aft, reflected)

    def test_material_masks_and_protected_fields(self):
        names = ['skin_forward_L', 'radome', 'nozzle']
        part = np.array([[1, 1, 1, 1, 2, 1, 3, 1]])
        position = np.zeros((1, 8, 3))
        position[0, 2, 1] = -2.4
        position[0, 3, 1] = -6.8
        normal = np.zeros_like(position)
        normal[..., 2] = 1
        shared = np.zeros((1, 8, 4))
        shared[..., 3] = .6
        shared[0, [5, 7], 0] = 1
        decal = np.zeros((1, 8))
        decal[0, [1, 7]] = 1
        result, masks = surface_map(shared, position, normal, part, names, decal, np.zeros(part.shape), np.zeros(part.shape))
        np.testing.assert_allclose(result[0, :, 0], [.98, 0, 0, 0, 0, 1, 0, 0])
        np.testing.assert_allclose(result[0, :, 3], [.90, .42, .42, .18, .42, .6, .6, .42])
        np.testing.assert_array_equal(result[0, 5], shared[0, 5])
        np.testing.assert_array_equal(result[0, 6], shared[0, 6])
        self.assertEqual(float(masks['anti_glare'][0, 3]), 1.)

    def test_partial_decal_alpha_blends_metal_response_exactly(self):
        shared = np.array([[[0., 0., 0., .4]]])
        position = np.zeros((1, 1, 3))
        result, _ = surface_map(shared, position, position, np.ones((1, 1), int),
                                ['skin_forward_L'], np.full((1, 1), .5), np.zeros((1, 1)), np.zeros((1, 1)))
        np.testing.assert_allclose(result[0, 0], [.49, 0, 0, .66])
        position[..., 1] = -2.0525
        result, masks = surface_map(shared, position, np.zeros_like(position), np.ones((1, 1), int),
                                    ['skin_forward_L'], np.full((1, 1), .5), np.zeros((1, 1)), np.zeros((1, 1)))
        np.testing.assert_allclose(masks['paint'], .75)
        np.testing.assert_allclose(result[0, 0], [.245, 0, 0, .54])


if __name__ == '__main__':
    unittest.main()
