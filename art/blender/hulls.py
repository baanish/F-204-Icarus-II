"""Convex collision pieces and LOD1 hulls for the export contract.

The exporter (tools/export_blockout.py) takes meshes in the "Colliders" collection as convex pieces of their parent
part, and one mesh per part in "LOD1" as its far-distance stand-in. Each sits at an identity transform under its part,
so its vertices are in the part's own space. Unity caps a convex collider at 255 vertices.

A hit lands on the part whose collider it touches, so colliders follow what the part is: curved skin panels get many
thin patches (a single hull of a curved panel would be a solid block hiding everything under it), the structure cores
only a thin keel strip, and compact parts one hull. A fuel cell keeps one hull even though its duct cut-out makes it
concave: splitting cells took the aircraft past 440 colliders for centimetres of overlap, and a round penetrates
through successive colliders anyway, so a shot into the duct area may also reach the neighbouring cell.
"""
import math

import bmesh
import bpy

import build_icarus as bi

MAX_HULL = 255
LOD_GREY = (0.14, 0.14, 0.14, 1.0)  # the colour the Unity author checks LOD1 meshes for
# Animated petals and seals, and the pylon blades and plugs the game shows and hides by station: no collider or LOD,
# since a LOD1 hull would stay drawn at a distance whichever of them is hidden.
SKIP = ("nozzle_petal_", "nozzle_seal_", "pylon_")
# Station length and angle around the body axis of one skin patch. A patch's hull bulges inward by its sagitta
# (r(1 - cos(angle/2))), which must stay inside the 3 cm compartment inset even on the narrow nose.
SKIN_PATCH = (1.0, math.radians(30))
WING_CHUNK = 0.7  # span of one wing or fin skin hull
DUCT_CHUNK = 0.45  # length of one intake duct hull: at least two of the duct's rings, or the hull is a flat disc
STRUCTURE_CORES = ("fuselage_forward", "fuselage_mid", "fuselage_aft")
BODY_AXIS_Z = 0.3  # height of the axis skin patch angles are measured around
NARROW_NOSE_END = 4.0  # ahead of this station the body tapers fast, so skin patches are half as long


def hull_mesh(name, points):
    """Convex hull of points, thinned until it fits Unity's vertex cap."""
    step = max(1, len(points) // 160)
    while True:
        bm = bmesh.new()
        for p in points[::step]:
            bm.verts.new(p)
        res = bmesh.ops.convex_hull(bm, input=list(bm.verts))
        loose = {e for e in res["geom_interior"] + res["geom_unused"] if isinstance(e, bmesh.types.BMVert)}
        bmesh.ops.delete(bm, geom=list(loose), context="VERTS")
        if bm.calc_volume() < 1e-4:  # flat: no use as a collider
            bm.free()
            return None
        if len(bm.verts) <= MAX_HULL - 5 and sum(len(f.verts) - 2 for f in bm.faces) <= MAX_HULL:
            me = bpy.data.meshes.new(name)
            bm.to_mesh(me)
            bm.free()
            return me
        bm.free()
        step += 1


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


def groups(owner):
    """Point groups, in the owner's space, that each become one convex collider."""
    local = [v.co.copy() for v in owner.data.vertices]
    world = [owner.matrix_world @ c for c in local]
    name = owner.name
    if name in STRUCTURE_CORES:  # the keel bar along the belly only, not the frames above it
        floor = min(w.z for w in world)
        return [[c for c, w in zip(local, world) if abs(w.x) <= 0.06 and w.z <= floor + 0.25]]
    if name.startswith(("skin_", "dorsal", "radome")):
        length, sector = SKIN_PATCH
        cells = {}
        for c, w in zip(local, world):
            s = w.y + bi.S0
            # angle from the top of the body, the same on both sides, so left and right panels mirror
            narrow = s < NARROW_NOSE_END
            key = (narrow, math.floor(s / (length / 2 if narrow else length)),
                   math.floor(math.atan2(abs(w.x), w.z - BODY_AXIS_Z) / sector))
            cells.setdefault(key, []).append(c)
        return [pts for pts in cells.values() if len(pts) >= 4]
    if name.startswith("intake_duct_"):  # a curved tube: short hulls, or one fat hull would swallow the fuel cells
        lo, hi = min(w.y for w in world), max(w.y for w in world)
        n = max(1, round((hi - lo) / DUCT_CHUNK))
        out = []
        for i in range(n):
            a, b = lo + (hi - lo) * i / n - 0.02, lo + (hi - lo) * (i + 1) / n + 0.02
            out.append([c for c, w in zip(local, world) if a <= w.y <= b])
        return [g for g in out if len(g) >= 4]
    if name in ("wing_skin_L", "wing_skin_R", "fin_skin"):
        axis = 2 if name == "fin_skin" else 0
        lo, hi = min(w[axis] for w in world), max(w[axis] for w in world)
        n = max(1, round((hi - lo) / WING_CHUNK))
        out = []
        for i in range(n):
            a = lo + (hi - lo) * i / n - 0.05
            b = lo + (hi - lo) * (i + 1) / n + 0.05
            out.append([c for c, w in zip(local, world) if a <= w[axis] <= b])
        return [g for g in out if len(g) >= 4]
    return [local]


def build(icarus):
    colliders = bi.collection("Colliders")
    lods = bi.collection("LOD1")
    lod_mat = lod_material()
    count = {"colliders": 0, "lods": 0}
    for owner in [o for o in icarus.all_objects if o.type == "MESH" and not o.name.startswith(SKIP)]:
        meshes = [m for m in (hull_mesh("%s_col" % owner.name, pts) for pts in groups(owner)) if m is not None]
        for i, me in enumerate(meshes):
            me.name = "%s_col%d" % (owner.name, i)
            attach(me.name, me, owner, colliders)
            count["colliders"] += 1
        lod = hull_mesh(owner.name + "_lod1", [v.co.copy() for v in owner.data.vertices])
        if lod is None:  # a flat part (an antenna blade seen edge-on) has no far stand-in
            continue
        lod.materials.append(lod_mat)
        attr = lod.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        for d in attr.data:
            d.color = LOD_GREY
        attach(owner.name + "_lod1", lod, owner, lods)
        count["lods"] += 1
    for col in (colliders, lods):  # wireframe and out of renders, but still evaluated for the exporter
        col.hide_render = True
        for obj in col.objects:
            obj.display_type = "WIRE"
    return count
