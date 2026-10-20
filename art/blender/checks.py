"""Geometry checks run at the end of every build, so a regression fails the build rather than showing up in a review.

Fuel cells must not touch anything but structure: not the skin (a cell showing through it), not an intake duct or
shock cone, not the wing roots buried in the fuselage, not the engine or another cell.
"""
import bmesh
import bpy
from mathutils.bvhtree import BVHTree


def tree(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    t = BVHTree.FromBMesh(bm)
    bm.free()
    return t


def fuel_cell_clearance(icarus):
    meshes = [o for o in icarus.all_objects if o.type == "MESH"]
    cells = [o for o in meshes if o.get("role") == "fuel_tank"]
    others = [o for o in meshes if o.get("role") != "structure" and o not in cells]
    trees = {o.name: tree(o) for o in cells + others}
    clashes = []
    for i, c in enumerate(cells):
        for o in others + cells[i + 1:]:
            if trees[c.name].overlap(trees[o.name]):
                clashes.append("%s touches %s" % (c.name, o.name))
    if clashes:
        raise ValueError("fuel cell clearance: " + "; ".join(clashes))
    return len(cells)
