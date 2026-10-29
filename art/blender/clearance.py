"""Collider clearance between parts with no joint between them, so a part that breaks free collides with the rest of
the jet as a stock part does, and nothing touches while attached.

Unity's joints switch collision off between the two bodies each joins (AeroPart.CreateJoints sets enableCollision false;
a HingeJoint's default is false) until the joint breaks. Every other pair of the Icarus's colliders collides, so their
hulls must stand apart by REQUIRED: both colliders' contact offset (CONTACT_OFFSET, which the plugin pins on every
Icarus collider, src/Icarus/ContactOffset.cs; Unity's 10 mm default would make contacts across a 20 mm gap) plus the
most each flexes toward the other in flight (FLEX, measured in game and on the A18 bench).

carve() runs last on the collider set, after the split pieces have their hulls: each hull is cut flat on its best
separating plane, REQUIRED short of every hull of a part that outranks it (RANK: moving surfaces and gear keep their
shape over their whole travel, then the wing and fin structure, the canopy, skins and radome, the hulls folded in from
the engine, ducts and the other internals, and last the fuselage sections' shells), as hulls.shells() carves them. The
parts' mass boxes are recorded before the cut (mass_box), so the centres of mass the Unity author places from the hulls
stay where they were.

check() fails the build where any two unjointed parts' hulls stand closer than REQUIRED, with every hinge turned
through its travel (parts.surface_sweep's poses) and each gear leg retracted with its doors (gear.retraction_sweep's
sequence).
"""
import math

import bpy
import numpy as np
from mathutils import Matrix, Vector

import hulls

# Unity's contact offset for each Icarus collider, metres; the plugin sets it at spawn (Unity serializes none).
CONTACT_OFFSET = 0.002
# How far each part moves in flight against a neighbour on other joints, metres, by name prefix, first match, else
# FLEX_DEFAULT; a pair's gap takes both parts' (REQUIRED). The outer wing at the crank in a 9 g pull, the inner wing box
# bending at the root with its folded skins (struck the aft fuselage and the fuel cells across 13 and 19 mm gaps in the
# full-stick pulls), the tail cone and the fin top, the flaps (tools/flight_peaks.py and A18 on 4b8710bd).
FLEX = (("wing_spar_outer_", 0.008), ("aileron_", 0.008), ("lef_", 0.008), ("wing_spar_", 0.020),
        ("fuselage_tail", 0.007), ("speed_brake", 0.007),
        ("fin_", 0.009), ("rudder", 0.009), ("stabilator", 0.009), ("flap_", 0.005), ("radome", 0.0035), ("canopy", 0.0035))
FLEX_DEFAULT = 0.001
# How far two unjointed parts come toward each other in flight, measured as a pair where one part's flex alone would
# not hold them apart: (prefix, prefix, metres), replacing their two FLEX values; src/Icarus/TailFlex.cs's approach line
# in full_stick_low_fast at 9.2 g. Each inner wing box toward fuselage_aft, which carries the engine since the internals
# fold into it (1,540 kg): 27.5 and 29.0 mm at the roll reversals, a tenth over. The fin skin toward the tail cone:
# 21.2 mm, a tenth over. Both were measured before src/Icarus/OriginShiftPoses.cs, so they hold the floating-origin
# shift's one-frame jumps; with it the wing boxes come no nearer than 0.2 mm in the same pull.
FLEX_PAIRS = (("wing_spar_", "fuselage_aft", 0.032), ("fin_skin", "fuselage_tail", 0.024))
# Who keeps its shape where two hulls are too close: the lower rank is cut, a folded skin hull by its panel's name.
# Moving parts aren't listed: they rank above all. The fuselage sections' shells yield to everything inside them, as
# hulls.build carves them last: their folded skin keeps them hulls all round.
RANK = (("wing_spar_", 5), ("wing_skin_", 5), ("fin_spar", 5), ("fin_skin", 5), ("canopy", 4.5), ("skin_", 4),
        ("dorsal_cover", 4), ("radome", 4), ("nozzle", 2.5), ("engine_", 2.5), ("intake_duct_", 1.5), ("fuselage_", 0.5))
RANK_MOVING, RANK_DEFAULT = 6, 1
# Braces: second joints, as IcarusAuthor.Parts.cs Braces (A22 checks that table against the tree).
BRACES = (("stabilator", "fuselage_aft"), ("rudder", "fuselage_aft"), ("fin_skin", "fuselage_aft"),
          ("wing_spar_outer_L", "fuselage_mid"), ("wing_spar_outer_R", "fuselage_mid"), ("fuselage_tail", "fuselage_mid"),
          ("fin_spar", "fuselage_mid"))
GEAR_FOLD_STEPS, GEAR_DOOR_STEPS = 24, 12
TOLERANCE = 0.0002
# The carve clears this much past REQUIRED: the axis test reads distance a little differently on a swept hull than on each
# pose the check turns through.
CARVE_SLACK = 0.001
BUDGET, CLOSEUPS = {}, {}  # a build module: its hulls' budget is hulls.BUDGET's


def first(table, name, default):
    return next((v for prefix, v in table if name.startswith(prefix)), default)


def part_of(col):
    """The part a collider belongs to: its owner, or the hinge empty above a surface's _visible mesh."""
    o = col.parent
    while o is not None and o.name.endswith("_visible"):
        o = o.parent
    return o


# Two parts a joint holds together never collide while it holds, so a folded skin hull and its chunk's other parts, and a
# fuselage section's shells and the parts jointed to it, need only stand apart, not REQUIRED: the blast trace
# (DamageEffects.FragTrace) must cross the outer one's hull before the inner one's, and a part the joint lets go of starts
# clear (a part freed inside shells it overlaps takes a kick getting out, enough to break a neighbour's joint). Other
# jointed pairs may overlap (the fin spar lies inside the fin skin's hulls); moving ones keep their sweeps.
JOINTED_GAP = 0.001
SECTIONS = ("fuselage_",)


def held_apart(a, b, moving):
    """Whether two jointed parts must still stand JOINTED_GAP apart: a fuselage section and a still part jointed to it."""
    return (a.startswith(SECTIONS) or b.startswith(SECTIONS)) and not {a, b} & moving


def required(a, b, jointed=False):
    if jointed:
        return JOINTED_GAP
    pair = next((f for x, y, f in FLEX_PAIRS if a.startswith(x) and b.startswith(y) or a.startswith(y) and b.startswith(x)), None)
    return 2 * CONTACT_OFFSET + (pair if pair is not None else first(FLEX, a, FLEX_DEFAULT) + first(FLEX, b, FLEX_DEFAULT))


def links(cols):
    """Pairs of part names a joint or brace joins: each part and its nearest ancestor that is a part too."""
    names = {part_of(c).name for c in cols}
    out = set()
    for p in {part_of(c) for c in cols}:
        up = p.parent
        while up is not None and up.name not in names:
            up = up.parent
        if up is not None:
            out |= {(p.name, up.name), (up.name, p.name)}
    for a, b in BRACES:
        out |= {(a, b), (b, a)}
    return out


# The Unity author replaces a gear leg's hulls with a cube this wide at its hinge (IcarusAuthor.Gear.cs GearHingeBox):
# the game's ground linecast would read a strut collider as full compression.
GEAR_HINGE_BOX = 0.15


def world(col):
    """A hull's world points, or for a gear leg the cube the Unity author gives it at the leg's hinge."""
    part = part_of(col)
    if part.name.startswith("gear_leg_"):
        h = GEAR_HINGE_BOX / 2
        return np.array([(part.matrix_world @ Vector((x, y, z)))[:] for x in (-h, h) for y in (-h, h) for z in (-h, h)])
    return np.array([(col.matrix_world @ v.co)[:] for v in col.data.vertices])


def faces(col):
    return [list(p.vertices) for p in col.data.polygons]


def shape_of(points):
    bm = hulls.convex([Vector(p) for p in points])
    s = hulls.bm_shape(bm)
    bm.free()
    return s


# --- moving parts ----------------------------------------------------------------------------------------------------

def hinge_poses(icarus):
    """{hinge name: [world matrices]}, each hinge turned through its travel in parts.surface_sweep's steps."""
    import parts

    out = {}
    for hinge in (o for o in icarus.all_objects if o.type == "EMPTY" and "deflection_deg" in o):
        vis = bpy.data.objects.get(hinge.name + "_visible")
        if vis is None:
            continue
        h = hinge.matrix_world
        centre = sum((v.co for v in vis.data.vertices), Vector()) / len(vis.data.vertices)
        turned = lambda deg: h @ Matrix.Rotation(math.radians(deg), 4, "X") @ h.inverted()
        kind = hinge.name[:-2] if hinge.name.endswith(("_L", "_R")) else hinge.name
        if kind in parts.TWO_WAY:
            signs = (1, -1)
        else:
            mid = vis.matrix_world @ centre
            score = (lambda m: abs((m @ mid).x)) if kind == "speed_brake" else (lambda m: -(m @ mid).z)
            signs = (1 if score(turned(1.0)) > score(turned(-1.0)) else -1,)
        travel = hinge["deflection_deg"]
        steps = math.ceil(travel / parts.SWEEP_STEP)
        poses = []
        for sign in signs:
            poses += [turned(sign * travel * i / steps) for i in range(steps + 1)]
        out[hinge.name] = poses
    return out


def gear_sequences(cols):
    """{leg: [{collider name: world points}]}: the leg folding with its doors open, then the doors closing, as
    gear.retraction_sweep moves them."""
    import gear

    out = {}
    for leg in gear.LEGS:
        doors = gear.doors_of(leg)
        moving = [c for c in cols if part_of(c).name in ["gear_leg_" + leg, "gear_wheel_" + leg] + doors]
        if not moving:
            continue
        steps = [(i / GEAR_FOLD_STEPS, 1.0) for i in range(GEAR_FOLD_STEPS + 1)]
        steps += [(1.0, 1 - j / GEAR_DOOR_STEPS) for j in range(1, GEAR_DOOR_STEPS + 1)]
        seq = []
        for fold, door in steps:
            fr = {n: fold for n in ("gear_leg_" + leg, "gear_wheel_" + leg) if n in bpy.data.objects}
            fr.update({d: door for d in doors if d in bpy.data.objects})
            with gear.posed(fr):
                seq.append({c.name: world(c) for c in moving})
        out[leg] = seq
    return out


def swept(seq_points):
    """Shapes covering a moving hull between consecutive poses: the hull of each pair of poses."""
    return [shape_of(np.vstack([a, b])) for a, b in zip(seq_points, seq_points[1:])] or [shape_of(seq_points[0])]


# --- carving ---------------------------------------------------------------------------------------------------------

def keep_most(s, o, need, sat_axis):
    """The cut that clears hull s from obstacle o by need and keeps the most of s: of the face normals of either (both
    ways) and the separating axis, the one whose plane need short of o leaves the largest share of s's extent. Cutting
    along the separating axis alone can slice a thin skin patch through its thickness."""
    axes = np.vstack([o[1], -o[1], s[1], -s[1], np.asarray(sat_axis)[None, :]]) if len(o[1]) and len(s[1]) else np.asarray(sat_axis)[None, :]
    ps, po = s[0] @ axes.T, o[0] @ axes.T
    at = po.min(0) - need - 1e-4
    lo, hi = ps.min(0), ps.max(0)
    kept = (at - lo) / np.maximum(hi - lo, 1e-9)
    i = int(kept.argmax())
    return axes[i], float(at[i])


def mass_box(cols):
    """Record on each part's owner, before the cut, the two hull boxes the Unity author places centres of mass from:
    mass_box_local, each hull's box in its owner's frame, its corners taken to world and boxed (ConfigurePart's rule), and
    mass_box_world, the box of the hulls' world points (KeepFamilyMoments' and A22's). Both in Blender world axes
    from the root part's origin, which the Unity author puts at the prefab's origin: a split piece's export pivot isn't
    its Blender origin. Each is min then max; the export writes a float array as a list, an array of arrays not at
    all."""
    root = np.array(bpy.data.objects["fuselage_mid"].matrix_world.translation[:])
    by_owner = {}
    for c in cols:
        by_owner.setdefault(c.parent, []).append(c)
    for owner, cs in by_owner.items():
        corners = []
        for c in cs:
            local = np.array([v.co[:] for v in c.data.vertices])
            lo, hi = local.min(0), local.max(0)
            corners += [(c.matrix_world @ Vector([(hi if k >> i & 1 else lo)[i] for i in range(3)]))[:] for k in range(8)]
        corners = np.array(corners) - root
        pts = np.vstack([world(c) for c in cs]) - root
        if "fold_centre" in owner:  # a chunk carrying folded panels: its mass-weighted centre (chunks.fold)
            corners = pts = np.array([owner["fold_centre"][:]]) - root
        owner["mass_box_local"] = [float(x) for x in np.concatenate([corners.min(0), corners.max(0)])]
        owner["mass_box_world"] = [float(x) for x in np.concatenate([pts.min(0), pts.max(0)])]


def carve(icarus):
    """Cut every hull clear of the hulls of unjointed parts that outrank it; returns a report line."""
    bpy.context.view_layer.update()  # the split pieces' hulls were parented since the last update: their world matrices are stale
    cols = [c for c in bpy.data.collections["Colliders"].objects if part_of(c) is not None]
    mass_box(cols)
    linked = links(cols)
    hinges = hinge_poses(icarus)
    gears = gear_sequences(cols)
    gear_parts = {part_of(c).name for c in cols if any(c.name in seq[0] for seq in gears.values())}
    moving = set(hinges) | gear_parts
    rank = lambda c: (RANK_MOVING if part_of(c).name in moving else first(RANK, c.get("folded_from") or part_of(c).name,
                                                                           RANK_DEFAULT), part_of(c).name)

    cache = {}

    def obstacles(c):
        """The shapes another part's hull c presents: its sweep where it moves, else its hull now."""
        if c.name in cache:
            return cache[c.name]
        name = part_of(c).name
        if name in hinges:
            rest = [v.co.copy() for v in c.data.vertices]
            out = swept([np.array([((m @ c.matrix_world) @ p)[:] for p in rest]) for m in hinges[name]])
        else:
            seq = next((seq for seq in gears.values() if c.name in seq[0]), None)
            out = swept([pose[c.name] for pose in seq]) if seq else [shape_of(world(c))]
        cache[c.name] = out
        return out

    order = sorted(cols, key=rank)
    cut_count, dropped = 0, []
    volume = lambda c: hulls.convex([Vector(p) for p in world(c)]).calc_volume()
    before = {}
    for c in cols:
        before[part_of(c).name] = before.get(part_of(c).name, 0.0) + volume(c)
    for i, c in enumerate(order):
        pc = part_of(c).name
        # a hull yields to every part ranked above it; moving parts also clear one another's sweeps both ways
        others = [o for o in (order if pc in moving else order[i + 1:]) if o is not c and o.name not in dropped
                  and (pc not in moving or part_of(o).name in moving)]
        # a folded skin hull keeps the clearance its panel had from parts jointed to the chunk it joined, moving ones too
        folded = c.get("folded_from") is not None
        others = [o for o in others if part_of(o).name != pc and ((pc, part_of(o).name) not in linked or folded
                                                                  or o.get("folded_from") or held_apart(pc, part_of(o).name, moving))]
        if not others:
            continue
        shapes = [(s, required(pc, part_of(o).name, (pc, part_of(o).name) in linked) + CARVE_SLACK)
                  for o in others for s in obstacles(o)]
        bm = hulls.convex([Vector(p) for p in world(c)])
        cuts = 0
        for _ in range(400):
            s = hulls.bm_shape(bm)
            lo, hi = s[0].min(0) - 0.05, s[0].max(0) + 0.05
            near = [(hulls.separation(s, o), o, need) for o, need in shapes
                    if np.all(o[0].min(0) <= hi) and np.all(lo <= o[0].max(0))]
            bad = [(sep, axis, o, need) for (sep, axis), o, need in near if sep < need - TOLERANCE]
            if not bad:
                break
            sep, axis, o, need = min(bad, key=lambda r: r[0] - r[3])
            axis, at = keep_most(s, o, need, axis)
            nxt = hulls.cut(bm, Vector(axis), at)
            bm.free()
            bm = nxt
            cuts += 1
            if bm is None:
                break
        else:
            raise ValueError("clearance: %s would not come clear of its neighbours" % c.name)
        if cuts == 0:
            bm.free()
            continue
        cut_count += cuts
        cache.pop(c.name, None)
        if bm is None:
            dropped.append(c.name)  # removed after the pass: later hulls still read the list
            continue
        bm.transform(c.parent.matrix_world.inverted())
        bm.to_mesh(c.data)
        bm.free()
    lost = sorted({part_of(c).name for c in cols} - {part_of(c).name for c in cols if c.name not in dropped})
    for c in [c for c in cols if c.name in dropped]:
        bpy.data.objects.remove(c)
    if lost:
        raise ValueError("clearance: carving left %s with no collider" % ", ".join(lost))
    after = {}
    for c in bpy.data.collections["Colliders"].objects:
        if part_of(c) is not None:
            after[part_of(c).name] = after.get(part_of(c).name, 0.0) + volume(c)
    kept = sorted((after.get(n, 0.0) / v, n) for n, v in before.items() if v > 0)
    return "clearance carve: %d cuts, %d hulls dropped (%s); hull volume kept, least: %s" % (
        cut_count, len(dropped), ", ".join(dropped[:12]), ", ".join("%s %.0f%%" % (n, 100 * f) for f, n in kept[:12]))


# --- the check -------------------------------------------------------------------------------------------------------

def check(icarus):
    bpy.context.view_layer.update()
    cols = [c for c in bpy.data.collections["Colliders"].objects if part_of(c) is not None]
    linked = links(cols)
    hinges = hinge_poses(icarus)
    gears = gear_sequences(cols)
    rest = {c.name: shape_of(world(c)) for c in cols}
    part = {c.name: part_of(c).name for c in cols}
    leg_of = {name: leg for leg, seq in gears.items() for name in seq[0]}
    moving = set(hinges) | {part[c] for c in leg_of}
    problems, pairs, least = [], 0, 1.0

    def judge(a, sa, b, sb, where):
        nonlocal pairs, least
        need = required(part[a], part[b], (part[a], part[b]) in linked)
        lo, hi = sa[0].min(0) - need, sa[0].max(0) + need
        if not (np.all(sb[0].min(0) <= hi) and np.all(lo <= sb[0].max(0))):
            return
        pairs += 1
        sep, _ = hulls.separation(sa, sb)
        least = min(least, sep - need)
        if sep < need - TOLERANCE:
            problems.append("%s and %s%s %.1f mm apart, need %.1f" % (a, b, where, sep * 1000, need * 1000))

    names = [c.name for c in cols]
    by_name = {c.name: c for c in cols}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            folded = by_name[a].get("folded_from") or by_name[b].get("folded_from")
            if part[a] == part[b] or (part[a], part[b]) in linked and not folded and not held_apart(part[a], part[b], moving):
                continue
            if a in leg_of and b in leg_of and leg_of[a] == leg_of[b]:
                continue  # one leg's own doors: judged along its retraction sequence below
            judge(a, rest[a], b, rest[b], "")
    for hinge, poses in hinges.items():
        for c in [c for c in cols if part[c.name] == hinge]:
            pts = np.array([v.co[:] for v in c.data.vertices])
            for k, m in enumerate(poses):
                sp = shape_of(np.array([((m @ c.matrix_world) @ Vector(p))[:] for p in pts]))
                for b in names:
                    if part[b] != hinge and (hinge, part[b]) not in linked:
                        judge(c.name, sp, b, rest[b], " (%s pose %d)" % (hinge, k))
    for leg, seq in gears.items():
        for k, pose in enumerate(seq):
            for a, pts in pose.items():
                sp = shape_of(pts)
                for b in names:
                    if part[b] == part[a] or (part[a], part[b]) in linked:
                        continue
                    sb = shape_of(pose[b]) if b in pose else rest[b]
                    if b in pose and b < a:
                        continue
                    judge(a, sp, b, sb, " (gear %s pose %d)" % (leg, k))
    if problems:
        raise ValueError("clearance check: %d pairs too close: %s" % (len(problems), "; ".join(problems[:25])))
    print("clearance check PASS: %d hulls, %d close pairs judged, least margin %.1f mm, contact offset %.0f mm, "
          "%d hinges and %d legs swept" % (len(cols), pairs, least * 1000, CONTACT_OFFSET * 1000, len(hinges), len(gears)))
