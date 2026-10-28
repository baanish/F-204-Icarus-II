"""Blender checks for the breakup split's plumbing: skin family names, the late plane cut, the family-aware island margin
and the budget's empty selectors.

Run with tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/test_breakup_split.py.
"""
import math
import sys
import unittest
from pathlib import Path

import bpy
from mathutils import Vector

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import budget
import parts
import uvs


def collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def sheet(col, name, size=(4, 2), origin=(0.0, 0.0), uv_origin=(0.1, 0.1), uv_scale=0.1, bend=0.0):
    """A grid of quads on the skin material, z rising as bend * x squared, UVs a scaled copy of x and y."""
    nx, ny = size
    verts = [(origin[0] + i, origin[1] + j, bend * (origin[0] + i) ** 2) for j in range(ny + 1) for i in range(nx + 1)]
    faces = [(j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i)
             for j in range(ny) for i in range(nx)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.materials.append(bpy.data.materials.get(uvs.SKIN) or bpy.data.materials.new(uvs.SKIN))
    uv = me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (uv_origin[0] + (co.x - origin[0]) * uv_scale, uv_origin[1] + (co.y - origin[1]) * uv_scale)
    for poly in me.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new(name, me)
    col.objects.link(obj)
    return obj


class Family(unittest.TestCase):
    def test_codes_drop_as_whole_tokens(self):
        self.assertEqual(parts.family("skin_forward_L"), "skin_forward_L")
        self.assertEqual(parts.family("skin_forward_belly_L"), "skin_forward_L")
        self.assertEqual(parts.family("wing_skin_outer_upper_L"), "wing_skin_L")
        self.assertEqual(parts.family("dorsal_cover_rear"), "dorsal_cover")
        self.assertEqual(parts.family("skin_aft_rear_R"), "skin_aft_R")
        self.assertEqual(parts.family("pylon_inner_L"), "pylon_inner_L")
        self.assertEqual(parts.family("wing_spar_outer_L"), "wing_spar_outer_L")


class SplitAndMargin(unittest.TestCase):
    def setUp(self):
        self.col = collection("SplitTest")
        root = bpy.data.objects.new("split_root", None)
        self.col.objects.link(root)

    def tearDown(self):
        for obj in list(self.col.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(self.col)

    def cut(self, family="skin_test_L"):
        obj = sheet(self.col, family, bend=0.05)
        obj["mass_kg"] = 40
        before = {(round(v.co.x, 6), round(v.co.y, 6)): None for v in obj.data.vertices}
        normals = {}
        for loop, n in zip(obj.data.loops, obj.data.corner_normals):
            normals[tuple(round(c, 6) for c in obj.data.vertices[loop.vertex_index].co)] = n.vector.copy()
        made = parts.cut_family(self.col, obj, [((1.5, 0, 0), (1, 0, 0))],
                                [("skin_test_front_L", "split_root", lambda c, side: c.x < 1.5),
                                 ("skin_test_rear_L", "split_root", lambda c, side: True)])
        return made, before, normals

    def test_cut_interpolates_uvs_and_normals_and_shares_mass(self):
        made, before, normals = self.cut()
        self.assertEqual([p.name for p in made], ["skin_test_front_L", "skin_test_rear_L"])
        self.assertAlmostEqual(sum(p["mass_kg"] for p in made), 40, places=2)
        for piece in made:
            me = piece.data
            uv = me.uv_layers.active.data
            for loop, n in zip(me.loops, me.corner_normals):
                w = piece.matrix_world @ me.vertices[loop.vertex_index].co
                # the UV is a linear map of x and y, so an interpolated corner lands on it exactly
                self.assertAlmostEqual(uv[loop.index].uv.x, 0.1 + w.x * 0.1, places=6)
                self.assertAlmostEqual(uv[loop.index].uv.y, 0.1 + w.y * 0.1, places=6)
                old = normals.get(tuple(round(c, 6) for c in w))
                if old is not None:
                    self.assertLess(old.angle(n.vector), math.radians(0.01))
                else:  # a new corner on the cut, between the old corners at x 1 and 2
                    self.assertAlmostEqual(w.x, 1.5, places=5)
                    self.assertLess(n.vector.angle(Vector((-0.15, 0, 1)).normalized()), math.radians(3))

    def test_margin_joins_a_cut_island(self):
        whole = sheet(self.col, "skin_whole_L")
        apart = sheet(self.col, "skin_apart_L", origin=(0, 5), uv_origin=(0.1, 0.4))
        unsplit = uvs.island_margin([whole, apart])
        made, _, _ = self.cut("skin_whole2_L")
        bpy.data.objects.remove(whole, do_unlink=True)
        # the cut sheet sits where the whole one did in the atlas
        self.assertAlmostEqual(uvs.island_margin(made + [apart]), unsplit, places=3)

    def test_margin_sees_two_families_two_px_apart(self):
        a = sheet(self.col, "skin_one_L")
        b = sheet(self.col, "skin_two_L", origin=(0, 5), uv_origin=(0.1 + 0.4 + 2 / uvs.ATLAS_SIZE, 0.1))
        self.assertAlmostEqual(uvs.island_margin([a, b]), 2.0, places=3)


class Budget(unittest.TestCase):
    def setUp(self):
        self.col = collection("BudgetTest")
        sheet(self.col, "skin_test_front_L")

    def tearDown(self):
        for obj in list(self.col.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(self.col)

    def test_selector_matching_nothing_fails(self):
        over = budget.over_caps(self.col, {"gone": {"target": 10, "cap": 10, "objects": ("skin_test_L",)}})
        self.assertEqual(len(over), 1)
        self.assertIn("matches nothing", over[0])

    def test_family_selector_counts_pieces(self):
        item = {"target": 10, "cap": 10, "family": ("skin_test_L",)}
        self.assertEqual(budget.measure(self.col, item), 16)
        self.assertEqual(budget.over_caps(self.col, {"family": item}), ["family 16 > 10"])

    def test_empty_selector_is_a_reservation(self):
        self.assertEqual(budget.over_caps(self.col, {"stock": {"target": 100, "cap": 100, "objects": ()}}), [])


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
