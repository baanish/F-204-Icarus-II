"""The Icarus's map icon, drawn from the built aircraft.

python tools/map_icon.py           # build, dump and draw
python tools/map_icon.py --draw    # draw again from the last dump in .cache/map_icon

AircraftDefinition.mapIcon is the one picture of the jet outside the 3D world: UnitMapIcon draws it on the map, turned
to the heading, and AircraftSelectionButton on the plane select screen; the target list, the reserve notices and the
faction panel reuse it. This draws it in the style of the stock icons, the Revoker's above all: a filled top-view
silhouette, nose up, white in every pixel with the shape in the alpha, on a 256 px square, the length spanning rows 1
to 254. The HUD markers (friendlyIcon, hostileIcon) are not drawn here: every stock aircraft shares the game's one
hudIcon_aircraft.

The Blender pass is tools/status_diagram.py's dump of every render mesh's world triangles, written to .cache/map_icon.
The outline is the outer surface's (status_diagram.outside), gear up as in flight, with enclosed holes filled.

The sprite keeps the whole square as its rect and the jet at its true proportions. Both slots stretch a sprite's rect
to a square (UnitMapIcon.prefab's 1 x 1 image, AircraftButton.prefab's 30 x 30, neither preserving aspect), and the
Revoker's rect hugs its outline, so the game draws it about 1.4 times its true width. The Icarus is a slender jet, and
stretched the same way it would be 2.6 times as wide and lose the needle shape that names it.

The PNG goes to unity/Assets/Blueprinter/Mods/icarus/Icons, which IcarusAuthor imports with the stock icon's settings
and wires to mapIcon. A sheet beside the Revoker and three other stock jets, at 1x and at the in-game sizes on a dark
map ground, goes to .cache/review/share/icons, when tools/local-paths.json names the game export.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "unity/Assets/Blueprinter/Mods/icarus/Icons/Icarus_mapIcon.png"
DUMP = REPO / ".cache/map_icon"
REVIEW = REPO / ".cache/review/share/icons"

# Measured on mapIcon_revoker: a 256 px square, the length from row 0 to 253, RGB white, the shape in an antialiased
# alpha. Rows 1 to 254 keep a clear pixel at each end for the bilinear filter.
PX, TOP, BOTTOM = 256, 1, 255
SUPERSAMPLE = 8
# The in-game sizes in UI units: the map's 15 x mapIconSize (UnitMapIcon.UpdateIcon, 1.2 on the Icarus as on the
# Revoker) at the default icon size, and the select button's image.
MAP_UNITS, SELECT_UNITS = 18, 30
# The stock jets on the sheet: definition, sprite, texture.
STOCK = (("FS-12 Revoker", "mapIcon_revoker"), ("FS-20 Vortex", "mapIcon_smallFighter1"),
         ("KR-67 Ifrit", "mapIcon_multirole1"), ("T/A-30 Compass", "mapIcon_trainer"))


def flown(name, info):
    """Whether a mesh is on the outline seen from above in flight: the outer surface, gear up."""
    import status_diagram

    return status_diagram.outside(name, info) and info["role"] != "gear" and not info["part"].startswith("gear_")


def silhouette(tris, owners):
    """The top view's coverage, 0 to 255, on the icon's square, and the metres per pixel."""
    import numpy as np
    from PIL import Image, ImageDraw

    import status_diagram

    names = sorted(o for o, info in owners.items() if flown(o, info))
    points = np.concatenate([tris[o] for o in names])
    lo, hi = points.reshape(-1, 3).min(0), points.reshape(-1, 3).max(0)
    scale = (BOTTOM - TOP) / (hi[1] - lo[1])  # px per metre
    if (hi[0] - lo[0]) * scale > PX - 2:
        raise SystemExit(f"the span {hi[0] - lo[0]:.2f} m doesn't fit beside the length {hi[1] - lo[1]:.2f} m")
    ss = SUPERSAMPLE
    # Seen from above with the nose up, Blender +x (the aircraft's left) on the left, as the status diagram draws it.
    flat = np.stack([(PX / 2 - points[..., 0] * scale) * ss, (TOP + (points[..., 1] - lo[1]) * scale) * ss], -1)
    mask = Image.new("L", (PX * ss, PX * ss), 0)
    draw = ImageDraw.Draw(mask)
    for t in flat:
        draw.polygon([tuple(q) for q in t], fill=255)
    full = Image.fromarray(status_diagram.filled(mask)).resize((PX, PX), Image.BOX)
    return full, 1 / scale


def icon(coverage):
    """The sprite's texture: white, the coverage as alpha."""
    from PIL import Image

    white = Image.new("L", coverage.size, 255)
    return Image.merge("RGBA", (white, white, white, coverage))


def drawn(texture, rect, size):
    """What the game puts on screen at size px: the sprite's rect stretched to the square, through the additive map
    material (the colour times the alpha; the stock DXT1 icons are white on black with no alpha), as a light mask."""
    import numpy as np
    from PIL import Image

    a = np.asarray(texture.convert("RGBA"), np.float32) / 255
    light = a[..., :3].mean(-1) * a[..., 3]
    x, y, w, h = rect
    # A sprite rect counts from the bottom; the image's rows from the top.
    top = texture.height - (y + h)
    crop = Image.fromarray((light * 255).round().astype(np.uint8)).crop((round(x), round(top), round(x + w), round(top + h)))
    return crop.resize((size, size), Image.BOX)


def sprite_rect(sprite):
    """A stock sprite's rect from the game export, in texture pixels."""
    import re

    text = sprite.read_text(encoding="utf-8")
    return tuple(float(v) for v in re.search(r"m_Rect:.*?x: ([\d.]+)\s+y: ([\d.]+)\s+width: ([\d.]+)\s+height: ([\d.]+)",
                                             text, re.S).groups())


def review(texture):
    """The Icarus beside the stock jets: the textures at 1x, then as the map and the select screen draw them, each at
    its true pixel size and magnified, white and in the friendly tint."""
    from PIL import Image, ImageDraw

    try:
        sys.path.insert(0, str(REPO / "tools"))
        from stores import paths
        export = paths.load()["game_export"]
    except SystemExit as e:
        print(f"no review sheet: {e}")
        return None
    icons = [("F-204 Icarus II", texture, (0, 0, PX, PX))]
    for title, name in STOCK:
        icons.append((title, Image.open(export / "Texture2D" / f"{name}.png"), sprite_rect(export / "Sprite" / f"{name}.asset")))
    # The Icarus drawn with a rect hugging its outline, as the Revoker's does, for the comparison only.
    box = texture.getchannel("A").getbbox()
    icons.append(("Icarus, rect hugging it", texture, (box[0], PX - box[3], box[2] - box[0], box[3] - box[1])))

    ground, friendly, label = (17, 27, 33), (90, 170, 255), (230, 230, 230)
    column, zoom = 300, 4
    rows = [("texture at 1x", PX), (f"map, {MAP_UNITS} px, and x{zoom}", MAP_UNITS * zoom + 40),
            (f"select screen, {SELECT_UNITS} px, and x{zoom}", SELECT_UNITS * zoom + 40),
            (f"map at 4K ({MAP_UNITS * 2} px), friendly tint", MAP_UNITS * 2 + 20)]
    height = 40 + sum(h + 40 for _, h in rows)
    sheet = Image.new("RGB", (column * len(icons) + 20, height), ground)
    text = ImageDraw.Draw(sheet)

    def put(mask, at, colour):
        sheet.paste(Image.new("RGB", mask.size, colour), at, mask)

    for i, (title, image, rect) in enumerate(icons):
        x = 20 + i * column
        text.text((x, 10), title, fill=label)
        y = 40
        for r, (caption, h) in enumerate(rows):
            text.text((x, y), caption, fill=(150, 160, 170))
            y += 20
            if r == 0:
                full = drawn(image, (0, 0, image.width, image.height), image.width)
                put(full.resize((PX, PX), Image.NEAREST), (x, y), (255, 255, 255))
                k = PX / image.width
                ox, oy = rect[0] * k, (image.height - rect[1] - rect[3]) * k
                text.rectangle((x + ox, y + oy, x + ox + rect[2] * k, y + oy + rect[3] * k), outline=(200, 90, 60))
            elif r in (1, 2):
                size = MAP_UNITS if r == 1 else SELECT_UNITS
                small = drawn(image, rect, size)
                put(small, (x, y), (255, 255, 255))
                put(small, (x + size + 20, y), friendly)
                put(small.resize((size * zoom, size * zoom), Image.NEAREST), (x + 2 * size + 40, y), (255, 255, 255))
            else:
                small = drawn(image, rect, MAP_UNITS * 2)
                put(small, (x, y), friendly)
            y += h + 20
    text.text((20, height - 18), "orange box: the sprite rect the game stretches to a square. Additive map material assumed "
              "(colour x alpha).", fill=(150, 160, 170))
    REVIEW.mkdir(parents=True, exist_ok=True)
    sheet.save(REVIEW / "map_icon_review.png")
    return REVIEW / "map_icon_review.png"


def main():
    args = sys.argv[1:]
    sys.path.insert(0, str(REPO / "tools"))
    import json

    import numpy as np

    if "--draw" not in args:
        run = subprocess.run(["pwsh", "-NoProfile", "-File", str(REPO / "tools/Run-Blender.ps1"), "--background", "--factory-startup",
                              "--python-exit-code", "1", "--python", str(REPO / "tools/status_diagram.py"), "--", "--blender", str(DUMP)],
                             capture_output=True, text=True)
        if "STATUS DIAGRAM DUMPED" not in run.stdout:
            sys.stdout.write(run.stdout[-4000:] + run.stderr[-2000:])
            raise SystemExit("the Blender pass failed")
    info = json.loads((DUMP / "owners.json").read_text(encoding="utf-8"))
    with np.load(DUMP / "tris.npz") as data:
        tris = {k: data[k] for k in data.files}
    coverage, metres = silhouette(tris, info["objects"])
    texture = icon(coverage)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    texture.save(OUT)
    box = coverage.getbbox()
    sheet = review(texture)
    print(f"MAP ICON: {OUT}, outline {box[2] - box[0]} x {box[3] - box[1]} px at {metres * 100:.1f} cm per px, review {sheet}")


if __name__ == "__main__":
    main()
