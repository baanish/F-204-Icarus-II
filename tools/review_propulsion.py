"""Measure propulsion against the trough and render the P3 owner review. Run through Run-Blender.ps1."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "art/blender"))
import build_icarus as bi
import budget
import propulsion
import review_sheet as rs
import stations


def measurements():
    icarus = bpy.data.collections["Icarus"]
    ducts = stations.tree_of([o for o in icarus.objects if o.name.startswith("intake_duct_")])
    skins = [o for o in icarus.objects if o.name.startswith("skin_")]
    points = [o.matrix_world @ v.co for o in skins for v in o.data.vertices]
    trough = [w for w in points if any(abs(c(w.x, w.z)) < 0.002
              for c in stations.carve_shapes(bi.PARAMS, w.y + bi.S0))]
    distance, point = min((ducts.find_nearest(w)[3], w) for w in trough)
    skin = stations.tree_of(skins)
    bodies = {key: min(skin.find_nearest(q)[3] for side in (1, -1) for q in stations.body_points(m, side))
              for key, m in stations.MOUNTS.items()}
    return {"duct_to_trough_m": distance, "at_s_x_z": [point.y + bi.S0, point.x, point.z],
            "trough_vertices": len(trough), "body_to_skin_m": bodies,
            "budgets": {key: {"triangles": budget.measure(icarus, item), "target": item["target"], "cap": item["cap"]}
                        for key, item in propulsion.BUDGET.items()},
            "exterior_renderers": sum(not budget.is_cockpit(o) for o in budget.meshes(icarus)),
            "nozzle_hinges": len(bpy.data.objects["nozzle_vector"].children)}


def render(out):
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    scene = rs.setup_scene()
    scene.render.film_transparent = False
    scene.display.shading.background_type = "WORLD"
    scene.world.color = (0.36, 0.39, 0.43)
    scene.display.shading.studiolight_rotate_z = 0.6
    scene.display.shading.show_shadows = True
    for name in ("Colliders", "LOD1", "References"):
        collection = bpy.data.collections.get(name)
        if collection:
            collection.hide_render = True
    # The stock trims have no preview colour in Blender. Use distinct review tints without changing exported slots.
    bpy.data.materials["jet_mechanical"].diffuse_color = (0.12, 0.14, 0.16, 1)
    bpy.data.materials["aircraft_structure"].diffuse_color = (0.27, 0.30, 0.34, 1)
    views = {
        "intake_head_on": (propulsion.CLOSEUPS["intake_head_on"][0], propulsion.CLOSEUPS["intake_head_on"][1], 140),
        "intake_three_quarter": ((2.65, -4.5, 1.1), (0.73, -1.0, 0.22), 60),
        "inboard_mouth": ((1.45, -3.4, 0.58), (0.70, -1.14, 0.22), 65),
        "nozzle": ((-1.15, 9.3, 0.95), (0, 7.42, 0.37), 48),
        "chase": ((0, 12.0, 0.37), (0, 7.20, 0.37), 100),
    }
    for name, (location, target, lens) in views.items():
        cam = rs.camera("P3_" + name)
        cam.data.type = "PERSP"
        cam.data.lens = lens
        cam.data.clip_start = 0.01
        cam.location = location
        cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
        poses = {"dry": {}, "full_ab": {"open_deg": 15}, "pitch5": {"pitch_deg": 5}} if name == "nozzle" else {"": {}}
        for pose, values in poses.items():
            propulsion.pose_nozzle(**values)
            bpy.context.view_layer.update()
            filename = name + ("_" + pose if pose else "") + ".png"
            rs.render_view(scene, cam, str(out / filename), (1600, 1100))
    propulsion.pose_nozzle()
    bpy.context.view_layer.update()


def section_data():
    p, m = bi.PARAMS, propulsion.MOUTH
    s, cx, cz, radius = p["duct"][0]
    sc = p["shock_cone"]
    at = lambda t: (sc["break_r"] * (t - sc["apex_s"]) / (sc["break_s"] - sc["apex_s"]) if t <= sc["break_s"]
                    else sc["break_r"] + (sc["radius"] - sc["break_r"]) * (t - sc["break_s"]) / (sc["base_s"] - sc["break_s"]))
    a, b = sc["bleed_s"], sc["bleed_s"] + 0.035
    return {"mouth": m, "duct": [cx, cz, radius], "cone_x": sc["x"], "cone_radius_at_lip": at(6.85),
            "cone_profile": [[sc["apex_s"], 0], [sc["break_s"], sc["break_r"]], [a, at(a)],
                             [a, at(a) - m["undercut"]], [b, at(b) - m["undercut"]], [b, at(b)],
                             [sc["base_s"], sc["radius"]]],
            "lip_edge_x_z": [[v.x, v.z] for v in propulsion.lip_edge(p, bpy.data.objects["skin_mid_L"])]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO / ".cache/review/wave2/P3/01")
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    args.out.mkdir(parents=True, exist_ok=True)
    if args.baseline:
        source = subprocess.check_output(["git", "show", "82cb1ab:art/blender/propulsion.py"], cwd=REPO)
        exec(compile(source, "baseline_propulsion.py", "exec"), propulsion.__dict__)
    if args.baseline:
        bi.build()  # This mode executes historical source in memory.
    else:
        bi.build_cached()
    report = measurements()
    name = "baseline-measurements.json" if args.baseline else "measurements.json"
    (args.out / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("P3 measurements: " + json.dumps(report), flush=True)
    if not args.baseline:
        (args.out / "section.json").write_text(json.dumps(section_data(), indent=2) + "\n", encoding="utf-8")
        render(args.out)


if __name__ == "__main__":
    main()
