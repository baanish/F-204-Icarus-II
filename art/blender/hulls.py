"""Convex collision pieces and LOD1 hulls for the export contract.

The exporter (tools/export_blockout.py) takes meshes in the "Colliders" collection as convex pieces of their parent
part, and one mesh per part in "LOD1" as its far-distance stand-in. Each sits at an identity transform under its part,
so its vertices are in the part's own space. Unity caps a convex collider at 255 vertices.

LOD1 is one hull per part seen from outside, its triangles capped by LOD1_TRIS so the set stays inside Exterior rule
27's 56 per hull and, with the wing skins split in four a side and the fuselage panels in their pieces (parts.SPLITS,
each piece at least LOD1_DEFAULT), 814 in all. The parts under the skin get none: at that distance the skin's hulls hide
them, and the hooked ventral fin none either: the ventral fin's stands in for it. A hull over its cap keeps the points
that reach furthest out (hull_mesh), so it never grows past the part.

Each hull wears its part's paint (paint_lods, after uvs.unwrap): a face takes the material of the part surface under
it and its corners the UVs of that surface's island, so the livery Unity puts on the skin, and the Bare Metal swap,
reach the hull too. Stock LOD1 meshes wear one flat grey (the Revoker's carry no colour at all), which on the Icarus
dropped every livery at range.

A hit lands on the part whose collider it touches, and the game recasts 0.1 m past each hit and lets blasts through
damageable hulls (DamageEffects.ArmorPenetrate, FragTrace), so each part's colliders are solid, as a stock jet's are: one
convex hull of the part and everything folded into it (merge(), after chunks.fold), capped at MERGED_TRIS like the
Revoker's 8 to 56 triangle hulls. clear() cuts it clear of the four keep-outs the Unity author checks (keepouts(): the
seat's escape path, the gear's ground casts, the hook's catch line, the conformal stores), with a second or third piece
only where one cut would keep less than KEEP_SHARE of it; clearance.carve() then stands parts that can collide apart.
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
LOD1_PER_HULL, LOD1_TOTAL = 56, 814
# Parts inside the skin's LOD1 hulls, which get none of their own, and the hooked ventral fin (tail_hook.HOOKED_FIN),
# which the ventral fin's stands in for: a LOD1 hull is always drawn, and the fins take turns.
LOD1_HIDDEN = ("fuselage_", "wing_spar_", "fin_spar", "engine_core", "engine_afterburner", "cockpit_cell", "radar_tray", "avionics_tray",
               "fuel_", "intake_duct_", "ventral_fin_hooked")
COLLIDER_TRIS = 24  # a mesh's own hull before the merge
MERGED_TRIS = 48  # a part's hull, or each piece of it
KEEP_SHARE = 0.6
MIN_WIDTH = 0.002  # thinner, a hull is a plane: bmesh's hull of coplanar points can still show faces and a volume

# LOD1 and collider limits, by collection: triangles in total (budget.py sums them).
BUDGET = {
    "lod1": {"target": 814, "cap": 814, "collection": "LOD1"},
    # 26 parts' hulls and the pieces round the cockpit cell and the tail cone's front (1,370 measured, the cap 2% over)
    "colliders": {"target": 1370, "cap": 1400, "collection": "Colliders"},
}
CLOSEUPS = {}
# One hull for each of the 26 parts, four each for the forward and aft sections (32 measured; the Revoker has 28).
COLLIDER_HULLS = 32


def check(icarus):
    import budget
    from clearance import part_of
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
    bpy.context.view_layer.update()
    obstacles = keepouts()
    for col in cols:
        s = shape([col.matrix_world @ v.co for v in col.data.vertices],
                  [list(f.vertices) for f in col.data.polygons])
        for obstacle in obstacles:
            if part_of(col).name in obstacle["exclude"]:
                continue
            distance, _ = separation(s, obstacle["shape"])
            if distance < obstacle["gap"] - 1e-7:
                problems.append("%s %.4f m from %s, need %.4f (Unity penetration limit %.3f)" %
                                (col.name, distance, obstacle["name"], obstacle["gap"], obstacle["limit"]))
    if problems:
        raise ValueError("hulls check: keep-outs: " + "; ".join(problems))
    col_tris = sum(budget.tris(o) for o in cols)
    if len(cols) > COLLIDER_HULLS or col_tris > BUDGET["colliders"]["cap"]:
        raise ValueError("hulls check: colliders %d hulls, %d triangles, over %d or %d" % (
            len(cols), col_tris, COLLIDER_HULLS, BUDGET["colliders"]["cap"]))
    print("hulls check PASS: LOD1 %d hulls, %d triangles, largest %d, %d skin faces (%d on a point of the atlas); "
          "colliders %d hulls (cap %d), %d triangles (cap %d)"
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


def capped(points, max_tris, paired=False):
    """Convex hull of points in at most max_tris triangles, as a bmesh: the extremes along each axis, then the point
    furthest outside, one at a time, while the hull stays under the cap. It lies inside the points' own hull. paired
    takes each point with its mirror image across Blender x = 0 where the points hold one, so a symmetric set stays
    symmetric."""
    bm = convex(points)
    if tris_of(bm) <= max_tris:
        return bm
    full = np.array([v.co[:] for v in bm.verts])
    bm.free()

    def grow(ids, js):
        for j in js:
            add = [j]
            if paired:
                d = np.linalg.norm(full - full[j] * (-1, 1, 1), axis=1)
                if d.min() < 1e-4:
                    add.append(int(d.argmin()))
            ids = list(dict.fromkeys(ids + add))
        return ids

    chosen = grow([], [int(i) for k in range(3) for i in (full[:, k].argmin(), full[:, k].argmax())])
    best = convex([full[i] for i in chosen])
    while True:
        out = outside(best, full)
        out[chosen] = -np.inf
        j = int(out.argmax())
        if out[j] <= 1e-6:
            return best
        trial_ids = grow(chosen, [j])
        trial = convex([full[i] for i in trial_ids])
        if tris_of(trial) > max_tris:
            trial.free()
            return best
        best.free()
        best, chosen = trial, trial_ids


def solid(bm):
    """A hull fit to be a convex collider: four faces or more, some volume and MIN_WIDTH across every face. bmesh's hull
    of points on one plane (a split half that keeps only its cut face) can still come out with faces and a volume."""
    if len(bm.faces) < 4 or bm.calc_volume() < 1e-4:
        return False
    bm.normal_update()
    pts = np.array([v.co[:] for v in bm.verts])
    return min(np.ptp(pts @ np.array(f.normal[:])) for f in bm.faces) >= MIN_WIDTH


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


def keepouts():
    """World convex shapes, gaps and excluded parts matching Unity's A9, A8, A23 and A14 checks."""
    import cockpit
    import tail_hook

    out = []
    sphere = bmesh.new()
    bmesh.ops.create_icosphere(sphere, subdivisions=2, radius=1.0)
    sphere.normal_update()
    # Scaling by the least face radius circumscribes the sphere, so no capsule surface escapes the polyhedron.
    inset = min(abs(f.normal.dot(f.verts[0].co)) for f in sphere.faces)
    round_points = [v.co.copy() / inset for v in sphere.verts]
    sphere.free()

    def add(name, points, gap, exclude=(), limit=0.0):
        bm = convex(points)
        out.append({"name": name, "shape": bm_shape(bm), "gap": gap, "exclude": exclude, "limit": limit})
        bm.free()

    def capsule(name, a, b, radius, gap, exclude=(), limit=0.0):
        add(name, [end + p * radius for end in (a, b) for p in round_points], gap, exclude, limit)

    # Fighter1's EjectionSeat is offset (0, .021817982, -.04099989) from pilot, rotated -6.83 degrees on X.
    # BuildCockpit moves the seat to cockpit_seat, preserving that world offset from the pilot.
    angle = math.radians(-6.83)
    y, z = 0.021817982, -0.04099989
    offset = Vector((0, -(y * math.sin(angle) + z * math.cos(angle)),
                     y * math.cos(angle) - z * math.sin(angle)))
    frame = bpy.data.objects["cockpit_cell"].matrix_world.to_quaternion()
    pilot = bpy.data.objects[cockpit.SEAT].matrix_world.translation - frame @ offset
    rail = frame @ Vector((0.024, -0.230, 0.973))
    for distance in (1.44, 1.50):
        centre = pilot + rail * distance
        # Unity's height includes the hemispheres: the end centres are a radius inside the .40/.90 ends.
        capsule("seat %.2f" % distance, centre + Vector((0, 0, -0.40 + 0.25)),
                centre + Vector((0, 0, 0.90 - 0.25)), 0.25, 0.001 + 0.004, ("canopy",))

    for leg in ("N", "L", "R"):
        # BuildGear resets castPoint to the bump stop, at the tyre centre + GearStroke, world vertical.
        # Its travel is wheel radius + GearStroke; the donor castPoint's local offset is discarded.
        wheel = bpy.data.objects["gear_wheel_" + leg + "_visible"]
        points = np.array([(wheel.matrix_world @ v.co)[:] for v in wheel.data.vertices])
        centre = (points.min(0) + points.max(0)) / 2
        delta = points - centre
        _, axes = np.linalg.eigh(delta.T @ delta)
        axle = axes[:, 0]
        radius = float(np.sqrt(np.maximum(0, (delta * delta).sum(1) - (delta @ axle) ** 2)).max())
        a = Vector(centre) + Vector((0, 0, 0.3))
        b = a - Vector((0, 0, radius + 0.3))
        # A microscopic box gives the line a full-dimensional SAT shape without changing the 5 mm rule.
        add("gear cast " + leg, [p + Vector((x, y, z)) for p in (a, b)
                                for x in (-1e-6, 1e-6) for y in (-1e-6, 1e-6) for z in (-1e-6, 1e-6)],
            0.005, ("gear_leg_N", "gear_leg_L", "gear_leg_R"))

    hook = bpy.data.objects[tail_hook.NAME]
    rest = hook.matrix_world.copy()
    points = [rest.translation.copy()]
    try:
        swing = hook["stowed_deg"] - hook["deployed_deg"]
        for i in range(tail_hook.SWEEP_STEPS + 1):
            tail_hook.pose_hook(hook, swing * i / tail_hook.SWEEP_STEPS)
            points.append(tail_hook.hook_point(hook))
    finally:
        hook.matrix_world = rest
        bpy.context.view_layer.update()
    # The swept catch line is planar. A microscopic thickness makes its convex shape unambiguous.
    add("hook catch line", [p + Vector((x, 0, 0)) for p in points for x in (-1e-6, 1e-6)],
        tail_hook.CLEAR["line_to_hulls"] + 0.003)

    for side in (1, -1):
        for name, a, b, radius in stations.capsules(side):
            capsule("store %s %s" % (name, side), a, b, radius, 0.0, ("fuselage_mid",), 0.005)
    return out


def clear(bm, keepouts, depth=0):
    """Consume a world hull, keeping the most volume clear of every keep-out, with at most two split levels."""
    from clearance import keep_most

    if not solid(bm):
        bm.free()
        return []
    s = bm_shape(bm)
    bad = [(obstacle, separation(s, obstacle["shape"])) for obstacle in keepouts]
    bad = [(o, result) for o, result in bad if result[0] < o["gap"] - 1e-7]
    if not bad:
        return [bm]
    obstacle, (_, axis) = min(bad, key=lambda item: item[1][0] - item[0]["gap"])
    normal, at = keep_most(s, obstacle["shape"], obstacle["gap"], axis)
    single = cut(bm, Vector(normal), at)
    volume = abs(bm.calc_volume())
    share = abs(single.calc_volume()) / volume if single is not None else 0.0
    if share >= KEEP_SHARE or depth >= 2:
        bm.free()
        return clear(single, keepouts, depth) if single is not None else []
    best = clear(single, keepouts, depth) if single is not None else []
    best_volume = sum(abs(p.calc_volume()) for p in best)
    centre = obstacle["shape"][0].mean(0)
    for i in range(3):
        normal = Vector(tuple(1 if j == i else 0 for j in range(3)))
        halves = [cut(bm, normal, float(centre[i])), cut(bm, -normal, -float(centre[i]))]
        pieces = [piece for half in halves if half is not None for piece in clear(half, keepouts, depth + 1)]
        kept = sum(abs(p.calc_volume()) for p in pieces)
        if kept > best_volume:
            for p in best:
                p.free()
            best, best_volume = pieces, kept
        else:
            for p in pieces:
                p.free()
    bm.free()
    return best


def symmetric(pieces):
    """A centreline part's world hulls, each cut to the mirror image (across Blender x = 0) of its twin: the piece whose
    reflection overlaps it most, itself for one astride the centre plane. The greedy cuts round a pair of obstacles need
    not pick mirrored planes, and a lopsided hull tilts the part's inertia. Cutting only shrinks a piece, so it stays
    clear of whatever it was cleared from; a piece the cut would leave unfit keeps its shape. Each is then capped at
    MERGED_TRIS again, still symmetric: one astride the centre plane keeps its points in mirror pairs (capped's paired),
    and of a mirrored pair the second is the first's reflection (the two cuts are each other's mirror images)."""
    def box(bm, sign=1):
        pts = np.array([(sign * v.co.x, v.co.y, v.co.z) for v in bm.verts])
        return pts.min(0), pts.max(0)

    def overlap(a, b):
        return float(np.prod(np.clip(np.minimum(a[1], b[1]) - np.maximum(a[0], b[0]), 0, None)))

    def reflect(bm):
        return [Vector((-v.co.x, v.co.y, v.co.z)) for v in bm.verts]

    twins = [max(range(len(pieces)), key=lambda j: overlap(box(p), box(pieces[j], -1))) for p in pieces]
    cuts = []
    for p, t in zip(pieces, twins):
        mirror = convex(reflect(pieces[t]))
        pts = np.array([v.co[:] for v in mirror.verts])
        planes = []
        for f in mirror.faces:
            # only planes every vertex lies behind: bmesh's hull keeps sliver faces whose planes cut through it (shape())
            n = Vector(f.normal)
            d = pts @ np.array(n[:]) - n.dot(f.verts[0].co)
            if d.max() <= 1e-6:
                planes.append((n, n.dot(f.verts[0].co)))
            elif d.min() >= -1e-6:
                planes.append((-n, -n.dot(f.verts[0].co)))
        mirror.free()
        cut_piece = p.copy()
        for n, d in planes:
            nxt = cut(cut_piece, n, d + 1e-6)
            cut_piece.free()
            cut_piece = nxt
            if cut_piece is None:
                break
        if cut_piece is not None and solid(cut_piece):
            cuts.append(cut_piece)
        else:
            if cut_piece is not None:
                cut_piece.free()
            cuts.append(None)
    out = []
    for i, (p, t, c) in enumerate(zip(pieces, twins, cuts)):
        if c is None:
            out.append(capped([v.co.copy() for v in p.verts], MERGED_TRIS))
        elif t < i and twins[t] == i and cuts[t] is not None:
            out.append(convex(reflect(out[t])))
        else:
            out.append(capped([v.co.copy() for v in c.verts], MERGED_TRIS, paired=t == i))
    for bm in pieces + [c for c in cuts if c is not None]:
        bm.free()
    return out


def merge(icarus):
    """Replace each part's colliders by its capped hull, cut only for hard keep-outs."""
    from clearance import part_of

    bpy.context.view_layer.update()
    colliders = bpy.data.collections["Colliders"]
    owned = {}
    for c in colliders.objects:
        owned.setdefault(c.parent, []).append(c)
    obstacles = keepouts()
    report = []
    for owner, cols in sorted(owned.items(), key=lambda item: item[0].name):
        bm = capped([c.matrix_world @ v.co for c in cols for v in c.data.vertices], MERGED_TRIS)
        volume = abs(bm.calc_volume())
        name = part_of(cols[0]).name
        pieces = clear(bm, [o for o in obstacles if name not in o["exclude"]])
        kept = []
        for piece in pieces:
            limited = capped([v.co.copy() for v in piece.verts], MERGED_TRIS)
            piece.free()
            if solid(limited):
                kept.append(limited)
            else:
                limited.free()
        share = sum(abs(p.calc_volume()) for p in kept) / volume if volume else 0.0
        for c in cols:
            data = c.data
            bpy.data.objects.remove(c, do_unlink=True)
            if data.users == 0:
                bpy.data.meshes.remove(data)
        count = attach_colliders(owner, kept, colliders)
        report.append("%s %d hulls, %.1f%% volume" % (owner.name, count, share * 100))
        if not count:
            raise ValueError("hulls merge: %s lost every hull to keep-outs" % owner.name)
    for c in colliders.objects:
        c.display_type = "WIRE"
    bpy.context.view_layer.update()
    print("hulls merge: " + "; ".join(report))


def build(icarus):
    colliders = bi.collection("Colliders")
    lods = bi.collection("LOD1")
    count = {"colliders": 0, "lods": 0}
    owned = {}
    for owner in [o for o in icarus.all_objects
                  if o.type == "MESH" and not o.name.startswith(SKIP) and o.get("role") not in SKIP_ROLES]:
        name = owner.name
        lod = None
        if not name.startswith(LOD1_HIDDEN):
            lod = hull_mesh(name + "_lod1", [v.co.copy() for v in owner.data.vertices], lod_tris(name))
        # Unity makes a part of every mesh with mass and of every fuel cell, and takes colliders from those alone
        if owner.get("mass_kg", 0) <= 0 and owner.get("role") != "fuel_tank":
            shapes = []
        else:
            import parts

            points = [owner.matrix_world @ v.co for v in owner.data.vertices]
            if not points:
                points = parts.SHELL_POINTS.get(name, [])
            shapes = [capped(points, COLLIDER_TRIS)] if len(points) >= 4 else []
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
    for owner, shapes in owned.items():
        count["colliders"] += attach_colliders(owner, shapes, colliders)
    for col in (colliders, lods):  # wireframe and out of renders, but still evaluated for the exporter
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"
    return count


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
    """One collider per split piece, with its family's LOD1 triangles shared by skin area."""
    from uvs import SKIN

    colliders, lods = bpy.data.collections["Colliders"], bpy.data.collections["LOD1"]
    for name, pieces in made.items():
        areas = [sum(f.area for f in p.data.polygons if p.data.materials[f.material_index].name == SKIN) for p in pieces]
        for piece, area in zip(pieces, areas):
            tris = max(LOD1_DEFAULT, round(lod_tris(name) * area / sum(areas)))
            lod = hull_mesh(piece.name + "_lod1", [v.co.copy() for v in piece.data.vertices], tris)
            if lod is not None:
                attach(piece.name + "_lod1", lod, piece, lods)
            if piece.get("mass_kg", 0) > 0 or piece.get("role") == "fuel_tank":
                bm = capped([piece.matrix_world @ v.co for v in piece.data.vertices], COLLIDER_TRIS)
                if solid(bm):
                    attach_colliders(piece, [bm], colliders)
                else:
                    bm.free()
    for col in (colliders, lods):
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"


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
