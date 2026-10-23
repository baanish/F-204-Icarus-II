"""Convex collision pieces and LOD1 hulls for the export contract.

The exporter (tools/export_blockout.py) takes meshes in the "Colliders" collection as convex pieces of their parent
part, and one mesh per part in "LOD1" as its far-distance stand-in. Each sits at an identity transform under its part,
so its vertices are in the part's own space. Unity caps a convex collider at 255 vertices.

LOD1 is one hull per part seen from outside, its triangles capped by LOD1_TRIS so the set stays inside Exterior rule
27's 56 per hull and 760 in all. The parts under the skin get none: at that distance the skin's hulls hide them. A
hull over its cap keeps the points that reach furthest out (hull_mesh), so it never grows past the part.

A hit lands on the part whose collider it touches, so colliders follow what the part is, and only parts get them
(the Unity author makes a part of every mesh with mass and of every fuel cell). Compact parts use their LOD1 hull, or
one capped at COLLIDER_TRIS. Curved skin panels and the wing and fin skins get up to PATCHES thin patches, each split
where its hull sits deepest under the skin: one hull of a curved panel would be a solid block hiding the fuel cells
and gear wells under it, and the LandingGear ground cast would meet it. Near the conformal stores every patch also
keeps to one side of each stations.collider_splits() plane, which can take a panel past PATCHES. The structure cores
carry SHELLS pieces of their frames round the body axis, and the intake ducts short chunks.

On the local sim each part is a Rigidbody of its own, held by FixedJoints that stop collisions only between the two
parts they join, so the hulls of two parts no joint joins must not touch: separate() cuts and carves them GAP apart,
and check() fails on any pair closer (part_clearance()). A structure core's keep clear even of the parts jointed to
it (touching_pairs()). A fuel cell's hull, convex over its duct cut-out, is carved
round the duct.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import build_icarus as bi
import stations

MAX_HULL = 255
LOD_GREY = (0.14, 0.14, 0.14, 1.0)  # the colour the Unity author checks LOD1 meshes for
# Animated petals and seals, and the pylon blades and plugs the game shows and hides by station: no collider or LOD,
# since a LOD1 hull would stay drawn at a distance whichever of them is hidden.
SKIP = ("nozzle_petal_", "nozzle_seal_", "pylon_")
# Renderers that stay visuals of their part (glass, wheels, lenses, exterior proxies) and the cockpit view's renderers
# get neither. Role "cockpit" is the cockpit_cell part itself, which keeps both.
SKIP_ROLES = ("visual", "cockpit_view")
# LOD1 triangles per hull by name prefix, first match, else LOD1_DEFAULT: the fuselage panels and the big surfaces
# get the most.
LOD1_TRIS = (("skin_", 40), ("radome", 32), ("nozzle", 32), ("dorsal_cover", 24), ("canopy_visible", 24),
             ("wing_skin_", 24), ("stabilator", 24), ("fin_skin", 20))
LOD1_DEFAULT = 12
LOD1_PER_HULL, LOD1_TOTAL = 56, 760
# Parts inside the skin's LOD1 hulls, which get none of their own.
LOD1_HIDDEN = ("fuselage_", "wing_spar_", "fin_spar", "engine_core", "cockpit_cell", "radar_tray", "avionics_tray",
               "fuel_", "intake_duct_")
COLLIDER_TRIS = 24  # a collider piece of a part with no LOD1 hull
# Thin skin patches: at most PATCHES a panel (more only where the trough's cuts make them) of PATCH_TRIS triangles,
# split no further once each stands no thicker than PATCH_DEPTH on average (hull volume over skin area). A patch
# with no volume (a flat stretch of skin) is thickened THIN inward, since PhysX cooks no convex collider without it.
PATCHED = ("skin_", "radome", "dorsal_cover", "wing_skin_", "fin_skin")
BODY = ("skin_", "radome", "dorsal_cover")  # panels round the body axis, which also split by angle round it
PATCHES, PATCH_TRIS = 6, 32
PATCH_DEPTH = 0.04
THIN = 0.01
BODY_AXIS_Z = 0.3  # height of the axis body patches split by angle around
# A panel is cut round a box SPLIT_NEAR beyond each side's conformal store capsules, and the patches inside it keep
# to one side of each collider_splits() plane; a patch reaching less than SPLIT_SLACK past a plane does not count as
# crossing it (Unity's A14 allows 0.005 m). Away from the stores there is no trough for a patch to span.
SPLIT_NEAR, SPLIT_SLACK = 0.05, 0.004
DUCT_CHUNKS = 6
STRUCTURE_CORES = ("fuselage_forward", "fuselage_mid", "fuselage_aft")
SHELLS = 4  # a structure core's pieces round its axis
# On the local sim every part is its own Rigidbody, and a FixedJoint stops collisions only between the two parts it
# joins, so the colliders of parts no joint joins keep GAP apart (separate(), touching_pairs()): twice the 0.005 m
# the Unity checks allow, and clear of the joints' sag. The game reports contacts out to about 0.04 m (two 0.02 m
# contact offsets), but those carry no impulse until the hulls meet. A cut leaves MARGIN more. A part's surface counts
# as covered within COVER of its hulls; a plane cut must keep CLIP_KEEP of what the hull covers, and a carved piece
# goes under PIECE_MIN m^3 or where it covers no more than PIECE_COVER of its part's surface.
GAP, MARGIN, COVER = 0.01, 0.0005, 0.02
CLIP_KEEP, PIECE_MIN, PIECE_COVER = 0.9, 1e-3, 0.02
CLEARANCE_TRIS = 48  # a hull's triangles after the cuts
# The outside of the aircraft, which gives way last when two hulls keep alike; gear legs, which Unity gives a
# GEAR_HINGE_BOX cube at the hinge instead of their hulls, never give way.
OUTER = PATCHED + ("canopy", "nozzle", "stabilator", "rudder", "aileron_", "flap_", "lef_")
GEAR_LEGS, GEAR_HINGE_BOX = "gear_leg_", 0.15

# LOD1 and collider limits, by collection: triangles in total (budget.py sums them).
BUDGET = {
    "lod1": {"target": 760, "cap": 760, "collection": "LOD1"},
    "colliders": {"target": 3000, "cap": 3000, "collection": "Colliders"},
}
CLOSEUPS = {}
COLLIDER_HULLS = 120  # provisional: gives way to hit access, the trough's clearance and the gear's ground cast


def check(icarus):
    import budget

    lods = [o for o in bpy.data.collections["LOD1"].objects]
    cols = [o for o in bpy.data.collections["Colliders"].objects]
    sizes = [budget.tris(o) for o in lods]
    problems = ["%s %d triangles" % (o.name, n) for o, n in zip(lods, sizes) if n > LOD1_PER_HULL]
    if sum(sizes) > LOD1_TOTAL:
        problems.append("LOD1 %d triangles in all" % sum(sizes))
    if problems:
        raise ValueError("hulls check: LOD1 over %d per hull or %d in all: %s" % (LOD1_PER_HULL, LOD1_TOTAL, "; ".join(problems)))
    (least, a, b), close = part_clearance(icarus)
    if close:
        raise ValueError("hulls part clearance: %d collider pairs that may not touch under %.3f m: %s" % (
            len(close), GAP, "; ".join(close)))
    print("hulls part clearance PASS: every two colliders that may not touch at least %.3f m apart, least %.4f m "
          "(%s, %s)" % (GAP, least, a, b))
    col_tris = sum(budget.tris(o) for o in cols)
    print("hulls check PASS: LOD1 %d hulls, %d triangles, largest %d; colliders %d hulls (provisional cap %d), %d "
          "triangles (provisional cap %d)" % (len(lods), sum(sizes), max(sizes), len(cols), COLLIDER_HULLS, col_tris,
                                              BUDGET["colliders"]["cap"]))


def tris_of(bm):
    return sum(len(f.verts) - 2 for f in bm.faces)


def convex(points):
    """The convex hull of points as a bmesh, interior points dropped."""
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p)
    res = bmesh.ops.convex_hull(bm, input=list(bm.verts))
    loose = {e for e in res["geom_interior"] + res["geom_unused"] if isinstance(e, bmesh.types.BMVert)}
    bmesh.ops.delete(bm, geom=list(loose), context="VERTS")
    bm.normal_update()
    return bm


def outside(bm, pts):
    """How far each point (rows of pts) lies outside the hull bm; a flat hull counts both sides."""
    centre = sum((v.co for v in bm.verts), Vector()) / max(1, len(bm.verts))
    out = np.full(len(pts), -np.inf)
    for f in bm.faces:
        n = f.normal
        c = f.calc_center_median()
        d = pts @ np.array(n) - n.dot(c)
        side = n.dot(c - centre)
        out = np.maximum(out, d if side > 1e-9 else -d if side < -1e-9 else np.abs(d))
    return out


def capped(points, max_tris):
    """Convex hull of points in at most max_tris triangles, as a bmesh: the extremes along each axis, then the point
    furthest outside, one at a time, while the hull stays under the cap. It lies inside the points' own hull."""
    bm = convex(points)
    if tris_of(bm) <= max_tris:
        return bm
    full = np.array([v.co[:] for v in bm.verts])
    bm.free()
    chosen = list(dict.fromkeys(int(i) for k in range(3) for i in (full[:, k].argmin(), full[:, k].argmax())))
    best = convex([full[i] for i in chosen])
    while True:
        out = outside(best, full)
        out[chosen] = -np.inf
        j = int(out.argmax())
        if out[j] <= 1e-6:
            return best
        trial = convex([full[i] for i in chosen + [j]])
        if tris_of(trial) > max_tris:
            trial.free()
            return best
        best.free()
        best, chosen = trial, chosen + [j]


def solid(bm):
    """A hull fit to be a convex collider: four faces or more and some volume."""
    return len(bm.faces) >= 4 and bm.calc_volume() >= 1e-4


def hull_mesh(name, points, max_tris):
    """Convex hull of points in at most max_tris triangles as a mesh, or None where it has no volume."""
    bm = capped(points, max_tris)
    if not solid(bm):  # flat (coplanar points hull to two faces): no use as a collider
        bm.free()
        return None
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def attach(name, mesh, owner, col):
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    obj.parent = owner
    obj.matrix_parent_inverse.identity()
    obj.matrix_basis.identity()
    return obj


def lod_material():
    mat = bpy.data.materials.get("LOD") or bpy.data.materials.new("LOD")
    mat.diffuse_color = LOD_GREY
    return mat


def lod_tris(name):
    return next((n for prefix, n in LOD1_TRIS if name.startswith(prefix)), LOD1_DEFAULT)


# --- splitting a mesh into pieces ---------------------------------------------------------------------------------

def world_bm(owner):
    bm = bmesh.new()
    bm.from_mesh(owner.data)
    bm.transform(owner.matrix_world)
    return bm


def halves(bm, co, no):
    """The two sides of bm cut by the plane (co, no), each keeping the cut edge, so their hulls meet on it."""
    out = []
    for keep_front in (False, True):
        half = bm.copy()
        bmesh.ops.bisect_plane(half, geom=list(half.verts) + list(half.edges) + list(half.faces), dist=1e-6,
                               plane_co=co, plane_no=no, clear_inner=keep_front, clear_outer=not keep_front)
        out.append(half)
    return out


def points_of(bm):
    return [v.co.copy() for v in bm.verts]


def crosses(pts, co, no, slack=SPLIT_SLACK):
    d = [(p - co).dot(no) for p in pts]
    return min(d) < -slack and max(d) > slack


def axis_planes(pts):
    """Mid planes across each axis of the points' bounds that spans more than 5 cm."""
    lo = Vector([min(p[k] for p in pts) for k in range(3)])
    hi = Vector([max(p[k] for p in pts) for k in range(3)])
    out = []
    for k in range(3):
        if hi[k] - lo[k] > 0.05:
            no = Vector((0, 0, 0))
            no[k] = 1
            out.append(((lo + hi) / 2, no))
    return out


def angle_plane(pts):
    """The plane through the body axis at the middle of a one-sided piece's angle round it, or None."""
    side = 1 if sum(p.x for p in pts) >= 0 else -1
    if any(p.x * side < -0.01 for p in pts):
        return None
    angles = [math.atan2(side * p.x, p.z - BODY_AXIS_Z) for p in pts]
    a = (min(angles) + max(angles)) / 2
    if max(angles) - min(angles) < math.radians(10):
        return None
    return Vector((0, 0, BODY_AXIS_Z)), Vector((side * math.cos(a), 0, -math.sin(a)))


def best_first(pieces, excess, planes, limit):
    """Split the piece with the most excess by whichever candidate plane leaves its halves the least excess in all,
    until no piece has any (excess > 0) or there are limit pieces. A piece no candidate improves is left whole.
    pieces are bmeshes."""
    scored = [(excess(p), p) for p in pieces]
    stuck = set()
    while len(scored) < limit:
        open_ = [i for i, (e, p) in enumerate(scored) if e > 0 and id(p) not in stuck]
        if not open_:
            break
        worst = max(open_, key=lambda i: scored[i][0])
        score, piece = scored[worst]
        best = []
        for co, no in planes(points_of(piece)):
            trial = halves(piece, co, no)
            scored_trial = [(excess(h), h) for h in trial] if min(len(h.verts) for h in trial) >= 4 else []
            if scored_trial and (not best or sum(e for e, _ in scored_trial) < sum(e for e, _ in best)):
                best, trial = scored_trial, [h for _, h in best]
            for h in trial:
                h.free()
        if not best or sum(e for e, _ in best) >= score:
            for _, h in best:
                h.free()
            stuck.add(id(piece))
            continue
        piece.free()
        scored[worst:worst + 1] = best
    return [p for _, p in scored]


# --- skin patches --------------------------------------------------------------------------------------------------

def patch_hull(pts, normals=None):
    """A patch's hull bmesh, thickened THIN inward if it has no volume, or None."""
    bm = capped(pts, PATCH_TRIS)
    if not solid(bm) and normals:
        bm.free()
        bm = capped(pts + [p - n * THIN for p, n in zip(pts, normals)], PATCH_TRIS)
    if not solid(bm):
        bm.free()
        return None
    return bm


def thickness(hull, piece):
    """A patch's hull volume over its skin's area: how thick it stands on average."""
    return hull.calc_volume() / max(1e-9, sum(f.calc_area() for f in piece.faces))


def store_boxes():
    """Each side's conformal store capsules together as one box grown by SPLIT_NEAR, (lo, hi), Blender world space."""
    out = []
    for side in (1, -1):
        caps = stations.capsules(side)
        out.append((Vector([min(min(a[k], b[k]) - r for _, a, b, r in caps) - SPLIT_NEAR for k in range(3)]),
                    Vector([max(max(a[k], b[k]) + r for _, a, b, r in caps) + SPLIT_NEAR for k in range(3)])))
    return out


def in_box(pts, box):
    """Whether the points' bounds reach more than SPLIT_SLACK into the box."""
    lo, hi = box
    return all(max(p[k] for p in pts) > lo[k] + SPLIT_SLACK and min(p[k] for p in pts) < hi[k] - SPLIT_SLACK
               for k in range(3))


def cut_all(pieces, co, no, where):
    """Each piece that where(points) picks and the plane crosses, cut in two along it."""
    out = []
    for piece in pieces:
        pts = points_of(piece)
        if not (where(pts) and crosses(pts, co, no)):
            out.append(piece)
            continue
        for half in halves(piece, co, no):
            if len(half.verts) >= 4:
                out.append(half)
            else:
                half.free()
        piece.free()
    return out


def skin_patches(owner):
    """The panel cut into thin patches, world-space bmeshes, and how many more patches the trough's cuts make.
    A body panel round both sides is first cut down the centre line, which no cut through the axis would choose
    alone (each half is as thick), but which lets the angle cuts follow. The panel is cut round each side's store
    box, and the pieces in a box by every collider_splits() plane. Then the piece whose hull stands thickest past
    PATCH_DEPTH (by volume) is split, by station, height, span or angle round the body, until none does or there are
    PATCHES besides those the trough's cuts made."""
    body = owner.name.startswith(BODY)
    boxes = store_boxes()
    pieces = [world_bm(owner)]
    if body:
        pieces = cut_all(pieces, Vector(), Vector((1, 0, 0)), lambda pts: True)
    before = len(pieces)
    for box in boxes:
        lo, hi = box
        for k in range(3):
            no = Vector((0, 0, 0))
            no[k] = 1
            for co in (lo, hi):
                pieces = cut_all(pieces, co, no, lambda pts, box=box: in_box(pts, box))
    near = lambda pts: any(in_box(pts, box) for box in boxes)
    for co, no in stations.collider_splits():
        pieces = cut_all(pieces, co, no, near)
    trough = len(pieces) - before

    def excess(piece):  # on the uncapped hull, whose volume a cut can only shrink
        hull = convex(points_of(piece))
        out = hull.calc_volume() - PATCH_DEPTH * sum(f.calc_area() for f in piece.faces)
        hull.free()
        return out

    def planes(pts):
        out = axis_planes(pts)
        a = angle_plane(pts) if body else None
        return out + ([a] if a else [])

    return best_first(pieces, excess, planes, PATCHES + trough), trough


# --- clearance between parts -----------------------------------------------------------------------------------------

def shape(points, faces):
    """A convex hull as arrays for separation(): world vertices, unit face normals and unit edge directions."""
    v = np.array([p[:] for p in points], dtype=float)
    normals, edges = [], set()
    for f in faces:
        a, b, c = (v[f[0]], v[f[1]], v[f[2]])
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) > 1e-12:
            n /= np.linalg.norm(n)
            d = v @ n - n @ a
            if d.max() < 1e-6 or d.min() > -1e-6:  # a face that cuts through the hull is no separating axis
                normals.append(n)
        for i, j in zip(f, f[1:] + f[:1]):
            edges.add((min(i, j), max(i, j)))
    e = np.array([v[j] - v[i] for i, j in edges])
    e = e[np.linalg.norm(e, axis=1) > 1e-9]
    return v, np.array(normals), e / np.linalg.norm(e, axis=1)[:, None]


def bm_shape(bm):
    idx = {v: i for i, v in enumerate(bm.verts)}
    return shape([v.co for v in bm.verts], [[idx[v] for v in f.verts] for f in bm.faces])


def obj_shape(obj):
    m = obj.matrix_world
    return shape([m @ v.co for v in obj.data.vertices], [list(p.vertices) for p in obj.data.polygons])


def separation(a, b):
    """How far apart two convex hulls stand along their best separating axis (face normals of either, crossings of
    an edge of each), and that axis, unit, pointing from a to b. Negative is the depth they interpenetrate, exactly;
    positive is never more than their true distance."""
    va, na, ea = a
    vb, nb, eb = b
    cross = np.cross(ea[:, None, :], eb[None, :, :]).reshape(-1, 3)
    size = np.linalg.norm(cross, axis=1)
    axes = np.vstack([na, nb, cross[size > 1e-6] / size[size > 1e-6, None]])
    pa, pb = va @ axes.T, vb @ axes.T
    ahead, behind = pb.min(0) - pa.max(0), pa.min(0) - pb.max(0)
    i, j = int(ahead.argmax()), int(behind.argmax())
    return (ahead[i], axes[i]) if ahead[i] >= behind[j] else (behind[j], -axes[j])


def part_of(owner_name):
    """The Unity part a collider's owner mesh becomes: a hinged surface's _visible mesh is its hinge's part."""
    return owner_name[:-len("_visible")] if owner_name.endswith("_visible") else owner_name


def touching_pairs(owners):
    """The pairs of parts whose colliders may touch, as frozensets: those a joint joins, each part and the nearest part
    above it in the Blender tree, which the Unity author joints it to (a hinged surface's part is its hinge empty, its
    _visible mesh's parent). Not a structure core's: its shells stay a band under the skin, clear of what it holds, so
    a part that breaks away does not start inside one."""
    parts = {part_of(o.name): o.parent if o.name.endswith("_visible") else o for o in owners}
    out = set()
    for part, obj in parts.items():
        up = obj.parent
        while up is not None and part_of(up.name) not in parts:
            up = up.parent
        if up is not None and part not in STRUCTURE_CORES and part_of(up.name) not in STRUCTURE_CORES:
            out.add(frozenset((part, part_of(up.name))))
    return out


def tier(part):
    """Which part gives way where two collide: the lower tier, or both alike when equal."""
    if part.startswith(GEAR_LEGS):
        return 3
    if part.startswith(OUTER):
        return 2
    return 0 if part in STRUCTURE_CORES else 1


def gear_box(owner):
    """The hinge box Unity puts on a gear leg in place of its hulls (IcarusAuthor.Gear.cs GearHingeBox), world space."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=GEAR_HINGE_BOX, matrix=owner.matrix_world)
    return bm


def cut(bm, n, c):
    """bm's hull cut to the side n.x <= c, as a new bmesh, or None where nothing solid is left."""
    d = {v: v.co.dot(n) - c for v in bm.verts}
    pts = [v.co.copy() for v in bm.verts if d[v] <= 1e-7]
    for e in bm.edges:
        a, b = e.verts
        if min(d[a], d[b]) < -1e-7 and max(d[a], d[b]) > 1e-7:
            pts.append(a.co.lerp(b.co, d[a] / (d[a] - d[b])))
    # bmesh's hull makes faces that cut through it when two points nearly coincide
    pts = list({tuple(round(x, 6) for x in p): p for p in pts}.values())
    if len(pts) < 4:
        return None
    out = convex(pts)
    if not solid(out):
        out.free()
        return None
    return out


def face_planes(bm):
    """bm's face planes, (outward unit normal, offset), coplanar faces once; a face that cuts through the hull (see
    cut()) is left out, so they bound a little more than the hull, never less."""
    centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    out = []
    for f in bm.faces:
        n = f.normal.copy()
        if n.dot(f.calc_center_median() - centre) < 0:
            n.negate()
        c = n.dot(f.verts[0].co)
        if max(v.co.dot(n) for v in bm.verts) > c + 1e-6:
            continue
        if not any((n - m).length < 1e-4 and abs(c - k) < 1e-5 for m, k in out):
            out.append((n, c))
    return out


def carve(bm, other, gap):
    """bm's hull less other's hull grown by gap, as convex pieces, each beyond one of other's face planes by gap:
    the biggest piece first, so few are left. Pieces under PIECE_MIN go."""
    rest, todo, pieces = bm.copy(), face_planes(other), []
    while todo and rest is not None:
        trials = [cut(rest, -n, -(c + gap)) for n, c in todo]
        vols = [t.calc_volume() if t else 0.0 for t in trials]
        k = max(range(len(todo)), key=vols.__getitem__)
        for i, t in enumerate(trials):
            if t and i != k:
                t.free()
        if vols[k] < PIECE_MIN:
            if trials[k]:
                trials[k].free()
            break
        pieces.append(trials[k])
        n, c = todo.pop(k)
        nxt = cut(rest, n, c + gap)
        rest.free()
        rest = nxt
    if rest is not None:
        rest.free()
    return pieces


def covered(pts, bm):
    """Which rows of pts (world points) lie inside bm's hull or within COVER of it."""
    faces = face_planes(bm)
    n = np.array([f[0][:] for f in faces])
    c = np.array([f[1] for f in faces])
    return (pts @ n.T - c).max(1) <= COVER


def separate(by_part, fixed, touching, surface):
    """Cut and carve the hulls (by_part: {part: [world bmesh]}, changed in place) until any two of parts not in
    touching (touching_pairs()) stand GAP apart; fixed holds hulls that never give way (the gear hinge boxes). Of a
    pair, the hull that keeps more of what it covers of its part's own surface (surface: {part: world vertex array})
    gives way, since a hull's reach past its part's surface is only convexity: equal tiers whose cuts both keep
    CLIP_KEEP lose half the clearance each; else that hull is cut flat if the cut keeps CLIP_KEEP, or carved round the
    other. The lower tier gives way when they keep alike, and a structure core's always. Pieces of one hull then join
    back wherever they still clear everything. Returns the report line."""
    items, conflicts = {}, {}
    counter = iter(range(10 ** 9))
    ops = {"halved": 0, "cut": 0, "carved": 0, "dropped": 0, "merged": 0}

    def add(part, bm, own=None, origin=None):
        i = next(counter)
        s = bm_shape(bm)
        items[i] = {"part": part, "bm": bm, "shape": s, "lo": s[0].min(0), "hi": s[0].max(0), "own": own,
                    "origin": origin}
        for j, o in list(items.items()):
            if (j != i and o["part"] != part and (origin is not None or o["origin"] is not None)
                    and frozenset((part, o["part"])) not in touching
                    and np.all(items[i]["lo"] <= o["hi"] + GAP) and np.all(o["lo"] <= items[i]["hi"] + GAP)):
                sep, axis = separation(s, o["shape"])
                if sep < GAP:
                    conflicts[(i, j)] = (sep, axis)

    def remove(i):
        for key in [k for k in conflicts if i in k]:
            del conflicts[key]
        items.pop(i)["bm"].free()

    def replace(k, new, bare=True):
        """Item k's hull swapped for new ones; bare=False drops those that cover none of its part's surface (a
        carved piece of the hull's bulk)."""
        part, own, origin = items[k]["part"], items[k]["own"], items[k]["origin"]
        remove(k)
        for bm in new:
            if bm is None:
                continue
            mine = own[covered(own, bm)]
            if bare or len(mine) > PIECE_COVER * len(surface[part]):
                add(part, bm, mine, origin)
            else:
                bm.free()

    for part, bms in fixed.items():
        for bm in bms:
            add(part, bm)
    for part, bms in by_part.items():
        for bm in bms:
            add(part, bm, surface[part][covered(surface[part], bm)], next(counter))
    first = len(conflicts)

    def share(k, keep):
        """The share of what item k covers of its part's surface that keep(points) leaves covered."""
        own = items[k]["own"]
        return float(keep(own).mean()) if len(own) else 1.0

    for step in range(20000):
        if not conflicts:
            break
        (i, j), (sep, axis) = min(conflicts.items(), key=lambda kv: kv[1][0])
        n = Vector(axis)
        deficit = GAP + MARGIN - sep
        top = max(v.co.dot(n) for v in items[i]["bm"].verts)
        low = min(v.co.dot(n) for v in items[j]["bm"].verts)
        # item i keeps n.x <= top - d, item j keeps n.x >= low + d
        plane = {i: lambda d: (n, top - d), j: lambda d: (-n, -(low + d))}
        movable = [k for k in (i, j) if items[k]["origin"] is not None]
        tiers = {k: tier(items[k]["part"]) for k in movable}

        def cut_share(k, d):
            m, c = plane[k](d)
            return share(k, lambda pts: pts @ np.array(m[:]) <= c + COVER)

        def yielder(score):  # a core's shells only fill what the rest leave them
            return max(movable, key=lambda k: (tiers[k] == 0, round(score[k], 3), -tiers[k]))

        if (len(movable) == 2 and tiers[i] == tiers[j]
                and min(cut_share(k, deficit / 2) for k in movable) >= CLIP_KEEP):
            for k in movable:
                replace(k, [cut(items[k]["bm"], *plane[k](deficit / 2))])
            ops["halved"] += 1
            continue
        score = {k: cut_share(k, deficit) for k in movable}
        k = yielder(score)
        if score[k] >= CLIP_KEEP:
            replace(k, [cut(items[k]["bm"], *plane[k](deficit))])
            ops["cut"] += 1
            continue

        def carve_share(k):
            faces = face_planes(items[j if k == i else i]["bm"])
            nn = np.array([f[0][:] for f in faces])
            cc = np.array([f[1] for f in faces])
            return share(k, lambda pts: (pts @ nn.T - cc).max(1) > GAP - COVER)

        k = yielder({k: carve_share(k) for k in movable})
        pieces = carve(items[k]["bm"], items[j if k == i else i]["bm"], GAP + MARGIN)
        ops["carved" if pieces else "dropped"] += 1
        replace(k, pieces, bare=False)
    else:
        raise ValueError("hulls: the parts' colliders still collide after 20000 steps")

    # Pieces of one hull join back wherever the hull of the two still stands GAP clear of every other part.
    def clear(bm, part, skip):
        s = bm_shape(bm)
        lo, hi = s[0].min(0) - GAP, s[0].max(0) + GAP
        return all(separation(s, o["shape"])[0] >= GAP for k, o in items.items()
                   if k not in skip and o["part"] != part and frozenset((part, o["part"])) not in touching
                   and np.all(o["lo"] <= hi) and np.all(lo <= o["hi"]))

    merging, failed = True, set()
    while merging:
        merging = False
        groups = {}
        for k, it in items.items():
            if it["origin"] is not None:
                groups.setdefault(it["origin"], []).append(k)
        for keys in groups.values():
            centre = {k: items[k]["shape"][0].mean(0) for k in keys}
            pairs = sorted((float(np.linalg.norm(centre[a] - centre[b])), a, b)
                           for x, a in enumerate(keys) for b in keys[x + 1:])
            for _, a, b in pairs:
                if (a, b) in failed:
                    continue
                union = convex(points_of(items[a]["bm"]) + points_of(items[b]["bm"]))
                if clear(union, items[a]["part"], (a, b)):
                    part, origin = items[a]["part"], items[a]["origin"]
                    own = np.vstack([items[a]["own"], items[b]["own"]])
                    remove(a)
                    remove(b)
                    add(part, union, own, origin)
                    ops["merged"] += 1
                    merging = True
                    break
                failed.add((a, b))
                union.free()
    for part in by_part:
        by_part[part] = [it["bm"] for it in items.values() if it["part"] == part and it["origin"] is not None]
        if not by_part[part]:
            raise ValueError("hulls: %s lost every collider keeping clear of its neighbours" % part)
    for it in items.values():
        if it["origin"] is None:
            it["bm"].free()
    return "%d pairs closer than %.3f m resolved in %d steps (%s)" % (
        first, GAP, step, ", ".join("%d %s" % (v, k) for k, v in ops.items()))


def part_clearance(icarus):
    """The least separation between any two exported colliders that may not touch (touching_pairs(); gear legs as
    their hinge boxes), and each pair under GAP."""
    shapes = []
    touching = touching_pairs({o.parent for o in bpy.data.collections["Colliders"].objects})
    for obj in bpy.data.collections["Colliders"].objects:
        part = part_of(obj.parent.name)
        if part.startswith(GEAR_LEGS):
            continue
        shapes.append((obj.name, part, obj_shape(obj)))
    for owner in {o.parent for o in bpy.data.collections["Colliders"].objects}:
        if part_of(owner.name).startswith(GEAR_LEGS):
            bm = gear_box(owner)
            shapes.append((part_of(owner.name) + "_hinge_box", part_of(owner.name), bm_shape(bm)))
            bm.free()
    least, close = (np.inf, None, None), []
    for k, (na, pa, sa) in enumerate(shapes):
        for nb, pb, sb in shapes[k + 1:]:
            if (pa == pb or frozenset((pa, pb)) in touching or np.any(sa[0].min(0) > sb[0].max(0) + 1)
                    or np.any(sb[0].min(0) > sa[0].max(0) + 1)):
                continue
            sep = separation(sa, sb)[0]
            least = min(least, (sep, na, nb))
            if sep < GAP - 1e-4:
                close.append("%s/%s %.4f m" % (na, nb, sep))
    return least, close


# --- the rest --------------------------------------------------------------------------------------------------------

def chunks(owner, n):
    """The mesh cut across its length (Blender y) into n chunks, world-space bmeshes."""
    pieces = [world_bm(owner)]
    ys = [v.co.y for v in pieces[0].verts]
    lo, hi = min(ys), max(ys)
    for i in range(1, n):
        rest = pieces.pop()
        pieces += halves(rest, Vector((0, lo + (hi - lo) * i / n, 0)), Vector((0, 1, 0)))
        rest.free()
    return pieces


def piece_hulls(pieces):
    """Each piece's hull at COLLIDER_TRIS, world space; the pieces are freed."""
    out = [capped(points_of(p), COLLIDER_TRIS) for p in pieces]
    for p in pieces:
        p.free()
    return out


def shells(owner):
    """A structure core's frames as SHELLS pieces round its axis (through its origin, along Blender y), world-space
    hulls: separate() carves each to the band between the skin's hulls and what the core holds. A blast hits a part
    only where its trace toward the part's origin meets that part's own collider (DamageEffects.FragTrace), so the
    core needs hulls all round its axis, not a keel under it."""
    world = [owner.matrix_world @ v.co for v in owner.data.vertices]
    zc = owner.matrix_world.translation.z
    groups = [[] for _ in range(SHELLS)]
    for w in world:
        a = math.atan2(w.x, w.z - zc) + math.pi / SHELLS  # the first piece centred on the top
        groups[int((a % (2 * math.pi)) // (2 * math.pi / SHELLS))].append(w)
    return [capped(g, PATCH_TRIS) for g in groups if len(g) >= 4]


def build(icarus):
    colliders = bi.collection("Colliders")
    lods = bi.collection("LOD1")
    lod_mat = lod_material()
    count = {"colliders": 0, "lods": 0}
    report, owned = [], {}
    for owner in [o for o in icarus.all_objects
                  if o.type == "MESH" and not o.name.startswith(SKIP) and o.get("role") not in SKIP_ROLES]:
        name = owner.name
        lod = None
        if not name.startswith(LOD1_HIDDEN):
            lod = hull_mesh(name + "_lod1", [v.co.copy() for v in owner.data.vertices], lod_tris(name))
        # Unity makes a part of every mesh with mass and of every fuel cell, and takes colliders from those alone
        if owner.get("mass_kg", 0) <= 0 and owner.get("role") != "fuel_tank":
            shapes = []
        elif name.startswith(PATCHED):
            pieces, trough = skin_patches(owner)
            shapes, thick = [], 0.0
            for piece in pieces:
                piece.normal_update()
                hull = patch_hull(points_of(piece), [v.normal.copy() for v in piece.verts])
                if hull:
                    shapes.append(hull)
                    thick = max(thick, thickness(hull, piece))
                piece.free()
            report.append("%s %d patches%s, thickest %.3f m" % (
                name, len(shapes), " (%d more for the trough)" % trough if trough else "", thick))
        elif name.startswith("intake_duct_"):
            shapes = piece_hulls(chunks(owner, DUCT_CHUNKS))
        elif name in STRUCTURE_CORES:
            shapes = shells(owner)
        elif lod is not None:
            shapes = [convex([owner.matrix_world @ v.co for v in lod.vertices])]
        else:
            shapes = [capped([owner.matrix_world @ v.co for v in owner.data.vertices], COLLIDER_TRIS)]
        kept = [bm for bm in shapes if solid(bm)]
        for bm in shapes:
            if bm not in kept:
                bm.free()
        if kept:
            owned[owner] = kept
        if lod is None:  # a hidden part, or a flat one (an antenna blade seen edge-on) with no far stand-in
            continue
        lod.materials.append(lod_mat)
        attr = lod.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        for d in attr.data:
            d.color = LOD_GREY
        attach(name + "_lod1", lod, owner, lods)
        count["lods"] += 1
    # A gear leg's own hulls go unused (Unity swaps in its hinge box), so they stay as built and the box stands in.
    legs = [o for o in owned if part_of(o.name).startswith(GEAR_LEGS)]
    by_part = {part_of(o.name): owned[o] for o in owned if o not in legs}
    if len(by_part) + len(legs) != len(owned):
        raise ValueError("hulls: two collider owners make the same part")
    surface = {part_of(o.name): np.array([(o.matrix_world @ v.co)[:] for v in o.data.vertices])
               for o in owned if o not in legs}
    report.append(separate(by_part, {part_of(o.name): [gear_box(o)] for o in legs}, touching_pairs(owned), surface))
    for owner in owned:
        part = part_of(owner.name)
        shapes = owned[owner] if owner in legs else by_part[part]
        to_local = owner.matrix_world.inverted()
        for made, bm in enumerate(shapes):
            hull = capped(points_of(bm), max(CLEARANCE_TRIS, tris_of(bm) if owner in legs else 0))
            bm.free()
            hull.transform(to_local)
            me = bpy.data.meshes.new("%s_col%d" % (owner.name, made))
            hull.to_mesh(me)
            hull.free()
            attach(me.name, me, owner, colliders)
            count["colliders"] += 1
    print("hulls: " + "; ".join(report))
    for col in (colliders, lods):  # wireframe and out of renders, but still evaluated for the exporter
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"
    return count
