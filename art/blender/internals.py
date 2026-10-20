"""Internal parts of the F-240 Icarus II: what a Full Fidelity damage model reveals under the skin.

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
    "avionics_aft": {"box": (4.95, 5.15, 0.42, -0.30, 0.70), "mass_kg": 140},  # a shelf; the gun bay holds fuel
    # Fuel, after the F-104S layout: an auxiliary cell in the old gun bay (as on the gunless F-104), the forward
    # main tank, three connected aft cells (the centre one between the intake ducts, the side ones wrapping round
    # them), and cells in the strakes and outboard wings. No fuel over or around the engine: a leak there is a fire. Each fuselage row: (s0, s1,
    # inset from the skin, z floor, x from, x to). A cell fills the skin section above its floor between its x
    # limits, minus the ducts with clearance. The design load is spread over the cells by what each holds.
    "design_fuel_kg": 2400,
    "duct_clearance": 0.025,  # duct wall plus gap between a fuel cell and an intake duct
    "fuel_aux": {"tank": (5.20, 5.90, 0.04, -0.30, -9.0, 9.0)},
    "fuel_forward_main": {"tank": (5.95, 7.70, 0.04, 0.05, -9.0, 9.0)},
    "fuel_aft_center": {"tank": (7.75, 9.30, 0.04, -0.32, -0.24, 0.24)},
    "fuel_aft_L": {"tank": (7.75, 9.30, 0.04, -0.15, 0.26, 0.92)},  # outboard of 0.92 is the strake cell
    "fuel_aft_R": {"tank": (7.75, 9.30, 0.04, -0.15, -0.92, -0.26)},
    "strake_tank": {"x": (1.10, 1.88), "f": (0.06, 0.70)},  # each strake: span and chord fraction, ahead of the flap
    "wing_tank": {"x": (1.95, 3.05), "f": (0.17, 0.68)},  # the box between the spars, outboard of the crank
    "engine": {"face_s": 9.70, "core_end_s": 13.10, "radius": 0.46, "ab_radius": 0.36, "end_s": 15.00,
               "z0": 0.31, "z1": 0.37, "mass_kg": 1450},
    "frames": {"s0": 1.6, "s1": 14.8, "pitch": 0.6, "inset": 0.03, "depth": 0.05, "mass_kg_each": 9},
    "spars": {"front_f": 0.15, "rear_f": 0.70, "rib_pitch": 0.45, "mass_kg_side": 140},
    "nose_gear_bay": {"box": (2.55, 4.05, 0.17, -0.48, -0.06), "mass_kg": 0},
    "main_gear_bay": {"box": (9.35, 11.15, 0.20, -0.42, -0.04), "x": 0.36, "mass_kg": 0},
}


def box(name, s0, s1, hw, z0, z1, x=0.0):
    v = [bi.P(s, x + sx * hw, z) for s in (s0, s1) for sx in (-1, 1) for z in (z0, z1)]
    # index = s*4 + side*2 + z
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return bi.mesh_object(name, v, faces)


def ring_at(p, s, inset, floor=None, x_lo=None, x_hi=None, count=None):
    """The skin section at s pulled inward by inset. With floor or x limits, the section is clipped to z >= floor
    and x_lo <= x <= x_hi (a true polygon cut, so the result never leaves the skin) and resampled to count points
    evenly round its outline, so neighbouring sections loft cleanly."""
    ring = bi.blended_ring(p, s)
    cz = sum(v.z for v in ring) / len(ring)
    out = []
    for v in ring:
        d = Vector((v.x, 0.0, v.z - cz))
        out.append(v - d.normalized() * inset if d.length > inset else Vector((0.0, v.y, cz)))
    if floor is None and x_lo is None:
        return out
    y = out[0].y
    pts = [(v.x, v.z) for v in out]
    if floor is not None:
        pts = clip(pts, lambda q: q[1] - floor)
    if x_lo is not None:
        pts = clip(pts, lambda q: q[0] - x_lo)
        pts = clip(pts, lambda q: x_hi - q[0])
    return [Vector((x, y, z)) for x, z in resample_outline(pts, count or len(ring) // 2)]


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
    rows = bi.resample(p["duct"], bi.spaced(p["duct"][0][0] - 0.3, p["duct"][-1][0] + 0.3, 20))
    cutters = []
    for side in (1, -1):
        rings = [[bi.P(s, side * (cx + (r + clearance) * math.cos(a)), cz + (r + clearance) * math.sin(a))
                  for a in [2 * math.pi * k / 48 for k in range(48)]] for s, cx, cz, r in rows]
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


def inner_solid(p, inset, s0=0.25, s1=15.15):
    """A closed solid just inside the fuselage skin, to clip compartments to."""
    n = int(round((s1 - s0) / 0.05)) + 1
    rings = [ring_at(p, s0 + (s1 - s0) * i / (n - 1), inset) for i in range(n)]
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


def mesh_volume(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    v = abs(bm.calc_volume())
    bm.free()
    return v


def tank(p, name, s0, s1, inset, floor, x_lo, x_hi, mat, cutters):
    # Stations every 0.1 m, plus either side of the intake lip, where the skin changes fastest: a coarser cell
    # bridges straight across a quick change in the skin and pokes through it.
    n = max(2, int(round((s1 - s0) / 0.1)) + 1)
    lip = p["intake"][0][0]
    stations = sorted({round(s0 + (s1 - s0) * i / (n - 1), 4) for i in range(n)}
                      | {x for x in (lip - 0.02, lip + 0.06) if s0 < x < s1})  # clear of the skin's step at the lip
    rings = [ring_at(p, s, inset, floor, x_lo, x_hi, count=64) for s in stations]
    obj = bi.finish(outward(bi.loft(name, rings, cap_back=True, cap_front=True)), mat, smooth=False)
    subtract(obj, cutters)  # the cells are separate from the intake ducts, with clearance for the duct walls
    vol = mesh_volume(obj)
    obj["volume_m3"] = round(vol, 3)
    obj["volume_holds_kg"] = round(vol * 1000 * FUEL_DENSITY, 1)
    return obj


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
    # Compartments are boxes clipped to a solid just inside the skin, so none can show through it.
    inner = inner_solid(p, I["compartment_inset"])
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
    mg = I["main_gear_bay"]
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
        stations = [(st["x"][0] + (st["x"][1] - st["x"][0]) * i / 6, st["f"][0], st["f"][1]) for i in range(7)]
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
        outer = ring_at(p, s, fr["inset"])
        inner = ring_at(p, s, fr["inset"] + fr["depth"])
        aft = Vector((0, 0.025, 0))
        # outer band, aft face, inner band, front face: the fifth ring closes the frame's cross-section
        rings = [outer, [v + aft for v in outer], [v + aft for v in inner], inner, outer]
        obj = bi.finish(bi.loft("frame_%02d" % k, rings), mats["structure"], smooth=False)
        parts.append(tag(obj, "structure", "fuselage", fr["mass_kg_each"]))
        s += fr["pitch"]
        k += 1

    sp = I["spars"]
    for side, suffix in ((1, "_L"), (-1, "_R")):
        pieces = []
        x0, x1 = 0.62, wing[-1][1] - 0.06
        for name, f in (("spar_front", sp["front_f"]), ("spar_rear", sp["rear_f"])):
            stations = [(x0 + (x1 - x0) * i / 10, f - 0.006, f + 0.006) for i in range(11)]
            pieces.append(bi.strip(name + suffix, wing, stations, p["wing"]["thickness"] * 0.9, "x"))
        n_ribs = int((x1 - x0) / sp["rib_pitch"]) + 1
        for i in range(n_ribs):
            u = x0 + i * (x1 - x0) / (n_ribs - 1)
            stations = [(u - 0.006, sp["front_f"], sp["rear_f"]), (u + 0.006, sp["front_f"], sp["rear_f"])]
            pieces.append(bi.strip("rib_%02d%s" % (i, suffix), wing, stations, p["wing"]["thickness"] * 0.9, "x"))
        for obj in pieces:
            if side < 0:
                obj.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
                obj.data.flip_normals()
            bi.finish(obj, mats["structure"], smooth=False)
            parts.append(tag(obj, "structure", "wing" + suffix, sp["mass_kg_side"] / len(pieces)))
    return parts
