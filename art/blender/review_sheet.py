"""Render the review views for one exterior iteration into a folder.

Top, side and front are orthographic at the scale and framing of the reference drawings, so tools/compose_review.py
can overlay the model on them pixel for pixel. A three-quarter view is added for the look. Uses Workbench, so a
render takes seconds and needs no GPU time next to the game.

    render(out_dir)                      # inside a live session, after build_icarus.build()
    blender --background --python art/blender/review_sheet.py -- <out_dir>
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_icarus  # noqa: E402

SUPERSAMPLE = 2


def camera(name):
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        bpy.context.scene.collection.objects.link(cam)
        cam.hide_viewport = True  # renders still use it; the owner's viewport stays clean
    return cam


def setup_scene():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_object_outline = True
    shading.show_cavity = True
    shading.cavity_type = "WORLD"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    refs = bpy.data.collections.get("References")
    if refs:
        refs.hide_render = True
    return scene


def render_view(scene, cam, path, res):
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def ortho(scene, out_dir, view, spec, repo):
    img_path = os.path.join(repo, build_icarus.PARAMS["references"]["dir"], spec["file"])
    img = bpy.data.images.load(img_path, check_existing=True)
    w, h = img.size
    k = spec["px_per_m"]
    cx, cy = w / 2, h / 2
    cam = camera("ReviewCam_" + view)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(w, h) / k
    cam.data.clip_end = 200
    s0 = build_icarus.S0
    if view == "top":
        nx, ny = spec["nose_px"]
        cam.rotation_euler = (0, 0, math.radians(90))
        cam.location = ((cy - ny) / k, -s0 + (cx - nx) / k, 50)
    elif view == "side":
        nx, ny = spec["nose_px"]
        cam.rotation_euler = (math.radians(90), 0, math.radians(90))
        cam.location = (50, -s0 + (cx - nx) / k, (ny - cy) / k)
    else:
        ux, uy = spec["centre_px"]
        cam.rotation_euler = (math.radians(90), 0, 0)
        cam.location = ((cx - ux) / k, -50, (uy - cy) / k)
    render_view(scene, cam, os.path.join(out_dir, view + ".png"), (w * SUPERSAMPLE, h * SUPERSAMPLE))


def three_quarter(scene, out_dir):
    cam = camera("ReviewCam_34")
    cam.data.type = "PERSP"
    cam.data.lens = 50
    target = Vector((0, 0, 0.6))
    cam.location = target + Vector((14.0, -17.0, 8.5))  # front left, above
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    render_view(scene, cam, os.path.join(out_dir, "three_quarter.png"), (1600, 900))


# Close-ups for details a full view hides: name -> (camera location, look-at point), Blender axes.
CLOSEUPS = {
    "intake": (Vector((3.2, -6.6, 1.0)), Vector((0.8, -1.2, 0.2))),
    "tail": (Vector((4.5, 4.0, 5.5)), Vector((0.0, 7.8, 2.4))),
    "intake_head_on": (Vector((0.8, -16.0, 0.22)), Vector((0.8, -1.0, 0.22))),
}


def closeups(scene, out_dir):
    for name, (loc, target) in CLOSEUPS.items():
        cam = camera("ReviewCam_" + name)
        cam.data.type = "PERSP"
        cam.data.lens = 200 if name.endswith("head_on") else 50
        cam.location = loc
        cam.rotation_euler = (target - loc).to_track_quat("-Z", "Y").to_euler()
        render_view(scene, cam, os.path.join(out_dir, name + ".png"), (1200, 800))


def render(out_dir, repo=None):
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.makedirs(out_dir, exist_ok=True)
    scene = setup_scene()
    refs = build_icarus.PARAMS["references"]
    for view in ("top", "side", "front"):
        ortho(scene, out_dir, view, refs[view], repo)
    three_quarter(scene, out_dir)
    closeups(scene, out_dir)
    return {"out": out_dir, "files": sorted(os.listdir(out_dir))}


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    build_icarus.build()
    print("icarus review:", render(args[0] if args else os.path.abspath(".cache/review/latest")))
