"""Render matching lit tail views and record geometry and skin UVs.

Run through tools/Run-Blender.ps1 with -- before or -- after.
Local game meshes are review references only.
"""
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi
import budget
import full_skin_review
import review_sheet
import uvs


def main():
    label = sys.argv[sys.argv.index("--") + 1]
    out = (REPO / ".cache/review/share/tail_light").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if "--scene" in sys.argv:
        bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index("--scene") + 1])
    else:
        bi.build_cached()
    icarus = bpy.data.collections["Icarus"]
    fingerprint = hashlib.sha256()
    for obj in uvs.skin_objects(icarus):
        fingerprint.update(obj.name.encode())
        for face in uvs.skin_faces(obj):
            for index in face.loop_indices:
                fingerprint.update(bytes(str(tuple(obj.data.uv_layers["UVMap"].data[index].uv)), "ascii"))
    result = dict(exterior_triangles=sum(budget.tris(o) for o in budget.meshes(icarus) if not budget.is_cockpit(o)),
                  reference_triangles=sum(o.get("reference_triangles", 0) for o in icarus.all_objects),
                  skin_uv_sha256=fingerprint.hexdigest())
    if "light_nav_aft" in icarus.all_objects:
        import nav_visibility
        result["aft"] = nav_visibility.measure_aft(icarus)
    (out / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / (label + ".blend")))
    full_skin_review.TEXTURES = REPO / "art/export/textures"
    full_skin_review.preview_material(bpy, 1, False)
    for obj in icarus.all_objects:
        if obj.type == "MESH":
            for index, material in enumerate(obj.data.materials):
                if material.name == "Icarus_NavFairing":
                    obj.data.materials[index] = bpy.data.materials["Icarus_Body"]
    lamp = bpy.data.objects.get("light_nav_aft")
    if lamp and lamp.type == "MESH":
        material = bpy.data.materials.new("review_white_lit")
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
        bsdf.inputs["Emission Color"].default_value = (1, 1, 1, 1)
        bsdf.inputs["Emission Strength"].default_value = 8
        lamp.data.materials[0] = material
    scene = review_sheet.setup_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.world = bpy.data.worlds.new("TailReviewWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    scene.view_settings.exposure = 0.7
    for obj in list(scene.objects):
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)
    sun = bpy.data.objects.new("review_sun", bpy.data.lights.new("review_sun", "SUN"))
    scene.collection.objects.link(sun)
    sun.data.energy = 2
    sun.rotation_euler = (0.4, -0.5, -0.4)
    target = bi.P(15.6, 0, 1.8)
    for view, offset in (("behind", (0, 8, 0)), ("side", (8, 0, 0)), ("above", (0, 1, 8))):
        cam = review_sheet.camera("tail_review")
        cam.data.type, cam.data.ortho_scale = "ORTHO", 4.4
        cam.location = target + Vector(offset)
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        review_sheet.render_view(scene, cam, str(out / (label + "_" + view + ".png")), (1400, 1100))
    print("TAIL REVIEW " + label + ": " + json.dumps({key: value for key, value in result.items() if key != "aft"}), flush=True)


if __name__ == "__main__":
    main()
