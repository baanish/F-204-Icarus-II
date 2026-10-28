"""The Icarus damage diagram and tac-screen front profile, drawn from the built aircraft.

python tools/status_diagram.py           # build, dump and draw
python tools/status_diagram.py --draw    # draw again from the last dump in .cache/diagram

Builds the Icarus in Blender (through tools/Run-Blender.ps1) and dumps every render mesh's world triangles, each
under the damageable part that carries it in Unity (its nearest ancestor with mass_kg). Back outside Blender it draws,
in the style of the stock diagrams (white on black under an additive material, tinted by the game):

  - the damage diagram's background: the top view's outline and the boundaries between the parts seen from above
  - one filled top-view silhouette per damageable part, cropped to the part, which StatusDisplay tints as it is hit
  - the tac screen's front profile: the outline of the airframe's main pieces seen from ahead, gear up

The PNGs go to unity/Assets/Blueprinter/Mods/icarus/Diagram and their layout, in the stock prefabs' UI units, to
art/diagram.json, which IcarusAuthor reads. A review sheet with the Revoker's own diagram beside the Icarus's (from
tools/local-paths.json's game export, when it is there) goes to .cache/review/diagram.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "unity/Assets/Blueprinter/Mods/icarus/Diagram"
LAYOUT = REPO / "art/diagram.json"
DUMP = REPO / ".cache/diagram"
REVIEW = REPO / ".cache/review/diagram"

# Measured on the Revoker's: a 1024 px background shown at 270 UI units, the aircraft's length from px 4 to 1012, lines
# 5 px wide at grey 206 and parts filled at 206; a 512 x 256 front profile shown at 320 x 160 units, at most 499 px
# wide, lines 2 px wide at grey 198.
STATUS_PX, STATUS_UNITS, STATUS_TOP, STATUS_BOTTOM, STATUS_LINE, STATUS_GREY = 1024, 270.0, 4, 1012, 5, 206
FRONT_PX, FRONT_UNITS, FRONT_WIDTH, FRONT_HEIGHT, FRONT_LINE, FRONT_GREY = (512, 256), (320.0, 160.0), 499, 244, 2, 198
SUPERSAMPLE = 4
PREFIX = "Icarus_status"


# --- inside Blender ---------------------------------------------------------------------------------------------

def blender_main(out):
    import bpy
    import numpy as np

    import build_icarus
    import stations

    build_icarus.build_cached()
    objects = list(bpy.data.collections["Icarus"].all_objects)
    parts = {o.name.removesuffix("_visible") for o in objects if o.type == "MESH" and o.get("mass_kg", 0) > 0}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    tris, owners = {}, {}
    for obj in objects:
        # No diagram draws the cockpit's inside.
        if obj.type != "MESH" or obj.get("role") == "cockpit_view":
            continue
        owner = obj
        while owner is not None and owner.name.removesuffix("_visible") not in parts:
            owner = owner.parent
        if owner is None:
            raise ValueError(f"{obj.name} hangs under no damageable part")
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        co = np.empty(len(mesh.vertices) * 3, "f4")
        mesh.vertices.foreach_get("co", co)
        index = np.empty(len(mesh.loop_triangles) * 3, "i4")
        mesh.loop_triangles.foreach_get("vertices", index)
        m = np.array(obj.matrix_world, "f4")
        world = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        tris[obj.name] = world[index.reshape(-1, 3)]
        evaluated.to_mesh_clear()
        owners[obj.name] = {"part": owner.name.removesuffix("_visible"), "role": obj.get("role")}

    # Station points on the front profile, Blender (x, z), left side; the right mirrors them. As IcarusAuthor.Stations
    # places them: the wingtip on the tip face at mid-thickness, the inner pylon at its lowest point, and the conformal
    # hardpoint where stations.CONFORMAL holds it.
    # the left wing skin, whole or in its pieces (wing_skin_<piece>_L)
    skin = np.concatenate([t.reshape(-1, 3) for n, t in tris.items() if n.startswith("wing_skin_") and n.endswith("_L")])
    outer = skin[:, 0].max()
    tip = skin[skin[:, 0] > outer - 0.001]
    pylon = tris["pylon_inner_L"].reshape(-1, 3)
    points = {"wingtip": [float(outer - 0.005), float((tip[:, 2].max() + tip[:, 2].min()) / 2)],
              "pylon": [float(pylon[:, 0].mean()), float(pylon[:, 2].min())],
              "conformal": [stations.CONFORMAL["x"], stations.CONFORMAL["z"]]}
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "tris.npz", **tris)
    (out / "owners.json").write_text(json.dumps({"parts": sorted(parts), "objects": owners, "stations": points},
                                                indent=1), encoding="utf-8")
    print(f"STATUS DIAGRAM DUMPED {len(tris)} meshes on {len(parts)} parts")


# --- outside Blender --------------------------------------------------------------------------------------------

def draw_ids(size, polygons, nearness, ids):
    """Each triangle's id where it is the nearest, on a z-buffer; 0 is empty. A pixel counts when its centre is within
    half a pixel of the triangle, so a surface seen edge-on (the fin from above) still draws as a line."""
    import numpy as np

    width, height = size
    near = np.full((height, width), -np.inf, np.float32)
    out = np.zeros((height, width), np.int32)
    for p, z, i in zip(polygons, nearness, ids):
        x0, y0 = np.maximum(np.floor(p.min(0) - 0.5).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(p.max(0) + 0.5).astype(int), (width, height))
        if x0 >= x1 or y0 >= y1:
            continue
        px, py = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        area = (p[1, 0] - p[0, 0]) * (p[2, 1] - p[0, 1]) - (p[1, 1] - p[0, 1]) * (p[2, 0] - p[0, 0])
        sign = 1.0 if area >= 0 else -1.0
        inside = np.ones(px.shape, bool)
        weights = []
        for a, b in ((1, 2), (2, 0), (0, 1)):
            edge = p[b] - p[a]
            cross = sign * (edge[0] * (py - p[a, 1]) - edge[1] * (px - p[a, 0]))
            weights.append(cross)
            length = np.hypot(*edge)
            if length > 1e-6:
                inside &= cross / length >= -0.5
        if not inside.any():
            continue
        if abs(area) > 1.0:
            depth = (weights[0] * z[0] + weights[1] * z[1] + weights[2] * z[2]) / abs(area)
        else:
            depth = np.full(px.shape, z.mean(), np.float32)
        view = near[y0:y1, x0:x1]
        win = inside & (depth > view)
        view[win] = depth[win]
        out[y0:y1, x0:x1][win] = i
    return out


def boundary_lines(id_map, radius, grey, size):
    """Lines radius supersampled px either side of every change of id, box-filtered down to size."""
    import numpy as np
    from PIL import Image

    a = id_map
    edge = np.zeros(a.shape, bool)
    edge[:, :-1] |= a[:, :-1] != a[:, 1:]
    edge[:-1, :] |= a[:-1, :] != a[1:, :]
    # A disc, as rows of horizontal runs: widen by each run's half-width, then shift by the row.
    wide = {0: edge}
    for w in range(1, radius + 1):
        prev = wide[w - 1]
        cur = prev.copy()
        cur[:, 1:] |= prev[:, :-1]
        cur[:, :-1] |= prev[:, 1:]
        wide[w] = cur
    line = np.zeros_like(edge)
    for dy in range(-radius, radius + 1):
        run = wide[int((radius * radius - dy * dy) ** 0.5)]
        if dy >= 0:
            line[dy:, :] |= run[:a.shape[0] - dy, :]
        else:
            line[:dy, :] |= run[-dy:, :]
    image = Image.fromarray((line * 255).astype(np.uint8)).resize(size, Image.BOX)
    return Image.fromarray((np.asarray(image, np.float32) * grey / 255).round().astype(np.uint8))


def filled(mask):
    """mask with its enclosed holes filled: everything the border's flood fill can't reach."""
    import numpy as np
    from PIL import ImageDraw

    probe = mask.copy()
    ImageDraw.floodfill(probe, (0, 0), 128, thresh=0)
    a = np.asarray(probe)
    out = np.asarray(mask).copy()
    out[a == 0] = 255
    return out


def outside(name, info):
    """Whether a mesh is the aircraft's outer surface: skins, glass, intakes, the hinged panels and the nozzle."""
    return (info["role"] in ("skin", "canopy", "intake") or info["part"] in ("canopy", "nozzle")
            or (name.endswith("_visible") and info["role"] == "structure"))


def spans(mask):
    """mask filled across each row between its first and last set pixel, then down each column likewise. The fuselage
    cores are frames on a keel, rungs on a rail from above: this draws them solid between their frames."""
    import numpy as np

    out = mask > 0
    for a in (out, out.T):
        hit = a.any(1)
        first, last = a.argmax(1), a.shape[1] - 1 - a[:, ::-1].argmax(1)
        index = np.arange(a.shape[1])
        a |= hit[:, None] & (index >= first[:, None]) & (index <= last[:, None])
    return np.where(out, 255, 0).astype(np.uint8)


def status(tris, owners, parts):
    """The top view: background, per-part silhouettes and their layout in diagram units."""
    import numpy as np
    from PIL import Image, ImageDraw

    all_tris = np.concatenate(list(tris.values()))
    lo, hi = all_tris.reshape(-1, 3).min(0), all_tris.reshape(-1, 3).max(0)
    scale = (STATUS_BOTTOM - STATUS_TOP) / (hi[1] - lo[1])  # px per metre
    centre = STATUS_PX / 2

    # Seen from above with the nose up, Blender +x (the aircraft's left) on the left.
    def project(t, ss):
        return np.stack([(centre - t[..., 0] * scale) * ss, (STATUS_TOP + (t[..., 1] - lo[1]) * scale) * ss], -1)

    names = sorted(parts)
    part_tris = {p: np.concatenate([tris[o] for o, info in owners.items() if info["part"] == p]) for p in names}
    ss = SUPERSAMPLE
    big = (STATUS_PX * ss, STATUS_PX * ss)
    # The outline is the outside's: frames and spars touch the skins from inside.
    seen = sorted(o for o, info in owners.items() if outside(o, info))
    polygons = np.concatenate([project(tris[o], ss) for o in seen])
    ids = np.concatenate([np.full(len(tris[o]), names.index(owners[o]["part"]) + 1) for o in seen])
    id_map = draw_ids(big, polygons, np.concatenate([tris[o][..., 2] for o in seen]), ids)
    background = boundary_lines(id_map, STATUS_LINE * ss // 2, STATUS_GREY, (STATUS_PX, STATUS_PX))

    unit = STATUS_UNITS / STATUS_PX
    images, layout = {}, {}
    for p in names:
        flat = project(part_tris[p], 1)
        # Padded by 2 px and rounded up to a multiple of 4, for block compression, growing towards the centreline so
        # a left part's crop mirrors its right twin's, and both ways on the centreline.
        x0, y0 = np.floor(flat.reshape(-1, 2).min(0)).astype(int) - 2
        x1, y1 = np.ceil(flat.reshape(-1, 2).max(0)).astype(int) + 2
        w, h = -(-(x1 - x0) // 4) * 4, -(-(y1 - y0) // 4) * 4
        side = x0 + x1 - 2 * centre
        x0 = x0 if side < 0 else x1 - w if side > 0 else x0 - (w - (x1 - x0)) // 2
        mask = Image.new("L", (w * ss, h * ss), 0)
        draw = ImageDraw.Draw(mask)
        for t in (flat - (x0, y0)) * ss:
            draw.polygon([tuple(q) for q in t], fill=255)
        full = filled(mask)
        if p.startswith("fuselage_"):
            full = spans(full)
        small = Image.fromarray(full).resize((w, h), Image.BOX)
        images[p] = Image.fromarray((np.asarray(small, np.float32) * STATUS_GREY / 255).round().astype(np.uint8))
        layout[p] = {"sprite": f"{PREFIX}_{p}.png",
                     "centre": [round(float(x0 + w / 2 - centre) * unit, 2), round(float(centre - y0 - h / 2) * unit, 2)],
                     "size": [round(float(w) * unit, 2), round(float(h) * unit, 2)], "px": [int(x0), int(y0)]}
    return background, images, layout


FRONT_GROUPS = (("wing_", ("wing_spar_", "wing_skin_", "lef_", "aileron_", "flap_")), ("intake_", ("intake_duct_",)),
                ("fin", ("fin_spar", "fin_skin", "rudder")), ("stabilator", ("stabilator",)), ("radome", ("radome",)))


def front_group(name, info):
    """The piece of the front profile a mesh outlines; None leaves it out."""
    if info["role"] == "gear" or info["part"].startswith("gear_") or name.startswith("light_"):
        return None  # in flight the gear is up and the doors shut
    if info["role"] == "canopy":
        return "canopy"
    if name.startswith("pylon_inner"):
        return "pylon_" + name[-1]
    if name.startswith("ventral_fin"):
        return "ventral_fin"
    for group, prefixes in FRONT_GROUPS:
        if info["part"].startswith(prefixes):
            return group + (info["part"][-1] if group.endswith("_") else "")
    return "body"


def front(tris, owners, points):
    """The front profile and its station markers in the profile's units."""
    import numpy as np

    kept = {o: g for o, g in ((o, front_group(o, info)) for o, info in owners.items()) if g}
    all_tris = np.concatenate([tris[o] for o in kept]).reshape(-1, 3)
    lo, hi = all_tris.min(0), all_tris.max(0)
    scale = min(FRONT_WIDTH / (hi[0] - lo[0]), FRONT_HEIGHT / (hi[2] - lo[2]))
    cx, cy = FRONT_PX[0] / 2, FRONT_PX[1] / 2 + (hi[2] + lo[2]) / 2 * scale

    # Seen from ahead, Blender +x (the aircraft's left) on the right.
    def project(x, z, ss=1):
        return np.stack([(cx + x * scale) * ss, (cy - z * scale) * ss], -1)

    groups = sorted(set(kept.values()))
    names = sorted(kept)
    ss = SUPERSAMPLE
    polygons = np.concatenate([project(tris[o][..., 0], tris[o][..., 2], ss) for o in names])
    ids = np.concatenate([np.full(len(tris[o]), groups.index(kept[o]) + 1) for o in names])
    # Blender -y is forward, so the nearest is the lowest y.
    id_map = draw_ids((FRONT_PX[0] * ss, FRONT_PX[1] * ss), polygons, np.concatenate([-tris[o][..., 1] for o in names]), ids)
    profile = boundary_lines(id_map, FRONT_LINE * ss // 2, FRONT_GREY, FRONT_PX)
    unit = FRONT_UNITS[0] / FRONT_PX[0]
    markers = {}
    for station, (x, z) in points.items():
        for side, sx in (("L", 1), ("R", -1)):
            u, v = project(sx * x, z)
            markers[f"{station}_{side}"] = [round(float(u - cx) * unit, 1), round(float(FRONT_PX[1] / 2 - v) * unit, 1)]
    return profile, markers


def review(background, images, layout, profile, markers):
    """The Icarus's diagram beside the Revoker's, with every part lit as if hit, and both front profiles, the Icarus's
    with its station markers."""
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw

    stock = None
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from stores import paths
        stock = paths.load()["game_export"] / "Texture2D"
    except SystemExit:
        pass
    lit = Image.new("RGB", (STATUS_PX, STATUS_PX))
    for p, image in images.items():
        tint = Image.merge("RGB", (image, image, Image.new("L", image.size, 0)))
        box = Image.new("RGB", lit.size)
        box.paste(tint, tuple(layout[p]["px"]))
        lit = ImageChops.add(lit, box)
    panels = [("Icarus diagram", background.convert("RGB")), ("Icarus parts lit", ImageChops.add(lit, background.convert("RGB")))]
    if stock and (stock / "fighter1_status.png").exists():
        panels.insert(0, ("Revoker (stock reference)", Image.open(stock / "fighter1_status.png").convert("RGB")))
    fronts = [("Icarus front profile", profile.convert("RGB"))]
    if stock and (stock / "fighter1_front.png").exists():
        fronts.insert(0, ("Revoker front profile (stock reference)", Image.open(stock / "fighter1_front.png").convert("RGB")))
    width = STATUS_PX * len(panels) + 20 * (len(panels) - 1)
    sheet = Image.new("RGB", (width, STATUS_PX + 40 + FRONT_PX[1] * 2 + 40), (40, 40, 40))
    text = ImageDraw.Draw(sheet)
    for i, (title, image) in enumerate(panels):
        sheet.paste(image, (i * (STATUS_PX + 20), 30))
        text.text((i * (STATUS_PX + 20) + 8, 8), title, fill=(255, 255, 255))
    for i, (title, image) in enumerate(fronts):
        x, y = i * (FRONT_PX[0] * 2 + 20), STATUS_PX + 70
        sheet.paste(image.resize((FRONT_PX[0] * 2, FRONT_PX[1] * 2), Image.NEAREST), (x, y))
        text.text((x + 8, y - 22), title, fill=(255, 255, 255))
    unit = FRONT_UNITS[0] / FRONT_PX[0]
    for mx, my in markers.values():
        u, v = x + (FRONT_PX[0] / 2 + mx / unit) * 2, y + (FRONT_PX[1] / 2 - my / unit) * 2
        text.rectangle((u - 7, v - 7, u + 7, v + 7), outline=(0, 255, 0), width=2)
    REVIEW.mkdir(parents=True, exist_ok=True)
    sheet.save(REVIEW / "diagram_review.png")
    return REVIEW / "diagram_review.png"


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if args and args[0] == "--blender":
        sys.path[:0] = [str(REPO / "tools"), str(REPO / "art/blender")]
        blender_main(Path(args[1]))
        return
    import numpy as np

    if "--draw" not in args:
        run = subprocess.run(["pwsh", "-NoProfile", "-File", str(REPO / "tools/Run-Blender.ps1"), "--background", "--factory-startup",
                              "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--blender", str(DUMP)],
                             capture_output=True, text=True)
        if "STATUS DIAGRAM DUMPED" not in run.stdout:
            sys.stdout.write(run.stdout[-4000:] + run.stderr[-2000:])
            raise SystemExit("the Blender pass failed")
    info = json.loads((DUMP / "owners.json").read_text(encoding="utf-8"))
    with np.load(DUMP / "tris.npz") as data:
        tris = {k: data[k] for k in data.files}
    background, images, layout = status(tris, info["objects"], info["parts"])
    profile, markers = front(tris, info["objects"], info["stations"])

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob(PREFIX + "*.png"):
        old.unlink()
    # RGB, like the stock art, so the importer takes the grey as colour.
    background.convert("RGB").save(OUT / f"{PREFIX}.png")
    for p, image in images.items():
        image.convert("RGB").save(OUT / layout[p]["sprite"])
    profile.convert("RGB").save(OUT / "Icarus_front.png")
    LAYOUT.write_text(json.dumps({
        "generator": "tools/status_diagram.py",
        "status": {"background": f"{PREFIX}.png", "units": STATUS_UNITS, "parts": layout},
        "front": {"sprite": "Icarus_front.png", "units": list(FRONT_UNITS), "markers": markers},
    }, indent=1) + "\n", encoding="utf-8", newline="\n")
    sheet = review(background, images, layout, profile, markers)
    print(f"STATUS DIAGRAM: {len(images)} part images, background and front profile in {OUT}, layout {LAYOUT}, review {sheet}")


if __name__ == "__main__":
    main()
