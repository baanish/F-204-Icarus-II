"""The cockpit, built on the canopy's design eye (canopy.EYE): one joined interior (front office, side consoles and
tub), the inner frames of the hood and the windscreen, the tac-screen quads, the warning lamps, the exterior proxies,
and the pivots the stock stick and throttle hang from. The stock seat, stick and throttle are not built here: the
Unity author places them (IcarusAuthor.Cockpit.cs), and STOCK holds where they stand so the interior clears them.

Construction follows the stock cockpits (the cockpit digest's rules): controls modelled at the stock parts' sizes and
triangle counts, lettering, dials and wear painted on one trim-sheet atlas (cockpit_atlas.py), every face on real
atlas area. The front office sits 40 mm lower than wave 1's, with the eye (owner, 2026-10-21); the stick and throttle
keep the Revoker's reach from the seat, which the stock seat keeps from the eye: a side stick on the right console,
the throttle on the left.

Positions are (s, x, z): s metres aft of the radome tip, x to the left, z above the radome-tip line.

    build(p, mats)          # from build_icarus._build, after the part tree is organised
    blender --background --factory-startup --python art/blender/cockpit.py -- <out_dir>   # build and render the review
"""
import math
import os
import sys
from collections import Counter

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import tessellate_polygon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_icarus as bi  # noqa: E402
import canopy  # noqa: E402
import cockpit_atlas  # noqa: E402
import materials  # noqa: E402
from solids import X, Y, Z, bvh, hit, must  # noqa: E402

MM = 0.001
# Object names the other modules and the Unity author build against. Renderers drawn in the cockpit view (layer 3)
# carry role "cockpit_view"; the proxies, seen from outside, carry "visual". Role "cockpit" is the cockpit_cell part.
INTERIOR = "cockpit_interior"
FRAMES_INNER = ("windscreen_frame_inner", "canopy_frame_inner")
TAC_SCREEN, WARNING_LAMPS = "cockpit_tac_screen", "cockpit_warning_lamps"
PROXIES = ("cockpit_proxy", "canopy_frame_proxy")
PIVOTS = ("cockpit_stick_pivot", "cockpit_throttle_pivot")  # empties the stock stick and throttle hang from
SEAT = "cockpit_seat"  # an empty where the stock seat's origin goes
SLOT = "Icarus_Cockpit"
# Triangles per renderer: target and cap (budget.py sums them). The cockpit's hard limit is 35,000 in all; the stock
# stick (1,890) and throttle (880) count toward it but are not built here. The warning lamps (40 to 80) and the stock
# seat count toward no total.
BUDGET = {
    "interior": {"target": 15000, "cap": 16000, "objects": (INTERIOR,), "cockpit": True},
    "canopy_frame_inner": {"target": 2600, "cap": 8000, "objects": ("canopy_frame_inner",), "cockpit": True},
    "windscreen_frame_inner": {"target": 1000, "cap": 1000, "objects": ("windscreen_frame_inner",), "cockpit": True},
    "tac_screen": {"target": 120, "cap": 120, "objects": (TAC_SCREEN,), "cockpit": True},
    "stock_hotas": {"target": 2770, "cap": 2770, "objects": (), "cockpit": True},
    "proxies": {"target": 940, "cap": 2930, "objects": PROXIES},
}
# Cockpit rules 2 to 6, 10, 16, 26, 27, 30 and 31 of the cockpit digest: (low, high).
RULES = {
    "interior_tris": (10500, 16000),  # rule 2's 13,500, raised to 16,000 for the cockpit's detail (owner, 2026-10-22)
    "cockpit_tris": (19500, 35000),  # all cockpit renderers; 19,500 is the reference aircraft, reported not padded
    "small_share": (2 / 3, 1.0),
    "items": (190, 330),
    "fasteners": (50, 95),
    "px_per_m_median": (300, 650),
    "panel_px_per_m": (1300, 1700),
    # display_width: the main pair side by side, as the F-16M's MFDs, the canvas split so each shows one set
    "display_dist": (0.73, 0.98), "display_below": (0.25, 0.43), "display_width": (0.37, 0.52),
    "screen_px_per_m": (1800, 2600),
    "overhead": (0.23, 0.36), "side": (0.35, 0.46), "sill": (0.27, 0.35), "panel_ahead": (0.60, 0.90),
    "front_office": (0.37, 0.74), "consoles": (0.08, 0.31), "tub": (0.12, 0.47),
    "bezel_mm": (2.0, 7.0), "ring_tris": (500, 2100),
    "frame_inner": (1300, 8000), "frame_shell": (850, 2800),
    "lamps": (40, 80), "proxy_interior": (700, 1030), "proxy_frame": (240, 1900), "hud": (0, 600),
    "glass_inset": (0.004, 0.006),
}
CLOSEUPS = {}

EYE = canopy.EYE
# The stock rig at the Revoker's offsets from its helmet eye, moved to EYE (Fighter1.prefab: helmetCamPoint, the
# EjectionSeat under the pilot rig, the joystick and the throttle). Boxes (s0, s1, |x| or x range, z0, z1) bound their
# meshes by height band; the interior keeps clear of them through the controls' travel (Cockpit: joystick 9 deg pitch
# and roll, throttle 6.5 deg about a pivot 1 m below its grip). The seat and the pilot in it sit SEAT_DROP lower than
# that offset, so the headbox clears the hood glass (owner, 2026-10-22); the eye stays at EYE.
SEAT_DROP = 0.020
SEAT_BOXES = [(3.75, 4.47, 0.270, -0.19, 0.31), (4.44, 4.68, 0.262, -0.19, 0.82), (4.68, 4.88, 0.190, 0.54, 0.82)]
SEAT_HEAD = [(4.54, 4.88, 0.188, 0.82, 0.94), (4.56, 4.83, 0.164, 0.94, 1.02), (4.57, 4.66, 0.164, 1.02, 1.06),
             (4.62, 4.64, 0.139, 1.06, 1.078)]  # the headbox, in 4 cm bands of the stock mesh
HEAD_GLASS_GAP = 0.005  # the least the headbox keeps from the hood's glass and frames, shut and opening
STOCK = {
    "seat_origin": (4.256, 0.0, 0.154 - SEAT_DROP),
    "seat": [(s0, s1, hx, z0 - SEAT_DROP, z1 - SEAT_DROP) for s0, s1, hx, z0, z1 in SEAT_BOXES + SEAT_HEAD],
    "seat_head": [(s0, s1, hx, z0 - SEAT_DROP, z1 - SEAT_DROP) for s0, s1, hx, z0, z1 in SEAT_HEAD],
    "stick_pivot": (3.936, -0.398, 0.343),
    "stick": [(3.895, 3.977, -0.432, -0.355, 0.332, 0.38), (3.904, 3.960, -0.409, -0.317, 0.38, 0.43),
              (3.868, 3.951, -0.408, -0.314, 0.43, 0.49), (3.844, 3.935, -0.374, -0.291, 0.49, 0.549)],
    "stick_deg": 9.0,
    "throttle_pivot": (3.869, 0.382, -0.641),
    "throttle": [(3.927, 3.999, 0.292, 0.416, 0.357, 0.385), (3.871, 3.999, 0.276, 0.406, 0.385, 0.415),
                 (3.862, 3.969, 0.261, 0.395, 0.415, 0.455)],
    "throttle_deg": 6.5,
}
LAYOUT = {
    "floor_z": -0.05,
    "footwell_s": 3.08,
    # the coaming under the windscreen: from its front (s0) back to where the hood takes over (s1), its sides this far
    # inside the skin
    "coaming": (2.36, 3.00, 0.008),
    "console": {"s0": 3.785, "s1": 4.84, "inner": 0.278, "top_z": 0.322},
    "pedals": {"s": 3.28, "x": 0.12, "bar": (3.18, 0.36)},
    "bulkhead": (4.88, 4.92),
    # The lining stands this far inside the skin, inboard of the fuselage frames' outer part; a rib covers the rest
    # of each frame (internals: 3 to 8 cm in, 25 mm thick, at s 3.4, 4.0 and 4.6).
    "lining_inset": 0.060,
    "ribs": (3.4125, 4.0125, 4.6125),
    "over_nose_margin": 0.005,
}
# What each display shows: its rect of the 1,024 x 512 tac-screen canvas (Icarus_TacScreen.prefab, the Revoker's
# layout; .cache/board/tac_regions.py reads it), in canvas pixels x0, y0, x1, y1 with y up from the bottom as UV v
# runs, and the density its glass is sized for. A, the tactical display: the radar map, or the targeting or landing
# camera in its place, with the NAV/RESET/VIEW/CNTR soft keys down its left edge and the fuel, throttle and heat
# gauges, mass, thrust-to-weight and the clock down its right. B: the weapon stations over the engine's thrust and RPM.
# C: heading, airspeed, radar altitude, climb rate, the horizon, AOA and VSI ladders. D: the system status list.
DISPLAYS = {
    "A": {"canvas": (0, 150, 590, 512), "px_per_m": 2050, "title": "TAC"},
    "B": {"canvas": (592, 150, 1024, 512), "px_per_m": 2050, "title": "STORES / ENGINE"},
    "C": {"canvas": (788, 4, 996, 148), "px_per_m": 1810, "title": "FLT INST"},
    "D": {"canvas": (438, 0, 606, 149), "px_per_m": 1850, "title": "SYS STATUS"},
}
TAC_SCREEN_PX = (1024, 512)
BEZEL = {"frame": 0.020, "height": 5 * MM, "recess_ring": 3 * MM, "recess_z": 2.5 * MM, "floor_z": 1 * MM,
         "screen_z": 1.5 * MM}
FRAME = {"glass_inset": 0.0052, "depth": 0.028, "seam_cover": 0.065}  # the inner frame shell, off the inner glass
SEAT_CLEAR = 0.010  # the inner frame stops this far up the glass from the seam, clear of the skin the hood seats in
LEDGE_DROP = 0.024  # the cockpit sill's top under the glass seam: 0.27 m or more below the eye (Cockpit rule 27)
LEDGE_S0 = 3.00  # the sill ledge starts where the coaming's sides end, so no skin shows between them


def P(s, x, z):
    return bi.P(s, x, z)


def sxz(v):
    return (v.y + bi.S0, v.x, v.z)


def eye_point():
    return P(*EYE)


def over_nose_z(s):
    return EYE[2] - canopy.OVER_NOSE_SLOPE * (EYE[0] - s)


def frame(origin, up, normal):
    """A placement: local Z along normal, Y as near up as allowed, X = Y x Z (the viewer's right)."""
    z = normal.normalized()
    y = (up - z * up.dot(z)).normalized()
    m = Matrix((y.cross(z), y, z)).transposed().to_4x4()
    m.translation = origin
    return m


def on_top(s, x, z):
    """Placement on a level surface: local Z up, local Y forward, so legends read from the seat."""
    return frame(P(s, x, z), -Y, Z)


# --- geometry gathering --------------------------------------------------------------------------------------------

def tris_of(faces):
    return sum(len(f) - 2 for f in faces)


def signed_volume(verts, faces):
    vol = 0.0
    for f in faces:
        a = verts[f[0]]
        for i in range(1, len(f) - 1):
            vol += a.dot(verts[f[i]].cross(verts[f[i + 1]]))
    return vol / 6.0


class Piece:
    """One closed solid or sheet in local space: vertices, faces (outward by construction or fixed by volume), a UV
    per face corner, and the faces dropped after orientation (undersides on a surface, never seen). A sheet turns its
    faces toward the eye when placed, unless keep: then they face as built."""

    def __init__(self, sheet=False, keep=False):
        self.verts, self.faces, self.uvs, self.hidden, self.sheet, self.keep = [], [], [], set(), sheet, keep

    def add(self, verts, faces, uvs, hidden=False):
        base = len(self.verts)
        self.verts += [Vector(v) for v in verts]
        for f, uv in zip(faces, uvs):
            if hidden:
                self.hidden.add(len(self.faces))
            self.faces.append(tuple(base + i for i in f))
            self.uvs.append(list(uv))
        return self


class Gather:
    """Faces for one renderer in world space, with per-face UVs and a group name for the region tallies."""

    def __init__(self, name):
        self.name = name
        self.verts, self.faces, self.uvs, self.groups = [], [], [], []

    def put(self, piece, m=None, group="", toward=None):
        """Add piece at placement m; a sheet's faces turn toward the point toward (default the eye)."""
        m = m or Matrix.Identity(4)
        verts = [m @ v for v in piece.verts]
        faces, uvs = list(piece.faces), list(piece.uvs)
        if piece.keep:
            pass
        elif piece.sheet:
            target = toward or eye_point()
            for i, f in enumerate(faces):
                n = _normal([verts[k] for k in f])
                c = sum((verts[k] for k in f), Vector()) / len(f)
                if n.dot(target - c) < 0:
                    faces[i], uvs[i] = f[::-1], uvs[i][::-1]
        elif signed_volume(verts, faces) < 0:
            faces = [f[::-1] for f in faces]
            uvs = [uv[::-1] for uv in uvs]
        base = len(self.verts)
        self.verts += verts
        for i, (f, uv) in enumerate(zip(faces, uvs)):
            if i in piece.hidden:
                continue
            self.faces.append(tuple(base + k for k in f))
            self.uvs.append(uv)
            self.groups.append(group)

    def tris(self, group=None):
        return sum(len(f) - 2 for f, g in zip(self.faces, self.groups) if group is None or g == group)

    def object(self, mat_names, mat_of=None):
        """The mesh object at the identity in the Icarus collection, faces on mat_of(group) (default the first), its
        charted faces flagged in the face attribute "bake". Runs once the atlas is packed."""
        used = sorted(set(k for f in self.faces for k in f))
        remap = {k: i for i, k in enumerate(used)}
        me = bpy.data.meshes.new(self.name)
        me.from_pydata([tuple(self.verts[k]) for k in used], [], [tuple(remap[k] for k in f) for f in self.faces])
        layer = me.uv_layers.new(name="UVMap")
        layer.data.foreach_set("uv", [c for uv in self.uvs for p in uv for c in cockpit_atlas.resolve(p)])
        baked = me.attributes.new("bake", "INT", "FACE")
        baked.data.foreach_set("value", [int(isinstance(uv[0], cockpit_atlas.ChartPoint) and uv[0].chart.kind in
                                              cockpit_atlas.KINDS) for uv in self.uvs])
        for n in mat_names:
            me.materials.append(bpy.data.materials.get(n) or materials.stock(n))
        if mat_of:
            me.polygons.foreach_set("material_index", [mat_names.index(mat_of(g)) for g in self.groups])
        me.validate()
        me.update()
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(35))
        obj = bpy.data.objects.new(self.name, me)
        bi.TARGET.objects.link(obj)
        return obj


def _normal(points):
    n = Vector()
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        n += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
    return n.normalized() if n.length > 1e-12 else Vector((0.0, 0.0, 1.0))


# --- UV mapping onto the atlas -------------------------------------------------------------------------------------

def strip_uvs(points, strip, along=None):
    """A face mapped flat onto a full-width strip: U along the face (along, or its longest edge), V across it, at the
    strip's density, or less where the face is taller than the strip. U repeats along the strip."""
    n = _normal(points)
    if along is not None and (along - n * along.dot(n)).length > 1e-6:
        u = (along - n * along.dot(n)).normalized()
    else:
        edges = [(points[(i + 1) % len(points)] - points[i]) for i in range(len(points))]
        e = max(edges, key=lambda d: d.length)
        u = e.normalized() if e.length > 1e-9 else n.orthogonal().normalized()
    v = n.cross(u)
    us, vs = [p.dot(u) for p in points], [p.dot(v) for p in points]
    span = max(vs) - min(vs)
    height_px = (strip.v1 - strip.v0) * cockpit_atlas.H
    d = min(strip.px_per_m, height_px / span) if span > 1e-9 else strip.px_per_m
    return [(a * d / cockpit_atlas.W, strip.v0 + (b - min(vs)) * d / cockpit_atlas.H) for a, b in zip(us, vs)]


def rect_uvs(points, rect, xaxis=None):
    """A face fitted into a tile or label chart, flat in its own plane (X from xaxis, or local X)."""
    n = _normal(points)
    xa = xaxis or X
    u = xa - n * xa.dot(n)
    u = u.normalized() if u.length > 1e-6 else n.orthogonal().normalized()
    v = n.cross(u)
    us, vs = [p.dot(u) for p in points], [p.dot(v) for p in points]
    du, dv = max(max(us) - min(us), 1e-9), max(max(vs) - min(vs), 1e-9)
    return [rect.frac((a - min(us)) / du, (b - min(vs)) / dv) for a, b in zip(us, vs)]


def rect_box_uvs(points, rect, box):
    """Points in a cap mapped into a tile or label chart by a shared box (x0, y0, x1, y1) in local X and Y, so a fan's
    triangles tile it together."""
    x0, y0, x1, y1 = box
    return [rect.frac((p.x - x0) / (x1 - x0), (p.y - y0) / (y1 - y0)) for p in points]


class UV:
    """What a face maps onto: a strip by name, a tile or label chart (fitted face by face, or across a whole cap)."""

    def __init__(self, atlas):
        self.atlas = atlas

    def __call__(self, spec, points, box=None, along=None):
        if isinstance(spec, str):
            return strip_uvs(points, self.atlas.strip(spec), along)
        if box is not None:
            return rect_box_uvs(points, spec, box)
        return rect_uvs(points, spec)


def ring_rect(hw, hh, z, r=0.0, seg=0):
    """Rounded rectangle at height z, counter-clockwise seen from +Z; seg arc segments per corner (0: square)."""
    pts = []
    for cx, cy, a0 in ((hw - r, -hh + r, -90), (hw - r, hh - r, 0), (-hw + r, hh - r, 90), (-hw + r, -hh + r, 180)):
        for i in range(seg + 1):
            a = math.radians(a0 + (90.0 * i / seg if seg else 45.0))
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    return pts


def ring_circle(rx, z, k, ry=None, phase=0.0):
    ry = rx if ry is None else ry
    return [(rx * math.cos(phase + 2 * math.pi * i / k), ry * math.sin(phase + 2 * math.pi * i / k), z) for i in range(k)]


def stack(uv, rings, bands, top=None, bottom=None, top_uv=None, bottom_uv=None, bottom_hidden=False, top_apex=None,
          bottom_apex=None):
    """A closed solid from rings of local points (same count, counter-clockwise from +Z), first ring to last. bands:
    one UV spec per band (or one for all). The last ring closes with an n-gon, or a fan to top_apex, mapped by top_uv
    (a rect fitted across the cap, or a strip); the first likewise with bottom_uv. bottom_hidden drops the underside
    once the solid is oriented."""
    k = len(rings[0])
    names = bands if isinstance(bands, list) else [bands] * (len(rings) - 1)
    piece = Piece()
    rings = [[Vector(p) for p in r] for r in rings]
    verts = [p for r in rings for p in r]
    faces, uvs = [], []
    for j in range(len(rings) - 1):
        a, b = j * k, (j + 1) * k
        for i in range(k):
            f = (a + i, a + (i + 1) % k, b + (i + 1) % k, b + i)
            faces.append(f)
            uvs.append(uv(names[j], [verts[q] for q in f], along=verts[a + (i + 1) % k] - verts[a + i]))
    piece.add(verts, faces, uvs)

    def cap(ring, apex, spec, up):
        xs, ys = [p.x for p in ring], [p.y for p in ring]
        box = (min(xs), min(ys), max(xs), max(ys))
        if apex is None:
            f = list(range(k)) if up else list(range(k))[::-1]
            pts = [ring[i] for i in f]
            u = uv(spec, pts, box=box if not isinstance(spec, str) else None)
            piece.add(pts, [tuple(range(k))], [u], hidden=not up and bottom_hidden)
        else:
            apex = Vector(apex)
            for i in range(k):
                tri = [ring[i], ring[(i + 1) % k], apex] if up else [apex, ring[(i + 1) % k], ring[i]]
                u = uv(spec, tri, box=box if not isinstance(spec, str) else None)
                piece.add(tri, [(0, 1, 2)], [u], hidden=not up and bottom_hidden)
    cap(rings[-1], top_apex, top_uv or names[-1], True)
    cap(rings[0], bottom_apex, bottom_uv or names[0], False)
    return piece


def sheet(uv, pts, spec, box=None):
    """A one-sided quad or n-gon, turned to the eye when placed."""
    piece = Piece(sheet=True)
    pts = [Vector(p) for p in pts]
    piece.add(pts, [tuple(range(len(pts)))], [uv(spec, pts, box=box)])
    return piece


def grid_sheet(uv, grid, spec, along=None, keep=False):
    """A one-sided sheet from rows of points, each cell mapped flat onto spec, or the whole grid unrolled onto a chart
    (grid_chart). keep: the faces stay as wound (row by row, the normal (next column) x (next row)), not turned to
    the eye."""
    piece = Piece(sheet=True, keep=keep)
    cols = len(grid[0])
    verts = [Vector(p) for row in grid for p in row]
    flat = grid_chart(grid, spec) if isinstance(spec, cockpit_atlas.Chart) else None
    faces, uvs = [], []
    for r in range(len(grid) - 1):
        for c in range(cols - 1):
            f = (r * cols + c, r * cols + c + 1, (r + 1) * cols + c + 1, (r + 1) * cols + c)
            faces.append(f)
            uvs.append([flat[i] for i in f] if flat else uv(spec, [verts[i] for i in f], along=along))
    piece.add(verts, faces, uvs)
    return piece


def grid_chart(grid, chart, closed=False):
    """Chart points for a grid of world points (rows of columns), unrolled by arc length: across a row by the rows'
    mean run to each column, down the rows by the columns' mean run; closed: each row loops back to its start."""
    rows = [[Vector(p) for p in row] for row in grid]
    ncol = len(rows[0])
    runs = []
    for row in rows:
        pts = row + row[:1] if closed else row
        run = [0.0]
        for a, b in zip(pts, pts[1:]):
            run.append(run[-1] + (b - a).length)
        runs.append(run)
    u = [sum(r[j] for r in runs) / len(runs) for j in range(len(runs[0]))]
    down = [0.0]
    for i in range(1, len(rows)):
        down.append(down[-1] + sum((rows[i][j] - rows[i - 1][j]).length for j in range(ncol)) / ncol)
    out = [chart.point(u[j], -down[i]) for i in range(len(rows)) for j in range(ncol)]
    if closed:  # the seam column, for faces that close each ring
        out += [chart.point(u[ncol], -down[i]) for i in range(len(rows))]
    return out


def solid(uv, verts, faces, spec, along=None, hidden=()):
    """A closed solid in world space, every face mapped flat onto a strip; hidden: face indices to drop."""
    piece = Piece()
    verts = [Vector(v) for v in verts]
    for i, f in enumerate(faces):
        pts = [verts[q] for q in f]
        piece.add(pts, [tuple(range(len(f)))], [uv(spec(i) if callable(spec) else spec, pts, along=along)],
                  hidden=i in hidden)
    return piece


def block(uv, s0, s1, x0, x1, z0, z1, spec, hide_bottom=True):
    v = [P(s, x, z) for s in (s0, s1) for x in (x0, x1) for z in (z0, z1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return solid(uv, v, faces, spec, hidden=(4,) if hide_bottom else ())


def loft_piece(uv, rings, spec, along=None, caps=True):
    """Rings of world points (same count) joined in order, the ends capped. On a chart, the bands unroll round the
    rings onto it and the caps go on the strip `caps` names (a string), or are left open."""
    k = len(rings[0])
    verts = [Vector(p) for r in rings for p in r]
    faces = [(j * k + i, j * k + (i + 1) % k, (j + 1) * k + (i + 1) % k, (j + 1) * k + i)
             for j in range(len(rings) - 1) for i in range(k)]
    if isinstance(spec, cockpit_atlas.Chart):
        flat = grid_chart(rings, spec, closed=True)
        seam = len(rings) * k
        corner = lambda j, i: flat[seam + j] if i == k else flat[j * k + i]
        piece = Piece()
        uvs = [[corner(j, i), corner(j, i + 1), corner(j + 1, i + 1), corner(j + 1, i)]
               for j in range(len(rings) - 1) for i in range(k)]
        piece.add(verts, faces, uvs)
        if isinstance(caps, str):
            for f in (tuple(range(k))[::-1], tuple((len(rings) - 1) * k + i for i in range(k))):
                pts = [verts[q] for q in f]
                piece.add(pts, [tuple(range(k))], [uv(caps, pts, along=along)])
        return piece
    if caps:
        faces += [tuple(range(k))[::-1], tuple((len(rings) - 1) * k + i for i in range(k))]
    return solid(uv, verts, faces, spec, along=along)


def tube(uv, points, r, sides, spec):
    """A capped tube of radius r through world points."""
    rings = []
    ref = None
    for i, o in enumerate(points):
        t = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
        ref = ref if ref is not None else (Z if abs(t.z) < 0.9 else X)
        a = (ref - t * ref.dot(t)).normalized()
        ref = a
        b = t.cross(a)
        rings.append([o + (a * math.cos(2 * math.pi * k / sides) + b * math.sin(2 * math.pi * k / sides)) * r
                      for k in range(sides)])
    return loft_piece(uv, rings, spec)


# --- the control kit (local space: Z out of the surface, Y up the legend, X to the right) -----------------------------

class Kit:
    """The controls, each built once per legend and reused, so copies share their UVs (Cockpit rule 11). Proportions,
    heights and segment counts follow the stock Revoker, Vortex and Ifrit parts measured from the game export
    (.cache/board/kit/kit-stats.txt); the geometry is drawn here. Each part's lowest band sits on a strip whose AO falls
    toward its foot, its upper bands on the same paint without it."""

    def __init__(self, uv, atlas):
        self.uv, self.atlas = uv, atlas

    def revolve(self, profile, seg, bands, top_uv=None, top_apex=None, phase=0.0):
        """A part turned from a profile of (height, radius) pairs, bottom up; bands: a strip per band (or one)."""
        rings = [ring_circle(r * MM, h * MM, seg, phase=phase) for h, r in profile]
        return stack(self.uv, rings, bands, top_uv=top_uv, top_apex=top_apex, bottom_hidden=True)

    def key(self, legend=None):
        """Display key: 12.2 x 10.6 x 6.1 mm, a 0.8 mm bevel round its cap, the cap sloping down toward the bottom,
        legend on the cap. 26 tris."""
        w, d, h, b, drop = 12.2 * MM, 10.6 * MM, 6.1 * MM, 0.8 * MM, 0.8 * MM
        lip = lambda x, y, z: (x, y, z - (drop if y < 0 else 0.0))
        base = ring_rect(w / 2, d / 2, 0.0)
        shoulder = [lip(x, y, h - b) for x, y, _ in ring_rect(w / 2, d / 2, 0.0)]
        top = [lip(x, y, h) for x, y, _ in ring_rect(w / 2 - b, d / 2 - b, 0.0)]
        cap = self.atlas.label(legend or " ", paper="key", cap_mm=2.6,
                               size_mm=((w - 2 * b) * 1000, (d - 2 * b) * 1000))
        return stack(self.uv, [base, shoulder, top], ["key_lo", "keyside"], top_uv=cap, bottom_hidden=True)

    def indicator(self, lens="lens_clear", legend=None, body="keyside"):
        """Indicator or push button: 17.1 x 16.4 x 9.5 mm, 1.15 mm bevel, the lens framed and set 0.9 mm into the
        top. 46 tris."""
        w, d, h, b = 17.1 * MM, 16.4 * MM, 9.5 * MM, 1.15 * MM
        rings = [ring_rect(w / 2, d / 2, 0.0), ring_rect(w / 2, d / 2, h - b), ring_rect(w / 2 - b, d / 2 - b, h),
                 ring_rect(w / 2 - 2 * b, d / 2 - 2 * b, h), ring_rect(w / 2 - 2 * b, d / 2 - 2 * b, h - 0.9 * MM),
                 ring_rect(w / 2 - 2 * b - 0.3 * MM, d / 2 - 2 * b - 0.3 * MM, h - 0.6 * MM)]
        lens_w, lens_d = w - 4 * b - 0.6 * MM, d - 4 * b - 0.6 * MM
        cap = self.atlas.label(legend, ink="ink_dark" if lens in ("lens_amber", "lens_green") else "ink", paper=lens,
                               cap_mm=2.4 if "\n" in legend else 3.0, size_mm=(lens_w * 1000, lens_d * 1000)) \
            if legend else self.atlas.tile(lens)
        return stack(self.uv, rings, ["key_lo", body, body, "recess", "recess"], top_uv=cap,
                     top_apex=(0.0, 0.0, h - 0.4 * MM))

    def knob(self, small=False):
        """Stepped rotary knob, 12-sided: a 15.6 mm skirt 8.5 mm tall, a chamfer in to the 9.5 mm grip, 16.2 mm
        tall, its top an index line (the Revoker's and Ifrit's 82-tri knob). small: the Ifrit's 0.69 scale."""
        k = 0.69 if small else 1.0
        prof = [(0.0, 7.8), (8.55, 7.25), (9.47, 5.16), (16.2, 4.6)]
        return self.revolve([(h * k, r * k) for h, r in prof], 12, ["knob_lo", "knurl", "knurl"],
                            top_uv=self.atlas.tile("knob_top"))

    def selector(self):
        """Pointer selector: a 41 mm skirt 5.4 mm tall, a chamfer up to a 28 mm boss, and the pointer bar across it,
        19.9 mm over the panel (the Revoker's and Ifrit's 214-tri selector)."""
        skirt = self.revolve([(0.0, 20.5), (4.6, 20.5), (5.4, 19.7), (7.9, 14.4), (8.4, 13.6)], 16,
                             ["knob_lo", "knurl", "knurl", "knurl"], top_uv=self.atlas.tile("knob_top_large"))
        rings = [ring_rect(0.0055, 0.0145, z, 0.0045, 2) for z in (8.0 * MM, 18.6 * MM)] + \
            [ring_rect(0.0045, 0.0135, 19.9 * MM, 0.0035, 2)]
        bar = stack(self.uv, rings, ["knob_lo", "knurl"], top_uv=self.atlas.tile("knob_top"), bottom_hidden=True)
        return [skirt, bar]

    def toggle(self, throw_deg=30.0):
        """Toggle switch: a 19.8 mm washer and a hex nut 3.2 mm over the panel, and a 25 mm bat lever on its bushing
        ending in a 7.8 mm ball, thrown toward +Y, polished metal, 12-sided (the stock 154 + 72 tris)."""
        def hexagon(r, z):  # a hex nut's outline on the washer's 12 points: corners and edge midpoints
            return [(r * (1.0 if i % 2 == 0 else math.cos(math.pi / 6)) * math.cos(math.pi * i / 6),
                     r * (1.0 if i % 2 == 0 else math.cos(math.pi / 6)) * math.sin(math.pi * i / 6), z) for i in range(12)]
        rings = [ring_circle(9.9 * MM, 0.0, 12), ring_circle(9.9 * MM, 0.9 * MM, 12), ring_circle(9.2 * MM, 1.3 * MM, 12),
                 hexagon(6.6 * MM, 1.3 * MM), hexagon(6.6 * MM, 2.8 * MM), hexagon(5.8 * MM, 3.2 * MM)]
        collar = stack(self.uv, rings, ["metal_lo", "metal", "metal", "metal", "metal"], top_apex=(0.0, 0.0, 3.2 * MM),
                       bottom_hidden=True)
        lever = Matrix.Translation((0.0, 0.0, 3.0 * MM)) @ Matrix.Rotation(math.radians(-throw_deg), 4, "X")
        prof = [(0.0, 4.0), (2.6, 3.7), (3.4, 2.3), (17.0, 1.9), (18.8, 2.9), (20.4, 3.85), (22.4, 3.75), (24.0, 2.6)]
        rings = [[tuple(lever @ Vector(p)) for p in ring_circle(r * MM, h * MM, 12)] for h, r in prof]
        bat = stack(self.uv, rings, "metal", top_apex=tuple(lever @ Vector((0.0, 0.0, 24.9 * MM))), bottom_hidden=True)
        return [collar, bat]

    def guard(self):
        """A guarded toggle: the red guard closed over it, 46 x 22 x 15 mm, its hinge at the -Y end, the edges
        chamfered, both ends closed, on yellow and black hatching (the stock guards lie closed, 150 + 32 tris)."""
        L, hw, c, t = 46.0 * MM, 11.0 * MM, 1.6 * MM, 1.5 * MM
        heights = [9.0, 12.5, 14.6, 15.4, 15.4, 14.0]
        rings = []
        for i, hh in enumerate(heights):  # a hood over the switch, closed at both ends
            y, h = -L / 2 + 4 * MM + (L - 4 * MM - t) * i / (len(heights) - 1), hh * MM
            rings.append([(x, y, z) for x, z in ((hw, 0.0), (hw, h - c), (hw - c, h), (-hw + c, h), (-hw, h - c),
                                                 (-hw, 0.0))])  # closed in section: no hollow shows at its ends
        lid = stack(self.uv, rings, ["guard_lo", "guard", "guard", "guard", "guard"], top_uv="guard", bottom_uv="guard")
        hinge = stack(self.uv, [[(x, -L / 2 + 2.5 * MM + 2.4 * MM * math.cos(a), 3.0 * MM + 2.4 * MM * math.sin(a))
                                 for a in [2 * math.pi * i / 8 for i in range(8)]] for x in (-hw - 1.5 * MM, hw + 1.5 * MM)],
                      "metal")
        hatch = self.placard(self.atlas.tile("hatch"), size=(2 * hw + 0.010, L + 0.006))
        return [hatch, lid, hinge]

    def rocker(self, legend="+\n-"):
        """A rocker switch, 10 x 22.4 x 6.3 mm, rocked toward +Y, its legend on its face (the Ifrit's)."""
        w, d = 5.0 * MM, 11.2 * MM
        top = [(x, y, 6.3 * MM - 2.2 * MM * (0.5 - y / (2 * d))) for x, y, _ in ring_rect(w - 0.5 * MM, d - 0.5 * MM, 0.0, 1.2 * MM, 1)]
        rings = [ring_rect(w + 0.6 * MM, d + 0.6 * MM, 0.0, 1.0 * MM, 1), ring_rect(w + 0.6 * MM, d + 0.6 * MM, 1.2 * MM, 1.0 * MM, 1),
                 ring_rect(w, d, 1.2 * MM, 1.2 * MM, 1), top]  # the frame, its top, in to the body and up its sides
        return [stack(self.uv, rings, ["keyside", "recess", "key_lo"], bottom_hidden=True,
                      top_uv=self.atlas.label(legend, paper="key", cap_mm=2.4, size_mm=(8.0, 19.0)))]

    def breaker(self):
        """A circuit breaker: an eight-sided 9 mm button 7 mm tall, no underside. 22 tris."""
        rings = [ring_circle(4.5 * MM, 0.0, 8, phase=math.pi / 8), ring_circle(4.5 * MM, 7 * MM, 8, phase=math.pi / 8)]
        return stack(self.uv, rings, "keyside", top_uv=self.atlas.tile("breaker_top"), bottom_hidden=True)

    def fastener(self):
        """Panel fastener: six-sided head, 6.6 x 6.9 x 1.65 mm, no underside. 28 tris."""
        rings = [ring_circle(3.3 * MM, 0.0, 6, ry=3.46 * MM), ring_circle(3.3 * MM, 0.6 * MM, 6, ry=3.46 * MM),
                 ring_circle(2.05 * MM, 1.65 * MM, 6, ry=2.15 * MM)]
        return stack(self.uv, rings, "metal", top_uv=self.atlas.tile("fastener_top"), bottom_hidden=True)

    def placard(self, rect, lift=0.3 * MM, size=None):
        """A textured quad of rect's size (or size), lift above the surface, facing +Z. Two tris."""
        w, h = (size or (rect.w_m, rect.h_m))
        pts = [(-w / 2, -h / 2, lift), (w / 2, -h / 2, lift), (w / 2, h / 2, lift), (-w / 2, h / 2, lift)]
        piece = Piece(sheet=True)
        piece.add([Vector(p) for p in pts], [(0, 1, 2, 3)], [[rect.frac(0, 0), rect.frac(1, 0), rect.frac(1, 1), rect.frac(0, 1)]])
        return piece

    def bezel(self, w, h, frame_w, corner_r, hgt=None, sunk=0.0):
        """Stepped display frame round a w x h glass: rolled outer edge, flat top hgt high, a step down to a 3 mm
        recess ring and a well whose floor sits under the screen; sunk: the well runs on down that far under the face
        it stands on (through a hole in it)."""
        seg = 3 if corner_r >= 0.006 else 2
        ring, rz, fz = BEZEL["recess_ring"], BEZEL["recess_z"], BEZEL["floor_z"]
        hgt = hgt or BEZEL["height"]
        if sunk:
            rz, fz = min(rz, hgt - 1.5 * MM), -sunk

        def at(d, z):
            r = MM + (corner_r + d - MM) * min(1.0, d / (ring + MM))
            return ring_rect(w / 2 + d, h / 2 + d, z, r, seg)
        well = 2 * MM if sunk else 0.0  # a sunk well stands clear of the glass, so oblique sight lines reach its edge
        rings = [at(frame_w, 0.0), at(frame_w, hgt - MM), at(frame_w - MM, hgt), at(ring + MM, hgt), at(ring, rz),
                 at(well, rz), at(well, fz)]
        return stack(self.uv, rings, ["bezel", "bezel", "bezel", "bezel", "recess", "recess"], top_uv="recess",
                     bottom_hidden=True)

    def dial(self, face, r=0.030):
        """A round instrument: a 16-sided bezel ring, its glass face set 3 mm in. 96 tris with its painted face."""
        rings = [ring_circle(r, 0.0, 16), ring_circle(r, 6 * MM, 16), ring_circle(r - 3 * MM, 6 * MM, 16),
                 ring_circle(r - 4 * MM, 3 * MM, 16)]
        return stack(self.uv, rings, ["bezel", "bezel", "recess"], top_uv=self.atlas.tile(face), bottom_hidden=True)


def bezel_corners(w, h, frame_w, corner_r):
    d = (frame_w + BEZEL["recess_ring"] + MM) / 2
    r = corner_r + d
    return [(sx * (w / 2 - corner_r + r * 0.7071), sy * (h / 2 - corner_r + r * 0.7071), BEZEL["height"])
            for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def quad(m, w, h, lift):
    return [m @ Vector((x, y, lift)) for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def offset_outline(pts, d):
    """Move a counter-clockwise outline inward by d, mitring the corners."""
    out = []
    for i, p in enumerate(pts):
        a, b = Vector(pts[i - 1]), Vector(pts[(i + 1) % len(pts)])
        p = Vector(p)
        n1 = Vector((-(p - a).y, (p - a).x)).normalized()
        n2 = Vector((-(b - p).y, (b - p).x)).normalized()
        bis = (n1 + n2).normalized()
        out.append(p + bis * d / bis.dot(n1))
    return out


# --- faces and plates -----------------------------------------------------------------------------------------------

PLATE = {"depth": 0.004, "chamfer": 0.0015}  # plates sit this far into their face, edges chamfered


def plane_sheet(chart, outline, holes=(), lift=0.0):
    """A flat sheet in local X, Y at Z = lift: outline less holes (counter-clockwise point lists), on chart in its own
    metres."""
    polys = [[Vector((x, y, lift)) for x, y in outline]] + [[Vector((x, y, lift)) for x, y in h] for h in holes]
    tris = [tuple(t) for t in tessellate_polygon(polys)]
    flat = [p for poly in polys for p in poly]
    tris = [t if (flat[t[1]] - flat[t[0]]).cross(flat[t[2]] - flat[t[0]]).z > 0 else t[::-1] for t in tris
            if abs((flat[t[1]] - flat[t[0]]).cross(flat[t[2]] - flat[t[0]]).z) > 2e-8]
    piece = Piece(sheet=True, keep=True)
    piece.add(flat, tris, [[chart.point(flat[i].x, flat[i].y) for i in t] for t in tris])
    return piece


def walls(outline, z0, z1, spec, uv, inward=True):
    """Side walls down a counter-clockwise outline from z0 to z1, facing in (a pocket) or out."""
    piece = Piece(sheet=True, keep=True)
    n = len(outline)
    for i in range(n):
        (ax, ay), (bx, by) = outline[i], outline[(i + 1) % n]
        quad = [Vector((ax, ay, z0)), Vector((bx, by, z0)), Vector((bx, by, z1)), Vector((ax, ay, z1))]
        if (z1 < z0) != inward:
            quad = quad[::-1]
        piece.add(quad, [(0, 1, 2, 3)], [uv(spec, quad)])
    return piece


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rounded(x0, y0, x1, y1, r, seg=2):
    pts = ring_rect((x1 - x0) / 2, (y1 - y0) / 2, 0.0, r, seg)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [(cx + p[0], cy + p[1]) for p in pts]


class Face:
    """A flat face (a panel, a console top, a wall): a placement m, an outline in local metres, its chart, the holes
    cut in it. Plates are pockets set into it; bezels and other parts stand on it."""

    def __init__(self, name, m, outline, chart):
        self.name, self.m, self.outline, self.chart = name, m, outline, chart
        self.holes = []
        self.plates = []  # (title, x0, y0, x1, y1), for the layout plan

    def at(self, x, y, lift=0.0):
        return self.m @ Matrix.Translation((x, y, lift))

    def point(self, x, y, lift=0.0):
        return self.m @ Vector((x, y, lift))

    def pocket(self, g, kit, uv, x0, y0, x1, y1, title=None, fasteners=4, group="front", floor_holes=()):
        """A plate set PLATE depth into the face, its edge chamfered, fasteners at its corners (and mid-sides when
        there are six or eight), its legend along its top edge; floor_holes: outlines cut through the plate (a
        throttle slot). Returns the plate's top as a placement maker."""
        d, c = PLATE["depth"], PLATE["chamfer"]
        hole = rect(x0, y0, x1, y1)
        self.holes.append(hole)
        self.plates.append((title, x0, y0, x1, y1))
        g.put(walls(hole, 0.0, -d - c, "bezel_dark", uv), self.m, group)
        inner = rect(x0 + c, y0 + c, x1 - c, y1 - c)
        ring = Piece(sheet=True, keep=True)
        for i in range(4):
            a, b = hole[i], hole[(i + 1) % 4]
            p, q = inner[i], inner[(i + 1) % 4]
            quad = [Vector((a[0], a[1], -d - c)), Vector((b[0], b[1], -d - c)), Vector((q[0], q[1], -d)),
                    Vector((p[0], p[1], -d))]
            ring.add(quad, [(0, 1, 2, 3)], [[self.chart.point(v.x, v.y) for v in quad]])
        g.put(ring, self.m, group)
        g.put(plane_sheet(self.chart, inner, floor_holes, lift=-d), self.m, group)
        e = 0.0065
        spots = [(x0 + e, y0 + e), (x1 - e, y0 + e), (x1 - e, y1 - e), (x0 + e, y1 - e)]
        if fasteners >= 6:
            spots += [((x0 + x1) / 2, y0 + e), ((x0 + x1) / 2, y1 - e)]
        if fasteners >= 8:
            spots += [(x0 + e, (y0 + y1) / 2), (x1 - e, (y0 + y1) / 2)]
        for x, y in spots[:fasteners]:
            g.put(kit.fastener(), self.at(x, y, -d), group)
        if title:
            lab = kit.atlas.label(title, cap_mm=3.5)
            g.put(kit.placard(lab), self.at((x0 + x1) / 2, y1 - 0.0035 - lab.h_m / 2, -d), group)
        return lambda x, y, lift=0.0: self.at(x, y, -d + lift)

    def close(self, g, group="front"):
        g.put(plane_sheet(self.chart, self.outline, self.holes), self.m, group)
        return self


# --- the space the cockpit stands in -------------------------------------------------------------------------------

class Space:
    """The skin's inside and the canopy's seam, sampled where the tub needs them."""

    def __init__(self, p):
        import internals
        self.p = p
        O = bpy.data.objects
        self.skin = bvh([o for o in bi.TARGET.all_objects if o.type == "MESH" and o.get("role") == "skin"])
        self.outer_glass = bvh([O[canopy.GLASS_OUTER], O[canopy.WINDSCREEN]])
        self.inner_glass = bvh([O[canopy.GLASS_INNER], O[canopy.WINDSCREEN_INNER]])
        self.sill_objects = [O[n] for n in ("skin_forward_L", "skin_forward_R", "dorsal_cover")]
        self.sill = bvh(self.sill_objects)  # the cut skin under the seam
        self._rings = {}
        self.internals = internals

    def wall_x(self, s, z):
        """|x| of the lining at (s, z): the skin's section pulled in by LAYOUT lining_inset, on the left side."""
        key = round(s, 4)
        if key not in self._rings:
            ring = self.internals.ring_at(self.p, s, LAYOUT["lining_inset"])
            self._rings[key] = sorted((v.z, v.x) for v in ring if v.x > 0)
        pts = self._rings[key]
        zs, xs = [q[0] for q in pts], [q[1] for q in pts]
        return float(np.interp(z, zs, xs))

    def seam(self, s):
        """(x, z) where the left inner glass meets the skin at s."""
        f = canopy.station(min(max(s, 2.96), 5.08))
        psi = canopy.seam_psi(self.outer_glass, self.skin, f, 1)
        point, _, _ = canopy.glass_at(self.inner_glass, f, psi)
        return point.x, point.z

    def skin_x(self, s, z, inset):
        """|x| of the skin's section pulled in by inset, at (s, z), on the left side."""
        key = (round(s, 4), inset)
        if key not in self._rings:
            ring = self.internals.ring_at(self.p, s, inset)
            self._rings[key] = sorted((v.z, v.x) for v in ring if v.x > 0)
        pts = self._rings[key]
        return float(np.interp(z, [q[0] for q in pts], [q[1] for q in pts]))

    def hood_sweep(self, extra):
        """Every hood vertex (its frame, both glass layers, and the extra Gathers hung from it) through the hinge's
        travel in 2.5 degree steps, closed included, as an array of (s, x, z)."""
        O = bpy.data.objects
        hinge = O["canopy"]
        a, u = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
        pts = [o.matrix_world @ v.co for o in hinge.children if o.type == "MESH" for v in o.data.vertices]
        pts += [v for g in extra for v in g.verts]
        self.hood = bvh([o for o in hinge.children if o.type == "MESH"])
        self.hood_extra = BVHTree.FromPolygons([v for g in extra for v in g.verts],
                                               [tuple(k + sum(len(h.verts) for h in extra[:i]) for k in face)
                                                for i, g in enumerate(extra) for face in g.faces]) if extra else None
        out, verts, polys = [], [], []
        faces = [(o.matrix_world, o.data) for o in hinge.children if o.type == "MESH"]
        steps = int(math.ceil(abs(hinge["travel_deg"]) / 2.5))
        for k in range(steps + 1):
            turn = Matrix.Translation(a) @ Matrix.Rotation(math.radians(hinge["travel_deg"] * k / steps), 4, u) \
                @ Matrix.Translation(-a)
            out += [sxz(turn @ p) for p in pts]
            for m, me in faces:
                base = len(verts)
                verts += [turn @ m @ v.co for v in me.vertices]
                polys += [tuple(base + i for i in f.vertices) for f in me.polygons]
            for g in extra:
                base = len(verts)
                verts += [turn @ v for v in g.verts]
                polys += [tuple(base + i for i in f) for f in g.faces]
        self.sweep = np.array(out)
        self.swept = BVHTree.FromPolygons(verts, polys)

    def sweep_floor(self, s, x0, x1, reach=0.08):
        """The lowest z a hood vertex reaches over x0..x1 (signed) near station s, opening or shut."""
        q = self.sweep
        sel = (np.abs(q[:, 0] - s) < reach) & (q[:, 1] >= min(x0, x1) - 0.01) & (q[:, 1] <= max(x0, x1) + 0.01)
        return float(q[sel, 2].min()) if sel.any() else math.inf

    def sill_x(self, s, z, side):
        """|x| of the cut skin under the glass seam at height z on one side, from the centreline out."""
        found = hit(self.sill, P(s, 0.0, z), Vector((side, 0.0, 0.0)), 1.0)
        return abs(found[0].x) if found else math.inf

    def sill_limit(self, s, z0, z1):
        """Narrowest skin clearance across a shroud wall's full height, including a flange between its corners."""
        lo, hi = sorted((z0, z1))
        points = [q for obj in self.sill_objects for q in self.internals.section_points(obj, s)]
        widths = [abs(x) for x, z in points if lo <= z <= hi]
        widths += [self.sill_x(s, z, side) for z in (lo, hi) for side in (1, -1)]
        return min(widths)

    def hood_x(self, s, z, side):
        """|x| of the shut hood (frame, glass, or the inner frame hung from it) at height z on one side, from the
        centreline out."""
        out = math.inf
        for tree in (self.hood, getattr(self, "hood_extra", None)):
            found = hit(tree, P(s, 0.0, z), Vector((side, 0.0, 0.0)), 1.0) if tree else None
            if found:
                out = min(out, abs(found[0].x))
        return out


# --- the interior --------------------------------------------------------------------------------------------------

GROUPS = ("front", "console", "tub")


# Console plates, front to back: (title, s0, s1, controls); a control is (kind, ds, dx, legend), ds aft of the plate's
# centre, dx outboard of the console's centre line. The left console carries the throttle with the engine, fuel and
# radio; the right the stick with the sensors, electrics, lights and oxygen (owner, 2026-10-22).
CONSOLES = {
    1: [("ENGINE", 4.065, 4.205, [("guarded", -0.030, -0.030, "ENG MASTER"), ("button", -0.030, 0.034, "START"),
                                  ("toggle", 0.035, -0.030, "IGN"), ("button", 0.035, 0.034, "AB")]),
        ("FUEL", 4.215, 4.355, [("button", -0.032, -0.035, "BST"), ("button", -0.032, 0.0, "XFD"),
                                ("lamp_green", -0.032, 0.035, "FLOW"), ("button", 0.032, -0.028, "DUMP"),
                                ("button", 0.032, 0.030, "TANK")]),
        ("COMM", 4.365, 4.585, [("knob", -0.068, -0.035, "VOL"), ("knob", -0.068, 0.035, "CHAN"),
                                ("window", -0.012, 0.0, "251.00"), ("key", 0.045, -0.027, "1"), ("key", 0.045, -0.009, "2"),
                                ("key", 0.045, 0.009, "3"), ("key", 0.045, 0.027, "4")]),
        ("IFF", 4.595, 4.775, [("button", -0.040, -0.030, "MODE"), ("key", -0.040, 0.030, "CODE"),
                               ("button", 0.035, 0.0, "IDENT")])],
    -1: [("SENSORS", 4.065, 4.225, [("knob", -0.032, -0.024, "RADAR"), ("button", -0.032, 0.040, "IR"),
                                    ("button", 0.034, -0.034, "ECM"), ("button", 0.034, 0.030, "EMCON")]),
         ("ELEC", 4.235, 4.375, [("toggle", -0.030, -0.035, "BATT"), ("toggle", -0.030, 0.0, "GEN"),
                                 ("button", -0.030, 0.035, "APU"), ("guarded", 0.034, 0.0, "EMER PWR")]),
         ("LIGHTS", 4.385, 4.585, [("knob", -0.048, -0.035, "CSL"), ("knob", -0.048, 0.035, "INST"),
                                   ("button", 0.010, -0.035, "POS"), ("button", 0.010, 0.035, "FORM"),
                                   ("button", 0.060, 0.0, "BCN")]),
         ("OXYGEN", 4.595, 4.775, [("knob", -0.040, 0.0, "REG"), ("blinker", 0.035, -0.030, "FLOW"),
                                   ("button", 0.035, 0.030, "100%")])],
}
LEGEND_AFT = {"toggle": 0.021, "guarded": 0.031, "knob": 0.019, "knob_large": 0.026, "key": 0.011, "blinker": 0.016,
              "button": 0.016, "lamp_green": 0.016}
CONSOLE_LIP = (0.016, 0.020)  # the raised outboard lip: width and height over the top


def console_x(space, side, s):
    """(inner, centre, outer) |x| of the console top at s: the inner edge clear of the seat, the outer at the lip."""
    inner = LAYOUT["console"]["inner"]
    outer = space.wall_x(s, LAYOUT["console"]["top_z"]) - 0.002 - CONSOLE_LIP[0]
    return inner, (inner + outer) / 2, outer


def console_frame(side):
    """A console top's placement: local X to the pilot's right, Y forward, Z up, origin at the console's front inner
    corner."""
    c = LAYOUT["console"]
    return frame(P(c["s0"], side * c["inner"], c["top_z"]), -Y, Z)


def consoles(g, uv, kit, atlas, space):
    """Each side console: a top face with the throttle or stick plate and its system plates set in, a raised lip
    along the wall, the inner wall down to the floor facing the seat."""
    c = LAYOUT["console"]
    top, floor = c["top_z"], LAYOUT["floor_z"]
    faces = []
    for side in (1, -1):
        stations = bi.spaced(c["s0"], c["s1"], 5)
        m = console_frame(side)
        inv = m.inverted()
        local = lambda s, x: tuple((inv @ P(s, x, top)).xy)
        outer = [local(s, side * console_x(space, side, s)[2]) for s in stations]
        inner = [local(s, side * c["inner"]) for s in stations]
        outline = inner + outer[::-1]
        if _area(outline) < 0:
            outline = outline[::-1]
        face = Face("console%d" % side, m, outline, atlas.chart("console", "console_top%d" % side))
        for title, s0, s1, controls in CONSOLES[side]:
            sub_panel(g, uv, kit, atlas, space, face, side, title, s0, s1, controls)
        if side > 0:
            throttle_quadrant(g, uv, kit, atlas, space, face)
        else:
            stick_base(g, uv, kit, atlas, space, face)
        faces.append(face.close(g, "console"))
        # the lip: a rounded rail along the wall, its top rolled
        w, h = CONSOLE_LIP
        rings = []
        for s in stations:
            x = console_x(space, side, s)[2]
            sec = [(x, top), (x, top + h - 0.004), (x + 0.004, top + h), (x + w - 0.002, top + h), (x + w, top + h - 0.002),
                   (x + w, top - 0.002)]
            rings.append([P(s, side * q, z) for q, z in sec])
        g.put(grid_sheet(uv, rings, atlas.chart("console", "lip%d" % side)),
              None, "console")
        # the inner wall, facing the seat, and the front, facing forward
        wall = [[P(s, side * c["inner"], z) for s in stations] for z in (top, (top + floor) / 2, floor)]
        g.put(grid_sheet(uv, wall, atlas.chart("tub", "console_wall%d" % side)), None, "console")
        s0 = c["s0"]
        front = [P(s0, side * c["inner"], floor), P(s0, side * (space.wall_x(s0, floor + 0.01) - 0.002), floor),
                 P(s0, side * (space.wall_x(s0, top) - 0.002), top + h), P(s0, side * c["inner"], top)]
        g.put(sheet(uv, front, "structure"), None, "console")
    return faces


def _area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def sub_panel(g, uv, kit, atlas, space, face, side, title, s0, s1, controls):
    """A plate set into the console top, fasteners at its corners, its controls and legends."""
    _, cx, _ = console_x(space, side, (s0 + s1) / 2)
    inner, _, outer = console_x(space, side, s0)
    hw = (outer - inner) / 2 - 0.007
    sc = (s0 + s1) / 2
    inv = face.m.inverted()
    a = inv @ P(s1, side * (cx - hw), LAYOUT["console"]["top_z"])
    b = inv @ P(s0, side * (cx + hw), LAYOUT["console"]["top_z"])
    top = face.pocket(g, kit, uv, min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y), title, 4, "console")
    for kind, ds, dx, legend in controls or ():
        q = inv @ P(sc + ds, side * (cx + dx), LAYOUT["console"]["top_z"])
        x, y = q.x, q.y
        if kind == "window":  # a recessed readout
            lab = atlas.label(legend, ink="lens_red", paper="recess", cap_mm=4.0, size_mm=(32, 10))
            g.put(stack(uv, [ring_rect(0.018, 0.0075, 0.0), ring_rect(0.018, 0.0075, 0.002)], "bezel", top_uv="bezel",
                        bottom_hidden=True), top(x, y), "console")
            g.put(kit.placard(lab), top(x, y, 0.002), "console")
            continue
        if kind in ("toggle", "guarded"):
            for piece in kit.guard() if kind == "guarded" else kit.toggle():
                g.put(piece, top(x, y), "console")
        elif kind == "knob":
            g.put(kit.knob(), top(x, y), "console")
        elif kind == "knob_large":
            for piece in kit.selector():
                g.put(piece, top(x, y), "console")
        elif kind == "key":
            g.put(kit.key(legend), top(x, y), "console")
            continue
        elif kind == "blinker":
            g.put(kit.indicator("lens_green", body="keyside"), top(x, y), "console")
        elif kind == "lamp_green":
            g.put(kit.indicator("lens_green", legend), top(x, y), "console")
            continue
        elif kind == "button":
            g.put(kit.indicator("lens_clear", legend[:5]), top(x, y), "console")
            continue
        lab = atlas.label(legend, cap_mm=3.0, box=kind in ("toggle", "guarded"))
        g.put(kit.placard(lab), top(x, y - LEGEND_AFT[kind] - lab.h_m / 2 + 0.004), "console")


def throttle_quadrant(g, uv, kit, atlas, space, face):
    """The plate the stock throttle stands over, its slot through the grip's travel, the detents and the friction
    knob."""
    st = STOCK["throttle"]
    c = LAYOUT["console"]
    s0, s1 = c["s0"] + 0.008, 4.055
    inner, cx, outer = console_x(space, 1, (s0 + s1) / 2)
    travel = (st[0][5] - STOCK["throttle_pivot"][2]) * math.sin(math.radians(STOCK["throttle_deg"]))
    xs = (st[0][2] + st[0][3]) / 2
    a, b = STOCK["throttle_pivot"][0] - travel - 0.012, STOCK["throttle_pivot"][0] + travel + 0.012
    inv = face.m.inverted()
    L = lambda s, x: inv @ P(s, x, c["top_z"])
    p0, p1 = L(s1, inner + 0.006), L(s0, outer - 0.006)
    slot = [L(b, xs - 0.012), L(a, xs - 0.012), L(a, xs + 0.012), L(b, xs + 0.012)]
    slot = [(v.x, v.y) for v in slot]
    if _area(slot) < 0:
        slot = slot[::-1]
    top = face.pocket(g, kit, uv, min(p0.x, p1.x), min(p0.y, p1.y), max(p0.x, p1.x), max(p0.y, p1.y), "THROTTLE", 4,
                      "console", floor_holes=[slot])
    g.put(walls(slot, -PLATE["depth"], -PLATE["depth"] - 0.025, "bezel_dark", uv), face.m, "console")
    for ds, name in ((a + 0.010, "AB"), (b - 0.022, "IDLE")):
        q = L(ds, xs + 0.020)
        g.put(stack(uv, [ring_rect(0.004, 0.009, 0.0), ring_rect(0.004, 0.009, 0.004)], "metal", bottom_hidden=True),
              top(q.x, q.y), "console")
        lab = atlas.label(name, cap_mm=3.0)
        r = L(ds, xs + 0.040)
        g.put(kit.placard(lab), top(r.x, r.y), "console")
    q = L(b + 0.020, inner + 0.032)
    g.put(kit.knob(), top(q.x, q.y), "console")
    lab = atlas.label("FRICT", cap_mm=3.0)
    g.put(kit.placard(lab), top(q.x, q.y - LEGEND_AFT["knob"] - lab.h_m / 2 + 0.004), "console")


def stick_base(g, uv, kit, atlas, space, face):
    """The plate the stock side stick stands on, its boot ring, and the trim knob ahead of it."""
    c = LAYOUT["console"]
    s0, s1 = c["s0"] + 0.008, 4.055
    inner, cx, outer = console_x(space, -1, (s0 + s1) / 2)
    inv = face.m.inverted()
    L = lambda s, x: inv @ P(s, x, c["top_z"])
    p0, p1 = L(s1, -(inner + 0.006)), L(s0, -(outer - 0.006))
    top = face.pocket(g, kit, uv, min(p0.x, p1.x), min(p0.y, p1.y), max(p0.x, p1.x), max(p0.y, p1.y), "FLT CTRL", 4,
                      "console")
    q = L(STOCK["stick_pivot"][0], STOCK["stick_pivot"][1])
    g.put(stack(uv, [ring_circle(0.034, 0.0, 16), ring_circle(0.032, 0.006, 16), ring_circle(0.026, 0.008, 16)],
                "bezel", top_uv="bezel_dark", bottom_hidden=True), top(q.x, q.y), "console")
    q = L(s0 + 0.034, -(inner + 0.030))
    g.put(kit.knob(), top(q.x, q.y), "console")
    lab = atlas.label("TRIM", cap_mm=3.0)
    g.put(kit.placard(lab), top(q.x, q.y - LEGEND_AFT["knob"] - lab.h_m / 2 + 0.004), "console")


def ledge_drop(s):
    """How far the sill ledge's top stands under the glass seam: LEDGE_DROP beside the pilot (Cockpit rule 27's sill),
    8 mm ahead of the console, up under the hood's longeron, so the eye sees no skin between the two."""
    t = min(max((s - 4.10) / 0.15, 0.0), 1.0)
    return 0.008 + (LEDGE_DROP - 0.008) * t


def ledge_rows(space, side, columns):
    """The sill ledge along one side: (s, |x| in, |x| out, top z) per station, from the lining's top out to just inside
    the shut hood, LEDGE_DROP under the glass seam; the hood's longeron comes down over the gap, P5's fixed-sill flange
    stands behind it. The ledge stays under every place the hood's vertices pass through as it opens, then is pulled in
    and down a segment at a time until the swept hood's faces and the skin's sill flange clear it."""
    rows = []
    for s in columns:
        sx, sz = space.seam(s)
        drop = ledge_drop(s)
        top = sz - drop
        for _ in range(2):
            x_in = space.wall_x(s, top - 0.030)
            zs = bi.spaced(top - 0.035, top + 0.005, 4)
            x_out = min(sx - 0.004, min(space.hood_x(s, z, side) for z in zs) - 0.008,
                        min(space.sill_x(s, z, side) for z in zs) - 0.004)
            x_out = max(x_out, x_in + 0.010)
            top = min(sz - drop, space.sweep_floor(s, side * x_in, side * x_out) - 0.008)
        rows.append([s, x_in, x_out, top])
    for _ in range(40):
        hits = [i for i in range(len(rows) - 1) if space.swept.overlap(ledge_tree(rows[i:i + 2], side))
                or space.sill.overlap(ledge_tree(rows[i:i + 2], side))]
        if not hits:
            break
        for i in set(hits) | {i + 1 for i in hits}:
            rows[i][2] = max(rows[i][1] + 0.010, rows[i][2] - 0.003)
            rows[i][3] -= 0.004
    else:
        raise ValueError("cockpit: the sill ledge cannot clear the opening hood and the skin at s %.2f" % rows[hits[0]][0])
    return [tuple(r) for r in rows]


def ledge_tree(rows, side):
    """A BVH of the actual ledge between two rows, including the faces the clearance solver must keep clear."""
    verts, polys = [], []
    for s, x_in, x_out, top in rows:
        verts += [P(s, side * q, z) for q, z in ((x_in, top - 0.030), (x_in, top),
                                                 (x_out, top), (x_out, top - 0.030))]
    polys = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]
    return BVHTree.FromPolygons(verts, polys)


def tub(g, uv, kit, atlas, space):
    """Lining sheets on both walls up to the sill ledge, the ledge itself, frame ribs, wiring looms, the floor, the
    footwell's front wall and kick panels, the rear bulkhead, the rudder pedals."""
    floor = LAYOUT["floor_z"]
    s_front, s_back = LAYOUT["footwell_s"], LAYOUT["bulkhead"][0]
    columns = bi.spaced(LEDGE_S0, s_back, 17)
    for side in (1, -1):
        rows = ledge_rows(space, side, columns)
        rings = [[P(s, side * q, z) for q, z in ((x_in, top - 0.030), (x_in, top), (x_out, top), (x_out, top - 0.030))]
                 for s, x_in, x_out, top in rows]
        g.put(loft_piece(uv, rings, atlas.chart("sill", "ledge%d" % side), along=Y, caps="structure"), None, "tub")
        # the lining, in cells from the floor to the ledge: charted where it is seen, ahead of the console and over it;
        # behind the console, on a strip
        k = next(i for i, r in enumerate(rows) if r[0] >= LAYOUT["console"]["s0"])
        cz = LAYOUT["console"]["top_z"]
        wall = lambda cols, z0, name, spec: g.put(grid_sheet(uv, [
            [P(s, side * space.wall_x(s, z0 + (top - 0.030 - z0) * f), z0 + (top - 0.030 - z0) * f) for s, _, _, top in cols]
            for f in (0.0, 0.25, 0.5, 0.75, 1.0)], spec), None, "tub")
        wall(rows[:k + 1], floor, "fwd", atlas.chart("tub", "lining_fwd%d" % side))
        wall(rows[k:], cz - 0.004, "aft", atlas.chart("tub", "lining_aft%d" % side))
        for rs in LAYOUT["ribs"]:
            top = float(np.interp(rs, [r[0] for r in rows], [r[3] for r in rows])) - 0.032
            # over a console the rib starts above the throttle and the stick
            z0 = 0.47 if LAYOUT["console"]["s0"] < rs < LAYOUT["console"]["s1"] else floor
            pts = [(space.wall_x(rs, z), z) for z in bi.spaced(z0, top, 4)]
            rings = [[P(rs + ds, side * x, z) for x, z in pts] + [P(rs + ds, side * (x - 0.026), z) for x, z in pts[::-1]]
                     for ds in (-0.0165, 0.0165)]
            g.put(loft_piece(uv, rings, "structure", along=Z), None, "tub")
        # two wiring looms along the lining under the ledge, in the footwell and aft of the throttle and stick
        for s0, s1 in ((s_front + 0.05, 3.70),):  # in the footwell; aft, the consoles cover the wall
            for drop in (0.020, 0.045):
                pts = []
                for s in bi.spaced(s0, s1, 4):
                    top = float(np.interp(s, [r[0] for r in rows], [r[3] for r in rows])) - 0.030
                    z = top - drop
                    pts.append(P(s, side * (space.wall_x(s, z) - 0.014), z))
                g.put(tube(uv, pts, 0.011, 6, "knurl"), None, "tub")
        breakers(g, uv, kit, atlas, space, side)
        # a data plate on the left wall over the breakers, the seat's warning on the right, on the lining
        s, z = 3.36, 0.315
        text, ink, paper = (("F-204 ICARUS II\nSERIAL 0001  BLOCK 2\nOXY / FUEL / HYD: SEE T.O. 1F-204-1", "ink", "plate")
                            if side > 0 else ("WARNING\nEJECTION SEAT\nKEEP CLEAR OF HANDLES", "ink_dark", "hatch_light"))
        lab = atlas.label(text, ink=ink, paper=paper, cap_mm=3.2, box=True)
        g.put(kit.placard(lab, lift=0.0015), frame(P(s, side * (space.wall_x(s, z) - 0.001), z), Z, Vector((-side, 0.0, 0.0))),
              "tub")
    # the floor in tread cells, the footwell wall, kick panels
    xs = bi.spaced(-1, 1, 6)
    grid = []
    for s in bi.spaced(s_front, s_back, 13):
        w = space.wall_x(s, floor + 0.005)
        grid.append([P(s, f * w, floor) for f in xs])
    # charted ahead of the seat, where it is seen; under the seat on a strip
    g.put(grid_sheet(uv, grid[:6], atlas.chart("floor", "floor")), None, "tub")
    g.put(grid_sheet(uv, grid[5:], "structure"), None, "tub")
    zs = bi.spaced(floor, 0.45, 5)
    wall = [[P(s_front, f * space.wall_x(s_front, z), z) for f in xs] for z in zs]
    g.put(grid_sheet(uv, wall, atlas.chart("tub", "footwell")), None, "tub")
    top_z, top_s = 0.186, 3.66  # under the wing panels
    for side in (1, -1):
        foot = [P(3.50, side * q, floor) for q in bi.spaced(0.20, space.wall_x(3.50, floor) - 0.003, 3)]
        head = [P(top_s, side * q, top_z) for q in bi.spaced(0.26, space.wall_x(top_s, top_z) - 0.003, 3)]
        g.put(grid_sheet(uv, [foot, [a.lerp(b, 0.5) for a, b in zip(foot, head)], head], atlas.chart("tub", "kick%d" % side)), None, "tub")
    # the rear bulkhead behind the seat, up to the ledge line, and the deck aft of it under the hood's tail, closing
    # the cockpit back to the aft bow at the seam line
    s0, s1 = LAYOUT["bulkhead"]
    sx, sz = space.seam(s0)
    fs = bi.spaced(-1, 1, 7)
    rows = []
    for t in bi.spaced(0.0, 1.0, 5):
        rows.append([P(s0, f * (space.wall_x(s0, floor) * (1 - t) + (sx - 0.020) * t),
                       floor + (sz - 0.025 + 0.05 * (1 - f * f) - floor) * t) for f in fs])
    g.put(grid_sheet(uv, rows, atlas.chart("back", "bulkhead")), None, "tub")
    deck = []
    for s in bi.spaced(s0, 5.03, 3):
        sx, sz = space.seam(s)
        deck.append([P(s, f * (sx - 0.020), sz - 0.025 + 0.05 * (1 - f * f)) for f in fs])
    g.put(grid_sheet(uv, deck, atlas.chart("tub", "aft_deck")), None, "tub")
    pedals(g, uv, kit)


def breakers(g, uv, kit, atlas, space, side):
    """A circuit-breaker panel low on each footwell wall: a plate, four rows of six breakers and their legends."""
    s0, s1, z0, z1 = 3.16, 3.54, 0.03, 0.25
    sc, zc = (s0 + s1) / 2, (z0 + z1) / 2
    inward = Vector((-side, 0.0, 0.0))
    at = lambda s, z, lift=0.0: P(s, side * (space.wall_x(s, z) - 0.004 - lift), z)
    corners = [at(s, z) for s in (s0, s1) for z in (z0, z1)]
    outer = [corners[0], corners[1], corners[3], corners[2]]
    g.put(loft_piece(uv, [outer, [p + inward * 0.004 for p in outer]], atlas.chart("console", "breakers%d" % side),
                     along=Y, caps="structure"), None, "tub")
    for r, title in enumerate(("PRI", "SEC", "ARM")):
        z = z1 - 0.030 - 0.048 * r
        for i in range(3):
            s = s0 + 0.080 + 0.100 * i
            g.put(kit.breaker(), frame(at(s, z, 0.004), Z, inward), "tub")
        g.put(kit.placard(atlas.label(title, cap_mm=3.5)), frame(at(s0 + 0.014, z, 0.004), Z, inward), "tub")


def pedals(g, uv, kit):
    """Hanging rudder pedals: raked plates with toe straps, arms up to a cross tube under the glare shield."""
    ps, px = LAYOUT["pedals"]["s"], LAYOUT["pedals"]["x"]
    floor = LAYOUT["floor_z"]
    z0, z1, w, t, rake = floor + 0.05, floor + 0.23, 0.08, 0.012, 14.0
    bar_s, bar_z = LAYOUT["pedals"]["bar"]
    tan = math.tan(math.radians(rake))
    face = lambda z: ps + ((z0 + z1) / 2 - z) * tan
    g.put(tube(uv, [P(bar_s, -0.26, bar_z), P(bar_s, 0.26, bar_z)], 0.014, 8, "metal"), None, "tub")
    for side in (1, -1):
        c = side * px
        v = [P(face((z0, z1)[k]) - (t if i == 0 else 0.0), c + (-w / 2, w / 2)[j], (z0, z1)[k])
             for i in (0, 1) for j in (0, 1) for k in (0, 1)]
        faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
        g.put(solid(uv, v, faces, lambda i: "structure"), None, "tub")
        sz0, sz1 = z0 + 0.105, z0 + 0.130
        fs = face((sz0 + sz1) / 2)
        for dx in (-w / 2, w / 2 - 0.006):
            g.put(block(uv, fs - 0.004, fs + 0.030, c + dx, c + dx + 0.006, sz0, sz1, lambda i: "knurl", False), None,
                  "tub")
        g.put(block(uv, fs + 0.030, fs + 0.036, c - w / 2, c + w / 2, sz0, sz1, lambda i: "knurl", False), None, "tub")
        g.put(tube(uv, [P(face(z1 - 0.015) - t - 0.008, c, z1 - 0.015), P(bar_s, c, bar_z)], 0.009, 4, "metal"), None,
              "tub")


# --- inner frames --------------------------------------------------------------------------------------------------

class Glass:
    """The inner panes of the hood and windscreen, for placing frame members a set depth inside them."""

    def __init__(self, space):
        self.space = space
        O = bpy.data.objects
        self.tree = bvh([O[canopy.GLASS_INNER], O[canopy.WINDSCREEN_INNER]])

    def at(self, plane, psi, depth):
        """The point depth inside the inner glass, along the glass's own normal, where the ray at angle psi from the
        crown (+ toward the left) in the plane frame `plane` (canopy.station or canopy.joint) meets it. The normal in
        the plane alone would put members closer to glass that runs across the plane, as the aft hood does."""
        origin, d = canopy.ray(plane, psi)
        point, n = must(hit(self.tree, origin, d), "inner glass at %.2f rad" % psi)
        out = point + n * depth  # hit() turns the normal back toward the origin: into the cockpit
        for _ in range(4):  # where the glass bends in under the hood's lip, a neighbouring face comes nearer
            near = self.tree.find_nearest(out)[3]
            if near >= depth - 1e-5:
                break
            out += n * (depth - near)
        return out

    def seam(self, plane, side):
        return canopy.seam_psi(self.space.outer_glass, self.space.skin, plane, side)


def hood_planes():
    """The hood's joint (point a, axis u), as canopy.build sets the hinge, and its bows' planes: front (two joint
    planes), middle and aft (station planes)."""
    hinge = bpy.data.objects["canopy"]
    a, u = hinge.matrix_world.translation.copy(), hinge.matrix_world.col[0].xyz.normalized()
    return a, u


def member(glass, planes, psis, outer_d, inner_ds):
    """A frame member: a closed band through rows of planes; each row's points at the psis, outer_d inside the glass
    and inner_ds[row] deeper on the cockpit side, as the two grids of a slab."""
    outer, inner = [], []
    for plane, inner_d in zip(planes, inner_ds):
        outer.append([glass.at(plane, psi, outer_d) for psi in psis])
        inner.append([glass.at(plane, psi, inner_d) for psi in psis])
    return outer, inner


def slab_piece(uv, outer, inner, spec, along=None, chart=None):
    """A closed slab between two grids of points (rows by columns); with a chart, its cockpit-side face (the inner
    grid) unrolls onto it and the rest takes spec."""
    rows, cols = len(outer), len(outer[0])
    o = lambda i, j: i * cols + j
    n = rows * cols
    faces = []
    for i in range(rows - 1):
        for j in range(cols - 1):
            faces.append((o(i, j), o(i + 1, j), o(i + 1, j + 1), o(i, j + 1)))
            faces.append((n + o(i, j + 1), n + o(i + 1, j + 1), n + o(i + 1, j), n + o(i, j)))
    for j in range(cols - 1):
        faces.append((o(0, j), o(0, j + 1), n + o(0, j + 1), n + o(0, j)))
        faces.append((n + o(rows - 1, j), n + o(rows - 1, j + 1), o(rows - 1, j + 1), o(rows - 1, j)))
    for i in range(rows - 1):
        faces.append((o(i, 0), n + o(i, 0), n + o(i + 1, 0), o(i + 1, 0)))
        faces.append((o(i + 1, cols - 1), n + o(i + 1, cols - 1), n + o(i, cols - 1), o(i, cols - 1)))
    verts = [p for row in outer for p in row] + [p for row in inner for p in row]
    if chart is None:
        return solid(uv, verts, faces, spec, along=along)
    flat = grid_chart(inner, chart)
    piece = Piece()
    for f in faces:
        pts = [verts[q] for q in f]
        if all(q >= n for q in f):
            piece.add(pts, [tuple(range(len(f)))], [[flat[q - n] for q in f]])
        else:
            piece.add(pts, [tuple(range(len(f)))], [uv(spec, pts, along=along)])
    return piece


def hood_frame_inner(uv, kit, glass, proxy=False, atlas=None):
    """The hood's inner frame (Cockpit rule 32): a shell of three bows and two longerons over the hood frame's own
    members, the glass_inset in from the inner glass, then fasteners and the canopy lock handle. proxy: the shell
    alone, coarser, for the exterior stand-in."""
    g = Gather("canopy_frame_proxy" if proxy else "canopy_frame_inner")
    a, u = hood_planes()
    d0, d1 = FRAME["glass_inset"], FRAME["glass_inset"] + FRAME["depth"]
    cols = 9 if proxy else 33  # 32 segments across each bow
    # each bow a ridged band: its middle row stands deeper than its edges
    # the front bow starts half a millimetre behind the joint and runs wide aft, so the outer frame shows past neither edge
    bows = [(canopy.joint(a, u, 0.0005), canopy.joint(a, u, 0.033), canopy.joint(a, u, 0.066)),
            (canopy.station(4.05), canopy.station(4.10), canopy.station(4.15)),
            (canopy.station(5.025), canopy.station(5.056), canopy.station(5.088))]
    for planes in bows:
        planes = planes[::2] if proxy else planes
        depths = (d1, d1) if proxy else (d1, d1 + 0.010, d1)
        # the bow's ends stop at the highest seam across its planes, clear of the skin the glass runs on under
        left, right = min(glass.seam(f, 1) for f in planes), max(glass.seam(f, -1) for f in planes)
        r = canopy.glass_at(glass.tree, planes[0], left)[2]
        psis = bi.spaced(left - SEAT_CLEAR / r, right + SEAT_CLEAR / r, cols)
        outer, inner = member(glass, planes, psis, d0, depths)
        g.put(slab_piece(uv, outer, inner, "structure", chart=atlas and atlas.chart("frame", "bow")), None, "frame")
    # longerons: from the front bow to the aft bow along each sill, covering the glass from the seam up, deepest a
    # third of the way up where the canopy seats on the sill
    stations = bi.spaced(3.0, 5.06, 6 if proxy else 16)
    for side in (1, -1):
        rows_o, rows_i = [], []
        for s in stations:
            f = canopy.station(s)
            seam = glass.seam(f, side)
            r = canopy.glass_at(glass.tree, f, seam)[2]
            if proxy:
                psis, depths = [seam - side * SEAT_CLEAR / r, seam - side * FRAME["seam_cover"] / r], (d1 + 0.006, d1 + 0.006)
            else:  # up from the seam, where the glass turns in under the hood's lip
                psis = [seam - side * SEAT_CLEAR / r, seam - side * 0.022 / r, seam - side * FRAME["seam_cover"] / r]
                depths = (d1 + 0.006, d1 + 0.014, d1)
            rows_o.append([glass.at(f, q, d0) for q in psis])
            rows_i.append([glass.at(f, q, d) for q, d in zip(psis, depths)])
        g.put(slab_piece(uv, rows_o, rows_i, "structure", chart=atlas and atlas.chart("frame", "longeron")), None, "frame")
    if proxy:
        return g
    # fasteners along the bows and longerons, faces toward the cockpit
    for _, mid, _ in bows:
        left, right = glass.seam(mid, 1), glass.seam(mid, -1)
        for psi in bi.spaced(left - 0.10, right + 0.10, 5):
            at0, at1 = glass.at(mid, psi, d1 + 0.010), glass.at(mid, psi, d0)
            g.put(kit.fastener(), frame(at0, mid[2], at0 - at1), "hardware")
    for side in (1, -1):
        for s in bi.spaced(3.3, 4.85, 6):
            f = canopy.station(s)
            seam = glass.seam(f, side)
            r = canopy.glass_at(glass.tree, f, seam)[2]
            psi = seam - side * 0.035 / r
            at0, at1 = glass.at(f, psi, d1 + 0.006), glass.at(f, psi, d0)
            g.put(kit.fastener(), frame(at0, Y, at0 - at1), "hardware")
    # the canopy lock handle on the right longeron: a boss, a lever along the sill, a knob
    f = canopy.station(3.62)
    seam = glass.seam(f, -1)
    r = canopy.glass_at(glass.tree, f, seam)[2]
    psi = seam + 0.040 / r
    boss = glass.at(f, psi, d1 + 0.006)
    inward = (glass.at(f, psi, d1 + 0.030) - boss).normalized()
    g.put(tube(uv, [boss, boss + inward * 0.012], 0.010, 10, "metal"), None, "hardware")
    lever = [glass.at(canopy.station(s), psi, d1 + 0.020) for s in (3.62, 3.70, 3.78)]
    g.put(tube(uv, lever, 0.005, 8, "metal"), None, "hardware")
    g.put(tube(uv, [lever[-1], lever[-1] + inward * 0.020], 0.008, 10, "guard"), None, "hardware")
    return g


def windscreen_frame_inner(uv, kit, glass, atlas=None):
    """The windscreen's inner frame: its arch just ahead of the joint and its two posts, over the outer frame's
    members, with fasteners."""
    g = Gather("windscreen_frame_inner")
    a, u = hood_planes()
    d0, d1 = FRAME["glass_inset"], FRAME["glass_inset"] + FRAME["depth"]
    f0, fm, f1 = canopy.joint(a, u, -0.042), canopy.joint(a, u, -0.022), canopy.joint(a, u, -0.002)
    left, right = glass.seam(f0, 1), glass.seam(f0, -1)
    r = canopy.glass_at(glass.tree, f0, left)[2]
    outer, inner = member(glass, (f0, fm, f1), bi.spaced(left - 0.004 / r, right + 0.004 / r, 33), d0,
                          (d1, d1 + 0.010, d1))
    g.put(slab_piece(uv, outer, inner, "structure", chart=atlas.chart("frame", "arch")), None, "frame")
    psi = math.radians(40)
    under_arch = glass.at(canopy.joint(a, u, -0.02), psi, d0).y + bi.S0
    start = 2.45
    for side in (1, -1):
        rows_o, rows_i = [], []
        for s in bi.spaced(under_arch, start, 6):
            f = canopy.station(s)
            r = canopy.glass_at(glass.tree, f, side * psi)[2]
            psis = [side * psi - 0.020 / r, side * psi, side * psi + 0.020 / r]
            rows_o.append([glass.at(f, q, d0) for q in psis])
            rows_i.append([glass.at(f, q, d) for q, d in zip(psis, (d1, d1 + 0.008, d1))])
        g.put(slab_piece(uv, rows_o, rows_i, "structure", chart=atlas.chart("frame", "post")), None, "frame")
        # the base rail along the windscreen's foot, over the outer frame's
        rows_o, rows_i = [], []
        for s in bi.spaced(2.40, 2.93, 6):
            f = canopy.station(s)
            seam = glass.seam(f, side)
            r = canopy.glass_at(glass.tree, f, seam)[2]
            psis = [seam, seam - side * 0.032 / r]
            rows_o.append([glass.at(f, q, d0) for q in psis])
            rows_i.append([glass.at(f, q, d1) for q in psis])
        g.put(slab_piece(uv, rows_o, rows_i, "structure", chart=atlas.chart("frame", "rail")), None, "frame")
        for s in bi.spaced(2.6, under_arch - 0.06, 2):
            f = canopy.station(s)
            at0, at1 = glass.at(f, side * psi, d1), glass.at(f, side * psi, d0)
            g.put(kit.fastener(), frame(at0, Y, at0 - at1), "hardware")
    for p in bi.spaced(left - 0.08, right + 0.08, 5):
        at0, at1 = glass.at(fm, p, d1 + 0.010), glass.at(fm, p, d0)
        g.put(kit.fastener(), frame(at0, fm[2], at0 - at1), "hardware")
    return g


# --- proxies, screens, lamps ---------------------------------------------------------------------------------------

def cockpit_proxy(uv, atlas, space):
    """The interior's exterior stand-in on Matte_black: the front office, the consoles, the walls, floor and
    bulkhead, coarse."""
    import cockpit_front as front

    g = Gather("cockpit_proxy")
    floor = LAYOUT["floor_z"]
    fr = front.FRONT
    y0, y1 = front.face_y(fr["stem_bottom_z"]), front.face_top_y()
    g.put(stack(uv, [ring_rect(fr["half_width"], (y1 - y0) / 2, -0.03), ring_rect(fr["half_width"], (y1 - y0) / 2, 0.0)],
                "structure"), front.face_frame() @ Matrix.Translation((0.0, (y0 + y1) / 2, 0.0)), "proxy")
    c = LAYOUT["console"]
    columns = bi.spaced(LEDGE_S0, LAYOUT["bulkhead"][0], 17)
    for side in (1, -1):
        rings = []
        for s in bi.spaced(c["s0"], c["s1"], 5):
            inner, _, outer = console_x(space, side, s)
            rings.append([P(s, side * q, z) for q, z in ((inner, floor), (outer, floor), (outer, c["top_z"]),
                                                         (inner, c["top_z"]))])
        g.put(loft_piece(uv, rings, "structure"), None, "proxy")
        rows = ledge_rows(space, side, columns)
        grid = [[P(s, side * space.wall_x(s, floor + (top - floor) * f), floor + (top - floor) * f)
                 for s, _, _, top in rows] for f in bi.spaced(0.0, 1.0, 6)]
        grid.append([P(s, side * x_out, top) for s, _, x_out, top in rows])
        g.put(grid_sheet(uv, grid, "structure"), None, "proxy")
    grid = [[P(s, f * space.wall_x(s, floor), floor) for f in bi.spaced(-1, 1, 7)] for s in columns]
    g.put(grid_sheet(uv, grid, "structure"), None, "proxy")
    s0 = LAYOUT["bulkhead"][0]
    sx, sz = space.seam(s0)
    ring = [(f * space.wall_x(s0, floor), floor) for f in bi.spaced(-1, 1, 7)] + \
           [(f * (sx - 0.020), sz - 0.025 + 0.05 * (1 - f * f)) for f in bi.spaced(1, -1, 9)]
    g.put(loft_piece(uv, [[P(s, x, z) for x, z in ring] for s in (s0, s0 + 0.04)], "structure"), None, "proxy")
    deck = []
    for s in bi.spaced(s0, 5.03, 3):
        sx, sz = space.seam(s)
        deck.append([P(s, f * (sx - 0.020), sz - 0.025 + 0.05 * (1 - f * f)) for f in bi.spaced(-1, 1, 7)])
    g.put(grid_sheet(uv, deck, "structure"), None, "proxy")
    front.shroud(g, atlas, uv, space, y1, "proxy", proxy=True)
    # the seat's silhouette is the stock seat itself, drawn in every view
    return g


def tac_screen(screens):
    """The display quads on stock tacScreenDisplay, each UV-mapped to its rect of the TacScreenRenderer."""
    g = Gather(TAC_SCREEN)
    for corners, (u0, v0, u1, v1) in screens:
        piece = Piece(sheet=True)
        piece.add(corners, [(0, 1, 2, 3)], [[(u0, v0), (u1, v0), (u1, v1), (u0, v1)]])
        g.put(piece, None, "screen")
    return g


# --- build ---------------------------------------------------------------------------------------------------------

def build(p, mats):
    """Build the cockpit's renderers and pivots under cockpit_cell and the canopy hinge. Runs after parts.organise:
    the cockpit hangs from the organised part tree. Lays out and bakes the atlas once the meshes stand. Returns the new
    objects."""
    import cockpit_front as front

    O = bpy.data.objects
    space = Space(p)
    atlas = cockpit_atlas.Atlas()
    uv = UV(atlas)
    kit = Kit(uv, atlas)
    mat = bpy.data.materials.get(SLOT) or materials.material(SLOT, (0.33, 0.34, 0.35, 1.0), 0.0, 0.6)

    glass = Glass(space)
    hood_inner = hood_frame_inner(uv, kit, glass, atlas=atlas)
    windscreen_inner = windscreen_frame_inner(uv, kit, glass, atlas=atlas)
    frame_proxy = hood_frame_inner(uv, kit, glass, proxy=True)
    space.hood_sweep([hood_inner, frame_proxy])
    interior = Gather(INTERIOR)
    screens, lenses, faces = front.build(interior, kit, atlas, uv, space)
    faces += consoles(interior, uv, kit, atlas, space)
    tub(interior, uv, kit, atlas, space)
    proxy = cockpit_proxy(uv, atlas, space)
    screen = tac_screen(screens)
    lamp = front.lamp_mesh(lenses)
    atlas.pack()
    LAST["atlas"], LAST["groups"] = atlas, {k: interior.tris(k) for k in GROUPS}
    LAST["frame_shell"] = hood_inner.tris("frame")
    LAST["faces"] = faces

    made = [interior.object([SLOT]), hood_inner.object([SLOT]), windscreen_inner.object([SLOT]),
            screen.object(["tacScreenDisplay"]), lamp.object(["CockpitWarningLight"]),
            proxy.object(["Matte_black"]), frame_proxy.object(["Matte_black"])]
    LAST["face_groups"] = list(interior.groups)
    cell, hinge = O["cockpit_cell"], O["canopy"]
    import parts  # imports this module back

    for obj in made:
        parts.recentre(obj)
        world = obj.matrix_world.copy()
        obj.parent = hinge if obj.name in ("canopy_frame_inner", "canopy_frame_proxy") else cell
        obj.matrix_world = world
        obj["role"] = "visual" if obj.name in PROXIES else "cockpit_view"
        obj["mass_kg"] = 0
    open_cell(cell)
    trim_frames(O["fuselage_forward"], space)
    for name, at in zip(PIVOTS + (SEAT,), (STOCK["stick_pivot"], STOCK["throttle_pivot"], STOCK["seat_origin"])):
        made.append(bi.empty(name, Matrix.Translation(P(*at)), cell))
        made[-1]["role"] = "cockpit_view"
        made[-1]["mass_kg"] = 0
    bpy.context.view_layer.update()
    bake_ao(atlas, made[:3])
    atlas.write(os.path.join(REPO, "art", "export", "textures"))
    print("cockpit: interior %d (front %d, consoles %d, tub %d), hood frame %d, windscreen frame %d, screen %d, "
          "lamps %d, proxies %d + %d; atlas %.0f%% laid out" % (
              interior.tris(), *[interior.tris(k) for k in GROUPS], hood_inner.tris(), windscreen_inner.tris(),
              screen.tris(), lamp.tris(), proxy.tris(), frame_proxy.tris(), 100 * atlas.use))
    return made


AO_BAKE = {"samples": 96, "distance": 0.75, "seed": 7}


def bake_ao(atlas, objs):
    """Cycles-bake ambient occlusion into the atlas's charts from the built aircraft: the interior and the inner
    frames bake (their charted faces only: the rest map, for the bake, to a corner off the sheet), and everything the
    cockpit view draws occludes: not the glass, the cell or the proxies the view hides, the colliders, LOD1 or the
    references. CPU with a fixed seed, so the same build bakes the
    same."""
    scene = bpy.context.scene
    keep = (scene.render.engine, scene.cycles.device, scene.cycles.samples, scene.cycles.seed, scene.world)
    hidden = []
    skip = {"Colliders", "LOD1", "References"}
    # what the cockpit view does not draw (the cell round the cockpit, the proxies on its surfaces) and the glass
    glass = set(COCKPIT_VIEW_HIDDEN) | {canopy.GLASS_INNER, canopy.WINDSCREEN_INNER, TAC_SCREEN, WARNING_LAMPS}
    for o in scene.objects:
        if o.type == "MESH" and not o.hide_render and (o.name in glass or {c.name for c in o.users_collection} & skip):
            o.hide_render = True
            hidden.append(o)
    img = bpy.data.images.new("CockpitAOBake", cockpit_atlas.W, cockpit_atlas.H, float_buffer=True, alpha=True)
    img.pixels.foreach_set(np.zeros(cockpit_atlas.W * cockpit_atlas.H * 4, np.float32))
    mat = bpy.data.materials[SLOT]
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    saved = []
    for o in objs:
        me = o.data
        layer = me.uv_layers.active.data
        uvs = np.zeros(len(layer) * 2, np.float32)
        layer.foreach_get("uv", uvs)
        saved.append(uvs.copy())
        flags = np.zeros(len(me.polygons), np.int32)
        me.attributes["bake"].data.foreach_get("value", flags)
        starts = np.zeros(len(me.polygons), np.int32)
        counts = np.zeros(len(me.polygons), np.int32)
        me.polygons.foreach_get("loop_start", starts)
        me.polygons.foreach_get("loop_total", counts)
        off = np.repeat(flags == 0, counts)
        uv2 = uvs.reshape(-1, 2)
        uv2[off] = (1.5, 1.5)
        layer.foreach_set("uv", uv2.ravel())
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = AO_BAKE["samples"]
    scene.cycles.seed = AO_BAKE["seed"]
    world = bpy.data.worlds.new("CockpitAOBake")
    world.light_settings.distance = AO_BAKE["distance"]
    scene.world = world
    for o in scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.bake(type="AO", margin=4, margin_type="EXTEND", use_clear=False)
    px = np.array(img.pixels[:], np.float32).reshape(cockpit_atlas.H, cockpit_atlas.W, 4)[::-1]
    atlas.take_bake(px[..., 0].copy(), px[..., 3] > 0.5)
    for o, uvs in zip(objs, saved):
        o.data.uv_layers.active.data.foreach_set("uv", uvs)
        o.select_set(False)
    mat.node_tree.nodes.remove(node)
    bpy.data.images.remove(img)
    for o in hidden:
        o.hide_render = False
    scene.render.engine, scene.cycles.device, scene.cycles.samples, scene.cycles.seed, scene.world = keep
    bpy.data.worlds.remove(world)


def open_cell(cell):
    """Drop the cockpit cell's ceiling: cutting the canopy out of the cell's box left a lid at the canopy's foot, which
    from outside hid everything under the glass below sill height. Its vertices stay, so its collider and LOD1 hull
    are unchanged; the cell hides in the cockpit view, and from outside the proxy now shows."""
    bm = bmesh.new()
    bm.from_mesh(cell.data)
    rot = cell.matrix_world.to_3x3()
    lid = [f for f in bm.faces if (rot @ f.normal).normalized().z > 0.3
           and (cell.matrix_world @ f.calc_center_median()).z > LAYOUT["console"]["top_z"]]
    bmesh.ops.delete(bm, geom=lid, context="FACES_ONLY")
    bm.to_mesh(cell.data)
    bm.free()
    LAST["cell_lid_faces"] = len(lid)


def trim_frames(core, space):
    """Drop the faces of the fuselage frames that stand inside the cockpit: the rings run 3 to 8 cm in from the skin,
    so their inner edge stood proud of the lining, above the consoles and the ledge, and through the stock throttle.
    Vertices stay, so the structure core's collider and LOD1 hull are unchanged."""
    s0, s1 = LAYOUT["footwell_s"], LAYOUT["bulkhead"][1]
    bm = bmesh.new()
    bm.from_mesh(core.data)
    inside = []
    for f in bm.faces:
        c = core.matrix_world @ f.calc_center_median()
        s = c.y + bi.S0
        if s0 <= s <= s1 and LAYOUT["floor_z"] < c.z < 0.9 and abs(c.x) < space.wall_x(s, c.z) + 0.012:
            inside.append(f)
    bmesh.ops.delete(bm, geom=inside, context="FACES_ONLY")
    bm.to_mesh(core.data)
    bm.free()
    LAST["frame_faces_trimmed"] = len(inside)


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAST = {}  # the last build's atlas and face groups, for check() and the review renders


# --- checks --------------------------------------------------------------------------------------------------------

def mesh_arrays(obj):
    """World positions, triangles (vertex indices), triangle UVs and triangle areas of a mesh object."""
    me = obj.data
    me.calc_loop_triangles()
    m = obj.matrix_world
    pos = np.array([tuple(m @ v.co) for v in me.vertices])
    tris = np.array([tuple(t.vertices) for t in me.loop_triangles], dtype=int).reshape(-1, 3)
    loops = np.array([tuple(t.loops) for t in me.loop_triangles], dtype=int).reshape(-1, 3)
    polys = np.array([t.polygon_index for t in me.loop_triangles], dtype=int)
    uv = np.array([tuple(d.uv) for d in me.uv_layers.active.data])[loops] if me.uv_layers.active else None
    p = pos[tris]
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    return pos, tris, uv, area, polys


def components(pos, tris):
    """Triangles grouped by welded connectivity (positions rounded to a micron), as the digest's items count."""
    _, inv = np.unique(np.round(pos, 6), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    par = list(range(int(inv.max()) + 1))

    def root(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    for t in inv[tris]:
        a = root(t[0])
        for b in t[1:]:
            par[root(b)] = a
    comp = {}
    for k, t in enumerate(tris):
        comp.setdefault(root(inv[t[0]]), []).append(k)
    return list(comp.values())


def measure(icarus):
    """The cockpit digest's measurements on the built cockpit, measured as .cache/research/digest/wave1_cockpit.py
    measures (item classes, density, repeated UVs, regions, display rings), at canopy.EYE."""
    O = bpy.data.objects
    eye = np.array(tuple(eye_point()))
    out = {}
    pos, tris, uv, area, polys = mesh_arrays(O[INTERIOR])
    out["interior_tris"] = len(tris)
    ua = 0.5 * np.abs((uv[:, 1, 0] - uv[:, 0, 0]) * (uv[:, 2, 1] - uv[:, 0, 1])
                      - (uv[:, 2, 0] - uv[:, 0, 0]) * (uv[:, 1, 1] - uv[:, 0, 1]))
    ok = area > 1e-9
    d = np.sqrt(ua[ok] * cockpit_atlas.W * cockpit_atlas.H / area[ok])
    w = area[ok]
    order = np.argsort(d)
    cw = np.cumsum(w[order])
    out["px_per_m_median"] = float(d[order][np.searchsorted(cw, cw[-1] / 2)])
    out["swatch_area_share"] = float(w[d < 1.0].sum() / w.sum())
    flat = np.nonzero(ok)[0][d < 1.0]
    groups = LAST.get("face_groups", [])
    out["swatch_at"] = [tuple(round(q, 3) for q in sxz(Vector(pos[tris[i]].mean(0)))) + (
        groups[polys[i]] if polys[i] < len(groups) else "?",) for i in flat[:4]]
    key = Counter(tuple(np.round(np.sort(t.reshape(-1)), 4)) for t in uv[ua > 1e-10])
    out["repeated_uv_tris"] = int(sum(c for c in key.values() if c > 1))
    # the panel faces: triangles mapped into a panel-density chart
    in_panel = np.zeros(len(uv), bool)
    for x0, y0, pw, ph in LAST["atlas"].panel_rects:
        in_panel |= (uv[:, :, 0].min(1) >= x0 / cockpit_atlas.W - 1e-6) & (uv[:, :, 0].max(1) <= (x0 + pw) / cockpit_atlas.W + 1e-6) \
            & (uv[:, :, 1].min(1) >= 1 - (y0 + ph) / cockpit_atlas.H - 1e-6) & (uv[:, :, 1].max(1) <= 1 - y0 / cockpit_atlas.H + 1e-6)
    sel = in_panel[ok]
    out["panel_px_per_m"] = float(np.median(d[sel])) if sel.any() else 0.0
    comps = components(pos, tris)
    small_items, small_tris, fasteners, classes = 0, 0, 0, Counter()
    for ks in comps:
        v = pos[tris[ks].ravel()]
        size = tuple(sorted(np.round(np.ptp(v, axis=0) * 1000).astype(int).tolist(), reverse=True))
        n = len(ks)
        if n <= 400 and size[0] <= 80:
            small_items += 1
            small_tris += n
            classes[(n, size)] += 1
            if n == 28 and size[0] <= 8:
                fasteners += 1
    out["items"], out["small_tris"], out["fasteners"] = small_items, small_tris, fasteners
    out["small_share"] = small_tris / len(tris)
    out["top_classes"] = ["%dt %dx%dx%d x%d" % (n, *s, c) for (n, s), c in classes.most_common(8)]
    # regions by triangle centroid in the eye frame
    import cockpit_front as front

    top_z = front.FRONT["glass_top"][1]
    # the panel face: the nearest interior point ahead on the centreline, 0.10 to 0.40 m under the eye
    # (cockpit_regions.py's panel_fwd)
    face = pos[(np.abs(pos[:, 0]) < 0.1) & (pos[:, 1] < eye[1]) & (np.abs(pos[:, 2] - (EYE[2] - 0.25)) < 0.15)]
    fwd = float(eye[1] - face[:, 1].max()) if len(face) else EYE[0] - front.FRONT["glass_top"][0]
    c = pos[tris].mean(1) - eye
    lat, f, h = np.abs(c[:, 0]), c[:, 1] * -1, c[:, 2]
    k = np.full(len(tris), "tub", dtype=object)
    TOP = top_z - EYE[2]
    k[(lat >= 0.18) & (f > -0.65) & (f < fwd - 0.12) & (h > -0.75) & (h < -0.12)] = "console"
    k[(f > fwd - 0.12) & (lat < 0.32) & (h <= TOP + 0.03)] = "panel"
    k[(f > 0.3) & (h > TOP + 0.03)] = "glare"
    k[(f > 0.3) & (lat < 0.13) & (h > TOP + 0.05)] = "hud"
    counts = {r: int((k == r).sum()) for r in ("panel", "glare", "hud", "console", "tub")}
    total = max(1, len(tris))
    out["regions"] = counts
    out["front_office"] = (counts["panel"] + counts["glare"] + counts["hud"]) / total
    out["consoles"] = counts["console"] / total
    out["tub"] = counts["tub"] / total
    out["hud"] = counts["hud"]
    # eye geometry: the canopy's, plus the panel face ahead and the cockpit sill (the ledge) below
    g = canopy.eye_geometry(EYE)
    out["overhead"], out["side"] = g["overhead"], g["side"]
    near = pos[(np.abs(pos[:, 0]) < 0.1) & (pos[:, 1] < eye[1]) & (np.abs(pos[:, 2] - (EYE[2] - 0.25)) < 0.15)]
    out["panel_ahead"] = float(eye[1] - near[:, 1].max()) if len(near) else 0.0
    side = pos[(np.abs(pos[:, 1] - eye[1]) < 0.1) & (np.abs(pos[:, 0]) > 0.2) & (pos[:, 2] < eye[2])]
    out["sill"] = float(eye[2] - side[:, 2].max()) if len(side) else 0.0
    # displays: size, distance and drop from the eye, density, the bezel lip and the triangles round each
    spos, stris, suv, _, spolys = mesh_arrays(O[TAC_SCREEN])
    shows = []
    for pi in sorted(set(spolys.tolist())):
        sel = spolys == pi
        v = spos[np.unique(stris[sel].ravel())]
        cen = v.mean(0)
        t0 = stris[sel][0]
        n = np.cross(spos[t0[1]] - spos[t0[0]], spos[t0[2]] - spos[t0[0]])
        n /= np.linalg.norm(n)
        if np.dot(n, eye - cen) < 0:
            n = -n
        u = np.cross(n, [0, 0, 1.0])
        u /= np.linalg.norm(u)
        wv = np.cross(n, u)
        lu, lw = (v - cen) @ u, (v - cen) @ wv
        hu, hw = np.ptp(lu) / 2, np.ptp(lw) / 2
        uvw = np.ptp(suv[sel][:, :, 0]) * TAC_SCREEN_PX[0]
        q = pos - cen
        pu, pw, ph = q @ u, q @ wv, q @ n
        ring = (np.abs(pu) < hu + 0.035) & (np.abs(pw) < hw + 0.035) & (np.abs(ph) < 0.05)
        ctr = pos[tris].mean(1) - cen
        tu, tw, th = ctr @ u, ctr @ wv, ctr @ n
        shows.append({"size": (2 * hu, 2 * hw), "dist": float(np.linalg.norm(cen - eye)), "below": float(eye[2] - cen[2]),
                      "px_per_m": uvw / (2 * hu), "bezel_mm": float(np.median(ph[ring]) * 1000) if ring.any() else 0.0,
                      "ring_tris": int(((np.abs(tu) < hu + 0.035) & (np.abs(tw) < hw + 0.035) & (np.abs(th) < 0.05)).sum())})
    out["displays"] = shows
    ab = spos[np.unique(stris[np.isin(spolys, sorted(set(spolys.tolist()))[:2])].ravel())]
    out["main_width"] = float(np.ptp(ab[:, 0]))
    count = lambda name: len(O[name].data.polygons) and sum(len(f.vertices) - 2 for f in O[name].data.polygons)
    out["frame_inner"] = count("canopy_frame_inner")
    out["frame_shell"] = LAST.get("frame_shell", 0)
    out["windscreen_frame_inner"] = count("windscreen_frame_inner")
    out["lamps"] = count(WARNING_LAMPS)
    out["proxy_interior"], out["proxy_frame"] = count("cockpit_proxy"), count("canopy_frame_proxy")
    out["cockpit_tris"] = sum(count(n) for n in (INTERIOR, "canopy_frame_inner", "windscreen_frame_inner", TAC_SCREEN,
                                                  canopy.GLASS_INNER, canopy.WINDSCREEN_INNER)) + 1890 + 880
    return out


def tree_of(objs, matrix=None):
    bm = bmesh.new()
    for o in objs:
        me = o.data.copy()
        me.transform((matrix or Matrix.Identity(4)) @ o.matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    t = BVHTree.FromBMesh(bm)
    bm.free()
    return t


def face_info(objs, j, matrix=None):
    """Which object face index j of tree_of(objs) is, and its extents in (s, x, z)."""
    for o in objs:
        if j < len(o.data.polygons):
            poly = o.data.polygons[j]
            m = (matrix or Matrix.Identity(4)) @ o.matrix_world
            pts = [sxz(m @ o.data.vertices[k].co) for k in poly.vertices]
            lo, hi = [min(p[a] for p in pts) for a in range(3)], [max(p[a] for p in pts) for a in range(3)]
            return "%s s %.3f-%.3f x %.3f-%.3f z %.3f-%.3f" % (o.name, lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
        j -= len(o.data.polygons)
    return "?"


def box_tree(boxes):
    """A BVH of axis boxes (s0, s1, x0, x1, z0, z1)."""
    verts, faces = [], []
    for s0, s1, x0, x1, z0, z1 in boxes:
        b = len(verts)
        verts += [P(s, x, z) for s in (s0, s1) for x in (x0, x1) for z in (z0, z1)]
        faces += [(b + i for i in f) for f in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2),
                                               (1, 3, 7, 5))]
    return BVHTree.FromPolygons(verts, [tuple(f) for f in faces])


def head_gap(hinge, hood, step_deg=5.0):
    """The least distance from the stock seat's headbox (STOCK seat_head, its corners and edge midpoints) to the hood's
    meshes, shut and at each step of the opening."""
    points = []
    for s0, s1, hx, z0, z1 in STOCK["seat_head"]:
        for s in (s0, (s0 + s1) / 2, s1):
            for x in (-hx, 0.0, hx):
                for z in (z0, z1):
                    points.append(P(s, x, z))
    a, u = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
    steps = int(math.ceil(abs(hinge["travel_deg"]) / step_deg))
    gap = math.inf
    for k in range(steps + 1):
        turn = Matrix.Translation(a) @ Matrix.Rotation(math.radians(hinge["travel_deg"] * k / steps), 4, u) \
            @ Matrix.Translation(-a)
        tree = tree_of(hood, turn)
        gap = min(gap, min(tree.find_nearest(q)[3] for q in points))
    return gap


def stock_keepout():
    """Boxes the stock seat, stick and throttle occupy through the controls' travel."""
    boxes = [(s0, s1, -hx, hx, z0, z1) for s0, s1, hx, z0, z1 in STOCK["seat"]]
    for s0, s1, x0, x1, z0, z1 in STOCK["stick"]:
        reach = (z1 - STOCK["stick_pivot"][2]) * math.sin(math.radians(STOCK["stick_deg"]))
        boxes.append((s0 - reach, s1 + reach, x0 - reach, x1 + reach, max(z0, STOCK["stick_pivot"][2] + 0.004), z1))
    for s0, s1, x0, x1, z0, z1 in STOCK["throttle"]:
        travel = (z1 - STOCK["throttle_pivot"][2]) * math.sin(math.radians(STOCK["throttle_deg"]))
        boxes.append((s0 - travel, s1, x0, x1, z0 - 0.008, z1))
    return boxes


def check(icarus):
    """The budgets, Cockpit rules 2 to 6, 10, 16, 26, 27, 30, 31 and 32's bands, and the clearances: the glare
    shield under the over-nose line, every display fully seen from the eye, the interior clear of the airframe, glass
    and frames, the stock seat, stick and throttle, and of the hood as it opens; the inner frames in their inset."""
    import budget

    O = bpy.data.objects
    problems = budget.over_caps(icarus, BUDGET)
    m = measure(icarus)
    LAST["measure"] = m

    def band(name, value):
        lo, hi = RULES[name]
        if not lo <= value <= hi:
            problems.append("%s %.3f outside %.3f to %.3f" % (name, value, lo, hi))
    for name in ("interior_tris", "small_share", "items", "fasteners", "px_per_m_median", "panel_px_per_m", "overhead",
                 "side", "sill", "panel_ahead", "front_office", "consoles", "tub", "frame_inner", "frame_shell", "lamps",
                 "proxy_interior", "proxy_frame", "hud"):
        band(name, m[name])
    if m["cockpit_tris"] > RULES["cockpit_tris"][1]:
        problems.append("cockpit renderers %d over %d" % (m["cockpit_tris"], RULES["cockpit_tris"][1]))
    if m["swatch_area_share"] > 0:
        problems.append("%.5f of the interior's area samples a point of the atlas, at %s" % (m["swatch_area_share"],
                                                                                           m["swatch_at"]))
    for k, d in zip(DISPLAYS, m["displays"]):
        band("bezel_mm", d["bezel_mm"])
        band("ring_tris", d["ring_tris"])
        band("screen_px_per_m", d["px_per_m"])
    a = m["displays"][0]
    band("display_dist", a["dist"])
    band("display_below", a["below"])
    band("display_width", m["main_width"])

    # the hood, the coaming and everything ahead of the eye under the over-nose line, with its margin
    pos, tris, _, _, _ = mesh_arrays(O[INTERIOR])
    ahead = [Vector(p) for p in pos if LAYOUT["coaming"][0] + 0.02 < p[1] + bi.S0 < EYE[0] - 0.4
             and (p[1] + bi.S0 > LAYOUT["coaming"][1] or abs(p[0]) < 0.25)]
    import cockpit_front as front

    def limit(s):  # ahead of the hood the windscreen's foot bounds the view over the nose (cockpit_front.shroud)
        return front.windscreen_deck_z(s) if s <= LAYOUT["coaming"][1] else over_nose_z(s) - LAYOUT["over_nose_margin"]
    high = [v for v in ahead if v.z > limit(v.y + bi.S0) + 0.0005]
    if high:
        v = max(high, key=lambda v: v.z - over_nose_z(v.y + bi.S0))
        problems.append("the front office stands above the over-nose line at s %.3f x %.3f z %.3f" % sxz(v))

    # clear of the airframe, the glass and the closed hood's frames, and of the stock rig
    inside_obj = O[INTERIOR]
    interior = tree_of([inside_obj])

    def where(pairs):
        """Where the first few overlapping interior faces are, and what they belong to."""
        seen = []
        for i, _ in pairs:
            poly = inside_obj.data.polygons[i]
            pts = [sxz(inside_obj.matrix_world @ inside_obj.data.vertices[k].co) for k in poly.vertices]
            lo, hi = [min(p[a] for p in pts) for a in range(3)], [max(p[a] for p in pts) for a in range(3)]
            spot = "%s s %.3f-%.3f x %.3f-%.3f z %.3f-%.3f" % (LAST["face_groups"][i], lo[0], hi[0], lo[1], hi[1],
                                                                lo[2], hi[2])
            if spot not in seen:
                seen.append(spot)
            if len(seen) == 4:
                break
        return "; ".join(seen)
    for names in (("skin_forward_L", "skin_forward_R", "dorsal_cover"), (canopy.FRAME,), (canopy.GLASS_INNER, canopy.GLASS_OUTER),
                  (canopy.WINDSCREEN, canopy.WINDSCREEN_INNER), ("canopy_frame_inner", "windscreen_frame_inner"),
                  ("avionics_tray", "radar_tray", "fuel_aux")):
        others = [O[n] for n in names]
        pairs = interior.overlap(tree_of(others))
        if pairs:
            problems.append("interior meets %s (%d face pairs): %s; against %s" % (
                "/".join(names), len(pairs), where(pairs), face_info(others, pairs[0][1])))
    pairs = interior.overlap(box_tree(stock_keepout()))
    if pairs:
        problems.append("interior enters the stock seat, stick or throttle space (%d pairs): %s" % (len(pairs), where(pairs)))
    import internals

    body = internals.inner_solid(bi.PARAMS, 0.004, LAYOUT["coaming"][0] - 0.1, 5.4)
    hood = internals.outward(canopy.build_canopy(None, bpy.data.materials[SLOT]))
    solids = [tree_of([body]), tree_of([hood])]
    for o in (body, hood):
        bpy.data.objects.remove(o, do_unlink=True)

    def inside(t, point):
        loc, normal, _, _ = t.find_nearest(point)
        return loc is not None and (point - loc).dot(normal) <= 1e-6
    outside = [Vector(p) for p in pos[::3] if not any(inside(t, Vector(p)) for t in solids)]
    if outside:
        problems.append("%d interior vertices outside the skin and canopy, first at s %.3f x %.3f z %.3f"
                        % (len(outside), *sxz(outside[0])))

    # the hood opening: its frame, glass and proxies swept against the interior and the windscreen's inner frame
    hinge = O["canopy"]
    ha, hu = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
    fixed = tree_of([O[INTERIOR], O["windscreen_frame_inner"]])
    hood_objs = [o for o in hinge.children if o.type == "MESH"]
    for k in range(1, 9):
        angle = hinge["travel_deg"] * k / 8
        turn = Matrix.Translation(ha) @ Matrix.Rotation(math.radians(angle), 4, hu) @ Matrix.Translation(-ha)
        pairs = fixed.overlap(tree_of(hood_objs, turn))
        if pairs:
            problems.append("the opening hood meets the interior at %.0f deg: %s; against %s" % (angle, where(
                [(i, j) for i, j in pairs if i < len(inside_obj.data.polygons)]), face_info(hood_objs, pairs[0][1], turn)))
            break

    # every display fully seen from the eye: a 5 x 5 ray grid per quad
    screens = O[TAC_SCREEN]
    blockers = tree_of([O[n] for n in (INTERIOR, "canopy_frame_inner", "windscreen_frame_inner", canopy.FRAME)])
    eye = eye_point()
    for k, poly in enumerate(screens.data.polygons):
        a_, b_, c_, d_ = [screens.matrix_world @ screens.data.vertices[i].co for i in poly.vertices]
        blocked = 0
        for fu in np.linspace(0.03, 0.97, 5):
            for fv in np.linspace(0.03, 0.97, 5):
                target = a_.lerp(b_, fu).lerp(d_.lerp(c_, fu), fv)
                ray = target - eye
                blocked += blockers.ray_cast(eye, ray.normalized(), ray.length - 1e-3)[0] is not None
        if blocked:
            problems.append("display %s: %d of 25 eye rays blocked" % ("ABCD"[k], blocked))

    # the stock seat's headbox clear of the hood, shut and through the opening
    m["head_gap"] = head_gap(hinge, hood_objs)
    if m["head_gap"] < HEAD_GLASS_GAP:
        problems.append("the stock seat's headbox comes %.4f m from the hood, under %.3f" % (m["head_gap"], HEAD_GLASS_GAP))

    # the inner frames sit glass_inset inside the inner glass, never outside it
    glass = tree_of([O[canopy.GLASS_INNER], O[canopy.WINDSCREEN_INNER]])
    for name in ("canopy_frame_inner", "windscreen_frame_inner"):
        o = O[name]
        near, at = min((glass.find_nearest(o.matrix_world @ v.co)[3], o.matrix_world @ v.co) for v in o.data.vertices)
        if near < RULES["glass_inset"][0] - 1e-4:
            problems.append("%s comes %.4f m from the inner glass, under %.3f, at s %.3f x %.3f z %.3f"
                            % (name, near, RULES["glass_inset"][0], *sxz(at)))
    print("cockpit measured: interior %d tris, %d items (%.0f%% of tris), %d fasteners, %.0f px/m median (panel %.0f), "
          "%d repeated UV tris; regions front %.0f%% consoles %.0f%% tub %.0f%%; display A %.3f x %.3f m at %.3f m, %.3f "
          "below; rings %s; eye overhead %.3f side %.3f sill %.3f panel %.3f; frames %d (shell %d) + %d, lamps %d, proxies %d + %d; "
          "cockpit renderers %d" % (
              m["interior_tris"], m["items"], 100 * m["small_share"], m["fasteners"], m["px_per_m_median"],
              m["panel_px_per_m"], m["repeated_uv_tris"], 100 * m["front_office"], 100 * m["consoles"], 100 * m["tub"],
              a["size"][0], a["size"][1], a["dist"], a["below"],
              ", ".join("%s %d tris %.1f mm %.0f px/m" % (k, d["ring_tris"], d["bezel_mm"], d["px_per_m"])
                        for k, d in zip(DISPLAYS, m["displays"])),
              m["overhead"], m["side"], m["sill"], m["panel_ahead"], m["frame_inner"], m["frame_shell"], m["windscreen_frame_inner"],
              m["lamps"], m["proxy_interior"], m["proxy_frame"], m["cockpit_tris"]))
    print("cockpit items: " + ", ".join(m["top_classes"]) + "; regions %s; hud zone %d; seat headbox %.4f m from the hood"
          % (m["regions"], m["hud"], m["head_gap"]))
    if problems:
        raise ValueError("cockpit: " + "; ".join(problems))
    return m


# --- review renders ------------------------------------------------------------------------------------------------

# What the game hides in the cockpit view (Aircraft.exteriorRenderers) or never draws there.
COCKPIT_VIEW_HIDDEN = ("cockpit_cell", "avionics_tray", "radar_tray", "gear_leg_N_visible", canopy.GLASS_OUTER,
                       canopy.WINDSCREEN) + PROXIES


def stock_rig(collection):
    """The stock seat, stick and throttle as review meshes, read from the local game export (tools/local-paths.json)
    and placed at the Revoker's offsets from its eye moved to EYE; none when the export is not on this machine."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    try:
        from stores import meshverts, paths
        root = paths.load()["game_export"] / "Mesh"
    except (ImportError, SystemExit):
        return []
    eye_u = (0.0, 0.758, 6.897)  # Fighter1.prefab helmetCamPoint, prefab root frame
    items = (("stock_seat", "ejectionSeat", (0.0, 0.027 - SEAT_DROP, 7.006), -6.8, (0.33, 0.36, 0.30, 1.0)),
             ("stock_stick", "fighter1_joystick", (0.398, 0.216, 7.326), 0.0, (0.12, 0.12, 0.12, 1.0)),
             ("stock_throttle", "fighter1_throttle", (-0.382, -0.768, 7.393), 0.0, (0.12, 0.12, 0.12, 1.0)))
    made = []
    for name, mesh, origin, rx, colour in items:
        a = math.radians(rx)
        pts = []
        for x, y, z in meshverts.positions(root / (mesh + ".asset")):
            y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
            u = (x + origin[0], y + origin[1], z + origin[2])
            pts.append(P(EYE[0] - (u[2] - eye_u[2]), -u[0], EYE[2] + (u[1] - eye_u[1])))
        me = bpy.data.meshes.new(name)
        me.from_pydata(pts, [], meshverts.triangles(root / (mesh + ".asset")))
        me.validate()
        me.materials.append(materials.material("Review_" + name, colour, 0.0, 0.6))
        obj = bpy.data.objects.new(name, me)
        collection.objects.link(obj)
        made.append(obj)
    return made


def render_review(out_dir):
    """The P10 review set: the eye view at 75 degrees, the head-room section and escape path, close-ups of the panel
    and each console, the region colours, the atlas sheet, the panel under a 1,500 px/m checker, and the proxy seen
    from outside."""
    import review_sheet

    os.makedirs(out_dir, exist_ok=True)
    scene = review_sheet.setup_scene()
    sh = scene.display.shading
    sh.color_type, sh.cavity_type = "TEXTURE", "BOTH"
    sh.show_backface_culling = True
    O = bpy.data.objects
    textures = os.path.join(REPO, "art", "export", "textures")
    albedo = bpy.data.images.load(os.path.join(textures, cockpit_atlas.NAME + "_b.png"), check_existing=True)
    mat = bpy.data.materials[SLOT]
    nodes = mat.node_tree.nodes
    tex = nodes.get("atlas") or nodes.new("ShaderNodeTexImage")
    tex.name, tex.image = "atlas", albedo
    nodes.active = tex
    for name, colour in (("tacScreenDisplay", (0.05, 0.22, 0.16, 1.0)), ("CockpitWarningLight", (0.55, 0.05, 0.03, 1.0)),
                         ("Matte_black", (0.02, 0.02, 0.02, 1.0))):
        m = bpy.data.materials[name]
        m.diffuse_color = colour
        m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = colour
    review = bpy.data.collections.new("CockpitReview")
    scene.collection.children.link(review)
    rig = stock_rig(review)
    eye = eye_point()
    marks = []

    def mark(name, points, radius, colour):
        m = materials.material("CockpitReview_" + name, colour)
        for q in points:
            me = bpy.data.meshes.new(name)
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=6, radius=radius)
            bm.to_mesh(me)
            bm.free()
            me.materials.append(m)
            obj = bpy.data.objects.new(name, me)
            obj.location = q
            review.objects.link(obj)
            marks.append(obj)

    def shoot(name, loc, target, fov=None, lens=50, ortho=0.0, clip=0.005, res=(1600, 1000), up=None):
        cam = review_sheet.camera("CockpitCam_" + name)
        cam.data.type = "ORTHO" if ortho else "PERSP"
        cam.data.ortho_scale = ortho or cam.data.ortho_scale
        if fov:
            cam.data.sensor_fit, cam.data.angle = "HORIZONTAL", math.radians(fov)
        else:
            cam.data.lens = lens
        cam.data.clip_start, cam.data.clip_end = clip, 100
        cam.location = loc
        cam.rotation_euler = (target - loc).to_track_quat("-Z", "Y").to_euler()
        if up is not None:
            cam.matrix_world = frame(loc, up, loc - target)
        review_sheet.render_view(scene, cam, os.path.join(out_dir, name + ".png"), res)

    def hide(names, flag=True):
        for n in names:
            if n in O:
                O[n].hide_render = flag

    inner_glass = (canopy.GLASS_INNER, canopy.WINDSCREEN_INNER)
    # the cockpit view: what the game draws there, the clear inner glass left out
    hide(COCKPIT_VIEW_HIDDEN + inner_glass)
    ahead = Vector((0.0, -1.0, 0.0))
    down = Vector((0.0, -math.cos(math.radians(15)), -math.sin(math.radians(15))))
    shoot("eye_view_75", eye, eye + down, fov=75)
    shoot("eye_view_level", eye, eye + ahead, fov=75)
    shoot("eye_left", eye, eye + Vector((0.8, -0.55, -0.6)), fov=75)
    shoot("eye_right", eye, eye + Vector((-0.8, -0.55, -0.6)), fov=75)
    shoot("eye_up_back", eye + Vector((0.0, -0.05, -0.05)), eye + Vector((0.25, 0.6, 0.5)), fov=90)
    import cockpit_front as front

    centre = front.face_frame() @ Vector((0.0, -0.10, 0.0))
    shoot("panel", centre + front.FACE_N * 0.62, centre, fov=70, up=front.FACE_UP)
    for name, side in (("console_left", 1), ("console_right", -1)):
        target = P(4.25, side * 0.36, LAYOUT["console"]["top_z"])
        shoot(name, target + Vector((-side * 0.30, 0.10, 0.55)), target, fov=70, up=-Y)
    shoot("glare_hud", P(4.0, -0.25, 0.95), P(3.45, 0.0, 0.68), fov=50)
    shoot("footwell_pedals", P(3.95, 0.0, 0.40), P(3.25, 0.0, 0.05), fov=80)

    # regions: the interior's faces in the measurement's three colours
    m = measure(None)
    LAST["measure"] = m
    interior = O[INTERIOR]
    copy = interior.copy()
    copy.data = interior.data.copy()
    review.objects.link(copy)
    pos, tris, _, _, polys = mesh_arrays(interior)
    c = pos[tris].mean(1) - np.array(tuple(eye))
    lat, f, h = np.abs(c[:, 0]), -c[:, 1], c[:, 2]
    top = front.FRONT["glass_top"][1] - EYE[2]
    fwd = EYE[0] - front.FRONT["glass_top"][0]
    region = np.full(len(tris), 2)
    region[(lat >= 0.18) & (f > -0.65) & (f < fwd - 0.12) & (h > -0.75) & (h < -0.12)] = 1
    region[((f > fwd - 0.12) & (lat < 0.32) & (h <= top + 0.03)) | ((f > 0.3) & (h > top + 0.03))] = 0
    face_region = {}
    for r, pi in zip(region, polys):
        face_region[int(pi)] = int(r)
    copy.data.materials.clear()
    for name, colour in (("front", (0.85, 0.45, 0.15, 1.0)), ("consoles", (0.20, 0.55, 0.85, 1.0)),
                         ("tub", (0.45, 0.70, 0.35, 1.0))):
        copy.data.materials.append(materials.material("CockpitRegion_" + name, colour))
    copy.data.polygons.foreach_set("material_index", [face_region.get(i, 2) for i in range(len(copy.data.polygons))])
    sh.color_type = "MATERIAL"
    interior.hide_render = True
    shoot("regions", eye + Vector((0.0, 0.25, 0.25)), eye + down, fov=90)
    shoot("regions_plan", P(4.0, 0.0, 3.0), P(4.0, 0.0, 0.0), ortho=2.4, up=-Y)
    interior.hide_render = False
    bpy.data.objects.remove(copy, do_unlink=True)

    # the panel under a 1,500 px/m checker: 15 px squares, 1 cm on the panel face
    yy, xx = np.mgrid[0:cockpit_atlas.H, 0:cockpit_atlas.W]
    check_px = np.where(((xx // 15) + (yy // 15)) % 2 == 0, 0.85, 0.25).astype(np.float32)
    checker = bpy.data.images.new("CockpitChecker", cockpit_atlas.W, cockpit_atlas.H)
    checker.pixels.foreach_set(np.stack([check_px, check_px, check_px, np.ones_like(check_px)], -1)[::-1].ravel())
    tex.image = checker
    sh.color_type = "TEXTURE"
    shoot("checker_panel", centre + front.FACE_N * 0.62, centre, fov=70, up=front.FACE_UP)
    shoot("checker_eye", eye, eye + down, fov=75)
    tex.image = albedo
    hide(COCKPIT_VIEW_HIDDEN + inner_glass, False)

    # the head-room section: the aircraft cut at x = 0, seen from the left, with the eye, the over-nose line, the
    # stock seat, stick and throttle; then the escape path with the hood gone and the seat up its rail
    mark("eye", [eye], 0.022, (1.0, 0.25, 0.1, 1.0))
    mark("over_nose", [eye + Vector((0, -d, -d * canopy.OVER_NOSE_SLOPE)) for d in bi.spaced(0.2, 2.2, 40)], 0.005,
         (1.0, 0.8, 0.1, 1.0))
    scene.world.color = (0.8, 0.8, 0.8)
    scene.render.film_transparent = False
    sh.show_backface_culling = False
    shoot("headroom_section", Vector((5.0, eye.y + 0.15, 0.55)), Vector((0.0, eye.y + 0.15, 0.55)), ortho=2.6, clip=5.0)
    hinge = O["canopy"]
    shut = hinge.matrix_basis.copy()
    hinge.matrix_basis = shut @ Matrix.Rotation(math.radians(hinge["travel_deg"]), 4, "X")
    shoot("headroom_open", Vector((5.0, eye.y + 0.15, 0.75)), Vector((0.0, eye.y + 0.15, 0.75)), ortho=3.2, clip=5.0)
    hinge.matrix_basis = shut
    for o in hinge.children_recursive:
        o.hide_render = True
    rail = Vector((0.024, -0.230, 0.973))  # the stock seat's rail (IcarusAuthor.Checks.Cockpit.cs SeatRail), Blender axes
    ghosts = []
    for o in rig[:1]:
        for d in (0.5, 1.0, 1.5):
            ghost = o.copy()
            ghost.location = rail * d
            review.objects.link(ghost)
            ghosts.append(ghost)
    shoot("escape_path", Vector((5.0, eye.y + 0.1, 1.3)), Vector((0.0, eye.y + 0.1, 1.3)), ortho=3.6, clip=5.0)
    for o in ghosts:
        bpy.data.objects.remove(o, do_unlink=True)
    for o in hinge.children_recursive:
        o.hide_render = False
    scene.render.film_transparent = True
    sh.show_backface_culling = True

    # outside: the proxies through the glass, which is drawn as wire, and nothing of the cockpit view
    cockpit_only = [o.name for o in bi.TARGET.all_objects if o.get("role") == "cockpit_view"]
    hide(cockpit_only)
    glass = [O[n] for n in (canopy.GLASS_OUTER, canopy.WINDSCREEN)]
    for o in glass:
        o.modifiers.new("wire", "WIREFRAME").thickness = 0.003
    for o in marks:
        o.hide_render = True
    sh.color_type = "MATERIAL"
    shoot("exterior_proxy", Vector((2.4, -7.0, 2.4)), Vector((0.0, -4.0, 0.7)), lens=70)
    shoot("exterior_proxy_top", Vector((0.0, -4.0, 5.0)), Vector((0.0, -4.0, 0.0)), ortho=2.8, up=-Y)
    sh.color_type = "TEXTURE"
    for o in glass:
        o.modifiers.remove(o.modifiers["wire"])
    hide(cockpit_only, False)

    # the atlas: the four maps on one sheet
    maps = []
    for key in cockpit_atlas.MAPS:
        img = bpy.data.images.load(os.path.join(textures, "%s_%s.png" % (cockpit_atlas.NAME, key)), check_existing=True)
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        maps.append(px.reshape(img.size[1], img.size[0], 4)[::-1])
    sheet = np.concatenate([np.concatenate(maps[:2], 1), np.concatenate(maps[2:], 1)], 0)
    sheet[..., 3] = 1.0
    cockpit_atlas.write_png(os.path.join(out_dir, "atlas_sheet.png"), np.round(sheet * 255).astype(np.uint8))
    for o in marks + rig:
        bpy.data.objects.remove(o, do_unlink=True)
    return sorted(os.listdir(out_dir))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = os.path.abspath(args[0] if args else ".cache/review/wave2/p10")
    cube = bpy.data.objects.get("Cube")  # the factory-startup scene's default cube would sit in every render
    if cube is not None:
        bpy.data.objects.remove(cube, do_unlink=True)
    print("icarus:", {k: v for k, v in bi.build().items() if k != "references"})
    import cockpit  # the copy the build used, not this __main__

    print("cockpit renders:", cockpit.render_review(out))
