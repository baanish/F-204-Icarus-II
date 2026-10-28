"""Convex collision pieces and LOD1 hulls for the export contract.

The exporter (tools/export_blockout.py) takes meshes in the "Colliders" collection as convex pieces of their parent
part, and one mesh per part in "LOD1" as its far-distance stand-in. Each sits at an identity transform under its part,
so its vertices are in the part's own space. Unity caps a convex collider at 255 vertices.

LOD1 is one hull per part seen from outside, its triangles capped by LOD1_TRIS so the set stays inside Exterior rule
27's 56 per hull and, with the wing skins split in four a side (parts.SPLITS, each piece at least LOD1_DEFAULT), 780
in all. The parts under the skin get none: at that distance the skin's hulls hide them. A
hull over its cap keeps the points that reach furthest out (hull_mesh), so it never grows past the part.

Each hull wears its part's paint (paint_lods, after uvs.unwrap): a face takes the material of the part surface under
it and its corners the UVs of that surface's island, so the livery Unity puts on the skin, and the Bare Metal swap,
reach the hull too. Stock LOD1 meshes wear one flat grey (the Revoker's carry no colour at all), which on the Icarus
dropped every livery at range.

A hit lands on the part whose collider it touches, so colliders follow what the part is, and only parts get them
(the Unity author makes a part of every mesh with mass and of every fuel cell). Compact parts use their LOD1 hull, or
one capped at COLLIDER_TRIS. Curved skin panels and the wing and fin skins get up to PATCHES thin patches, each split
where its hull sits deepest under the skin: one hull of a curved panel would be a solid block hiding the fuel cells
and gear wells under it, and the LandingGear ground cast would meet it. Near the conformal stores every patch also
keeps to one side of each stations.collider_splits() plane, which can take a panel past PATCHES. The structure cores
carry SHELLS pieces of their frames round the body axis (shells()), and the intake ducts short chunks. A fuel cell
keeps one hull even though its duct cut-out makes it concave: clearing the ducts takes a dozen pieces round each, and a
round penetrates through successive colliders anyway, so a shot into the duct area may also reach the cell wrapped
round it. The Icarus's own parts never collide with one another (src/Icarus/SelfCollision.cs), so hulls may overlap.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

import build_icarus as bi
import stations

MAX_HULL = 255
# A LOD1 face whose corners land on so little of the atlas that the GPU samples one texel for it: counted by check().
POINT_UV_AREA = 1e-8
# Surface.fit: how far a LOD1 face's UVs are drawn toward its centre, in turn, until they lie on its island, to within
# UV_SLACK (half a texel of the 4096 atlas).
UV_SCALES = (1.0, 0.7, 0.5, 0.35, 0.25, 0.17, 0.12, 0.08, 0.05, 0.03)
UV_SLACK = 0.5 / 4096
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
LOD1_PER_HULL, LOD1_TOTAL = 56, 780
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
# A core's frames as SHELLS pieces round its axis, each cut SHELL_GAP clear of the other parts' hulls: past A12's
# 0.005 m, so the Unity author braces no part to a shell. The parts jointed to the core may overlap it (no brace),
# except the cockpit and the gear legs: A9's seat path and A8's ground casts run through them.
SHELLS, SHELL_GAP = 8, 0.01

# LOD1 and collider limits, by collection: triangles in total (budget.py sums them).
BUDGET = {
    "lod1": {"target": 780, "cap": 780, "collection": "LOD1"},
    # The base set (~2,950) plus the stations' clearance cuts (~1,100), the section shells blast must reach (~560), the
    # skin hulls split round the gear doors' holes (~190) and at the trough ramps' deep ends (~420).
    "colliders": {"target": 5300, "cap": 5300, "collection": "Colliders"},
}
CLOSEUPS = {}
# The same three, 102 base hulls, 40 clearance cuts and 17 net for the section shells, and about 20 where the gear
# doors' holes and the trough ramps' deep ends split the skin.
COLLIDER_HULLS = 180


def check(icarus):
    import budget
    from uvs import SKIN

    lods = [o for o in bpy.data.collections["LOD1"].objects]
    cols = [o for o in bpy.data.collections["Colliders"].objects]
    sizes = [budget.tris(o) for o in lods]
    problems = ["%s %d triangles" % (o.name, n) for o, n in zip(lods, sizes) if n > LOD1_PER_HULL]
    if sum(sizes) > LOD1_TOTAL:
        problems.append("LOD1 %d triangles in all" % sum(sizes))
    if problems:
        raise ValueError("hulls check: LOD1 over %d per hull or %d in all: %s" % (LOD1_PER_HULL, LOD1_TOTAL, "; ".join(problems)))
    # paint_lods: each hull wears only its part's materials, the skin wherever the part does, with UVs if it has them
    skin_faces = point_faces = 0
    for o in lods:
        own = [m.name for m in o.parent.data.materials if m]
        worn = [m.name if m else None for m in o.data.materials]
        if not worn or any(m not in own for m in worn):
            problems.append("%s wears %s, not its part's %s" % (o.name, worn, own))
        elif SKIN in own and SKIN not in worn:
            problems.append("%s lacks its part's %s" % (o.name, SKIN))
        if o.parent.data.uv_layers and not o.data.uv_layers:
            problems.append("%s has no UVs" % o.name)
        if SKIN not in worn or not o.data.uv_layers:
            continue
        uv = o.data.uv_layers[0].data
        for f in o.data.polygons:
            if o.data.materials[f.material_index].name != SKIN:
                continue
            a, b, c = (uv[i].uv for i in f.loop_indices[:3])
            skin_faces += 1
            point_faces += abs((b - a).cross(c - a)) / 2 < POINT_UV_AREA
    if problems:
        raise ValueError("hulls check: LOD1 paint: " + "; ".join(problems))
    col_tris = sum(budget.tris(o) for o in cols)
    print("hulls check PASS: LOD1 %d hulls, %d triangles, largest %d, %d skin faces (%d on a point of the atlas); "
          "colliders %d hulls (provisional cap %d), %d triangles (provisional cap %d)"
          % (len(lods), sum(sizes), max(sizes), skin_faces, point_faces, len(cols), COLLIDER_HULLS, col_tris,
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


# --- the structure cores' shells -------------------------------------------------------------------------------------

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


def jointed(core, owner):
    """Whether a joint joins core to owner's part: its parent or a child in the part tree (a hinged surface's part is
    its hinge empty, its _visible mesh's parent)."""
    part = owner.parent if owner.name.endswith("_visible") else owner
    return part.parent == core or core.parent == part


# Each structure core's frame points by shell sector, world space, as build() found them before open_bays cut the
# render meshes: rebuild_pieces carves a core's shells again from these when the parts round it change.
SHELL_GROUPS = {}


def shell_groups(owner):
    """A structure core's world vertices in SHELLS sectors round its axis (through its origin, along Blender y)."""
    world = [owner.matrix_world @ v.co for v in owner.data.vertices]
    zc = owner.matrix_world.translation.z
    groups = [[] for _ in range(SHELLS)]
    for w in world:
        a = math.atan2(w.x, w.z - zc)  # pieces meet on the centre line, so each side's are cut alike
        groups[min(SHELLS - 1, int((a % (2 * math.pi)) // (2 * math.pi / SHELLS)))].append(w)
    return groups


def shells(owner, others, groups=None):
    """A structure core's frames as SHELLS pieces round its axis (shell_groups, or the groups given), each cut flat
    SHELL_GAP clear of every hull in others (separation() shapes), closest first, world space. A blast hits a part only
    where its trace toward the part's origin meets that part's own collider (DamageEffects.FragTrace), so the core
    needs hulls all round its axis, not a keel under it."""
    groups = shell_groups(owner) if groups is None else groups
    out = []
    for g in groups:
        bm = capped(g, PATCH_TRIS) if len(g) >= 4 else None
        for _ in range(500):
            if bm is None:
                break
            s = bm_shape(bm)
            lo, hi = s[0].min(0) - SHELL_GAP, s[0].max(0) + SHELL_GAP
            near = [(separation(s, o), o) for o in others if np.all(o[0].min(0) <= hi) and np.all(lo <= o[0].max(0))]
            (sep, axis), o = min(near, key=lambda r: r[0][0], default=((np.inf, None), None))
            if sep >= SHELL_GAP:
                out.append(capped(points_of(bm), PATCH_TRIS))
                bm.free()
                break
            # the other hull starts at its lowest point along the axis; the shell keeps SHELL_GAP short of it
            nxt = cut(bm, Vector(axis), float((o[0] @ axis).min()) - SHELL_GAP - 1e-4)
            bm.free()
            bm = nxt
        else:
            raise ValueError("hulls: %s's shell would not come clear of its neighbours" % owner.name)
    return out


def build(icarus):
    colliders = bi.collection("Colliders")
    lods = bi.collection("LOD1")
    count = {"colliders": 0, "lods": 0}
    report, owned, cores = [], {}, []
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
            shapes = patches(owner, report)
        elif name.startswith("intake_duct_"):
            shapes = piece_hulls(chunks(owner, DUCT_CHUNKS))
        elif name in STRUCTURE_CORES:  # its shells fill round the other parts' hulls, so they come last
            shapes = []
            cores.append(owner)
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
        attach(name + "_lod1", lod, owner, lods)
        count["lods"] += 1
    for core in cores:
        SHELL_GROUPS[core.name] = shell_groups(core)
        owned[core] = shells(core, others_of(core, owned), SHELL_GROUPS[core.name])
        report.append("%s %d shells" % (core.name, len(owned[core])))
    for owner, shapes in owned.items():
        count["colliders"] += attach_colliders(owner, shapes, colliders)
    print("hulls: " + "; ".join(report))
    for col in (colliders, lods):  # wireframe and out of renders, but still evaluated for the exporter
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"
    return count


def patches(owner, report):
    """A skin panel's thin patch hulls (skin_patches), world space, with a line for the report."""
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
        owner.name, len(shapes), " (%d more for the trough)" % trough if trough else "", thick))
    return shapes


def others_of(core, owned):
    """The separation() shapes a core's shells keep clear of: every other part's hulls but those jointed to the core,
    the cockpit's and the gear's excepted."""
    return [bm_shape(bm) for o, bms in owned.items()
            if o != core and (not jointed(core, o) or o.get("role") in ("cockpit", "gear")) for bm in bms]


def attach_colliders(owner, shapes, colliders):
    """Each world-space hull as a collider mesh of owner, freed; returns how many."""
    to_local = owner.matrix_world.inverted()
    for made, bm in enumerate(shapes):
        bm.transform(to_local)
        me = bpy.data.meshes.new("%s_col%d" % (owner.name, made))
        bm.to_mesh(me)
        bm.free()
        attach(me.name, me, owner, colliders)
    return len(shapes)


def rebuild_pieces(made):
    """Hulls for the skin pieces parts.split_pieces made, {family: [pieces]}: each piece its own skin_patches in full
    and a LOD1 hull with its family's LOD1_TRIS shared by skin area (LOD1_DEFAULT at least). A structure core that a
    piece hangs on in place of the family's own parent, or that loses such a piece, has its shells carved again from
    SHELL_GROUPS, clear of the parts round it now (a core's shells keep clear only of parts not jointed to it)."""
    from parts import full_tree
    from uvs import SKIN

    colliders, lods = bpy.data.collections["Colliders"], bpy.data.collections["LOD1"]
    report, cores = [], set()
    for name, pieces in made.items():
        areas = [sum(f.area for f in p.data.polygons if p.data.materials[f.material_index].name == SKIN) for p in pieces]
        for piece, area in zip(pieces, areas):
            moved = {piece.parent.name, full_tree()[name][0]}
            if len(moved) > 1:
                cores.update(moved & set(STRUCTURE_CORES))
            tris = max(LOD1_DEFAULT, round(lod_tris(name) * area / sum(areas)))
            lod = hull_mesh(piece.name + "_lod1", [v.co.copy() for v in piece.data.vertices], tris)
            if lod is not None:
                attach(piece.name + "_lod1", lod, piece, lods)
            if piece.get("mass_kg", 0) > 0:
                attach_colliders(piece, patches(piece, report), colliders)
    for name in sorted(cores):
        core = bpy.data.objects[name]
        for c in [c for c in core.children if c.name in colliders.objects]:
            data = c.data
            bpy.data.objects.remove(c, do_unlink=True)
            bpy.data.meshes.remove(data)
        owned = {}
        for c in colliders.objects:
            if c.parent != core:
                bm = bmesh.new()
                bm.from_mesh(c.data)
                bm.transform(c.parent.matrix_world)
                owned.setdefault(c.parent, []).append(bm)
        carved = shells(core, others_of(core, owned), SHELL_GROUPS[name])
        for bms in owned.values():
            for bm in bms:
                bm.free()
        attach_colliders(core, carved, colliders)
        report.append("%s %d shells" % (name, len(carved)))
    for col in (colliders, lods):
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"
    print("hulls: pieces: " + "; ".join(report))


# --- LOD1 paint ---------------------------------------------------------------------------------------------------

class Surface:
    """A part's render mesh as triangles in its own space, for the hull faces to find their paint on: a BVH over all
    of them, and per triangle its material slot, corner UVs and island. An island joins triangles of one slot across
    edges whose UVs match, so its UVs are one connected stretch of the atlas."""

    def __init__(self, owner):
        bm = bmesh.new()
        bm.from_mesh(owner.data)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.faces.ensure_lookup_table()
        layer = bm.loops.layers.uv.active
        self.corners = [[l.vert.co.copy() for l in f.loops] for f in bm.faces]
        self.uvs = [[l[layer].uv.to_3d() for l in f.loops] for f in bm.faces] if layer else None
        self.slots = [f.material_index for f in bm.faces]
        self.normals = [f.normal.copy() for f in bm.faces]
        parent = list(range(len(bm.faces)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for e in bm.edges:
            if len(e.link_faces) != 2:
                continue
            a, b = e.link_faces
            if a.material_index != b.material_index:
                continue
            if layer and any((next(l for l in a.loops if l.vert == v)[layer].uv
                              - next(l for l in b.loops if l.vert == v)[layer].uv).length > 1e-5 for v in e.verts):
                continue
            parent[find(a.index)] = find(b.index)
        self.island = [find(i) for i in range(len(parent))]
        bm.free()
        self.tree = self.bvh(range(len(self.corners)))
        self.islands = {}

    def bvh(self, tris, corners=None):
        tris = list(tris)
        verts = [co for t in tris for co in (corners or self.corners)[t]]
        return BVHTree.FromPolygons(verts, [(3 * k, 3 * k + 1, 3 * k + 2) for k in range(len(tris))]), tris

    def island_trees(self, island):
        """The island's triangles as a BVH in the part's space and one in the atlas's (UV, 0)."""
        if island not in self.islands:
            tris = [t for t, k in enumerate(self.island) if k == island]
            self.islands[island] = (self.bvh(tris), self.bvh(tris, self.uvs)[0])
        return self.islands[island]

    def under(self, c, n):
        """The triangle a hull face (centre c, outward normal n) covers: the nearest that faces the same way, else the
        first the face's normal meets going in, else the nearest."""
        tree, _ = self.tree
        loc, _, nearest, _ = tree.find_nearest(c)
        if nearest is not None and self.normals[nearest].dot(n) > 0:
            return nearest
        _, _, hit, _ = tree.ray_cast(c + n * 1e-3, -n)
        return hit if hit is not None else nearest

    def uv_near(self, island, p):
        """UV of the island's surface point nearest p."""
        (tree, tris), _ = self.island_trees(island)
        loc, _, k, _ = tree.find_nearest(p)
        t = tris[k]
        a, b, c = self.corners[t]
        return barycentric_transform(loc, a, b, c, *self.uvs[t]).to_2d()

    def fit(self, island, centre, corners):
        """The corner UVs drawn toward centre (a UV on the island) until the triangle they span lies on the island, so
        the face samples no gutter or neighbouring island: a straight UV triangle between three points of a curved or
        notched island can leave it. Tested at the corners, edge thirds and inside to within half an atlas texel; None
        where no scale fits."""
        _, flat = self.island_trees(island)
        for scale in UV_SCALES:
            uvs = [centre.lerp(uv, scale) for uv in corners]
            if all(flat.find_nearest((uvs[0] * i + uvs[1] * j + uvs[2] * (3 - i - j)).to_3d() / 3)[3] <= UV_SLACK
                   for i in range(4) for j in range(4 - i)):
                return uvs
        return None


def paint_lods():
    """Give every LOD1 hull its part's paint. A face takes the material slot of the part triangle it covers (Surface.under)
    and each corner, drawn a tenth of the way to the face centre, the UV of the nearest point on that triangle's
    island, drawn in further where the triangle would leave the island (Surface.fit): the face maps onto one stretch
    of the atlas, never across the gutters between islands. Runs after uvs.unwrap, on the final render meshes."""
    from uvs import SKIN

    report = []
    for lod in bpy.data.collections["LOD1"].objects:
        owner = lod.parent
        surface = Surface(owner)
        bm = bmesh.new()
        bm.from_mesh(lod.data)
        bm.normal_update()
        layer = bm.loops.layers.uv.new("UVMap") if surface.uvs else None
        centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
        covered = []
        for f in bm.faces:
            c = f.calc_center_median()
            covered.append((f, c, surface.under(c, f.normal if f.normal.dot(c - centre) >= 0 else -f.normal)))
        slots = list(dict.fromkeys(surface.slots[t] for _, _, t in covered))
        # the slots go on first: to_mesh clamps each face's material index to the mesh's slots
        for slot in slots:
            lod.data.materials.append(owner.data.materials[slot])
        for f, c, t in covered:
            f.material_index = slots.index(surface.slots[t])
            if layer:
                island = surface.island[t]
                middle = surface.uv_near(island, c)
                corners = [surface.uv_near(island, l.vert.co.lerp(c, 0.1)) for l in f.loops]
                # a middle on the island's rim leaves no room to fit: then the covered triangle's own middle
                uvs = (surface.fit(island, middle, corners)
                       or surface.fit(island, (sum(surface.uvs[t], Vector()) / 3).to_2d(), corners))
                # Nearest-point projection can collapse onto an island rim. Sample the covered skin triangle instead.
                if owner.data.materials[surface.slots[t]].name == SKIN and (
                        not uvs or abs((uvs[1] - uvs[0]).cross(uvs[2] - uvs[0])) / 2 <= POINT_UV_AREA):
                    uvs = [uv.to_2d() for uv in surface.uvs[t]]
                for l, uv in zip(f.loops, uvs or [middle] * 3):
                    l[layer].uv = uv
        bm.to_mesh(lod.data)
        bm.free()
        report.append("%s %s" % (lod.name, "/".join(owner.data.materials[s].name for s in slots)))
    print("hulls: LOD1 paint: " + "; ".join(report))
