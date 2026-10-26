"""Conformal shoe review: textured renders of the empty conformal trough, the missile gone and its mount's shoe left on
the trough floor, as the game shows it after launch.

The shoe is authored in Unity (IcarusAuthor.Stations.cs ShoeMesh), so this hangs it here from blockout's own corners
(stations.shoe) with the UVs the author gives it (--uv) on the game's jet_mechanical textures from tools/local-paths.json's
game export, which stay local.

Run through tools/Run-Blender.ps1 with --background --factory-startup --python-exit-code 1 --python
tools/review_conformal_rail.py -- --out <absolute folder> --label <before|after> --uv <metres|plain> [--res W H]. Blender
resolves relative paths from C:\\, so --out must be absolute.
"""
import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi  # noqa: E402

# The owner's two playtest angles, left trough, Blender axes (x outboard, y aft, z up): camera, target, lens mm.
VIEWS = {"below_aft": (bi.P(8.1, 1.1, -1.2), bi.P(7.2, 0.5, -0.35), 32),
         "below_forward": (bi.P(5.9, 1.25, -1.0), bi.P(7.25, 0.5, -0.38), 32)}
# The shoe UVs, by name: its unscaled metres and the plain dark patch of the jet_mechanical atlas
# (IcarusAuthor.Stations.cs ShoeUV).
UVS = {"metres": lambda x, y, z: (z, y + x),
       "plain": lambda x, y, z: (0.745 + 0.2 * z, 0.38 + 0.2 * (y + x))}


def jet_mechanical(export):
    """The game's jet_mechanical as Unity's Standard shader draws it: albedo times its tint, normal map, metallic from
    the red channel, smoothness 0 (its _GlossMapScale)."""
    mat = bpy.data.materials.new("review_jet_mechanical")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]

    def texture(name, linear):
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(export / "Texture2D" / name), check_existing=True)
        if linear:
            node.image.colorspace_settings.name = "Non-Color"
        return node

    tint = nodes.new("ShaderNodeMixRGB")
    tint.blend_type, tint.inputs[0].default_value = "MULTIPLY", 1.0
    tint.inputs[2].default_value = (0.849, 0.849, 0.849, 1)
    links.new(texture("jet_mechanical_AlbedoTransparency.png", False).outputs["Color"], tint.inputs[1])
    links.new(tint.outputs[0], bsdf.inputs["Base Color"])
    normal = nodes.new("ShaderNodeNormalMap")
    links.new(texture("jet_mechanical_n.png", True).outputs["Color"], normal.inputs["Color"])
    links.new(normal.outputs[0], bsdf.inputs["Normal"])
    split = nodes.new("ShaderNodeSeparateColor")
    links.new(texture("jet_mechanical_MetallicSmoothness.png", True).outputs["Color"], split.inputs[0])
    links.new(split.outputs[0], bsdf.inputs["Metallic"])
    bsdf.inputs["Roughness"].default_value = 1.0
    return mat


def hang_shoe(name, corners, hp, uv, mat):
    """ShoeMesh's box from its eight corners (mount frame, Unity axes), one quad per face, at Blender point hp."""
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (2, 3, 7, 6), (0, 4, 5, 1), (0, 2, 6, 4), (1, 5, 7, 3)]
    verts, faces, uvs = [], [], []
    for q in quads:
        start = len(verts)
        for i in q:
            x, y, z = corners[i]
            verts.append(Vector(hp) + Vector((-x, -z, y)))
            uvs.append(UVS[uv](x, y, z))
        faces.append(tuple(range(start, start + 4)))
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate()
    for p in me.polygons:  # face out from the box's centre
        if p.normal.dot(p.center - sum((Vector(v) for v in verts), Vector()) / len(verts)) < 0:
            p.flip()
    layer = me.uv_layers.new()
    for p in me.polygons:
        for li in p.loop_indices:
            layer.data[li].uv = uvs[me.loops[li].vertex_index]
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)


def main():
    import gear
    import review_gear_doors as doors
    import skin_review
    import stations
    from stores import paths

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--uv", required=True, choices=sorted(UVS))
    ap.add_argument("--res", nargs=2, type=int, default=(1400, 1050))
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not args.out.is_absolute():
        raise ValueError("--out must be absolute")
    args.out.mkdir(parents=True, exist_ok=True)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bi.build_cached()
    for name in ("Colliders", "LOD1", "References"):
        col = bpy.data.collections.get(name)
        if col:
            col.hide_render = True
    for obj in bpy.data.objects:
        if obj.get("role") == "cockpit_view":
            obj.hide_render = True
    skin_review.preview_material(1)
    doors.metal("jet_mechanical", (0.16, 0.17, 0.18), 0.45, 0.6)
    doors.metal("aircraft_structure", (0.30, 0.31, 0.33), 0.45, 0.6)
    doors.metal("Fighter1_gear", (0.62, 0.64, 0.66), 0.35)
    mat = jet_mechanical(paths.load()["game_export"])
    c = stations.CONFORMAL
    corners = stations.shoe(stations.MOUNTS["AAM1_single"])  # every mount's shoe is the same box
    for side in (1, -1):
        hang_shoe("shoe_%d" % side, corners, bi.P(c["s"], side * c["x"], c["z"]), args.uv, mat)
    scene = bpy.context.scene
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = args.res
    scene.render.resolution_percentage = 100
    world = scene.world or bpy.data.worlds.new("review")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value, bg.inputs["Strength"].default_value = (0.22, 0.32, 0.48, 1), 1.2
    scene.view_settings.view_transform, scene.view_settings.look = "AgX", "AgX - Medium High Contrast"
    scene.view_settings.exposure = -1.0
    doors.light(scene, "under", bi.P(7.0, 2.5, -3.5), bi.P(7.2, 0.5, -0.4), 250, 4.0)
    cam = bpy.data.objects.new("rail_cam", bpy.data.cameras.new("rail_cam"))
    scene.collection.objects.link(cam)
    cam.data.clip_start = 0.01
    scene.camera = cam
    stowed = {n: 1.0 for g in gear.LEGS for n in ("gear_leg_" + g, "gear_wheel_" + g)}
    for view, (loc, target, lens) in VIEWS.items():
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = lens
        scene.render.filepath = str(args.out / ("%s_%s.png" % (args.label, view)))
        with gear.posed(stowed):  # in flight: the doors shut over the stowed gear
            bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
