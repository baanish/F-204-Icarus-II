"""Review renders of the left main gear leg: a close three-quarter and a front view, each with the wheel free and at the
bump stop (gear.GEAR_STROKE), and the fold from behind and below as a GIF, in a metal and a clay look.

Run through tools/Run-Blender.ps1 with --background --factory-startup --python-exit-code 1 --python
tools/review_main_leg.py -- --out <absolute folder> --label <before|after> [--blend <absolute .blend to save>]
[--frames N]. Blender resolves relative paths from C:\\, so every path must be absolute.
"""
import argparse
import math
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi  # noqa: E402

# (camera location, target, lens mm), left leg, Blender axes (x outboard, y aft, z up)
VIEWS = {"close": ((-0.15, 0.55, -1.22), (0.80, 2.00, -0.72), 38),
         "front": ((1.10, -1.60, -1.05), (0.90, 1.95, -0.78), 50),
         "fold": ((1.45, 4.15, -1.75), (0.72, 1.85, -0.62), 32)}
LEG = "L"


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


def light(scene, name, kind, loc, target, energy, size):
    data = bpy.data.lights.new(name, kind)
    data.energy = energy
    if kind == "AREA":
        data.size = size
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def look(scene, kind):
    if kind == "clay":
        scene.render.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light, sh.color_type, sh.single_color = "STUDIO", "SINGLE", (0.72, 0.70, 0.66)
        sh.show_cavity, sh.cavity_type, sh.show_shadows = True, "BOTH", False
        sh.use_world_space_lighting = False
        sh.background_type = "WORLD"
        scene.world.color = (0.16, 0.17, 0.19)
        return
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"


def slide(lift):
    """Slide the unsprung and the wheel straight up, as LandingGear does along its bump stop."""
    for name in ("gear_unsprung_" + LEG, "gear_wheel_%s_visible" % LEG):
        o = bpy.data.objects[name]
        o.matrix_world = Matrix.Translation(Vector((0, 0, lift))) @ o.matrix_world
    bpy.context.view_layer.update()


def shoot(scene, cam, view, path):
    loc, target, lens = VIEWS[view]
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--blend", type=Path)
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--skip-gif", action="store_true")
    ap.add_argument("--load", type=Path, help="render a saved --blend instead of building")
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
    import gear
    import uvs

    if args.blend and not args.load:
        bpy.ops.wm.save_as_mainfile(filepath=str(args.blend))
    for name in ("Colliders", "LOD1", "References"):
        col = bpy.data.collections.get(name)
        if col:
            col.hide_render = True
    for obj in bpy.data.objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    metal(uvs.SKIN, (0.40, 0.42, 0.45), 0.62, 0.5)
    metal("Fighter1_gear", (0.62, 0.64, 0.66), 0.35)
    metal("Mirror", (0.92, 0.92, 0.94), 0.06)
    metal("Aircraft_wheels", (0.03, 0.03, 0.03), 0.75, 0.0)
    metal("jet_mechanical", (0.16, 0.17, 0.18), 0.45, 0.6)
    metal("aircraft_structure", (0.30, 0.31, 0.33), 0.45, 0.6)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1280, 960, 100
    world = scene.world or bpy.data.worlds.new("review")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value, bg.inputs["Strength"].default_value = (0.05, 0.055, 0.065, 1), 1.0
    scene.view_settings.view_transform, scene.view_settings.look = "AgX", "AgX - Medium High Contrast"
    focus = (0.9, 1.95, -0.8)
    light(scene, "key", "AREA", (0.0, 0.0, -2.4), focus, 220, 1.5)
    light(scene, "rim", "AREA", (2.4, 4.2, -2.0), focus, 160, 1.2)
    light(scene, "fill", "AREA", (2.8, 0.6, -1.0), focus, 70, 2.0)
    cam = bpy.data.objects.new("leg_cam", bpy.data.cameras.new("leg_cam"))
    scene.collection.objects.link(cam)
    cam.data.clip_start = 0.01
    scene.camera = cam
    stroke = gear.GEAR_STROKE
    for kind in ("metal", "clay"):
        look(scene, kind)
        for view in ("close", "front"):
            for pose, lift in (("extended", 0.0), ("compressed", stroke)):
                slide(lift)
                shoot(scene, cam, view, args.out / ("%s_%s_%s_%s.png" % (args.label, kind, view, pose)))
                slide(-lift)
    if args.skip_gif:
        return
    ease = lambda t: 0.5 - 0.5 * math.cos(math.pi * t)
    folds = [ease(i / args.frames) for i in range(args.frames + 1)]
    folds = [0.0] * 4 + folds + [1.0] * 4 + folds[::-1]
    scene.render.resolution_x, scene.render.resolution_y = 800, 600
    for kind in ("metal", "clay"):
        look(scene, kind)
        frames = args.out / ("%s_%s_fold_frames" % (args.label, kind))
        frames.mkdir(exist_ok=True)
        for i, f in enumerate(folds):
            pose = {n: f for leg in gear.LEGS for n in ("gear_leg_" + leg, "gear_wheel_" + leg)}
            pose.update({d: 1.0 for leg in gear.LEGS for d in gear.doors_of(leg)})
            with gear.posed(pose):
                shoot(scene, cam, "fold", frames / ("f%03d.png" % i))
        gif = args.out / ("%s_%s_fold.gif" % (args.label, kind))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "12", "-i", str(frames / "f%03d.png"),
                        "-vf", "split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse", str(gif)], check=True)
    print("MAIN LEG REVIEW", args.out)


if __name__ == "__main__":
    main()
