"""Compare historical and current intake/wing-root skin with matched cameras.

Run through tools/Run-Blender.ps1. All output paths must be absolute.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def inspect_skin(objects):
    report = {}
    for obj in objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        bm.normal_update()
        edges = []
        for edge in bm.edges:
            at = sum((v.co for v in edge.verts), Vector()) / 2
            if .55 < abs(at.x) < 1.05 and .5 < at.y < 3.5 and -.15 < at.z < .55:
                angle = edge.calc_face_angle(0.0)
                edges.append({"at": list(at), "length_m": edge.calc_length(),
                              "faces": len(edge.link_faces), "angle_deg": angle * 180 / 3.141592653589793})
        if edges:
            report[obj.name] = {"vertices": len(bm.verts), "faces": len(bm.faces),
                                "triangles": sum(len(f.verts) - 2 for f in bm.faces),
                                "local_boundary_edges": sum(e["faces"] == 1 for e in edges),
                                "local_edges": sorted(edges, key=lambda e: -e["angle_deg"])}
        bm.free()
    return report


def render(out, label, objects):
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    for name in ("References", "Colliders", "LOD1"):
        col = bpy.data.collections.get(name)
        if col:
            col.hide_render = True
    for obj in objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1536, 1000, 100
    shading = scene.display.shading
    shading.light, shading.color_type = "STUDIO", "MATERIAL"
    shading.show_shadows = False
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    shading.background_type = "WORLD"
    scene.world.color = (.12, .22, .28)
    camera = bpy.data.objects.new("Wingroot_review_camera", bpy.data.cameras.new("Wingroot_review_camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    views = {"owner_close": ((4.8, -.8, 1.8), (.78, .8, .16), 4.1),
             "owner_side": ((5.8, 1.2, 1.4), (.72, 1.7, .12), 6.0)}
    for name, (location, target, scale) in views.items():
        camera.location = location
        camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.type, camera.data.ortho_scale = "ORTHO", scale
        scene.render.filepath = str(out / (label + "_" + name + ".png"))
        bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--skin-only", action="store_true")
    parser.add_argument("--uncut", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--blend", type=Path)
    parser.add_argument("--expect-notch", action="store_true", help="Require the junction check to reject this historical mesh")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not args.out.is_absolute() or not args.repo.is_absolute():
        raise ValueError("repo and output paths must be absolute")
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.repo / "art/blender"))
    sys.path.insert(0, str(args.repo / "tools"))
    import build_icarus as bi
    report = {"repo": str(args.repo), "label": args.label, "blend": str(args.blend) if args.blend else None}
    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=str(args.blend))
    elif args.skin_only:
        import gear
        import materials
        bi.TARGET = bi.collection("Icarus")
        mats = materials.build()
        obj = bi.build_fuselage(bi.PARAMS, mats["body"], mats["duct"])
        report["before_doors"] = inspect_skin([obj])
        report["skin_rings"] = [[list(v.co) for v in obj.data.vertices[1 + j * bi.RING:1 + (j + 1) * bi.RING]]
                                for j in range((len(obj.data.vertices) - 1) // bi.RING)]
        if not args.uncut:
            gear.cut_doors(obj)
        bi.build_surfaces(bi.PARAMS, mats)
    else:
        import cockpit
        cockpit.REPO = str(args.out / (args.label + "_generated"))
        bi.build()
    objects = list(bpy.data.collections["Icarus"].all_objects)
    spec = importlib.util.spec_from_file_location("wingroot_checks", Path(__file__).resolve().parents[1] / "art/blender/checks.py")
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    try:
        report["junction_check"] = checks.intake_wing_junction(bpy.data.collections["Icarus"])
    except ValueError as exc:
        report["junction_check"] = {"failure": str(exc)}
        print(str(exc), flush=True)
    report["topology"] = inspect_skin(objects)
    import uvs
    atlas = {obj.name: hashlib.sha256(repr([(tuple(obj.data.loops[d].vertex_index for d in f.loop_indices),
                                           [tuple(obj.data.uv_layers.active.data[d].uv) for d in f.loop_indices])
                                          for f in uvs.skin_faces(obj)]).encode()).hexdigest()
             for obj in uvs.skin_objects(bpy.data.collections["Icarus"])
             if obj.data.uv_layers.active}
    report["skin_uv_sha256"] = atlas
    colliders = bpy.data.collections.get("Colliders")
    report["collider_mesh_sha256"] = {
        obj.name: hashlib.sha256(repr(([tuple(v.co) for v in obj.data.vertices],
                                      [tuple(f.vertices) for f in obj.data.polygons])).encode()).hexdigest()
        for obj in colliders.all_objects if obj.type == "MESH"} if colliders else {}
    report["collider_world_vertices_um"] = {
        obj.name: sorted({tuple(round(c, 6) for c in obj.matrix_world @ v.co) for v in obj.data.vertices})
        for obj in colliders.all_objects if obj.type == "MESH"} if colliders else {}
    (args.out / (args.label + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    failed = "failure" in report["junction_check"]
    if failed != args.expect_notch:
        raise ValueError(report["junction_check"].get("failure", "expected a notch, but the junction check passed"))
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out / (args.label + ".blend")))
    render(args.out, args.label, objects)
    if args.export:
        import export_blockout
        bi.build = lambda: None
        sys.argv = [__file__, "--", "--out", str(args.out / (args.label + "_export"))]
        export_blockout.main()


if __name__ == "__main__":
    main()
