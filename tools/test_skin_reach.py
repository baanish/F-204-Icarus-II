"""Blender regression checks for hulls.skin_reach: what the visible skin encloses, where it is open, several meshes that
overlap, and a notch whose walls meet every one of a fixed set of rays.

Run with tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/test_skin_reach.py.
"""
import sys
import unittest
from pathlib import Path

import bpy
from mathutils import Vector

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import hulls

# A unit cube's corners (index x + 2y + 4z) and its faces wound outward.
CORNERS = [Vector((i & 1, i >> 1 & 1, i >> 2 & 1)) for i in range(8)]
FACES = [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4), (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]
# The axes and the diagonals: the directions the ray test cast from each corner.
DIRECTIONS = [Vector(d).normalized() for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
              + tuple((a, b, c) for a in (1, -1) for b in (1, -1) for c in (1, -1))]


class SkinReach(unittest.TestCase):
    def setUp(self):
        self.col = bpy.data.collections.new("SkinReachTest")
        bpy.context.scene.collection.children.link(self.col)

    def tearDown(self):
        for o in list(self.col.objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(self.col)

    def mesh(self, verts, faces):
        me = bpy.data.meshes.new("skin")
        me.from_pydata(verts, [], faces)
        self.col.objects.link(bpy.data.objects.new("skin", me))

    def cube(self, low, size):
        self.mesh([Vector(low) + c * size for c in CORNERS], FACES)

    def reach(self, point):
        return hulls.skin_reach(hulls.visible_skin(self.col), [Vector(point)])[0]

    def test_notch_whose_walls_meet_every_ray_is_open(self):
        # a 0.1 m wall 0.2 m out across each direction, facing away: every one of those rays meets a wall, but the
        # gaps between them open the point to the air
        for d in DIRECTIONS:
            u = d.orthogonal().normalized() * 0.05
            v = d.cross(u)
            c = d * 0.2
            self.mesh([c - u - v, c + u - v, c + u + v, c - u + v], [(0, 1, 2, 3)])
        self.assertAlmostEqual(self.reach((0, 0, 0)), 0.2, places=3)

    def test_inside_a_closed_mesh(self):
        self.cube((-0.5, -0.5, -0.5), 1)
        self.assertEqual(self.reach((0.1, -0.2, 0.3)), 0)

    def test_outside_a_closed_mesh(self):
        self.cube((-0.5, -0.5, -0.5), 1)
        self.assertAlmostEqual(self.reach((0.8, 0, 0)), 0.3, places=4)

    def test_overlapping_meshes(self):
        self.cube((0, 0, 0), 1)
        self.cube((0.5, 0, 0), 1)
        self.assertEqual(self.reach((0.75, 0.5, 0.5)), 0)  # inside both
        self.assertEqual(self.reach((1.25, 0.5, 0.5)), 0)  # inside the second only, past the first's face
        self.assertAlmostEqual(self.reach((0.75, 1.2, 0.5)), 0.2, places=4)


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
