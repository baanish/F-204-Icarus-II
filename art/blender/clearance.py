"""Collider clearance between parts with no joint between them, so a part that breaks free collides with the rest of
the jet as a stock part does, and nothing touches while attached.

Unity's joints switch collision off between the two bodies each joins (AeroPart.CreateJoints sets enableCollision false;
a HingeJoint's default is false) until the joint breaks. Every other pair of the Icarus's colliders collides, so their
hulls must stand apart by REQUIRED: both colliders' contact offset (CONTACT_OFFSET, which the plugin pins on every
Icarus hull, src/Icarus/ContactOffset.cs; Unity's 10 mm default would make contacts across a 20 mm gap) plus the
most each flexes toward the other in flight (FLEX, measured in game and on the A18 bench). A gear leg's only collider in
Unity is a trigger at its hinge (IcarusAuthor.Gear.cs), which touches nothing, so the gear stands outside both.

carve() runs last on the collider set, after hulls.merge: each hull is cut flat on its best separating plane, or split
round the other part where one cut would keep too little of it (hulls.clear), REQUIRED short of every hull of a part
that outranks it (RANK: moving surfaces keep their shape, then the wing and fin
structure, the canopy and radome, and last the fuselage sections). Then each centreline part's hulls are cut to their
mirror images (hulls.symmetric), so the cuts leave the jet the same both sides. The parts' mass boxes are recorded
before the cut (mass_box), so the centres of mass the Unity author places from the hulls stay where they were.

check() fails the build where any two unjointed parts' hulls stand closer than REQUIRED.

Both judge every hull where it is built, at rest: no Icarus collider moves in game. The controllers turn a _hinge child
under each surface part and the canopy its hood, as stock controllers turn a _visible child, while the hulls sit on the
part itself (IcarusAuthor.Aero.cs BuildSurfaces, IcarusAuthor.Canopy.cs; ControlJobSettings, HighLiftDevice), and a gear
leg carries only a trigger.
"""
import bmesh
import bpy
import numpy as np
from mathutils import Vector

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
# Who keeps its shape where two hulls are too close: the lower rank is cut.
# Moving parts aren't listed: they rank above all. Fuselage sections yield to the parts inside them.
RANK = (("wing_spar_", 5), ("wing_skin_", 5), ("fin_spar", 5), ("fin_skin", 5), ("canopy", 4.5), ("skin_", 4),
        ("dorsal_cover", 4), ("radome", 4), ("nozzle", 2.5), ("engine_", 2.5), ("intake_duct_", 1.5), ("fuselage_", 0.5))
RANK_MOVING, RANK_DEFAULT = 6, 1
# Braces: second joints, as IcarusAuthor.Parts.cs Braces (A22 checks that table against the tree).
BRACES = (("stabilator", "fuselage_aft"), ("rudder", "fuselage_aft"), ("fin_skin", "fuselage_aft"),
          ("wing_spar_outer_L", "fuselage_mid"), ("wing_spar_outer_R", "fuselage_mid"), ("fuselage_tail", "fuselage_mid"),
          ("fin_spar", "fuselage_mid"))
GEAR = ("gear_leg_",)  # outside the clearance: their trigger touches nothing
TOLERANCE = 0.0002
# The carve clears this much past REQUIRED, so float error in the cut never leaves a pair a hair short in the check.
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


# Two parts a joint holds together never collide while it holds, but a fuselage section and a still part jointed to it,
# and a still part and a moving part jointed to it, still stand apart, so a part starts clear when its joint breaks: one
# freed inside a hull it overlaps takes a kick getting out, enough to break a neighbour's joint. Other jointed pairs may
# overlap (the fin spar lies inside the fin skin's hull).
JOINTED_GAP = 0.001
SECTIONS = ("fuselage_",)


def held_apart(a, b, moving):
    """Whether two jointed parts must still stand JOINTED_GAP apart: a fuselage section and a still part jointed to it,
    or a still part and a moving part jointed to it."""
    return (a in moving) != (b in moving) or (a.startswith(SECTIONS) or b.startswith(SECTIONS)) and not {a, b} & moving


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


def world(col):
    """A hull's world points."""
    return np.array([(col.matrix_world @ v.co)[:] for v in col.data.vertices])


def faces(col):
    return [list(p.vertices) for p in col.data.polygons]


def shape_of(points):
    bm = hulls.convex([Vector(p) for p in points])
    s = hulls.bm_shape(bm)
    bm.free()
    return s


# --- moving parts ----------------------------------------------------------------------------------------------------

def hinged(icarus):
    """The names of the hinged parts (parts.surface_sweep's surfaces): they keep their shape where hulls meet."""
    return {o.name for o in icarus.all_objects if o.type == "EMPTY" and "deflection_deg" in o
            and bpy.data.objects.get(o.name + "_visible") is not None}


# --- carving ---------------------------------------------------------------------------------------------------------

def keep_most(bm, s, o, need, sat_axis, candidates=16):
    """bm's hull (shape s) cut clear of obstacle o by need, keeping the most of its volume, as a new bmesh or None: of
    the face normals of either (both ways) and the separating axis, the planes need short of o that keep the largest
    share of s's extent, each cut and weighed. By extent alone the wing box kept a diagonal plane past its flap that cut
    a wedge out of the wing ahead of it; cutting along the separating axis alone can slice a shallow hull through its
    thickness."""
    axes = np.vstack([o[1], -o[1], s[1], -s[1], np.asarray(sat_axis)[None, :]]) if len(o[1]) and len(s[1]) else np.asarray(sat_axis)[None, :]
    ps, po = s[0] @ axes.T, o[0] @ axes.T
    at = po.min(0) - need - 1e-4
    lo, hi = ps.min(0), ps.max(0)
    kept = (at - lo) / np.maximum(hi - lo, 1e-9)
    best, best_volume = None, -1.0
    for i in np.argsort(-kept)[:candidates]:
        piece = hulls.cut(bm, Vector(axes[i]), float(at[i]))
        volume = abs(piece.calc_volume()) if piece is not None else 0.0
        if volume > best_volume:
            if best is not None:
                best.free()
            best, best_volume = piece, volume
        elif piece is not None:
            piece.free()
    return best


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


# The farthest fill() carries a hull's end toward the hull across a gap from it, metres.
FILL_REACH = 0.4


def fill(icarus, linked, moving):
    """Square each hull's ends off toward its neighbours, as the stock hulls abut: where the hull across a gap from it
    along an axis covers the same ground, its outline is carried out to that hull's face (the convex hull of its points
    and their projections onto that face), then cut back clear of every other part's hull and the keep-outs as the carve
    clears them (hulls.clear). A tapered end that left a wedge open to its neighbour comes out square, but no corner
    may stand further outside the visible skin than hulls.SKIN_REACH: the fin spar's swept edge, carried forward,
    stood 0.8 m clear of the fin in the air ahead of it. Only the body's
    still centreline parts grow, along and up and down it, so they stay the same both sides: the hinged surfaces already
    stand JOINTED_GAP off their carriers, and a wing grown toward its neighbours reached into the pylon stores' room
    (IcarusAuthor A14), which no keep-out here stands for. Returns the hulls that grew."""
    obstacles = hulls.keepouts()
    skin = hulls.visible_skin(icarus)
    grown = []
    for c in sorted((c for c in bpy.data.collections["Colliders"].objects
                     if part_of(c) is not None and not part_of(c).name.startswith(GEAR)), key=lambda c: c.name):
        cols = [o for o in bpy.data.collections["Colliders"].objects
                if part_of(o) is not None and not part_of(o).name.startswith(GEAR) and o is not c]
        pc = part_of(c).name
        if pc in moving or pc.endswith(("_L", "_R")):
            continue
        near = [{"shape": shape_of(world(o)), "gap": required(pc, part_of(o).name, (pc, part_of(o).name) in linked) + CARVE_SLACK}
                for o in cols if part_of(o).name != pc
                and ((pc, part_of(o).name) not in linked or held_apart(pc, part_of(o).name, moving))]
        near += [o for o in obstacles if pc not in o["exclude"]]
        pts = world(c)
        start = hulls.convex([Vector(p) for p in pts]).calc_volume()
        # one direction at a time, each kept where it grows the hull in one piece and gives up no ground elsewhere: grown
        # all ways at once, a hull that reaches round a neighbour is cut into pieces and keeps none of it, and a cut that
        # trims an end back opens the gap the growth was to close
        for k in (1, 2):
            for sign in (1, -1):
                lo, hi = pts.min(0), pts.max(0)
                face = hi[k] if sign > 0 else lo[k]
                across = []
                for o in cols:
                    q = world(o)
                    qlo, qhi = q.min(0), q.max(0)
                    if any(min(hi[j], qhi[j]) - max(lo[j], qlo[j]) <= 0.01 for j in range(3) if j != k):
                        continue
                    gap = (qlo[k] - face) if sign > 0 else (face - qhi[k])
                    if 0.001 < gap < FILL_REACH:
                        across.append(gap)
                if not across:
                    continue
                moved = pts.copy()
                moved[:, k] = face + sign * min(across)
                pieces = hulls.clear(hulls.convex([Vector(p) for p in np.vstack([pts, moved])]), near)
                if len(pieces) == 1 and abs(pieces[0].calc_volume()) > hulls.convex([Vector(p) for p in pts]).calc_volume() * 1.001:
                    new = np.array([v.co[:] for v in pieces[0].verts])
                    if (np.all(new.min(0) <= lo + 0.01) and np.all(new.max(0) >= hi - 0.01)
                            and hulls.skin_reach(skin, new)[0] <= hulls.SKIN_REACH):
                        pts = new
                for piece in pieces:
                    piece.free()
        piece = hulls.capped([Vector(p) for p in pts], hulls.MERGED_TRIS)
        if hulls.solid(piece) and abs(piece.calc_volume()) > start * 1.001:
            piece.transform(c.matrix_world.inverted())
            piece.to_mesh(c.data)
            grown.append(c.name)
        piece.free()
    bpy.context.view_layer.update()
    return grown


def trim(icarus):
    """Cut each hull back where a corner stands further outside the visible skin than hulls.SKIN_REACH: on the plane
    SKIN_REACH out from the skin across that corner, in turn while one does. Runs after hulls.symmetric, whose mirror
    cuts make corners on hull faces that span air (the rear truss's above the dorsal covers' gap); a centreline hull is
    cut on the mirror plane too, and recapped in mirror pairs, so it stays symmetric. Cutting only shrinks a hull, so it
    stays clear of what it was cleared from. Returns the hulls cut."""
    skin = hulls.visible_skin(icarus)
    trimmed = []
    for c in sorted(bpy.data.collections["Colliders"].objects, key=lambda c: c.name):
        centreline = not part_of(c).name.endswith(("_L", "_R"))
        bm = hulls.convex([Vector(p) for p in world(c)])
        cut = False
        for _ in range(8):
            worst, at = hulls.skin_reach(skin, [v.co for v in bm.verts])
            if worst <= hulls.SKIN_REACH:
                break
            q = skin.tree.find_nearest(at)[0]
            n = (at - q).normalized()
            for normal in [n, Vector((-n.x, n.y, n.z))][:2 if centreline else 1]:
                piece = hulls.cut(bm, normal, n.dot(q) + hulls.SKIN_REACH - 0.001)
                if piece is None:
                    break
                bm.free()
                bm, cut = piece, True
            if piece is None:
                break
        if cut:
            capped = hulls.capped([v.co.copy() for v in bm.verts], hulls.MERGED_TRIS, paired=centreline)
            bm.free()
            bm = capped
            bm.transform(c.matrix_world.inverted())
            bm.to_mesh(c.data)
            trimmed.append(c.name)
        bm.free()
    bpy.context.view_layer.update()
    return trimmed


def carve(icarus):
    """Cut every hull clear of the hulls of unjointed parts that outrank it; returns a report line."""
    bpy.context.view_layer.update()  # the split pieces' hulls were parented since the last update: their world matrices are stale
    cols = [c for c in bpy.data.collections["Colliders"].objects if part_of(c) is not None]
    mass_box(cols)
    cols = [c for c in cols if not part_of(c).name.startswith(GEAR)]
    linked = links(cols)
    moving = hinged(icarus)
    rank = lambda c: (RANK_MOVING if part_of(c).name in moving else first(RANK, part_of(c).name,
                                                                           RANK_DEFAULT), part_of(c).name)

    order = sorted(cols, key=rank)
    cut_count, dropped = 0, []
    volume = lambda c: hulls.convex([Vector(p) for p in world(c)]).calc_volume()
    before = {}
    for c in cols:
        before[part_of(c).name] = before.get(part_of(c).name, 0.0) + volume(c)
    for i, c in enumerate(order):
        pc = part_of(c).name
        # a hull yields to every part ranked above it; moving parts also clear one another both ways
        others = [o for o in (order if pc in moving else order[i + 1:]) if o is not c and o.name not in dropped
                  and (pc not in moving or part_of(o).name in moving)]
        others = [o for o in others if part_of(o).name != pc and ((pc, part_of(o).name) not in linked
                                                                  or held_apart(pc, part_of(o).name, moving))]
        if not others:
            continue
        shapes = [(shape_of(world(o)), required(pc, part_of(o).name, (pc, part_of(o).name) in linked) + CARVE_SLACK)
                  for o in others]
        bm = hulls.convex([Vector(p) for p in world(c)])
        pts = np.array([v.co[:] for v in bm.verts])
        lo, hi = pts.min(0) - 0.05, pts.max(0) + 0.05
        near = [{"shape": o, "gap": need - TOLERANCE} for o, need in shapes
                if np.all(o[0].min(0) <= hi) and np.all(lo <= o[0].max(0))]
        # a section round a part jointed inside it splits round that part, as the keep-outs do (hulls.clear), rather
        # than losing most of its hull to one cut
        pieces = hulls.clear(bm, near)
        if pieces == [bm]:
            bm.free()
            continue
        cut_count += 1
        if not pieces:
            dropped.append(c.name)  # removed after the pass: later hulls still read the list
            continue
        to_local = c.parent.matrix_world.inverted()
        for k, piece in enumerate(pieces):
            piece.transform(to_local)
            if k == 0:
                piece.to_mesh(c.data)
            else:
                me = bpy.data.meshes.new("%s_%d" % (c.name, k))
                piece.to_mesh(me)
                hulls.attach(me.name, me, c.parent, bpy.data.collections["Colliders"]).display_type = "WIRE"
            piece.free()
    lost = sorted({part_of(c).name for c in cols} - {part_of(c).name for c in cols if c.name not in dropped})
    for c in [c for c in cols if c.name in dropped]:
        bpy.data.objects.remove(c)
    if lost:
        raise ValueError("clearance: carving left %s with no collider" % ", ".join(lost))
    bpy.context.view_layer.update()  # the pieces the split added have no world matrix yet
    grown = fill(icarus, links([c for c in bpy.data.collections["Colliders"].objects
                                if part_of(c) is not None and not part_of(c).name.startswith(GEAR)]), moving)
    centreline = {}
    for c in bpy.data.collections["Colliders"].objects:
        if part_of(c) is not None and not part_of(c).name.endswith(("_L", "_R")):
            centreline.setdefault(part_of(c).name, []).append(c)
    for cs in centreline.values():
        shapes = []
        for c in cs:
            bm = bmesh.new()
            bm.from_mesh(c.data)
            bm.transform(c.matrix_world)
            shapes.append(bm)
        for c, bm in zip(cs, hulls.symmetric(shapes)):
            bm.transform(c.matrix_world.inverted())
            bm.to_mesh(c.data)
            bm.free()
    trimmed = trim(icarus)
    after = {}
    for c in bpy.data.collections["Colliders"].objects:
        if part_of(c) is not None:
            after[part_of(c).name] = after.get(part_of(c).name, 0.0) + volume(c)
    kept = sorted((after.get(n, 0.0) / v, n) for n, v in before.items() if v > 0)
    return ("clearance carve: %d hulls cut, %d dropped (%s), %d squared off toward their neighbours (%s), %d trimmed to "
            "the skin (%s); hull volume kept, least: %s") % (
        cut_count, len(dropped), ", ".join(dropped[:12]), len(grown), ", ".join(grown), len(trimmed), ", ".join(trimmed),
        ", ".join("%s %.0f%%" % (n, 100 * f) for f, n in kept[:12]))


# --- the check -------------------------------------------------------------------------------------------------------

def check(icarus):
    bpy.context.view_layer.update()
    cols = [c for c in bpy.data.collections["Colliders"].objects if part_of(c) is not None
            and not part_of(c).name.startswith(GEAR)]
    linked = links(cols)
    rest = {c.name: shape_of(world(c)) for c in cols}
    part = {c.name: part_of(c).name for c in cols}
    moving = hinged(icarus)
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
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if part[a] == part[b] or (part[a], part[b]) in linked and not held_apart(part[a], part[b], moving):
                continue
            judge(a, rest[a], b, rest[b], "")
    if problems:
        raise ValueError("clearance check: %d pairs too close: %s" % (len(problems), "; ".join(problems[:25])))
    print("clearance check PASS: %d hulls, %d close pairs judged, least margin %.1f mm, contact offset %.0f mm, "
          "%d hinged parts at rest" % (len(cols), pairs, least * 1000, CONTACT_OFFSET * 1000, len(moving)))
