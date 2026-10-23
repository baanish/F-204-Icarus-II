"""Measure and render the upper nose with a fixed camera, before or after an internal fit change."""
import argparse
import contextlib
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "art/blender"))
import build_icarus as bi
import checks
import uvs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--blend", type=Path, help="Review already-built geometry without rebuilding it")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    out = ROOT / ".cache/review/share/nose_pokethrough"
    out.mkdir(parents=True, exist_ok=True)
    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
    if not args.blend:
        bi.build()
    col = bpy.data.collections["Icarus"]
    bi.TARGET = col
    for name in ("References", "Colliders", "LOD1"):
        bpy.data.collections[name].hide_render = True
        bpy.data.collections[name].hide_viewport = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    counts, points = Counter(), defaultdict(list)
    for iy in range(451):
        y = -9 + iy * .01
        for ix in range(71):
            x = -.35 + ix * .01
            ok, loc, _, index, obj, _ = bpy.context.scene.ray_cast(dg, Vector((x, y, 3)), Vector((0, 0, -1)))
            if ok:
                mat = obj.data.materials[obj.data.polygons[index].material_index].name
                key = obj.name + "/" + mat
                counts[key] += 1
                points[key].append(tuple(loc))
    report = {"first_hits": {key: {"rays": n, "min": [min(p[i] for p in points[key]) for i in range(3)],
                                         "max": [max(p[i] for p in points[key]) for i in range(3)]}
                             for key, n in counts.most_common()}, "uvs_check": uvs.check(col)}
    reference = bi.loft("nose_reference", [bi.blended_ring(bi.PARAMS, s) for s in bi.fuselage_stations(bi.PARAMS) if s <= 3],
                        tip_front=bi.P(0, 0, bi.PARAMS["fuselage"][0][2]))
    shell = checks.tree(reference)
    for key in ("radar_tray/jet_mechanical", "fuselage_forward/aircraft_structure"):
        gaps = []
        for point in points[key]:
            at, _, _, _ = shell.ray_cast(Vector((point[0], point[1], 3)), Vector((0, 0, -1)))
            if at is not None:
                gaps.append(at.z - point[2])
        if gaps:
            report[key + "_below_uncut_skin_m"] = [min(gaps), max(gaps)]
    report["radar_min_normal_clearance_m"] = min(shell.find_nearest(Vector(q))[3]
                                                for q in checks.surface_samples(bpy.data.objects["radar_tray"]))
    skin_trees = [checks.tree(bpy.data.objects[name]) for name in ("radome", "skin_forward_L", "skin_forward_R")]
    report["radar_min_render_skin_clearance_m"] = min(min(t.find_nearest(Vector(q))[3] for t in skin_trees)
                                                     for q in checks.surface_samples(bpy.data.objects["radar_tray"]))
    mesh = reference.data
    bpy.data.objects.remove(reference, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    for allow_openings in (True, False):
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                checks.interior_visibility(col, allow_openings)
            report["visibility_openings_" + str(allow_openings)] = captured.getvalue().strip()
            print(captured.getvalue().strip(), flush=True)
        except ValueError as exc:
            report["visibility_openings_" + str(allow_openings)] = str(exc)
    atlas = [(o.name, [(tuple(v.co)) for v in o.data.vertices],
              [(f.vertices[:], f.material_index) for f in o.data.polygons],
              [tuple(d.uv) for d in o.data.uv_layers.active.data]) for o in sorted(uvs.skin_objects(col), key=lambda o: o.name)]
    report["skin_geometry_uv_sha256"] = hashlib.sha256(repr(atlas).encode()).hexdigest()
    report["part_triangles"] = {name: sum(len(f.vertices) - 2 for f in bpy.data.objects[name].data.polygons)
                                for name in ("radar_tray", "cockpit_cell", "avionics_tray", "fuselage_forward",
                                             "fuselage_mid", "fuselage_aft", "radome", "skin_forward_L", "skin_forward_R")}
    report["part_world_bounds"] = {name: [[fn((bpy.data.objects[name].matrix_world @ v.co)[i]
                                             for v in bpy.data.objects[name].data.vertices) for i in range(3)]
                                          for fn in (min, max)] for name in report["part_triangles"]}
    report["exterior_hardware_faces"] = {o.name: sum(v.value for v in o.data.attributes["exterior_hardware"].data)
                                          for o in col.all_objects if o.type == "MESH"
                                          and o.data.attributes.get("exterior_hardware")}
    (out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    print("NOSE_REVIEW", json.dumps(report), flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / (args.label + ".blend")))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1400, 1100, 100
    shading = scene.display.shading
    shading.light, shading.color_type = "STUDIO", "MATERIAL"
    shading.show_shadows = False
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    shading.background_type = "WORLD"
    scene.world.color = (.15, .15, .15)
    camera = bpy.data.objects.new("Nose_review_camera", bpy.data.cameras.new("Nose_review_camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.location = (2.6, -10.0, 5.8)
    target = Vector((0, -6.4, .15))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type, camera.data.ortho_scale = "ORTHO", 4.1
    scene.render.filepath = str(out / (args.label + ".png"))
    for obj in col.all_objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
