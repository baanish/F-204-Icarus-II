"""Render the Icarus with a tip tank on each Tip Tank station, and check the paint the tanks take.

pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/review_tip_tanks.py

Writes side, front and three-quarter views, a close-up of the left tip from ahead and above, and paint.json (each
livery's colour round the tank's upper and lower paint points, art/blender/tip_tanks.py PAINT, and its spread) under
.cache/review/share/tip_tanks/. The lenses glow red and green for the views; in game they follow the wing lenses.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi
import full_skin_review
import nav_visibility as nv
import review_sheet
import tip_tanks

OUT = REPO / ".cache/review/share/tip_tanks"
WINDOW = 3  # texels each way round a paint point


def paint_report():
    """Each livery's mean colour and its largest channel deviation in the window round both paint points."""
    tank = bpy.data.objects[tip_tanks.NAME]
    report = {}
    for livery in (1, 2, 3, 4):
        image = bpy.data.images.load(str(REPO / ("art/export/textures/Icarus_livery_%d.png" % livery)), check_existing=True)
        w, h = image.size
        pixels = np.empty(w * h * 4, np.float32)
        image.pixels.foreach_get(pixels)
        pixels = pixels.reshape(h, w, 4)[:, :, :3]
        for name, uv in zip(("upper", "lower"), tank["paint_uv"]):
            x, y = int(uv[0] * w), int(uv[1] * h)
            patch = pixels[y - WINDOW:y + WINDOW + 1, x - WINDOW:x + WINDOW + 1].reshape(-1, 3)
            mean = patch.mean(0)
            report["livery_%d_%s" % (livery, name)] = dict(uv=[round(c, 5) for c in uv], rgb_255=[round(float(c) * 255) for c in mean],
                                                         max_deviation_255=round(float(np.abs(patch - mean).max()) * 255, 1))
    return report


def lens(name, matrix, colour):
    _, lenses = nv.stock_geometry()
    verts, tris = lenses["L"]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Emission Color"].default_value = (*colour, 1)
    bsdf.inputs["Emission Strength"].default_value = 8
    obj = bi.mesh_object(name, [matrix @ nv.blender(v) for v in verts], tris[:, ::-1].tolist())
    obj.data.materials.append(mat)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bi.build_cached()
    icarus = bpy.data.collections["Icarus"]
    (OUT / "paint.json").write_text(json.dumps(paint_report(), indent=2) + "\n")
    full_skin_review.TEXTURES = REPO / "art/export/textures"
    full_skin_review.preview_material(bpy, 1, False)
    for obj in icarus.all_objects:
        if obj.type == "MESH":
            for index, material in enumerate(obj.data.materials):
                if material.name == "Icarus_NavFairing":
                    obj.data.materials[index] = bpy.data.materials["Icarus_Body"]
            if obj.name.startswith(("pylon_inner_L", "pylon_inner_R")):
                obj.hide_render = True
    for collection in ("Internals", "Colliders", "LOD1", "References"):
        if collection in bpy.data.collections:
            bpy.data.collections[collection].hide_render = True
    for name in ("Cube", "Light", "Camera"):  # the factory scene's own
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    tank = bpy.data.objects[tip_tanks.NAME]
    stations = tip_tanks.stations_world(icarus)
    bi.TARGET = bi.collection("TipTankReview")
    right = tank.copy()
    bi.TARGET.objects.link(right)
    right.matrix_world = stations["R"]
    for side, colour in (("L", (1, 0.002, 0.001)), ("R", (0.001, 1, 0.01))):
        for name, anchor in tip_tanks.lens_anchors().items():
            lens("tip_tank_lens_%s_%s" % (name, side), stations[side] @ anchor, colour)

    scene = review_sheet.setup_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("TipTankWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.16, 0.19, 0.24, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    scene.view_settings.view_transform = "AgX"
    for o in list(scene.objects):
        if o.type == "LIGHT":
            bpy.data.objects.remove(o, do_unlink=True)
    sun = bpy.data.objects.new("tip_tank_sun", bpy.data.lights.new("tip_tank_sun", "SUN"))
    scene.collection.objects.link(sun)
    sun.data.energy = 3
    sun.rotation_euler = (0.6, -0.4, -0.5)

    centre = Vector((0, 0, 0.3))
    views = {
        # name: (location, look-at, orthographic scale or None for perspective)
        "side": (Vector((40, 0.5, 0.3)), Vector((0, 0.5, 0.3)), 18.0),
        "front": (Vector((0, -40, 0.3)), Vector((0, 0, 0.3)), 9.0),
        "three_quarter": (centre + Vector((14.0, -17.0, 8.5)), centre, None),
        "tip_close": (stations["L"].translation + Vector((2.6, -4.2, 2.2)), stations["L"].translation + Vector((0, 0.3, 0)), None),
    }
    for name, (location, target, scale) in views.items():
        cam = review_sheet.camera("TipTankCam_" + name)
        cam.data.type = "ORTHO" if scale else "PERSP"
        if scale:
            cam.data.ortho_scale = scale
        cam.data.lens = 50
        cam.data.clip_end = 300
        cam.location = location
        cam.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
        review_sheet.render_view(scene, cam, str(OUT / (name + ".png")), (1600, 900))
    print("TIP TANK REVIEW: " + str(OUT))


if __name__ == "__main__":
    main()
