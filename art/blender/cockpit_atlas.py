"""The cockpit atlas: one 2048 x 1024 sheet in four maps (Cockpit rule 9), written to
art/export/textures/Icarus_Cockpit_{b,n,m,ao}.png: albedo, tangent normal, metallic (R) and smoothness (A), and AO.

The sheet has four kinds of region:
- charts: the large surfaces (panel faces and plates, the hood and its rim, the coaming, consoles, tub, floor, frames),
  each on its own unique area at its kind's density, so a Cycles bake of the joined cockpit gives them real ambient
  occlusion (cockpit.bake_ao). The charts at panel density (1,000 px/m and over) pack first, and Atlas.panel_rects
  lists them;
- labels: legends and placards in Blender's built-in vector font at LABEL_PX_PER_M, light ink on the plate colour;
- tiles a whole cap maps onto (a knob top, a fastener head, a dial face, a lens), shared by every copy;
- full-width strips along the bottom that repeat along U, for the sides of the small parts, each with the part's own
  contact shading painted toward its foot.

Charts and labels are laid out by a shelf packer once the cockpit is built (Atlas.pack); until then their faces carry
ChartPoints, positions in the chart's own metres. The relief, wear and grime of a chart come from its baked coverage and
AO: edges roll off and wear light where they stand in the open, corners darken and dull. Everything but the bake is
numpy and seeded, so a rebuild writes the same bytes for the same bake.
"""
import math
import os
import struct
import zlib
from collections import namedtuple

import numpy as np

W, H = 2048, 1024
NAME = "Icarus_Cockpit"
MAPS = ("b", "n", "m", "ao")
LABEL_PX_PER_M = 3000  # 5 mm caps stand 15 texels tall
PANEL_DENSITY = 1000  # charts at this density or over are panel faces (Cockpit rule 10's 1,500 px/m)
GAP = 8  # pixels between packed charts: the bake's 4 px margin on each side

# 8-bit sRGB albedo, metallic, smoothness. Values follow the stock band: tub and floor 30 to 45, panels and consoles
# 55 to 75, bezels 20 to 30, knob and key tops 25 to 40 under light legends.
PALETTE = {
    "panel": ((64, 67, 68), 0.0, 0.46),
    "plate": ((57, 60, 61), 0.0, 0.45),
    "console": ((62, 65, 66), 0.0, 0.45),
    "hood": ((33, 34, 35), 0.0, 0.38),
    "tub": ((41, 42, 43), 0.0, 0.36),
    "floor": ((35, 36, 36), 0.0, 0.28),
    "frame": ((46, 47, 48), 0.0, 0.42),
    "structure": ((52, 54, 55), 0.0, 0.36),
    "bezel": ((25, 25, 26), 0.0, 0.42),
    "key": ((36, 37, 38), 0.0, 0.46),
    "knob": ((31, 31, 32), 0.0, 0.48),
    "ink": ((222, 222, 214), 0.0, 0.40),
    "ink_dark": ((14, 14, 14), 0.0, 0.40),
    "white": ((226, 226, 220), 0.0, 0.40),
    "hatch_dark": ((22, 22, 22), 0.0, 0.40),
    "hatch_light": ((214, 170, 34), 0.0, 0.40),
    "guard": ((156, 28, 24), 0.0, 0.55),
    "recess": ((17, 17, 18), 0.0, 0.40),
    "fastener": ((118, 118, 114), 0.8, 0.50),
    "metal": ((150, 150, 146), 0.9, 0.60),
    "lens_green": ((40, 92, 58), 0.0, 0.85),
    "lens_amber": ((132, 86, 18), 0.0, 0.85),
    "lens_red": ((110, 18, 16), 0.0, 0.85),
    "lens_clear": ((118, 126, 124), 0.0, 0.88),
    # a missile warning lens unlit: frosted grey-green, as the Vortex's and Ifrit's read in the hood's shade, dark enough
    # that the lamp's red glow over it shows
    "lens_off": ((84, 92, 86), 0.0, 0.80),
}

# Chart kinds: (palette, px per metre, grain (degrees of tilt), edge bevel in mm, wear width in mm).
KINDS = {
    "panel": ("panel", 1330, 6.0, 1.2, 1.6),
    "plate": ("plate", 1330, 6.0, 1.0, 1.4),
    "cheek": ("hood", 1000, 5.0, 1.5, 2.0),
    "rim": ("hood", 400, 3.5, 2.5, 2.5),
    "hood": ("hood", 380, 3.5, 2.5, 2.5),
    "deck": ("hood", 300, 2.4, 2.5, 2.5),
    "console": ("console", 420, 2.2, 2.0, 2.0),
    "sill": ("frame", 420, 2.2, 2.0, 2.5),
    "tub": ("tub", 300, 2.8, 2.5, 2.5),
    "floor": ("floor", 300, 4.5, 2.5, 3.0),
    "back": ("tub", 220, 2.8, 2.5, 2.5),  # behind the seat, seen from the eye only past the headbox
    "frame": ("frame", 340, 3.5, 2.0, 2.5),
    "structure": ("structure", 400, 3.5, 1.5, 2.0),
}

# Kinds whose sheets are riveted and seamed: (rivet pitch, head radius) in mm.
STRUCTURE = {"tub": (38.0, 2.2), "back": (38.0, 2.2), "deck": (45.0, 2.4), "hood": (45.0, 2.4), "rim": (45.0, 2.2),
             "sill": (32.0, 2.0), "frame": (34.0, 2.0), "console": (40.0, 2.0)}

Strip = namedtuple("Strip", "v0 v1 px_per_m")
ChartPoint = namedtuple("ChartPoint", "chart x y")

TILES = {  # name -> (w, h) px
    "knob_top": (48, 48), "knob_top_large": (64, 64), "fastener_top": (24, 24), "lens_green": (32, 32),
    "lens_amber": (32, 32), "lens_red": (32, 32), "lens_clear": (32, 32), "lens_off": (32, 32), "hatch": (64, 64),
    "standby": (128, 128), "dial_fuel": (128, 128), "dial_clock": (128, 128), "dial_alt": (128, 128),
    "dial_asi": (128, 128), "pedal": (96, 128), "breaker_top": (24, 24), "toggle_ball": (24, 24),
}
# Full-width strips along the bottom, top to bottom: name -> (height px, px per metre along U and V).
STRIP_ROWS = (
    ("structure", 40, 360), ("bezel", 20, 1500), ("knurl", 12, 1500), ("knob_lo", 12, 1500), ("guard", 10, 1500),
    ("guard_lo", 10, 1500), ("metal", 10, 1500), ("metal_lo", 10, 1500), ("keyside", 8, 1500), ("key_lo", 8, 1500),
    ("recess", 8, 1500), ("bezel_dark", 8, 1500),
)
STRIPS = {}
_y = H - sum(r[1] for r in STRIP_ROWS)
STRIP_TOP = _y
for _name, _h, _d in STRIP_ROWS:
    STRIPS[_name] = (_y, _h, _d)
    _y += _h


def _rgb(name):
    return np.array([c / 255.0 for c in PALETTE[name][0]], np.float32)


def _seed(name):
    return zlib.crc32(name.encode()) & 0xFFFFFFFF


class Chart:
    """A rect of the sheet a set of faces maps onto, in its own metres: free (grown by the points asked of it) or of a
    fixed pixel size (labels and tiles, addressed by fractions with frac). at: its top-left pixel once packed."""

    def __init__(self, kind, density, size_px=None, name=""):
        self.kind, self.d, self.name = kind, density, name
        self.at, self.rot = None, False
        self.fixed = size_px is not None
        if self.fixed:
            self.w_px, self.h_px = size_px
            self.lo, self.hi = [0.0, 0.0], [size_px[0] / density, size_px[1] / density]
        else:
            self.lo, self.hi = [math.inf, math.inf], [-math.inf, -math.inf]

    @property
    def w_m(self):
        return self.hi[0] - self.lo[0]

    @property
    def h_m(self):
        return self.hi[1] - self.lo[1]

    def point(self, x, y):
        if not self.fixed:
            self.lo = [min(self.lo[0], x), min(self.lo[1], y)]
            self.hi = [max(self.hi[0], x), max(self.hi[1], y)]
        return ChartPoint(self, x, y)

    def frac(self, fx, fy):
        """A point a fraction across a fixed chart, a pixel in from its edge so filtering never reaches a neighbour."""
        return ChartPoint(self, (1 + fx * (self.w_px - 2)) / self.d, (1 + fy * (self.h_px - 2)) / self.d)

    def size(self):
        """Its pixel size as packed: a free chart taller than wide lies on its side."""
        if self.fixed:
            return self.w_px, self.h_px
        w, h = (int(math.ceil((self.hi[0] - self.lo[0]) * self.d)) + 3,
                int(math.ceil((self.hi[1] - self.lo[1]) * self.d)) + 3)
        self.rot = h > w
        return (h, w) if self.rot else (w, h)

    def uv(self, p):
        """The sheet UV of a point of this chart; free charts sit 1.5 px in from their packed rect."""
        pad = 0.0 if self.fixed else 1.5
        if self.rot:  # a quarter turn, so the texture keeps its handedness
            x = self.at[0] + pad + (self.hi[1] - p.y) * self.d
            y = self.at[1] + pad + (self.hi[0] - p.x) * self.d
        else:
            x = self.at[0] + pad + (p.x - self.lo[0]) * self.d
            y = self.at[1] + pad + (self.hi[1] - p.y) * self.d
        return x / W, 1.0 - y / H


def resolve(p):
    """A face corner's UV: a ChartPoint placed on the packed sheet, or an immediate (u, v)."""
    return p.chart.uv(p) if isinstance(p, ChartPoint) else p


def skyline_pack(items, x0, x1, h, sky=None):
    """Place items (Chart) bottom-left on a skyline across x0..x1 (y growing down the sheet from 0, at most h), widest
    and tallest first; sky: the starting skyline as [x, width, y] segments. Returns the items that did not fit and the
    skyline after."""
    sky = [list(s) for s in (sky or [[x0, x1 - x0, 0]])]
    rest = []
    for it in items:
        iw, ih = it.size()
        gap = 2 if it.fixed else GAP  # labels and tiles take no bake margin
        iw, ih = iw + gap, ih + gap
        best = None
        for i, (sx, _, _) in enumerate(sky):
            if sx + iw > x1:
                break
            top, run, k = 0, 0, i
            while run < iw:  # the highest segment under the item's span
                top = max(top, sky[k][2])
                run += sky[k][1]
                k += 1
            if top + ih <= h and (best is None or (top, sx) < best[:2]):
                best = (top, sx, i)
        if best is None:
            rest.append(it)
            continue
        top, sx, i = best
        it.at = (sx + gap // 2, top + gap // 2)
        new = [sx, iw, top + ih]
        out = sky[:i] + [new]
        end = sx + iw
        for seg in sky[i:]:
            if seg[0] + seg[1] <= end:
                continue
            if seg[0] < end:
                seg = [end, seg[0] + seg[1] - end, seg[2]]
            out.append(seg)
        merged = []
        for seg in out:
            if merged and merged[-1][2] == seg[2]:
                merged[-1][1] += seg[1]
            else:
                merged.append(list(seg))
        sky = merged
    return rest, sky


class Layer:
    """One region's maps while it is painted: albedo (sRGB 0..1), height (mm), metallic, smoothness, AO."""

    def __init__(self, w, h, base):
        self.w, self.h = w, h
        self.albedo = np.tile(_rgb(base), (h, w, 1))
        self.height = np.zeros((h, w), np.float32)
        _, metallic, smooth = PALETTE[base]
        self.metal = np.full((h, w), metallic, np.float32)
        self.smooth = np.full((h, w), smooth, np.float32)
        self.ao = np.ones((h, w), np.float32)
        self.mm_per_px = 1000.0 / 1500

    def fill(self, mask, name):
        self.albedo[mask] = _rgb(name)
        _, metallic, smooth = PALETTE[name]
        self.metal[mask] = metallic
        self.smooth[mask] = smooth

    def noise(self, name, amount, scale=1):
        n = _noise(name, self.h, self.w, scale)
        self.albedo *= (1.0 + amount * n)[..., None]
        self.smooth = np.clip(self.smooth + 0.15 * amount * n, 0.0, 1.0)

    def grid(self):
        return np.mgrid[0:self.h, 0:self.w]


def _noise(name, h, w, scale=1):
    """Value noise in -0.5..0.5, cells of scale px, bilinear."""
    rng = np.random.default_rng(_seed(name))
    gh, gw = h // scale + 2, w // scale + 2
    n = rng.random((gh, gw)).astype(np.float32) - 0.5
    if scale == 1:
        return n[:h, :w]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) / scale
    y0, x0 = yy.astype(int), xx.astype(int)
    fy, fx = yy - y0, xx - x0
    return ((n[y0, x0] * (1 - fx) + n[y0, x0 + 1] * fx) * (1 - fy) + (n[y0 + 1, x0] * (1 - fx) + n[y0 + 1, x0 + 1] * fx) * fy)


# --- tile and strip painters ----------------------------------------------------------------------------------------

def paint_knob_top(layer):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "knob")
    layer.albedo *= (0.9 + 0.25 * np.clip(1 - r / (0.5 * layer.w), 0, 1) ** 2)[..., None]  # a soft sheen in the dish
    layer.fill((np.abs(xx - c) < 1.4) & (yy < c - 3) & (r < 0.46 * layer.w), "white")  # the pointer line
    layer.height -= np.clip(r - 0.38 * layer.w, 0, None) * 0.05  # the chamfer round the top
    layer.height += 0.02 * np.cos(np.clip(r / (0.38 * layer.w), 0, 1) * np.pi / 2)  # a shallow dome
    layer.ao *= np.clip(0.75 + 0.6 * (1 - r / (0.5 * layer.w)), 0.75, 1.0)


def paint_fastener_top(layer):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "fastener")
    layer.height += np.clip(0.48 * layer.w - r, 0, None) * 0.04
    slot = (np.abs(xx - c) < 1.2) & (r < 0.36 * layer.w)
    layer.albedo[slot] *= 0.35
    layer.height[slot] -= 0.3
    layer.ao[slot] = 0.5


def paint_breaker_top(layer):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "knob")
    layer.fill((r > 0.30 * layer.w) & (r < 0.40 * layer.w), "white")  # the white collar a tripped breaker shows
    layer.height -= np.clip(r - 0.40 * layer.w, 0, None) * 0.05


def paint_toggle_ball(layer):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c) / (layer.w / 2)
    layer.fill(np.ones_like(r, bool), "metal")
    layer.albedo *= (1.15 - 0.4 * r)[..., None]


def paint_lens(name):
    def paint(layer):
        yy, xx = layer.grid()
        c = (layer.w - 1) / 2
        r = np.hypot(xx - c, yy - c) / (layer.w / 2)
        layer.fill(np.ones_like(r, bool), name)
        layer.albedo *= (1.2 - 0.45 * r)[..., None]
        layer.height += 0.08 * (1 - np.clip(r, 0, 1) ** 2)
        # the prismatic grid of a real lens, faint
        grid = ((xx % 4) == 0) | ((yy % 4) == 0)
        layer.albedo[grid] *= 0.85
    return paint


def paint_hatch(layer):
    yy, xx = layer.grid()
    light = ((xx + yy) // 6) % 2 == 0
    layer.fill(np.ones_like(light), "hatch_dark")
    layer.fill(light, "hatch_light")
    layer.noise("hatch", 0.10, 2)


def _ring_text(layer, values, radius, cap_px, start_deg, step_deg):
    """Numerals round a dial face, upright."""
    c = (layer.w - 1) / 2
    for i, text in enumerate(values):
        a = math.radians(start_deg + step_deg * i)
        mask = text_mask([text], cap_px)
        h, w = mask.shape
        x = int(round(c + radius * math.sin(a) - w / 2))
        y = int(round(c - radius * math.cos(a) - h / 2))
        sub = (slice(max(y, 0), min(y + h, layer.h)), slice(max(x, 0), min(x + w, layer.w)))
        m = mask[sub[0].start - y:sub[0].stop - y, sub[1].start - x:sub[1].stop - x]
        layer.albedo[sub] = layer.albedo[sub] * (1 - m[..., None]) + _rgb("white") * m[..., None]


def _dial(layer, ticks, needle_deg, numerals=None, start=0.0, step=30.0, name=None):
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    ang = np.degrees(np.arctan2(xx - c, c - yy))
    layer.fill(np.ones_like(r, bool), "recess")
    for a in ticks:
        d = (ang - a + 180) % 360 - 180
        layer.fill((np.abs(d) < 1.6) & (r > 0.38 * layer.w) & (r < 0.46 * layer.w), "white")
    for a in np.arange(ticks[0], ticks[-1], (ticks[1] - ticks[0]) / 5):
        d = (ang - a + 180) % 360 - 180
        layer.fill((np.abs(d) < 0.9) & (r > 0.42 * layer.w) & (r < 0.46 * layer.w), "white")
    if numerals:
        _ring_text(layer, numerals, 0.30 * layer.w, 0.085 * layer.w, start, step)
    if name:
        mask = text_mask([name], 0.065 * layer.w)
        h, w = mask.shape
        x, y = int(c - w / 2), int(c + 0.12 * layer.w)
        layer.albedo[y:y + h, x:x + w] = layer.albedo[y:y + h, x:x + w] * (1 - mask[..., None]) + _rgb("white") * mask[..., None]
    d = (ang - needle_deg + 180) % 360 - 180
    needle = (np.abs(d) < 3.0 * (1 - r / (0.45 * layer.w)) + 0.6) & (r < 0.40 * layer.w)
    layer.fill(needle, "white")
    layer.fill(r < 0.05 * layer.w, "metal")
    layer.smooth[r < 0.47 * layer.w] = 0.88  # the cover glass
    layer.ao *= np.clip(0.55 + 0.45 * (1 - np.clip((r - 0.40 * layer.w) / (0.08 * layer.w), 0, 1)), 0.55, 1.0)


def paint_standby(layer):
    """An attitude indicator: sky over ground, horizon and pitch ladder, a roll scale, the aircraft symbol."""
    yy, xx = layer.grid()
    c = (layer.w - 1) / 2
    r = np.hypot(xx - c, yy - c)
    layer.fill(np.ones_like(r, bool), "recess")
    ball = r < 0.42 * layer.w
    layer.albedo[ball & (yy <= c)] = (0.26, 0.42, 0.56)
    layer.albedo[ball & (yy > c)] = (0.36, 0.25, 0.15)
    white = _rgb("white")
    k = layer.w / 96
    layer.albedo[ball & (np.abs(yy - c) < 0.9 * k)] = white
    for p, half in ((9, 8), (18, 12), (-9, 8), (-18, 12)):
        layer.albedo[ball & (np.abs(yy - c - p * k) < 0.6 * k) & (np.abs(xx - c) < half * k)] = white
    ang = np.degrees(np.arctan2(xx - c, c - yy))
    for a in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
        layer.albedo[(np.abs(ang - a) < 1.6) & (r > 0.44 * layer.w) & (r < 0.49 * layer.w)] = white
    amber = np.array([0.85, 0.55, 0.10], np.float32)
    layer.albedo[(np.abs(yy - c) < 1.2 * k) & (np.abs(xx - c) > 7 * k) & (np.abs(xx - c) < 20 * k)] = amber
    layer.albedo[(r < 1.6 * k)] = amber
    layer.smooth[r < 0.49 * layer.w] = 0.88
    layer.ao *= np.clip(0.6 + 0.4 * (1 - np.clip((r - 0.40 * layer.w) / (0.08 * layer.w), 0, 1)), 0.6, 1.0)


def paint_pedal(layer):
    layer.fill(np.ones((layer.h, layer.w), bool), "structure")
    yy, xx = layer.grid()
    bar = (yy % 10) < 3
    layer.fill(bar, "metal")
    layer.height[bar] += 0.2


def paint_strip(base, noise=0.05, foot=None):
    """A plain strip; foot: the AO at the strip's bottom edge (V = 0), rising to 1 at its top."""
    def paint(layer):
        layer.fill(np.ones((layer.h, layer.w), bool), base)
        layer.noise(base + "strip", noise, 2)
        if foot is not None:
            yy, _ = layer.grid()
            t = yy / max(layer.h - 1, 1)  # 0 at the top row, 1 at the bottom (V = v0), the part's foot
            layer.ao *= 1 - (1 - foot) * t ** 1.5
    return paint


def paint_knurl(layer):
    _, xx = layer.grid()
    ridge = (xx % 3) == 0
    layer.fill(np.ones((layer.h, layer.w), bool), "knob")
    layer.albedo[ridge] *= 1.55
    layer.height[ridge] += 0.08
    layer.ao[~ridge] *= 0.8


def paint_knurl_foot(layer):
    paint_knurl(layer)
    yy, _ = layer.grid()
    t = yy / max(layer.h - 1, 1)  # 1 at the bottom row (V = v0), the part's foot
    layer.ao *= 1 - 0.55 * t ** 1.5


def paint_bezel(base):
    def paint(layer):
        layer.fill(np.ones((layer.h, layer.w), bool), base)
        layer.noise("bezel" + base, 0.05, 2)
        yy, _ = layer.grid()
        t = yy / max(layer.h - 1, 1)
        layer.albedo *= (0.85 + 0.25 * (1 - t))[..., None]
        layer.height += 0.05 * np.sin(np.pi * t)
    return paint


def paint_structure(layer):
    layer.fill(np.ones((layer.h, layer.w), bool), "structure")
    layer.noise("structure", 0.08, 3)
    yy, xx = layer.grid()
    for y in (6, layer.h - 7):
        d = np.hypot((xx % 30) - 15, yy - y)
        layer.fill(d < 1.6, "fastener")
        layer.height += np.clip(1.6 - d, 0, None) * 0.05


TILE_PAINTERS = {
    "knob_top": paint_knob_top, "knob_top_large": paint_knob_top, "fastener_top": paint_fastener_top,
    "hatch": paint_hatch, "standby": paint_standby, "pedal": paint_pedal, "breaker_top": paint_breaker_top,
    "toggle_ball": paint_toggle_ball,
    "lens_green": paint_lens("lens_green"), "lens_amber": paint_lens("lens_amber"), "lens_red": paint_lens("lens_red"),
    "lens_clear": paint_lens("lens_clear"), "lens_off": paint_lens("lens_off"),
    "dial_fuel": lambda l: _dial(l, list(range(-135, 136, 45)), 40, ["0", "2", "4", "6", "8", "10", "12"], -135, 45,
                                 "FUEL"),
    "dial_clock": lambda l: _dial(l, list(range(0, 331, 30)), 110, ["12", "3", "6", "9"], 0, 90),
    "dial_alt": lambda l: _dial(l, list(range(0, 325, 36)), 200, [str(i) for i in range(10)], 0, 36, "ALT"),
    "dial_asi": lambda l: _dial(l, list(range(-150, 151, 30)), -40, ["0", "100", "200", "300", "400", "500", "600"],
                                -150, 50, "KT"),
}
STRIP_PAINTERS = {
    "structure": paint_structure, "bezel": paint_bezel("bezel"), "bezel_dark": paint_bezel("recess"),
    "knurl": paint_knurl, "knob_lo": paint_knurl_foot, "guard": paint_strip("guard", 0.08),
    "guard_lo": paint_strip("guard", 0.08, 0.55), "metal": paint_strip("metal", 0.06),
    "metal_lo": paint_strip("metal", 0.06, 0.5), "keyside": paint_strip("key", 0.04), "key_lo": paint_strip("key", 0.04, 0.5),
    "recess": paint_strip("recess", 0.04, 0.7),
}


# --- vector-font legends --------------------------------------------------------------------------------------------

_TEXT = {}


def text_mask(lines, cap_px, bold=1):
    """Coverage (h x w, 0..1) of text lines in Blender's built-in font, centred, caps cap_px tall, rasterised from the
    glyph triangles at 4 x 4 samples a pixel; bold: pixels of dilation."""
    key = (tuple(lines), round(cap_px, 2), bold)
    if key in _TEXT:
        return _TEXT[key]
    import bpy
    cu = bpy.data.curves.new("CockpitLegend", "FONT")
    cu.body = "\n".join(lines)
    cu.align_x = "CENTER"
    cu.space_line = 1.15
    ob = bpy.data.objects.new("CockpitLegend", cu)
    bpy.context.scene.collection.objects.link(ob)
    deps = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(deps).to_mesh()
    me.calc_loop_triangles()
    co = np.array([v.co[:2] for v in me.vertices], np.float64).reshape(-1, 2)
    tris = np.array([t.vertices[:] for t in me.loop_triangles], int).reshape(-1, 3)
    ob.evaluated_get(deps).to_mesh_clear()
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.curves.remove(cu)
    ss = 4
    scale = cap_px * ss / 0.70  # the built-in font's caps stand 0.70 of its size
    lo = co.min(0) if len(co) else np.zeros(2)
    hi = co.max(0) if len(co) else np.zeros(2)
    pad = (bold + 1) * ss
    w = int(math.ceil((hi[0] - lo[0]) * scale)) + 2 * pad
    h = int(math.ceil((hi[1] - lo[1]) * scale)) + 2 * pad
    w, h = w + (-w) % ss, h + (-h) % ss
    acc = np.zeros((h, w), bool)
    p = np.stack([(co[:, 0] - lo[0]) * scale + pad, (hi[1] - co[:, 1]) * scale + pad], 1)
    for t in tris:
        a, b, c = p[t[0]], p[t[1]], p[t[2]]
        x0, x1 = int(max(min(a[0], b[0], c[0]), 0)), int(min(max(a[0], b[0], c[0]) + 1, w))
        y0, y1 = int(max(min(a[1], b[1], c[1]), 0)), int(min(max(a[1], b[1], c[1]) + 1, h))
        if x1 <= x0 or y1 <= y0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1] + 0.5
        d = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[0] - xx) * (c[1] - yy) - (b[1] - yy) * (c[0] - xx)) / d
        l2 = ((c[0] - xx) * (a[1] - yy) - (c[1] - yy) * (a[0] - xx)) / d
        acc[y0:y1, x0:x1] |= (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
    for _ in range(bold * ss // 2):
        g = acc.copy()
        g[1:] |= acc[:-1]
        g[:-1] |= acc[1:]
        g[:, 1:] |= acc[:, :-1]
        g[:, :-1] |= acc[:, 1:]
        acc = g
    mask = acc.reshape(h // ss, ss, w // ss, ss).mean((1, 3)).astype(np.float32)
    _TEXT[key] = mask
    return mask


# --- the sheet ------------------------------------------------------------------------------------------------------

class Atlas:
    """The sheet's layout: charts, labels and tiles asked for while building, then packed (pack), baked into
    (take_bake) and painted (paint)."""

    def __init__(self):
        self.charts = []
        self.labels = {}  # key -> Chart
        self.tiles = {}
        self.panel_rects = []  # the pixel rects of the panel-density charts
        self.bake_ao = None  # H x W baked AO, and where it was written
        self.bake_cover = None

    # -- layout -----------------------------------------------------------------------------------------------------

    def chart(self, kind, name=""):
        """A new free chart of a surface kind (KINDS)."""
        c = Chart(kind, KINDS[kind][1], name=name)
        self.charts.append(c)
        return c

    def tile(self, name):
        if name not in self.tiles:
            self.tiles[name] = Chart("tile:" + name, 1500, size_px=TILES[name], name=name)
        return self.tiles[name]

    @staticmethod
    def strip(name):
        """(v0, v1, px per metre) of a full-width strip, half a pixel in at each edge."""
        y, h, d = STRIPS[name]
        return Strip(1.0 - (y + h - 0.5) / H, 1.0 - (y + 0.5) / H, d)

    def label(self, text, ink="ink", paper="plate", cap_mm=4.5, size_mm=None, box=False):
        """A legend: text (lines split on newlines) in the vector font, caps cap_mm tall, centred on a cell of the paper
        colour (size_mm, or the text plus 1.5 mm round it), boxed in a thin ink line if box. The same label asked twice
        is the same chart; its w_m and h_m are the quad to put it on."""
        lines = text.upper().split("\n")
        cap_px = cap_mm * LABEL_PX_PER_M / 1000
        key = (tuple(lines), ink, paper, round(cap_mm, 2), size_mm, box)
        if key not in self.labels:
            mask = text_mask(lines, cap_px)
            if size_mm:
                w, h = (max(4, int(round(v * LABEL_PX_PER_M / 1000))) for v in size_mm)
                fit = min(1.0, (w - 4) / mask.shape[1], (h - 4) / mask.shape[0])
                if fit < 1.0:  # a long legend on a small cap: smaller letters, not clipped ones
                    mask = text_mask(lines, cap_px * fit)
            else:
                padx = int(round((2.5 if box else 1.5) * LABEL_PX_PER_M / 1000))
                w, h = mask.shape[1] + 2 * padx, mask.shape[0] + 2 * padx
            c = Chart("label", LABEL_PX_PER_M, size_px=(w, h), name=text)
            c.ink, c.paper, c.mask, c.box = ink, paper, mask, box
            self.labels[key] = c
        return self.labels[key]

    def pack(self):
        """Lay out every chart, label and tile above the strips: the panel-density charts first, the rest round them."""
        self.charts = [c for c in self.charts if c.lo[0] < math.inf]  # asked for, never drawn on
        panel = [c for c in self.charts if c.d >= PANEL_DENSITY]
        rest = [c for c in self.charts if c.d < PANEL_DENSITY] + list(self.labels.values()) + list(self.tiles.values())
        # a skyline packer is order-sensitive: try the usual orders in turn, the first that fits wins
        for key in (lambda c: (-c.size()[1], -c.size()[0], c.name), lambda c: (-c.size()[0] * c.size()[1], c.name),
                    lambda c: (-c.size()[0], -c.size()[1], c.name), lambda c: (-max(c.size()), c.name)):
            for c in panel + rest:
                c.at = None
            left, sky = skyline_pack(sorted(panel, key=key), 0, W, STRIP_TOP)
            left, _ = skyline_pack(left + sorted(rest, key=key), 0, W, STRIP_TOP, sky)
            if not left:
                break
        self.panel_rects = [(c.at[0], c.at[1]) + c.size() for c in panel if c.at]
        if left:
            for c in sorted(self.charts, key=lambda c: -c.size()[0] * c.size()[1]):
                print("cockpit atlas chart %-14s %-12s %5d x %4d px  %.3f x %.3f m" % (c.kind, c.name, *c.size(), c.w_m, c.h_m))
            print("cockpit atlas: charts %d px, labels %d px, tiles %d px, of %d above the strips" % (
                sum(c.size()[0] * c.size()[1] for c in self.charts), sum(c.w_px * c.h_px for c in self.labels.values()),
                sum(c.w_px * c.h_px for c in self.tiles.values()), W * STRIP_TOP))
            raise ValueError("cockpit atlas: %d regions do not fit, the first %s %s" % (len(left), left[0].name,
                                                                                         left[0].size()))
        self.use = (sum(c.size()[0] * c.size()[1] for c in panel + rest) + W * (H - STRIP_TOP)) / (W * H)

    def take_bake(self, ao, cover):
        """The Cycles AO bake of the charts (H x W, rows top to bottom) and the pixels it wrote."""
        self.bake_ao, self.bake_cover = ao, cover

    # -- painting ---------------------------------------------------------------------------------------------------

    def paint(self):
        """The four maps as uint8 arrays, rows top to bottom: albedo RGBA, normal RGBA, metallic-smoothness RGBA, AO
        RGBA."""
        albedo = np.zeros((H, W, 3), np.float32)
        albedo[:] = _rgb("hood")
        normal = np.zeros((H, W, 3), np.float32)
        metal = np.zeros((H, W), np.float32)
        smooth = np.full((H, W), 0.35, np.float32)
        ao = np.ones((H, W), np.float32)
        normal[..., 2] = 1.0

        def put(x, y, layer):
            sl = (slice(y, y + layer.h), slice(x, x + layer.w))
            albedo[sl] = np.clip(layer.albedo, 0.0, 1.0)
            metal[sl], smooth[sl] = layer.metal, np.clip(layer.smooth, 0.0, 1.0)
            normal[sl] = height_normals(layer.height, layer.mm_per_px)
            ao[sl] = np.clip(layer.ao, 0.0, 1.0)

        for c in sorted(self.tiles.values(), key=lambda c: c.name):
            layer = Layer(c.w_px, c.h_px, "recess")
            TILE_PAINTERS[c.name](layer)
            put(c.at[0], c.at[1], layer)
        for name, (y, h, d) in STRIPS.items():
            layer = Layer(W, h, "recess")
            layer.mm_per_px = 1000.0 / d
            STRIP_PAINTERS[name](layer)
            layer.height += math.tan(math.radians(4.0)) * layer.mm_per_px * 3.8 * _noise("sg" + name, h, W, 1)
            put(0, y, layer)
        for c in self.labels.values():
            layer = Layer(c.w_px, c.h_px, c.paper)
            layer.mm_per_px = 1000.0 / LABEL_PX_PER_M
            layer.noise("label" + c.name, 0.04, 3)
            layer.height += math.tan(math.radians(5.0)) * layer.mm_per_px * 3.8 * _noise("lg" + c.name, c.h_px, c.w_px, 1)
            m = np.zeros((c.h_px, c.w_px), np.float32)
            mh, mw = c.mask.shape
            oy, ox = (c.h_px - mh) // 2, (c.w_px - mw) // 2
            ys, xs = slice(max(oy, 0), max(oy, 0) + min(mh, c.h_px)), slice(max(ox, 0), max(ox, 0) + min(mw, c.w_px))
            m[ys, xs] = c.mask[max(-oy, 0):max(-oy, 0) + min(mh, c.h_px), max(-ox, 0):max(-ox, 0) + min(mw, c.w_px)]
            if c.box:
                t = 2
                inset = int(round(0.8 * LABEL_PX_PER_M / 1000))
                frame = np.zeros_like(m)
                frame[inset:inset + t, inset:c.w_px - inset] = 1
                frame[c.h_px - inset - t:c.h_px - inset, inset:c.w_px - inset] = 1
                frame[inset:c.h_px - inset, inset:inset + t] = 1
                frame[inset:c.h_px - inset, c.w_px - inset - t:c.w_px - inset] = 1
                m = np.maximum(m, frame)
            ink = _rgb(c.ink)
            layer.albedo = layer.albedo * (1 - m[..., None]) + ink * m[..., None]
            layer.smooth = layer.smooth * (1 - m) + PALETTE[c.ink][2] * m
            layer.ao[:] = 0.82  # the plates' baked AO, on average, round where the legends sit
            put(c.at[0], c.at[1], layer)
        for c in self.charts:
            x, y = c.at
            w, h = c.size()
            layer = self.paint_chart(c, w, h)
            sl = (slice(y, y + h), slice(x, x + w))
            # the bake writes past the faces by its margin; paint the whole rect so that margin reads the same
            albedo[sl] = np.clip(layer.albedo, 0.0, 1.0)
            metal[sl], smooth[sl] = layer.metal, np.clip(layer.smooth, 0.0, 1.0)
            normal[sl] = height_normals(layer.height, layer.mm_per_px)
            ao[sl] = np.clip(layer.ao, 0.0, 1.0)
        to8 = lambda a: np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
        opaque = np.full((H, W, 1), 255, np.uint8)
        zero = np.zeros((H, W), np.float32)
        return {
            "b": np.concatenate([to8(albedo), opaque], -1),
            "n": np.concatenate([to8(normal * 0.5 + 0.5), opaque], -1),
            "m": to8(np.stack([metal, zero, zero, smooth], -1)),
            "ao": np.concatenate([to8(np.repeat(ao[..., None], 3, -1)), opaque], -1),
        }

    def paint_chart(self, c, w, h):
        """A chart's maps from its kind and its bake: paint with a large mottle and a fine grain, edges rolled off and
        worn light where they stand in the open, grime in the occluded corners."""
        base, density, grain, bevel_mm, wear_mm = KINDS[c.kind]
        layer = Layer(w, h, base)
        layer.mm_per_px = 1000.0 / density
        x, y = c.at
        if self.bake_ao is not None:
            ao = self.bake_ao[y:y + h, x:x + w].copy()
            cover = self.bake_cover[y:y + h, x:x + w].copy()
        else:
            ao, cover = np.full((h, w), 0.8, np.float32), np.ones((h, w), bool)
        ao = np.where(cover, ao, 1.0)
        tag = "%s%d%d" % (c.kind, x, y)
        mottle = _noise("m" + tag, h, w, max(2, int(0.05 * density)))
        layer.albedo *= (1.0 + 0.10 * mottle)[..., None]
        fine = _noise("f" + tag, h, w, 1)
        layer.albedo *= (1.0 + 0.05 * fine)[..., None]
        # the grain: paint's micro-texture a texel across on the panel faces; where a texel is wide, a fine streak
        # along the sheet, which reads as rolled metal under paint rather than dents
        k = math.tan(math.radians(grain)) * layer.mm_per_px * 3.8
        if density >= 900:
            layer.height += k * _noise("g" + tag, h, w, 1)
        else:
            n = _noise("g" + tag, h, w // 8 + 2, 1)
            xs = np.arange(w) / 8.0
            i0 = xs.astype(int)
            f = (xs - i0)[None, :]
            layer.height += 1.8 * k * (n[:, i0] * (1 - f) + n[:, i0 + 1] * f)  # the streak tilts one way only
        # distance in from the chart's covered edge, in mm
        edge = distance_in(cover, int(math.ceil(12.0 * density / 1000)) + 1) * 1000.0 / density
        roll = np.clip(1 - edge / bevel_mm, 0, 1)
        layer.height -= 0.8 * bevel_mm * roll ** 2
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) * layer.mm_per_px
        if c.kind in STRUCTURE:
            # rivets in rows a hand's width in from the edges, and the seams between the sheets
            pitch, r = STRUCTURE[c.kind]
            dx, dy = (xx + pitch / 2) % pitch - pitch / 2, (yy + pitch / 2) % pitch - pitch / 2
            d = np.hypot(dx, dy)
            centre_edge = edge  # the lattice point's own distance in, near enough over a rivet's width
            head = (d < r) & (centre_edge > 5.0) & (centre_edge < 11.0) & cover
            layer.height[head] += 0.45 * np.sqrt(1 - (d[head] / r) ** 2)
            layer.albedo[head] *= 1.25
            seam = ((xx % 300.0) < 1.1) & cover & (edge > 3.0)
            layer.height[seam] -= 0.35
            layer.albedo[seam] *= 0.55
        if c.kind == "floor":
            # anti-slip tread plate: raised lozenges, alternating, 30 mm apart (finer aliases at this texel size)
            p = 30.0
            cu, cv = xx % p - p / 2, yy % p - p / 2
            even = ((xx // p + yy // p) % 2) == 0
            bar = np.where(even, (np.abs(cu - cv) < 3.4) & (np.abs(cu + cv) < 15.0), (np.abs(cu + cv) < 3.4) & (np.abs(cu - cv) < 15.0))
            layer.height[bar & cover] += 0.5
            layer.albedo[bar & cover] *= 1.15
        chip = _noise("c" + tag, h, w, max(1, int(0.002 * density)))
        worn = cover & (edge < wear_mm * (0.6 + chip)) & (ao > 0.62)
        layer.albedo[worn] = layer.albedo[worn] * 1.45 + 0.03
        layer.smooth[worn] += 0.14
        grime = np.clip((0.62 - ao) / 0.45, 0, 1) * cover
        layer.albedo *= (1.0 - 0.28 * grime)[..., None]
        layer.smooth -= 0.12 * grime
        layer.smooth += 0.05 * fine
        layer.ao = np.clip(ao, 0.12, 1.0)
        return layer

    def write(self, folder):
        """Paint and write the four PNGs; returns their paths."""
        os.makedirs(folder, exist_ok=True)
        paths = {}
        for key, pixels in self.paint().items():
            paths[key] = os.path.join(folder, "%s_%s.png" % (NAME, key))
            write_png(paths[key], pixels)
        return paths


def height_normals(height, mm_per_px):
    """Tangent-space normals of a height field in mm, rows down the image (V up)."""
    hp = np.pad(height, 1, mode="edge")
    dx = (hp[1:-1, 2:] - hp[1:-1, :-2]) * 0.5 / mm_per_px
    dy = (hp[2:, 1:-1] - hp[:-2, 1:-1]) * 0.5 / mm_per_px
    n = np.stack([-dx, dy, np.ones_like(dx)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def distance_in(mask, steps):
    """Approximate distance in pixels from each covered pixel to the nearest uncovered one, up to steps."""
    d = np.full(mask.shape, float(steps), np.float32)
    cur = mask.copy()
    for k in range(steps):
        er = cur.copy()
        er[1:] &= cur[:-1]
        er[:-1] &= cur[1:]
        er[:, 1:] &= cur[:, :-1]
        er[:, :-1] &= cur[:, 1:]
        d[cur & ~er] = np.minimum(d[cur & ~er], k + 0.5)
        cur = er
    d[~mask] = 0.0
    return d


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
