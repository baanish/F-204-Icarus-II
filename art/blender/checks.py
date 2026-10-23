"""Geometry checks run at the end of every build, so a regression fails the build rather than showing up in a review.

Fuel cells must not touch anything but structure: not the skin (a cell showing through it), not an intake duct or
shock cone, not the wing roots buried in the fuselage, not the engine or another cell. No internal part may cut
through the skin.
"""
import bmesh
import bpy
import math
from mathutils import Vector
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


def surface_samples(obj, spacing=.025):
    mesh = obj.data
    mesh.calc_loop_triangles()
    hardware = mesh.attributes.get("exterior_hardware")
    points = set()
    for tri in mesh.loop_triangles:
        if hardware and hardware.data[tri.polygon_index].value:
            continue
        a, b, c = [obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices]
        n = max(1, math.ceil(max((b - a).length, (c - a).length, (c - b).length) / spacing))
        for i in range(n + 1):
            for j in range(n + 1 - i):
                q = a + (b - a) * (i / n) + (c - a) * (j / n)
                points.add(tuple(round(v, 6) for v in q))
        points.add(tuple((a + b + c) / 3))
    return sorted(points)


def compartment_clearance(objects, skin, inset):
    shell = tree(skin)
    for obj in objects:
        sample = min(surface_samples(obj), key=lambda q: shell.find_nearest(Vector(q))[3])
        at, _, _, distance = shell.find_nearest(Vector(sample))
        if distance < inset - 1e-5:
            raise ValueError("compartment clearance: %s %.6f m < %.6f m at %s nearest %s" %
                             (obj.name, distance, inset, sample, tuple(at)))
        print("compartment clearance: %s %.6f m >= %.6f m: PASS" % (obj.name, distance, inset), flush=True)


def interior_visibility(icarus, allow_openings=True):
    """Sample enclosed damage parts at 25 mm spacing from 14 outside directions.

    The intake mouths, gear door patches, speed brake wells and exhaust are deliberate openings. Close those
    exact patches for this fit check; allow_openings=False also reports views through them for an art review.
    Well hinge fittings are exterior hardware even after joining a structure core. Cockpit-view meshes cannot
    hide a failed fit.
    """
    meshes = [o for o in icarus.all_objects if o.type == "MESH"]
    inside = [o for o in meshes if o.name in ("radar_tray", "avionics_tray", "cockpit_cell", "fin_spar")
              or o.name.startswith(("fuel_", "fuselage_", "wing_spar_"))]
    outside = [o for o in meshes if o not in inside and o.get("role") != "cockpit_view"]
    verts, faces = [], []
    for obj in outside:
        offset = len(verts)
        verts.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        faces.extend(tuple(offset + i for i in f.vertices) for f in obj.data.polygons)
    exterior_vertices, exterior_faces = len(verts), len(faces)
    if allow_openings:
        import build_icarus as bi
        import gear
        import speed_brakes

        p = bi.PARAMS
        stations = bi.fuselage_stations(p)
        rings = [bi.blended_ring(p, s) for s in stations]
        reference = bi.loft("visibility_openings", rings, tip_front=bi.P(0, 0, p["fuselage"][0][2]))
        try:
            _, vid = gear.skin_grid(reference)
            patches, edges = [], {}
            for spec in gear.GEAR["doors"]:
                j0, j1, k0, k1 = gear.door_patch(reference, spec)
                k0 = edges.get(spec[1:4], k0)
                edges[spec[1:3] + (spec[4],)] = k1
                js, ks = gear.kept(j0, j1, spec[6]), gear.kept(k0, k1, spec[7])
                hinge = k1 if spec[5] == "outer" else k0
                for side in (1, -1):
                    vk = lambda k: k if side > 0 else bi.RING // 2 - k
                    co = lambda j, k: reference.data.vertices[vid(j, vk(k))].co.copy()
                    gear.snap_edges(reference, j0, j1, k0, k1, js, ks, lambda j, k: vid(j, vk(k)))
                    gear.straighten(reference, [vid(j, vk(hinge)) for j in range(j0, j1 + 1)])
                    gear.square_ends(reference, co(j0, hinge), co(j1, hinge),
                                     [[vid(j, vk(k)) for k in range(k0, k1 + 1)] for j in (j0, j1)])
                    patches.append({vid(j, vk(k))
                                    for j in range(j0, j1 + 1) for k in range(k0, k1 + 1)})
            lip = stations.index(p["intake"][0][0])
            patches.append({vid(j, k) for j in (lip - 1, lip) for k in range(bi.RING)})
            offset = len(verts)
            verts.extend(v.co.copy() for v in reference.data.vertices)
            faces.extend(tuple(offset + i for i in f.vertices) for f in reference.data.polygons
                         if any(set(f.vertices) <= patch for patch in patches))
            faces.append(tuple(offset + vid(len(rings) - 1, k) for k in range(bi.RING)))
            grid = speed_brakes.Patch(p)
            for side in (1, -1):
                start = len(verts)
                cols = len(grid.grid[0])
                verts.extend(Vector((side * v.x, v.y, v.z)) for row in grid.grid for v in row)
                faces.extend((start + j * cols + k, start + j * cols + k + 1,
                              start + (j + 1) * cols + k + 1, start + (j + 1) * cols + k)
                             for j in range(len(grid.grid) - 1) for k in range(cols - 1))
        finally:
            mesh = reference.data
            bpy.data.objects.remove(reference, do_unlink=True)
            bpy.data.meshes.remove(mesh)
    shell = BVHTree.FromPolygons(verts[:exterior_vertices], faces[:exterior_faces])
    openings = BVHTree.FromPolygons(verts, faces[exterior_faces:], epsilon=1e-5) if allow_openings else None
    directions = [Vector(v).normalized() for v in
                  ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
                  + tuple((x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1))]
    failures, total = [], 0
    for obj in inside:
        points = surface_samples(obj)
        exposed = []
        for point in points:
            q = Vector(point)
            if openings and openings.find_nearest(q)[3] <= 1e-5:
                continue  # Well rims lie on the intentional opening, with micrometre rounding after joining.
            for direction in directions:
                # Aim at the sample from well outside the entire aircraft. A shell hit at the sample itself
                # gives no clearance and must fail too; checking intersections alone misses open skin gaps.
                hit, _, _, distance = shell.ray_cast(q + direction * 30, -direction, 30.0001)
                if hit is None or distance >= 29.9999:
                    # A well rim may lie on an opening's edge; unlike an enclosed compartment it needs no gap
                    # to this virtual patch. The real shell still requires an earlier, occluding hit.
                    if openings:
                        tangent = direction.cross(Vector((0, 0, 1)))
                        tangent = tangent.normalized() if tangent.length > .1 else Vector((1, 0, 0))
                        across = direction.cross(tangent)
                        offsets = (Vector(), tangent * 1e-5, tangent * -1e-5, across * 1e-5, across * -1e-5)
                        if any(openings.ray_cast(q + direction * 30 + offset, -direction, 30.0001)[0] is not None
                               for offset in offsets):
                            continue
                    exposed.append((point, tuple(direction)))
                    break
        total += len(points)
        if exposed:
            bounds = [(min(p[0][i] for p in exposed), max(p[0][i] for p in exposed)) for i in range(3)]
            failures.append("%s: %d/%d exposed samples; first %s toward %s; bounds %s" %
                            (obj.name, len(exposed), len(points), exposed[0][0], exposed[0][1], bounds))
    message = "interior visibility: %d enclosed parts, %d samples, 14 directions" % (len(inside), total)
    if failures:
        raise ValueError(message + "; " + "; ".join(failures))
    print(message + ": PASS", flush=True)
    return len(inside)
