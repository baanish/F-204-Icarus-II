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
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import nav_visibility as nv


class NavVisibility(unittest.TestCase):
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
                patch.object(nv, "tip_stations", return_value={s: (np.zeros(3), np.eye(3)) for s in ("L", "R")}):
            for tree, blocked in ((clear, 0), (enclosing, 20091)):
                with patch.object(nv.solids, "bvh", return_value=tree):
                    report = nv.measure(collection)
                self.assertEqual([(r["total"], r["blocked"], r["fraction"]) for r in report["results"]],
                                 [(20091, blocked, blocked / 20091)] * 2)
                self.assertEqual(report["azimuth_deg"], [0, 110])
                self.assertEqual(report["elevation_deg"], [-90, 90])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
