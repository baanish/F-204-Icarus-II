"""Blender checks of the split build's intakes and blast aim points: each intake is its fairing's outside chunk (the lip,
its skin piece and an inner face, its one hull outboard of the root's one hull), the duct stays on the root, every
single-hull part but the canopy holds its origin, the aft and forward sections hold theirs in a piece, every part with
fuel keeps its origin parts.FIRE_EYE_CLEAR from the design eye, and hulls.aim_points fails a part moved off its hull.

Run with tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/test_intake_chunk.py
(it loads the cached split build, or builds one).
"""
import sys
import unittest
from pathlib import Path

import bpy
from mathutils import Vector

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "art/blender")]
import build_icarus as bi
import canopy
import hulls
import parts
from clearance import part_of


def colliders_of(name):
    return [c for c in bpy.data.collections["Colliders"].objects if part_of(c) is not None and part_of(c).name == name]


class IntakeChunk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bi.build_cached()
        cls.icarus = bpy.data.collections["Icarus"]

    def test_intake_is_the_outside_chunk(self):
        for sd in ("L", "R"):
            intake = bpy.data.objects["intake_duct_" + sd]
            chunk = bpy.data.objects["skin_mid_intake_" + sd]
            duct = bpy.data.objects["duct_" + sd]
            self.assertEqual(chunk.parent.name, intake.name)
            self.assertEqual(duct.parent.name, "fuselage_mid")
            self.assertEqual(duct.get("folded_into"), "fuselage_mid")
            self.assertEqual(bpy.data.objects["skel_intake_duct_" + sd].parent.name, "fuselage_mid")
            self.assertIn("aircraft_structure", [m.name for m in intake.data.materials])
            self.assertEqual(len(colliders_of(intake.name)), 1)
            side = 1.0 if sd == "L" else -1.0
            self.assertGreater(side * intake.matrix_world.translation.x, 0.5)  # outboard, on the fairing
        self.assertEqual(len(colliders_of("fuselage_mid")), 1)

    def test_far_stand_ins_follow_the_split(self):
        import bmesh
        import numpy as np

        lods = bpy.data.collections["LOD1"].objects
        for sd in ("L", "R"):
            chunk = bpy.data.objects["skin_mid_intake_" + sd]
            mine = [o for o in lods if o.parent == chunk]
            self.assertEqual(sorted(o.parent.name for o in lods if o.parent and o.parent.name.startswith("skin_mid_") and o.parent.name.endswith(sd)),
                             sorted("skin_mid_%s_%s" % (k, sd) for k in ("front", "front_belly", "intake", "rear", "rear_belly")))
            self.assertEqual(len(mine), 1, "the intake's own LOD1 hull leaves with it")
            skin = np.array([(chunk.matrix_world @ v.co)[:] for v in chunk.data.vertices])
            for lod in (o for o in lods if o.parent and o.parent.name.startswith("skin_mid_") and o.parent != chunk):
                bm = bmesh.new()
                bm.from_mesh(lod.data)
                bm.transform(lod.matrix_world)
                islands, seen = [], set()
                for v in bm.verts:  # each convex hull of the joined stand-in is one island
                    if v in seen:
                        continue
                    stack, island = [v], []
                    while stack:
                        u = stack.pop()
                        if u not in seen:
                            seen.add(u)
                            island.append(u.co.copy())
                            stack.extend(e.other_vert(u) for e in u.link_edges)
                    islands.append(island)
                bm.free()
                for island in islands:
                    hull = hulls.convex(island)
                    depth = hulls.outside(hull, skin)
                    hull.free()
                    self.assertEqual(int((depth < -0.01).sum()), 0, "%s spans %s's skin" % (lod.name, chunk.name))

    def test_aim_points_hold(self):
        cols = list(bpy.data.collections["Colliders"].objects)
        self.assertIn("single-hull parts hold their origins", hulls.aim_points(cols))
        for name in ("fuselage_aft", "fuselage_forward"):
            at = bpy.data.objects[name].matrix_world.translation
            self.assertLessEqual(min(hulls.outside_hull(c, at) for c in colliders_of(name)), hulls.AIM_SLACK)

    def test_a_single_hull_part_without_its_hull_fails(self):
        cols = [c for c in bpy.data.collections["Colliders"].objects if part_of(c) is None or part_of(c).name != "intake_duct_L"]
        with self.assertRaisesRegex(ValueError, "intake_duct_L has 0 hulls, one by design"):
            hulls.aim_points(cols)

    def test_moved_origin_fails_the_aim_check(self):
        part = bpy.data.objects["wing_spar_L"]
        keep = part.matrix_world.translation.copy()
        try:
            parts.move_origin(part, keep + Vector((3.0, 0.0, 0.0)))
            with self.assertRaisesRegex(ValueError, "wing_spar_L's origin .* outside its hull"):
                hulls.aim_points(list(bpy.data.collections["Colliders"].objects))
        finally:
            parts.move_origin(part, keep)

    def test_tank_fires_clear_of_the_pilot(self):
        eye = bi.P(*canopy.EYE)
        tanks = [o for o in self.icarus.all_objects if o.get("fuel_kg", 0) > 0]
        self.assertEqual(len(tanks), 6)
        for o in tanks:
            self.assertGreaterEqual((o.matrix_world.translation - eye).length, parts.FIRE_EYE_CLEAR, o.name)
        self.assertIn("fuselage_forward", parts.fire_clear(self.icarus))


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
