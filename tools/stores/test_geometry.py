"""Exact mesh distances must keep face, edge and crossing minima when pruning pairs."""
import unittest
from unittest.mock import patch

import numpy as np

from stores.geometry import mesh_distance


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


if __name__ == "__main__":
    unittest.main()
