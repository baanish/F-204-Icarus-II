"""Landing gear, gear doors, the opening canopy, lights and antennas.

Positions follow the F-104: a nose leg just aft of the cockpit folding forward under it, and two main legs on a
2.5 m track folding forward into the fuselage. Every moving piece is a hinge empty (local X along the hinge) with a
<name>_visible mesh child, like the control surfaces; the built pose is gear down, doors shut, canopy shut. A hinge's
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
CANOPY = {"windscreen_end_s": 2.95, "hinge_side_x": 1, "open_deg": 75, "frame_w": 0.04}
LIGHTS = [  # (name, s, x, z, kind, colour)
    ("light_nav_L", None, None, None, "nav", "red"),  # at the left wingtip, placed from the wing
    ("light_nav_R", None, None, None, "nav", "green"),
    ("light_beacon_top", 15.20, 0.0, 2.90, "anticollision", "red"),
    ("light_beacon_belly", 9.00, 0.0, -0.40, "anticollision", "red"),
    ("light_formation_L", 6.30, 0.95, 0.30, "formation", "green"),
    ("light_formation_R", 6.30, -0.95, 0.30, "formation", "green"),
    ("light_landing", None, None, None, "landing", "white"),  # on the nose leg
]
ANTENNAS = [  # (name, s, z of root, height, chord, which side: top or belly)
    ("antenna_uhf_top", 7.20, None, 0.20, 0.30, "top"),
    ("antenna_iff_belly", 6.40, None, 0.15, 0.22, "belly"),
    ("antenna_datalink_top", 11.60, None, 0.16, 0.26, "top"),
]
# Weapon pylons: blades under the wing at a fraction of the span from the root row to the tip. Each carries one store,
# which the game hangs from the hardpoint at the pylon's lower edge. The wingtip stations have no blade or rail: every
# mount brings its own launch rail, which bears straight on the tip face. The game hides an empty station's blade and
# shows its plug instead, a stub on the blade's root footprint standing "plug" metres below the wing.
PYLONS = {"inner": 0.37, "outer": 0.70, "length": 1.5, "depth": 0.26, "thickness": 0.10, "rake": 0.30, "bury": 0.03,
          "plug": 0.03}


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


def hinge_canopy(p, canopy, frame_mat):
    """Split the canopy into a fixed windscreen and an opening hood hinged along its left sill."""
    end = CANOPY["windscreen_end_s"] - bi.S0
    pieces = {}
    for name, keep in (("windscreen", lambda c: c.y < end), ("canopy_mesh", lambda c: c.y >= end)):
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
    parts = bi.hinged("canopy", hood, frame_on(a, b - a))  # hinged along the left sill
    # opened, the hood swings up and over to the left: its right edge rises and moves toward the hinge
    parts[0]["travel_deg"] = opening_travel(parts[0], CANOPY["open_deg"], lambda pts: max(q.z for q in pts) + min(q.x for q in pts))
    return parts + [pieces["windscreen"], bow]


def lights_and_antennas(p, mats):
    w = p["wing"]
    # The nav lamps sit on top of the tip, 0.075 m inboard of the tip face the wingtip store's rail bears on, as on
    # the Revoker.
    lamp_x = w["planform"][-1][1] - 0.075
    lamp_le, lamp_z, lamp_chord = wing_at(w, lamp_x)
    parts = []
    for name, s, x, z, kind, colour in LIGHTS:
        if kind == "nav":
            side = 1 if name.endswith("_L") else -1
            pos = bi.P(lamp_le + lamp_chord * 0.35, side * lamp_x, lamp_z + bi.airfoil(0.35) * w["thickness"] * lamp_chord)
        elif kind == "landing":
            g = GEAR["nose"]
            pos = bi.P(g["wheel_s"] - 0.15, 0.0, GEAR["ground_z"] + g["wheel_d"] + 0.15)
        else:
            pos = bi.P(s, x, z)
        e = bi.empty(name, Matrix.Translation(pos))
        e["light"] = kind
        e["colour"] = colour
        parts.append(e)
    for name, s, _, h, chord, where in ANTENNAS:
        ring = bi.blended_ring(p, s)
        z0 = max(v.z for v in ring) if where == "top" else min(v.z for v in ring)
        up = 1 if where == "top" else -1
        verts = [bi.P(s - chord / 2, 0.0, z0 - up * 0.02), bi.P(s + chord / 2, 0.0, z0 - up * 0.02),
                 bi.P(s + chord * 0.1, 0.0, z0 + up * h), bi.P(s - chord * 0.05, 0.0, z0 + up * h)]
        thick = Vector((0.006, 0, 0))
        v = [q - thick for q in verts] + [q + thick for q in verts]
        f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        obj = bi.finish(bi.mesh_object(name, v, f), mats["antenna"], smooth=False)
        obj["role"] = "antenna"
        parts.append(obj)
    return parts


def wing_at(w, x):
    """The wing section (s of the leading edge, z of the chord line, chord) at spanwise x, between planform rows."""
    sections = bi.wing_sections(w)
    for (le0, x0, z0, c0), (le1, x1, z1, c1) in zip(sections, sections[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return le0 + t * (le1 - le0), z0 + t * (z1 - z0), c0 + t * (c1 - c0)
    raise ValueError("x %.2f is outside the wing" % x)


def slab(name, s0, s1, x, z_top, depth, thick, rake, mat):
    """A vertical blade along s, its top at z_top and its lower edge raked back from the front by rake."""
    profile = [bi.P(s0, x, z_top), bi.P(s1, x, z_top), bi.P(s1 - rake / 3, x, z_top - depth), bi.P(s0 + rake, x, z_top - depth)]
    half = Vector((thick / 2, 0, 0))
    v = [q - half for q in profile] + [q + half for q in profile]
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    obj = bi.finish(bi.mesh_object(name, v, f), mat, smooth=False)
    obj["role"] = "pylon"
    return obj


def fixed_box(p, x):
    """Chord fractions (front, back) of the fixed wing box at spanwise x, the same limits build_icarus.box_stations
    leaves between the leading-edge devices and trailing-edge surfaces."""
    gap, front, back = p["surface_gap"], 0.0, 1.0
    for _, a, b, c0, c1 in p["wing_surfaces"]:
        if a - gap / 2 <= x <= b + gap / 2:
            if c0 == 0.0:
                front = max(front, c1 + gap / 2)
            else:
                back = min(back, c0 - gap / 2)
    return front, back


def pylons(p, mat):
    """The inner and outer wing pylons, one store each, and their plugs."""
    w, y = p["wing"], PYLONS
    root_x, tip_x = w["planform"][0][1], w["planform"][-1][1]
    parts = []
    for side, suffix in ((1, "_L"), (-1, "_R")):
        for station in ("inner", "outer"):
            x = root_x + y[station] * (tip_x - root_x)
            le, z, chord = wing_at(w, x)
            low = z - 0.5 * w["thickness"] * chord
            length = min(y["length"], 0.75 * chord)
            # The blade's buried root stays on the fixed box, clear of the moving surfaces and the space they sweep.
            front, back = fixed_box(p, x)
            s0 = max(le + front * chord, le + 0.45 * chord - length / 2)
            s1 = min(le + back * chord, le + 0.45 * chord + length / 2)
            parts.append(slab("pylon_%s%s" % (station, suffix), s0, s1, side * x, low + y["bury"],
                              y["depth"] + y["bury"], y["thickness"], y["rake"], mat))
            parts.append(slab("pylon_%s_plug%s" % (station, suffix), s0, s1, side * x, low + y["bury"],
                              y["plug"] + y["bury"], y["thickness"], 0.0, mat))
    return parts
