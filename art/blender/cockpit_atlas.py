"""The cockpit atlas: one 2048 x 1024 trim sheet in four maps (Cockpit rule 9), written to
art/export/textures/Icarus_Cockpit_{b,n,m,ao}.png: albedo, tangent normal, metallic (R) and smoothness (A), and AO.

The sheet has three kinds of region (Cockpit rule 11):
- the main panel's face, unique, at PANEL_PX_PER_M (Cockpit rule 10's 1,500 px/m on panel faces);
- tiles a whole cap maps onto (a key legend, a knob top, a fastener head, a dial face), shared by every copy;
- full-width strips that repeat along U, so a face of any length maps onto one at its own density.

Every region is painted from its own height field, which gives the normal map and a cavity AO per region: a trim
sheet's shared UVs cannot take a geometry AO bake. Everything is numpy and deterministic, so a rebuild writes the
same bytes. Placards and key legends use an original 5 x 7 pixel font.
"""
import os
import struct
import zlib
from collections import namedtuple

import numpy as np

W, H = 2048, 1024
PANEL_PX_PER_M = 1500
LABEL_PX_PER_M = 1500
NAME = "Icarus_Cockpit"
MAPS = ("b", "n", "m", "ao")

# 8-bit sRGB albedo, metallic, smoothness. The panel greys follow the stock Ifrit's.
PALETTE = {
    "panel": ((84, 88, 90), 0.0, 0.38),
    "structure": ((66, 68, 70), 0.0, 0.32),
    "lining": ((58, 60, 61), 0.0, 0.22),
    "floor": ((40, 41, 42), 0.1, 0.30),
    "key": ((112, 114, 116), 0.0, 0.45),
    "plaque": ((150, 150, 146), 0.0, 0.35),
    "ink": ((10, 10, 10), 0.0, 0.30),
    "white": ((228, 228, 222), 0.0, 0.40),
    "hatch_dark": ((24, 24, 24), 0.0, 0.40),
    "hatch_light": ((222, 178, 36), 0.0, 0.40),
    "guard": ((168, 30, 26), 0.0, 0.55),
    "recess": ((20, 20, 21), 0.0, 0.40),
    "knob": ((28, 28, 29), 0.0, 0.50),
    "fastener": ((122, 122, 118), 0.8, 0.50),
    "metal": ((158, 158, 154), 0.9, 0.62),
    "lens_green": ((70, 132, 92), 0.0, 0.80),
    "lens_amber": ((176, 120, 30), 0.0, 0.80),
    "lens_red": ((150, 30, 26), 0.0, 0.80),
    "lens_clear": ((150, 160, 158), 0.0, 0.85),
}

Rect = namedtuple("Rect", "u0 v0 u1 v1 w_m h_m")
Strip = namedtuple("Strip", "v0 v1 px_per_m")

# Regions in pixels, (x0, y0, w, h) from the image's top left.
PANEL = (0, 0, 1100, 600)
LABELS = (1104, 0, 944, 356)
TILES = {
    "knob_top": (1104, 360, 48, 48),
    "fastener_top": (1156, 360, 24, 24),
    "lens_green": (1184, 360, 32, 32),
    "lens_amber": (1220, 360, 32, 32),
    "lens_red": (1256, 360, 32, 32),
    "lens_clear": (1292, 360, 32, 32),
    "hatch": (1328, 360, 64, 64),
    "standby": (1396, 360, 96, 96),
    "dial_fuel": (1496, 360, 96, 96),
    "dial_clock": (1596, 360, 96, 96),
    "dial_cabin": (1696, 360, 96, 96),
    "screw_plate": (1796, 360, 64, 64),
    "pedal": (1864, 360, 96, 128),
}
# Full-width strips below the panel, top to bottom: name -> (height px, px per metre along U and V).
STRIP_ROWS = (
    ("console", 96, 1000), ("lining", 80, 340), ("floor", 56, 300), ("structure", 80, 360), ("frame", 36, 900),
    ("bezel", 24, 1500), ("knurl", 12, 1500), ("guard", 12, 1500), ("metal", 12, 1500), ("keyside", 8, 1500),
    ("recess", 8, 1500),
)
STRIPS = {}
_y = PANEL[3]
for _name, _h, _d in STRIP_ROWS:
    STRIPS[_name] = (_y, _h, _d)
    _y += _h
if _y != H:
    raise ValueError("cockpit atlas strips fill %d of %d rows" % (_y, H))

# An original condensed-caps 5x7 pixel font, rows top to bottom.
GLYPHS = {
    "A": ".###. #...# #...# ##### #...# #...# #...#", "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.", "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####", "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .###.", "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.", "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#", "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#", "N": "#...# ##..# #.#.# #..## #...# #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.", "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#", "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".###. #...# #.... .###. ....# #...# .###.", "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.", "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# #.#.# .#.#.", "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..", "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.", "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####", "3": "##### ...#. ..#.. ...#. ....# #...# .###.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.", "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.", "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.", "9": ".###. #...# #...# .#### ....# ...#. .##..",
    "-": "..... ..... ..... .###. ..... ..... .....", "/": "....# ....# ...#. ..#.. .#... #.... #....",
    ".": "..... ..... ..... ..... ..... .##.. .##..", " ": "..... ..... ..... ..... ..... ..... .....",
    "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
}


def _rgb(name):
    return np.array([c / 255.0 for c in PALETTE[name][0]], np.float32)


def _seed(name):
    return zlib.crc32(name.encode()) & 0xFFFFFFFF


class Layer:
    """One region's maps while it is painted: albedo (sRGB 0..1), height (mm), metallic, smoothness, and an AO
    factor for painted contact shading."""

    def __init__(self, w, h, base):
        self.w, self.h = w, h
        self.albedo = np.tile(_rgb(base), (h, w, 1))
        self.height = np.zeros((h, w), np.float32)
        _, metallic, smooth = PALETTE[base]
        self.metal = np.full((h, w), metallic, np.float32)
        self.smooth = np.full((h, w), smooth, np.float32)
        self.ao = np.ones((h, w), np.float32)

    def fill(self, mask, name):
        self.albedo[mask] = _rgb(name)
        _, metallic, smooth = PALETTE[name]
        self.metal[mask] = metallic
        self.smooth[mask] = smooth

    def noise(self, name, amount, scale=1):
        rng = np.random.default_rng(_seed(name))
        n = rng.random((self.h // scale + 1, self.w // scale + 1)).astype(np.float32) - 0.5
        n = np.kron(n, np.ones((scale, scale), np.float32))[:self.h, :self.w]
        self.albedo *= (1.0 + amount * n)[..., None]
        self.smooth = np.clip(self.smooth + 0.15 * amount * n, 0.0, 1.0)

    def grid(self):
        return np.mgrid[0:self.h, 0:self.w]


# --- region painters (rows top to bottom in each block) -------------------------------------------------------------

def _rivets(layer, rows, pitch, r=1.6, colour="fastener"):
    yy, xx = layer.grid()
    for y in rows:
        d = np.hypot((xx % pitch) - pitch / 2, yy - y)
        dot = d < r
        layer.fill(dot, colour)
        layer.height += np.clip(r - d, 0, None) * 0.25


def _seam(layer, mask, depth=0.3):
    layer.albedo[mask] *= 0.45
    layer.height[mask] -= depth


def paint_panel(layer, seams):
    """The main panel face: paint, sub-panel seams with screw heads at their corners, and wear toward the edges.
    seams: rectangles (x0, y0, x1, y1) in pixels of the region."""
    layer.noise("panel", 0.06, 3)
    yy, xx = layer.grid()
    for x0, y0, x1, y1 in seams:
        edge = ((np.abs(xx - x0) < 1.0) | (np.abs(xx - x1) < 1.0)) & (yy >= y0) & (yy <= y1)
        edge |= ((np.abs(yy - y0) < 1.0) | (np.abs(yy - y1) < 1.0)) & (xx >= x0) & (xx <= x1)
        _seam(layer, edge)
        for cx, cy in ((x0 + 6, y0 + 6), (x1 - 6, y0 + 6), (x0 + 6, y1 - 6), (x1 - 6, y1 - 6)):
            d = np.hypot(xx - cx, yy - cy)
            layer.fill(d < 2.6, "fastener")
            layer.height += np.clip(2.6 - d, 0, None) * 0.15
            slot = (d < 2.4) & (np.abs(xx - cx) < 0.6)
            layer.height[slot] -= 0.3
    rim = np.minimum(np.minimum(xx, layer.w - 1 - xx), np.minimum(yy, layer.h - 1 - yy))
    layer.albedo *= (1.0 + 0.10 * np.exp(-rim / 6.0))[..., None]


def paint_console(layer):
    layer.noise("console", 0.07, 2)
    yy, xx = layer.grid()
    _seam(layer, (yy < 1) | (yy > layer.h - 2))
    _rivets(layer, (5, layer.h - 6), 40, 1.8, "fastener")


def paint_lining(layer):
    """Sidewall lining: quilted insulation panels between seams, a rivet row along the top."""
    layer.noise("lining", 0.08, 4)
    yy, xx = layer.grid()
    cell = 56
    u, v = (xx % cell) - cell / 2, yy - layer.h / 2
    layer.height += 0.8 * np.cos(np.pi * u / cell) * np.cos(np.pi * v / layer.h)
    stitch = (np.abs(xx % cell) < 1) | (yy < 1) | (yy > layer.h - 2)
    _seam(layer, stitch, 0.5)
    _rivets(layer, (5,), 24, 1.4)


def paint_floor(layer):
    """Anti-slip tread: raised diagonal lozenges, alternating, on dark plate."""
    layer.noise("floor", 0.05, 2)
    yy, xx = layer.grid()
    p = 14
    cu, cv = xx % p - (p - 1) / 2, yy % p - (p - 1) / 2
    even = (xx // p + yy // p) % 2 == 0
    rising = (np.abs(cu - cv) < 1.6) & (np.abs(cu + cv) < 8)
    falling = (np.abs(cu + cv) < 1.6) & (np.abs(cu - cv) < 8)
    bar = np.where(even, rising, falling)
    layer.fill(bar, "structure")
    layer.height[bar] += 0.4


def paint_structure(layer):
    layer.noise("structure", 0.08, 3)
    yy, xx = layer.grid()
    _rivets(layer, (6, layer.h - 7), 30, 1.6)
    _seam(layer, (xx % 512) < 1)


def paint_frame(layer):
    layer.noise("frame", 0.06, 2)
    yy, xx = layer.grid()
    _rivets(layer, (layer.h // 2,), 34, 1.8)
    _seam(layer, (yy < 1) | (yy > layer.h - 2), 0.3)


def paint_bezel(layer):
    layer.fill(np.ones((layer.h, layer.w), bool), "panel")
    layer.noise("bezel", 0.05, 2)
    yy, _ = layer.grid()
    layer.albedo *= (0.85 + 0.25 * (yy / layer.h))[..., None]
    layer.height += 0.3 * np.sin(np.pi * yy / layer.h)


def paint_knurl(layer):
    _, xx = layer.grid()
    ridge = (xx % 3) == 0
    layer.fill(np.ones((layer.h, layer.w), bool), "knob")
    layer.albedo[ridge] *= 1.5
    layer.height[ridge] += 0.3


def paint_flat(name, noise=0.05):
    def paint(layer):
        layer.fill(np.ones((layer.h, layer.w), bool), name)
        layer.noise(name, noise, 2)
    return paint


def paint_knob_top(layer):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "knob")
    layer.fill((np.abs(xx - c) < 1.3) & (yy < c - 3), "white")  # the pointer, to the top of the tile
    layer.height -= np.clip(r - 0.40 * layer.w, 0, None) * 0.15


def paint_fastener_top(layer):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "fastener")
    layer.height += np.clip(0.48 * layer.w - r, 0, None) * 0.08
    slot = (np.abs(xx - c) < 1.2) & (r < 0.36 * layer.w)
    layer.albedo[slot] *= 0.35
    layer.height[slot] -= 0.5


def paint_lens(name):
    def paint(layer):
        yy, xx = layer.grid()
        c = (layer.w - 1) / 2
        r = np.hypot(xx - c, yy - c) / (layer.w / 2)
        layer.fill(np.ones_like(r, bool), name)
        layer.albedo *= (1.15 - 0.35 * r)[..., None]
        layer.height += 0.5 * (1 - r ** 2)
    return paint


def paint_hatch(layer):
    yy, xx = layer.grid()
    light = ((xx + yy) // 6) % 2 == 0
    layer.fill(np.ones_like(light), "hatch_dark")
    layer.fill(light, "hatch_light")


def _dial(layer, ticks, needle_deg):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    ang = np.degrees(np.arctan2(xx - c, c - yy))
    layer.fill(np.ones_like(r, bool), "recess")
    for a in ticks:
        layer.fill((np.abs(ang - a) < 2.2) & (r > 0.36 * layer.w) & (r < 0.45 * layer.w), "white")
    layer.fill((np.abs(ang - needle_deg) < 2.5) & (r < 0.38 * layer.w), "white")
    layer.fill(r < 3, "metal")
    layer.smooth[r < 0.46 * layer.w] = 0.85  # the cover glass


def paint_standby(layer):
    """An attitude indicator: sky over ground, horizon and pitch ladder, a roll scale, the aircraft symbol."""
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "recess")
    ball = r < 0.42 * layer.w
    layer.albedo[ball & (yy <= c)] = (0.30, 0.47, 0.62)
    layer.albedo[ball & (yy > c)] = (0.42, 0.29, 0.17)
    white = _rgb("white")
    layer.albedo[ball & (np.abs(yy - c) < 0.8)] = white
    for k, half in ((9, 8), (18, 12), (-9, 8), (-18, 12)):
        layer.albedo[ball & (np.abs(yy - c - k) < 0.6) & (np.abs(xx - c) < half)] = white
    ang = np.degrees(np.arctan2(xx - c, c - yy))
    for a in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
        layer.albedo[(np.abs(ang - a) < 1.6) & (r > 0.44 * layer.w) & (r < 0.49 * layer.w)] = white
    amber = _rgb("lens_amber") * 1.4
    layer.albedo[(np.abs(yy - c) < 1.0) & (np.abs(xx - c) > 7) & (np.abs(xx - c) < 20)] = amber
    layer.smooth[r < 0.49 * layer.w] = 0.85


def paint_screw_plate(layer):
    layer.noise("screw_plate", 0.05, 2)
    yy, xx = layer.grid()
    _seam(layer, (xx < 1) | (yy < 1) | (xx > layer.w - 2) | (yy > layer.h - 2))


def paint_pedal(layer):
    layer.fill(np.ones((layer.h, layer.w), bool), "structure")
    yy, xx = layer.grid()
    bar = (yy % 10) < 3
    layer.fill(bar, "metal")
    layer.height[bar] += 0.5


TILE_PAINTERS = {
    "knob_top": paint_knob_top, "fastener_top": paint_fastener_top, "hatch": paint_hatch, "standby": paint_standby,
    "lens_green": paint_lens("lens_green"), "lens_amber": paint_lens("lens_amber"), "lens_red": paint_lens("lens_red"),
    "lens_clear": paint_lens("lens_clear"),
    "dial_fuel": lambda l: _dial(l, range(-120, 121, 30), 40), "dial_clock": lambda l: _dial(l, range(0, 360, 30), 110),
    "dial_cabin": lambda l: _dial(l, range(-90, 91, 30), -20), "screw_plate": paint_screw_plate, "pedal": paint_pedal,
}
STRIP_BASE = {"console": "panel", "lining": "lining", "floor": "floor", "structure": "structure", "frame": "structure",
              "bezel": "panel", "knurl": "knob", "guard": "guard", "metal": "metal", "keyside": "key",
              "recess": "recess"}
STRIP_PAINTERS = {
    "console": paint_console, "lining": paint_lining, "floor": paint_floor, "structure": paint_structure,
    "frame": paint_frame, "bezel": paint_bezel, "knurl": paint_knurl, "guard": paint_flat("guard", 0.08),
    "metal": paint_flat("metal", 0.06), "keyside": paint_flat("key", 0.04), "recess": paint_flat("recess", 0.04),
}


class Atlas:
    """The sheet's layout and its labels. Ask for regions while building (rects, strips, labels); paint() makes the
    maps once every label is known."""

    def __init__(self):
        self.labels = {}  # key -> (x, y, w, h, text, ink, paper)
        self.cursor = [LABELS[0], LABELS[1], 0]
        self.seams = []

    # -- layout -----------------------------------------------------------------------------------------------------

    @staticmethod
    def rect(x, y, w, h, px_per_m=LABEL_PX_PER_M):
        """UV rect of a pixel rect given from the image's top left, with its size in metres at px_per_m."""
        return Rect(x / W, 1.0 - (y + h) / H, (x + w) / W, 1.0 - y / H, w / px_per_m, h / px_per_m)

    def tile(self, name):
        x, y, w, h = TILES[name]
        return self.rect(x + 1, y + 1, w - 2, h - 2)  # a pixel in, so filtering never reaches the neighbour

    @staticmethod
    def strip(name):
        """(v0, v1, px per metre) of a full-width strip, half a pixel in at each edge."""
        y, h, d = STRIPS[name]
        return Strip(1.0 - (y + h - 0.5) / H, 1.0 - (y + 0.5) / H, d)

    @staticmethod
    def panel_rect():
        """UV rect of the panel face, and its size in metres."""
        x, y, w, h = PANEL
        return Atlas.rect(x, y, w, h, PANEL_PX_PER_M)

    def panel_seam(self, x0, y0, x1, y1):
        """Paint a sub-panel outline on the panel face; corners in metres from the region's bottom left."""
        k, (_, _, _, h) = PANEL_PX_PER_M, PANEL
        self.seams.append((x0 * k, h - y1 * k, x1 * k, h - y0 * k))

    def label(self, text, ink="ink", paper="plaque", cell=None):
        """UV rect of text (lines split on newlines) in the pixel font, centred in a cell of paper colour, and its
        size in metres at LABEL_PX_PER_M. The same label asked twice is the same region."""
        lines = text.upper().split("\n")
        tw, th = max(len(line) for line in lines) * 6 - 1, len(lines) * 9 - 2
        w, h = cell or (tw + 4, th + 4)
        key = (text, ink, paper, w, h)
        if key not in self.labels:
            x, y, row = self.cursor
            if x + w > LABELS[0] + LABELS[2]:
                x, y, row = LABELS[0], y + row + 2, 0
            if y + h > LABELS[1] + LABELS[3]:
                raise ValueError("cockpit atlas: the label area is full at %r" % text)
            self.cursor = [x + w + 2, y, max(row, h)]
            self.labels[key] = (x, y, w, h, lines, ink, paper)
        x, y, w, h = self.labels[key][:4]
        return self.rect(x, y, w, h)

    # -- painting ---------------------------------------------------------------------------------------------------

    def paint(self):
        """The four maps as uint8 arrays, rows top to bottom: albedo RGBA, normal RGBA, metallic-smoothness RGBA, AO
        RGBA."""
        albedo = np.zeros((H, W, 3), np.float32)
        normal = np.zeros((H, W, 3), np.float32)
        metal = np.zeros((H, W), np.float32)
        smooth = np.zeros((H, W), np.float32)
        ao = np.ones((H, W), np.float32)
        normal[..., 2] = 1.0

        def put(x, y, layer, strength=0.6, cavity=0.5):
            sl = (slice(y, y + layer.h), slice(x, x + layer.w))
            albedo[sl] = np.clip(layer.albedo, 0.0, 1.0)
            metal[sl], smooth[sl] = layer.metal, np.clip(layer.smooth, 0.0, 1.0)
            h = np.pad(layer.height, 1, mode="edge")
            dx = (h[1:-1, 2:] - h[1:-1, :-2]) * 0.5
            dy = (h[2:, 1:-1] - h[:-2, 1:-1]) * 0.5  # rows run down the image, V up
            n = np.stack([-dx * strength, dy * strength, np.ones_like(dx)], -1)
            normal[sl] = n / np.linalg.norm(n, axis=-1, keepdims=True)
            ao[sl] = np.clip(layer.ao * (1.0 - cavity * np.clip(_blur(layer.height, 3) - layer.height, 0, None)),
                             0.35, 1.0)

        x, y, w, h = PANEL
        layer = Layer(w, h, "panel")
        paint_panel(layer, self.seams)
        put(x, y, layer)
        for name, (x, y, w, h) in TILES.items():
            layer = Layer(w, h, "panel")
            TILE_PAINTERS[name](layer)
            put(x, y, layer)
        for name, (y, h, _) in STRIPS.items():
            layer = Layer(W, h, STRIP_BASE[name])
            STRIP_PAINTERS[name](layer)
            put(0, y, layer)
        label_bg = Layer(LABELS[2], LABELS[3], "panel")
        label_bg.noise("labels", 0.04, 2)
        put(LABELS[0], LABELS[1], label_bg)
        for x, y, w, h, lines, ink, paper in self.labels.values():
            layer = Layer(w, h, paper)
            tw, th = max(len(line) for line in lines) * 6 - 1, len(lines) * 9 - 2
            ox, oy = (w - tw) // 2, (h - th) // 2
            for li, line in enumerate(lines):
                for ci, ch in enumerate(line):
                    for r, row in enumerate(GLYPHS[ch].split()):
                        for c, bit in enumerate(row):
                            px, py = ox + ci * 6 + c, oy + li * 9 + r
                            if bit == "#" and 0 <= px < w and 0 <= py < h:
                                layer.albedo[py, px] = _rgb(ink)
            put(x, y, layer, strength=0.0, cavity=0.0)
        to8 = lambda a: np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
        opaque = np.full((H, W, 1), 255, np.uint8)
        zero = np.zeros((H, W), np.float32)
        return {
            "b": np.concatenate([to8(albedo), opaque], -1),
            "n": np.concatenate([to8(normal * 0.5 + 0.5), opaque], -1),
            "m": to8(np.stack([metal, zero, zero, smooth], -1)),
            "ao": np.concatenate([to8(np.repeat(ao[..., None], 3, -1)), opaque], -1),
        }

    def write(self, folder):
        """Paint and write the four PNGs; returns their paths."""
        os.makedirs(folder, exist_ok=True)
        paths = {}
        for key, pixels in self.paint().items():
            paths[key] = os.path.join(folder, "%s_%s.png" % (NAME, key))
            write_png(paths[key], pixels)
        return paths


def _blur(a, r):
    """Box blur of radius r, edges clamped."""
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def write_png(path, rgba):
    """An 8-bit RGBA PNG, rows top to bottom, written byte-for-byte the same for the same pixels."""
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
