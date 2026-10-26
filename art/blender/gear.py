"""Landing gear, gear doors and the suspension chain.

Each leg is the transform chain the game moves (IcarusAuthor.Gear.cs drives it with the Revoker's LandingGear):

- gear_leg_<leg> is the hinge empty the leg folds about (local X along the hinge; travel_deg turns it from down to
  stowed), with the sprung mesh gear_leg_<leg>_visible on Fighter1_gear.
- gear_wheel_<leg>, a child of the hinge, is the second fold the game turns through LandingGear.movingParts, geared
  linearly to the first: the main gear's wheel carrier swivelling the wheel flat, as the F-104's does; on the nose
  leg it does not turn. What rides it: gear_arm_<leg> (the main gear's carrier: knuckle, neck and the shock strut's
  cylinder), gear_unsprung_<leg> (the strut's piston on Mirror, axle, yoke, brake, torque guide: what slides with
  LandingGear.suspensionTravel) and gear_wheel_<leg>_visible (tyre and hub on Aircraft_wheels).

The built pose is gear down, doors shut. The game slides the unsprung straight up its bump stop, so every piston
stands vertical when down. Both legs move as the F-104's do (F-104G flight manual LR1-14404-1, p. 1-47; sources in
GEAR). Each main leg is an I-section forging on a trunnion at the keel, splayed out to its wheel, with its retraction
actuator and hydraulic lines along it (MAIN_LEG). It swings forward and inward about an oblique hinge while the carrier
at its foot, which holds the shock strut, turns the wheel 90 degrees, so the two tyres lie flat side by side across the belly, above the conformal
troughs and under the ducts. The nose leg folds forward, its wheel upright, into a well behind the seat. Doors are
patches of the fuselage skin, resampled to a coarse grid and built like the speed brakes: skin outside, on
jet_mechanical a tray inside with a rim, ribs and a stringer, carved back where the stowed gear lies close, and hinge
knuckles on a straight line just inside the skin, the ends square to it. The wells (internals: gear_bay) run out to
just inside the skin on the opaque dark slot, so nothing past them shows through the open doors.
"""
import contextlib
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi
import solids
from solids import X, Y, Z
from speed_brakes import Shell, ring

SEG_TYRE, SEG_HUB, SEG_LEG = 24, 12, 12
GEAR = {
    "ground_z": -1.28,  # ground height below the radome-tip line, gear down, from the reference side view
    # The nose tyre is the F-104's 18 x 5.5 (Lockheed "MAP F-104" brochure, 1963, p. 13). Wheel centre station and
    # lateral offset, tyre diameter, width and rim radius. The nose leg's pivot (s, x, z) sits just ahead of the oleo,
    # which stands on the wheel; fold_deg turns it forward about -X, twist_deg its piston, so the wheel stows flat under
    # the cockpit floor, clear of the seat's lowest point (z -0.21) by about 0.09 m.
    "nose": {"wheel_s": 5.20, "wheel_x": 0.0, "wheel_d": 0.457, "wheel_w": 0.14, "rim_r": 0.10,
             "pivot": (5.13, 0.0, -0.30), "crown_gap": 0.035, "piston": 0.10, "oleo": 0.28,
             "fold_deg": 90.0, "twist_deg": 90.0},
    # The main wheel is the F-104's 26 x 8.0-14 in diameter (0.66 m, MAP brochure p. 13) on today's 0.16 m width,
    # the owner's call: a 0.203 m tyre needs the ducts' undersides 0.04 m higher still. The leg retracts "forward and
    # inward" and "a linkage causes the wheels to rotate 90 degrees during retraction" (flight manual p. 1-47): it
    # turns fold_deg about "hinge" through the keel pivot (s, x, z), and geared to it the carrier swivels swivel_deg
    # about "swivel" through the wheel centre (left side, Blender axes; tools/gear_fold_solve.py solves both for a
    # stowed wheel centre, "stowed" (s, x, z); tools/gear_fold_solve.py --pivot 10.47,0.30,-0.20 --wheel
    # 9.84,1.24,-0.95 --stow 0.335,-0.055 --bundle build/icarus_0.0.1.nobp --scan). Stowed the tyres lie flat side by side, 0.01 m apart over the
    # keel, their outboard faces up and the carriers under them, just behind the conformal missiles' tails: their fins
    # stand up into the belly there, and Stores rule 12 keeps 0.05 m, so the wells sit 0.72 m ahead of the wheels where
    # the F-104's lie about 1 m ahead, and the trunnion 0.63 m behind them; the leg rakes forward to its wheel. Of the
    # hinges that do it, this one (--scan) swings the wheel forward and inboard from the start, keeping the tyre 0.058 m
    # from the inner wing's twin racks (tools/store_clearance.py; Stores rule 12: 0.05 m) and 0.027 m from the
    # trough's skin; the folds near 120 degrees lift it outboard into the twin racks' inboard missile first. As on the F-104, the forged
    # leg runs down to its foot, which holds the swivel: the wheel carrier turns in the foot on the swivel axis and
    # carries the shock strut, whose piston carries the stub axle (main_points, MAIN_LEG).
    "main": {"wheel_s": 9.84, "wheel_x": 1.24, "wheel_d": 0.66, "wheel_w": 0.16, "rim_r": 0.178,
             "pivot": (10.47, 0.30, -0.20), "hinge": (-0.05276, -0.75163, -0.65747), "fold_deg": 93.818,
             "swivel": (0.88711, 0.01478, 0.46132), "swivel_deg": 90.0, "stowed": (9.1206, 0.335, -0.055)},
    # Door patches of the belly skin, left side: (name, s from, s to, x from, x to, hinge edge, rows, columns, degrees
    # open, opening[, (first ring point, last)]). The patch runs along the skin's own rings and ring points nearest
    # those limits; rows and columns are the resampled grid, all of the skin's where they exceed it. Every door takes
    # all of them: a coarser grid's chords stand off the skin's curve (a 4 by 4 flap by up to 33 mm) and the hole's edge
    # is snapped onto them, so the door reads as facets beside the smooth skin, open or shut. Two doors a side
    # on the main bay, forward and aft as on the F-104 (p. 1-47), which hinges both outboard. Here the forward door
    # hinges at its front edge: its inner edge runs down the conformal trough's lip beside the rear ramp, then steps in
    # behind the ramp's end (patch_cells) over the skin the ramp's fade fans out, which the tyre passes through. The
    # aft door hinges inboard. The game holds every gear door open while the gear is down (LandingGear), where the
    # F-104's forward door recloses to a detent. The nose well's wide pair ends where the trough's front ramp
    # begins to move the skin's columns (stations.ramp_stations); behind it a narrow pair on the keel's columns, which
    # hold their even angles there (build_icarus.NOSE_SLOT_KEEL), lets the oleo out.
    "doors": [("gear_door_N_L", 4.08, 5.025, 0.0, 0.31, "outer", 40, 40, 88, "down"),
              ("gear_door_N2_L", 5.025, 5.30, 0.0, 0.085, "outer", 40, 40, 88, "down"),
              ("gear_door_main_L", 8.80, 9.077, 0.0, 0.0, "front", 40, 40, 80, "down", (92, 94, 84)),
              ("gear_door_flap_L", 9.077, 10.77, 0.17, 0.97, "inner", 40, 40, 95, "down")],
}
# The main leg's foot, along the swivel axis inboard of the wheel centre: tools/gear_fold_solve.py --solution ...
# --axis-pin sweeps it; from 0.16 m out the tyre clears its own leg as it twists, 0.058 m here.
PIN_REACH = 0.20
# The main leg's hardware about its skeleton (main_points), metres, left leg, gear down; main_solids builds it.
# - leg: the forged I-section, stations (fraction from the trunnion to the foot, half-width of its broad face, half-depth
#   of its flanges). The broad face lies square to the hinge, which stows it flat in the well, where the room is across
#   the keel, not up and down. flange and web are the thicknesses, ribs the stations of the ribs that pocket the web,
#   and shift (along u, v) moves the section up and inboard (stowed), off the door where the belly rises outboard,
#   easing over the last third of the leg to (shift[2], 0), clear of the carrier as it swivels. From twist_from down the leg twists and flattens into a
#   tongue square to the swivel axis, which the foot's boss (length along the axis, radius) can hold: the carrier
#   turns against the boss's outboard face.
# - Everything the carrier and the unsprung hold lies within about 0.04 m of the foot across the swivel axis (along X,
#   gear down): stowed, that is height, between the well's floor (z -0.27) and the tyre over it. And as the carrier
#   swivels its aft side turns up into the leg, so it holds its parts above and ahead of the axle.
# - oleo: the shock strut stands on the carrier, its axis (dx, dy) from the foot, its gland and head heights above it,
#   the piston on the unsprung. head is as tall as it can stand: stowed, it lies across the well toward the keel. So
#   the piston shows `gland` less the clamp's height at full extension and is hidden in the cylinder for the first
#   `head - gland` of the stroke; beyond, to the bump stop (GEAR_STROKE), its top comes out of the head.
# - guide: the torque guide, a rod on the axle yoke sliding through an ear on the strut's gland: the game slides the
#   unsprung straight up, so the links of a scissor, which would have to turn, cannot follow it.
# - actuator: the retraction actuator from a lug on the leg's forward edge at `at` of the way down to its airframe eye
#   on the hinge line, `eye` past the trunnion, so it turns with the leg as one piece; r its cylinder's.
MAIN_LEG = {
    "leg": ((0.03, 0.040, 0.032), (0.14, 0.085, 0.034), (0.55, 0.064, 0.030), (0.86, 0.048, 0.026),
            (0.97, 0.040, 0.016)),
    "flange": 0.016, "web": 0.012, "ribs": (0.30, 0.55, 0.78), "shift": (0.020, -0.030, 0.008), "foot": (0.036, 0.052),
    "twist_from": 0.70,
    "trunnion": {"pin": (-0.080, 0.070), "bore": (0.036, 0.040), "bearings": (0.040, 0.060, 0.034)},
    "oleo": {"dx": 0.035, "dy": 0.040, "gland": 0.180, "head": 0.355, "r": 0.042, "piston_r": 0.026},
    "guide": {"dx": 0.066, "dy": 0.0, "r": 0.009, "top": 0.25},
    "actuator": {"at": 0.50, "eye": 0.105, "r": 0.035},
}
GEAR_STROKE = 0.30  # the bump stop above the free wheel (IcarusAuthor.Gear.cs GearStroke): the piston's slide
DOOR_SKIN = 0.006  # the door's inner face sits this far inside its outer skin
DOOR_GAP = 0.002  # and its free edges stand this far in from the hole's, so it swings clear of the skin
DOOR_CLEAR = 0.004  # a door's tray kept this far from the stowed gear it closes on
CARVE_STEP = 0.005  # and looks for that gear this often across each cell: a corner of a main leg stows 4 mm inside the flap
MIN_SKIN = 0.003  # the thinnest a door's skin gets where the gear lies against it
# Object names the other modules and the Unity author build against, per leg N, L and R: the sprung leg is
# gear_leg_<leg>_visible and the wheel gear_wheel_<leg>_visible; the piston and axle slide as gear_unsprung_<leg>,
# and the main gear's carrier is gear_arm_<leg>.
UNSPRUNG, ARM = "gear_unsprung_", "gear_arm_"
LEGS = ("N", "L", "R")
# Triangles per component: target and cap (budget.py sums them). A leg counts its sprung, unsprung, arm and wheel; the
# main legs' caps take what the nose leg's leaves.
BUDGET = {
    **{"leg_" + leg: {"target": target, "cap": cap,
                      "objects": ("gear_leg_" + leg, "gear_wheel_" + leg, UNSPRUNG + leg, ARM + leg)}
       for leg, target, cap in (("N", 1150, 1200), ("L", 1750, 1800), ("R", 1750, 1800))},
    # Built to the speed brakes' standard (rim, ribs, stringer, hinge knuckles): the stock F-99's bay doors run 824
    # triangles each, the Ifrit's gear doors 2,266 in all. Taking all of the skin's rings and columns added about 1,000,
    # nearly all on the flaps; the intakes' caps gave up the 1,000.
    "doors": {"target": 4950, "cap": 5000, "objects": ("gear_door_",)},
}
DOOR_TRIS = (32, 1250)  # each door, outer skin and inner trim (Exterior rule 22, raised for the detailed doors)
# Stock wheel layout, measured on _donotship/Texture2D/aircraft_wheels_b_PLACEHOLDER.png (512 px): the tread strip
# runs down the left edge (u from, u to), and each hub face maps onto one of the drawn hubs (centre px, radius px).
WHEEL_UV = {"tread": (0.0, 0.40),
            "main": {"out": (295, 240, 88), "in": (297, 421, 88)},
            "nose": {"out": (432, 328, 64), "in": (438, 88, 61)}}
TYRE_TOL, BOX_TOL = 0.001, 0.03  # the tyre's centre and radius, and the leg's break-off box (gear.check)
STOW_TOL = 0.001  # the main wheel's stowed centre (m) and axle (radians off vertical) against GEAR["main"]["stowed"]
SWEEP_STEP = 0.01  # largest vertex move between two poses of the retraction sweep
TYRE_CLEAR = 0.01  # least gap from a tyre's tread and sidewalls to the rest of its own leg
CLOSEUPS = {}


def build(p, mats):
    """The three legs; the doors are cut from the fuselage skin earlier (cut_doors)."""
    return main_leg(1) + main_leg(-1) + nose_leg()

# --- frames --------------------------------------------------------------------------------------------------------

def frame_on(origin, x_axis):
    x_axis = x_axis.normalized()
    ref = Vector((0, 1, 0)) if abs(x_axis.y) < 0.9 else Vector((0, 0, 1))
    y_axis = (ref - x_axis * x_axis.dot(ref)).normalized()
    return Matrix.Translation(origin) @ Matrix((x_axis, y_axis, x_axis.cross(y_axis))).transposed().to_4x4()


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


def turn(point, origin, axis, degrees):
    return origin + Matrix.Rotation(math.radians(degrees), 3, axis) @ (point - origin)


def mirrored(v, side):
    return Vector((side * v.x, v.y, v.z))


# --- the main legs -------------------------------------------------------------------------------------------------

def main_points(side=1):
    """The main leg's skeleton, gear down, world space: wheel centre C, the leg's foot A on the swivel axis PIN_REACH
    inboard of C (any point on that axis turns the wheel alike, so the foot takes the swivel and the stub axle runs
    from it along the axis into the hub), pivot P, and the hinge and swivel axes (a right leg turns the same angles
    about the mirrored axes reversed, since a mirror reverses a rotation's sense)."""
    g = GEAR["main"]
    C = bi.P(g["wheel_s"], g["wheel_x"], GEAR["ground_z"] + g["wheel_d"] / 2)
    sw = Vector(g["swivel"]).normalized()
    A = C - sw * PIN_REACH * (1 if sw.x > 0 else -1)
    pts = {"C": C, "A": A, "P": bi.P(*g["pivot"])}
    pts = {k: mirrored(v, side) for k, v in pts.items()}
    flip = lambda v: Vector(v).normalized() if side > 0 else -mirrored(Vector(v).normalized(), -1)
    pts["hinge"], pts["swivel"] = flip(g["hinge"]), flip(g["swivel"])
    return pts


def stowed(point, k, swivel=True):
    """Where a point of the main leg (k = main_points) lies with the gear up; swivel=False for the sprung leg."""
    g = GEAR["main"]
    if swivel:
        point = turn(point, k["A"], k["swivel"], g["swivel_deg"])
    return turn(point, k["P"], k["hinge"], g["fold_deg"])


def leg_foot(k):
    """Where the forged leg ends, left leg: the middle of the foot's boss round the swivel axis."""
    return k["A"] - k["swivel"] * MAIN_LEG["foot"][0] / 2


def leg_frame(k):
    """The forged leg's axes, left leg: l along it from the trunnion to the foot, u across its flanges (the hinge's
    part square to the leg; stowed, down) and v across its broad face (stowed, outboard)."""
    l = (leg_foot(k) - k["P"]).normalized()
    u = (k["hinge"] - l * l.dot(k["hinge"])).normalized()
    return l, u, l.cross(u)


def leg_station(f):
    """(f, half-width, half-depth) of the forged leg at fraction f, between its MAIN_LEG stations."""
    st = MAIN_LEG["leg"]
    for (f0, w0, d0), (f1, w1, d1) in zip(st, st[1:]):
        if f <= f1:
            t = max(0.0, (f - f0) / (f1 - f0))
            return f, w0 + (w1 - w0) * t, d0 + (d1 - d0) * t
    return st[-1]


def leg_centre(k, f):
    """The forged leg's section centre at fraction f, left leg."""
    l, u, v = leg_frame(k)
    su, sv, foot = MAIN_LEG["shift"]
    t = min(1.0, 3 * (1 - f))
    return k["P"] + (leg_foot(k) - k["P"]) * f - u * (foot + (su - foot) * t) + v * sv * t


def leg_axes(k, f):
    """The forged leg's (u, v) at fraction f, left leg: leg_frame's, turned about the leg from twist_from down so its
    broad face ends square to the swivel axis."""
    l, u, v = leg_frame(k)
    p = l.cross(k["swivel"]).normalized()
    p = p if p.dot(v) > 0 else -p
    t = min(1.0, max(0.0, (f - MAIN_LEG["twist_from"]) / (1.0 - MAIN_LEG["twist_from"])))
    turn_ = Matrix.Rotation(math.atan2(v.cross(p).dot(l), v.dot(p)) * t * t * (3 - 2 * t), 3, l)
    return turn_ @ u, turn_ @ v


def actuator_ends(k):
    """The retraction actuator's eyes, left leg (k = main_points()): on its lug off the leg's forward flange (-v), and
    on the hinge line past the trunnion's aft bearing, where it turns about its own eye as the leg folds."""
    m = MAIN_LEG
    l, u, v = leg_frame(k)
    f, w, _ = leg_station(m["actuator"]["at"])
    lo = leg_centre(k, f) - u * 0.012 - v * (w + 0.036)
    return lo, k["P"] - k["hinge"] * m["actuator"]["eye"]


def main_solids():
    """Left main leg meshes, gear down, world space, after the F-104's (flight manual LR1-14404-1, pp. 1-46 to 1-48;
    MAP brochure p. 13; Brewczynski and Tora 2014, fig. 1), laid out by MAIN_LEG: sprung (the trunnion pin and its
    bearings, the forged I-section leg from its bore on the pin to the foot's boss round the swivel, its web pocketed
    between ribs, the retraction actuator and two hydraulic lines down the leg), arm (the wheel carrier: its knuckle
    in the foot, the neck up to the shock strut's gland, the strut's cylinder and the torque guide's ear), unsprung
    (the stub axle and its yoke, the arm across to the strut's chrome piston, the torque guide's rod, the brake) and
    wheel."""
    k = main_points()
    m = MAIN_LEG
    P, A, C = k["P"], k["A"], k["C"]
    h, sw = k["hinge"], k["swivel"]
    out = sw if sw.x > 0 else -sw  # along the swivel axis toward the wheel
    l, u, v = leg_frame(k)
    gear, chrome = "Fighter1_gear", "Mirror"
    sprung = solids.Solids()
    tr = m["trunnion"]
    solids.cylinder(sprung, P + h * tr["pin"][0], P + h * tr["pin"][1], 0.024, 8, chrome)  # trunnion pin
    solids.cylinder(sprung, P - h * tr["bore"][0], P + h * tr["bore"][0], tr["bore"][1], SEG_LEG, gear)  # the leg's bore
    b0, b1, br = tr["bearings"]
    for s in (-1, 1):  # its bearings, round about the hinge so they read as fixed while the leg turns
        solids.cylinder(sprung, P + h * (s * b0), P + h * (s * b1), br, SEG_LEG, gear)
    centre = lambda f: leg_centre(k, f)
    fl, web = m["flange"], m["web"]

    def member(span):
        """One member of the I-section: span(w, d) gives its (u from, u to, v from, v to) at a station."""
        rings = []
        for f, w, d in m["leg"]:
            u0, u1, v0, v1 = span(w, d)
            uf, vf = leg_axes(k, f)
            rings.append([centre(f) + uf * a + vf * b for a, b in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))])
        sprung.loft(rings, gear)

    member(lambda w, d: (-d, d, w - fl, w))  # the flanges
    member(lambda w, d: (-d, d, -w, -w + fl))
    member(lambda w, d: (-web / 2, web / 2, -w + fl, w - fl))  # the web
    for f in m["ribs"]:
        _, w, d = leg_station(f)
        solids.box(sprung, centre(f), (l, *leg_axes(k, f)), (0.006, d * 0.85, w - fl / 2), gear)
    solids.cylinder(sprung, A - out * m["foot"][0], A - out * 0.002, m["foot"][1], SEG_LEG, gear)  # the foot's boss
    lo, hi = actuator_ends(k)
    d = (hi - lo).normalized()
    body = 0.58 * (hi - lo).length
    at, w, _ = leg_station(m["actuator"]["at"])
    ar = m["actuator"]["r"]
    solids.beam(sprung, centre(at) - v * (w - 0.004), lo, l, 0.040, 0.020, gear)  # its lug
    solids.lathe(sprung, hi - d * 0.022, -d, [(0.0, ar - 0.008), (0.016, ar), (body - 0.016, ar), (body, ar - 0.006)], 10,
                 gear)  # cylinder
    solids.cylinder(sprung, hi - d * (body + 0.012), lo + d * 0.018, ar * 0.45, 8, chrome)  # rod
    for e, axis, half in ((hi, h, 0.016), (lo, u, 0.011)):
        solids.cylinder(sprung, e - axis * half, e + axis * half, 0.019, 8, gear)  # eyes
        solids.cylinder(sprung, e - axis * (half + 0.008), e + axis * (half + 0.008), 0.007, 6, chrome)  # pins
    for dv in (-0.016, 0.006):  # hydraulic lines down the web's forward pocket, through the ribs, to the foot
        pts = [centre(f) + leg_axes(k, f)[0] * (web / 2 + 0.0055) + leg_axes(k, f)[1] * dv for f in (0.06, 0.30, 0.62, 0.86)]
        solids.tube(sprung, pts, 0.0055, 5, gear)
    uf, vf = leg_axes(k, 0.87)
    solids.box(sprung, centre(0.87) + uf * (web / 2 + 0.008) - vf * 0.005, (l, uf, vf), (0.014, 0.010, 0.022), gear)

    arm = solids.Solids()
    ol, gd = m["oleo"], m["guide"]
    O = A + X * ol["dx"] + Y * ol["dy"]  # the strut's axis at the foot's height
    G = A + X * gd["dx"] + Y * gd["dy"]  # the torque guide's
    solids.cylinder(arm, A + out * 0.004, A + out * 0.050, 0.046, SEG_LEG, gear)  # knuckle, turning against the boss
    solids.beam(arm, A + out * 0.025 + Z * 0.035 - Y * 0.012, O + Z * (ol["gland"] + 0.011) - Y * (ol["r"] + 0.004), X,
                0.040, 0.022, gear)  # neck up the strut's forward side to its gland
    lift = ol["head"] - ol["gland"]
    solids.lathe(arm, O + Z * ol["gland"], Z, [(0.0, ol["piston_r"] + 0.002), (0.0, ol["r"] + 0.006),
                                              (0.022, ol["r"] + 0.006), (0.022, ol["r"]), (lift - 0.016, ol["r"]),
                                              (lift, ol["r"] - 0.008)], 10, gear)  # gland nut, cylinder, head
    solids.beam(arm, O + Z * (ol["gland"] + 0.011), G + Z * (ol["gland"] + 0.011), Z, 0.016, 0.018, gear)  # guide ear
    solids.cylinder(arm, G + Z * (ol["gland"] + 0.002), G + Z * (ol["gland"] + 0.020), 0.017, 8, gear)

    unsprung = solids.Solids()
    solids.cylinder(unsprung, A + out * 0.052, C + out * 0.03, 0.028, 8, chrome)  # stub axle, through the hub
    yoke = A + out * 0.074
    a, rise, fwd = solids.basis(out, Z)
    solids.box(unsprung, yoke + rise * 0.012, (a, rise, fwd), (0.022, 0.042, 0.038), gear)  # its yoke
    solids.beam(unsprung, yoke + Y * 0.02 + Z * 0.03, O + Z * 0.03, Z, 0.03, 0.028, gear)  # arm across to the strut
    solids.cylinder(unsprung, O + Z * 0.008, O + Z * 0.052, ol["piston_r"] + 0.010, 10, gear)  # piston clamp
    solids.cylinder(unsprung, O + Z * 0.052, O + Z * (ol["gland"] + 0.012), ol["piston_r"], 10, chrome)  # piston
    solids.cylinder(unsprung, G + Z * 0.06, G + Z * gd["top"], gd["r"], 6, chrome)  # torque guide rod
    W = GEAR["main"]["wheel_w"] / 2
    solids.cylinder(unsprung, C - X * (0.5 * W + 0.022), C - X * (0.5 * W - 0.002), 0.09, SEG_LEG, gear)  # brake, in the hub's dish
    wheel = wheel_solid(C, X, "main")
    return sprung, arm, unsprung, wheel


def main_leg(side):
    """One main leg's objects; the right leg is the left one mirrored."""
    sd = "L" if side > 0 else "R"
    k = main_points(side)
    meshes = [mesh_from(s, side) for s in main_solids()]
    g = GEAR["main"]
    parts = bi.hinged("gear_leg_" + sd, rename(meshes[0], "gear_leg_" + sd), frame_on(k["P"], k["hinge"]))
    parts[0]["travel_deg"] = g["fold_deg"]
    swivel = bi.hinged("gear_wheel_" + sd, rename(meshes[3], "gear_wheel_" + sd), frame_on(k["A"], k["swivel"]),
                       parent=parts[0])
    swivel[0]["travel_deg"] = g["swivel_deg"]
    swivel[0]["stowed_wheel"] = list(stowed(k["C"], k))  # IcarusAuthor.Gear.cs picks the turns' senses from it
    for obj, name in ((meshes[1], ARM + sd), (meshes[2], UNSPRUNG + sd)):
        ride(rename(obj, name), swivel[0])
    for obj in meshes[1:]:
        obj["role"] = "visual"  # no collider or LOD1 hull: these move against the part they belong to
    return parts + swivel + meshes[1:3]


# --- the nose leg --------------------------------------------------------------------------------------------------

def nose_points():
    """The nose leg's skeleton, gear down: wheel centre C, fork crown, gland G, oleo top T, pivot P, the hinge (-X: a
    positive turn folds it forward) and the twist axis up the piston."""
    g = GEAR["nose"]
    C = bi.P(g["wheel_s"], g["wheel_x"], GEAR["ground_z"] + g["wheel_d"] / 2)
    crown = C + Z * (g["wheel_d"] / 2 + g["crown_gap"] + 0.015)
    G = crown + Z * (0.015 + g["piston"])
    return {"C": C, "crown": crown, "G": G, "T": G + Z * g["oleo"], "P": bi.P(*g["pivot"]),
            "hinge": -X, "twist": Z.copy()}


def nose_stowed(point, k, twist=True):
    g = GEAR["nose"]
    if twist:
        point = turn(point, k["C"], k["twist"], g["twist_deg"])
    return turn(point, k["P"], k["hinge"], g["fold_deg"])


def landing_lamp():
    """The landing lamp's lens centre, gear down: just ahead of the oleo's gland collar, under the light_landing
    empty (lights.py). Any further forward and it rises above the well's roof as the leg folds."""
    g = GEAR["nose"]
    return bi.P(g["wheel_s"] - 0.085, 0.0, GEAR["ground_z"] + g["wheel_d"] + 0.15)


def nose_solids():
    """Nose leg meshes, gear down, world space: sprung (yoke, oleo, landing lamp), unsprung (piston, fork) and wheel."""
    g = GEAR["nose"]
    k = nose_points()
    C, crown, G, T, P = k["C"], k["crown"], k["G"], k["T"], k["P"]
    gear, chrome = "Fighter1_gear", "Mirror"
    sprung = solids.Solids()
    solids.cylinder(sprung, P - X * 0.10, P + X * 0.10, 0.03, SEG_LEG, gear)  # trunnion
    solids.beam(sprung, P + Z * 0.01, T + Z * 0.02, X, 0.10, 0.05, gear)  # yoke from the trunnion to the oleo top
    solids.lathe(sprung, G, Z, [(0.0, 0.056), (0.03, 0.056), (0.03, 0.05), ((T - G).length, 0.05),
                                ((T - G).length + 0.03, 0.035)], SEG_LEG, gear)  # oleo, gland collar at its foot
    eye = G - Y * 0.085 + Z * 0.03  # upper torque link, ahead of the oleo
    solids.beam(sprung, G - Y * 0.045 + Z * 0.03, eye, X, 0.022, 0.02, gear)
    solids.cylinder(sprung, eye - Z * 0.012, eye + Z * 0.012, 0.014, 8, gear)
    lamp = landing_lamp()  # on a bracket, its lens on Mirror
    solids.lathe(sprung, lamp + Y * 0.03, -Y, [(0.0, 0.03), (0.0, 0.045), (0.045, 0.045), (0.05, 0.04)], 10, gear,
                 cap_mats=(gear, chrome))
    solids.beam(sprung, G - Y * 0.04 + Z * 0.015, lamp + Y * 0.03, X, 0.02, 0.016, gear)
    unsprung = solids.Solids()
    solids.cylinder(unsprung, crown + Z * 0.015, G + Z * 0.05, 0.037, SEG_LEG, chrome)  # piston
    solids.box(unsprung, crown, (X, Y, Z), (0.11, 0.035, 0.015), gear)  # fork crown
    for sx in (-1, 1):
        x = sx * (g["wheel_w"] / 2 + 0.022)
        solids.beam(unsprung, crown + X * x, Vector((x, C.y, C.z - 0.02)), Y, 0.035, 0.018, gear)  # fork arm
    solids.cylinder(unsprung, C - X * 0.102, C + X * 0.102, 0.02, 8, gear)  # axle
    solids.beam(unsprung, crown - Y * 0.035, crown - Y * 0.085, X, 0.02, 0.025, gear)  # lower link lug
    solids.cylinder(unsprung, crown - Y * 0.085, Vector((0.0, eye.y, eye.z + 0.05)), 0.008, 6, gear)
    return sprung, unsprung, wheel_solid(C, X, "nose")


def nose_leg():
    g = GEAR["nose"]
    k = nose_points()
    sprung, unsprung, wheel = [mesh_from(s, 1) for s in nose_solids()]
    parts = bi.hinged("gear_leg_N", rename(sprung, "gear_leg_N"), frame_on(k["P"], k["hinge"]))
    parts[0]["travel_deg"] = g["fold_deg"]
    twist = bi.hinged("gear_wheel_N", rename(wheel, "gear_wheel_N"), frame_on(k["C"], k["twist"]), parent=parts[0])
    twist[0]["travel_deg"] = g["twist_deg"]
    twist[0]["stowed_wheel"] = list(nose_stowed(k["C"], k))
    ride(rename(unsprung, UNSPRUNG + "N"), twist[0])
    for obj in (wheel, unsprung):
        obj["role"] = "visual"
    return parts + twist + [unsprung]


# --- wheels --------------------------------------------------------------------------------------------------------

def tyre_profile(R, W, rim):
    """(x along the axle, r) round the tyre section from the outboard bead: sidewall, a well rounded shoulder (the
    stowed tyre's corners are what touch the engine and the wing root), crown; the tread is the texture's."""
    half = [(0.86 * W, rim), (W, rim + 0.45 * (R - rim)), (0.86 * W, R - 0.22 * (R - rim)), (0.58 * W, R - 0.06 * (R - rim)),
            (0.25 * W, R)]
    return half + [(-x, r) for x, r in half[::-1]]


HUB = [(0.55, 0.25), (0.35, 0.333), (0.30, 0.833), (0.90, 0.933), (0.93, 1.056), (-0.93, 1.056), (-0.90, 0.933),
       (-0.50, 0.833), (-0.50, 0.25)]  # (x / half width, r / rim): a dished outboard face, a flat inboard one


def wheel_solid(centre, outboard, kind):
    """Tyre and hub about the axle `outboard`, with UVs on the stock wheel layout: (verts, faces, uvs per face)."""
    g = GEAR[kind]
    R, W, rim = g["wheel_d"] / 2, g["wheel_w"] / 2, g["rim_r"]
    a, u, w = solids.basis(outboard, Y)
    ring = lambda x, r, i, n: centre + a * x + (u * math.cos(2 * math.pi * i / n) + w * math.sin(2 * math.pi * i / n)) * r
    verts, faces, uvs = [], [], []
    tyre = tyre_profile(R, W, rim)
    arc = [0.0]
    for (x0, r0), (x1, r1) in zip(tyre, tyre[1:]):
        arc.append(arc[-1] + math.hypot(x1 - x0, r1 - r0))
    u0, u1 = WHEEL_UV["tread"]
    tu = [u0 + (u1 - u0) * t / arc[-1] for t in arc]
    n = len(tyre)
    for x, r in tyre:
        verts += [ring(x, r, i, SEG_TYRE) for i in range(SEG_TYRE)]
    for j in range(n):  # the last band closes the section across the bead, inside the hub
        jn = (j + 1) % n
        for i in range(SEG_TYRE):
            faces.append((j * SEG_TYRE + i, j * SEG_TYRE + (i + 1) % SEG_TYRE, jn * SEG_TYRE + (i + 1) % SEG_TYRE,
                          jn * SEG_TYRE + i))
            v0, v1 = i / SEG_TYRE, (i + 1) / SEG_TYRE
            ua, ub = tu[j], tu[jn] if jn else u1
            uvs.append(((ua, v0), (ua, v1), (ub, v1), (ub, v0)))
    base = len(verts)
    for x, r in HUB:
        verts += [ring(x * W, r * rim, i, SEG_HUB) for i in range(SEG_HUB)]
    discs = WHEEL_UV[kind]

    def disc_uv(x, r, i):
        cx, cy, cr = discs["out" if x >= 0 else "in"]
        t = 2 * math.pi * i / SEG_HUB
        f = r / 1.056 * cr
        return ((cx + f * math.cos(t)) / 512, 1 - (cy + f * math.sin(t)) / 512)

    for j in range(len(HUB) - 1):
        x_face = HUB[j][0] + HUB[j + 1][0]
        for i in range(SEG_HUB):
            ids = (j * SEG_HUB + i, j * SEG_HUB + (i + 1) % SEG_HUB, (j + 1) * SEG_HUB + (i + 1) % SEG_HUB, (j + 1) * SEG_HUB + i)
            faces.append(tuple(base + q for q in ids))
            sx = 1 if x_face >= 0 else -1
            uvs.append(tuple(disc_uv(sx, HUB[q // SEG_HUB][1], q % SEG_HUB) for q in ids))
    for j, sx in ((0, 1), (len(HUB) - 1, -1)):  # the bore caps
        ids = [j * SEG_HUB + i for i in range(SEG_HUB)]
        ids = ids[::-1] if sx > 0 else ids
        faces.append(tuple(base + q for q in ids))
        uvs.append(tuple(disc_uv(sx, HUB[j][1], q % SEG_HUB) for q in ids))
    return verts, faces, uvs


# --- objects -------------------------------------------------------------------------------------------------------

def mesh_from(shape, side):
    """A mesh object from Solids or a wheel (verts, faces, uvs), built for the left side and mirrored for the right."""
    if isinstance(shape, solids.Solids):
        verts, faces, mats, uvs = shape.verts, shape.faces, shape.mats, None
    else:
        verts, faces, uvs = shape
        mats = ["Aircraft_wheels"] * len(faces)
    verts = [mirrored(v, side) for v in verts]
    if side < 0:
        faces = [f[::-1] for f in faces]
        uvs = [uv[::-1] for uv in uvs] if uvs else None
    names = list(dict.fromkeys(mats))
    me = bpy.data.meshes.new("gear_part")
    me.from_pydata([tuple(v) for v in verts], [], faces)
    for name in names:
        me.materials.append(bpy.data.materials[name])
    me.polygons.foreach_set("material_index", [names.index(m) for m in mats])
    if uvs:
        layer = me.uv_layers.new(name="UVMap")
        for poly, corners in zip(me.polygons, uvs):
            for li, uv in zip(poly.loop_indices, corners):
                layer.data[li].uv = uv
    me.validate()
    me.update()
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(40))
    obj = bpy.data.objects.new("gear_part", me)
    bi.TARGET.objects.link(obj)
    return obj


def rename(obj, name):
    obj.name = obj.data.name = name
    return obj


def ride(obj, parent):
    """Hang a world-space mesh object from parent, keeping it in place."""
    obj.data.transform(parent.matrix_world.inverted())
    obj.parent = parent
    obj.matrix_world = parent.matrix_world.copy()


# --- doors ---------------------------------------------------------------------------------------------------------

def skin_grid(fuselage):
    """The loft's rings: station of each ring, and vertex index of ring j, point k (the tip is vertex 0)."""
    n = (len(fuselage.data.vertices) - 1) // bi.RING
    stations = [fuselage.data.vertices[1 + j * bi.RING].co.y + bi.S0 for j in range(n)]
    return stations, lambda j, k: 1 + j * bi.RING + k % bi.RING


def door_patch(fuselage, spec):
    """Rings j0..j1 and ring points k0..k1 (left side, k counting up from the bottom of the ring) of a door: the ring
    points from the spec's x limits at the middle ring, or its own (k0, k1) where the skin's columns bunch there."""
    name, s0, s1, x0, x1 = spec[:5]
    stations, vid = skin_grid(fuselage)
    j0 = min(range(len(stations)), key=lambda j: abs(stations[j] - s0))
    j1 = min(range(len(stations)), key=lambda j: abs(stations[j] - s1))
    mid = (j0 + j1) // 2
    bottom = 3 * bi.RING // 4
    if len(spec) > 10:
        return (j0, j1) + tuple(spec[10][:2])
    xs = {k: fuselage.data.vertices[vid(mid, k)].co.x for k in range(bottom, bottom + bi.RING // 4)}
    k0 = min(k for k, x in xs.items() if x >= x0 - 1e-6)
    k1 = max(k for k, x in xs.items() if x <= x1 + 1e-6)
    return j0, j1, k0, k1


def step_ring(spec, j0, j1, k0, co):
    """Where a stepped door's inner edge turns, or None. A third explicit column steps it: down k0 to the ring where
    that column's point comes nearest k0's (the trough's rear ramp ends there, gathering its columns to within a few
    millimetres), then down the third column, so the door takes in the skin the ramp's fade fans out behind it."""
    if len(spec) < 11 or len(spec[10]) < 3:
        return None
    return min(range(j0, j1 + 1), key=lambda j: (co(j, spec[10][2]) - co(j, k0)).length)


def patch_cells(fuselage, spec, j0, j1, k0, k1, vid):
    """The patch's (ring, ring point) pairs, left side, a stepped door's (step_ring) included."""
    step = step_ring(spec, j0, j1, k0, lambda j, k: fuselage.data.vertices[vid(j, k)].co)
    inner = lambda j: spec[10][2] if step is not None and j >= step else k0
    return [(j, k) for j in range(j0, j1 + 1) for k in range(inner(j), k1 + 1)]


def patch_row(spec, j, step, k0, ks, co):
    """A door grid's row on ring j: the skin's points ks. A stepped door's rows run from its third column from the
    step on; ahead of it the extra points are spread along the ring's edge out of k0, so every row has as many."""
    if step is None:
        return [co(j, k) for k in ks]
    aft, k1 = spec[10][2], ks[-1]
    if j >= step:
        return [co(j, k) for k in range(aft, k1 + 1)]
    n = k0 - aft
    return [co(j, k0).lerp(co(j, k0 + 1), i / (n + 1)) for i in range(n + 1)] + [co(j, k) for k in range(k0 + 1, k1 + 1)]


def kept(a, b, n):
    """n + 1 indices from a to b, ends included."""
    return sorted({round(a + (b - a) * i / n) for i in range(n + 1)})


def stowed_tree():
    """Every leg's meshes as one world-space BVH tree in the stowed pose, built from the solids before the legs
    exist, so the doors' trays can be carved round what they close on."""
    from mathutils.bvhtree import BVHTree

    verts, faces = [], []

    def add(shape, place):
        if isinstance(shape, solids.Solids):
            vs, fs = shape.verts, shape.faces
        else:
            vs, fs = shape[0], shape[1]
        base = len(verts)
        verts.extend(place(Vector(v)) for v in vs)
        faces.extend(tuple(base + i for i in f) for f in fs)

    k = main_points()
    sprung, arm, unsprung, wheel = main_solids()
    for side in (1, -1):
        add(sprung, lambda v, side=side: mirrored(stowed(v, k, swivel=False), side))
        for part in (arm, unsprung, wheel):
            add(part, lambda v, side=side: mirrored(stowed(v, k), side))
    kn = nose_points()
    sprung, unsprung, wheel = nose_solids()
    add(sprung, lambda v: nose_stowed(v, kn, twist=False))
    for part in (unsprung, wheel):
        add(part, lambda v: nose_stowed(v, kn))
    return BVHTree.FromPolygons(verts, faces)


def hole(fuselage, spec, edges, vid):
    """Shape a door's hole in the skin, both sides: the patch (rings j0..j1, ring points k0..k1, a door starting where
    another ends sharing its edge through edges), its kept rows js and columns ks, the hole's edge snapped onto them,
    the hinge edge put on a straight line and, for a hinge along a column, the ends squared to it. A "front" hinge
    runs along the patch's first ring; its side edges keep the skin's columns. Returns j0, j1, k0, k1, js, ks."""
    rows, cols, hinge_edge = spec[6], spec[7], spec[5]
    j0, j1, k0, k1 = door_patch(fuselage, spec)
    k0 = edges.get(spec[1:4], k0)
    edges[spec[1:3] + (spec[4],)] = k1
    js, ks = kept(j0, j1, rows), kept(k0, k1, cols)
    for side in (1, -1):  # both sides' holes first: a left and a right door can share their centreline points
        vk = (lambda k: k) if side > 0 else (lambda k: bi.RING // 2 - k)  # ring point k mirrors to RING / 2 - k
        co = lambda j, k: fuselage.data.vertices[vid(j, vk(k))].co.copy()
        snap_edges(fuselage, j0, j1, k0, k1, js, ks, lambda j, k: vid(j, vk(k)))
        if hinge_edge == "front":
            straighten(fuselage, [vid(j0, vk(k)) for k in range(k0, k1 + 1)])
            continue
        hinge_k = k1 if hinge_edge == "outer" else k0
        straighten(fuselage, [vid(j, vk(hinge_k)) for j in range(j0, j1 + 1)])
        square_ends(fuselage, co(j0, hinge_k), co(j1, hinge_k), [[vid(j, vk(k)) for k in range(k0, k1 + 1)] for j in (j0, j1)])
    return j0, j1, k0, k1, js, ks


def cut_doors(fuselage):
    """Lift the door patches out of the fuselage skin into hinged doors, resampled to a coarse grid with the skin's
    hole edge snapped onto the grid's. Returns the parts."""
    stations, vid = skin_grid(fuselage)
    parts = []
    gear_up = stowed_tree()
    edges = {}
    for spec in GEAR["doors"]:
        name, hinge_edge = spec[0], spec[5]
        j0, j1, k0, k1, js, ks = hole(fuselage, spec, edges, vid)
        cells = patch_cells(fuselage, spec, j0, j1, k0, k1, vid)
        step = step_ring(spec, j0, j1, k0, lambda j, k: fuselage.data.vertices[vid(j, k)].co)
        for side in (1, -1):
            vk = (lambda k: k) if side > 0 else (lambda k: bi.RING // 2 - k)
            co = lambda j, k: fuselage.data.vertices[vid(j, vk(k))].co.copy()
            grid = [patch_row(spec, j, step, k0, ks, co) for j in js]
            if len(grid) == 2:  # a door one ring long gets a middle row, on its straight side edges
                grid.insert(1, [p.lerp(q, 0.5) for p, q in zip(*grid)])
            if hinge_edge == "front":  # the grid turned, so its first column is the hinge
                grid = [list(r) for r in zip(*grid)]
            grid = gapped(grid, "outer" if hinge_edge == "outer" else "inner")
            remove_faces(fuselage, {vid(j, vk(k)) for j, k in cells})
            col = -1 if hinge_edge == "outer" else 0
            a, b = grid[0][col], grid[-1][col]
            # The hinge runs just inside the door's outer skin: on the skin itself, the door's thickness would swing
            # round into the skin beside the hinge.
            inside = Vector((0.0, a.y, 0.3))
            inward = ((b - a).cross(grid[len(grid) // 2][1 if col == 0 else -2] - a)).normalized()
            inward = inward if inward.dot(inside - a) > 0 else -inward
            a, b = a + inward * DOOR_SKIN, b + inward * DOOR_SKIN
            door = door_panel(name.replace("_L", "_L" if side > 0 else "_R"), grid, len(grid[0]) - 1 if col else 0,
                              (a, b), inside, gear_up)
            made = bi.hinged(door.name, door, frame_on(a, (b - a) * side))
            bpy.context.view_layer.update()  # opening_travel reads the door's matrix_local, stale until an update
            # hangs down (on a front hinge, swinging down and forward), or folds out and over to lie under the wing root
            score = {"down": lambda pts: -min(q.z for q in pts),
                     "out": lambda pts: sum(abs(q.x) for q in pts) / len(pts)}[spec[9]]
            made[0]["travel_deg"] = opening_travel(made[0], spec[8], score)
            with posed({made[0].name: 1.0}):  # where IcarusAuthor.Gear.cs takes the opening's sense from
                made[0]["open_centre"] = list(sum(world_points(made[1]), Vector()) / len(made[1].data.vertices))
            parts += made
    return parts


def snap_edges(fuselage, j0, j1, k0, k1, js, ks, vid):
    """Move the skin points along the hole's edge onto the straight edges of the coarse door, so no gap opens."""
    verts = fuselage.data.vertices
    for line, fixed, kept_ids in (([(j, k0) for j in range(j0, j1 + 1)], "k", js),
                                  ([(j, k1) for j in range(j0, j1 + 1)], "k", js),
                                  ([(j0, k) for k in range(k0, k1 + 1)], "j", ks),
                                  ([(j1, k) for k in range(k0, k1 + 1)], "j", ks)):
        idx = [jk[0] if fixed == "k" else jk[1] for jk in line]
        for (j, k), i in zip(line, idx):
            if i in kept_ids:
                continue
            lo = max(q for q in kept_ids if q < i)
            hi = min(q for q in kept_ids if q > i)
            t = (i - lo) / (hi - lo)
            a = verts[vid(lo, k) if fixed == "k" else vid(j, lo)].co
            b = verts[vid(hi, k) if fixed == "k" else vid(j, hi)].co
            verts[vid(j, k)].co = a.lerp(b, t)


def straighten(obj, ids):
    """Put a hole's hinge edge (vertex ids along it) on the straight line between its ends: a door turns about a
    straight hinge, and a hinge edge that followed the skin's curve would swing into the skin beside it."""
    verts = obj.data.vertices
    a, b = verts[ids[0]].co.copy(), verts[ids[-1]].co.copy()
    d = (b - a).normalized()
    for i in ids[1:-1]:
        verts[i].co = a + d * d.dot(verts[i].co - a)


def square_ends(obj, a, b, ends):
    """Put the hole's two end edges (vertex ids, the first at a's end) square to the hinge a-b: an end edge askew to
    the hinge would sweep fore and aft through the skin as the door turns."""
    verts = obj.data.vertices
    d = (b - a).normalized()
    for ids, origin in zip(ends, (a, b)):
        for i in ids:
            move = d * d.dot(verts[i].co - origin)
            if abs(verts[i].co.x) < 1e-5:  # shared by a left and a right door: it stays on the centreline
                move.x = 0.0
            verts[i].co -= move


def remove_faces(obj, inside):
    """Delete the faces all of whose points are in `inside` (vertex indices)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if all(v.index in inside for v in f.verts)], context="FACES_ONLY")
    bm.to_mesh(obj.data)
    bm.free()


# part name -> (parent, dry mass kg); parts.full_tree adds these to its own
TREE = {"gear_door_flap_L": ("fuselage_mid", 0), "gear_door_flap_R": ("fuselage_mid", 0),
        "gear_door_N2_L": ("fuselage_forward", 0), "gear_door_N2_R": ("fuselage_forward", 0)}


def bay_doors(core):
    """BVH trees of the doors that close a structure core's gear bays beyond those parts.open_bays lists: the main
    bays' flaps and the aft nose doors, shut."""
    door = {"fuselage_mid": "gear_door_flap_%s_visible", "fuselage_forward": "gear_door_N2_%s_visible"}.get(core)
    return [tree(bpy.data.objects[door % sd]) for sd in ("L", "R")] if door else []


def gapped(grid, hinge_edge):
    """The door's outer grid drawn DOOR_GAP in from the hole on every edge but its hinge, so it swings clear."""
    rows, cols = len(grid), len(grid[0])
    hinge_col = cols - 1 if hinge_edge == "outer" else 0
    out = [[p.copy() for p in row] for row in grid]
    for i in range(rows):
        for j in range(cols):
            if i in (0, rows - 1):
                out[i][j] += (grid[1 if i == 0 else rows - 2][j] - grid[i][j]).normalized() * DOOR_GAP
            if j in (0, cols - 1) and j != hinge_col:
                out[i][j] += (grid[i][1 if j == 0 else cols - 2] - grid[i][j]).normalized() * DOOR_GAP
    return out


# A door's inner structure, in metres below its outer face: the rim round its edges, ribs across it every rib_pitch
# and a stringer along its middle stand frame_depth deep, the inner sheet between them sheet_depth (a honeycomb-cored
# door would be thicker; these follow the speed brakes, whose panels are the same skin). Hinge knuckles on the hinge
# line knuckle_inset from each end and at the middle, each with a lug back into the rim.
DOOR_SHAPE = {"frame_depth": 0.026, "sheet_depth": 0.005, "rim": 0.028, "rib": 0.014, "rib_pitch": 0.30, "cell": 0.15,
              "knuckle_r": 0.009, "knuckle_half": 0.016, "knuckle_inset": 0.07, "lug": 0.030}
# A shallower tray for the nose well's narrow pairs: a deep rim on a door that narrow swings into the well's edge.
DOOR_DEPTH = {"gear_door_N2": 0.010, "gear_door_flap": 0.012}


class Grid:
    """A door's outer skin, rows along the station by columns round the section, addressed in metres: u down its rows
    from the first, v across its columns from the first (each the mean of the grid's lines). Points are bilinear over
    the grid's cells, so the door's outer face is the grid itself. inside is a point inside the body."""

    def __init__(self, grid, inside):
        self.g, self.inside = grid, inside
        rows, cols = len(grid), len(grid[0])
        self.us = [0.0]
        for i in range(1, rows):
            self.us.append(self.us[-1] + sum((grid[i][j] - grid[i - 1][j]).length for j in range(cols)) / cols)
        self.vs = [0.0]
        for j in range(1, cols):
            self.vs.append(self.vs[-1] + sum((grid[i][j] - grid[i][j - 1]).length for i in range(rows)) / rows)
        self.length, self.width = self.us[-1], self.vs[-1]

    @staticmethod
    def locate(marks, x):
        i = next((k for k in range(len(marks) - 2) if x < marks[k + 1]), len(marks) - 2)
        return i, (x - marks[i]) / (marks[i + 1] - marks[i])

    def point(self, u, v):
        i, fi = self.locate(self.us, u)
        j, fj = self.locate(self.vs, v)
        g = self.g
        return g[i][j].lerp(g[i][j + 1], fj).lerp(g[i + 1][j].lerp(g[i + 1][j + 1], fj), fi)

    def normal(self, u, v, e=0.01):
        n = (self.point(u + e, v) - self.point(u - e, v)).cross(self.point(u, v + e) - self.point(u, v - e)).normalized()
        return n if n.dot(self.point(u, v) - self.inside) > 0 else -n

    def at(self, u, v, depth=0.0):
        return self.point(u, v) - self.normal(u, v) * depth


def split(a, b, cell):
    n = max(1, math.ceil((b - a) / cell - 1e-9))
    return [a + (b - a) * i / n for i in range(n + 1)]


def door_panel(name, grid, hinge_col, axis, inside, gear_up=None):
    """The door, world space, from its outer skin grid (gapped): skin on the outer face and edges, on jet_mechanical a
    tray inside with a rim, ribs and a middle stringer carved clear of the stowed gear (gear_up, a BVH tree), and the
    hinge knuckles on axis (two points on the hinge line) with their lugs."""
    sh = dict(DOOR_SHAPE, frame_depth=DOOR_DEPTH.get(name[:-2], DOOR_SHAPE["frame_depth"]))
    gd = Grid(grid, inside)
    L, W = gd.length, gd.width
    rows, cols = len(grid), len(grid[0])
    panel = Shell()
    outer = {(i, k): panel.vert(grid[i][k]) for i in range(rows) for k in range(cols)}
    for i in range(rows - 1):
        for k in range(cols - 1):
            panel.face([outer[i, k], outer[i + 1, k], outer[i + 1, k + 1], outer[i, k + 1]], 0,
                       away=inside)
    rim, rib = sh["rim"], sh["rib"] / 2
    n_ribs = max(1, round((L - 2 * rim) / sh["rib_pitch"]) - 1)
    rib_us = [L * (r + 1) / (n_ribs + 1) for r in range(n_ribs)]
    us = [0.0]
    cuts = [rim] + [x for c in rib_us for x in (c - rib, c + rib)] + [L - rim, L]
    for a, b in zip([0.0] + cuts[:-1], cuts):
        us += split(a, b, sh["cell"])[1:]
    mid = W / 2
    vs = [0.0]
    for a, b in zip([0.0, rim, mid - rib, mid + rib, W - rim], [rim, mid - rib, mid + rib, W - rim, W]):
        vs += split(a, b, sh["cell"])[1:]
    at = lambda marks, x: min(range(len(marks)), key=lambda i: abs(marks[i] - x))  # split() rounds its ends
    frame_u = {0, len(us) - 2} | {at(us, c - rib) for c in rib_us}
    frame_v = {0, at(vs, mid - rib), len(vs) - 2}

    def room(u, v):
        """How deep the tray may stand at (u, v): the stowed gear DOOR_CLEAR inside it, at most."""
        if gear_up is None:
            return 1.0
        hit = gear_up.ray_cast(gd.point(u, v), -gd.normal(u, v), sh["frame_depth"] + DOOR_CLEAR)
        return 1.0 if hit[0] is None else hit[3] - DOOR_CLEAR

    def depth(i, k):
        """A cell's depth: the rim, ribs and stringer stand frame_depth deep and the sheet sheet_depth, each carved
        back where the stowed gear lies close (the F-104G's main doors bulge for its tyres; these give way inside)."""
        d = sh["frame_depth"] if i in frame_u or k in frame_v else sh["sheet_depth"]
        free = min(room(u, v) for u in split(us[i], us[i + 1], CARVE_STEP) for v in split(vs[k], vs[k + 1], CARVE_STEP))
        return round(max(min(d, free), MIN_SKIN), 4)

    depths = {(i, k): depth(i, k) for i in range(len(us) - 1) for k in range(len(vs) - 1)}
    rim_cells = [c for c in depths if c[0] in (0, len(us) - 2) or c[1] in (0, len(vs) - 2)]
    rim_d = min(depths[c] for c in rim_cells)  # one depth all round, so the edges join it in one strip
    for c in rim_cells:
        depths[c] = rim_d
    depth = lambda i, k: depths[i, k]

    inner = {}

    def iv(i, k, d):
        if (i, k, d) not in inner:
            inner[i, k, d] = panel.vert(gd.at(us[i], vs[k], d))
        return inner[i, k, d]

    for i in range(len(us) - 1):
        for k in range(len(vs) - 1):
            d = depth(i, k)
            panel.face([iv(i, k, d), iv(i + 1, k, d), iv(i + 1, k + 1, d), iv(i, k + 1, d)], 1, toward=inside)
            if i + 2 < len(us) and depth(i + 1, k) != d:
                e = depth(i + 1, k)
                panel.face([iv(i + 1, k, d), iv(i + 1, k + 1, d), iv(i + 1, k + 1, e), iv(i + 1, k, e)], 1)
            if k + 2 < len(vs) and depth(i, k + 1) != d:
                e = depth(i, k + 1)
                panel.face([iv(i, k + 1, d), iv(i + 1, k + 1, d), iv(i + 1, k + 1, e), iv(i, k + 1, e)], 1)
    # the edges, skin, zipped from the outer grid's breaks to the rim's
    d = rim_d
    uo, vo = gd.us, gd.vs
    sides = [([(u, outer[i, 0]) for i, u in enumerate(uo)], [(u, iv(i, 0, d)) for i, u in enumerate(us)]),
             ([(u, outer[i, cols - 1]) for i, u in enumerate(uo)], [(u, iv(i, len(vs) - 1, d)) for i, u in enumerate(us)]),
             ([(v, outer[0, k]) for k, v in enumerate(vo)], [(v, iv(0, k, d)) for k, v in enumerate(vs)]),
             ([(v, outer[rows - 1, k]) for k, v in enumerate(vo)], [(v, iv(len(us) - 1, k, d)) for k, v in enumerate(vs)])]
    centre = gd.at(L / 2, W / 2, d / 2)
    for top, bottom in sides:
        a = b = 0
        while a < len(top) - 1 or b < len(bottom) - 1:
            if b == len(bottom) - 1 or (a < len(top) - 1 and top[a + 1][0] <= bottom[b + 1][0]):
                panel.face([top[a][1], top[a + 1][1], bottom[b][1]], 0, away=centre)
                a += 1
            else:
                panel.face([top[a][1], bottom[b + 1][1], bottom[b][1]], 0, away=centre)
                b += 1
    # hinge knuckles on the axis, each with a lug back into the rim
    a0, a1 = axis
    ax = (a1 - a0).normalized()
    hinge_v = 0.0 if hinge_col == 0 else W
    into = 1.0 if hinge_col == 0 else -1.0
    for u in (sh["knuckle_inset"], L / 2, L - sh["knuckle_inset"]):
        on = gd.point(u, hinge_v)
        c = a0 + ax * ax.dot(on - a0)
        side = (gd.at(u, hinge_v + into * sh["lug"], d) - c)
        side -= ax * ax.dot(side)
        side.normalize()
        up = ax.cross(side)
        panel.tube([ring(c + ax * t, side, up, sh["knuckle_r"], 8) for t in (-sh["knuckle_half"], sh["knuckle_half"])], 1)
        far = gd.at(u, hinge_v + into * (sh["lug"] + rim * 0.5), d)
        panel.box(lambda i, j, k: c + ax * (-0.010, 0.010)[i] + up * (-0.006, 0.006)[j] * 1.0
                  + (far - c) * (0.0, 1.0)[k] + side * 0.0, 1)
    return panel.realise(name, (bpy.data.materials["Icarus_Body"], bpy.data.materials["jet_mechanical"]))


# --- poses and checks ----------------------------------------------------------------------------------------------

@contextlib.contextmanager
def posed(fractions):
    """Turn hinges by a fraction of their travel_deg ({name: fraction}) for the length of a with-block. The transform
    is restored channel by channel: writing matrix_basis back decomposes it again and drifts the export's axes."""
    O = bpy.data.objects
    channels = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
    copy = lambda v: v if isinstance(v, str) else v.copy() if hasattr(v, "copy") else tuple(v)
    saved = {n: [(c, copy(getattr(O[n], c))) for c in channels] for n in fractions}
    for n, f in fractions.items():
        O[n].matrix_basis = O[n].matrix_basis @ Matrix.Rotation(math.radians(O[n]["travel_deg"] * f), 4, "X")
    bpy.context.view_layer.update()
    try:
        yield
    finally:
        for n, s in saved.items():
            for c, v in s:
                setattr(O[n], c, v)
        bpy.context.view_layer.update()


def leg_meshes(leg):
    O = bpy.data.objects
    names = ["gear_leg_%s_visible" % leg, "gear_wheel_%s_visible" % leg, UNSPRUNG + leg, ARM + leg]
    return [O[n] for n in names if n in O]


def doors_of(leg):
    if leg == "N":
        return ["gear_door_N_L", "gear_door_N_R", "gear_door_N2_L", "gear_door_N2_R"]
    return ["gear_door_main_" + leg, "gear_door_flap_" + leg]


def tree(obj):
    import checks

    return checks.tree(obj)


def world_points(obj):
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def aabb(points):
    return (Vector([min(p[i] for p in points) for i in range(3)]), Vector([max(p[i] for p in points) for i in range(3)]))


def members(leg, k):
    """The sprung leg's members as capsules (end, end, radius): the trunnion, the forged leg, its foot and the
    retraction actuator, or the nose leg's trunnion, leg, sleeve and landing lamp."""
    if leg != "N":
        kl, side = main_points(), -1 if leg == "R" else 1  # laid out on the left leg, mirrored
        P, A, h, out, pin = kl["P"], kl["A"], kl["hinge"], kl["swivel"], MAIN_LEG["trunnion"]["pin"]
        caps = [(P + h * pin[0], P + h * pin[1], 0.046), (P, A, 0.08), (A - out * MAIN_LEG["foot"][0], A, 0.056),
                (*actuator_ends(kl), 0.03)]
        return [(mirrored(a, side), mirrored(b, side), r) for a, b, r in caps]
    lamp = landing_lamp()
    return [(k["P"] - X * 0.10, k["P"] + X * 0.10, 0.03), (k["P"], k["T"], 0.035), (k["G"], k["T"], 0.056),
            (lamp - Y * 0.02, lamp + Y * 0.03, 0.045)]


def structure_points(obj):
    """World points of a mesh's faces on the gear's own material (the leg door is not structure)."""
    gear = {i for i, m in enumerate(obj.data.materials) if m and m.name in ("Fighter1_gear", "Mirror")}
    keep = {v for f in obj.data.polygons if f.material_index in gear for v in f.vertices}
    return [obj.matrix_world @ obj.data.vertices[v].co for v in keep]


def wheel_of(points):
    """The tyre as the Unity author reads it: bounds centre and the largest distance off the axle (along X)."""
    lo, hi = aabb(points)
    c = (lo + hi) / 2
    return c, max((p - c - X * (p - c).x).length for p in points)


def check(icarus):
    import budget

    over = budget.over_caps(icarus, BUDGET)
    problems = ["over the triangle caps: " + "; ".join(over)] if over else []
    O = bpy.data.objects
    report = {}
    for leg in LEGS:
        g = GEAR["nose" if leg == "N" else "main"]
        side = -1 if leg == "R" else 1
        want = bi.P(g["wheel_s"], side * g["wheel_x"], GEAR["ground_z"] + g["wheel_d"] / 2)
        c, r = wheel_of(world_points(O["gear_wheel_%s_visible" % leg]))
        moved = (c - want).length
        if moved > TYRE_TOL or abs(r - g["wheel_d"] / 2) > TYRE_TOL:
            problems.append("%s tyre centre moved %.4f m, radius %.4f (spec %.3f)" % (leg, moved, r, g["wheel_d"] / 2))
        # Unity's break-off box: the sprung mesh's bounds grown round the tyre. The detail may stand at most BOX_TOL
        # proud of the leg's own members, each a capsule (end, end, radius).
        k = nose_points() if leg == "N" else main_points(side)
        lo, hi = aabb(structure_points(O["gear_leg_%s_visible" % leg]))
        lo0, hi0 = aabb([p for a, b, rad in members(leg, k) for p in (a, b)
                         for p in (p - Vector((rad,) * 3), p + Vector((rad,) * 3))])
        tyre = (want - Vector((g["wheel_d"] / 2,) * 3), want + Vector((g["wheel_d"] / 2,) * 3))
        box = lambda b: (Vector(map(min, b[0], tyre[0])), Vector(map(max, b[1], tyre[1])))
        (a0, a1), (b0, b1) = box((lo0, hi0)), box((lo, hi))
        drift = max(max(x - y for x, y in zip(a0, b0)), max(y - x for x, y in zip(a1, b1)), 0.0)
        report[leg] = {"tyre_moved_m": round(moved, 5), "tyre_r": round(r, 4), "box_proud_m": round(drift, 4),
                       "box": [[round(c, 3) for c in v] for v in (b0, b1)]}
        if drift > BOX_TOL:
            problems.append("%s break-off box stands %.3f m proud of the leg's members" % (leg, drift))
        tris = {o.name: sum(len(f.vertices) - 2 for f in o.data.polygons) for o in leg_meshes(leg)}
        report[leg]["tris"] = tris
        if leg != "N":  # the wheel stows flat where GEAR["main"]["stowed"] puts it
            with posed({"gear_leg_" + leg: 1.0, "gear_wheel_" + leg: 1.0}):
                pts = world_points(O["gear_wheel_%s_visible" % leg])
                lo_, hi_ = aabb(pts)
                stow = mirrored(bi.P(*GEAR["main"]["stowed"]), side)
                off = ((lo_ + hi_) / 2 - stow).length
                tilt = math.asin(min(1.0, (hi_.z - lo_.z - g["wheel_w"]) / g["wheel_d"])) if hi_.z - lo_.z > g["wheel_w"] else 0.0
            report[leg]["stowed_off_m"], report[leg]["stowed_tilt_deg"] = round(off, 5), round(math.degrees(tilt), 2)
            if off > STOW_TOL or tilt > 0.02:
                problems.append("%s stows its wheel %.4f m from its spec, tilted %.2f deg" % (leg, off, math.degrees(tilt)))
    for name in [d for leg in LEGS for d in doors_of(leg)]:
        t = sum(len(f.vertices) - 2 for f in O[name + "_visible"].data.polygons)
        report[name] = t
        if not DOOR_TRIS[0] <= t <= DOOR_TRIS[1]:
            problems.append("%s has %d triangles (%d to %d)" % (name, t, *DOOR_TRIS))
    stow, sweep, swing, own = stowed_check(icarus), retraction_sweep(icarus), door_swing(icarus), tyre_contact()
    carrier = carrier_clear()
    problems += stow + sweep["clashes"] + swing + own["clashes"] + carrier["clashes"]
    for line in problems:
        print("gear problem:", line)
    print("gear check:", {"legs": report, "stowed_intrusions": len(stow), "sweep_poses": sweep["poses"],
                          "sweep_clashes": len(sweep["clashes"]), "least_gap_m": sweep["least"],
                          "tyre_to_own_leg_m": own["least"], "tyre_contact_poses": own["poses"],
                          "tyre_to_own_leg_compressed_m": own["bump_stop_m"], "carrier_to_leg_m": carrier["least"]})
    if problems:
        raise ValueError("gear: " + "; ".join(problems[:30]) + (" (%d in all)" % len(problems) if len(problems) > 30 else ""))


def door_swing(icarus):
    """Each leg's doors from just off shut to open together (LandingGear moves them as one), gear down, each against
    everything but the gear and itself: a door must swing clear of the airframe and the other doors."""
    gear = {o.name for leg in LEGS for o in leg_meshes(leg)}
    found = []
    for leg in LEGS:
        for d in doors_of(leg):
            door = bpy.data.objects[d + "_visible"]
            others = [o for o in icarus.all_objects if o.type == "MESH" and o.name not in gear and o is not door
                      and o.data.polygons]
            hinge = bpy.data.objects[d]
            for i in range(1, 11):
                with posed({e: 0.05 + 0.95 * i / 10 for e in doors_of(leg)}):
                    # The door's edges ride the hole's (its hinge edge on the skin's), so the door is tried 3 mm off its
                    # hinge line and 3 mm in from every edge: what it meets then, it cuts.
                    origin, axis = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
                    bm = bmesh.new()
                    bm.from_mesh(door.data)
                    bm.transform(door.matrix_world)
                    mid = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
                    for v in bm.verts:
                        r = v.co - origin - axis * axis.dot(v.co - origin)
                        v.co += (r.normalized() * 0.003 if r.length > 1e-6 else Vector()) + (mid - v.co).normalized() * 0.003
                    t = solids.BVHTree.FromBMesh(bm)
                    bm.free()
                    near_hinge = lambda o, f: line_gap([o.matrix_world @ o.data.vertices[v].co  # skin on the hinge line
                                                        for v in o.data.polygons[f].vertices], origin, axis) < DOOR_SKIN + 0.003
                    hits = ["%s at s %.3f x %.3f z %.3f" % (o.name, *where(o, pairs[0][1]))
                            for o in others for pairs in [[q for q in t.overlap(tree(o)) if not near_hinge(o, q[1])]]
                            if pairs]
                if hits:
                    found.append("%s at %.2f open meets %s" % (d, 0.05 + 0.95 * i / 10, "; ".join(hits)))
    return found


def line_gap(points, origin, axis):
    """How near a flat convex face (its points) comes to the line through origin along axis (unit): its nearest point,
    not its nearest corner, since a face can cross close by the line between corners well clear of it."""
    ps = [p - origin - axis * axis.dot(p - origin) for p in points]  # square to the line, which is the point 0 there
    turns = [a.cross(b).dot(axis) for a, b in zip(ps, ps[1:] + ps[:1])]
    if abs(sum(turns)) > 1e-12 and (min(turns) >= 0 or max(turns) <= 0):
        return 0.0
    gaps = []
    for a, b in zip(ps, ps[1:] + ps[:1]):
        e = b - a
        t = max(0.0, min(1.0, -a.dot(e) / e.length_squared)) if e.length_squared > 1e-12 else 0.0
        gaps.append((a + e * t).length)
    return min(gaps)


def tyre_points(leg, rest):
    """The tyre's tread and sidewalls (world space): its vertices beyond the rim, where the hub ends. rest is the
    wheel's matrix_world gear down, when its axle runs along X."""
    g = GEAR["nose" if leg == "N" else "main"]
    wheel = bpy.data.objects["gear_wheel_%s_visible" % leg]
    me = wheel.data
    c, _ = wheel_of([wheel.matrix_world @ v.co for v in me.vertices])
    axle = ((wheel.matrix_world @ rest.inverted()).to_3x3() @ X).normalized()
    keep = []
    for v in me.vertices:
        p = wheel.matrix_world @ v.co
        if (p - c - axle * axle.dot(p - c)).length > g["rim_r"] * 1.07:
            keep.append(p)
    return keep


def tyre_contact():
    """Each tyre against the rest of its own leg: the leg, the carrier or arm and the unsprung, gear down with the
    wheel free, and through the fold (the wheel rides the carrier, so only the sprung leg moves against it there):
    the tyre's tread and sidewalls must keep TYRE_CLEAR from all of them. Slid up its stroke the wheel is measured,
    not judged: the nose leg's piston is shorter than the bump stop, so its tyre meets the oleo's gland collar
    compressed (bump_stop_m). No contact is accepted anywhere."""
    O = bpy.data.objects
    clashes, least, poses, bump = [], 9.0, 0, {}
    for leg in LEGS:
        own = [m for m in leg_meshes(leg) if m.name != "gear_wheel_%s_visible" % leg]
        slid = [O[UNSPRUNG + leg], O["gear_wheel_%s_visible" % leg]]
        rest = slid[1].matrix_world.copy()
        n = max(1, math.ceil(reach(leg) / SWEEP_STEP))
        cases = [(0.0, c) for c in (0.0, GEAR_STROKE / 2, GEAR_STROKE)] + [(i / n, 0.0) for i in range(1, n + 1)]
        for fold, lift in cases:
            with posed({"gear_leg_" + leg: fold, "gear_wheel_" + leg: fold}):
                saved = [o.matrix_world.copy() for o in slid]
                for o in slid:  # LandingGear slides the unsprung straight up its bump stop
                    o.matrix_world = Matrix.Translation(Z * lift) @ o.matrix_world
                bpy.context.view_layer.update()
                pts = tyre_points(leg, Matrix.Translation(Z * lift) @ rest if fold == 0.0 else rest)
                for m in own if fold == 0.0 else [O["gear_leg_%s_visible" % leg]]:
                    t = tree(m)
                    near = [(t.find_nearest(p), p) for p in pts]
                    d = min(h[3] for h, _ in near)
                    if lift > 0.0:
                        bump[leg] = round(min(bump.get(leg, 9.0), d), 4)
                        continue
                    least = min(least, d)
                    if d < TYRE_CLEAR:
                        clashes.append("%s tyre %.3f m from %s at fold %.2f" % (leg, d, m.name, fold))
                for o, mw in zip(slid, saved):
                    o.matrix_world = mw
                bpy.context.view_layer.update()
                poses += 1
    return {"clashes": clashes, "least": round(least, 4), "poses": poses, "bump_stop_m": bump}


def carrier_clear():
    """Each main leg's carrier and unsprung against its sprung leg through the fold, wheel free: the carrier turns
    against the foot's boss and swings the strut past the leg's end, and nothing it holds may pass into the leg."""
    O = bpy.data.objects
    clashes, least = [], 9.0
    for leg in ("L", "R"):
        sprung = O["gear_leg_%s_visible" % leg]
        n = max(1, math.ceil(reach(leg) / SWEEP_STEP))
        for i in range(n + 1):
            with posed({"gear_leg_" + leg: i / n, "gear_wheel_" + leg: i / n}):
                t = tree(sprung)
                for m in (O[ARM + leg], O[UNSPRUNG + leg]):
                    if t.overlap(tree(m)):
                        clashes.append("%s passes into %s at fold %.2f" % (m.name, sprung.name, i / n))
                    least = min(least, min(t.find_nearest(m.matrix_world @ v.co)[3] for v in m.data.vertices))
    return {"clashes": clashes, "least": round(least, 4)}


def all_folds(fraction):
    return {n: fraction for leg in LEGS for n in ("gear_leg_" + leg, "gear_wheel_" + leg)}


def all_doors(fraction):
    return {d: fraction for leg in LEGS for d in doors_of(leg)}


def stowed_check(icarus):
    """Gear up, doors shut: every mesh of every leg against every other mesh of the aircraft, triangle overlap."""
    legs = {leg: leg_meshes(leg) for leg in LEGS}
    gear = {o.name for ms in legs.values() for o in ms}
    others = [o for o in icarus.all_objects if o.type == "MESH" and o.name not in gear and o.data.polygons]
    found = []
    with posed(all_folds(1.0)):
        trees = {o.name: tree(o) for o in others + [o for ms in legs.values() for o in ms]}
        for leg, meshes in legs.items():
            for m in meshes:
                for o in others + [x for l2, ms in legs.items() if l2 != leg for x in ms]:
                    pairs = trees[m.name].overlap(trees[o.name])
                    if pairs:
                        at = m.matrix_world @ m.data.polygons[pairs[0][0]].center
                        found.append("stowed %s meets %s at s %.3f x %.3f z %.3f (its face s %.3f x %.3f z %.3f)" % (
                            m.name, o.name, at.y + bi.S0, at.x, at.z, *where(o, pairs[0][1])))
    return found


def reach(leg):
    """Largest distance any of a leg's vertices travels through the fold, as an arc bound."""
    O = bpy.data.objects
    total = 0.0
    for hinge in ("gear_leg_" + leg, "gear_wheel_" + leg):
        h = O[hinge]
        origin, axis = h.matrix_world.translation, h.matrix_world.col[0].xyz.normalized()
        r = max((p - origin - axis * axis.dot(p - origin)).length for m in leg_meshes(leg) if m.parent == h or
                m.parent.parent == h for p in world_points(m))
        total += math.radians(abs(h["travel_deg"])) * r
    return total


def where(obj, face):
    """Station, x and z of a face's centre."""
    c = obj.matrix_world @ obj.data.polygons[face].center
    return c.y + bi.S0, c.x, c.z


def retraction_sweep(icarus):
    """Each leg from down to up with its doors open, then its doors closing on the stowed leg, in steps that move no
    vertex more than SWEEP_STEP: the leg's meshes against the skin and every internal, and against its own doors."""
    from mathutils.bvhtree import BVHTree

    legs = {leg: leg_meshes(leg) for leg in LEGS}
    gear = {o.name for ms in legs.values() for o in ms}
    door_names = {d + "_visible" for leg in LEGS for d in doors_of(leg)}
    static = [o for o in icarus.all_objects if o.type == "MESH" and o.name not in gear and o.name not in door_names
              and o.data.polygons]
    fixed = solids.bvh(static)
    trees = {o.name: tree(o) for o in static}
    clashes, poses, least = [], 0, 9.0
    for leg, meshes in legs.items():
        n = max(1, math.ceil(reach(leg) / SWEEP_STEP))
        doors = [bpy.data.objects[d] for d in doors_of(leg)]
        m_doors = max(1, math.ceil(max(math.radians(abs(d["travel_deg"])) * max(
            (p - d.matrix_world.translation).length for p in world_points(d.children[0])) for d in doors) / SWEEP_STEP))
        steps = [(i / n, 1.0) for i in range(n + 1)] + [(1.0, 1 - j / m_doors) for j in range(1, m_doors + 1)]
        for fold, door in steps:
            fr = {"gear_leg_" + leg: fold, "gear_wheel_" + leg: fold}
            fr.update({d.name: door for d in doors})
            with posed(fr):
                bm = bmesh.new()
                for m in meshes:
                    me = m.data.copy()
                    me.transform(m.matrix_world)
                    bm.from_mesh(me)
                    bpy.data.meshes.remove(me)
                moving = BVHTree.FromBMesh(bm)
                pts = [v.co.copy() for v in bm.verts]
                bm.free()
                poses += 1
                if moving.overlap(fixed):
                    at = ["%s at s %.3f x %.3f z %.3f meets %s at s %.3f x %.3f z %.3f" % (
                        m.name, *where(m, pairs[0][0]), n, *where(bpy.data.objects[n], pairs[0][1]))
                          for m in meshes for n, t in trees.items() for pairs in [tree(m).overlap(t)] if pairs]
                    clashes.append("%s at fold %.2f doors %.2f: %s" % (leg, fold, door, "; ".join(at)))
                for d in doors:
                    pairs = moving.overlap(tree(d.children[0]))
                    if pairs:
                        clashes.append("%s at fold %.2f doors %.2f meets %s at s %.3f x %.3f z %.3f"
                                       % (leg, fold, door, d.name, *where(d.children[0], pairs[0][1])))
                if fold in (0.0, 1.0) or poses % 10 == 0:
                    least = min(least, min(fixed.find_nearest(p)[3] for p in pts[::7]))
    return {"clashes": clashes, "poses": poses, "least": round(least, 4)}
