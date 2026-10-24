"""Render the exterior (LOD0) beside the LOD1 hulls in two liveries, to see whether the hulls keep the paint.

    pwsh -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/review_lod_livery.py -- --label after
    python -I tools/review_lod_livery.py <before_label> <after_label>

In Blender it renders the built aircraft (build_cached) into .cache/review/share/lod_livery/<label>/ (or --out, an
absolute path, to render another checkout's build into this one's sheet), the livery's
albedo on the Icarus_Body slot (livery 1, PALA Navy, and livery 4, PALA Bare Metal), the other slots in their own
colours. Outside Blender it composes the two labels into one sheet per view: rows per livery, columns LOD0, then
LOD1 of each label. A hull still on the stock LOD slot draws flat light grey, as the game's LOD shader drew it.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".cache/review/share/lod_livery"
LIVERIES = ((1, "PALA Navy"), (4, "PALA Bare Metal"))
VIEWS = ("whole", "nose")
SIZE = (960, 600)
LOD_GREY = (0.62, 0.62, 0.62, 1.0)


def render(label, out_root):
    import bpy
    from mathutils import Vector

    sys.path.insert(0, str(ROOT / "art/blender"))
    import build_icarus as bi

    bi.build_cached()
    for name in ("References", "Colliders", "Internals"):
        bpy.data.collections[name].hide_render = True
    for name in ("Cube", "Light", "Camera"):  # factory startup's scene
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name])
    bpy.data.collections["LOD1"].hide_render = False
    lod1 = [o for o in bpy.data.collections["LOD1"].objects]
    for o in lod1:
        o.display_type = "TEXTURED"  # hulls.build draws them as wires, which Workbench renders as such
    lod0 = [o for o in bpy.data.collections["Icarus"].all_objects if o.type == "MESH" and not o.hide_render]
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_cavity = False
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.film_transparent = False
    scene.world = scene.world or bpy.data.worlds.new("World")
    scene.world.color = (0.32, 0.5, 0.66)
    if "LOD" in bpy.data.materials:
        bpy.data.materials["LOD"].diffuse_color = LOD_GREY

    skin = bpy.data.materials["Icarus_Body"]
    skin.use_nodes = True
    nodes = skin.node_tree.nodes
    texture = nodes.new("ShaderNodeTexImage")
    skin.node_tree.links.new(texture.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    nodes.active = texture

    camera = bpy.data.objects.new("lod_camera", bpy.data.cameras.new("lod_camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.lens = 50

    def frame(objs, direction, margin):
        points = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
        lo = Vector([min(p[i] for p in points) for i in range(3)])
        hi = Vector([max(p[i] for p in points) for i in range(3)])
        centre, radius = (lo + hi) / 2, (hi - lo).length / 2
        d = Vector(direction).normalized()
        camera.location = centre + d * radius * margin
        camera.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()

    nose = [o for o in lod0 if o.name in ("radome", "skin_forward_L", "skin_forward_R", "dorsal_cover", "canopy_visible", "windscreen")]
    views = {"whole": (lod0, (-1.0, -1.1, 0.7), 2.3), "nose": (nose, (-1.0, -0.8, 0.55), 2.6)}
    out = out_root / label
    out.mkdir(parents=True, exist_ok=True)
    for number, _ in LIVERIES:
        texture.image = bpy.data.images.load(str(ROOT / ("art/export/textures/Icarus_livery_%d.png" % number)), check_existing=True)
        for view, (objs, direction, margin) in views.items():
            frame(objs, direction, margin)
            for level, shown in (("lod0", lod0), ("lod1", lod1)):
                for o in lod0 + lod1:
                    o.hide_render = o not in shown
                scene.render.filepath = str(out / ("%s_livery%d_%s.png" % (view, number, level)))
                bpy.ops.render.render(write_still=True)
    print("LOD LIVERY RENDERS: " + str(out))


def compose(before, after):
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("segoeui.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    columns = (("LOD0", before, "lod0"), ("LOD1 " + before, before, "lod1"), ("LOD1 " + after, after, "lod1"))
    for view in VIEWS:
        w, h = SIZE
        sheet = Image.new("RGB", (w * len(columns), (h + 44) * len(LIVERIES)), "white")
        draw = ImageDraw.Draw(sheet)
        for row, (number, name) in enumerate(LIVERIES):
            y = row * (h + 44)
            for col, (title, label, level) in enumerate(columns):
                tile = Image.open(OUT / label / ("%s_livery%d_%s.png" % (view, number, level))).convert("RGB")
                sheet.paste(tile, (col * w, y + 44))
                draw.text((col * w + 12, y + 6), "%s, livery %d %s" % (title, number, name), fill="black", font=font)
        path = OUT / ("lod_livery_%s.png" % view)
        sheet.save(path)
        print(path)


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401
    except ImportError:
        compose(*sys.argv[1:3])
    else:
        args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
        render(args[args.index("--label") + 1] if "--label" in args else "after",
               Path(args[args.index("--out") + 1]) if "--out" in args else OUT)
