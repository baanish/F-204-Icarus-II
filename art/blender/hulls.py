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
carry only a thin keel strip and the intake ducts short chunks. A fuel cell keeps one hull even though its duct
cut-out makes it concave: clearing the ducts takes a dozen pieces round each, and a round penetrates through
successive colliders anyway, so a shot into the duct area may also reach the cell wrapped round it.
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


def keel(owner):
    """A structure core's keel bar along the belly, not the frames above it, world space."""
    world = [owner.matrix_world @ v.co for v in owner.data.vertices]
    floor = min(w.z for w in world)
    return [w for w in world if abs(w.x) <= 0.06 and w.z <= floor + 0.25]


def build(icarus):
    colliders = bi.collection("Colliders")
    lods = bi.collection("LOD1")
    lod_mat = lod_material()
    count = {"colliders": 0, "lods": 0}
    report = []
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
            shapes = [capped(keel(owner), COLLIDER_TRIS)]
        elif lod is not None:
            shapes = [convex([owner.matrix_world @ v.co for v in lod.vertices])]
        else:
            shapes = [capped([owner.matrix_world @ v.co for v in owner.data.vertices], COLLIDER_TRIS)]
        to_local = owner.matrix_world.inverted()
        made = 0
        for bm in shapes:
            if solid(bm):
                bm.transform(to_local)
                me = bpy.data.meshes.new("%s_col%d" % (name, made))
                bm.to_mesh(me)
                attach(me.name, me, owner, colliders)
                made += 1
            bm.free()
        count["colliders"] += made
        if lod is None:  # a hidden part, or a flat one (an antenna blade seen edge-on) with no far stand-in
            continue
        lod.materials.append(lod_mat)
        attr = lod.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        for d in attr.data:
            d.color = LOD_GREY
        attach(name + "_lod1", lod, owner, lods)
        count["lods"] += 1
    print("hulls: " + "; ".join(report))
    for col in (colliders, lods):  # wireframe and out of renders, but still evaluated for the exporter
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"
    return count
