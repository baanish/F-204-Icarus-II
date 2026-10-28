"""Exact mesh distances must keep face, edge and crossing minima when pruning pairs."""
import unittest
from unittest.mock import patch

import numpy as np

from stores.geometry import axis_quat, mesh_distance, quat_matrix, turn_upright


class MeshDistance(unittest.TestCase):
    def mesh(self, points):
        return np.asarray(points, float), np.array([[0, 1, 2]])

    def test_vertex_to_face(self):
        a = self.mesh([[0, 0, 0], [2, 0, 0], [0, 2, 0]])
        b = self.mesh([[0.25, 0.25, 0.125], [0.5, 0.25, 1], [0.25, 0.5, 1]])
        self.assertEqual(mesh_distance(a, b, 1), 0.125)
        self.assertEqual(mesh_distance(b, a, 1), 0.125)
        self.assertEqual(mesh_distance(a, b, 0.125), 0.125)

    def test_edge_interiors(self):
        a = self.mesh([[-1, 0, 0], [1, 0, 0], [0, -1, 0]])
        b = self.mesh([[0, 0.25, -1], [0, 0.25, 1], [0, 1, 0]])
        self.assertEqual(mesh_distance(a, b, 1), 0.25)
        self.assertEqual(mesh_distance(b, a, 1), 0.25)

    def test_crossing_without_vertex_contact(self):
        a = self.mesh([[-1, 0, 0], [1, 0, 0], [0, -1, 0]])
        b = self.mesh([[0, -0.25, -1], [0, -0.25, 1], [0, 1, 0]])
        self.assertEqual(mesh_distance(a, b, 1), 0.0)
        self.assertEqual(mesh_distance(b, a, 1), 0.0)

    def test_coplanar_and_degenerate(self):
        a = self.mesh([[0, 0, 0], [2, 0, 0], [0, 2, 0]])
        b = self.mesh([[0.25, 0.25, 0], [0.5, 0.25, 0], [0.25, 0.5, 0]])
        self.assertEqual(mesh_distance(a, b, 1), 0.0)
        self.assertEqual(mesh_distance(a, self.mesh([[0, 0, 0]] * 3), 1), 1)

    def test_distant_boxes_return_gap(self):
        a = self.mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        b = self.mesh([[0, 0, 2], [1, 0, 2], [0, 1, 2]])
        self.assertEqual(mesh_distance(a, b, 0.5), 2.0)

    def test_minimum_in_later_chunk(self):
        a = self.mesh([[0, 0, 0], [2, 0, 0], [0, 2, 0]])
        b = (np.array([[0, 0, 1], [2, 0, 1], [0, 2, 1],
                       [0, 0, 0.125], [2, 0, 0.125], [0, 2, 0.125]]),
             np.array([[0, 1, 2], [3, 4, 5]]))
        with patch("stores.geometry.CHUNK", 2):
            self.assertEqual(mesh_distance(a, b, 2), 0.125)


KEY = "baanish_icarus_tip_tank"


class TurnUpright(unittest.TestCase):
    """A store hung upside down is turned half a roll about its own forward axis, as the plugin does on the right tank."""

    def store(self, roll):
        verts = np.array([[0, 0.4, 0], [0, 0, 1.0], [0.2, 0, -1.0]])
        capsule = dict(kind="Capsule", trigger=False, centre=(0.0, 0.0, 0.0), rot=axis_quat((0, 0, 1), roll), axis=2)
        return (verts, np.array([[0, 1, 2]])), [capsule]

    def test_upside_down_store_turns_about_its_axis(self):
        mount = self.store(180.0)
        (turned, _), _ = turn_upright(KEY, mount, np.eye(3))
        np.testing.assert_allclose(turned, [[0, -0.4, 0], [0, 0, 1.0], [-0.2, 0, -1.0]], atol=1e-9)

    def test_upright_store_is_left_alone(self):
        mount = self.store(0.0)
        self.assertIs(turn_upright(KEY, mount, np.eye(3)), mount)

    def test_hardpoint_rotation_decides(self):
        mount = self.store(0.0)
        half_roll = quat_matrix(axis_quat((0, 0, 1), 180.0))
        self.assertIsNot(turn_upright(KEY, mount, half_roll), mount)
        self.assertIs(turn_upright("AAM1_double", mount, half_roll), mount)


if __name__ == "__main__":
    unittest.main()
