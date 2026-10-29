"""Skin panels and internals folded into the parts they sit in, as stock jets are built: each part a chunk with its skin
and what lies inside it.

A Revoker part carries its own skin and sheds nothing separately (every part's disintegrateObjects is empty), a chunk
that breaks off collides like any other, and nothing inside a section is a part of its own: its FuelTanks sit on the
fuselage and wing parts, its engine in the tail part, which takes the JetNozzle's thrust. Here each skin panel (FOLDED),
fuel cell and internal (INTERNALS) stays a mesh of its own, so its UVs, livery and damage stay as they are, but stops
being a part: its mass, fuel and collider hulls go to the part it sits in, and the Unity author places its mesh under
that part as a visual (IcarusAuthor.Parts.cs PlaceSkins), whose skin renderers take the part's livery and damage
(ListLiveryRenderers). A part with no mesh of its own (fuselage_aft and the truss halves) takes its skin panels into its
mesh instead (join_bare). The receiving part's centre of mass becomes the mass-weighted centre of what it carries
(fold_centre, read by clearance.mass_box), or for the sections that take internals the one keep_balance gives them, so
the balance holds empty and full.

The radome, canopy and fin skin stay parts: the radome carries the radar and target camera, the canopy the escape
path, the fin skin the fin's lift. So does the cockpit cell, the cockpit section the Revoker's cockpit part becomes,
with the crew, weapon manager and displays, the radome, canopy and nose gear on it.
"""
import bmesh
import bpy
import numpy as np
from mathutils import Vector

FOLDED = ("skin_", "wing_skin_", "dorsal_cover")
INTERNALS = ("intake_duct_", "radar_tray", "avionics_tray", "engine_core", "engine_afterburner", "nozzle")


def is_part(obj):
    return obj.get("mass_kg", 0) > 0 or obj.get("role") == "fuel_tank"


def folds(obj):
    """Whether a part folds into the part it sits in: a skin panel, a fuel cell or an internal."""
    return is_part(obj) and (obj.name.startswith(FOLDED + INTERNALS) or obj.get("role") == "fuel_tank")


def hulls_of(obj):
    return [c for c in obj.children if c.name in bpy.data.collections["Colliders"].objects]


def box_centre(colliders):
    """ConfigurePart's centre of mass: each hull's own box, its corners boxed in world."""
    corners = []
    for c in colliders:
        local = np.array([v.co[:] for v in c.data.vertices])
        lo, hi = local.min(0), local.max(0)
        corners += [(c.matrix_world @ Vector([(hi if k >> i & 1 else lo)[i] for i in range(3)]))[:] for k in range(8)]
    corners = np.array(corners)
    return (corners.min(0) + corners.max(0)) / 2


PIECE_CODES = ("front", "rear", "belly", "inner", "outer", "upper", "lower")  # IcarusAuthor.cs PieceCodes


def family_of(obj):
    """IcarusAuthor's SplitFamilies key: the family prop, else a skin's name less its piece codes."""
    if "family" in obj:
        return obj["family"]
    return "_".join(t for t in obj.name.split("_") if t not in PIECE_CODES) if obj.name.startswith(FOLDED) else obj.name


def world_box(colliders):
    pts = np.vstack([np.array([(c.matrix_world @ v.co)[:] for v in c.data.vertices]) for c in colliders])
    return pts.min(0), pts.max(0)


def markers(icarus):
    """Every part's centre-of-mass marker as the Unity author placed it before the fold: ConfigurePart's box centre,
    then for each split family (family_mass_kg) KeepFamilyMoments' moves along and up the body (Blender z and y),
    from the hulls' world boxes, dry and full fuel; a fuselage section's or truss half's box is its pinned one
    (parts.CORE_MASS_BOXES)."""
    from parts import CORE_MASS_BOXES

    pinned = lambda o: tuple(np.array(v) for v in CORE_MASS_BOXES[o.name])
    parts = [o for o in icarus.all_objects if o.type == "MESH" and is_part(o) and hulls_of(o)]
    out = {o: sum(pinned(o)) / 2 if o.name in CORE_MASS_BOXES else box_centre(hulls_of(o)) for o in parts}
    families = {}
    for o in parts:
        if o.get("family_mass_kg", 0) > 0:
            families.setdefault(family_of(o), []).append(o)
    for members in families.values():
        boxes = [pinned(m) if m.name in CORE_MASS_BOXES else world_box(hulls_of(m)) for m in members]
        centres = [(lo + hi) / 2 for lo, hi in boxes]
        whole = (np.min([lo for lo, _ in boxes], 0) + np.max([hi for _, hi in boxes], 0)) / 2
        mass = [float(m["mass_kg"]) for m in members]
        fuel = [float(m.get("fuel_kg", 0.0)) for m in members]
        moves = [np.zeros(3) for _ in members]
        for axis in (2, 1):
            lo = lambda i: boxes[i][0][axis] - centres[i][axis]
            hi = lambda i: boxes[i][1][axis] - centres[i][axis]
            dry = -sum(mass[i] * (centres[i][axis] - whole[axis]) for i in range(len(members)))
            full = -sum((mass[i] + fuel[i]) * (centres[i][axis] - whole[axis]) for i in range(len(members)))
            det = mass[0] * (mass[1] + fuel[1]) - mass[1] * (mass[0] + fuel[0]) if len(members) == 2 else 0.0
            if abs(det) > 1e-3:
                second = min(max((mass[0] * full - (mass[0] + fuel[0]) * dry) / det, lo(1)), hi(1))
                moves[1][axis] = second
                moves[0][axis] = min(max((dry - mass[1] * second) / mass[0], lo(0)), hi(0))
            else:
                for i in range(len(members)):
                    moves[i][axis] = min(max(dry / sum(mass), lo(i)), hi(i))
        for m, c, d in zip(members, centres, moves):
            out[m] = c + d
    return out


def fold(icarus):
    """Fold every panel, fuel cell and internal into the part it sits in; returns a report line."""
    bpy.context.view_layer.update()
    panels = sorted((o for o in icarus.all_objects if o.type == "MESH" and folds(o)), key=lambda o: o.name)
    # where each part's mass sat before the fold; every split family's member keeps its marker there afterwards, so the
    # Unity author's family moves come out nil and the balance holds
    marker = markers(icarus)
    for o, at in marker.items():
        if o.get("family_mass_kg", 0) > 0 and not folds(o):
            o["fold_centre"] = [float(x) for x in at]
    carried, fuel, inner = {}, {}, set()
    for panel in panels:
        host = panel.parent
        while host is not None and (not is_part(host) or folds(host)):
            host = host.parent
        if host is None:
            raise ValueError("chunks: %s hangs on no part" % panel.name)
        if "family" in panel and any(o.get("family") == panel["family"] and not folds(o) for o in icarus.all_objects):
            raise ValueError("chunks: %s folds away from its split family" % panel.name)
        entry = carried.setdefault(host, [(float(host["mass_kg"]), marker[host])])
        mass = float(panel["mass_kg"])
        entry.append((mass, marker[panel]))
        if not panel.name.startswith(FOLDED):
            inner.add(host)
        if panel.get("fuel_kg", 0) > 0:
            if host.get("fuel_kg", 0) > 0 and host not in fuel:
                raise ValueError("chunks: %s carries fuel of its own at a marker the fold moves" % host.name)
            fuel.setdefault(host, []).append((float(panel["fuel_kg"]), marker[panel]))
            host["fuel_kg"] = round(float(host.get("fuel_kg", 0.0)) + float(panel["fuel_kg"]), 3)
            del panel["fuel_kg"]
        for c in hulls_of(panel):
            c["folded_from"] = panel.name  # clearance keeps it clear of what the panel was clear of
            world = c.matrix_world.copy()
            c.parent = host
            c.matrix_parent_inverse.identity()
            c.matrix_basis.identity()
            c.data.transform(host.matrix_world.inverted() @ world)
        family = host.get("family")
        if family is not None:
            for o in icarus.all_objects:
                if o.get("family") == family and "family_mass_kg" in o:
                    o["family_mass_kg"] = float(o["family_mass_kg"]) + mass
        host["mass_kg"] = float(host["mass_kg"]) + mass
        del panel["mass_kg"]
        for key in ("family", "family_mass_kg"):
            if key in panel:
                del panel[key]
        panel["folded_into"] = host.name
    for host, entry in carried.items():
        total = sum(m for m, _ in entry)
        host["fold_centre"] = [float(x) for x in sum(m * c for m, c in entry) / total]
    hosts = sorted(inner, key=lambda o: o.name)
    bpy.context.view_layer.update()  # the moved hulls' world matrices, for the bounds
    for host, at in zip(hosts, keep_balance([carried[h] for h in hosts], [fuel.get(h, []) for h in hosts])):
        lo, hi = world_box(hulls_of(host))
        if np.any(at < lo - 1e-6) or np.any(at > hi + 1e-6):
            raise ValueError("chunks: %s's centre of mass %s would leave its hulls' bounds" % (host.name, at.round(3)))
        host["fold_centre"] = [float(x) for x in at]
    bpy.context.view_layer.update()
    return "chunks: %d panels and internals folded into %s; %.1f kg of fuel into %s" % (len(panels), ", ".join(
        "%s (%d)" % (h.name, len(e) - 1) for h, e in sorted(carried.items(), key=lambda kv: kv[0].name)),
        sum(w for f in fuel.values() for w, _ in f), ", ".join(sorted(h.name for h in fuel)))


def keep_balance(dry, fuel):
    """The centres of mass of the sections the internals fold into, each its carried parts' mass-weighted centre moved
    by the least mass-weighted amount that keeps both the dry moment and the folded fuel's moment: a part's fuel sits at
    its centre-of-mass marker (UnitPart.ModifyMass), so fuel folded into a section would otherwise sit where its dry mass
    does, and the full-fuel centre of mass (IcarusAuthor A22's pin) would move. dry and fuel hold each section's
    (mass, centre) entries; returns a centre a section, world space."""
    m = np.array([sum(w for w, _ in d) for d in dry])
    centre = np.array([sum(w * np.asarray(c) for w, c in d) / mi for d, mi in zip(dry, m)])
    f = np.array([sum(w for w, _ in g) for g in fuel])
    moment = sum((w * np.asarray(c) for g in fuel for w, c in g), np.zeros(3))
    constraints, weights = np.vstack([m, f]), np.diag(1 / m)
    out = centre.copy()
    for axis in range(3):
        miss = np.array([0.0, moment[axis] - f @ centre[:, axis]])
        out[:, axis] += weights @ constraints.T @ np.linalg.solve(constraints @ weights @ constraints.T, miss)
    return out


def join_bare(icarus):
    """Join the folded skin panels of a part with no mesh of its own (fuselage_aft, the truss halves) into its mesh, and
    their painted LOD1 hulls into one, as the export draws a part by its own mesh. A plain merge, run once the checks
    have seen the panels as panels; returns a report line. Internals stay visuals of their own."""
    import hulls
    import parts

    lods, joined = bpy.data.collections["LOD1"], []
    for host in sorted((o for o in icarus.all_objects if o.type == "MESH" and is_part(o) and not o.data.polygons),
                       key=lambda o: o.name):
        panels = sorted((o for o in icarus.all_objects if o.get("folded_into") == host.name and o.name.startswith(FOLDED)),
                        key=lambda o: o.name)
        lod_hulls = [c for p in panels for c in p.children if c.name in lods.objects]
        if lod_hulls:
            materials = list(lod_hulls[0].data.materials)
            if any(list(h.data.materials) != materials for h in lod_hulls):
                raise ValueError("chunks: %s's panels' LOD1 hulls wear different materials" % host.name)
            bm = bmesh.new()
            for hull in lod_hulls:
                me = hull.data.copy()
                me.transform(host.matrix_world.inverted() @ hull.matrix_world)
                bm.from_mesh(me)
                bpy.data.meshes.remove(me)
                data = hull.data
                bpy.data.objects.remove(hull, do_unlink=True)
                bpy.data.meshes.remove(data)
            me = bpy.data.meshes.new(host.name + "_lod1")
            bm.to_mesh(me)
            bm.free()
            for mat in materials:
                me.materials.append(mat)
            hulls.attach(host.name + "_lod1", me, host, lods)
        for p in panels:
            for c in list(p.children):
                world = c.matrix_world.copy()
                c.parent = host
                c.matrix_world = world
            p["merge_into"] = host.name
        host["joined"] = [p.name for p in panels]  # their families still find them (parts.family_objects)
        joined += [p.name for p in panels]
    parts.merge_details(icarus)
    bpy.context.view_layer.update()
    return "chunks: joined into their part's mesh: " + ", ".join(joined)
