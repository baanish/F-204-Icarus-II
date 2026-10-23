"""Geometry checks run at the end of every build, so a regression fails the build rather than showing up in a review.

Fuel cells must not touch anything but structure: not the skin (a cell showing through it), not an intake duct or
shock cone, not the wing roots buried in the fuselage, not the engine or another cell. No internal part may cut
through the skin.
"""
import bmesh
import bpy
from mathutils.bvhtree import BVHTree


def tree(obj, slot=None):
    """obj's faces as a world-space BVH tree; with slot, only the faces on that material."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if slot is not None:
        names = [m.name if m else "" for m in obj.data.materials]
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if names[f.material_index] != slot], context="FACES")
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


def internals_inside_skin(icarus):
    """Nothing under the skin may cut through it: radar, avionics, cockpit, gear, engine, fuel cells, and the
    fuselage's frames, stringers and break walls (the structure cores' Icarus_Frame faces) through the fuselage's own
    skin. Those do cross the wing roots buried in the body, as a real wing carry-through does, and the wells joined
    into the cores meet the skin at their openings."""
    meshes = [o for o in icarus.all_objects if o.type == "MESH" and not o.name.endswith("_visible")]
    skins = [o for o in meshes if o.get("role") in ("skin", "canopy")]
    inside = [o for o in meshes if o.get("role") in ("radar", "avionics", "cockpit", "gear", "engine", "fuel_tank")]
    cores = [o for o in meshes if o.name in ("fuselage_forward", "fuselage_mid", "fuselage_aft")]
    body = [o for o in skins if not o.name.startswith(("wing_skin_", "fin_skin"))]
    trees = {o.name: tree(o) for o in skins + inside}
    grid = {o.name: tree(o, "Icarus_Frame") for o in cores}
    clashes = ["%s cuts %s" % (o.name, s.name) for o in inside for s in skins if trees[o.name].overlap(trees[s.name])]
    clashes += ["%s cuts %s" % (o.name, s.name) for o in cores for s in body if grid[o.name].overlap(trees[s.name])]
    if clashes:
        raise ValueError("internals through the skin: " + "; ".join(clashes))
    return len(inside)
