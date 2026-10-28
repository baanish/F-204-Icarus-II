"""Blender check that parts.seam_check catches an open seam: the split build passes, and with one piece's seam corners
moved 0.3 mm off its siblings' (past SEAM_SHARED, well inside the radius the check looks for a sibling in) it fails on
that piece.

Run with tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/test_seam_check.py
(it loads the cached split build, or builds one).
"""
import sys
import unittest
from pathlib import Path

import bpy
from mathutils import Vector

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import build_icarus as bi
import parts

PIECE = "skin_mid_front_belly_L"


class SeamCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bi.build_cached()
        cls.icarus = bpy.data.collections["Icarus"]

    def test_split_build_passes(self):
        parts.seam_check(self.icarus)

    def test_seam_displaced_fails(self):
        me = bpy.data.objects[PIECE].data
        flag = me.attributes[parts.SEAM_CORNER]
        moved = [v for v in me.vertices if flag.data[v.index].value]
        self.assertTrue(moved)
        shift = bpy.data.objects[PIECE].matrix_world.inverted().to_3x3() @ Vector((0.0, 0.0, 0.0003))
        try:
            for v in moved:
                v.co += shift
            # either side of the open seam may report it: the moved piece's corner, or a sibling's corner it left
            with self.assertRaisesRegex(ValueError, r"is 0\.0003\d m from %s's nearest|%s corner \S+ \S+ \S+ is 0\.0003\d m" % (PIECE, PIECE)):
                parts.seam_check(self.icarus)
        finally:
            for v in moved:
                v.co -= shift


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
