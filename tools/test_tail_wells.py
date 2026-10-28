"""Blender check that checks.structure_clear_of_bays covers the tail cone: with a frame member left standing inside a
speed brake well in fuselage_tail (as if speed_brakes.clear_wells had skipped the tail cone), the check must fail on it.

Run with tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/test_tail_wells.py
(it loads the cached split build, or builds one).
"""
import sys
import unittest
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import build_icarus as bi
import checks
import speed_brakes


class TailWells(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bi.build_cached()
        cls.icarus = bpy.data.collections["Icarus"]

    def test_clear_build_passes(self):
        checks.structure_clear_of_bays(self.icarus)

    def test_tail_frame_in_a_well_fails(self):
        tail = bpy.data.objects["fuselage_tail"]
        verts, _ = next(iter(speed_brakes.Patch(bi.PARAMS).voids(1)))
        centre = sum((Vector(v) for v in verts), Vector()) / len(verts)
        saved = tail.data.copy()
        try:
            bm = bmesh.new()
            bm.from_mesh(tail.data)
            slot = [m.name for m in tail.data.materials].index("Icarus_Frame")
            local = tail.matrix_world.inverted() @ centre
            made = bmesh.ops.create_cube(bm, size=0.04, matrix=Matrix.Translation(local))
            for f in {f for v in made["verts"] for f in v.link_faces}:
                f.material_index = slot
            bm.to_mesh(tail.data)
            bm.free()
            with self.assertRaisesRegex(ValueError, "fuselage_tail"):
                checks.structure_clear_of_bays(self.icarus)
        finally:
            tail.data = saved


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
