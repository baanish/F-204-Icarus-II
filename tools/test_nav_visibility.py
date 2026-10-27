"""Blender regression checks for the visibility grid, paired lamps and occlusion.

Run with tools/Run-Blender.ps1 --background --factory-startup
--python-exit-code 1 --python tools/test_nav_visibility.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import nav_visibility as nv


class NavVisibility(unittest.TestCase):
    def test_aft_sector_at_every_stabilator_pose(self):
        collection = bpy.data.collections.new("AftVisibilityTest")
        bpy.context.scene.collection.children.link(collection)
        hinge = bpy.data.objects.new("stabilator", None)
        collection.objects.link(hinge)
        hinge["deflection_deg"] = 15
        vertices = [(s * 0.01 if axis == i else 0) for s in (-1, 1) for i in range(3) for axis in range(3)]
        points = [Vector(vertices[i:i + 3]) for i in range(0, len(vertices), 3)]
        faces = []
        for x in (0, 3):
            for y in (1, 4):
                for z in (2, 5):
                    a, b, c = (points[i] for i in (x, y, z))
                    faces.append((x, y, z) if (b - a).cross(c - a).dot(a + b + c) > 0 else (z, y, x))
        mesh = bpy.data.meshes.new("aft_lens")
        mesh.from_pydata(points, [], faces)
        lamp = bpy.data.objects.new("light_nav_aft", mesh)
        collection.objects.link(lamp)
        lamp.parent = hinge
        bpy.context.view_layer.update()
        clear = BVHTree.FromPolygons([(100, 0, 0), (100, 1, 0), (100, 0, 1)], [(0, 1, 2)])
        corners = [(x, y, z) for x in (-5, 5) for y in (-5, 5) for z in (-5, 5)]
        enclosing = BVHTree.FromPolygons(corners, [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                                                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
        rest = hinge.matrix_world.copy()
        try:
            for tree, blocked in ((clear, 0), (enclosing, 25521)):
                with patch.object(nv, "aft_occluders", return_value=[tree]):
                    report = nv.measure_aft(collection)
                self.assertEqual(report["azimuth_deg"], [-70, 70])
                self.assertEqual(report["elevation_deg"], [-90, 90])
                self.assertEqual([(r["stabilator_deg"], r["total"], r["blocked"]) for r in report["results"]],
                                 [(k * 0.5, 25521, blocked) for k in range(-30, 31)])
                self.assertEqual(report["worst_fraction"], blocked / 25521)
                self.assertEqual(hinge.matrix_world, rest)
        finally:
            bpy.data.objects.remove(lamp, do_unlink=True)
            bpy.data.objects.remove(hinge, do_unlink=True)
            bpy.data.collections.remove(collection)

    def test_rear_obstruction_fails_the_build(self):
        with patch.object(nv, "measure", return_value={"results": [{"blocked": 0}]}), \
                patch.object(nv, "measure_aft", return_value={"worst_fraction": 1 / 25521}):
            with self.assertRaisesRegex(ValueError, "rear position-light sector"):
                nv.check(None)

    def test_paired_lenses_and_enclosing_airframe(self):
        collection = bpy.data.collections.new("VisibilityTest")
        bpy.context.scene.collection.children.link(collection)
        vertices = np.array([(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], float) * 0.01
        triangles = np.array([(4, k, (k + 1) % 4) for k in range(4)])
        lenses = {s: (vertices, triangles) for s in ("L", "R")}
        for side, x in (("L", 1), ("R", -1)):
            for lower in (False, True):
                obj = bpy.data.objects.new("light_nav_" + ("lower_" if lower else "") + side, None)
                collection.objects.link(obj)
                obj["light"] = "nav"
                obj.matrix_world = Matrix.Translation((x, 0, 0)) @ (Matrix.Rotation(np.pi, 4, "Y") if lower else Matrix.Identity(4))
        bpy.context.view_layer.update()
        distant = (np.array([(100, 0, 0), (100, 1, 0), (100, 0, 1)], float), np.array([(0, 1, 2)]))
        clear = nv.mesh_tree(distant)
        corners = [(x, y, z) for x in (-5, 5) for y in (-5, 5) for z in (-5, 5)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        enclosing = BVHTree.FromPolygons(corners, faces)
        with patch.object(nv, "stock_geometry", return_value=({"synthetic": (distant, [])}, lenses)), \
                patch.object(nv, "tip_stations", return_value={s: (np.zeros(3), np.eye(3)) for s in ("L", "R")}), \
                patch.object(nv, "tank_lamps", return_value=([], {})):
            for tree, blocked in ((clear, 0), (enclosing, 20091)):
                with patch.object(nv.solids, "bvh", return_value=tree):
                    report = nv.measure(collection)
                self.assertEqual([(r["total"], r["blocked"], r["fraction"]) for r in report["results"]],
                                 [(20091, blocked, blocked / 20091)] * 4)  # the stock store and the tip tank, each side
                self.assertEqual(report["azimuth_deg"], [0, 110])
                self.assertEqual(report["elevation_deg"], [-90, 90])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
