"""Convex collision pieces and LOD1 hulls for the export contract.

The exporter (tools/export_blockout.py) takes meshes in the "Colliders" collection as convex pieces of their parent
part, and one mesh per part in "LOD1" as its far-distance stand-in. Each sits at an identity transform under its part,
so its vertices are in the part's own space. Unity caps a convex collider at 255 vertices.
"""
import bmesh
import bpy

import build_icarus as bi

MAX_HULL = 255
LOD_GREY = (0.14, 0.14, 0.14, 1.0)  # the colour the Unity author checks LOD1 meshes for

# Parts with no collider or LOD: animated petals and seals, the probe, and the ducts inside the fuselage.
SKIP = ("nozzle_petal_", "nozzle_seal_", "probe", "duct_", "shock_cone_")
# Long parts get several hulls: axis index in part space (0 = x, 1 = y) and chunk length in metres.
CHUNKED = {"fuselage": (1, 1.6), "wing_L": (0, 0.7), "wing_R": (0, 0.7)}


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


def build(icarus):
    colliders = bi.collection("Colliders")
    lods = bi.collection("LOD1")
    lod_mat = lod_material()
    count = {"colliders": 0, "lods": 0}
    for owner in [o for o in icarus.objects if o.type == "MESH" and not o.name.startswith(SKIP)]:
        pts = [v.co.copy() for v in owner.data.vertices]
        if owner.name in CHUNKED:
            axis, length = CHUNKED[owner.name]
            lo, hi = min(p[axis] for p in pts), max(p[axis] for p in pts)
            n = max(1, round((hi - lo) / length))
            for i in range(n):
                a = lo + (hi - lo) * i / n - 0.05
                b = lo + (hi - lo) * (i + 1) / n + 0.05
                chunk = [p for p in pts if a <= p[axis] <= b]
                if len(chunk) >= 4:
                    attach("%s_col%d" % (owner.name, i), hull_mesh("%s_col%d" % (owner.name, i), chunk), owner, colliders)
                    count["colliders"] += 1
        else:
            attach(owner.name + "_col0", hull_mesh(owner.name + "_col0", pts), owner, colliders)
            count["colliders"] += 1
        lod = hull_mesh(owner.name + "_lod1", pts)
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
