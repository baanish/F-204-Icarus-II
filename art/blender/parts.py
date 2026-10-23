"""Organise the built geometry into the aircraft's damageable parts.

Nuclear Option damages an aircraft part by part: each part is a separate body with its own colliders, hit points and
joint to its parent, and what a hit or a detachment reveals is whatever geometry lies under it. So the exterior skin is
split into thin panels that can come away, the frames, spars and tanks they cover are parts of their own, and the
Blender parent tree is the part tree the Unity author builds. Names, parents and dry masses follow the Full Fidelity
plan in the project notes (5,800 kg dry), except that the stabilator is one all-moving piece where the plan has two
halves, so 40 parts where it has 41.

Detail a package builds as its own object tagged merge_into = "<part>" joins that part's mesh (merge_details), so it
takes the part's livery and damage without a renderer of its own.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import build_icarus as bi
import canopy
import checks
import internals as interior
import lights
import stations

SKIN = "Icarus_Body"
# Triangles per component: target and cap (budget.py sums them). Caps are ceilings; the references sit lower.
BUDGET = {
    "fuselage_skin": {"target": 20000, "cap": 20000, "objects": ("radome", "skin_", "dorsal_cover")},
    "wing_box_L": {"target": 2000, "cap": 2000, "objects": ("wing_skin_L",)},
    "wing_box_R": {"target": 2000, "cap": 2000, "objects": ("wing_skin_R",)},
    **{surface: {"target": 400, "cap": 400, "objects": (surface + "_visible",)}
       for surface in ("lef_L", "lef_R", "flap_L", "flap_R", "aileron_L", "aileron_R", "rudder")},
    "stabilator": {"target": 2120, "cap": 2120, "objects": ("stabilator_visible",)},
    "fins": {"target": 1600, "cap": 1600, "objects": ("fin_skin", "ventral_fin")},
    "speed_brake_L": {"target": 480, "cap": 480, "objects": ("speed_brake_L_visible",)},
    "speed_brake_R": {"target": 480, "cap": 480, "objects": ("speed_brake_R_visible",)},
    "structure_cores": {"target": 11000, "cap": 11000, "objects": ("fuselage_forward", "fuselage_mid", "fuselage_aft")},
    "wing_spars": {"target": 3000, "cap": 3000, "objects": ("wing_spar_",)},
    "fuel_cells": {"target": 5000, "cap": 5000, "objects": ("fuel_",)},
    "engine": {"target": 1500, "cap": 1500, "objects": ("engine_core",)},
    "radar_avionics_cockpit": {"target": 1500, "cap": 1500, "objects": ("radar_tray", "avionics_tray", "cockpit_cell")},
}
# Review close-ups: name -> (camera location, look-at point), Blender axes.
CLOSEUPS = {
    "nose": (Vector((1.6, -10.6, 0.6)), Vector((0.0, -7.3, 0.05))),
    "wing_box": (Vector((3.4, 0.4, 4.6)), Vector((2.1, 2.2, 0.0))),
    "fin_tip_side": (Vector((4.0, 7.2, 3.0)), Vector((0.0, 7.2, 2.75))),
    "fin_tip_rear": (Vector((1.2, 12.5, 3.4)), Vector((0.0, 7.3, 2.8))),
}

# part name -> (parent, dry mass kg). Hinged surfaces are listed by their hinge name. The canopy, light and station
# modules list their own parts (organise merges their TREEs).
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
    "stabilator": ("fin_spar", 120),
    "gear_leg_N": ("cockpit_cell", 75),
    "gear_leg_L": ("fuselage_mid", 100),
    "gear_leg_R": ("fuselage_mid", 100),
    "fuel_aux": ("fuselage_forward", 15),
    "fuel_forward_main": ("fuselage_mid", 35),
    "fuel_aft_center": ("fuselage_mid", 30),
    "fuel_aft_L": ("fuselage_mid", 20),
    "fuel_aft_R": ("fuselage_mid", 20),
    "skin_forward_L": ("fuselage_forward", 35),
    "skin_forward_R": ("fuselage_forward", 35),
    "skin_mid_L": ("fuselage_mid", 45),
    "skin_mid_R": ("fuselage_mid", 45),
    "skin_aft_L": ("fuselage_aft", 45),
    "skin_aft_R": ("fuselage_aft", 45),
    "gear_door_N_L": ("fuselage_forward", 0),
    "gear_door_N_R": ("fuselage_forward", 0),
    "gear_door_main_L": ("fuselage_mid", 0),
    "gear_door_main_R": ("fuselage_mid", 0),
    "dorsal_cover": ("fuselage_mid", 40),
    # Not in the plan's 41: small parts the plan folds into their parents' budgets.
    "speed_brake_L": ("fuselage_aft", 0),
    "speed_brake_R": ("fuselage_aft", 0),
    "ventral_fin": ("fuselage_aft", 0),
}

ROLE = {"fuel_": "fuel_tank", "skin_": "skin", "dorsal": "skin", "wing_skin": "skin", "fin_skin": "skin",
        "radome": "skin", "engine": "engine", "nozzle": "engine", "gear_": "gear", "cockpit": "cockpit",
        "canopy": "canopy", "windscreen": "canopy", "radar": "radar", "light_": "light", "antenna_": "antenna", "pylon_": "pylon", "avionics": "avionics", "intake": "intake"}

# Fuselage skin panels by station: radome ahead of RADOME_END, then forward, mid and aft panels per side; the
# dorsal cover is the spine strip between DORSAL s range above DORSAL_Z.
RADOME_END, FORWARD_END, MID_END = 1.6, 5.6, 11.0
DORSAL = (5.0, 12.4)
DORSAL_Z, DORSAL_HALF_WIDTH = 0.80, 0.30


def station(v):
    return v.y + bi.S0


def drop_inside(obj, solid):
    """Delete obj's faces whose centres lie inside the closed, outward-facing solid."""
    to_solid = solid.matrix_world.inverted() @ obj.matrix_world
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    drop = []
    for f in bm.faces:
        c = to_solid @ f.calc_center_median()
        found, at, normal, _ = solid.closest_point_on_mesh(c)
        if found and (c - at).dot(normal) < 0:
            drop.append(f)
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()


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
            if mat is not None and mat not in mats:  # empty slots would export as unnamed materials
                mats.append(mat)
            remap.append(mats.index(mat) if mat is not None else 0)
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
    """A thin keel member along the inside of the belly, so a structure core has something solid to hit. It follows
    the belly 6 cm above it, area-rule waist included, in ten straight pieces."""
    rings = []
    for i in range(11):
        s = s0 + (s1 - s0) * i / 10
        z0 = min(v.z for v in bi.blended_ring(p, s) if abs(v.x) < 0.06) + 0.06
        rings.append([bi.P(s, x, z) for x, z in ((-0.05, z0), (0.05, z0), (0.05, z0 + 0.08), (-0.05, z0 + 0.08))])
    obj = bi.loft(name, rings, cap_back=True, cap_front=True)
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


def full_tree():
    """Every part: TREE, then the parts the canopy, light and station modules list."""
    return {**TREE, **canopy.TREE, **lights.TREE, **stations.TREE}


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
    # The canopy is its own loft on top of the body, so the body's top skin ran on under it as a floor across the
    # cockpit, and the frames there closed over the pilot as full rings. The cockpit opening is whatever of the skin
    # and the frames lies inside the canopy's closed shape.
    canopy_solid = interior.outward(canopy.build_canopy(p, structure_mat))
    for obj in [fus] + [o for o in icarus.objects if o.name.startswith("frame_")]:
        drop_inside(obj, canopy_solid)
    bpy.data.objects.remove(canopy_solid, do_unlink=True)
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
        frames = [o for o in icarus.objects if o.name.startswith(("frame_", "bulkhead_"))]  # joined ones are gone
        members = [f for f in frames if a <= station(f.matrix_world @ f.data.vertices[0].co) < b]
        members.append(keel(name + "_keel", max(a, 1.7), min(b, 15.0), p, structure_mat))
        # gear wells belong to the structure they are cut into
        members += [o for o in icarus.objects if o.name.startswith(("nose_gear_bay", "main_gear_bay"))
                    and a <= station(o.matrix_world @ o.data.vertices[0].co) < b]
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
        # The wing is too thin for separate tank parts: a skin or spar hull would swallow them. As on stock
        # aircraft, the wing's fuel belongs to the wing part itself, the spar, with the bladders as its meshes.
        bladders = [O["fuel_strake_" + sd], O["fuel_wing_" + sd]]
        wing_fuel = sum(o["fuel_kg"] for o in bladders)
        spar_obj = join("wing_spar_" + sd, spar + bladders)
        spar_obj["fuel_kg"] = round(wing_fuel, 1)
        rename(O["wing_" + sd], "wing_skin_" + sd)
    rename(O["fin"], "fin_skin")
    fin = p["fin"]["sections"]
    spar_stations = [(fin[0][2] + 0.25 + (fin[-1][2] - fin[0][2] - 0.35) * i / 8, 0.30, 0.34) for i in range(9)]
    fin_spar = bi.strip("fin_spar", fin, spar_stations, p["fin"]["thickness"] * 0.9, "z")
    fin_spar.data.materials.append(structure_mat)
    # The fin sits on the fuselage: trim its buried root to the skin, so it clears the engine and nozzle in the
    # tight tail cone, and its root follows the body's top line.
    body = interior.inner_solid(p, 0.0, 11.5, 15.4, step=0.15)  # no finer than the skin's own stations
    for obj in (O["fin_skin"], fin_spar):
        interior.subtract(interior.outward(obj), [body])
    bpy.data.objects.remove(body, do_unlink=True)
    # The fin's own side area, before the fin-tip fairing joins its mesh: IcarusAuthor.Aero.cs gives the fin this
    # lifting area, and the fairing is no part of it.
    O["fin_skin"]["side_area_m2"] = round(side_area(O["fin_skin"]), 4)
    # The canopy's lower edge dips into the fuselage; keep the cockpit cell clear of it.
    solid = canopy.build_canopy(p, structure_mat)  # the closed canopy shape; the built hood and windscreen are open
    # Grown 2 cm and thinned to a fifth of its faces: the cut takes on the cutter's faceting, and the full glass mesh
    # would spend a thousand triangles of the cell on it.
    canopy_cut = interior.grown(solid, 0.02)
    canopy_cut.modifiers.new("coarse", "DECIMATE").ratio = 0.2
    interior.subtract(interior.outward(O["cockpit_cell"]), [canopy_cut])
    for o in (solid, canopy_cut):
        bpy.data.objects.remove(o, do_unlink=True)

    tree = full_tree()
    parts = {}
    for name, (parent, mass) in tree.items():
        obj = O.get(name)
        if obj is None:
            raise ValueError("part %s was not built" % name)
        parts[name] = obj
    for name, obj in parts.items():
        if obj.type == "MESH":
            recentre(obj)
    for name, (parent, mass) in tree.items():
        obj = parts[name]
        role = next((r for k, r in ROLE.items() if name.startswith(k)), "structure")
        target = O.get(name + "_visible", obj) if obj.type == "EMPTY" else obj  # lights are bare empties
        target["role"] = target.get("role", role)
        target["mass_kg"] = mass
        if parent:
            world = obj.matrix_world.copy()
            obj.parent = parts[parent]
            obj.matrix_world = world
    nozzle_vector = O["nozzle_vector"]
    world = nozzle_vector.matrix_world.copy()
    nozzle_vector.parent = parts["nozzle"]
    nozzle_vector.matrix_world = world
    # detail waiting to join its part (merge_details) is not a part of its own
    leftover = [o.name for o in icarus.objects if o.parent is None and o.name not in tree and "merge_into" not in o]
    if leftover:
        raise ValueError("objects outside the part tree: %s" % ", ".join(sorted(leftover)))
    for obj in icarus.objects:
        if obj.type == "MESH" and not obj.name.startswith("intake_duct") and obj.get("role") != "cockpit_view":
            face_outward(obj)
    return parts


def check(icarus):
    import budget

    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("parts: over the triangle caps: " + "; ".join(over))
    print(surface_sweep(icarus))


def side_area(obj):
    """Area of a mesh seen along X, as IcarusAuthor.Aero.cs SideArea measures it: every triangle projected on the
    YZ plane, both faces, halved."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    rot = obj.matrix_world.to_3x3()
    area = sum(abs((rot @ (f.verts[1].co - f.verts[0].co)).cross(rot @ (f.verts[2].co - f.verts[0].co)).x) / 2
               for f in bm.faces)
    bm.free()
    return area / 2


SWEEP_STEP = 2.5  # most degrees between two poses of the surface sweep
TWO_WAY = ("aileron", "rudder", "stabilator")  # the rest move one way: flaps and LEFs droop, speed brakes open out
# What a moving surface must not meet: the boxes and skins around it, the nozzle, and every other surface at rest.
SWEEP_FIXED = ("wing_skin_", "wing_spar_", "fin_skin", "fin_spar", "ventral_fin", "radome", "skin_", "dorsal_cover",
               "nozzle", "pylon_", "intake_duct_")


def surface_sweep(icarus):
    """Turn every hinge with a deflection_deg (flaps, LEFs, ailerons, rudder, stabilator, speed brakes) through
    its authored travel in steps of at most SWEEP_STEP, both ways where it has them, and fail if its mesh meets the
    airframe or another surface at rest: BVH triangle overlap, not sampled points."""
    O = bpy.data.objects
    hinges = sorted((o for o in icarus.all_objects if o.type == "EMPTY" and "deflection_deg" in o), key=lambda o: o.name)
    meshes = {o.name: checks.tree(o) for o in icarus.all_objects if o.type == "MESH" and (
        o.name.startswith(SWEEP_FIXED) or o.name in [h.name + "_visible" for h in hinges])}
    clashes, poses = [], 0
    for hinge in hinges:
        vis = O[hinge.name + "_visible"]
        local = hinge.matrix_world.inverted() @ vis.matrix_world
        centre = sum((v.co for v in vis.data.vertices), Vector()) / len(vis.data.vertices)

        def turned(deg):
            return hinge.matrix_world @ Matrix.Rotation(math.radians(deg), 4, "X") @ local

        travel = hinge["deflection_deg"]
        kind = hinge.name[:-2] if hinge.name.endswith(("_L", "_R")) else hinge.name
        if kind in TWO_WAY:
            signs = (1, -1)
        else:  # the way that moves the middle down (flaps, LEFs) or away from the centreline (speed brakes)
            score = (lambda m: abs((m @ centre).x)) if kind == "speed_brake" else (lambda m: -(m @ centre).z)
            signs = (1 if score(turned(1.0)) > score(turned(-1.0)) else -1,)
        steps = math.ceil(travel / SWEEP_STEP)
        others = [n for n in meshes if n != vis.name]
        for sign in signs:
            for i in range(steps + 1):
                deg = sign * travel * i / steps
                bm = bmesh.new()
                bm.from_mesh(vis.data)
                bm.transform(turned(deg))
                posed = BVHTree.FromBMesh(bm)
                bm.free()
                poses += 1
                clashes += ["%s at %+.1f deg meets %s" % (hinge.name, deg, n) for n in others if posed.overlap(meshes[n])]
    if clashes:
        raise ValueError("surface sweep: " + "; ".join(clashes[:20]) + (" (%d in all)" % len(clashes) if len(clashes) > 20 else ""))
    return "surface sweep: %d hinges clear through %d poses" % (len(hinges), poses)


def open_bays(icarus):
    """Open the gear wells to view from below, in the structure cores' render meshes only (their hulls are built).
    The internals build each bay as a closed box clipped to the inside of the skin and joined into its core, so from
    below a bay read as shut, its walls facing away from anyone looking in. The floor under the shut doors goes, the
    rest of the bay turns to face inward, and the frames and keel running through the bay are cut back to its walls."""
    O = bpy.data.objects
    nose, main = interior.INTERNALS["nose_gear_bay"], interior.INTERNALS["main_gear_bay"]
    wells = {"fuselage_forward": ([nose["box"] + (0.0,)], ("gear_door_N_L", "gear_door_N_R")),
             "fuselage_mid": ([main["box"] + (side * main["x"],) for side in (1, -1)],
                              ("gear_door_main_L", "gear_door_main_R"))}
    for core_name, (boxes, doors) in wells.items():
        core = O[core_name]
        bay_slot = [m.name for m in core.data.materials].index("jet_mechanical")
        door_trees = [checks.tree(O[d + "_visible"]) for d in doors]
        # the structure members, less the bay boxes run on down through the skin
        members = core.copy()
        members.data = core.data.copy()
        icarus.objects.link(members)
        bm = bmesh.new()
        bm.from_mesh(members.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index == bay_slot], context="FACES")
        bm.to_mesh(members.data)
        bm.free()
        cutters = []
        for s0, s1, hw, z0, z1, xc in boxes:
            me = bpy.data.meshes.new("bay_cutter")
            me.from_pydata([bi.P(s, xc + sx * hw, z) for s in (s0, s1) for sx in (-1, 1) for z in (z0 - 0.3, z1)], [],
                           [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)])
            cutter = bpy.data.objects.new("bay_cutter", me)
            icarus.objects.link(cutter)
            cutters.append(cutter)
            mod = members.modifiers.new("bay", "BOOLEAN")
            mod.operation, mod.solver, mod.object = "DIFFERENCE", "EXACT", cutter
        bpy.context.view_layer.update()
        cut = bpy.data.meshes.new_from_object(members.evaluated_get(bpy.context.evaluated_depsgraph_get()))
        # the bay: its faces turned to face in, less the floor under each door (a ray out of it meets the shut door)
        bm = bmesh.new()
        bm.from_mesh(core.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index != bay_slot], context="FACES")
        to_world, rot = core.matrix_world, core.matrix_world.to_3x3()

        def under_door(f):
            o, n = to_world @ f.calc_center_median(), (rot @ f.normal).normalized()
            return n.z < -0.25 and any(t.ray_cast(o, n, 0.12)[0] is not None for t in door_trees)

        bmesh.ops.delete(bm, geom=[f for f in bm.faces if under_door(f)], context="FACES")
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        before = len(bm.faces)
        bm.from_mesh(cut)  # appends the cut members, on the members' slots; the cut faces take the first, structure
        bm.faces.ensure_lookup_table()
        for f in bm.faces[before:]:
            f.material_index = min(f.material_index, len(core.data.materials) - 1)
        bm.to_mesh(core.data)
        bm.free()
        for o in cutters + [members]:
            me = o.data
            bpy.data.objects.remove(o)
            bpy.data.meshes.remove(me)
        bpy.data.meshes.remove(cut)


def merge_details(icarus):
    """Join every mesh tagged merge_into = "<part>" into that part's mesh (a hinged part's _visible mesh), its faces
    keeping their materials, with the skin slot first: the game paints a livery on slot 0 only (UnitPart.SetLivery).
    Returns the number merged."""
    details = [o for o in icarus.objects if o.type == "MESH" and "merge_into" in o]
    for detail in details:
        part = bpy.data.objects[detail["merge_into"]]
        if part.type == "EMPTY":
            part = bpy.data.objects[part.name + "_visible"]
        me = detail.data.copy()
        me.transform(part.matrix_world.inverted() @ detail.matrix_world)
        slots = list(part.data.materials)
        remap = []
        for mat in me.materials:
            if mat not in slots:
                slots.append(mat)
            remap.append(slots.index(mat))
        bm = bmesh.new()
        bm.from_mesh(part.data)
        before = len(bm.faces)
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        for f in bm.faces[before:]:
            f.material_index = remap[f.material_index] if remap else 0
        order = sorted(range(len(slots)), key=lambda i: slots[i].name != SKIN)  # stable: the skin moves to the front
        for f in bm.faces:
            f.material_index = order.index(f.material_index)
        part.data.materials.clear()  # resets the faces' indices, so before the faces are written back
        for i in order:
            part.data.materials.append(slots[i])
        bm.to_mesh(part.data)
        bm.free()
        bpy.data.meshes.remove(me)
        data = detail.data
        bpy.data.objects.remove(detail, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    return len(details)


def face_outward(obj):
    """Point every face of a render mesh out of its surface. The game culls back faces, and most lofts come out wound
    inward (the fin's rows happen to run the other way), so the skins drew inside out in game. The intake ducts and the
    cockpit view's renderers (the inner glass) keep their inward faces: they are seen from inside."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
