"""Convex collision pieces and LOD1 hulls for the export contract.

The exporter (tools/export_blockout.py) takes meshes in the "Colliders" collection as convex pieces of their parent
part, and one mesh per part in "LOD1" as its far-distance stand-in. Each sits at an identity transform under its part,
so its vertices are in the part's own space. Unity caps a convex collider at 255 vertices.

A hit lands on the part whose collider it touches, so colliders follow what the part is: curved skin panels get many
thin patches (a single hull of a curved panel would be a solid block hiding everything under it), the structure cores
only a thin keel strip, and compact parts one hull.
"""
import math

import bmesh
import bpy

import build_icarus as bi

MAX_HULL = 255
LOD_GREY = (0.14, 0.14, 0.14, 1.0)  # the colour the Unity author checks LOD1 meshes for
SKIP = ("nozzle_petal_", "nozzle_seal_")  # animated petals and seals: no collider or LOD
SKIN_PATCH = (1.2, math.radians(60))  # station length and angle around the body axis of one skin patch
WING_CHUNK = 0.7  # span of one wing or fin skin hull
STRUCTURE_CORES = ("fuselage_forward", "fuselage_mid", "fuselage_aft")
BODY_AXIS_Z = 0.3  # height of the axis skin patch angles are measured around


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
    if name in STRUCTURE_CORES:
        return [[c for c, w in zip(local, world) if abs(w.x) <= 0.06]]
    if name.startswith(("skin_", "dorsal")):
        length, sector = SKIN_PATCH
        cells = {}
        for c, w in zip(local, world):
            key = (math.floor((w.y + bi.S0) / length), math.floor(math.atan2(w.z - BODY_AXIS_Z, w.x) / sector))
            cells.setdefault(key, []).append(c)
        return [pts for pts in cells.values() if len(pts) >= 4]
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
        for i, pts in enumerate(groups(owner)):
            attach("%s_col%d" % (owner.name, i), hull_mesh("%s_col%d" % (owner.name, i), pts), owner, colliders)
            count["colliders"] += 1
        lod = hull_mesh(owner.name + "_lod1", [v.co.copy() for v in owner.data.vertices])
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
