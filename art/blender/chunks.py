"""Skin panels folded into the parts they hang on, as stock jets are built: each part a chunk with its skin on it.

A Revoker part carries its own skin and sheds nothing separately (every part's disintegrateObjects is empty), and a
chunk that breaks off collides like any other. Here each skin panel (FOLDED) stays a mesh of its own, so its UVs,
livery and damage stay as they are, but stops being a part: its mass and collider hulls go to the part its joint hung
it on, and the Unity author places its mesh under that part as a visual (IcarusAuthor.Parts.cs PlaceSkins), whose
skin renderers take the part's livery and damage (ListLiveryRenderers). A part with no mesh of its own (fuselage_aft and
the truss halves, with no frames inside the skin) takes its panels into its mesh instead (join_bare). The receiving
part's centre of mass becomes the mass-weighted centre of what it carries (fold_centre, read by clearance.mass_box), so
the balance holds.

The radome, canopy and fin skin stay parts: the radome carries the radar and target camera, the canopy the escape
path, the fin skin the fin's lift.
"""
import bmesh
import bpy
import numpy as np
from mathutils import Vector

FOLDED = ("skin_", "wing_skin_", "dorsal_cover")


def is_part(obj):
    return obj.get("mass_kg", 0) > 0 or obj.get("role") == "fuel_tank"


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
    """Fold every panel into its part; returns a report line."""
    bpy.context.view_layer.update()
    panels = sorted((o for o in icarus.all_objects if o.type == "MESH" and o.name.startswith(FOLDED) and is_part(o)),
                    key=lambda o: o.name)
    # where each part's mass sat before the fold; every split family's member keeps its marker there afterwards, so the
    # Unity author's family moves come out nil and the balance holds
    marker = markers(icarus)
    for o, at in marker.items():
        if o.get("family_mass_kg", 0) > 0 and not o.name.startswith(FOLDED):
            o["fold_centre"] = [float(x) for x in at]
    carried = {}
    for panel in panels:
        host = panel.parent
        while host is not None and not is_part(host):
            host = host.parent
        if host is None:
            raise ValueError("chunks: %s hangs on no part" % panel.name)
        entry = carried.setdefault(host, [(float(host["mass_kg"]), marker[host])])
        mass = float(panel["mass_kg"])
        entry.append((mass, marker[panel]))
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
    bpy.context.view_layer.update()
    return "chunks: %d panels folded into %s" % (len(panels), ", ".join(
        "%s (%d)" % (h.name, len(e) - 1) for h, e in sorted(carried.items(), key=lambda kv: kv[0].name)))


def join_bare(icarus):
    """Join the folded panels of a part with no mesh of its own (fuselage_aft, the truss halves) into its mesh, and
    their painted LOD1 hulls into one, as the export draws a part by its own mesh. A plain merge, run once the checks
    have seen the panels as panels; returns a report line."""
    import hulls
    import parts

    lods, joined = bpy.data.collections["LOD1"], []
    for host in sorted((o for o in icarus.all_objects if o.type == "MESH" and is_part(o) and not o.data.polygons),
                       key=lambda o: o.name):
        panels = sorted((o for o in icarus.all_objects if o.get("folded_into") == host.name), key=lambda o: o.name)
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
