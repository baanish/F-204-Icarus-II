"""Landing gear, gear doors and the suspension chain.

Each leg is the transform chain the game moves (IcarusAuthor.Gear.cs drives it with the Revoker's LandingGear):

- gear_leg_<leg> is the hinge empty the leg folds about (local X along the hinge; travel_deg turns it from down to
  stowed), with the sprung mesh gear_leg_<leg>_visible on Fighter1_gear.
- gear_wheel_<leg>, a child of the hinge, is the second fold the game turns through LandingGear.movingParts: the main
  gear's knee at the oleo top, the nose gear's twist about its piston. What rides it: gear_arm_<leg> (the main gear's
  oleo below the knee), gear_unsprung_<leg> (piston on Mirror, foot, axle arm or fork, lower link: what slides with
  LandingGear.suspensionTravel) and gear_wheel_<leg>_visible (tyre and hub on Aircraft_wheels).

The built pose is gear down, doors shut. The game slides the unsprung straight up its bump stop, so every piston
stands vertical when down. Each main leg hangs from a trunnion in the lobe beside its bay and folds inboard; the oleo,
piston and wheel fold again at the knee, so the tyre lies tilted in the belly beside its twin, under the engine. The
nose leg folds forward and twists its wheel flat under the cockpit floor. Doors are patches of the fuselage skin,
resampled to a coarse grid with an inner face on jet_mechanical, hinged on a straight line at that face, their ends
square to it. Each main bay has a door hinged by the keel and, outboard of it, a flap that folds out under the wing
root so the strut has its way out of the bay; behind the nose doors a narrow pair lets the nose oleo out.
"""
import contextlib
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi
import solids
from solids import X, Y, Z

SEG_TYRE, SEG_HUB, SEG_LEG = 24, 12, 12
GEAR = {
    "ground_z": -1.28,  # ground height below the radome-tip line, gear down, from the reference side view
    # Wheel centre station and lateral offset, tyre diameter, width and rim radius. The nose leg's pivot (s, x, z) sits
    # just ahead of the oleo, which stands on the wheel; fold_deg turns it forward about -X, twist_deg its piston.
    "nose": {"wheel_s": 5.20, "wheel_x": 0.0, "wheel_d": 0.48, "wheel_w": 0.14, "rim_r": 0.13,
             "pivot": (5.13, 0.0, -0.30), "crown_gap": 0.035, "piston": 0.10, "oleo": 0.28,
             "fold_deg": 90.0, "twist_deg": 90.0},
    # The main tyre is 0.16 m wide: a 0.20 m tyre has no room to lie in the belly beside its twin under the engine.
    # The pivot, hinge and knee were solved against the airframe's free space, stowed and through the fold (left side,
    # Blender axes): the hinge turns fold_deg about "hinge" through the pivot (s, x, z), the knee knee_deg about "knee"
    # through the oleo top, and the piston foot sits "arm" metres from the axle stub at arm_deg in the wheel's plane
    # (0 is aft). Change the airframe round the bay and gear.check says whether they still fit.
    "main": {"wheel_s": 9.84, "wheel_x": 1.24, "wheel_d": 0.67, "wheel_w": 0.16, "rim_r": 0.18,
             "pivot": (9.82467, 0.47992, -0.04471), "hinge": (0.65569, 0.18047, 0.73314), "fold_deg": 57.480,
             "knee": (0.46283, -0.66642, 0.58453), "knee_deg": -90.417, "arm_deg": -2.137, "arm": 0.483,
             "stub": 0.11, "piston": 0.12, "oleo": 0.42},
    # Door patches of the belly skin, left side: (name, s from, s to, x from, x to, hinge edge, rows, columns, degrees
    # open, opening). The patch runs along the skin's own rings and ring points nearest those limits; rows and columns
    # are the resampled grid. Behind the nose doors a narrow pair lets the oleo out (wider, they would reach the trough's
    # lip). The main door opens past square, so its curve hangs straight down by the keel; outboard of it a flap
    # hinged on its outer edge folds up against the lobe, clearing the strut's way out of the bay.
    "doors": [("gear_door_N_L", 4.08, 5.23, 0.0, 0.31, "outer", 4, 3, 88, "down"),
              ("gear_door_N2_L", 5.23, 5.43, 0.0, 0.10, "outer", 2, 2, 88, "down"),
              ("gear_door_main_L", 9.62, 11.15, 0.04, 0.36, "inner", 4, 2, 100, "down"),
              ("gear_door_flap_L", 9.62, 11.15, 0.36, 0.74, "outer", 4, 2, 135, "out")],
}
DOOR_SKIN = 0.006  # the door's inner face sits this far inside its outer skin
DOOR_GAP = 0.002  # and its free edges stand this far in from the hole's, so it swings clear of the skin
# Object names the other modules and the Unity author build against, per leg N, L and R: the sprung leg is
# gear_leg_<leg>_visible and the wheel gear_wheel_<leg>_visible; the piston and axle slide as gear_unsprung_<leg>,
# and the main gear's oleo below the knee is gear_arm_<leg>.
UNSPRUNG, ARM = "gear_unsprung_", "gear_arm_"
LEGS = ("N", "L", "R")
# Triangles per component: target and cap (budget.py sums them). A leg counts its sprung, unsprung, arm and wheel.
BUDGET = {
    **{"leg_" + leg: {"target": 3000, "cap": 3800,
                      "objects": ("gear_leg_" + leg, "gear_wheel_" + leg, UNSPRUNG + leg, ARM + leg)}
       for leg in LEGS},
    "doors": {"target": 400, "cap": 520, "objects": ("gear_door_",)},
}
DOOR_TRIS = (32, 130)  # each door, outer skin and inner trim (Exterior rule 22)
# Stock wheel layout, measured on _donotship/Texture2D/aircraft_wheels_b_PLACEHOLDER.png (512 px): the tread strip
# runs down the left edge (u from, u to), and each hub face maps onto one of the drawn hubs (centre px, radius px).
WHEEL_UV = {"tread": (0.0, 0.40),
            "main": {"out": (295, 240, 88), "in": (297, 421, 88)},
            "nose": {"out": (432, 328, 64), "in": (438, 88, 61)}}
TYRE_TOL, BOX_TOL = 0.001, 0.03  # the tyre's centre and radius, and the leg's break-off box (gear.check)
SWEEP_STEP = 0.01  # largest vertex move between two poses of the retraction sweep
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
    """The main leg's skeleton, gear down, world space: wheel centre C, axle stub, piston foot F, gland G, oleo top
    (knee) T, pivot P, and the hinge and knee axes (a right leg turns the same angles about the mirrored axes reversed,
    since a mirror reverses a rotation's sense)."""
    g = GEAR["main"]
    C = bi.P(g["wheel_s"], g["wheel_x"], GEAR["ground_z"] + g["wheel_d"] / 2)
    stub = C - X * g["stub"]
    a = math.radians(g["arm_deg"])
    F = stub + Vector((0.0, math.cos(a), math.sin(a))) * g["arm"]
    G = F + Z * g["piston"]
    T = G + Z * g["oleo"]
    pts = {"C": C, "stub": stub, "F": F, "G": G, "T": T, "P": bi.P(*g["pivot"])}
    pts = {k: mirrored(v, side) for k, v in pts.items()}
    flip = lambda v: Vector(v).normalized() if side > 0 else -mirrored(Vector(v).normalized(), -1)
    pts["hinge"], pts["knee"] = flip(g["hinge"]), flip(g["knee"])
    return pts


def stowed(point, k, knee=True):
    """Where a point of the main leg (k = main_points) lies with the gear up; knee=False for the sprung leg."""
    g = GEAR["main"]
    if knee:
        point = turn(point, k["T"], k["knee"], g["knee_deg"])
    return turn(point, k["P"], k["hinge"], g["fold_deg"])


def main_solids():
    """Left main leg meshes, gear down, world space: sprung, arm (oleo), unsprung and wheel."""
    k = main_points()
    P, T, G, F, C, stub = k["P"], k["T"], k["G"], k["F"], k["C"], k["stub"]
    h, kn = k["hinge"], k["knee"]
    gear, chrome = "Fighter1_gear", "Mirror"
    sprung = solids.Solids()
    solids.cylinder(sprung, P - h * 0.06, P + h * 0.06, 0.03, SEG_LEG, gear)  # trunnion
    d = (T - P).normalized()
    solids.lathe(sprung, P, d, [(-0.02, 0.026), (0.0, 0.04), ((T - P).length - 0.07, 0.036), ((T - P).length - 0.05, 0.026)],
                 SEG_LEG, gear)  # the upper strut down to the knee clevis
    side = kn.cross(d).normalized()
    for s in (-1, 1):  # clevis cheeks either side of the knee lug, joined to the strut's end
        solids.beam(sprung, T - d * 0.06 + kn * (0.038 * s), T + kn * (0.038 * s), side, 0.045, 0.014, gear)
    solids.cylinder(sprung, T - kn * 0.05, T + kn * 0.05, 0.014, 8, gear)  # knee pin
    arm = solids.Solids()
    solids.cylinder(arm, T - kn * 0.03, T + kn * 0.03, 0.027, SEG_LEG, gear)  # knee lug
    length = (T - G).length
    solids.lathe(arm, G, Z, [(0.0, 0.058), (0.03, 0.058), (0.03, 0.052), (length - 0.035, 0.052), (length, 0.027)],
                 SEG_LEG, gear)  # oleo, gland collar at its foot
    aft = Vector((0.0, 1.0 if (C - F).y < 0 else -1.0, 0.0))  # the side of the oleo away from the wheel
    eye = G + aft * 0.085 + Z * 0.03
    solids.beam(arm, G + aft * 0.045 + Z * 0.03, eye, X, 0.02, 0.018, gear)  # upper torque link
    solids.cylinder(arm, eye - Z * 0.011, eye + Z * 0.011, 0.013, 8, gear)
    unsprung = solids.Solids()
    solids.cylinder(unsprung, F, G + Z * 0.06, 0.038, SEG_LEG, chrome)  # piston
    solids.box(unsprung, F, (X, Y, Z), (0.04, 0.045, 0.032), gear)  # foot
    solids.beam(unsprung, F + (stub - F).normalized() * 0.03, stub + X * 0.018, X, 0.036, 0.055, gear)  # axle arm
    solids.cylinder(unsprung, stub, C + X * 0.03, 0.025, SEG_LEG, gear)  # axle, through the hub
    solids.beam(unsprung, F + aft * 0.03, F + aft * 0.085, X, 0.02, 0.026, gear)  # lower link lug
    solids.cylinder(unsprung, F + aft * 0.085, Vector((F.x, eye.y, eye.z + 0.05)), 0.008, 6, gear)  # lower link rod
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
    knee = bi.hinged("gear_wheel_" + sd, rename(meshes[3], "gear_wheel_" + sd), frame_on(k["T"], k["knee"]),
                     parent=parts[0])
    knee[0]["travel_deg"] = g["knee_deg"]
    knee[0]["stowed_wheel"] = list(stowed(k["C"], k))  # IcarusAuthor.Gear.cs picks the turns' senses from it
    for obj, name in ((meshes[1], ARM + sd), (meshes[2], UNSPRUNG + sd)):
        ride(rename(obj, name), knee[0])
    for obj in meshes[1:]:
        obj["role"] = "visual"  # no collider or LOD1 hull: these move against the part they belong to
    return parts + knee + meshes[1:3]


# --- the nose leg --------------------------------------------------------------------------------------------------

def nose_points():
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
    # The landing lamp just ahead of the gland collar, under the light_landing empty (lights.py), on a bracket; its lens
    # on Mirror. Any further forward and it rises above the bay's roof when the leg folds.
    lamp = bi.P(g["wheel_s"] - 0.085, 0.0, GEAR["ground_z"] + g["wheel_d"] + 0.15)
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
    """Rings j0..j1 and ring points k0..k1 (left side, k counting up from the bottom of the ring) of a door."""
    name, s0, s1, x0, x1, hinge, rows, cols, _, _ = spec
    stations, vid = skin_grid(fuselage)
    j0 = min(range(len(stations)), key=lambda j: abs(stations[j] - s0))
    j1 = min(range(len(stations)), key=lambda j: abs(stations[j] - s1))
    mid = (j0 + j1) // 2
    bottom = 3 * bi.RING // 4
    xs = {k: fuselage.data.vertices[vid(mid, k)].co.x for k in range(bottom, bottom + bi.RING // 4)}
    k0 = min(k for k, x in xs.items() if x >= x0 - 1e-6)
    k1 = max(k for k, x in xs.items() if x <= x1 + 1e-6)
    return j0, j1, k0, k1


def kept(a, b, n):
    """n + 1 indices from a to b, ends included."""
    return sorted({round(a + (b - a) * i / n) for i in range(n + 1)})


def cut_doors(fuselage):
    """Lift the door patches out of the fuselage skin into hinged doors, resampled to a coarse grid with the skin's
    hole edge snapped onto the grid's. Returns the parts."""
    stations, vid = skin_grid(fuselage)
    parts = []
    edges = {}  # (s from, s to, x) -> ring point, so a door starting where another ends shares its edge
    for spec in GEAR["doors"]:
        name, hinge_edge, rows, cols = spec[0], spec[5], spec[6], spec[7]
        j0, j1, k0, k1 = door_patch(fuselage, spec)
        k0 = edges.get(spec[1:4], k0)
        edges[spec[1:3] + (spec[4],)] = k1
        js, ks = kept(j0, j1, rows), kept(k0, k1, cols)
        hinge_k = k1 if hinge_edge == "outer" else k0
        # ring point k of the left side mirrors to point (RING / 2 - k) on the right
        mirror_k = {1: lambda k: k, -1: lambda k: bi.RING // 2 - k}
        for side in (1, -1):  # both sides' holes first: a left and a right door can share their centreline points
            vk = mirror_k[side]
            co = lambda j, k: fuselage.data.vertices[vid(j, vk(k))].co.copy()
            snap_edges(fuselage, j0, j1, k0, k1, js, ks, lambda j, k: vid(j, vk(k)))
            straighten(fuselage, [vid(j, vk(hinge_k)) for j in range(j0, j1 + 1)])
            square_ends(fuselage, co(j0, hinge_k), co(j1, hinge_k), [[vid(j, vk(k)) for k in range(k0, k1 + 1)] for j in (j0, j1)])
        for side in (1, -1):
            vk = mirror_k[side]
            co = lambda j, k: fuselage.data.vertices[vid(j, vk(k))].co.copy()
            grid = [[co(j, k) for k in ks] for j in js]
            if len(grid) == 2:  # a door one ring long gets a middle row, on its straight side edges
                grid.insert(1, [p.lerp(q, 0.5) for p, q in zip(*grid)])
            grid = gapped(grid, hinge_edge)
            remove_faces(fuselage, {vid(j, vk(k)) for j in range(j0, j1 + 1) for k in range(k0, k1 + 1)})
            door = door_slab(name.replace("_L", "_L" if side > 0 else "_R"), grid, side)
            col = -1 if hinge_edge == "outer" else 0
            a, b = grid[0][col], grid[-1][col]
            # The hinge runs along the door's inner face: on the outer skin, the door's thickness would swing round
            # into the skin beside the hinge.
            inward = ((b - a).cross(grid[len(grid) // 2][1 if col == 0 else -2] - a)).normalized()
            inward = inward if inward.dot(Vector((0.0, a.y, 0.3)) - a) > 0 else -inward
            a, b = a + inward * DOOR_SKIN, b + inward * DOOR_SKIN
            made = bi.hinged(door.name, door, frame_on(a, (b - a) * side))
            bpy.context.view_layer.update()  # opening_travel reads the door's matrix_local, stale until an update
            down = spec[9] == "down"  # hangs down, or folds out and over to lie under the wing root
            made[0]["travel_deg"] = opening_travel(made[0], spec[8], (lambda pts: -min(q.z for q in pts)) if down
                                                   else (lambda pts: sum(abs(q.x) for q in pts) / len(pts)))
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


def door_slab(name, grid, side):
    """A door from its outer skin grid (rows by columns, world space): the skin outside on Icarus_Body, an inner face
    DOOR_SKIN inside on jet_mechanical, and the edge between them on jet_mechanical, as one closed slab."""
    rows, cols = len(grid), len(grid[0])
    normal = lambda i, j: ((grid[min(i + 1, rows - 1)][j] - grid[max(i - 1, 0)][j])
                           .cross(grid[i][min(j + 1, cols - 1)] - grid[i][max(j - 1, 0)])).normalized()
    centre = bi.P(grid[0][0].y + bi.S0, 0.0, 0.3)  # inside the body
    out = []
    for i in range(rows):
        row = []
        for j in range(cols):
            n = normal(i, j)
            n = n if n.dot(grid[i][j] - centre) > 0 else -n
            row.append(grid[i][j] - n * DOOR_SKIN)
        out.append(row)
    shape = solids.Solids()
    shape.slab(grid, out, "jet_mechanical")
    for c in range((rows - 1) * (cols - 1)):
        shape.mats[2 * c] = "Icarus_Body"  # the slab lists each cell's outer face, then its inner one
    obj = mesh_from(shape, 1)
    obj.data.shade_flat()
    return rename(obj, name)


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
    """The sprung leg's members as capsules (end, end, radius): the trunnion, the strut or yoke, the knee pin or the
    oleo, and the nose leg's landing lamp."""
    if leg != "N":
        return [(k["P"] - k["hinge"] * 0.06, k["P"] + k["hinge"] * 0.06, 0.03), (k["P"], k["T"], 0.04),
                (k["T"] - k["knee"] * 0.05, k["T"] + k["knee"] * 0.05, 0.014)]
    g = GEAR["nose"]
    lamp = bi.P(g["wheel_s"] - 0.085, 0.0, GEAR["ground_z"] + g["wheel_d"] + 0.15)
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
    for name in [d for leg in LEGS for d in doors_of(leg)]:
        t = sum(len(f.vertices) - 2 for f in O[name + "_visible"].data.polygons)
        report[name] = t
        if not DOOR_TRIS[0] <= t <= DOOR_TRIS[1]:
            problems.append("%s has %d triangles (%d to %d)" % (name, t, *DOOR_TRIS))
    stow, sweep, swing = stowed_check(icarus), retraction_sweep(icarus), door_swing(icarus)
    problems += stow + sweep["clashes"] + swing
    for line in problems:
        print("gear problem:", line)
    print("gear check:", {"legs": report, "stowed_intrusions": len(stow), "sweep_poses": sweep["poses"],
                          "sweep_clashes": len(sweep["clashes"]), "least_gap_m": sweep["least"]})
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
                    off = lambda c: (c - origin - axis * axis.dot(c - origin)).length
                    near_hinge = lambda o, f: min(off(o.matrix_world @ o.data.vertices[v].co)  # skin on the hinge line
                                                  for v in o.data.polygons[f].vertices) < DOOR_SKIN + 0.003
                    hits = ["%s at s %.3f x %.3f z %.3f" % (o.name, *where(o, pairs[0][1]))
                            for o in others for pairs in [[q for q in t.overlap(tree(o)) if not near_hinge(o, q[1])]]
                            if pairs]
                if hits:
                    found.append("%s at %.2f open meets %s" % (d, 0.05 + 0.95 * i / 10, "; ".join(hits)))
    return found


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
                        found.append("stowed %s meets %s at s %.3f x %.3f z %.3f" % (m.name, o.name, at.y + bi.S0, at.x, at.z))
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
                    at = ["%s meets %s at s %.3f x %.3f z %.3f" % (m.name, n, *where(bpy.data.objects[n], pairs[0][1]))
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
