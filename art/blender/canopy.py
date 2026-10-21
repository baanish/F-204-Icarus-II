"""The canopy: a fixed windscreen, the opening hood hinged along its left sill, the windscreen frame, and the design
eye point the cockpit is fitted to.
"""
import bmesh
import bpy
from mathutils import Vector

import build_icarus as bi
import gear

CANOPY = {"windscreen_end_s": 2.95, "hinge_side_x": 1, "open_deg": 75, "frame_w": 0.04}
# Object names the other modules and the Unity author build against.
FRAME = "canopy_visible"  # the hood's mesh, under the "canopy" hinge
GLASS_OUTER, GLASS_INNER = "canopy_glass_outer", "canopy_glass_inner"
WINDSCREEN, WINDSCREEN_INNER = "windscreen", "windscreen_inner"  # outer and inner windscreen glass
# The design eye, (s, x, z) as in PARAMS; tools/export_blockout.py writes it to blockout.json. It sits
# EYE_BELOW_CROWN under the hood's highest point, at the crown's mean station, as IcarusAuthor.Canopy.cs derives
# the pilot's eye from the hood mesh; check() holds the two together.
EYE = (3.436, 0.0, 0.930)
EYE_BELOW_CROWN = 0.20
# part name -> (parent, dry mass kg); parts.full_tree adds these to its own
TREE = {
    "windscreen": ("cockpit_cell", 0),
    "windscreen_frame": ("cockpit_cell", 0),
}
# Triangles per component: target and cap (budget.py sums them). The fixed sill merges into the skin panels.
BUDGET = {
    "hood_frame": {"target": 480, "cap": 480, "objects": (FRAME,)},
    "windscreen_frame": {"target": 480, "cap": 480, "objects": ("windscreen_frame",)},
    "outer_glass": {"target": 2050, "cap": 2050, "objects": (GLASS_OUTER, WINDSCREEN)},
    "inner_glass": {"target": 1000, "cap": 2050, "objects": (GLASS_INNER, WINDSCREEN_INNER), "cockpit": True},
}
CLOSEUPS = {}


def build(p, mats):
    return hinge_canopy(p, build_canopy(p, mats["glass"]), mats["frame"])


def check(icarus):
    """The design eye still sits where the Unity author derives the pilot's eye from the hood."""
    hood = bpy.data.objects[FRAME]
    points = [hood.matrix_world @ v.co for v in hood.data.vertices]
    top = max(q.z for q in points)
    crown = [q for q in points if q.z > top - 0.01]
    derived = Vector((0.0, sum(q.y for q in crown) / len(crown), top - EYE_BELOW_CROWN))
    miss = (derived - bi.P(*EYE)).length
    if miss > 0.001:
        raise ValueError("canopy: EYE is %.4f m from the eye the hood gives, (s %.4f, x %.4f, z %.4f)"
                         % (miss, derived.y + bi.S0, derived.x, derived.z))
    return "eye within %.4f m of the hood crown's" % miss


def build_canopy(p, mat):
    rows = bi.resample(p["canopy"], bi.spaced(p["canopy"][0][0], p["canopy"][-1][0], 24))
    rings = [bi.body_ring(s, hw, top, bot, 2.0, e_bot=4.0, zmid=bot + 0.02) for s, hw, top, bot in rows]
    return bi.finish(bi.loft("canopy", rings, cap_back=True, cap_front=True), mat)


def hinge_canopy(p, canopy, frame_mat):
    """Split the canopy into a fixed windscreen and an opening hood hinged along its left sill."""
    end = CANOPY["windscreen_end_s"] - bi.S0
    pieces = {}
    for name, keep in ((WINDSCREEN, lambda c: c.y < end), ("canopy_mesh", lambda c: c.y >= end)):
        me = canopy.data.copy()
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep(f.calc_center_median())], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(name, me)
        bi.TARGET.objects.link(obj)
        pieces[name] = obj
    hood = pieces["canopy_mesh"]
    sill = [v.co for v in hood.data.vertices if v.co.x > 0]
    low = min(v.z for v in sill)
    rim = [v for v in sill if v.z < low + 0.03]
    a = min(rim, key=lambda v: v.y)
    b = max(rim, key=lambda v: v.y)
    # The windscreen frame: an arched band where the windscreen meets the hood.
    s0 = CANOPY["windscreen_end_s"]
    rows = bi.resample(p["canopy"], [s0 - CANOPY["frame_w"], s0 + CANOPY["frame_w"]])
    rings = []
    for s_, hw, top, bot in rows:
        ring = bi.body_ring(s_, hw * 1.03, top + 0.01, bot, 2.0, e_bot=4.0, zmid=bot + 0.02)
        rings.append(ring)
    bow = bi.finish(bi.loft("windscreen_frame", rings), frame_mat, smooth=False)
    bpy.data.objects.remove(canopy, do_unlink=True)
    parts = bi.hinged("canopy", hood, gear.frame_on(a, b - a))  # hinged along the left sill
    # opened, the hood swings up and over to the left: its right edge rises and moves toward the hinge
    parts[0]["travel_deg"] = gear.opening_travel(parts[0], CANOPY["open_deg"], lambda pts: max(q.z for q in pts) + min(q.x for q in pts))
    return parts + [pieces[WINDSCREEN], bow]
