"""Landing gear and gear doors.

Positions follow the F-104: a nose leg just aft of the cockpit folding forward under it, and two main legs on a
2.5 m track folding forward into the fuselage. Every moving piece is a hinge empty (local X along the hinge) with a
<name>_visible mesh child, like the control surfaces; the built pose is gear down, doors shut. A hinge's
"travel_deg" property is the rotation about its X from the built pose to the stowed or open pose.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi

GEAR = {
    "ground_z": -1.28,  # ground height below the radome-tip line, gear down, from the reference side view
    # pivot (s, x, z), wheel centre station and lateral offset, wheel diameter and width, strut radius, and the point
    # the wheel is swung to when stowed
    "nose": {"pivot": (4.95, 0.0, -0.32), "wheel_s": 5.20, "wheel_x": 0.0, "wheel_d": 0.48, "wheel_w": 0.14,
             "strut_r": 0.035, "stow": (3.95, 0.0, -0.26)},
    "main": {"pivot": (10.70, 0.42, -0.30), "wheel_s": 9.84, "wheel_x": 1.24, "wheel_d": 0.67, "wheel_w": 0.20,
             "strut_r": 0.05, "stow": (9.55, 0.36, -0.24)},
    # Door patches cut from the belly skin: (name, s0, s1, x from, x to); the hinge runs along the outer edge.
    "doors": [("gear_door_N_L", 3.70, 5.15, 0.00, 0.17), ("gear_door_N_R", 3.70, 5.15, -0.17, 0.00),
              ("gear_door_main_L", 9.35, 11.10, 0.16, 0.56), ("gear_door_main_R", 9.35, 11.10, -0.56, -0.16)],
    "door_open_deg": 85,
}
# Object names the other modules and the Unity author build against, per leg N, L and R: the sprung leg is
# gear_leg_<leg>_visible and the wheel gear_wheel_<leg>_visible; the piston and axle slide as gear_unsprung_<leg>,
# and a drag brace is gear_arm_<leg>.
UNSPRUNG, ARM = "gear_unsprung_", "gear_arm_"
# Triangles per component: target and cap (budget.py sums them). A leg counts its sprung, unsprung, arm and wheel.
BUDGET = {
    **{"leg_" + leg: {"target": 3800, "cap": 3800, "objects": ("gear_leg_" + leg, "gear_wheel_" + leg, UNSPRUNG + leg, ARM + leg)}
       for leg in ("N", "L", "R")},
    "doors": {"target": 520, "cap": 520, "objects": ("gear_door_",)},
}
CLOSEUPS = {}


def build(p, mats):
    """The three legs; the doors are cut from the fuselage skin earlier (cut_doors)."""
    return build_gear(mats)


def check(icarus):
    return None


def cylinder(name, a, b, r, segments=16):
    """A capped cylinder from point a to point b."""
    axis = (b - a).normalized()
    side = axis.orthogonal().normalized()
    up = axis.cross(side)
    ring = lambda c: [c + (side * math.cos(t) + up * math.sin(t)) * r for t in [2 * math.pi * k / segments for k in range(segments)]]
    return bi.loft(name, [ring(a), ring(b)], cap_back=True, cap_front=True)


def wheel(name, centre, d, w):
    return cylinder(name, centre - Vector((w / 2, 0, 0)), centre + Vector((w / 2, 0, 0)), d / 2, 24)


def axis_between(d1, d2):
    """Rotation axis and angle taking direction d1 onto d2."""
    ax = d1.cross(d2)
    return ax.normalized(), math.degrees(d1.angle(d2))


def frame_on(origin, x_axis):
    x_axis = x_axis.normalized()
    ref = Vector((0, 1, 0)) if abs(x_axis.y) < 0.9 else Vector((0, 0, 1))
    y_axis = (ref - x_axis * x_axis.dot(ref)).normalized()
    return Matrix.Translation(origin) @ Matrix((x_axis, y_axis, x_axis.cross(y_axis))).transposed().to_4x4()


def leg(name, spec, mat_strut, mat_tyre, mirror=1):
    piv = bi.P(spec["pivot"][0], mirror * spec["pivot"][1], spec["pivot"][2])
    centre = bi.P(spec["wheel_s"], mirror * spec["wheel_x"], GEAR["ground_z"] + spec["wheel_d"] / 2)
    stow = bi.P(spec["stow"][0], mirror * spec["stow"][1], spec["stow"][2])
    ax, travel = axis_between((centre - piv).normalized(), (stow - piv).normalized())
    strut = bi.finish(cylinder(name + "_strut", piv, centre + Vector((0, 0, spec["wheel_d"] * 0.15)), spec["strut_r"]), mat_strut)
    axle_tip = centre
    tyre = bi.finish(wheel(name + "_tyre", axle_tip, spec["wheel_d"], spec["wheel_w"]), mat_tyre)
    parts = []
    leg_frame = frame_on(piv, ax)
    parts += bi.hinged(name, strut, leg_frame)
    parts[0]["travel_deg"] = round(travel, 1)
    # The wheel turns about the strut as it stows, so a big main wheel can lie flat in a shallow bay.
    wheel_frame = frame_on(centre, (centre - piv))
    wheel_parts = bi.hinged(name.replace("gear_leg", "gear_wheel"), tyre, wheel_frame, parent=parts[0])
    wheel_parts[0]["travel_deg"] = 90.0 if spec is GEAR["main"] else 0.0
    return parts + wheel_parts


def build_gear(mats):
    parts = []
    parts += leg("gear_leg_N", GEAR["nose"], mats["strut"], mats["tyre"])
    for mirror, sd in ((1, "L"), (-1, "R")):
        parts += leg("gear_leg_" + sd, GEAR["main"], mats["strut"], mats["tyre"], mirror)
    return parts


def opening_travel(hinge, degrees, score):
    """The signed travel about the hinge's X whose opened pose scores higher; score(points) rates the moved
    _visible mesh in world space. Deriving the sign by hand from each frame proved error-prone."""
    vis = hinge.children[0]
    local = [vis.matrix_local @ v.co for v in vis.data.vertices]
    best = None
    for sign in (1, -1):
        m = hinge.matrix_world @ Matrix.Rotation(math.radians(sign * degrees), 4, "X")
        pts = [m @ c for c in local]
        if best is None or score(pts) > best[0]:
            best = (score(pts), sign * degrees)
    return best[1]


def cut_doors(fuselage):
    """Lift the door patches out of the fuselage skin into hinged doors; returns the door parts."""
    parts = []
    for name, s0, s1, x0, x1 in GEAR["doors"]:
        def inside(c, s0=s0, s1=s1, x0=x0, x1=x1):
            return s0 <= c.y + bi.S0 <= s1 and x0 <= c.x <= x1 and c.z < 0.0
        me = fuselage.data.copy()
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not inside(f.calc_center_median())], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        if not bm.faces:
            bm.free()
            continue
        outer = max(bm.verts, key=lambda v: abs(v.co.x)).co.x
        edge = [v.co.copy() for v in bm.verts if abs(v.co.x - outer) < 0.03]
        a = min(edge, key=lambda v: v.y)
        b = max(edge, key=lambda v: v.y)
        bm.to_mesh(me)
        bm.free()
        door = bpy.data.objects.new(name + "_mesh", me)
        bi.TARGET.objects.link(door)
        hinge_axis = (b - a) if a.x >= 0 else (a - b)  # X runs aft on the left, forward on the right
        parts += bi.hinged(name, door, frame_on(a if a.x >= 0 else b, hinge_axis))
        # built shut; opened, the door hangs down from its outer hinge
        parts[-2]["travel_deg"] = opening_travel(parts[-2], GEAR["door_open_deg"], lambda pts: -min(q.z for q in pts))
        # remove the door faces from the skin
        bm = bmesh.new()
        bm.from_mesh(fuselage.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if inside(f.calc_center_median())], context="FACES")
        bm.to_mesh(fuselage.data)
        bm.free()
    return parts
