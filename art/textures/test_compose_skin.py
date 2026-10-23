"""Surface response measurements compare joints and fasteners with clear panel faces."""
import unittest

import numpy as np

from compose_skin import response_regions


class ResponseRegionTests(unittest.TestCase):
    def test_relief_splits_features_from_clear_faces(self):
        painted = np.array([True, True, True, True, False])
        relief = np.array([0, .005, .3, .8, .9])
        recessed, clear, report = response_regions(painted, relief)
        self.assertEqual(recessed.tolist(), [False, False, False, True, False])
        self.assertEqual(clear.tolist(), [True, True, False, False, False])
        self.assertEqual(report['recessed_texels'], 1)
        self.assertEqual(report['clear_texels'], 2)

    def test_missing_evidence_fails_before_nan_means(self):
        with self.assertRaisesRegex(ValueError, 'Insufficient'):
            response_regions(np.ones(3, bool), np.zeros(3))


if __name__ == '__main__':
    unittest.main()
