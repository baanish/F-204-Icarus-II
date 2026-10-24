"""Measure and render the stabilator's cut-out round the fin-tip fairing, through its full pitch travel.

    pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 \
        --python tools/review_fintip.py -- --out <absolute dir> --label before

Writes <label>.json (triangles, height, the clearance between the stabilator and the fin skin with its fairing at
every pose of the travel) and <label>_<view>.png renders from fixed cameras, so two labels compare frame for frame.
Clearance is the nearest distance from points sampled every SPACING metres on either mesh round the junction to the
other mesh's surface, posed; a positive travel raises the stabilator's trailing edge (nose up).
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

SPACING = 0.003
STEP = 0.5  # degrees between poses


def junction(co):
    """Points of either mesh near enough the fairing to matter (Blender axes, y = s - 8)."""
    return abs(co.x) < 0.16 and 6.55 < co.y < 8.0 and 2.6 < co.z < 3.05


def samples(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    out = []
    for tri in mesh.loop_triangles:
        a, b, c = [obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices]
        if not any(junction(v) for v in (a, b, c)):
            continue
        n = max(1, math.ceil(max((b - a).length, (c - a).length, (c - b).length) / SPACING))
        out += [a + (b - a) * (i / n) + (c - a) * (j / n) for i in range(n + 1) for j in range(n + 1 - i)]
    return out


def tree(obj):
    mesh = obj.data
    return BVHTree.FromPolygons([obj.matrix_world @ v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons])


def pose(deg):
    hinge = bpy.data.objects["stabilator"]
    if "rest" not in hinge:
        hinge["rest"] = [c for row in hinge.matrix_world for c in row]
    rest = Matrix([hinge["rest"][i:i + 4] for i in range(0, 16, 4)])
    hinge.matrix_world = rest @ Matrix.Rotation(math.radians(deg), 4, "X")
    bpy.context.view_layer.update()


def clearance(travel):
    stab, fin = bpy.data.objects["stabilator_visible"], bpy.data.objects["fin_skin"]
    fin_tree, fin_points = tree(fin), samples(fin)
    rows = []
    for k in range(-round(travel / STEP), round(travel / STEP) + 1):
        deg = k * STEP
        pose(deg)
        stab_tree = tree(stab)
        best = (math.inf, None)
        for p in samples(stab):
            hit = fin_tree.find_nearest(p)
            if hit[0] is not None and hit[3] < best[0]:
                best = (hit[3], p)
        for p in fin_points:
            hit = stab_tree.find_nearest(p)
            if hit[0] is not None and hit[3] < best[0]:
                best = (hit[3], hit[0])
        rows.append({"deg": deg, "gap_mm": round(best[0] * 1000, 2), "overlap": bool(stab_tree.overlap(fin_tree)),
                     "at_s_x_z": [round(best[1].y + 8.0, 3), round(best[1].x, 3), round(best[1].z, 3)]})
        print("clearance %+5.1f deg: %.2f mm%s" % (deg, rows[-1]["gap_mm"], " OVERLAP" if rows[-1]["overlap"] else ""),
              flush=True)
    pose(0.0)
    return rows


def rest_profile():
    """The gap at rest along the cut-out: sideways beside the fairing every 5 cm of s, and fore and aft behind it."""
    stab, fin = bpy.data.objects["stabilator_visible"], bpy.data.objects["fin_skin"]
    stab_tree, fin_tree = tree(stab), tree(fin)
    out = []
    for i in range(23):
        s = 14.80 + 0.05 * i
        y = s - 8.0
        side = stab_tree.ray_cast(Vector((0.0, y, 2.82)), Vector((1.0, 0.0, 0.0)), 0.3)
        wall = fin_tree.ray_cast(Vector((0.3, y, 2.83)), Vector((-1.0, 0.0, 0.0)), 0.3)  # the fairing's outside
        if side[0] is not None and wall[0] is not None:
            out.append({"s": round(s, 2), "fairing_x": round(wall[0].x, 4), "stabilator_x": round(side[0].x, 4),
                        "gap_mm": round((side[0].x - wall[0].x) * 1000, 1)})
    aft = stab_tree.ray_cast(Vector((0.0, 6.0, 2.82)), Vector((0.0, 1.0, 0.0)), 3.0)
    tail = fin_tree.ray_cast(Vector((0.0, 9.0, 2.83)), Vector((0.0, -1.0, 0.0)), 3.0)
    if aft[0] is not None and tail[0] is not None:
        out.append({"centreline_aft_gap_mm": round((aft[0].y - tail[0].y) * 1000, 1)})
    return out


VIEWS = {  # name: (camera location, look-at, ortho scale or None for a 40 mm perspective lens)
    "top": ((0.0, 7.25, 5.0), (0.0, 7.25, 2.83), 1.5),
    "rear_three_quarter": ((-2.2, 10.2, 4.0), (0.0, 7.35, 2.78), None),
    "owner": ((-1.3, 5.6, 4.1), (0.0, 7.35, 2.83), None),
    "side": ((-4.0, 7.2, 2.75), (0.0, 7.2, 2.75), 1.6),
    "front": ((0.0, 3.0, 2.80), (0.0, 7.0, 2.80), 0.55),
    "fillet": ((-1.1, 6.6, 2.5), (0.0, 7.15, 2.79), None),
}
GAP_VIEWS = {  # the junction behind the fairing's tail, posed at full travel
    "gap_top": ((0.0, 7.66, 4.0), (0.0, 7.66, 2.83), 0.32),
    "gap_quarter": ((-0.5, 8.3, 3.2), (0.0, 7.68, 2.83), None),
}


def render(out, label, travel):
    for name in ("References", "Colliders", "LOD1", "Internals"):
        col = bpy.data.collections.get(name)
        if col:
            col.hide_render = True
    for obj in bpy.data.collections["Icarus"].all_objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1400, 1000, 100
    shading = scene.display.shading
    shading.light, shading.color_type = "STUDIO", "SINGLE"
    shading.single_color = (0.62, 0.66, 0.70)
    shading.show_shadows, shading.show_cavity, shading.cavity_type = False, True, "BOTH"
    shading.background_type = "WORLD"
    scene.world.color = (0.08, 0.10, 0.12)
    camera = bpy.data.objects.new("fintip_review_camera", bpy.data.cameras.new("fintip_review_camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    shots = [(name, view, 0.0) for name, view in VIEWS.items()]
    shots += [("%s_%s" % (name, way), view, deg) for name, view in GAP_VIEWS.items()
              for way, deg in (("nose_up", travel), ("nose_down", -travel))]
    paths = []
    for name, (location, target, scale), deg in shots:
        pose(deg)
        camera.location = location
        camera.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
        camera.data.type = "ORTHO" if scale else "PERSP"
        if scale:
            camera.data.ortho_scale = scale
        else:
            camera.data.lens = 40
        camera.data.clip_start = 0.01
        scene.render.filepath = str(out / ("%s_%s.png" % (label, name)))
        bpy.ops.render.render(write_still=True)
        paths.append(scene.render.filepath)
    pose(0.0)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not args.out.is_absolute():
        raise ValueError("the output path must be absolute (Blender resolves relative paths from its own folder)")
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.repo / "art/blender"))
    import build_icarus as bi

    bi.build_cached(str(args.repo))
    import budget

    icarus = bpy.data.collections["Icarus"]
    exterior = [o for o in icarus.all_objects if o.type == "MESH" and o.get("role") != "cockpit_view"]
    tops = [max((o.matrix_world @ v.co).z for v in o.data.vertices) for o in exterior if o.data.vertices]
    travel = bpy.data.objects["stabilator"]["deflection_deg"]
    report = {"label": args.label, "travel_deg": travel,
              "triangles": {n: budget.tris(bpy.data.objects[n]) for n in ("stabilator_visible", "fin_skin", "ventral_fin")},
              "exterior_triangles": sum(map(budget.tris, exterior)),
              "top_z": round(max(tops), 4), "rest_profile": rest_profile(), "clearance": clearance(travel)}
    worst = min(report["clearance"], key=lambda r: r["gap_mm"])
    report["worst"] = worst
    report["renders"] = render(args.out, args.label, travel)
    (args.out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    print("fintip review %s: stabilator %d tris, fin_skin %d tris, top z %.4f, worst gap %.2f mm at %+.1f deg"
          % (args.label, report["triangles"]["stabilator_visible"], report["triangles"]["fin_skin"], report["top_z"],
             worst["gap_mm"], worst["deg"]), flush=True)


if __name__ == "__main__":
    main()
