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
    "avionics_aft": {"box": (4.95, 5.15, 0.42, 0.00, 0.70), "mass_kg": 140},  # above the nose gear bay  # a shelf; the gun bay holds fuel
    # Fuel, after the F-104S layout: an auxiliary cell in the old gun bay (as on the gunless F-104), the forward
    # main tank, three connected aft cells (the centre one between the intake ducts, the side ones wrapping round
    # them), and cells in the strakes and outboard wings. No fuel over or around the engine: a leak there is a fire. Each fuselage row: (s0, s1,
    # inset from the skin, z floor, x from, x to). A cell fills the skin section above its floor between its x
    # limits, minus the ducts with clearance. The design load is spread over the cells by what each holds.
    "design_fuel_kg": 2400,
    "duct_clearance": 0.025,  # duct wall plus gap between a fuel cell and an intake duct
    "fuel_aux": {"tank": (5.20, 5.90, 0.04, -0.22, -9.0, 9.0)},
    "fuel_forward_main": {"tank": (5.95, 7.70, 0.04, 0.05, -9.0, 9.0)},
    "fuel_aft_center": {"tank": (7.75, 9.30, 0.04, -0.22, -0.24, 0.24)},
    "fuel_aft_L": {"tank": (7.75, 9.30, 0.04, -0.15, 0.26, 0.92)},  # outboard of 0.92 is the strake cell
    "fuel_aft_R": {"tank": (7.75, 9.30, 0.04, -0.15, -0.92, -0.26)},
    "strake_tank": {"x": (1.10, 1.88), "f": (0.06, 0.70)},  # each strake: span and chord fraction, ahead of the flap
    "wing_tank": {"x": (1.95, 3.05), "f": (0.17, 0.68)},  # the box between the spars, outboard of the crank
    # z0 is the axis height at the face, z1 at the nozzle; the face sits high enough for the stowed main wheels below.
    "engine": {"face_s": 9.70, "core_end_s": 13.10, "radius": 0.46, "ab_radius": 0.36, "end_s": 15.00,
               "z0": 0.35, "z1": 0.37, "mass_kg": 1450},
    # The fuselage's semi-monocoque grid, laid on the skin's own columns (bi.RING round each section) so frames and
    # stringers meet at shared points and follow the skin exactly. Frames: an L section, a flange along the skin and
    # a web standing in from it, through every stringer's column and whatever others keep its straight runs within
    # tolerance of the skin (more round the intake fillets, few on the round top). Stringers: on every sixth column,
    # 16 round the body, about 0.25 m apart at the widest, so the bays between them and the 0.6 m frames read as
    # skin panels, about 2.5 to 1, as on a real fuselage. The four at 45 degrees off the vertical, where a fuselage
    # carries its corner longerons, are heavier. Each stringer runs inside one structure core, wall to wall (runs),
    # straight between the fewest skin stations that keep it within tolerance of its column.
    "frames": {"s0": 1.6, "s1": 14.8, "pitch": 0.6, "inset": 0.03, "tolerance": 0.02, "flange": 0.05, "web": 0.08,
               "thickness": 0.008, "mass_kg_each": 9},
    "stringers": {"column_step": 6, "size": (0.015, 0.025), "tolerance": 0.01,
                  "longerons": (12, 36, 60, 84), "longeron_size": (0.03, 0.04),
                  "runs": ((1.6, 5.57), (5.92, 10.97), (11.03, 14.8))},
    # A thin wall just inside each fuselage break (parts.FORWARD_END 5.6, MID_END 11.0 and the tail end at 14.8), so
    # a section that comes away shows a closed, shaded face instead of open frames against the sky. Each is cut clear
    # of whatever runs through it and has a torn rim. Stations (centres): 5.57 and 10.97 ahead of their joints,
    # 11.03 behind its joint, 14.76 inside the last frame; the mid section's front wall stands at 5.92, behind the
    # aux cell (to 5.90), which leaves with the forward section and would hole a wall at the joint down to its floor.
    # The radome break at 1.6 needs none: the nose avionics box fills the section there.
    "bulkheads": {"at": (5.57, 5.92, 10.97, 11.03, 14.76), "thickness": 0.02, "inset": 0.035, "points": 20,
                  "tear": (0.0, 0.6, 0.15, 1.0, 0.35, 0.0, 0.8, 0.25, 0.5, 0.05), "tear_depth": 0.03,
                  "clearance": 0.015, "hole_points": 12},
    # the front spar on the fixed box, behind the leading-edge flap's cut (0.166 of the chord)
    "spars": {"front_f": 0.175, "rear_f": 0.70, "rib_pitch": 0.45, "mass_kg_side": 140},
    # The nose leg folds forward into its bay under the cockpit floor; the bay's roof stays under fuel_aux's floor.
    "nose_gear_bay": {"box": (4.06, 5.32, 0.31, -0.55, -0.23), "mass_kg": 0},
    # Each main leg folds inboard and its oleo and wheel fold again into a bay from the keel to the lobe; the bay's
    # roof runs on into the engine and the wing root, which close it.
    "main_gear_bay": {"box": (9.62, 11.15, 0.41, -0.50, 0.25), "x": 0.45, "mass_kg": 0},
}


def box(name, s0, s1, hw, z0, z1, x=0.0):
    v = [bi.P(s, x + sx * hw, z) for s in (s0, s1) for sx in (-1, 1) for z in (z0, z1)]
    # index = s*4 + side*2 + z
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return bi.mesh_object(name, v, faces)


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


def duct_cutter(p, clearance):
    """Closed solids around each intake duct and its shock cone, grown by clearance, to cut out of the fuel cells."""
    rows = bi.resample(p["duct"], bi.spaced(p["duct"][0][0] - 0.3, p["duct"][-1][0] + 0.3, 14))
    cutters = []
    for side in (1, -1):
        rings = [[bi.P(s, side * (cx + (r + clearance) * math.cos(a)), cz + (r + clearance) * math.sin(a))
                  for a in [2 * math.pi * k / 32 for k in range(32)]] for s, cx, cz, r in rows]
        cutters.append(outward(bi.loft("duct_cutter_%d" % side, rings, cap_back=True, cap_front=True)))
        sc = p["shock_cone"]
        zc = p["intake"][0][2]
        r = sc["radius"] + clearance
        cone = bi.loft("cone_cutter_%d" % side,
                       [[bi.P(s, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                         for a in [2 * math.pi * k / 32 for k in range(32)]] for s in (sc["apex_s"] - 0.05, sc["base_s"] + 0.05)],
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
    stations, s = [s0], s0
    while s < s1 - 1e-6:
        s = min(s1, s + (0.1 if abs(s - lip) < 0.3 else 0.2))
        stations.append(round(s, 4))
    stations = sorted(set(stations) | {x for x in (lip - 0.02, lip + 0.06) if s0 < x < s1})  # clear of the lip's step
    rings = [ring_at(p, s, inset, floor, x_lo, x_hi, count=32) for s in stations]
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


def hull_2d(pts):
    """Convex hull of (x, z) points, counter-clockwise (monotone chain)."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def grown_hull(hull, by):
    """A counter-clockwise convex polygon pushed out by `by` along its edge normals."""
    out = []
    for i, b in enumerate(hull):
        a, c = hull[i - 1], hull[(i + 1) % len(hull)]
        n1 = Vector((b[1] - a[1], -(b[0] - a[0]))).normalized()
        n2 = Vector((c[1] - b[1], -(c[0] - b[0]))).normalized()
        bis = (n1 + n2).normalized()
        d = by / max(bis.dot(n1), 0.3)
        out.append((b[0] + bis.x * d, b[1] + bis.y * d))
    return out


def bulkhead(p, name, s, crossing):
    """A thin wall across the fuselage at s with a torn rim, holed clear of every object in crossing that runs
    through it. A hole is the grown convex hull of that object's section inside the skin, kept to a few points: the
    wall is seen at a break, not inspected."""
    b = INTERNALS["bulkheads"]
    ring = ring_at(p, s, b["inset"], count=b["points"])
    cx = sum(v.x for v in ring) / len(ring)
    cz = sum(v.z for v in ring) / len(ring)
    rim = [v - Vector((v.x - cx, 0.0, v.z - cz)).normalized() * b["tear_depth"] * b["tear"][k % len(b["tear"])]
           for k, v in enumerate(ring)]
    half = Vector((0.0, b["thickness"] / 2, 0.0))
    wall = outward(bi.loft(name, [[v - half for v in rim], [v + half for v in rim]], cap_back=True, cap_front=True))
    skin = [(v.x, v.z) for v in ring_at(p, s, 0.01)]
    cutters = []
    for obj in crossing:
        hull = hull_2d([q for q in section_points(obj, s) if inside(q, skin)])
        if len(hull) < 3:
            continue
        if len(hull) > b["hole_points"]:
            hull = hull_2d(resample_outline(hull, b["hole_points"]))
        hole = grown_hull(hull, b["clearance"])
        cutters.append(outward(bi.loft(obj.name + "_hole", [[bi.P(s + d, x, z) for x, z in hole] for d in (-0.1, 0.1)],
                                       cap_back=True, cap_front=True)))
    if cutters:
        subtract(wall, cutters)
        for c in cutters:
            bpy.data.objects.remove(c, do_unlink=True)
    bm = bmesh.new()  # as for the tanks: no boolean n-gons
    bm.from_mesh(wall.data)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(wall.data)
    bm.free()
    if not wall.data.polygons:
        raise ValueError("%s: nothing left of the wall at station %.2f" % (name, s))
    return wall


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
    # Compartments are boxes clipped to a solid just inside the skin, so none can show through it. Ahead of the intakes
    # the section is convex, so a coarse solid stays inside the skin; the main bays, by the intake fillets, clip to
    # the skin's own ring.
    inner = inner_solid(p, I["compartment_inset"], 0.25, 5.35, step=0.25, count=48)
    r = I["radar"]
    nose = bi.blended_ring(p, r["dish_s"])
    cz = (max(v.z for v in nose) + min(v.z for v in nose)) / 2
    dish_r = min(r["dish_r"], min((v - bi.P(r["dish_s"], 0.0, cz)).length for v in nose) - I["compartment_inset"] - 0.02)
    dish = cylinder_loft("radar_dish", [(r["dish_s"], 0.0, cz, dish_r), (r["dish_s"] + 0.04, 0.0, cz, dish_r)])
    parts.append(tag(bi.finish(clip_to(dish, inner), mats["avionics"], smooth=False), "radar", "fuselage", r["mass_kg"] * 0.4))
    unit = box("radar_unit", r["dish_s"] + 0.08, r["s"][1], 0.20, -0.15, 0.22)
    parts.append(tag(bi.finish(clip_to(unit, inner), mats["avionics"], smooth=False), "radar", "fuselage", r["mass_kg"] * 0.6))

    for name, role in (("avionics_nose", "avionics"), ("cockpit_tub", "cockpit"), ("avionics_aft", "avionics"),
                       ("nose_gear_bay", "gear_bay")):
        s0, s1, hw, z0, z1 = I[name]["box"]
        obj = bi.finish(clip_to(box(name, s0, s1, hw, z0, z1), inner), mats[role], smooth=False)
        parts.append(tag(obj, role, "fuselage", I[name]["mass_kg"]))
    bpy.data.objects.remove(inner, do_unlink=True)
    mg = I["main_gear_bay"]
    inner = inner_solid(p, I["compartment_inset"], mg["box"][0] - 0.15, mg["box"][1] + 0.15, step=0.15)
    for side, suffix in ((1, "_L"), (-1, "_R")):
        s0, s1, hw, z0, z1 = mg["box"]
        obj = clip_to(box("main_gear_bay" + suffix, s0, s1, hw, z0, z1, x=side * mg["x"]), inner)
        parts.append(tag(bi.finish(obj, mats["gear_bay"], smooth=False), "gear_bay", "fuselage"))
    bpy.data.objects.remove(inner, do_unlink=True)

    cutters = duct_cutter(p, I["duct_clearance"])
    wing_cut = [grown(bpy.data.objects[n], 0.015) for n in ("wing_L", "wing_R")]  # wing roots buried in the body
    for name in ("fuel_aux", "fuel_forward_main", "fuel_aft_center", "fuel_aft_L", "fuel_aft_R"):
        s0, s1, inset, floor, x_lo, x_hi = I[name]["tank"]
        obj = tank(p, name, s0, s1, inset, floor, x_lo, x_hi, mats["fuel_tank"], cutters + wing_cut)
        parts.append(tag(obj, "fuel_tank", "fuselage"))
    for c in cutters + wing_cut:
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

    fr = I["frames"]
    s = fr["s0"]
    k = 0
    while s <= fr["s1"] + 1e-9:
        skin = bi.skin_ring(p, s)  # pulled whole, about the same centre as the stringers
        n = len(skin)
        line = pulled(skin, fr["inset"]) + [pulled(skin, fr["inset"])[0]]
        needed = simplified(line, 0, n // 2, fr["tolerance"]) | simplified(line, n // 2, n, fr["tolerance"])
        columns = sorted({c % n for c in needed} | set(range(0, n, I["stringers"]["column_step"])))
        outer, web, inner = ([ring[c] for c in columns] for ring in
                             (pulled(skin, fr["inset"] + d) for d in (0.0, fr["thickness"], fr["web"])))
        aft = lambda ring, dy: [v + Vector((0, dy, 0)) for v in ring]
        # the L section, round from the flange's skin face: flange, its edge, the web's aft face, the web's inner
        # edge, its front face back to the skin; the last ring closes it
        rings = [outer, aft(outer, fr["flange"]), aft(web, fr["flange"]), aft(web, fr["thickness"]),
                 aft(inner, fr["thickness"]), inner, outer]
        obj = bi.finish(bi.loft("frame_%02d" % k, rings), mats["frame"], smooth=False)
        parts.append(tag(obj, "structure", "fuselage", fr["mass_kg_each"]))
        s += fr["pitch"]
        k += 1

    sp = I["spars"]
    for side, suffix in ((1, "_L"), (-1, "_R")):
        pieces = []
        x0, x1 = 0.62, wing[-1][1] - 0.06
        for name, f in (("spar_front", sp["front_f"]), ("spar_rear", sp["rear_f"])):
            stations = [(u, f - 0.006, f + 0.006) for u in bi.span_stations(wing, "x", x0, x1)]
            pieces.append(bi.strip(name + suffix, wing, stations, p["wing"]["thickness"] * 0.9, "x"))
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

    bh = I["bulkheads"]
    # Everything built so far that may run through a wall, less the skin and the fin, whose root organise trims
    # back to the skin.
    crossing = [o for o in list(bpy.data.collections["Icarus"].objects) + list(bi.TARGET.objects)
                if o.type == "MESH" and o.name not in ("fuselage", "fin") and not o.name.startswith("frame_")]
    for s in bh["at"]:
        wall = bulkhead(p, "bulkhead_%05.2f" % s, s, crossing)
        parts.append(tag(bi.finish(wall, mats["frame"], smooth=False), "structure", "fuselage"))
    for obj in stringers(p):
        parts.append(tag(bi.finish(obj, mats["frame"], smooth=False), "structure", "fuselage"))
    return parts


def stringers(p):
    """INTERNALS["stringers"]: each a box section along its skin column, one object per run."""
    st, inset = INTERNALS["stringers"], INTERNALS["frames"]["inset"]
    skin_stations = bi.fuselage_stations(p)
    rings = {}

    def ring(s):
        if s not in rings:
            rings[s] = bi.skin_ring(p, s)
        return rings[s]

    out = []
    for run, (s0, s1) in enumerate(st["runs"]):
        stations = [s0] + [s for s in skin_stations if s0 < s < s1] + [s1]
        for c in range(0, bi.RING, st["column_step"]):
            width, depth = st["longeron_size"] if c in st["longerons"] else st["size"]
            line = [pulled(ring(s), inset)[c] for s in stations]
            keep = sorted(simplified(line, 0, len(line) - 1, st["tolerance"]) | {0, len(line) - 1})
            sections = []
            for i in keep:
                skin = ring(stations[i])
                side = (skin[(c + 1) % bi.RING] - skin[c - 1]).normalized() * (width / 2)
                face, back = pulled(skin, inset)[c], pulled(skin, inset + depth)[c]
                sections.append([face - side, face + side, back + side, back - side])
            out.append(bi.loft("stringer_%02d_%d" % (c, run), sections, cap_back=True, cap_front=True))
    return out


def simplified(line, i, j, tolerance):
    """The indices between i and j that a polyline needs to stay within tolerance of line (Douglas-Peucker)."""
    a, b = line[i], line[j]
    far, at = 0.0, None
    for k in range(i + 1, j):
        t = max(0.0, min(1.0, (line[k] - a).dot(b - a) / max((b - a).length_squared, 1e-12)))
        d = (line[k] - a.lerp(b, t)).length
        if d > far:
            far, at = d, k
    if at is None or far <= tolerance:
        return set()
    return {at} | simplified(line, i, at, tolerance) | simplified(line, at, j, tolerance)
