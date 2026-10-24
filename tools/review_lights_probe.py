"""Textured review renders of the formation lenses and the nose probe, beside the Revoker's own formation strips.

Run through tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python
tools/review_lights_probe.py -- <absolute output folder> [--samples N]. The Revoker meshes and textures come from the
local game export (tools/local-paths.json) for this review only; nothing from them is written to source assets.
"""
import argparse
import re
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "art/blender"), str(REPO / "tools")]
import build_icarus as bi
import skin_review
from stores import paths
from stores.bodies import mesh_path
from stores.prefab_tree import asset_index

# The Revoker parts round its cockpit and their positions in its root frame (prefab_tree.py Fighter1; no rotations).
REVOKER = {"fighter1_cockpit": (0, -0.01, 7.18), "fighter1_slimelights_F": (0, -0.01, 7.18),
           "fighter1_nose": (0, -0.371, 9.528), "fighter1_fuselage": (0, 0.043, 3.337),
           "fighter1_intake_L": (-1.058, -0.597, 5.117), "fighter1_cheek_L": (-1.175, 0.054, 5.631)}
REVOKER_OFFSET = Vector((40.0, 0.0, 0.0))
LENS = bi.P(4.0, 0.47, -0.24)  # where the forward lenses sit on the left side
# name: (camera location, target, lens mm); the Icarus's left side is +X, its nose -Y.
VIEWS = {
    "owner_angle": (Vector((2.35, -2.35, 0.40)), bi.P(6.3, 0.6, 0.15), 50),
    "formation_side": (Vector((4.6, -4.4, 0.6)), bi.P(4.6, 0.4, 0.0), 35),
    "formation_close": (LENS + Vector((1.15, -0.35, -0.62)), LENS, 35),
    "probe_side": (Vector((1.6, -9.0, 0.7)), bi.P(-0.4, 0.0, 0.03), 35),
    "probe_from_cockpit": (Vector((0.45, -6.75, 0.85)), bi.P(-0.6, 0.0, 0.0), 50),
}


def unity_to_blender(v):
    return Vector((-v[0], -v[2], v[1]))


def read_mesh(path):
    """Positions, UV0 and per-submesh triangles of an AssetRipper YAML mesh (float32 channels in stream 0)."""
    text = Path(path).read_text(errors="replace")
    vertex = text[text.index("m_VertexData:"):]
    count = int(re.search(r"m_VertexCount: (\d+)", vertex)[1])
    channels = [tuple(map(int, c)) for c in re.findall(
        r"- stream: (\d+)\s+offset: (\d+)\s+format: (\d+)\s+dimension: (\d+)", vertex.split("m_DataSize")[0])]
    sizes = {0: 4, 1: 2, 2: 1}
    stride = max(c[1] + sizes[c[2]] * (c[3] & 0xF) for c in channels if c[0] == 0 and c[3] & 0xF)
    raw = bytes.fromhex(re.search(r"_typelessdata: ([0-9a-f]+)", vertex)[1])
    pos = [struct.unpack_from("<3f", raw, i * stride + channels[0][1]) for i in range(count)]
    uv = [struct.unpack_from("<2f", raw, i * stride + channels[4][1]) for i in range(count)] if channels[4][3] else None
    index = bytes.fromhex(re.search(r"m_IndexBuffer: ([0-9a-f]*)", text)[1])
    wide = re.search(r"m_IndexFormat: (\d)", text)[1] == "1"
    submeshes = []
    for m in re.finditer(r"firstByte: (\d+)\s+indexCount: (\d+)\s+topology: (\d+)\s+baseVertex: (\d+)",
                         text.split("m_Shapes:")[0]):
        first, n, _, base = map(int, m.groups())
        ids = struct.unpack_from("<%d%s" % (n, "I" if wide else "H"), index, first)
        submeshes.append([tuple(base + i for i in ids[k:k + 3]) for k in range(0, n, 3)])
    return pos, uv, submeshes


def textured(name, folder, files):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]

    def image(key, linear):
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(folder / files[key]), check_existing=True)
        if linear:
            node.image.colorspace_settings.name = "Non-Color"
        return node

    links.new(image("b", False).outputs["Color"], bsdf.inputs["Base Color"])
    metal = nodes.new("ShaderNodeSeparateColor")
    m = image("m", True)
    links.new(m.outputs["Color"], metal.inputs[0])
    links.new(metal.outputs["Red"], bsdf.inputs["Metallic"])
    rough = nodes.new("ShaderNodeMath")
    rough.operation = "SUBTRACT"
    rough.inputs[0].default_value = 1
    links.new(m.outputs["Alpha"], rough.inputs[1])
    links.new(rough.outputs[0], bsdf.inputs["Roughness"])
    normal = nodes.new("ShaderNodeNormalMap")
    links.new(image("n", True).outputs["Color"], normal.inputs["Color"])
    links.new(normal.outputs[0], bsdf.inputs["Normal"])
    return mat


def load_revoker(lens_material):
    root = paths.load()["game_export"]
    index = asset_index(root, "Mesh")
    skin = textured("review_fighter1_skin", root / "Texture2D",
                    {"b": "fighter1_skin_b.png", "m": "fighter1_skin_m.png", "n": "fighter1_skin_n.png"})
    other = bpy.data.materials.new("review_fighter1_trim")
    other.diffuse_color = (0.2, 0.2, 0.2, 1)
    made = []
    for name, at in REVOKER.items():
        pos, uv, submeshes = read_mesh(mesh_path(index, name))
        verts = [unity_to_blender(Vector(at) + Vector(p)) + REVOKER_OFFSET for p in pos]
        faces = [t[::-1] for sub in submeshes for t in sub]  # Unity winds clockwise
        obj = bi.mesh_object("review_" + name, verts, faces)
        obj.data.materials.append(lens_material if "slimelights" in name else skin)
        obj.data.materials.append(other)
        start = 0
        for k, sub in enumerate(submeshes):
            for f in obj.data.polygons[start:start + len(sub)]:
                f.material_index = min(k, 1)
            start += len(sub)
        if uv:
            layer = obj.data.uv_layers.new(name="UVMap")
            for loop in obj.data.loops:
                layer.data[loop.index].uv = uv[loop.vertex_index]
        obj.data.shade_smooth()
        made.append(obj)
    strip = bpy.data.objects["review_fighter1_slimelights_F"]
    left = [strip.matrix_world @ v.co for v in strip.data.vertices if v.co.x > REVOKER_OFFSET.x]
    return sum(left, Vector()) / len(left)


def flat(name, rgba, metallic, roughness, emission=None):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        colour, strength = emission
        bsdf.inputs["Emission Color"].default_value = colour
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def setup(samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == "OPTIX"
        scene.cycles.device = "GPU" if any(d.use for d in prefs.devices) else "CPU"
    except (TypeError, RuntimeError):
        scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
    scene.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("review_world")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    nodes.clear()
    env = nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(Path(bpy.utils.resource_path("LOCAL")) / "datafiles/studiolights/world/courtyard.exr"))
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.8
    output = nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(env.outputs[0], background.inputs[0])
    world.node_tree.links.new(background.outputs[0], output.inputs[0])
    sun = bpy.data.objects.new("review_sun", bpy.data.lights.new("review_sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.0, 0.01
    sun.rotation_euler = Vector((6, -8, 12)).to_track_quat("Z", "Y").to_euler()
    scene.collection.objects.link(sun)
    camera = bpy.data.objects.new("review_camera", bpy.data.cameras.new("review_camera"))
    camera.data.sensor_width, camera.data.clip_start = 36, 0.02
    scene.collection.objects.link(camera)
    scene.camera = camera
    return scene, camera


def render(scene, camera, location, target, lens, path):
    camera.location = location
    camera.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = lens
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print("RENDERED", path, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--samples", type=int, default=64)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    bi.build_cached()
    for name in ("Internals", "Colliders", "LOD1", "References"):
        if bpy.data.collections.get(name):
            bpy.data.collections[name].hide_render = True
    # The stock values each slot maps to in Unity (IcarusAuthor.Materials.cs, the game's light_green_off and slimelight_on).
    off = (0.4729, 0.6118, 0.5372, 1)
    lens = flat("light_green_off", off, 1.0, 1 - 0.594)
    flat("Icarus_Strut", (0.708, 0.716, 0.723, 1), 1.0, 0.25)
    flat("Icarus_Frame", (0.032, 0.034, 0.038, 1), 0.6, 0.5)
    scene, camera = setup(args.samples)
    stock_lens = load_revoker(lens)
    normal = Vector((0.89, 0, -0.46)).normalized()
    stock_camera = stock_lens + normal * 1.3 + Vector((0, -0.35, 0))

    def lit(on):
        bsdf = lens.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1) if on else off
        bsdf.inputs["Metallic"].default_value = 0 if on else 1
        bsdf.inputs["Emission Color"].default_value = (0.047 / 3, 1.0, 0.33 / 3, 1)
        bsdf.inputs["Emission Strength"].default_value = 2.996 if on else 0

    skin_review.preview_material(1)
    for state in ("off", "lit"):
        lit(state == "lit")
        for view in ("owner_angle", "formation_side", "formation_close"):
            render(scene, camera, *VIEWS[view], out / f"{view}_{state}.png")
        render(scene, camera, stock_camera, stock_lens, 35, out / f"revoker_formation_close_{state}.png")
    lit(False)
    for livery in (1, 4):
        skin_review.preview_material(livery)
        for view in ("probe_side", "probe_from_cockpit"):
            render(scene, camera, *VIEWS[view], out / f"{view}_livery{livery}.png")
    print("LIGHTS PROBE REVIEW PASS: " + str(out))


if __name__ == "__main__":
    main()
