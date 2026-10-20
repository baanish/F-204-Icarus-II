"""Organise the built geometry into the aircraft's damageable parts.

Nuclear Option damages an aircraft part by part: each part is a separate body with its own colliders, hit points and
joint to its parent, and what a hit or a detachment reveals is whatever geometry lies under it. So the exterior skin is
split into thin panels that can come away, the frames, spars and tanks they cover are parts of their own, and the
Blender parent tree is the part tree the Unity author builds. Names, parents and dry masses follow the Full Fidelity
plan in the project notes (41 parts, 5,800 kg dry); the stabilator is two pivoting halves.
"""
import bmesh
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi

# part name -> (parent, dry mass kg). Hinged surfaces are listed by their hinge name.
TREE = {
    "fuselage_mid": (None, 910),
    "fuselage_forward": ("fuselage_mid", 500),
    "cockpit_cell": ("fuselage_forward", 480),
    "radome": ("cockpit_cell", 35),
    "radar_tray": ("cockpit_cell", 65),
    "avionics_tray": ("fuselage_forward", 100),
    "canopy": ("cockpit_cell", 60),
    "fuselage_aft": ("fuselage_mid", 400),
    "engine_core": ("fuselage_aft", 1150),
    "nozzle": ("engine_core", 130),
    "intake_duct_L": ("fuselage_mid", 100),
    "intake_duct_R": ("fuselage_mid", 100),
    "wing_spar_L": ("fuselage_mid", 230),
    "wing_spar_R": ("fuselage_mid", 230),
    "wing_skin_L": ("wing_spar_L", 60),
    "wing_skin_R": ("wing_spar_R", 60),
    "aileron_L": ("wing_spar_L", 35),
    "aileron_R": ("wing_spar_R", 35),
    "flap_L": ("wing_spar_L", 45),
    "flap_R": ("wing_spar_R", 45),
    "lef_L": ("wing_spar_L", 30),
    "lef_R": ("wing_spar_R", 30),
    "fin_spar": ("fuselage_aft", 100),
    "fin_skin": ("fin_spar", 35),
    "rudder": ("fin_spar", 30),
    "stabilator_L": ("fin_spar", 60),
    "stabilator_R": ("fin_spar", 60),
    "gear_leg_N": ("cockpit_cell", 75),
    "gear_leg_L": ("fuselage_mid", 100),
    "gear_leg_R": ("fuselage_mid", 100),
    "fuel_aux": ("fuselage_forward", 15),
    "fuel_forward_main": ("fuselage_mid", 35),
    "fuel_aft_center": ("fuselage_mid", 30),
    "fuel_aft_L": ("fuselage_mid", 20),
    "fuel_aft_R": ("fuselage_mid", 20),
    "fuel_saddle": ("fuselage_aft", 0),  # cells beyond the 41-part plan; their dry mass is in their hosts
    "fuel_strake_L": ("wing_spar_L", 0),
    "fuel_strake_R": ("wing_spar_R", 0),
    "fuel_wing_L": ("wing_spar_L", 0),
    "fuel_wing_R": ("wing_spar_R", 0),
    "skin_forward_L": ("fuselage_forward", 35),
    "skin_forward_R": ("fuselage_forward", 35),
    "skin_mid_L": ("fuselage_mid", 45),
    "skin_mid_R": ("fuselage_mid", 45),
    "skin_aft_L": ("fuselage_aft", 45),
    "skin_aft_R": ("fuselage_aft", 45),
    "dorsal_cover": ("fuselage_mid", 40),
    # Not in the 41: small parts the plan folds into their parents' budgets.
    "speed_brake_L": ("fuselage_aft", 0),
    "speed_brake_R": ("fuselage_aft", 0),
    "ventral_fin": ("fuselage_aft", 0),
}

ROLE = {"fuel_": "fuel_tank", "skin_": "skin", "dorsal": "skin", "wing_skin": "skin", "fin_skin": "skin",
        "radome": "skin", "engine": "engine", "nozzle": "engine", "gear_": "gear", "cockpit": "cockpit",
        "canopy": "canopy", "radar": "radar", "avionics": "avionics", "intake": "intake"}

# Fuselage skin panels by station: radome ahead of RADOME_END, then forward, mid and aft panels per side; the
# dorsal cover is the spine strip between DORSAL s range above DORSAL_Z.
RADOME_END, FORWARD_END, MID_END = 1.6, 5.6, 11.0
DORSAL = (5.0, 12.4)
DORSAL_Z, DORSAL_HALF_WIDTH = 0.80, 0.30


def station(v):
    return v.y + bi.S0


def subset(name, source, keep_face):
    """A new object holding the faces of source for which keep_face(center) is true."""
    me = source.data.copy()
    bm = bmesh.new()
    bm.from_mesh(me)
    drop = [f for f in bm.faces if not keep_face(source.matrix_world @ f.calc_center_median())]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.name = name
    obj = bpy.data.objects.new(name, me)
    obj.matrix_world = source.matrix_world.copy()
    bi.TARGET.objects.link(obj)
    return obj


def join(name, objs):
    """One object from several, world positions and per-face materials kept."""
    bm = bmesh.new()
    mats = []
    for o in objs:
        m = o.data.copy()
        m.transform(o.matrix_world)
        before = len(bm.faces)
        bm.from_mesh(m)
        bm.faces.ensure_lookup_table()
        remap = []
        for mat in m.materials:
            if mat not in mats:
                mats.append(mat)
            remap.append(mats.index(mat))
        for f in bm.faces[before:]:
            f.material_index = remap[f.material_index] if remap else 0
        bpy.data.meshes.remove(m)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for mat in mats:
        me.materials.append(mat)
    for o in objs:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    obj = bpy.data.objects.new(name, me)
    bi.TARGET.objects.link(obj)
    return obj


def rename(obj, name):
    obj.name = name
    obj.data.name = name
    return obj


def keel(name, s0, s1, p, mat):
    """A thin keel member along the inside of the belly, so a structure core has something solid to hit."""
    rows = [(s, bi.pchip([r[0] for r in p["fuselage"]], [r[3] for r in p["fuselage"]], s)) for s in (s0, s1)]
    z0 = max(r[1] for r in rows) + 0.06
    obj = bi.mesh_object(name, [bi.P(s, x, z) for s in (s0, s1) for x in (-0.05, 0.05) for z in (z0, z0 + 0.08)],
                         [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)])
    obj.data.materials.append(mat)
    return obj


def recentre(obj):
    """Move a part's origin to its bounding-box centre, keeping the geometry where it is."""
    if obj.type != "MESH" or not obj.data.vertices:
        return
    lo = Vector([min(v.co[i] for v in obj.data.vertices) for i in range(3)])
    hi = Vector([max(v.co[i] for v in obj.data.vertices) for i in range(3)])
    c = (lo + hi) / 2
    obj.data.transform(Matrix.Translation(-c))
    obj.matrix_world = obj.matrix_world @ Matrix.Translation(c)


def organise(p, icarus, internals, structure_mat):
    """Turn the built exterior and internals into the part tree. Returns the parts by name."""
    prev, bi.TARGET = bi.TARGET, icarus
    try:
        return _organise(p, icarus, internals, structure_mat)
    finally:
        bi.TARGET = prev


def _organise(p, icarus, internals, structure_mat):
    O = bpy.data.objects
    for o in list(internals.objects):  # every internal part becomes an aircraft part or folds into one
        internals.objects.unlink(o)
        icarus.objects.link(o)

    fus = O["fuselage"]
    side = lambda c: "L" if c.x >= 0 else "R"
    dorsal = lambda c: DORSAL[0] <= station(c) <= DORSAL[1] and c.z > DORSAL_Z and abs(c.x) < DORSAL_HALF_WIDTH
    radome = subset("radome_skin", fus, lambda c: station(c) < RADOME_END)
    join("radome", [radome, O["probe"]])
    subset("dorsal_cover", fus, dorsal)
    for name, a, b in (("skin_forward", RADOME_END, FORWARD_END), ("skin_mid", FORWARD_END, MID_END),
                       ("skin_aft", MID_END, 99.0)):
        for sd in ("L", "R"):
            subset("%s_%s" % (name, sd), fus,
                   lambda c, a=a, b=b, sd=sd: a <= station(c) < b and side(c) == sd and not dorsal(c))
    bpy.data.objects.remove(fus, do_unlink=True)

    for name, a, b in (("fuselage_forward", 0.0, FORWARD_END), ("fuselage_mid", FORWARD_END, MID_END),
                       ("fuselage_aft", MID_END, 99.0)):
        frames = [o for o in icarus.objects if o.name.startswith("frame_")]  # joined frames are gone
        members = [f for f in frames if a <= station(f.matrix_world @ f.data.vertices[0].co) < b]
        members.append(keel(name + "_keel", max(a, 1.7), min(b, 15.0), p, structure_mat))
        join(name, members)

    rename(O["cockpit_tub"], "cockpit_cell")
    join("radar_tray", [O["radar_dish"], O["radar_unit"], O["avionics_nose"]])
    rename(O["avionics_aft"], "avionics_tray")
    join("engine_core", [O["engine_core"], O["engine_afterburner"]])
    rename(O["nozzle_shroud"], "nozzle")
    for sd in ("L", "R"):
        join("intake_duct_" + sd, [O["duct_" + sd], O["shock_cone_" + sd], O["shock_cone_%s_bleed" % sd]])
        spar = [o for o in icarus.objects if o.name.startswith(("spar_front_" + sd, "spar_rear_" + sd))
                or (o.name.startswith("rib_") and o.name.endswith("_" + sd))]
        join("wing_spar_" + sd, spar)
        rename(O["wing_" + sd], "wing_skin_" + sd)
    rename(O["nose_gear_bay"], "gear_leg_N")
    rename(O["main_gear_bay_L"], "gear_leg_L")
    rename(O["main_gear_bay_R"], "gear_leg_R")
    rename(O["fin"], "fin_skin")
    fin = p["fin"]["sections"]
    spar_stations = [(fin[0][2] + 0.25 + (fin[-1][2] - fin[0][2] - 0.35) * i / 8, 0.30, 0.34) for i in range(9)]
    fin_spar = bi.strip("fin_spar", fin, spar_stations, p["fin"]["thickness"] * 0.9, "z")
    fin_spar.data.materials.append(structure_mat)

    parts = {}
    for name, (parent, mass) in TREE.items():
        obj = O.get(name)
        if obj is None:
            raise ValueError("part %s was not built" % name)
        parts[name] = obj
    for name, obj in parts.items():
        if obj.type == "MESH":
            recentre(obj)
    for name, (parent, mass) in TREE.items():
        obj = parts[name]
        role = next((r for k, r in ROLE.items() if name.startswith(k)), "structure")
        target = obj if obj.type == "MESH" else O[name + "_visible"]
        target["role"] = role
        target["mass_kg"] = mass
        if parent:
            world = obj.matrix_world.copy()
            obj.parent = parts[parent]
            obj.matrix_world = world
    nozzle_vector = O["nozzle_vector"]
    world = nozzle_vector.matrix_world.copy()
    nozzle_vector.parent = parts["nozzle"]
    nozzle_vector.matrix_world = world
    leftover = [o.name for o in icarus.objects if o.parent is None and o.name not in TREE]
    if leftover:
        raise ValueError("objects outside the part tree: %s" % ", ".join(sorted(leftover)))
    return parts
