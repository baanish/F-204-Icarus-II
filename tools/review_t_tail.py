"""Measure the T-tail and render it skin on, from the side, behind, above and a chase three-quarter.

    pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 \
        --python tools/review_t_tail.py -- <label> [--scene <blend>]

--scene measures and renders a saved aircraft (a .cache/build-cache blend) instead of building this checkout's.

Writes .cache/review/share/t_tail/<label>.json (the fin's lift and drawn side areas and the station of fin_skin's area
centroid, where the game puts the fin's lift; the rudder's side area; the stabilator's planform area; the tail's
triangles and extent) and <label>_<view>.png. <label>_side_full.png is the whole aircraft from the left at PX_PER_M with
the radome tip at NOSE_PX, to set beside a three-view drawn at a known scale; <label>_stab_<deg>_side.png and _rear34.png
show the stabilator at both ends of its travel and at rest.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi
import budget
import full_skin_review
import parts
import review_sheet

PX_PER_M = 70.0
NOSE_PX = (60, 300)  # the radome tip in side_full.png, which is FULL_SIZE
FULL_SIZE = (1320, 400)


def planform_area(obj):
    """Area of a mesh seen from above, both faces halved, as IcarusAuthor.Aero.cs PlanformArea measures it."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    world = [obj.matrix_world @ v.co for v in mesh.vertices]
    total = 0.0
    for tri in mesh.loop_triangles:
        a, b, c = (world[i] for i in tri.vertices)
        total += abs((b - a).cross(c - a).z) / 2
    return total / 2


def centroid_s(obj):
    """Station of a mesh's area-weighted triangle centroid, as IcarusAuthor.Aero.cs AreaCentroid finds it."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    world = [obj.matrix_world @ v.co for v in mesh.vertices]
    total, moment = 0.0, 0.0
    for tri in mesh.loop_triangles:
        a, b, c = (world[i] for i in tri.vertices)
        area = (b - a).cross(c - a).length / 2
        total += area
        moment += area * (a.y + b.y + c.y) / 3
    return moment / total + bi.S0


def main():
    label = sys.argv[sys.argv.index("--") + 1]
    out = (REPO / ".cache/review/share/t_tail").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if "--scene" in sys.argv:
        bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index("--scene") + 1])
    else:
        bi.build_cached()
    icarus = bpy.data.collections["Icarus"]
    objects = icarus.all_objects
    tail = [objects[n] for n in ("fin_skin", "rudder_visible", "stabilator_visible")]
    result = dict(
        fin_lift_area_m2=objects["fin_skin"]["side_area_m2"],
        fin_drawn_side_area_m2=objects["fin_skin"].get("drawn_side_area_m2", objects["fin_skin"]["side_area_m2"]),
        fin_lift_s=round(centroid_s(objects["fin_skin"]), 4),
        rudder_side_area_m2=round(parts.side_area(objects["rudder_visible"]), 4),
        stabilator_planform_area_m2=round(planform_area(objects["stabilator_visible"]), 4),
        triangles={n: budget.tris(objects[n]) for n in ("fin_skin", "ventral_fin", "rudder_visible",
                                                        "stabilator_visible", "light_tail_fairing")},
        exterior_triangles=sum(budget.tris(o) for o in budget.meshes(icarus) if not budget.is_cockpit(o)),
        top_z=round(max((o.matrix_world @ v.co).z for o in tail for v in o.data.vertices), 4),
        aft_s=round(max((o.matrix_world @ v.co).y for o in tail for v in o.data.vertices) + bi.S0, 4),
    )
    (out / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")

    full_skin_review.TEXTURES = REPO / "art/export/textures"
    full_skin_review.preview_material(bpy, 1, False)
    for name in ("References", "Colliders", "LOD1", "Internals"):
        col = bpy.data.collections.get(name)
        if col:
            col.hide_render = True
    for obj in objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    cube = bpy.data.objects.get("Cube")  # --factory-startup's
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    scene = review_sheet.setup_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("TTailReviewWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.58, 0.62, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
    scene.view_settings.exposure = 0.6
    for obj in list(scene.objects):
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)
    sun = bpy.data.objects.new("t_tail_sun", bpy.data.lights.new("t_tail_sun", "SUN"))
    scene.collection.objects.link(sun)
    sun.data.energy = 2.5
    sun.rotation_euler = (0.5, -0.6, -0.5)

    def shoot(name, location, target, scale=None, lens=50, res=(1400, 1100)):
        cam = review_sheet.camera("t_tail_" + name)
        cam.data.type = "ORTHO" if scale else "PERSP"
        if scale:
            cam.data.ortho_scale = scale
        else:
            cam.data.lens = lens
        cam.data.clip_start, cam.data.clip_end = 0.05, 200
        cam.location = location
        cam.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
        review_sheet.render_view(scene, cam, str(out / ("%s_%s.png" % (label, name))), res)

    target = bi.P(15.2, 0, 1.9)
    shoot("side", target + Vector((20, 0, 0)), target, 5.0)  # from the left (+x), nose to the left as the three-view
    shoot("behind", target + Vector((0, 20, 0)), target, 5.0)
    shoot("above", target + Vector((0, 0, 20)), target, 5.0)
    shoot("chase", bi.P(22.5, 5.5, 5.2), bi.P(14.8, 0, 2.0), lens=45)
    width = FULL_SIZE[0] / PX_PER_M
    height = FULL_SIZE[1] / PX_PER_M
    centre_s = (FULL_SIZE[0] / 2 - NOSE_PX[0]) / PX_PER_M
    centre_z = (NOSE_PX[1] - FULL_SIZE[1] / 2) / PX_PER_M + bi.PARAMS["fuselage"][0][2]
    full = bi.P(centre_s, 0, centre_z)
    shoot("side_full", full + Vector((30, 0, 0)), full, max(width, height), res=FULL_SIZE)
    # the stabilator at both ends of its travel and between, round its hinge's X (positive raises the trailing edge)
    hinge = objects["stabilator"]
    rest = hinge.matrix_world.copy()
    travel = hinge["deflection_deg"]
    tip = bi.P(15.4, 0, 2.8)
    for deg in (-travel, 0, travel):
        hinge.matrix_world = rest @ Matrix.Rotation(math.radians(deg), 4, "X")
        bpy.context.view_layer.update()
        shoot("stab_%+d_side" % deg, tip + Vector((10, 0, 0)), tip, 2.6, res=(1200, 800))
        shoot("stab_%+d_rear34" % deg, bi.P(18.2, 1.8, 3.7), tip, lens=50, res=(1200, 800))
    hinge.matrix_world = rest
    print("T TAIL REVIEW " + label + ": " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
