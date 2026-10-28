"""Blender check that checks.interior_visibility sees the mid section's truss: with the skin pieces over its front half
gone (the dorsal cover's front piece and both upper mid front panels), the check must fail on fuselage_truss_front.

Run with tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/test_truss_visible.py
(it loads the cached split build, or builds one).
"""
import sys
import unittest
from pathlib import Path

import bpy

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import build_icarus as bi
import checks

OVER_TRUSS = ("dorsal_cover_front", "skin_mid_front_L", "skin_mid_front_R")


class TrussVisible(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bi.build_cached()
        cls.icarus = bpy.data.collections["Icarus"]

    def test_truss_without_its_skin_fails(self):
        owners = {name: list(bpy.data.objects[name].users_collection) for name in OVER_TRUSS}
        try:
            for name, collections in owners.items():
                for c in collections:
                    c.objects.unlink(bpy.data.objects[name])
            with self.assertRaisesRegex(ValueError, "fuselage_truss_front: "):
                checks.interior_visibility(self.icarus)
        finally:
            for name, collections in owners.items():
                for c in collections:
                    c.objects.link(bpy.data.objects[name])


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
