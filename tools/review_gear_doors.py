"""Gear door review: each door's tessellation, shading and edge against the skin it was cut from, and textured renders
of the main bay's doors open (close, behind and below), shut against the skin, and the nose doors open.

Run through tools/Run-Blender.ps1 with --background --factory-startup --python-exit-code 1 --python
tools/review_gear_doors.py -- --out <absolute folder> --label <before|after> [--blend <absolute .blend to save>]
[--load <absolute .blend>] [--skip-renders]. Blender resolves relative paths from C:\\, so every path must be absolute.
Prints one DOORS line of JSON with the measurements.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi  # noqa: E402

# (camera location, target, lens mm, doors' open fraction, legs whose doors it poses), left side, Blender axes (x
# outboard, y aft, z up); a shut view stows those legs too
VIEWS = {"main_open_close": ((1.55, 0.35, -1.35), (0.55, 1.55, -0.55), 35, 1.0, "LR"),
         "main_open_behind": ((0.55, 5.4, -1.7), (0.45, 1.4, -0.55), 35, 1.0, "LR"),
         "main_open_below": ((0.6, 1.7, -3.2), (0.45, 1.6, -0.5), 35, 1.0, "LR"),
         "main_shut": ((2.4, 4.4, -1.5), (0.45, 1.6, -0.5), 35, 0.0, "LR"),
         "nose_open": ((1.3, -4.4, -1.55), (0.1, -3.3, -0.55), 35, 1.0, "N")}


def edge_lengths(obj, polys):
    """Median length of a mesh's edges in the given polygons, split into along the station (y) and round the section."""
    mw = obj.matrix_world
    along, around = [], []
    seen = set()
    for p in polys:
        vs = list(p.vertices)
        for a, b in zip(vs, vs[1:] + vs[:1]):
            if (min(a, b), max(a, b)) in seen:
                continue
            seen.add((min(a, b), max(a, b)))
            d = mw @ obj.data.vertices[b].co - mw @ obj.data.vertices[a].co
            if d.length < 1e-5:
                continue
            (along if abs(d.y) > 0.7 * d.length else around).append(d.length)
    med = lambda xs: round(statistics.median(xs), 4) if xs else None
    return med(along), med(around), len(along), len(around)


def measure():
    import gear

    O = bpy.data.objects
    skin = [o for o in O if o.type == "MESH" and (o.name.startswith("skin_") or o.name == "radome")]
    out = {}
    for leg in gear.LEGS:
        for d in gear.doors_of(leg):
            door = O[d + "_visible"]
            me = door.data
            me.calc_loop_triangles()
            mw = door.matrix_world
            outer = [p for p in me.polygons if p.material_index == 0 and len(p.vertices) == 4]
            pts = [mw @ me.vertices[i].co for p in outer for i in p.vertices]
            lo = Vector([min(q[i] for q in pts) for i in range(3)])
            hi = Vector([max(q[i] for q in pts) for i in range(3)])
            near = lambda q, m=0.05: all(lo[i] - m <= q[i] <= hi[i] + m for i in range(3))
            sk = []
            for o in skin:
                ps = [p for p in o.data.polygons if all(near(o.matrix_world @ o.data.vertices[i].co, 0.08) for i in p.vertices)]
                if ps:
                    sk.append((o, ps))
            skin_e = [edge_lengths(o, ps) for o, ps in sk]
            s_along = [e[0] for e in skin_e if e[0]]
            s_around = [e[1] for e in skin_e if e[1]]
            d_along, d_around, _, _ = edge_lengths(door, outer)
            # the free edge: outer-boundary points to the nearest tray point, the lip's thickness
            inner = {i for p in me.polygons if p.material_index == 1 for i in p.vertices}
            inner_pts = [mw @ me.vertices[i].co for i in inner]
            edge_ids = {i for p in me.polygons if p.material_index == 0 and len(p.vertices) == 3 for i in p.vertices}
            outer_ids = {i for p in outer for i in p.vertices}
            lip = [min((mw @ me.vertices[i].co - q).length for q in inner_pts) for i in edge_ids & outer_ids][:400]
            out[d] = {"tris": len(me.loop_triangles),
                      "outer_quads": len(outer),
                      "outer_tris_skin": sum(1 for t in me.loop_triangles if t.material_index == 0),
                      "size_m": [round(x, 3) for x in hi - lo],
                      "door_edge_along_m": d_along, "door_edge_around_m": d_around,
                      "skin_edge_along_m": round(statistics.median(s_along), 4) if s_along else None,
                      "skin_edge_around_m": round(statistics.median(s_around), 4) if s_around else None,
                      "smooth_faces": sum(p.use_smooth for p in me.polygons), "faces": len(me.polygons),
                      "sharp_edges": sum(1 for e in me.edges if e.use_edge_sharp),
                      "lip_m": round(statistics.median(lip), 4) if lip else None}
    return out


def metal(name, rgb, rough, metallic=1.0):
    m = bpy.data.materials.get(name)
    if m is None:
        return
    m.use_nodes = True
    nodes = m.node_tree.nodes
    nodes.clear()
    b = nodes.new("ShaderNodeBsdfPrincipled")
    m.node_tree.links.new(b.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough


def light(scene, name, loc, target, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.size = energy, size
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def renders(out, label):
    import gear
    import skin_review

    for name in ("Colliders", "LOD1", "References"):
        col = bpy.data.collections.get(name)
        if col:
            col.hide_render = True
    for obj in bpy.data.objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    skin_review.preview_material(1)
    metal("Fighter1_gear", (0.62, 0.64, 0.66), 0.35)
    metal("Mirror", (0.92, 0.92, 0.94), 0.06)
    metal("Aircraft_wheels", (0.03, 0.03, 0.03), 0.75, 0.0)
    metal("jet_mechanical", (0.16, 0.17, 0.18), 0.45, 0.6)
    metal("aircraft_structure", (0.30, 0.31, 0.33), 0.45, 0.6)
    scene = bpy.context.scene
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1280, 960, 100
    world = scene.world or bpy.data.worlds.new("review")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value, bg.inputs["Strength"].default_value = (0.10, 0.11, 0.13, 1), 1.0
    scene.view_settings.view_transform, scene.view_settings.look = "AgX", "AgX - Medium High Contrast"
    scene.view_settings.exposure = -0.5
    light(scene, "key", (2.5, -1.0, -3.0), (0.4, 1.5, -0.5), 600, 3.0)
    light(scene, "rim", (-1.5, 5.5, -2.0), (0.4, 1.5, -0.5), 300, 2.0)
    light(scene, "nose_key", (2.5, -5.5, -2.5), (0.1, -3.3, -0.5), 300, 2.0)
    cam = bpy.data.objects.new("door_cam", bpy.data.cameras.new("door_cam"))
    scene.collection.objects.link(cam)
    cam.data.clip_start = 0.01
    scene.camera = cam
    for view, (loc, target, lens, fraction, leg) in VIEWS.items():
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = lens
        pose = {d: fraction for g in leg for d in gear.doors_of(g)}
        if not fraction:  # shut over the stowed gear
            pose.update({n: 1.0 for g in leg for n in ("gear_leg_" + g, "gear_wheel_" + g)})
        with gear.posed(pose):
            scene.render.filepath = str(out / ("%s_%s.png" % (label, view)))
            bpy.ops.render.render(write_still=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--blend", type=Path)
    ap.add_argument("--load", type=Path, help="render a saved --blend instead of building")
    ap.add_argument("--skip-renders", action="store_true")
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not args.out.is_absolute():
        raise ValueError("--out must be absolute")
    args.out.mkdir(parents=True, exist_ok=True)
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    if args.load:
        bpy.ops.wm.open_mainfile(filepath=str(args.load))
    else:
        bi.build_cached()
    if args.blend and not args.load:
        bpy.ops.wm.save_as_mainfile(filepath=str(args.blend))
    print("DOORS " + json.dumps(measure()))
    if not args.skip_renders:
        renders(args.out, args.label)


if __name__ == "__main__":
    main()
