"""Measure and render loaded wingtip lamps. Run in Blender through Run-Blender.ps1.

-- before|after writes six lit PNGs and a visibility JSON under
.cache/review/share/navlights/. Uses local stock meshes only for review.
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
import budget
import nav_visibility as nv
import review_sheet
import stations
import full_skin_review
from stores.geometry import axis_quat


def preview(name, mesh, colour, lit=False):
    verts, tris = mesh
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*colour, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    if lit:
        bsdf.inputs["Emission Color"].default_value = (*colour, 1)
        bsdf.inputs["Emission Strength"].default_value = 8
    obj = bi.mesh_object(name, [nv.blender(v) for v in verts], tris[:, ::-1].tolist())
    obj.data.materials.append(mat)


def main():
    label = sys.argv[sys.argv.index("--") + 1]
    out = (REPO / ".cache/review/share/navlights").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if "--scene" in sys.argv:
        bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index("--scene") + 1])
    else:
        bi.build_cached()
    icarus = bpy.data.collections["Icarus"]
    bi.TARGET = icarus
    if icarus.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(icarus)
    result = nv.measure(icarus)
    result["exterior_triangles"] = sum(budget.tris(o) for o in budget.meshes(icarus) if not budget.is_cockpit(o))
    result["stock_nav_triangles"] = len(result["positions_unity"]) * 14
    (out / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    mounts, lenses = nv.stock_geometry()
    station_data = nv.tip_stations(icarus)
    clearance_meshes = nv.lamp_meshes(icarus, lenses)
    for obj in icarus.all_objects:
        if obj.name.startswith("light_nav_mount_"):
            obj.data.calc_loop_triangles()
            clearance_meshes[obj.name] = (np.array([nv.unity(obj.matrix_world @ v.co) for v in obj.data.vertices]),
                                         np.array([list(t.vertices) for t in obj.data.loop_triangles]))
    snapshot = dict(lamps={n: dict(vertices=v.tolist(), triangles=t.tolist()) for n, (v, t) in clearance_meshes.items()},
                    tip_stations={"hardpoint_wingtip_" + s: dict(position=p.tolist(), rotation=axis_quat((0, 0, 1), -90 if s == "L" else 90))
                                  for s, (p, r) in station_data.items()},
                    tip_faces={s: abs(float(p[0])) + 0.005 for s, (p, r) in station_data.items()})
    (out / (label + "-clearance.json")).write_text(json.dumps(snapshot, indent=2) + "\n")
    full_skin_review.TEXTURES = REPO / "art/export/textures"
    full_skin_review.preview_material(bpy, 1, False)
    for obj in icarus.all_objects:
        if obj.type == "MESH":
            for index, material in enumerate(obj.data.materials):
                if material.name == "Icarus_NavFairing":
                    obj.data.materials[index] = bpy.data.materials["Icarus_Body"]
    bi.TARGET = bi.collection("NavReview")
    largest = max(mounts, key=lambda k: np.prod(np.ptp(mounts[k][0][0], axis=0)))
    for side, (pos, rot) in nv.tip_stations(icarus).items():
        mesh = mounts[largest][0]
        preview("review_store_" + side, (pos + mesh[0] @ rot.T, mesh[1]), (0.5, 0.52, 0.48))
    for name, mesh in nv.lamp_meshes(icarus, lenses).items():
        preview("review_" + name, mesh, (1, 0.002, 0.001) if name.endswith("_L") else (0.001, 1, 0.01), True)
    scene = review_sheet.setup_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.world = bpy.data.worlds.new("NavReviewWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    scene.view_settings.exposure = 0.7
    for o in list(scene.objects):
        if o.type == "LIGHT":
            bpy.data.objects.remove(o, do_unlink=True)
    sun = bpy.data.objects.new("review_sun", bpy.data.lights.new("review_sun", "SUN"))
    scene.collection.objects.link(sun)
    sun.data.energy = 2
    sun.rotation_euler = (0.4, -0.5, -0.4)
    for side, sign in (("L", 1), ("R", -1)):
        wing = bi.PARAMS["wing"]
        x = wing["planform"][-1][1] - 0.075
        leading, z, chord = stations.wing_at(wing, x)
        target = bi.P(leading + chord * 0.35, sign * x, z + bi.airfoil(0.35) * wing["thickness"] * chord)
        for view, offset in (("above", (sign * 1.8, -1.5, 3)), ("below", (sign * 1.8, -1.5, -3)), ("ahead", (0, -4, 0))):
            cam = review_sheet.camera("nav_review")
            cam.data.type, cam.data.ortho_scale = "ORTHO", 3.4
            cam.location = target + Vector(offset)
            cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
            review_sheet.render_view(scene, cam, str(out / (label + "_" + side + "_" + view + ".png")), (1200, 900))
    print("NAV REVIEW: " + str(out) + ", largest store " + largest)


if __name__ == "__main__":
    main()
