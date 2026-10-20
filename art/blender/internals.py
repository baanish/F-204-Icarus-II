"""Internal parts of the F-240 Icarus II: what a Full Fidelity damage model reveals under the skin.

Built into the "Internals" collection by build_icarus.build(). Each object carries custom properties the Unity author
reads: role (fuel_tank, engine, structure, avionics, radar, cockpit, gear_bay), owner (the external part it sits in),
mass_kg (dry), and for tanks volume_m3. The layout follows the F-104's: radar in the nose, the cockpit, bladder tanks
in the fuselage above the intake ducts, the engine from the duct exit to the nozzle, gear retracting into the
fuselage, no gun in this variant (its bay holds avionics). The strake tanks are the Icarus's own.
"""
import math

import bpy
from mathutils import Vector

import build_icarus as bi

FUEL_DENSITY = 0.80  # kg per litre, JP-8

INTERNALS = {
    "radar": {"s": (0.30, 1.55), "dish_s": 0.95, "dish_r": 0.30, "mass_kg": 120},
    "avionics_nose": {"box": (1.55, 2.30, 0.30, -0.25, 0.42), "mass_kg": 90},  # s0, s1, half width, z0, z1
    "cockpit_tub": {"box": (2.35, 4.90, 0.38, -0.05, 0.78), "mass_kg": 260},
    "avionics_aft": {"box": (4.95, 5.60, 0.42, -0.30, 0.70), "mass_kg": 140},  # the F-104's gun bay
    # Fuel: (s0, s1, inset from the skin, z floor). A tank fills the skin section above its floor.
    "fuel_fwd": {"tank": (5.65, 6.80, 0.05, -0.38)},
    "fuel_mid": {"tank": (6.85, 8.40, 0.05, 0.40)},  # wraps down around the tops of the ducts
    "fuel_aft": {"tank": (8.45, 9.55, 0.05, 0.40)},
    "fuel_saddle": {"tank": (9.60, 12.40, 0.05, 0.80)},  # over the engine, under the spine
    "strake_tank": {"x": (1.00, 1.88), "f": (0.06, 0.80)},  # in each strake: span and chord fraction range
    "engine": {"face_s": 9.70, "core_end_s": 13.10, "radius": 0.46, "ab_radius": 0.40, "end_s": 15.00,
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


def ring_at(p, s, inset, floor=None):
    """The skin section at s pulled inward by inset, optionally cut flat at z = floor."""
    ring = bi.blended_ring(p, s)
    cx = 0.0
    cz = sum(v.z for v in ring) / len(ring)
    out = []
    for v in ring:
        d = Vector((v.x - cx, 0.0, v.z - cz))
        w = v - d.normalized() * inset if d.length > inset else Vector((cx, v.y, cz))
        if floor is not None and w.z < floor:
            w = Vector((w.x, w.y, floor))
        out.append(w)
    return out


def section_area(ring):
    """Area of a ring's polygon in the x-z plane (shoelace)."""
    a = 0.0
    for p0, p1 in zip(ring, ring[1:] + ring[:1]):
        a += p0.x * p1.z - p1.x * p0.z
    return abs(a) / 2


def tank(p, name, s0, s1, inset, floor, mat):
    stations = [s0 + (s1 - s0) * i / 8 for i in range(9)]
    rings = [ring_at(p, s, inset, floor) for s in stations]
    vol = sum(0.5 * (section_area(a) + section_area(b)) * (sb - sa)
              for a, b, sa, sb in zip(rings, rings[1:], stations, stations[1:]))
    obj = bi.finish(bi.loft(name, rings, cap_back=True, cap_front=True), mat, smooth=False)
    obj["volume_m3"] = round(vol, 3)
    obj["fuel_kg"] = round(vol * 1000 * FUEL_DENSITY, 1)
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
    r = I["radar"]
    dish = cylinder_loft("radar_dish", [(r["dish_s"], 0.0, 0.03, r["dish_r"]), (r["dish_s"] + 0.04, 0.0, 0.03, r["dish_r"])])
    parts.append(tag(bi.finish(dish, mats["avionics"], smooth=False), "radar", "fuselage", r["mass_kg"] * 0.4))
    unit = box("radar_unit", r["dish_s"] + 0.08, r["s"][1], 0.20, -0.15, 0.22)
    parts.append(tag(bi.finish(unit, mats["avionics"], smooth=False), "radar", "fuselage", r["mass_kg"] * 0.6))

    for name, role in (("avionics_nose", "avionics"), ("cockpit_tub", "cockpit"), ("avionics_aft", "avionics"),
                       ("nose_gear_bay", "gear_bay")):
        s0, s1, hw, z0, z1 = I[name]["box"]
        obj = bi.finish(box(name, s0, s1, hw, z0, z1), mats[role], smooth=False)
        parts.append(tag(obj, role, "fuselage", I[name]["mass_kg"]))
    mg = I["main_gear_bay"]
    for side, suffix in ((1, "_L"), (-1, "_R")):
        s0, s1, hw, z0, z1 = mg["box"]
        obj = bi.finish(box("main_gear_bay" + suffix, s0, s1, hw, z0, z1, x=side * mg["x"]), mats["gear_bay"], smooth=False)
        parts.append(tag(obj, "gear_bay", "fuselage"))

    for name in ("fuel_fwd", "fuel_mid", "fuel_aft", "fuel_saddle"):
        s0, s1, inset, floor = I[name]["tank"]
        obj = tank(p, name, s0, s1, inset, floor, mats["fuel_tank"])
        parts.append(tag(obj, "fuel_tank", "fuselage"))
    st = I["strake_tank"]
    wing = bi.wing_sections(p["wing"])
    for side, suffix in ((1, "_L"), (-1, "_R")):
        stations = [(st["x"][0] + (st["x"][1] - st["x"][0]) * i / 6, st["f"][0], st["f"][1]) for i in range(7)]
        obj = bi.strip("strake_tank" + suffix, wing, stations, p["wing"]["thickness"] * 0.85, "x")
        if side < 0:
            obj.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
            obj.data.flip_normals()
        bi.finish(obj, mats["fuel_tank"], smooth=False)
        # volume: chord span strip of a biconvex section, 0.85 of the skin thickness, between the fractions
        vol = 0.0
        for (u0, _, _), (u1, _, _) in zip(stations, stations[1:]):
            c = bi.section_at(wing, 0.5 * (u0 + u1), "x")[3]
            f0, f1 = st["f"]
            # integral of 2 * 2t(1-t) * thickness * chord over t in [f0, f1], times chord, times span
            integ = 4 * ((f1 ** 2 / 2 - f1 ** 3 / 3) - (f0 ** 2 / 2 - f0 ** 3 / 3))
            vol += integ * p["wing"]["thickness"] * 0.85 * c * c * (u1 - u0)
        obj["volume_m3"] = round(vol, 3)
        obj["fuel_kg"] = round(vol * 1000 * FUEL_DENSITY, 1)
        parts.append(tag(obj, "fuel_tank", "wing" + suffix))

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
