"""Rule 14 must reject a lens contained in an envelope as well as a surface crossing."""
import contextlib
import io
import unittest

import numpy as np

from stores.lights import check_tip_lamps


class TipLampClearance(unittest.TestCase):
    def check_gap(self, x, colliders=()):
        lamp = (np.array([[x, 0, 0], [x, 0.01, 0], [x, 0, 0.01]]), np.array([[0, 1, 2]]))
        store = (np.array([[0, -1, -1], [0, 1, -1], [0, 0, 1]]), np.array([[0, 1, 2]]))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = check_tip_lamps([("tip", np.zeros(3), np.eye(3))], [("lamp", lamp)],
                                     {"store": (store, colliders)})
        return result, output.getvalue()

    def test_rendered_envelope_gap(self):
        passed, output = self.check_gap(0.05)
        self.assertTrue(passed)
        self.assertIn("least envelope gap 0.050000 m", output)
        self.assertFalse(self.check_gap(0)[0])

    def test_lens_inside_capsule(self):
        cap = {"kind": "Capsule", "centre": (0, 0, 0), "rot": (0, 0, 0, 1),
               "axis": 2, "half_len": 1, "r": 0.1, "trigger": False}
        passed, output = self.check_gap(0.05, [cap])
        self.assertFalse(passed)
        self.assertIn("least envelope gap -0.050000 m", output)
        self.assertTrue(self.check_gap(0.05, [dict(cap, trigger=True)])[0])

    def test_lens_inside_box(self):
        box = {"kind": "Box", "centre": (0, 0, 0), "rot": (0, 0, 0, 1),
               "half": (0.1, 1, 1), "trigger": False}
        self.assertFalse(self.check_gap(0.05, [box])[0])


if __name__ == "__main__":
    unittest.main()
