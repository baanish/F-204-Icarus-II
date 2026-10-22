"""Build P7 proving views and its Blender-side rule 14 snapshot, using stock meshes only for local review.

Run through tools/Run-Blender.ps1 with --background --factory-startup --python-exit-code 1 --python
tools/review_lights.py -- [output-folder]. No stock geometry or textures are written to source assets.
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi
import review_sheet
from stores import paths
from stores.geometry import axis_quat, quat_matrix
from stores.lights import stock_lens
from stores.mounts import load_mount
from stores.prefab_tree import asset_index


def unity(v):
    return [-v[0], v[2], -v[1]]


def blender(v):
    return Vector((-v[0], -v[2], v[1]))


def preview(name, mesh, colour):
    verts, tris = mesh
    material = bpy.data.materials.new(name + "_review_colour")
    material.diffuse_color = colour
    obj = bi.mesh_object(name, [blender(v) for v in verts], tris.tolist())
    obj.data.materials.append(material)
    return obj


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = Path(args[0]) if args else REPO / ".cache/review/wave2/p7/01"
    out.mkdir(parents=True, exist_ok=True)
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    bi.build()
    root = paths.load()["game_export"]
    index = asset_index(root, "Mesh")
    mount, _ = load_mount(root, index, "AAM1_single")
    snapshot = {"nav_anchors": {}, "tip_stations": {}, "tip_faces": {}}
    for side, sign in (("L", -1), ("R", 1)):
        anchor = unity(bpy.data.objects["light_nav_" + side].matrix_world.translation)
        snapshot["nav_anchors"][side] = anchor
        wing = bpy.data.objects["wing_skin_" + side]
        verts = np.asarray([unity(wing.matrix_world @ v.co) for v in wing.data.vertices])
        outer = np.abs(verts[:, 0]).max()
        tip = verts[np.abs(verts[:, 0]) > outer - 0.001]
        leading, trailing = tip[:, 2].max(), tip[:, 2].min()
        pos = np.array([sign * (outer - 0.005), (tip[:, 1].max() + tip[:, 1].min()) / 2,
                        leading - 0.545 * (leading - trailing)])
        rotation = axis_quat((0, 0, 1), sign * 90)
        snapshot["tip_stations"]["hardpoint_wingtip_" + side] = {"position": pos.tolist(), "rotation": rotation}
        snapshot["tip_faces"][side] = float(outer)
        preview("review_stock_navlight_" + side, stock_lens(index, side, anchor),
                (0.7, 0.02, 0.01, 1) if side == "L" else (0.02, 0.6, 0.05, 1))
        preview("review_stock_MMR_S3_" + side, (pos + mount[0] @ quat_matrix(rotation).T, mount[1]), (0.7, 0.72, 0.70, 1))
    (out / "lights-blockout.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    scene = review_sheet.setup_scene()
    bpy.data.materials["light_green_off"].diffuse_color = (0.38, 0.48, 0.25, 1)

    def render(name, target, offset, scale):
        cam = review_sheet.camera("P7_" + name)
        cam.data.type, cam.data.ortho_scale = "ORTHO", scale
        cam.location = target + offset
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        review_sheet.render_view(scene, cam, str(out / (name + ".png")), (1600, 1000))

    for side, sign in (("L", 1), ("R", -1)):
        target = blender(snapshot["nav_anchors"][side])
        render("tip_" + side + "_MMR_S3", target, Vector((sign * 2.2, -1.8, 1.8)), 3.6)
        render("tip_" + side + "_lens", target, Vector((sign * 1.5, -1.3, 1.2)), 0.65)
    strip = bpy.data.objects["light_formation_L"]
    target = sum((strip.matrix_world @ v.co for v in strip.data.vertices), Vector()) / len(strip.data.vertices)
    render("formation_strip", target, Vector((1.8, -0.7, 0.4)), 0.85)
    print("P7 REVIEW PASS: " + str(out.resolve()))


if __name__ == "__main__":
    main()
