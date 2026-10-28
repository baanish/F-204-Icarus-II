"""Geometry checks run at the end of every build, so a regression fails the build rather than showing up in a review.

Fuel cells must not touch anything but structure: not the skin (a cell showing through it), not an intake duct or
shock cone, not the wing roots buried in the fuselage, not the engine or another cell. No internal part may cut
through the skin. The canopy's glass and frames meet the skin on one edge, and from the design eye nothing but the
glass shows the sky.
"""
import bmesh
import bpy
import math
from mathutils import Vector
from mathutils.bvhtree import BVHTree

Z = Vector((0, 0, 1))


def tree(obj, slot=None):
    """obj's faces (or a list of objects', as a skin family's pieces) as a world-space BVH tree; with slot, only the
    faces on that material. Makes no datablocks, so a caller may build trees while it walks a collection's objects."""
    bm = bmesh.new()
    for o in obj if isinstance(obj, (list, tuple)) else [obj]:
        verts, faces = len(bm.verts), len(bm.faces)
        bm.from_mesh(o.data)  # appends
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        if slot is not None:
            names = [m.name if m else "" for m in o.data.materials]
            bmesh.ops.delete(bm, geom=[f for f in bm.faces[faces:] if names[f.material_index] != slot], context="FACES")
            bm.verts.ensure_lookup_table()
        bmesh.ops.transform(bm, matrix=o.matrix_world, verts=bm.verts[verts:])
    t = BVHTree.FromBMesh(bm)
    bm.free()
    return t


def intake_wing_junction(icarus):
    """The intake/wing landing has no opening or fore-aft crease. Limit turns across its station rings to
    10 degrees; the rounded cross-section's much larger turns along longitudinal edges are intentional.
    Both sides must contain checked edges, so a missing skin cannot pass an empty measurement.
    The band is in world metres, stations 8.5 to 10, above the deliberate trough and gear openings.
    """
    counts, worst, problems = {1: 0, -1: 0}, 0.0, []
    for obj in icarus.all_objects:
        if obj.name not in ("fuselage", "skin_mid_L", "skin_mid_R"):
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        bm.normal_update()
        for edge in bm.edges:
            a, b = [v.co for v in edge.verts]
            q = (a + b) / 2
            if not (.85 < abs(q.x) < 1.1 and .5 < q.y < 2.0 and .18 < q.z < .5):
                continue
            if abs(a.y - b.y) > 1e-5:
                continue
            counts[1 if q.x > 0 else -1] += 1
            angle = math.degrees(edge.calc_face_angle(0.0))
            worst = max(worst, angle)
            if len(edge.link_faces) != 2 or angle > 10.0:
                problems.append("%s at %s: %d faces, %.3f deg" %
                                (obj.name, tuple(round(v, 4) for v in q), len(edge.link_faces), angle))
        bm.free()
    if problems or not all(counts.values()):
        raise ValueError("intake/wing skin: " + "; ".join(problems[:8]) + " edges per side %s" % counts)
    print("intake/wing skin: %d ring edges, maximum turn %.3f deg <= 10.000 deg: PASS" %
          (sum(counts.values()), worst), flush=True)
    return {"ring_edges": sum(counts.values()), "maximum_turn_deg": worst}


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
    from hulls import STRUCTURE_CORES

    cores = [o for o in meshes if o.name in STRUCTURE_CORES]
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


def intake_and_tailpipe():
    """What a view into an intake or the tailpipe crosses: the fuselage's band of faces at the intake lip, the
    mouths and the skin round them, and the disc closing its open tail end."""
    import build_icarus as bi

    p = bi.PARAMS
    stations = bi.fuselage_stations(p)
    lip = stations.index(p["intake"][0][0])
    ahead, mouth, tail = (bi.blended_ring(p, stations[j]) for j in (lip - 1, lip, -1))
    n = len(ahead)
    faces = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
    faces.append(tuple(range(2 * n, 2 * n + len(tail))))
    return BVHTree.FromPolygons(ahead + mouth + tail, faces)


def interior_visibility(icarus, allow_openings=True):
    """Sample enclosed damage parts at 25 mm spacing from 14 outside directions, twice: gear doors shut, then open
    with the gear down, as the game leaves them on the ground.

    The speed brake wells are deliberate openings, and so are the gear door patches while the doors are shut. Close
    those exact patches for this fit check; allow_openings=False also reports views through them for an art review.
    The intake mouths, the tailpipe and the open gear doors' holes stay open: the ducts, backplates and gear wells
    must hide the structure as the game draws them. A view entering one passes back faces, which the game culls,
    and trim faces reaching the stock texture's alpha-clipped lightening holes (trims.clipped). Well faces and hinge
    fittings are exterior hardware even after joining a structure core: never sampled, they hide what lies behind
    them as any drawn face does. Cockpit-view meshes cannot hide a failed fit.
    """
    import gear

    _interior_visibility(icarus, allow_openings, doors_open=False)
    with gear.posed(gear.all_doors(1.0)):
        _interior_visibility(icarus, allow_openings, doors_open=True)


def _interior_visibility(icarus, allow_openings, doors_open):
    import trims

    meshes = [o for o in icarus.all_objects if o.type == "MESH"]
    inside = [o for o in meshes if o.name in ("radar_tray", "avionics_tray", "cockpit_cell", "fin_spar")
              or o.name.startswith(("fuel_", "fuselage_", "wing_spar_"))]
    outside = [o for o in meshes if o not in inside and o.get("role") != "cockpit_view"]
    verts, faces, clipped = [], [], []
    for obj in outside + inside:
        hardware = obj.data.attributes.get("exterior_hardware")
        if obj in inside and not hardware:
            continue
        drawn = [f for f in obj.data.polygons if obj in outside or hardware.data[f.index].value]
        offset = len(verts)
        verts.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        faces.extend(tuple(offset + i for i in f.vertices) for f in drawn)
        clipped.extend(bool(obj.data.materials) and trims.clipped(obj, f) for f in drawn)
    exterior_vertices, exterior_faces = len(verts), len(faces)
    door_holes = []
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
                j0, j1, k0, k1, _, _ = gear.hole(reference, spec, edges, vid)
                cells = gear.patch_cells(reference, spec, j0, j1, k0, k1, vid)
                for side in (1, -1):
                    vk = lambda k: k if side > 0 else bi.RING // 2 - k
                    patches.append({vid(j, vk(k)) for j, k in cells})
            holes = [tuple(f.vertices) for f in reference.data.polygons if any(set(f.vertices) <= q for q in patches)]
            if doors_open:  # the holes are portals then, cast as the game draws what lies beyond them
                door_holes = ([v.co.copy() for v in reference.data.vertices], holes)
            else:
                offset = len(verts)
                verts.extend(v.co.copy() for v in reference.data.vertices)
                faces.extend(tuple(offset + i for i in f) for f in holes)
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
    rays = [(direction, direction * 30, -direction) for direction in directions]
    portals = intake_and_tailpipe()
    doors = BVHTree.FromPolygons(*door_holes) if door_holes else None

    def drawn_cast(origin, direction, reach):
        """The first face the game draws across the ray: turned toward it and not cut out."""
        travelled = 0.0
        while True:
            hit, normal, index, distance = shell.ray_cast(origin, direction, reach - travelled)
            if hit is None or any(n.dot(direction) < 0 and not clipped[i]  # with any face coincident there
                                  for _, n, i, _ in [(hit, normal, index, 0)] + shell.find_nearest_range(hit, 1e-5)):
                return hit, normal, index, None if hit is None else travelled + distance
            travelled += distance + 1e-5
            origin = hit + direction * 1e-5

    failures, total = [], 0
    for obj in inside:
        points = surface_samples(obj)
        exposed = []
        for point in points:
            q = Vector(point)
            if openings and openings.find_nearest(q)[3] <= 1e-5:
                continue  # Well rims lie on the intentional opening, with micrometre rounding after joining.
            for direction, origin, inward in rays:
                # Aim at the sample from well outside the entire aircraft. A shell hit at the sample itself
                # gives no clearance and must fail too; checking intersections alone misses open skin gaps.
                into = portals.ray_cast(q + origin, inward, 29.9999)[0] is not None
                into = into or (doors is not None and doors.ray_cast(q + origin, inward, 29.9999)[0] is not None)
                hit, _, _, distance = (drawn_cast if into else shell.ray_cast)(q + origin, inward, 30.0001)
                if into and hit is not None and distance >= 29.9999 and (hit - q).length < 2e-4:
                    continue  # a drawn well face lying on the sample: a frame cut flush with the well's wall
                if hit is None or distance >= 29.9999:
                    tangent = direction.cross(Vector((0, 0, 1)))
                    tangent = tangent.normalized() if tangent.length > .1 else Vector((1, 0, 0))
                    across = direction.cross(tangent)
                    offsets = (Vector(), tangent * 1e-5, tangent * -1e-5, across * 1e-5, across * -1e-5)
                    # A ray down a shell seam, through a vertex seen end on, can slip between the faces that share
                    # it: the sample is covered if a ray a hair to one side meets the shell before it.
                    beside = [(drawn_cast if into else shell.ray_cast)(q + origin + offset, inward, 30.0001)
                              for offset in offsets[1:]]
                    if any(h[0] is not None and h[3] < 29.9999 for h in beside):
                        continue
                    # A well rim may lie on an opening's edge; unlike an enclosed compartment it needs no gap
                    # to this virtual patch. The real shell still requires an earlier, occluding hit.
                    if openings:
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
    message = "interior visibility, gear doors %s: %d enclosed parts, %d samples, 14 directions" % (
        "open" if doors_open else "shut", len(inside), total)
    if failures:
        raise ValueError(message + "; " + "; ".join(failures))
    print(message + ": PASS", flush=True)
    return len(inside)


def structure_clear_of_bays(icarus, spacing=0.01, tolerance=0.001):
    """No frame, stringer or break wall (the structure cores' Icarus_Frame faces) inside a bay or well, where an open
    door or panel would show it: the gear bays (parts.open_bays' boxes), the speed brake wells (speed_brakes.Patch's
    voids) and the conformal trough (stations.carve_shapes). The faces are sampled every spacing; a sample counts once
    it is more than tolerance inside, so members cut back to a bay's wall pass."""
    import build_icarus as bi
    import internals as interior
    import speed_brakes
    import stations

    p = bi.PARAMS
    volumes = []  # (name, lower corner, upper corner, inside(q))
    bays = [("nose gear bay", b) for b in interior.bay_boxes("nose_gear_bay")] + [
        ("main gear bay " + "LR"[side < 0], b) for side in (1, -1) for b in interior.bay_boxes("main_gear_bay", side)]
    for name, (s0, s1, x0, x1, z0, z1) in bays:
        lo, hi = bi.P(s0, x0, z0 - 0.3), bi.P(s1, x1, z1)
        volumes.append((name, lo, hi, lambda q, lo=lo, hi=hi: all(lo[i] + tolerance < q[i] < hi[i] - tolerance
                                                                    for i in range(3))))
    patch = speed_brakes.Patch(p)
    for side in (1, -1):
        for name, (verts, faces) in zip(("well", "channel"), patch.voids(side)):
            shell = BVHTree.FromPolygons(verts, faces)
            lo = Vector([min(v[i] for v in verts) for i in range(3)])
            hi = Vector([max(v[i] for v in verts) for i in range(3)])
            volumes.append(("speed brake %s %s" % (name, "LR"[side < 0]), lo, hi,
                            lambda q, shell=shell: inside_closed(shell, q) and shell.find_nearest(q)[3] > tolerance))
    fields = {}

    def in_trough(q):
        s = round(q.y + bi.S0, 3)
        if s not in fields:
            fields[s] = stations.carve_shapes(p, s)
        return any(f(q.x, q.z) < -tolerance for f in fields[s])

    ramps = stations.ramp_stations(p)
    s0, s1 = min(lo for lo, _, _ in ramps), max(hi for _, hi, _ in ramps)
    c = stations.CONFORMAL
    volumes.append(("conformal trough", bi.P(s0, -c["x"] - 0.3, -1.0), bi.P(s1, c["x"] + 0.3, c["z"] + 0.3), in_trough))
    found, sampled = {}, {}
    from hulls import STRUCTURE_CORES

    for core in (o for o in icarus.all_objects if o.name in STRUCTURE_CORES):
        slots = [m.name if m else "" for m in core.data.materials]
        mesh = core.data
        mesh.calc_loop_triangles()
        for tri in mesh.loop_triangles:
            if slots[mesh.polygons[tri.polygon_index].material_index] != "Icarus_Frame":
                continue
            a, b, c3 = (core.matrix_world @ mesh.vertices[i].co for i in tri.vertices)
            near = [v for v in volumes if all(min(a[i], b[i], c3[i]) < v[2][i] and max(a[i], b[i], c3[i]) > v[1][i]
                                              for i in range(3))]
            if not near:
                continue
            nb, nc = (max(1, math.ceil(e.length / spacing)) for e in (b - a, c3 - a))
            for i in range(nb + 1):
                for j in range(math.floor(nc * (1 - i / nb) + 1e-9) + 1):
                    q = a + (b - a) * (i / nb) + (c3 - a) * (j / nc)
                    sampled[core.name] = sampled.get(core.name, 0) + 1
                    for name, lo, hi, inside in near:
                        if all(lo[k] <= q[k] <= hi[k] for k in range(3)) and inside(q):
                            found.setdefault((name, core.name), []).append(q)
    message = "structure clear of bays: %s frame samples near %d bays and wells" % (
        ", ".join("%s %d" % kv for kv in sorted(sampled.items())), len(volumes))
    if found:
        raise ValueError(message + ": " + "; ".join(
            "%d in the %s from %s, first at s %.3f x %.3f z %.3f" % (len(qs), name, core, qs[0].y + bi.S0, qs[0].x, qs[0].z)
            for (name, core), qs in found.items()))
    print(message + ": PASS", flush=True)


def inside_closed(shell, q, direction=Vector((0.5773, 0.5774, 0.5774))):
    """Whether q lies inside the closed surface in shell: an odd number of crossings along a ray."""
    crossings, origin = 0, q
    while True:
        hit = shell.ray_cast(origin, direction)[0]
        if hit is None:
            return crossings % 2 == 1
        crossings += 1
        origin = hit + direction * 1e-6


# What the game hides in the cockpit view (IcarusAuthor.Cockpit.cs exteriorRenderers, with the canopy's outer panes),
# and the inner panes it draws there, seen through.
COCKPIT_HIDDEN = ("cockpit_cell", "avionics_tray", "radar_tray", "gear_leg_N_visible", "canopy_glass_outer", "windscreen",
                  "cockpit_proxy", "canopy_frame_proxy")
COCKPIT_GLASS = ("canopy_glass_inner", "windscreen_inner")
EYE_RAYS = 200000  # about 0.5 degrees apart
FIT_TOLERANCE = 0.001


def eye_directions(n):
    """n directions spread evenly over the sphere (a Fibonacci lattice)."""
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        z = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(1 - z * z)
        yield Vector((r * math.cos(golden * i), r * math.sin(golden * i), z))


def pilot_eye_leaks(icarus):
    """Cast from the design eye in every direction through what the cockpit view draws, as the game draws it: back
    faces culled, the inner glass seen through. A ray that meets no front face reaches the sky, and must leave through
    the glass: the last surface it crossed is an inner pane. Through the back of the skin or anything else, or past
    nothing at all, is a leak, unless rays a hair either side of it are stopped (it ran down a seam between two
    meshes); every other leak fails, the tub's (consoles, lining, floor, bulkhead) as much as the canopy's. The stock
    seat, stick and throttle are not in the build and stop nothing here."""
    import build_icarus as bi
    import canopy

    meshes = [o for o in icarus.all_objects if o.type == "MESH" and o.name not in COCKPIT_HIDDEN]
    verts, polys, owner = [], [], []
    for o in meshes:
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        for f in o.data.polygons:
            polys.append(tuple(base + i for i in f.vertices))
            owner.append(o.name)
    ray_cast = BVHTree.FromPolygons(verts, polys).ray_cast
    eye = bi.P(*canopy.EYE)

    def leak(at, d):
        """Where the ray from at along d leaves for the sky other than through the glass, and through what."""
        last, out = None, None
        for _ in range(64):
            q, n, i, _ = ray_cast(at, d, 60.0)
            if q is None:
                return None if last in COCKPIT_GLASS else (last or "nothing", out)
            if owner[i] not in COCKPIT_GLASS and n.dot(d) < 0:
                return None  # an opaque front face: the view stops on it
            last, out = owner[i], q
            at = q + d * 1e-5
        return None

    leaks = {}
    for d in eye_directions(EYE_RAYS):
        found = leak(eye, d)
        if found is None:
            continue
        side = d.cross(Z if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized() * 1e-5
        if any(leak(eye + o, d) is None for o in (side, -side, side.cross(d), -side.cross(d))):
            continue
        leaks.setdefault(found[0], []).append(d)
    if leaks:
        found = []
        for name, ds in sorted(leaks.items(), key=lambda kv: -len(kv[1])):
            az = [math.degrees(math.atan2(d.x, -d.y)) for d in ds]  # 0 ahead, + to the left
            el = [math.degrees(math.asin(max(-1.0, min(1.0, d.z)))) for d in ds]
            found.append("%d through %s (azimuth %.0f to %.0f deg, elevation %.0f to %.0f deg)"
                         % (len(ds), name, min(az), max(az), min(el), max(el)))
        total = sum(map(len, leaks.values()))
        raise ValueError("pilot eye leaks: %d of %d rays from the eye escape other than through the glass: %s"
                         % (total, EYE_RAYS, "; ".join(found)))
    print("pilot eye leaks: %d rays from the eye (s %.3f, z %.3f) through %d drawn meshes: none escape but through the "
          "glass: PASS" % (EYE_RAYS, canopy.EYE[0], canopy.EYE[2], len(meshes)), flush=True)


def welded(objs):
    """objs' faces in one world-space bmesh, coincident vertices merged (panel splits close up)."""
    bm = bmesh.new()
    for o in objs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    return bm


def canopy_fit(icarus):
    """Seen from outside, glass, frames and skin meet on one edge, within FIT_TOLERANCE of the fuselage's own loft
    (uncut, so nothing can hide under the hole): every edge of the outer panes but their joint lies on the skin and no
    glass runs under it; the skin's cut edge lies on the glass; no frame lies buried, under the skin but not under the
    canopy (under it is the cockpit); and wherever a frame's outside, out of the canopy's shape, comes down to within
    3 cm of the skin, in 2 cm steps along the cockpit either side, it stands on it."""
    import build_icarus as bi
    import canopy
    import internals

    O = bpy.data.objects
    solid = canopy.skin_solid(bi.PARAMS)
    over_skin = canopy.signed_distance(solid)
    canopy.remove(solid)
    solid = internals.outward(canopy.build_canopy(bi.PARAMS, None))
    over_canopy = canopy.signed_distance(solid)
    shape = tree(solid)
    canopy.remove(solid)
    opening = lambda q: shape.ray_cast(q, Vector((0, 0, 1)), 2.0)[0] is not None  # under the canopy: the cockpit
    where = lambda q: "(s %.3f, x %.3f, z %.3f)" % (q.y + bi.S0, q.x, q.z)
    region = lambda q: canopy.PROFILE[0][0] - 0.1 <= q.y + bi.S0 <= canopy.TAIL_END + 0.1 and q.z > 0.35
    problems = []

    def report(what, found, of):
        found = sorted(found, key=lambda t: -t[0])
        if found:
            problems.append("%d of %d %s, worst %.1f mm at %s" % (len(found), of, what, 1000 * found[0][0], where(found[0][1])))

    hinge = O["canopy"]
    a, u = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
    panes = welded([O[canopy.WINDSCREEN], O[canopy.GLASS_OUTER]])
    joint = lambda e: all(abs((v.co - a).dot(u)) < FIT_TOLERANCE for v in e.verts)
    edge = {v for e in panes.edges if e.is_boundary and not joint(e) for v in e.verts}
    report("glass edge points off the skin", [(abs(over_skin(v.co)), v.co.copy()) for v in edge
                                              if abs(over_skin(v.co)) > FIT_TOLERANCE], len(edge))
    report("glass points under the skin", [(-over_skin(v.co), v.co.copy()) for v in panes.verts
                                           if over_skin(v.co) < -FIT_TOLERANCE], len(panes.verts))
    glass = BVHTree.FromBMesh(panes)
    panes.free()
    skins = welded([o for o in icarus.all_objects if o.type == "MESH" and o.get("role") == "skin"])
    seam = {v for e in skins.edges if e.is_boundary for v in e.verts if region(v.co)}
    report("skin cut-edge points off the glass", [(glass.find_nearest(v.co)[3], v.co.copy()) for v in seam
                                                  if glass.find_nearest(v.co)[3] > FIT_TOLERANCE], len(seam))
    # the frames: the hood's, and the windscreen frame and fixed sills merged into the skin panels, off the skin; their
    # outsides, the points outside the canopy's shape
    points = {}
    for f in skins.faces:
        if all(region(v.co) for v in f.verts) and any(abs(over_skin(v.co)) > FIT_TOLERANCE for v in f.verts):
            points.update((v.index, v.co.copy()) for v in f.verts)
    skins.free()
    points = list(points.values())
    hood = welded([O[canopy.FRAME]])
    points += [v.co.copy() for v in hood.verts]
    hood.free()
    report("frame points buried under the skin", [(-h, q) for h, q in ((over_skin(q), q) for q in points)
                                                  if h < -FIT_TOLERANCE and not opening(q)], len(points))
    outside = [(over_skin(q), q) for q in points if over_canopy(q) > FIT_TOLERANCE]
    lowest = {}
    for h, q in outside:
        key = (round((q.y + bi.S0) / 0.02), q.x > 0)
        if h < lowest.get(key, (math.inf,))[0]:
            lowest[key] = (h, q)
    report("2 cm steps where a frame stands off the skin", [t for t in lowest.values() if FIT_TOLERANCE < t[0] < 0.03],
           len(lowest))
    message = ("canopy fit: %d glass edge points, %d skin cut-edge points, %d frame points, within %.0f mm of the skin"
               % (len(edge), len(seam), len(points), 1000 * FIT_TOLERANCE))
    if problems:
        raise ValueError(message + ": " + "; ".join(problems))
    print(message + ": PASS", flush=True)
