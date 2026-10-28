"""The tip tank's weapon icon: side-view line art of the tank, drawn from its pinned mesh export.

python tools/tip_tank_icon.py

WeaponInfo.weaponIcon is the picture the weapon panel, the loadout menu, the radial menu and the station indicators
draw for a store. The stock icons (weaponIcon_bomb_250 and the rest) are 512 x 256 px, opaque, a side view with the nose
on the left drawn in white lines about two pixels wide on black, with a line across each joint of the body. The tank
is drawn the same way from art/export/tip_tank.fbx, the mesh IcarusAuthor.TipTanks imports: its outline, the edges
where its faces turn sharply (the fins, where they meet the body) and a line at each end of the cylinder. Its 5.44 m
span the length, as the stock icons of the longer stores do.

The PNG goes to unity/Assets/Blueprinter/Mods/icarus/Icons, which IcarusAuthor.TipTanks imports with the stock
icon's settings and wires to the tank's WeaponInfo. A sheet beside the PAB-250 and two other stock icons goes to
.cache/tiptank-ui, when tools/local-paths.json names the game export.
"""
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion, binary_fill_holes

REPO = Path(__file__).resolve().parents[1]
FBX = REPO / "art/export/tip_tank.fbx"
OUT = REPO / "unity/Assets/Blueprinter/Mods/icarus/Icons/Icarus_weaponIcon_tip_tank.png"
SHEET = REPO / ".cache/tiptank-ui/icon_sheet.png"

# Measured on the stock icons: 512 x 256, the long stores centred on the middle row with 40 to 80 px beside them.
W, H = 512, 256
MARGIN = 40
LINE = 2.0  # px
SS = 4
CREASE_DEG = 35
STOCK = ("bomb_250", "bomb_500", "AAM1")


def fbx_nodes(data, pos, end):
    """The binary FBX (version below 7500) nodes in data[pos:end] as (name, properties, children)."""
    nodes = []
    while pos < end:
        node_end, count, _, name_len = struct.unpack_from("<IIIB", data, pos)
        if node_end == 0:
            break
        name = data[pos + 13:pos + 13 + name_len].decode()
        pos += 13 + name_len
        props = []
        for _ in range(count):
            kind = chr(data[pos])
            pos += 1
            if kind in "YCIFLD":
                size = {"Y": 2, "C": 1, "I": 4, "F": 4, "L": 8, "D": 8}[kind]
                props.append(struct.unpack_from("<" + {"Y": "h", "C": "?", "I": "i", "F": "f", "L": "q", "D": "d"}[kind], data, pos)[0])
                pos += size
            elif kind in "fdlib":
                length, enc, packed = struct.unpack_from("<III", data, pos)
                pos += 12
                dtype = {"f": "<f4", "d": "<f8", "l": "<i8", "i": "<i4", "b": "u1"}[kind]
                raw = data[pos:pos + packed]
                props.append(np.frombuffer(zlib.decompress(raw) if enc else raw, dtype)[:length])
                pos += packed
            elif kind in "SR":
                length = struct.unpack_from("<I", data, pos)[0]
                props.append(data[pos + 4:pos + 4 + length])
                pos += 4 + length
            else:
                raise ValueError(f"unknown FBX property type {kind!r}")
        children = fbx_nodes(data, pos, node_end) if pos < node_end else []
        nodes.append((name, props, children))
        pos = node_end
    return nodes


def mesh_triangles():
    """The tank's triangles, (n, 3, 3), in the file's axes."""
    data = FBX.read_bytes()
    if data[:18] != b"Kaydara FBX Binary" or struct.unpack_from("<I", data, 23)[0] >= 7500:
        raise SystemExit(f"{FBX.name}: expected a binary FBX below version 7500")
    top = fbx_nodes(data, 27, len(data))
    objects = next(c for n, _, c in top if n == "Objects")
    geometry = [c for n, _, c in objects if n == "Geometry"]
    if len(geometry) != 1:
        raise SystemExit(f"{FBX.name} has {len(geometry)} geometries, expected the tank's one")
    nodes = {n: p[0] for n, p, _ in geometry[0] if p}
    verts = nodes["Vertices"].reshape(-1, 3)
    tris = []
    poly = []
    for i in nodes["PolygonVertexIndex"]:
        poly.append(int(i) if i >= 0 else ~int(i))
        if i < 0:
            tris += [(poly[0], poly[k], poly[k + 1]) for k in range(1, len(poly) - 1)]
            poly = []
    return verts[np.array(tris)]


def side_view(tris):
    """Triangles as (n, 3, 3) of (right, up, nose) with the metres normalised to the exported length.

    The file's axes are the exporter's. The longest extent is the length; of the other two the one the fin raises one
    side of is up, so a tank is read the same whichever axes it was written in. The nose is the end without the fin.
    """
    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)
    length_axis = int(np.argmax(hi - lo))
    layout = json.loads((REPO / "art/export/blockout.json").read_text())["tip_tank"]
    tris = tris * (layout["length"] / (hi - lo)[length_axis])
    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)
    others = [a for a in range(3) if a != length_axis]
    up_axis = max(others, key=lambda a: abs(hi[a] + lo[a]))
    side_axis = next(a for a in others if a != up_axis)
    up_sign = 1.0 if hi[up_axis] > -lo[up_axis] else -1.0
    # The fin stands above the body at the tail: the end with the larger height is the tail.
    height = pts[:, up_axis] * up_sign
    along = pts[:, length_axis]
    mid = (hi[length_axis] + lo[length_axis]) / 2
    tail_sign = 1.0 if height[along > mid].max() > height[along <= mid].max() else -1.0
    out = np.stack([tris[..., side_axis], tris[..., up_axis] * up_sign, -tail_sign * tris[..., length_axis]], -1)
    return out, layout


def draw_icon(tris):
    """The icon: white lines on black, 512 x 256, the nose on the left."""
    flat = tris[..., [2, 1]]  # screen: nose to the left means -tail; here +nose is +x then mirrored below
    lo, hi = flat.reshape(-1, 2).min(0), flat.reshape(-1, 2).max(0)
    scale = (W - 2 * MARGIN) / (hi[0] - lo[0])

    def screen(p):
        # the nose (largest "nose" coordinate) goes left, the body's centre line on the middle row
        return np.stack([(W - MARGIN) * SS - (p[..., 0] - lo[0]) * scale * SS, H / 2 * SS - p[..., 1] * scale * SS], -1)

    px = screen(flat)
    mask = Image.new("L", (W * SS, H * SS), 0)
    draw = ImageDraw.Draw(mask)
    for t in px:
        draw.polygon([tuple(q) for q in t], fill=255)
    solid = binary_fill_holes(np.array(mask) > 127)
    width = int(LINE * SS)
    edge = solid & ~binary_erosion(solid, iterations=width)
    lines = Image.fromarray((edge * 255).astype(np.uint8))
    pen = ImageDraw.Draw(lines)

    # Edges where faces turn sharply, welded by position: the fins and where they meet the body.
    key = lambda p: tuple(np.round(p, 4))
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    faces = {}
    for i, t in enumerate(tris):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            faces.setdefault(frozenset((key(t[a]), key(t[b]))), []).append((i, a, b))
    cos = np.cos(np.radians(CREASE_DEG))
    for edge_faces in faces.values():
        if len(edge_faces) != 2 and len(edge_faces) != 1:
            continue
        sharp = len(edge_faces) == 1 or normals[edge_faces[0][0]] @ normals[edge_faces[1][0]] < cos
        if not sharp:
            continue
        i, a, b = edge_faces[0]
        p, q = screen(flat[i, a]), screen(flat[i, b])
        if np.hypot(*(p - q)) >= 6 * SS:  # not the lens bosses
            pen.line([tuple(p), tuple(q)], fill=255, width=width)

    # A line across each end of the cylinder, the joint the stock stores show as a band.
    radius = np.abs(tris[..., 0]).reshape(-1)
    nose = tris[..., 2].reshape(-1)
    full = nose[radius >= radius.max() * 0.999]
    height = flat.reshape(-1, 2)[:, 1]
    for x in (full.min(), full.max()):
        rows = height[np.abs(nose - x) < 1e-3]
        top, bottom = screen(np.array([flat[..., 0].reshape(-1)[np.abs(nose - x) < 1e-3][0], rows.max()])), screen(np.array([flat[..., 0].reshape(-1)[np.abs(nose - x) < 1e-3][0], rows.min()]))
        pen.line([tuple(top), tuple(bottom)], fill=255, width=width)

    gray = lines.resize((W, H), Image.BOX)
    rgba = Image.merge("RGBA", [gray, gray, gray, Image.new("L", (W, H), 255)])
    return rgba


def review(icon):
    export = REPO / "tools/local-paths.json"
    if not export.exists():
        return
    folder = Path(json.loads(export.read_text())["game_export"]) / "Texture2D"
    sheet = Image.new("RGB", (W * 2, H * 2), (40, 40, 40))
    sheet.paste(icon.convert("RGB"), (0, 0))
    for i, name in enumerate(STOCK, 1):
        sheet.paste(Image.open(folder / f"weaponIcon_{name}.png").convert("RGB"), ((i % 2) * W, (i // 2) * H))
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET)
    print("sheet", SHEET)


def main():
    tris, _ = side_view(mesh_triangles())
    icon = draw_icon(tris)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT)
    print("icon", OUT)
    review(icon)


if __name__ == "__main__":
    sys.exit(main())
