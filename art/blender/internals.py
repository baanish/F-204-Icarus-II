"""Internal parts of the F-204 Icarus II: what a Full Fidelity damage model reveals under the skin.

Built into the "Internals" collection by build_icarus.build(). Each object carries custom properties the Unity author
reads: role (fuel_tank, engine, structure, avionics, radar, cockpit, gear_bay), owner (the external part it sits in),
mass_kg (dry), and for tanks volume_m3. The layout follows the F-104's: radar in the nose, the cockpit, bladder tanks
in the fuselage above the intake ducts, the engine from the duct exit to the nozzle, gear retracting into the
fuselage, no gun in this variant (its bay holds avionics).
"""
import math

import bmesh
import bpy
from mathutils import Vector

import build_icarus as bi

FUEL_DENSITY = 0.80  # kg per litre, JP-8

INTERNALS = {
    "compartment_inset": 0.03,  # how far inside the skin every compartment stays
    "radar": {"s": (0.30, 1.55), "dish_s": 0.95, "dish_r": 0.30, "mass_kg": 120},
    "avionics_nose": {"box": (1.55, 2.30, 0.30, -0.25, 0.42), "mass_kg": 90},  # s0, s1, half width, z0, z1
    "cockpit_tub": {"box": (2.35, 4.90, 0.38, -0.05, 0.78), "mass_kg": 260},
    "avionics_aft": {"box": (4.95, 5.15, 0.42, 0.00, 0.70), "mass_kg": 140},  # a shelf; the gun bay holds fuel
    # Fuel, after the F-104S layout: an auxiliary cell in the old gun bay (as on the gunless F-104), the forward
    # main tank, three connected aft cells (the centre one between the intake ducts, the side ones wrapping round
    # them), and cells in the strakes and outboard wings. No fuel over or around the engine: a leak there is a fire. Each fuselage row: (s0, s1,
    # inset from the skin, z floor, x from, x to). A cell fills the skin section above its floor between its x
    # limits, minus the ducts with clearance. The design load is spread over the cells by what each holds: what they
    # hold round the F-104-style gear wells and the Y-duct, one constant tube from just behind the lips to the engine
    # face, its branches' inboard walls flat from the lips, with the shock cones cut back to their tips (design's 2,400 kg,
    # trimmed by the wells to 2,320).
    "design_fuel_kg": 3082,
    "duct_clearance": 0.025,  # duct wall plus gap between a fuel cell and an intake duct
    # The fuel cells' mesh, coarse since they show only when a section breaks away: points round each section,
    # stations every step metres (lip_step within 0.3 m of the intake lip), and the duct cutter that shapes them,
    # duct_points round each of its rings on duct_stations stations, with floor_step between those over the
    # flattened floor. Coarser cuts the cells' sections across the lobe's crease into the skin, or the cutter's chords
    # inside the duct's clearance.
    "cell_mesh": {"points": 16, "step": 0.4, "lip_step": 0.3,
                  "duct_points": 16, "duct_stations": 11, "floor_step": 0.3},
    # The aux cell's floor keeps its coarse section DUCT_CLEARANCE off the store trough (stations.trough_clearance).
    "fuel_aux": {"tank": (5.20, 5.90, 0.04, -0.20, -9.0, 9.0)},
    "fuel_forward_main": {"tank": (5.95, 7.70, 0.04, 0.05, -9.0, 9.0)},
    # The aft cells run on to 9.55, short of the compressor faces at 9.60 (none round the engine); the gear wells
    # cut their lower lobes, as the F-104's main wells lie under its aft centre cell.
    "fuel_aft_center": {"tank": (7.75, 9.55, 0.04, -0.22, -0.24, 0.24)},
    "fuel_aft_L": {"tank": (7.75, 9.55, 0.04, -0.15, 0.26, 0.92)},  # outboard of 0.92 is the strake cell
    "fuel_aft_R": {"tank": (7.75, 9.55, 0.04, -0.15, -0.92, -0.26)},
    "gear_cut": 0.015,  # a fuel cell's wall this far from a gear well's
    "strake_tank": {"x": (1.10, 1.88), "f": (0.06, 0.70)},  # each strake: span and chord fraction, ahead of the flap
    "wing_tank": {"x": (1.95, 3.05), "f": (0.17, 0.68)},  # the box between the spars, outboard of the crank
    # z0 is the axis height at the face, z1 at the nozzle; the face sits high enough for the stowed main wheels below.
    "engine": {"face_s": 9.70, "core_end_s": 13.10, "radius": 0.46, "ab_radius": 0.36, "end_s": 15.00,
               "z0": 0.35, "z1": 0.37, "mass_kg": 1450},
    # The fuselage's frame stations: 0.6 m apart, as the painted panel lines are (art/textures/panels.py). No frame,
    # stringer or wall is drawn, as on stock jets; the structure cores' and the truss's collider shells are cut from the
    # skin's shape there, inset and inset plus web inside it, over each frame's flange (shell_rings, hulls.shell_groups),
    # and just inside each break, at the ends ("ends": stations, thickness, inset), so each section's shells run to its
    # breaks and its centre of mass (the hulls' box) stays where the balance pins it (IcarusAuthor A22).
    "frames": {"s0": 1.6, "s1": 14.8, "pitch": 0.6, "inset": 0.03, "web": 0.08, "flange": 0.05,
               "ends": ((5.57, 5.92, 10.97, 11.03, 12.97, 13.075, 14.76), 0.02, 0.035)},
    # the front spar on the fixed box, behind the leading-edge flap's cut (0.166 of the chord)
    "spars": {"front_f": 0.175, "rear_f": 0.70, "rib_pitch": 0.45, "mass_kg_side": 140},
    # The gear wells, each a union of boxes (s from, s to, x from, x to, z from, z to) clipped to just inside the
    # skin (bay_inset), round the stowed gear and the path it folds through (gear.GEAR). The nose well: the flat
    # wheel and the folded leg under the cockpit floor, then a narrow slot back past the oleo. Each main well, left side (the right mirrors it): the flat tyre under the
    # duct's flattened underside, the carrier and leg along the keel back to the trunnion, the lobe's flank the wheel
    # comes in through, and the leg's way down aft of the trough.
    # A well runs out to the skin only over its doors' holes; elsewhere it stays clear of the skin.
    "nose_gear_bay": {"boxes": [(4.00, 5.035, -0.31, 0.31, -0.56, -0.23), (5.025, 5.31, -0.105, 0.105, -0.56, -0.23)],
                      "mass_kg": 0},
    "main_gear_bay": {"boxes": [(8.77, 9.49, 0.0, 0.46, -0.27, 0.09), (8.77, 9.49, 0.46, 0.70, -0.17, 0.09),
                                (8.785, 9.108, 0.50, 0.96, -0.56, 0.09), (8.80, 9.108, 0.40, 0.50, -0.56, 0.09),
                                (9.06, 10.78, 0.55, 0.97, -0.56, 0.09), (9.06, 10.78, 0.17, 0.97, -0.56, -0.10)],
                      "mass_kg": 0},
    "bay_inset": 0.0005,  # the gear wells' walls this far inside the skin (the doors' own gap is gear.DOOR_GAP)
    "bay_duct_gap": 0.01,  # the main wells' roofs this far below the ducts' walls
}


def box(name, s0, s1, hw, z0, z1, x=0.0):
    v = [bi.P(s, x + sx * hw, z) for s in (s0, s1) for sx in (-1, 1) for z in (z0, z1)]
    # index = s*4 + side*2 + z
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return bi.mesh_object(name, v, faces)


def bay_boxes(name, side=1):
    """A gear well's boxes (s from, s to, x from, x to, z from, z to), mirrored for the right main well."""
    boxes = INTERNALS[name]["boxes"]
    return boxes if side > 0 else [(s0, s1, -x1, -x0, z0, z1) for s0, s1, x0, x1, z0, z1 in boxes]


def boxes_solid(name, boxes, steps=None):
    """One closed solid, the union of axis-aligned boxes (s from, s to, x from, x to, z from, z to). Each box is grown
    by its own fraction of a millimetre (steps: each box's, by default its index), so no two share a face plane: the
    exact union leaves coplanar faces non-manifold, and a cutter that is not closed corrupts what it cuts. Boxes that
    never touch may share a step."""
    objs = [outward(box(name, s0 - e, s1 + e, (x1 - x0) / 2 + e, z0 - e, z1 + e, x=(x0 + x1) / 2))
            for i, (s0, s1, x0, x1, z0, z1) in enumerate(boxes) for e in [0.0003 * ((steps or range(len(boxes)))[i] + 1)]]
    first = objs[0]
    for other in objs[1:]:
        mod = first.modifiers.new("union", "BOOLEAN")
        mod.operation, mod.solver, mod.object = "UNION", "EXACT", other
    bpy.context.view_layer.update()
    baked = bpy.data.meshes.new_from_object(first.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    old = first.data
    first.modifiers.clear()
    first.data = baked
    bpy.data.meshes.remove(old)
    for other in objs[1:]:
        me = other.data
        bpy.data.objects.remove(other, do_unlink=True)
        bpy.data.meshes.remove(me)
    first.name = baked.name = name
    drop_degenerate(first)
    return outward(first)


@bi.geometry_cache.ring
def ring_at(p, s, inset, floor=None, x_lo=None, x_hi=None, count=None):
    """The skin section at s pulled inward by inset. With floor or x limits, the section is clipped to z >= floor
    and x_lo <= x <= x_hi (a true polygon cut, so the result never leaves the skin); clipped or given a count, it is
    resampled to count points evenly round its outline, so neighbouring sections loft cleanly."""
    ring = bi.skin_ring(p, s)
    out = pulled(ring, inset)
    if floor is None and x_lo is None and count is None:
        return out
    y = out[0].y
    pts = [(v.x, v.z) for v in out]
    if floor is not None:
        pts = clip(pts, lambda q: q[1] - floor)
    if x_lo is not None:
        pts = clip(pts, lambda q: q[0] - x_lo)
        pts = clip(pts, lambda q: x_hi - q[0])
    return [Vector((x, y, z)) for x, z in resample_outline(pts, count or len(ring) // 2)]


def pulled(ring, inset):
    """A skin ring's columns pulled inset toward its centre line (x = 0, its mean z)."""
    cz = sum(v.z for v in ring) / len(ring)
    out = []
    for v in ring:
        d = Vector((v.x, 0.0, v.z - cz))
        out.append(v - d.normalized() * inset if d.length > inset else Vector((0.0, v.y, cz)))
    return out


def clip(poly, inside):
    """Sutherland-Hodgman: keep the part of a closed polygon where inside(point) >= 0."""
    out = []
    for i, cur in enumerate(poly):
        prev = poly[i - 1]
        a, b = inside(prev), inside(cur)
        if b >= 0:
            if a < 0:
                t = a / (a - b)
                out.append((prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t))
            out.append(cur)
        elif a >= 0:
            t = a / (a - b)
            out.append((prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t))
    return out


def resample_outline(poly, n):
    """n points evenly spaced round a closed polygon, starting straight below its centroid, so that sections of
    different shapes still line up when lofted (starting from a corner lets the start jump between sections)."""
    cx = sum(q[0] for q in poly) / len(poly)
    cz = sum(q[1] for q in poly) / len(poly)
    # Insert the point where the outline crosses the vertical through the centroid, below it, and start there:
    # the nearest vertex would jump between the two corners of a flat floor.
    best = None
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if (a[0] - cx) * (b[0] - cx) <= 0 and a[0] != b[0]:
            t = (cx - a[0]) / (b[0] - a[0])
            z = a[1] + (b[1] - a[1]) * t
            if z < cz and (best is None or z < best[1]):
                best = (i, z)
    i, z = best
    poly = [(cx, z)] + poly[i + 1:] + poly[:i + 1]
    seg = [((poly[(i + 1) % len(poly)][0] - poly[i][0]) ** 2 + (poly[(i + 1) % len(poly)][1] - poly[i][1]) ** 2) ** 0.5
           for i in range(len(poly))]
    total = sum(seg)
    out, i, acc = [], 0, 0.0
    for k in range(n):
        target = total * k / n
        while acc + seg[i] < target:
            acc += seg[i]
            i += 1
        t = (target - acc) / seg[i] if seg[i] else 0.0
        a, b = poly[i], poly[(i + 1) % len(poly)]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def duct_cutter(p, clearance, n=28, count=18, floor_step=0.1):
    """Closed solids around the Y-duct and each shock cone, grown by clearance, to cut out of the fuel cells. The duct's
    is one solid: each half lofted up to the centre plane, the faces on the plane dropped and the halves welded there.
    Two halves overlapping across the plane would share the trunk's wall there, and the exact boolean fails on faces
    that nearly coincide."""
    # A ring just behind where the grown branches merge closes the wedge of fuel between them there, well ahead of
    # the duct's own crotch; one on each of the duct's rows up to its tube keeps the loft on its quick close behind
    # the lip.
    import propulsion

    stations = sorted(set(bi.duct_stations(p, p["duct"][0][0] - 0.3, p["duct"][-1][0] + 0.3, count, floor_step)
                          + [round(bi.duct_merge_s(p, clearance) + 0.002, 4)]
                          + [row[0] for row in p["duct"] if row[0] <= propulsion.DUCT_AREAS["tube_s"][0]]))
    half = [[bi.P(s, x, z) for x, z in bi.duct_ring(p, s, n, clearance, 0.0, closed=True)] for s in stations]
    loop = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
            for j in range(len(half) - 1) for k in range(n)]
    loop += [tuple(range(n))[::-1], tuple((len(half) - 1) * n + k for k in range(n))]
    verts = [v for ring in half for v in ring]
    faces = loop + [tuple(len(verts) + i for i in f[::-1]) for f in loop]  # the right half, mirrored
    duct = bi.mesh_object("duct_cutter", verts + [Vector((-v.x, v.y, v.z)) for v in verts], faces)
    bm = bmesh.new()
    bm.from_mesh(duct.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if all(abs(v.co.x) < 1e-9 for v in f.verts)], context="FACES")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-7)
    if any(not e.is_manifold for e in bm.edges):
        raise ValueError("internals: the Y-duct's cutter is not closed")
    bm.to_mesh(duct.data)
    bm.free()
    cutters = [outward(duct)]
    for side in (1, -1):
        sc = p["shock_cone"]
        zc = p["intake"][0][2]
        r = sc["radius"] + clearance
        cone = bi.loft("cone_cutter_%d" % side,
                       [[bi.P(s, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                         for a in [2 * math.pi * k / 32 for k in range(32)]]
                        for s in (sc["apex_s"] - 0.05, sc["base_s"] + sc["cap"] + 0.05)],
                       cap_back=True, cap_front=True)
        cutters.append(outward(cone))
    return cutters


def outward(obj):
    """Make a closed mesh's faces point outward; lofts and mirrored copies can come out inside-out, which the
    exact boolean reads as an inverted solid."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    inverted = bm.calc_volume(signed=True) < 0
    bm.free()
    if inverted:
        obj.data.flip_normals()
    return obj


def grown(obj, by):
    """A copy of a closed mesh pushed out along its normals, to cut with clearance instead of a shared face."""
    me = obj.data.copy()
    me.transform(obj.matrix_world)
    bm = bmesh.new()
    bm.from_mesh(me)
    if bm.calc_volume(signed=True) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * by
    bm.to_mesh(me)
    bm.free()
    cutter = bpy.data.objects.new(obj.name + "_cutter", me)
    bi.TARGET.objects.link(cutter)
    return cutter


def inner_solid(p, inset, s0=0.25, s1=15.15, step=0.05, count=None):
    """A closed solid just inside the fuselage skin, to clip compartments to: sections every step metres, of count
    points (the skin's own ring by default). A clipped compartment takes on its faceting."""
    n = int(round((s1 - s0) / step)) + 1
    rings = [ring_at(p, s0 + (s1 - s0) * i / (n - 1), inset, count=count) for i in range(n)]
    return outward(bi.loft("inner_solid", rings, cap_back=True, cap_front=True))


def compartment_solid(p, inset, s0, s1):
    """Offset the rendered skin's triangles inward, keeping at least inset to each incident face plane.

    Radial ring offsets have less normal clearance on sloping skin, and resampled rings can bridge its bends.
    Keep the skin's own stations and angular vertices so neither approximation defines a compartment's fit.
    Two micrometres of extra offset absorb float32 and Boolean rounding.
    """
    stations = [s0] + [s for s in bi.fuselage_stations(p) if s0 < s < s1] + [s1]
    solid = outward(bi.loft("compartment_solid", [bi.skin_ring(p, s) for s in stations],
                            cap_back=True, cap_front=True))
    solid.data.calc_loop_triangles()
    triangulated = bpy.data.meshes.new("compartment_triangles")
    triangulated.from_pydata([v.co for v in solid.data.vertices], [], [t.vertices for t in solid.data.loop_triangles])
    original = solid.data
    solid.data = triangulated
    bpy.data.meshes.remove(original)
    bm = bmesh.new()
    bm.from_mesh(solid.data)
    bm.normal_update()
    offsets = {v: v.normal * ((inset + 2e-6) / min(v.normal.dot(f.normal) for f in v.link_faces)) for v in bm.verts}
    for v, offset in offsets.items():
        v.co -= offset
    bm.to_mesh(solid.data)
    bm.free()
    return solid


def clip_to(obj, solid):
    """Bake obj intersected with solid into obj's own mesh, so a box compartment follows the round skin."""
    outward(obj)
    mod = obj.modifiers.new("clip", "BOOLEAN")
    mod.operation, mod.solver, mod.object = "INTERSECT", "EXACT", solid
    bpy.context.view_layer.update()
    baked = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    old = obj.data
    obj.modifiers.clear()
    obj.data = baked
    baked.name = obj.name
    bpy.data.meshes.remove(old)
    drop_degenerate(obj)
    return obj


def subtract(obj, cutters):
    """Bake obj minus the cutters into obj's own mesh."""
    for c in cutters:
        mod = obj.modifiers.new("cut_" + c.name, "BOOLEAN")
        mod.operation, mod.solver, mod.object = "DIFFERENCE", "EXACT", c
    bpy.context.view_layer.update()
    baked = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    old = obj.data
    obj.modifiers.clear()
    obj.data = baked
    baked.name = obj.name
    bpy.data.meshes.remove(old)
    drop_degenerate(obj)


def drop_degenerate(obj):
    """Booleans leave zero-area slivers and empty material slots from the cutter; drop both so the export carries
    neither. The faces keep their own materials (a fin keeps its rudder cove's trim); cut faces take the first."""
    slots = list(obj.data.materials)
    keep = [m for m in dict.fromkeys(slots) if m is not None]
    remap = [keep.index(m) if m is not None else 0 for m in slots] or [0]
    faces = [remap[min(poly.material_index, len(remap) - 1)] for poly in obj.data.polygons]
    obj.data.materials.clear()  # resets every face's index
    for m in keep:
        obj.data.materials.append(m)
    for poly, index in zip(obj.data.polygons, faces):
        poly.material_index = index
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges)
    bm.to_mesh(obj.data)
    bm.free()


def mesh_volume(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    v = abs(bm.calc_volume())
    bm.free()
    return v


def tank(p, name, s0, s1, inset, floor, x_lo, x_hi, mat, cutters):
    # Stations every 0.2 m, but every 0.1 m within 0.3 m of the intake lip and either side of it, where the skin
    # changes fastest: a coarser cell bridges straight across a quick change in the skin and pokes through it.
    lip = p["intake"][0][0]
    mesh = INTERNALS["cell_mesh"]
    stations, s = [s0], s0
    while s < s1 - 1e-6:
        s = min(s1, s + (mesh["lip_step"] if abs(s - lip) < 0.3 else mesh["step"]))
        stations.append(round(s, 4))
    stations = sorted(set(stations) | {x for x in (lip - 0.02, lip + 0.06) if s0 < x < s1})  # clear of the lip's step
    rings = [ring_at(p, s, inset, floor, x_lo, x_hi, count=mesh["points"]) for s in stations]
    obj = bi.finish(outward(bi.loft(name, rings, cap_back=True, cap_front=True)), mat, smooth=False)
    subtract(obj, cutters)  # the cells are separate from the intake ducts, with clearance for the duct walls
    # Boolean n-gons cast broken Workbench stencil shadows through the skin. Match the export's triangulation.
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(obj.data)
    bm.free()
    vol = mesh_volume(obj)
    obj["volume_m3"] = round(vol, 3)
    obj["volume_holds_kg"] = round(vol * 1000 * FUEL_DENSITY, 1)
    return obj


def shell_rings(p):
    """The shape the structure cores' and the truss's collider shells are cut from (hulls.shell_groups), as (station,
    points) with the station that places them: each frame station's skin section pulled in by the inset and by inset
    plus web, at the station and its flange's aft edge, and each of the ends' sections pulled in by their inset either
    side of the station. Stations are summed as they always were, so one lands a rounding off a break
    (12.999999999999995), which parts.in_section puts ahead."""
    f = INTERNALS["frames"]
    aft = lambda ring, dy: [v + Vector((0.0, dy, 0.0)) for v in ring]
    out, s = [], f["s0"]
    while s <= f["s1"] + 1e-9:
        ring = bi.skin_ring(p, s)
        section = pulled(ring, f["inset"]) + pulled(ring, f["inset"] + f["web"])
        out.append((s, section + aft(section, f["flange"])))
        s += f["pitch"]
    stations, thickness, inset = f["ends"]
    for s in stations:
        ring = pulled(bi.skin_ring(p, s), inset)
        out.append((s, aft(ring, -thickness / 2) + aft(ring, thickness / 2)))
    return out


def section_points(obj, s):
    """Where obj's mesh crosses the station plane at s, as (x, z) points; empty if it does not."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-6,
                                 plane_co=bi.P(s, 0.0, 0.0), plane_no=Vector((0, 1, 0)))
    pts = [(v.co.x, v.co.z) for v in cut["geom_cut"] if isinstance(v, bmesh.types.BMVert)]
    bm.free()
    return pts


def inside(q, poly):
    """Even-odd test of the (x, z) point q against a closed polygon."""
    hit = False
    for (x1, z1), (x2, z2) in zip(poly[-1:] + poly[:-1], poly):
        if (z1 > q[1]) != (z2 > q[1]) and q[0] < x1 + (q[1] - z1) * (x2 - x1) / (z2 - z1):
            hit = not hit
    return hit


def cylinder_loft(name, profile, segments=32):
    """profile: (s, x, z, r) rows along the part."""
    rings = [[bi.P(s, x + r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / segments for k in range(segments)]]
             for s, x, z, r in profile]
    return bi.loft(name, rings, cap_back=True)


def tag(obj, role, owner, mass_kg=0.0):
    obj["role"] = role
    obj["owner"] = owner
    obj["mass_kg"] = mass_kg
    return obj


def build(p, col, mats):
    """Build every internal part into col. mats: dict of role -> material."""
    prev, bi.TARGET = bi.TARGET, col
    try:
        return _build(p, mats)
    finally:
        bi.TARGET = prev


def _build(p, mats):
    I = INTERNALS
    parts = []
    inner = compartment_solid(p, I["compartment_inset"], 0.25, 5.35)
    r = I["radar"]
    nose = bi.blended_ring(p, r["dish_s"])
    cz = (max(v.z for v in nose) + min(v.z for v in nose)) / 2
    dish_r = min(r["dish_r"], min((v - bi.P(r["dish_s"], 0.0, cz)).length for v in nose) - I["compartment_inset"] - 0.02)
    dish = cylinder_loft("radar_dish", [(r["dish_s"], 0.0, cz, dish_r), (r["dish_s"] + 0.04, 0.0, cz, dish_r)])
    parts.append(tag(bi.finish(clip_to(dish, inner), mats["avionics"], smooth=False), "radar", "fuselage", r["mass_kg"] * 0.4))
    unit = box("radar_unit", r["dish_s"] + 0.08, r["s"][1], 0.20, -0.15, 0.22)
    parts.append(tag(bi.finish(clip_to(unit, inner), mats["avionics"], smooth=False), "radar", "fuselage", r["mass_kg"] * 0.6))

    s0, s1, hw, z0, z1 = I["avionics_nose"]["box"]
    obj = bi.finish(clip_to(box("avionics_nose", s0, s1, hw, z0, z1), inner), mats["avionics"], smooth=False)
    parts.append(tag(obj, "avionics", "fuselage", I["avionics_nose"]["mass_kg"]))
    import checks

    checks.compartment_clearance(parts, bpy.data.objects["fuselage"], I["compartment_inset"])
    bpy.data.objects.remove(inner, do_unlink=True)
    inner = inner_solid(p, I["compartment_inset"], 0.25, 5.35, step=0.25, count=48)
    for name, role in (("cockpit_tub", "cockpit"), ("avionics_aft", "avionics")):
        s0, s1, hw, z0, z1 = I[name]["box"]
        obj = bi.finish(clip_to(box(name, s0, s1, hw, z0, z1), inner), mats[role], smooth=False)
        parts.append(tag(obj, role, "fuselage", I[name]["mass_kg"]))
    bpy.data.objects.remove(inner, do_unlink=True)
    # The gear wells run out to just inside the skin: a well a compartment's inset short of it would leave a slot
    # round the open doors that looks past the well's walls into the structure. The main wells' roofs stand above the
    # ducts' flattened floor where it dips at the wells' ends; cut clear of the ducts, or they stand
    # inside the intakes. Over the middle the floor stands only 8 to 15 mm above the roof, so a wider clearance
    # would cut the whole roof down.
    ducts = duct_cutter(p, I["bay_duct_gap"])
    for name, side in (("nose_gear_bay", 1), ("main_gear_bay_L", 1), ("main_gear_bay_R", -1)):
        boxes = bay_boxes(name[:13], side)
        inner = compartment_solid(p, I["bay_inset"], min(b[0] for b in boxes) - 0.15, max(b[1] for b in boxes) + 0.15)
        obj = clip_to(boxes_solid(name, boxes), inner)
        if name.startswith("main"):
            subtract(obj, ducts)
        parts.append(tag(bi.finish(obj, mats["gear_bay"], smooth=False), "gear_bay", "fuselage"))
        bpy.data.objects.remove(inner, do_unlink=True)
    for c in ducts:
        bpy.data.objects.remove(c, do_unlink=True)

    mesh = I["cell_mesh"]
    cutters = duct_cutter(p, I["duct_clearance"], mesh["duct_points"], mesh["duct_stations"], mesh["floor_step"])
    wing_cut = [grown(bpy.data.objects[n], 0.015) for n in ("wing_L", "wing_R")]  # wing roots buried in the body
    g = I["gear_cut"]
    # The main wells as one solid, their keel boxes as one box across the centre line: two wells cut one after the
    # other would each leave a face on the same plane over the keel, where the Y-duct's cutter meets them, and the
    # exact boolean fails there. Each mirrored pair of boxes shares a step; they never touch.
    grow = lambda boxes: [(s0 - g, s1 + g, x0 - g, x1 + g, z0 - g, z1 + g) for s0, s1, x0, x1, z0, z1 in boxes]
    main = bay_boxes("main_gear_bay")
    if main[0][2] != 0.0 or any(b[2] <= 0.0 for b in main[1:]):
        raise ValueError("internals: only the main well's first box may reach the keel")
    keel = (*main[0][:2], -main[0][3], main[0][3], *main[0][4:])
    wells = [boxes_solid("well_cut", grow(bay_boxes("nose_gear_bay"))),
             boxes_solid("well_cut", grow([keel] + main[1:] + bay_boxes("main_gear_bay", -1)[1:]),
                         [0] + list(range(1, len(main))) * 2)]
    for name in ("fuel_aux", "fuel_forward_main", "fuel_aft_center", "fuel_aft_L", "fuel_aft_R"):
        s0, s1, inset, floor, x_lo, x_hi = I[name]["tank"]
        obj = tank(p, name, s0, s1, inset, floor, x_lo, x_hi, mats["fuel_tank"], cutters + wing_cut + wells)
        parts.append(tag(obj, "fuel_tank", "fuselage"))
    for c in cutters + wing_cut + wells:
        bpy.data.objects.remove(c, do_unlink=True)
    st = I["strake_tank"]
    wing_rows = bi.wing_sections(p["wing"])
    cells = [("fuel_strake", st), ("fuel_wing", I["wing_tank"])]
    for (cell, st), (side, suffix) in [(c, s) for c in cells for s in ((1, "_L"), (-1, "_R"))]:
        stations = [(u, st["f"][0], st["f"][1]) for u in bi.span_stations(wing_rows, "x", *st["x"])]
        obj = bi.strip(cell + suffix, wing_rows, stations, p["wing"]["thickness"] * 0.85, "x")
        if side < 0:
            obj.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
            obj.data.flip_normals()
        bi.finish(obj, mats["fuel_tank"], smooth=False)
        vol = mesh_volume(obj)
        obj["volume_m3"] = round(vol, 3)
        obj["volume_holds_kg"] = round(vol * 1000 * FUEL_DENSITY, 1)
        parts.append(tag(obj, "fuel_tank", "wing" + suffix))
    cells = [o for o in parts if o["role"] == "fuel_tank"]
    holds = sum(o["volume_holds_kg"] for o in cells)
    if holds < I["design_fuel_kg"]:
        raise ValueError("fuel cells hold %.0f kg, less than the %d kg design load" % (holds, I["design_fuel_kg"]))
    for o in cells:
        o["fuel_kg"] = round(I["design_fuel_kg"] * o["volume_holds_kg"] / holds, 1)
    wing = bi.wing_sections(p["wing"])

    e = I["engine"]
    core = cylinder_loft("engine_core", [(e["face_s"], 0.0, e["z0"], e["radius"] * 0.92), (e["face_s"] + 0.15, 0.0, e["z0"], e["radius"]),
                                         (e["core_end_s"], 0.0, 0.5 * (e["z0"] + e["z1"]), e["radius"])])
    parts.append(tag(bi.finish(core, mats["engine"]), "engine", "fuselage", e["mass_kg"] * 0.8))
    ab = cylinder_loft("engine_afterburner", [(e["core_end_s"], 0.0, 0.5 * (e["z0"] + e["z1"]), e["radius"] * 0.96),
                                              (e["end_s"], 0.0, e["z1"], e["ab_radius"])])
    parts.append(tag(bi.finish(ab, mats["engine"]), "engine", "fuselage", e["mass_kg"] * 0.2))

    sp = I["spars"]
    for side, suffix in ((1, "_L"), (-1, "_R")):
        pieces = []
        x0, x1 = 0.62, wing[-1][1] - 0.06
        # Each spar in two at the crank, where the wing's inner box (parts.organise) ends and its outer box begins.
        for name, f in (("spar_front", sp["front_f"]), ("spar_rear", sp["rear_f"])):
            for piece, a, b in (("", x0, bi.WING_CRANK), ("_outer", bi.WING_CRANK, x1)):
                stations = [(u, f - 0.006, f + 0.006) for u in bi.span_stations(wing, "x", a, b)]
                pieces.append(bi.strip(name + piece + suffix, wing, stations, p["wing"]["thickness"] * 0.9, "x"))
        n_ribs = int((x1 - x0) / sp["rib_pitch"]) + 1
        for i in range(n_ribs):
            u = x0 + i * (x1 - x0) / (n_ribs - 1)
            stations = [(u - 0.006, sp["front_f"], sp["rear_f"]), (u + 0.006, sp["front_f"], sp["rear_f"])]
            pieces.append(bi.strip("rib_%02d%s" % (i, suffix), wing, stations, p["wing"]["thickness"] * 0.9, "x",
                                   count=6))  # a flat web between the spars
        for obj in pieces:
            if side < 0:
                obj.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
                obj.data.flip_normals()
            bi.finish(obj, mats["structure"], smooth=False)
            parts.append(tag(obj, "structure", "wing" + suffix, sp["mass_kg_side"] / len(pieces)))

    return parts

