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
    "interior": {"target": 12500, "cap": 13500, "objects": (INTERIOR,), "cockpit": True},
    "canopy_frame_inner": {"target": 2600, "cap": 8000, "objects": ("canopy_frame_inner",), "cockpit": True},
    "windscreen_frame_inner": {"target": 1000, "cap": 1000, "objects": ("windscreen_frame_inner",), "cockpit": True},
    "tac_screen": {"target": 120, "cap": 120, "objects": (TAC_SCREEN,), "cockpit": True},
    "stock_hotas": {"target": 2770, "cap": 2770, "objects": (), "cockpit": True},
    "proxies": {"target": 940, "cap": 2930, "objects": PROXIES},
}
# Cockpit rules 2 to 6, 10, 16, 26, 27, 30 and 31 of the cockpit digest: (low, high).
RULES = {
    "interior_tris": (10500, 13500),
    "cockpit_tris": (19500, 35000),  # all cockpit renderers; 19,500 is the reference aircraft, reported not padded
    "small_share": (2 / 3, 1.0),
    "items": (190, 330),
    "fasteners": (50, 95),
    "px_per_m_median": (300, 650),
    "panel_px_per_m": (1300, 1700),
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
TILT = math.radians(20.0)
LAYOUT = {
    # The panel's aft face is a plane through `at`, its top tilted forward by TILT.
    "panel": {"at": (3.62, 0.0, 0.46), "z0": 0.24, "z1": 0.615, "half_width": 0.315, "thickness": 0.012,
              "edge": 0.003},
    "raised": {"half_width": 0.255, "top_v": 0.148},  # the panel's centre steps up to carry display A's frame
    "glare": {"s0": 3.06, "s1": 3.58, "z0": 0.495, "z1": 0.650, "half_width0": 0.27, "half_width1": 0.305,
              "lip_under_z": 0.640},
    "hud": {"half_width": 0.075, "s0": 3.40, "s1": 3.55, "z0": 0.60, "top_z": 0.672},
    "pedestal": {"s0": 3.58, "s1": 3.70, "half_width": 0.08},
    "floor_z": -0.05,
    "footwell_s": 3.08,
    # the coaming under the windscreen: from its front (s0) back to the glare shield (s1), its deck this far inside
    # the skin at the sides
    "coaming": (2.36, 3.06, 0.008),
    "console": {"s0": 3.78, "s1": 4.84, "inner": 0.278, "top_z": 0.322},
    "pedals": {"s": 3.28, "x": 0.12, "bar": (3.18, 0.36)},
    "bulkhead": (4.88, 4.92),
    # The lining stands this far inside the skin, inboard of the fuselage frames' outer part; a rib covers the rest
    # of each frame (internals: 3 to 8 cm in, 25 mm thick, at s 3.4, 4.0 and 4.6).
    "lining_inset": 0.060,
    "ribs": (3.4125, 4.0125, 4.6125),
    "over_nose_margin": 0.005,
}
# Display glass in the panel plane, sized for 1,800 to 2,600 px/m of the 1024 x 512 TacScreenRenderer, and the UV
# rect of the canvas each shows: A the radar, target camera and right panel; B system status; C flight instruments.
DISPLAYS = {
    "A": {"glass": (0.440, 0.155), "x": 0.0, "top_z": 0.612, "corner_r": 0.004, "keys": ("1234", "ABCD"),
          "uv": (0.0, 0.291, 1.0, 1.0), "title": None},
    "B": {"glass": (0.090, 0.079), "x": -0.165, "z": 0.345, "corner_r": 0.004, "keys": ("1234", "ABCD"),
          "uv": (0.428, 0.0, 0.592, 0.29), "title": "SYS STAT"},
    "C": {"glass": (0.108, 0.075), "x": 0.165, "z": 0.345, "corner_r": 0.006, "keys": ("123", "ABC"),
          "uv": (0.770, 0.008, 0.973, 0.290), "title": "FLT INST"},
}
TAC_SCREEN_PX = (1024, 512)
BEZEL = {"frame": 0.020, "height": 5 * MM, "recess_ring": 3 * MM, "recess_z": 2.5 * MM, "floor_z": 1 * MM,
         "screen_z": 1.5 * MM}
FRAME = {"glass_inset": 0.0052, "depth": 0.028, "seam_cover": 0.065}  # the inner frame shell, off the inner glass
SEAT_CLEAR = 0.010  # the inner frame stops this far up the glass from the seam, clear of the skin the hood seats in
LEDGE_DROP = 0.024  # the cockpit sill's top under the glass seam: 0.27 m or more below the eye (Cockpit rule 27)


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


PANEL_N = Vector((0.0, math.cos(TILT), math.sin(TILT)))  # toward the pilot: aft and up
PANEL_UP = Vector((0.0, -math.sin(TILT), math.cos(TILT)))  # up the panel face: up and forward


def panel_v(z):
    return (z - LAYOUT["panel"]["at"][2]) / math.cos(TILT)


def on_panel(x, v, lift=0.0):
    """Placement on the panel's aft face at x (local X, the pilot's right) and v up the plane."""
    return frame(P(*LAYOUT["panel"]["at"]) + Vector((-x, 0.0, 0.0)) + PANEL_UP * v + PANEL_N * lift, PANEL_UP, PANEL_N)


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
    per face corner, and the faces dropped after orientation (undersides on a surface, never seen)."""

    def __init__(self, sheet=False):
        self.verts, self.faces, self.uvs, self.hidden, self.sheet = [], [], [], set(), sheet

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
        if piece.sheet:
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
        """The mesh object at the identity in the Icarus collection, faces on mat_of(group) (default the first)."""
        used = sorted(set(k for f in self.faces for k in f))
        remap = {k: i for i, k in enumerate(used)}
        me = bpy.data.meshes.new(self.name)
        me.from_pydata([tuple(self.verts[k]) for k in used], [], [tuple(remap[k] for k in f) for f in self.faces])
        layer = me.uv_layers.new(name="UVMap")
        layer.data.foreach_set("uv", [c for uv in self.uvs for p in uv for c in p])
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
    """A face fitted into a tile rect, flat in its own plane (X from xaxis, or local X)."""
    n = _normal(points)
    xa = xaxis or X
    u = xa - n * xa.dot(n)
    u = u.normalized() if u.length > 1e-6 else n.orthogonal().normalized()
    v = n.cross(u)
    us, vs = [p.dot(u) for p in points], [p.dot(v) for p in points]
    du, dv = max(max(us) - min(us), 1e-9), max(max(vs) - min(vs), 1e-9)
    return [(rect.u0 + (a - min(us)) / du * (rect.u1 - rect.u0), rect.v0 + (b - min(vs)) / dv * (rect.v1 - rect.v0))
            for a, b in zip(us, vs)]


def rect_box_uvs(points, rect, box):
    """Points in a cap mapped into rect by a shared box (x0, y0, x1, y1) in local X and Y, so a fan's triangles
    tile the rect together."""
    x0, y0, x1, y1 = box
    return [(rect.u0 + (p.x - x0) / (x1 - x0) * (rect.u1 - rect.u0), rect.v0 + (p.y - y0) / (y1 - y0) * (rect.v1 - rect.v0))
            for p in points]


class UV:
    """What a face maps onto: a strip by name, a tile or label rect (fitted face by face, or across a whole cap)."""

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


def grid_sheet(uv, grid, spec, along=None):
    """A one-sided sheet from rows of points, each cell mapped flat onto spec."""
    piece = Piece(sheet=True)
    cols = len(grid[0])
    verts = [Vector(p) for row in grid for p in row]
    for r in range(len(grid) - 1):
        for c in range(cols - 1):
            f = (r * cols + c, r * cols + c + 1, (r + 1) * cols + c + 1, (r + 1) * cols + c)
            pts = [verts[i] for i in f]
            piece.add(pts, [(0, 1, 2, 3)], [uv(spec, pts, along=along)])
    return piece


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
    """Rings of world points (same count) joined in order, the ends capped."""
    k = len(rings[0])
    verts = [Vector(p) for r in rings for p in r]
    faces = [(j * k + i, j * k + (i + 1) % k, (j + 1) * k + (i + 1) % k, (j + 1) * k + i)
             for j in range(len(rings) - 1) for i in range(k)]
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
    """Stock-sized controls, each built once per legend and reused, so copies share their UVs (Cockpit rule 11)."""

    def __init__(self, uv, atlas):
        self.uv, self.atlas = uv, atlas

    def key(self, legend=None):
        """Display key: 12.2 x 10.6 x 6.1 mm, its cap sloping down toward the bottom, legend on the cap. 14 tris."""
        w, d, h, inset, drop = 12.2 * MM, 10.6 * MM, 6.1 * MM, 0.8 * MM, 1.1 * MM
        base = ring_rect(w / 2, d / 2, 0.0)
        top = [(x - math.copysign(inset, x), y - math.copysign(inset, y), h if y > 0 else h - drop) for x, y, _ in base]
        cap = self.atlas.label(legend or " ", paper="key", cell=(16, 14))
        return stack(self.uv, [base, top], "keyside", top_uv=cap, top_apex=(0.0, 0.0, h - drop / 2 + 0.3 * MM))

    def indicator(self, lens="lens_clear", legend=None, body="keyside"):
        """Indicator or push button: 17.1 x 16.4 x 9.5 mm, 1.15 mm bevel, a lens set into the top. 46 tris."""
        w, d, h, b = 17.1 * MM, 16.4 * MM, 9.5 * MM, 1.15 * MM
        rings = [ring_rect(w / 2, d / 2, 0.0), ring_rect(w / 2, d / 2, h - b), ring_rect(w / 2 - b, d / 2 - b, h),
                 ring_rect(w / 2 - 2 * b, d / 2 - 2 * b, h), ring_rect(w / 2 - 2 * b, d / 2 - 2 * b, h - 0.9 * MM),
                 ring_rect(w / 2 - 2 * b - 0.3 * MM, d / 2 - 2 * b - 0.3 * MM, h - 0.6 * MM)]
        cap = self.atlas.label(legend, paper=lens, cell=(max(22, 6 * len(legend) + 1), 20)) if legend else self.atlas.tile(lens)
        return stack(self.uv, rings, [body, body, body, "recess", "recess"], top_uv=cap,
                     top_apex=(0.0, 0.0, h - 0.4 * MM))

    def knob(self):
        """Rotary knob: 23 mm, 16-sided, a pointer painted on its face. 94 tris."""
        rings = [ring_circle(11.5 * MM, 0.0, 16), ring_circle(11.5 * MM, 8.5 * MM, 16), ring_circle(10.3 * MM, 10.2 * MM, 16)]
        return stack(self.uv, rings, "knurl", top_uv=self.atlas.tile("knob_top"), top_apex=(0.0, 0.0, 10.4 * MM),
                     bottom_uv="knurl")

    def toggle(self, throw_deg=15.0):
        """Toggle switch: a 12-sided 20.5 mm collar (72 tris) and a ball-tipped lever thrown toward +Y."""
        collar = [ring_circle(10.25 * MM, 0.0, 12), ring_circle(10.25 * MM, 2.5 * MM, 12), ring_circle(8.6 * MM, 4.0 * MM, 12)]
        a = stack(self.uv, collar, "metal", top_apex=(0.0, 0.0, 4.0 * MM), bottom_apex=(0.0, 0.0, 0.0))
        profile = [(2.0, 1.7), (5.0, 1.6), (9.0, 1.45), (13.0, 1.3), (16.5, 1.25), (17.5, 1.9), (18.6, 2.4), (20.0, 2.55),
                   (21.4, 2.3), (22.4, 1.5)]
        lever = Matrix.Rotation(math.radians(-throw_deg), 4, "X")
        rings = [[tuple(lever @ Vector(p)) for p in ring_circle(r * MM, z * MM, 8)] for z, r in profile]
        b = stack(self.uv, rings, "metal", top_apex=tuple(lever @ Vector((0.0, 0.0, 22.9 * MM))))
        return [a, b]

    def guard(self, open_deg=100.0):
        """Red switch guard, 17.7 x 41.3 x 29.6 mm, standing open over the switch, and its hinge."""
        hw, length, t, c = 17.7 / 2 * MM * 1.3, 41.3 * MM, 1.4 * MM, 1.5 * MM
        hy, hz, hr = -length / 2 + 2.5 * MM, 2.5 * MM, 2.5 * MM
        at = Matrix.Translation((0.0, hy, hz))
        lid = at @ Matrix.Rotation(math.radians(open_deg), 4, "X") @ at.inverted()
        heights = [10.0, 16.5, 22.0, 26.5, 29.0, 29.6, 29.6, 27.5]
        rings = []
        for i, hh in enumerate(heights):  # a channel over the switch, closed at its free end by a plate
            y, h = -length / 2 + (length - t) * i / (len(heights) - 1), hh * MM
            rings.append([tuple(lid @ Vector((x, y, z))) for x, z in (
                (hw, 0.0), (hw, h - c), (hw - c, h), (-hw + c, h), (-hw, h - c), (-hw, 0.0), (-hw + t, 0.0),
                (-hw + t, h - t), (hw - t, h - t), (hw - t, 0.0))])
        h = heights[-1] * MM
        plate = [[tuple(lid @ Vector((x, y, z))) for x, z in ((hw, 0.0), (hw, h - c), (hw - c, h), (-hw + c, h),
                                                                  (-hw, h - c), (-hw, 0.0))]
                 for y in (length / 2 - t, length / 2)]
        hinge = [[(x, hy + hr * math.cos(a), hz + hr * math.sin(a)) for a in [2 * math.pi * i / 8 for i in range(8)]]
                 for x in (-hw - MM, hw + MM)]
        return [stack(self.uv, rings, "guard"), stack(self.uv, plate, "guard"), stack(self.uv, hinge, "metal")]

    def breaker(self):
        """A circuit breaker: an eight-sided 9 mm button 7 mm tall, no underside. 22 tris."""
        rings = [ring_circle(4.5 * MM, 0.0, 8, phase=math.pi / 8), ring_circle(4.5 * MM, 7 * MM, 8, phase=math.pi / 8)]
        return stack(self.uv, rings, "keyside", top_uv=self.atlas.tile("lens_clear"), bottom_hidden=True)

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
        piece.add([Vector(p) for p in pts], [(0, 1, 2, 3)],
                  [[(rect.u0, rect.v0), (rect.u1, rect.v0), (rect.u1, rect.v1), (rect.u0, rect.v1)]])
        return piece

    def bezel(self, w, h, frame_w, corner_r):
        """Stepped display frame round a w x h glass: rolled outer edge, flat top, a step down to a 3 mm recess ring
        and a well whose floor sits under the screen."""
        seg = 3 if corner_r >= 0.006 else 2
        hgt, ring, rz, fz = BEZEL["height"], BEZEL["recess_ring"], BEZEL["recess_z"], BEZEL["floor_z"]

        def at(d, z):
            r = MM + (corner_r + d - MM) * min(1.0, d / (ring + MM))
            return ring_rect(w / 2 + d, h / 2 + d, z, r, seg)
        rings = [at(frame_w, 0.0), at(frame_w, hgt - MM), at(frame_w - MM, hgt), at(ring + MM, hgt), at(ring, rz),
                 at(0.0, rz), at(0.0, fz)]
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

    def hood_x(self, s, z, side):
        """|x| of the shut hood (frame or glass) at height z on one side, from the centreline out."""
        found = hit(self.hood, P(s, 0.0, z), Vector((side, 0.0, 0.0)), 1.0)
        return abs(found[0].x) if found else math.inf


# --- the interior --------------------------------------------------------------------------------------------------

GROUPS = ("front", "console", "tub")


def front_office(g, uv, kit, atlas):
    """Main panel, displays, glare shield, HUD, pedestal; returns the screen quads and the lamp lenses."""
    pl = LAYOUT["panel"]
    vb, vt, hw = panel_v(pl["z0"]), panel_v(pl["z1"]), pl["half_width"]
    rs = LAYOUT["raised"]
    hr, vr, ch = rs["half_width"], rs["top_v"], 0.008
    cut = 0.030  # the outer top corners, chamfered clear of the hood's longeron as it swings open over the left one
    outline = [(-hw + ch, vb), (hw - ch, vb), (hw, vb + ch), (hw, vr - cut), (hw - cut, vr), (hr, vr), (hr, vt - ch),
               (hr - ch, vt), (-hr + ch, vt), (-hr, vt - ch), (-hr, vr), (-hw + cut, vr), (-hw, vr - cut), (-hw, vb + ch)]
    e, t = pl["edge"], pl["thickness"]
    rings = [[(q.x, q.y, z) for q in offset_outline(outline, d)] for d, z in ((0.0, -t), (0.0, -e), (0.3 * e, -0.3 * e),
                                                                              (e, 0.0))]
    face = atlas.panel_rect()
    box = (-face.w_m / 2, vb - 0.0005, face.w_m / 2, vb - 0.0005 + face.h_m)
    g.put(stack(uv, rings, "structure", top_uv=face, bottom_hidden=True), on_panel(0.0, 0.0), "front")
    # seams painted on the face: the centre column, the side columns, display A's raised plate
    to_face = lambda x, v: (x + face.w_m / 2, v - box[1])
    for x0, v0, x1, v1 in ((-0.305, vb + 0.008, -0.235, -0.050), (0.235, vb + 0.008, 0.305, -0.050),
                           (-0.09, vb + 0.008, 0.09, -0.012), (-0.25, -0.006, 0.25, vt - 0.008)):
        atlas.panel_seam(*to_face(x0, v0), *to_face(x1, v1))

    screens, lamps = [], []
    for name, d in DISPLAYS.items():
        gw, gh = d["glass"]
        v = panel_v(d["top_z"]) - gh / 2 if "top_z" in d else panel_v(d["z"])
        m = on_panel(d["x"], v)
        g.put(kit.bezel(gw, gh, BEZEL["frame"], d["corner_r"]), m, "front")
        for corner in bezel_corners(gw, gh, BEZEL["frame"], d["corner_r"]):
            g.put(kit.fastener(), m @ Matrix.Translation(corner), "front")
        keys_left, keys_right = d["keys"]
        dx = gw / 2 + BEZEL["frame"] + 3 * MM + 6.1 * MM
        pitch = {"A": 0.034, "B": 0.019}.get(name, 0.022)
        for side, legends in ((-1, keys_left), (1, keys_right)):
            n = len(legends)
            for i, legend in enumerate(legends):
                g.put(kit.key(legend), on_panel(d["x"] + side * dx, v + pitch * ((n - 1) / 2 - i)), "front")
        if name != "A":  # brightness and contrast knobs under the small displays, inside the 35 mm ring
            for sx in (-1, 1):
                g.put(kit.knob(), on_panel(d["x"] + sx * 0.030, v - gh / 2 - BEZEL["frame"] - 0.012), "front")
        screens.append((quad(m, gw, gh, BEZEL["screen_z"]), d["uv"]))
        if d["title"]:
            g.put(kit.placard(atlas.label(d["title"])), on_panel(d["x"], v + gh / 2 + BEZEL["frame"] + 0.006), "front")

    # Under display A: a row of mode push buttons.
    va = panel_v(DISPLAYS["A"]["top_z"]) - DISPLAYS["A"]["glass"][1] - BEZEL["frame"] - 0.016
    for i, legend in enumerate(("NAV", "A/A", "A/G", "RDR", "EO", "EW")):
        g.put(kit.indicator("lens_clear", legend), on_panel(-0.1125 + 0.045 * i, va), "front")

    # Centre column: standby attitude indicator with its knobs, the guarded MASTER ARM, EMER JETT.
    xc, sv = 0.0, va - 0.058
    sm = on_panel(xc, sv)
    g.put(kit.bezel(0.054, 0.054, 0.008, 0.004), sm, "front")
    for corner in bezel_corners(0.054, 0.054, 0.008, 0.004):
        g.put(kit.fastener(), sm @ Matrix.Translation(corner), "front")
    g.put(kit.placard(atlas.tile("standby"), lift=BEZEL["screen_z"], size=(0.054, 0.054)), sm, "front")
    for sx, text in ((-1, "CAGE"), (1, "BRT")):
        g.put(kit.knob(), on_panel(xc + sx * 0.044, sv - 0.012), "front")
        g.put(kit.placard(atlas.label(text)), on_panel(xc + sx * 0.044, sv - 0.031), "front")
    arm = on_panel(xc - 0.028, sv - 0.075)
    for piece in kit.toggle() + kit.guard():
        g.put(piece, arm, "front")
    g.put(kit.placard(atlas.label("ARM")), on_panel(xc - 0.054, sv - 0.075), "front")
    jett = on_panel(xc + 0.030, sv - 0.075)
    g.put(kit.placard(atlas.tile("hatch"), size=(0.030, 0.030)), jett, "front")
    g.put(kit.indicator("lens_red", "JETT"), jett, "front")
    g.put(kit.placard(atlas.label("EMER")), on_panel(xc + 0.030, sv - 0.101), "front")

    # Left column (the pilot's left, local -X): the master warning lamp, the gear lights stacked under it, the transit
    # lamp and the gear handle; below display A, the fuel gauge.
    xg = -0.288
    g.put(kit.placard(atlas.label("GEAR")), on_panel(xg, 0.098), "front")
    for i, legend in enumerate("NLR"):
        g.put(kit.indicator("lens_green", legend), on_panel(xg, 0.079 - 0.019 * i), "front")
    g.put(kit.indicator("lens_red"), on_panel(xg, 0.017), "front")
    plate = on_panel(xg, -0.040)
    g.put(stack(uv, [ring_rect(0.009, 0.030, 0.0), ring_rect(0.009, 0.030, 2 * MM)], "recess", bottom_hidden=True),
          plate, "front")
    base = on_panel(xg, -0.062, 2 * MM).translation  # the slot's DN end: the aircraft spawns gear down
    lever = frame(base, PANEL_UP, (PANEL_N * 0.85 - PANEL_UP * 0.5).normalized())
    g.put(stack(uv, [ring_circle(4 * MM, 0.0, 8), ring_circle(3.5 * MM, 0.045, 8)], "metal"), lever, "front")
    wheel = [ring_circle(18 * MM, 0.0, 16), ring_circle(18 * MM, 11 * MM, 16), ring_circle(16 * MM, 13 * MM, 16),
             ring_circle(7 * MM, 13 * MM, 16), ring_circle(6 * MM, 14 * MM, 16)]
    g.put(stack(uv, wheel, ["knurl", "knurl", "knurl", "metal"], top_uv="metal"),
          lever @ Matrix.Translation((0.0, 0.0, 0.040)), "front")
    g.put(kit.placard(atlas.label("UP")), on_panel(xg + 0.018, -0.014), "front")
    g.put(kit.placard(atlas.label("DN")), on_panel(xg + 0.018, -0.066), "front")
    g.put(kit.dial("dial_fuel", 0.030), on_panel(xg + 0.010, -0.140), "front")
    g.put(kit.placard(atlas.label("FUEL")), on_panel(xg + 0.010, -0.180), "front")
    for i, legend in enumerate(("FWD", "AFT")):
        g.put(kit.key(legend[0]), on_panel(xg - 0.002 + 0.024 * i, -0.200), "front")

    # Right column: the master caution lamp over the 2 x 4 caution panel; below display A, the clock and cabin
    # pressure gauges and the data plate.
    xk = 0.288
    g.put(stack(uv, [ring_rect(0.021, 0.042, 0.0), ring_rect(0.020, 0.041, 3 * MM)], "structure", bottom_hidden=True),
          on_panel(xk, 0.049), "front")
    for i, legend in enumerate(("FUEL", "HYD", "OIL", "GEN", "ENG", "FCS", "OXY", "ECS")):
        col, row = i % 2, i // 2
        g.put(kit.indicator("lens_amber", legend), on_panel(xk - 0.0095 + 0.019 * col, 0.079 - 0.020 * row, 3 * MM), "front")
    g.put(kit.placard(atlas.label("CAUTION")), on_panel(xk, 0.098), "front")
    g.put(kit.dial("dial_clock", 0.025), on_panel(xk, -0.032), "front")
    g.put(kit.knob(), on_panel(xk - 0.010, -0.072), "front")
    g.put(kit.dial("dial_cabin", 0.026), on_panel(xk - 0.003, -0.130), "front")
    g.put(kit.placard(atlas.label("CABIN")), on_panel(xk - 0.003, -0.166), "front")
    g.put(kit.placard(atlas.label("F-204\nICARUS II")), on_panel(xk - 0.010, -0.200), "front")

    # Panel perimeter fasteners.
    for x, v in ((-0.303, vb + 0.010), (0.303, vb + 0.010), (-0.18, vb + 0.010), (0.18, vb + 0.010),
                 (-0.248, vt - 0.010), (0.248, vt - 0.010), (-0.235, -0.105), (0.235, -0.105)):
        g.put(kit.fastener(), on_panel(x, v), "front")

    # The master warning and caution lamps at the panel's top corners, under the glare shield's lip: on its top they
    # would stand above the over-nose line.
    for x, text in ((-0.288, "WARN"), (0.288, "CAUT")):
        lm = on_panel(x, vr - 0.016)
        g.put(kit.indicator("lens_red" if text == "WARN" else "lens_amber", body="keyside"), lm, "front")
        lamps.append(lm)
        g.put(kit.placard(atlas.label(text)), on_panel(x, vr - 0.034), "front")

    # Glare shield, fasteners along its top.
    g.put(glare_shield(uv), None, "front")
    for s, x in ((3.14, 0.12), (3.14, -0.12), (3.26, 0.22), (3.26, -0.22), (3.34, 0.10), (3.34, -0.10), (3.46, 0.24),
                 (3.46, -0.24), (3.53, 0.14), (3.53, -0.14)):
        at, n = glare_top(s, x)
        g.put(kit.fastener(), frame(at, -Y, n), "front")

    # HUD: body sunk into the glare shield, posts and top bar, a control strip on the body's aft face.
    hud = LAYOUT["hud"]
    for piece in hud_body(uv):
        g.put(piece, None, "front")
    strip_z = hud["z0"] + 0.040
    for x, text in ((0.056, "SYM"), (-0.056, "BRT")):
        g.put(kit.knob(), frame(P(hud["s1"], x, strip_z), Z, Y), "front")
        g.put(kit.placard(atlas.label(text)), frame(P(hud["s1"], x, strip_z - 0.020), Z, Y), "front")
    for i in range(5):
        g.put(kit.key(str(i + 1)), frame(P(hud["s1"], 0.028 - 0.014 * i, strip_z), Z, Y), "front")
    for s, x in ((3.42, 0.055), (3.42, -0.055), (3.53, 0.055), (3.53, -0.055)):
        g.put(kit.fastener(), frame(P(s, x, hud["top_z"]), -Y, Z), "front")

    # Pedestal under the panel: the anti-ice and pitot heat toggles, then the lighting knobs.
    g.put(pedestal(uv), None, "front")
    on_pedestal = lambda t, x: frame(pedestal_face(t)[0] + Vector((x, 0.0, 0.0)), *pedestal_face(t)[1:])
    for t, row in ((0.16, (("ICE", 0.040), ("PITOT", -0.040))), (0.46, (("ANTI-SKID", 0.040), ("NWS", -0.040)))):
        for text, x in row:
            for piece in kit.toggle():
                g.put(piece, on_pedestal(t, x), "front")
            g.put(kit.placard(atlas.label(text)), on_pedestal(t + 0.13, x), "front")
    for x in (0.040, -0.040):
        g.put(kit.knob(), on_pedestal(0.80, x), "front")
    for x in (0.066, -0.066):
        g.put(kit.fastener(), on_pedestal(0.04, x), "front")
    return screens, lamps


def glare_shield(uv):
    """The hood over the panel: a crowned top rising to the lip, the lip's underside along the eye's sight line so
    display A's top shows under it, and a rear wall just ahead of the panel's front face."""
    g = LAYOUT["glare"]
    crown, floor = 0.006, 0.40
    sight = (EYE[2] - g["lip_under_z"]) / (EYE[0] - g["s1"])
    t = LAYOUT["panel"]["thickness"] + 0.002
    at = LAYOUT["panel"]["at"]

    def wall_s(z):
        return at[0] - (z - at[2]) * math.tan(TILT) - t / math.cos(TILT)
    z_meet = g["lip_under_z"]
    for _ in range(30):
        z_meet = g["lip_under_z"] - sight * (g["s1"] - wall_s(z_meet))
    top = [(g["s0"] + (g["s1"] - g["s0"]) * t, g["z0"] + (g["z1"] - g["z0"]) * t, True) for t in (0.0, 1 / 3, 2 / 3, 1.0)]
    profile = [(g["s0"], floor, False)] + top + [(g["s1"], g["lip_under_z"], False), (wall_s(z_meet), z_meet, False),
                                                 (wall_s(floor), floor, False)]
    rings = []
    for u in (-1.0, -0.92, -0.66, -0.33, 0.0, 0.33, 0.66, 0.92, 1.0):
        ring = []
        for s, z, top in profile:
            f = (s - g["s0"]) / (g["s1"] - g["s0"])
            w = g["half_width0"] + (g["half_width1"] - g["half_width0"]) * f
            ring.append(P(s, u * w, z - (crown * u * u if top else 0.0)))
        rings.append(ring)
    k = len(profile)
    verts = [p for r in rings for p in r]
    faces = [(j * k + i, j * k + (i + 1) % k, (j + 1) * k + (i + 1) % k, (j + 1) * k + i)
             for j in range(len(rings) - 1) for i in range(k)]
    faces += [tuple(range(k))[::-1], tuple((len(rings) - 1) * k + i for i in range(k))]
    # its two ends face the sidewalls, unseen, and their n-gons would triangulate into slivers
    return solid(uv, verts, faces, "structure", along=X, hidden=(len(faces) - 2, len(faces) - 1))


def coaming(g, uv, space, group):
    """A dark tray under the windscreen, from the glare shield forward to the windscreen's front, closing the view into
    the nose bay: the canopy's cut runs on forward under the glass, so below the skin line the eye saw the bay's frames
    and the radome from inside. The deck stays under the 16 deg over-nose line with the glare shield's margin; its
    sides run up the inner skin to the glass's foot, and its front wall up to the skin's line at the windscreen's
    front, so nothing above that line changes."""
    s0, s1, inset = LAYOUT["coaming"]
    gl = LAYOUT["glare"]
    stations = bi.spaced(s0, s1, 7)
    deck = lambda s: min(over_nose_z(s) - LAYOUT["over_nose_margin"], gl["z0"])
    # the sides stop at the glass's foot (PROFILE's bottom, 2 cm under its widest point, where its lip turns in under
    # the skin), clear of the windscreen's base rails and the hood's longerons
    foot = [row[3] for row in bi.resample(canopy.PROFILE, stations)]
    rows = []
    for s, top in zip(stations, foot):
        z0 = deck(s)
        side = [(space.skin_x(s, z, inset), z) for z in bi.spaced(top, z0, 4)]
        w = side[-1][0]
        across = [(w * f, z0) for f in bi.spaced(1, -1, 7)[1:-1]]
        rows.append([P(s, x, z) for x, z in side] + [P(s, x, z) for x, z in across]
                    + [P(s, -x, z) for x, z in side[::-1]])
    g.put(grid_sheet(uv, rows, "structure", along=X), None, group)
    # the front wall: the first section, filled up to 5 mm over the skin's line over the top, so the look that grazes
    # the nose (7 deg) cannot slip under it
    s, first = stations[0], rows[0]
    over, under = (space.internals.ring_at(space.p, s, d) for d in (-0.005, inset))
    arc = [o if abs(o.x) < 0.12 else u for o, u in zip(over, under) if u.z > foot[0]]
    arc.sort(key=lambda v: -math.atan2(v.x, v.z - foot[0]))
    arc = [first[0]] + [P(s, v.x, v.z) for v in arc] + [first[-1]]
    run = [0.0]
    for a, b in zip(arc, arc[1:]):
        run.append(run[-1] + (b - a).length)
    top = []
    for i in range(len(first)):
        t = run[-1] * i / (len(first) - 1)
        k = min(max(j for j in range(len(run)) if run[j] <= t), len(arc) - 2)
        f = (t - run[k]) / max(run[k + 1] - run[k], 1e-9)
        top.append(arc[k].lerp(arc[k + 1], f))
    g.put(grid_sheet(uv, [first, top], "structure", along=X), None, group)


def glare_top(s, x):
    """A point on the glare shield's top and the top's normal there."""
    g = LAYOUT["glare"]
    f = (s - g["s0"]) / (g["s1"] - g["s0"])
    w = g["half_width0"] + (g["half_width1"] - g["half_width0"]) * f
    slope = (g["z1"] - g["z0"]) / (g["s1"] - g["s0"])
    z = g["z0"] + (g["z1"] - g["z0"]) * f - 0.006 * (x / w) ** 2
    return P(s, x, z), Vector((0.0, -slope, 1.0)).normalized()


def hud_body(uv):
    """The HUD's body sunk into the glare shield. The game draws the HUD as a screen-space overlay (Cockpit rule 18),
    so no combiner is modelled: its posts and glass framed nothing and stood in the view ahead."""
    h = LAYOUT["hud"]
    hw, c = h["half_width"], 0.01
    section = [(hw, h["z0"]), (hw, h["top_z"] - c), (hw - c, h["top_z"]), (-hw + c, h["top_z"]), (-hw, h["top_z"] - c),
               (-hw, h["z0"])]
    return [loft_piece(uv, [[P(s, x, z) for x, z in section] for s in (h["s0"], h["s1"])], "structure", along=X)]


def pedestal(uv):
    pd, floor = LAYOUT["pedestal"], LAYOUT["floor_z"]
    top = LAYOUT["panel"]["z0"] - 0.004
    profile = [(pd["s0"], floor), (pd["s1"], floor), (pd["s1"], 0.12), (pd["s0"] + 0.045, top), (pd["s0"], top)]
    return loft_piece(uv, [[P(s, x, z) for s, z in profile] for x in (-pd["half_width"], pd["half_width"])], "console",
                      along=X)


def pedestal_face(t):
    """Placement on the pedestal's sloping face, t from 0 at its top to 1 at its foot: (point, up, normal)."""
    pd = LAYOUT["pedestal"]
    a = P(pd["s0"] + 0.045, 0.0, LAYOUT["panel"]["z0"] - 0.004)
    b = P(pd["s1"], 0.0, 0.12)
    down = (b - a).normalized()
    normal = Vector((0.0, -down.z, down.y))
    if normal.y < 0:
        normal = -normal
    return a + (b - a) * t, -down, normal


# Console sub-panels, front to back: (title, s0, s1, controls); a control is (kind, ds, dx, legend), ds aft of the
# plate's centre, dx outboard of the console's centre line. The stick and the throttle stand in their own plates.
CONSOLES = {
    1: [("FUEL", 4.07, 4.21, [("button", -0.035, -0.035, "BST"), ("button", -0.035, 0.035, "XFD"),
                              ("knob", 0.030, 0.0, "DUMP")]),
        ("EXT LT", 4.23, 4.39, [("knob", -0.035, -0.035, "POS"), ("knob", -0.035, 0.035, "FORM"),
                                ("button", 0.035, 0.0, "BCN")]),
        ("COMM", 4.41, 4.61, [("knob", -0.055, -0.035, "VOL"), ("knob", -0.055, 0.035, "CHAN"),
                              ("window", 0.005, 0.0, "251.00"), ("key", 0.055, -0.027, "1"), ("key", 0.055, -0.009, "2"),
                              ("key", 0.055, 0.009, "3"), ("key", 0.055, 0.027, "4")]),
        ("DATA", 4.63, 4.80, None)],
    -1: [("ELEC", 4.07, 4.23, [("toggle", -0.035, -0.035, "BATT"), ("toggle", -0.035, 0.035, "GEN"),
                               ("button", 0.035, 0.0, "EMER")]),
         ("ECS", 4.25, 4.39, [("knob", -0.030, 0.0, "TEMP"), ("button", 0.035, -0.035, "RAM"),
                              ("button", 0.035, 0.035, "DEFOG")]),
         ("OXY", 4.41, 4.57, [("knob", -0.035, 0.0, "REG"), ("blinker", 0.035, -0.035, "FLOW"),
                              ("button", 0.035, 0.035, "100")]),
         ("INT LT", 4.59, 4.78, [("knob", -0.040, -0.035, "CSL"), ("knob", -0.040, 0.035, "INST"),
                                 ("knob", 0.040, 0.0, "FLOOD")])],
}
PLATE_WIDTH = 0.150
LEGEND_AFT = {"toggle": 0.020, "guarded": 0.030, "knob": 0.020, "key": 0.011, "blinker": 0.016, "button": 0.016}


def console_x(space, side, s):
    """(inner, centre, outer) |x| of the console at s: the inner edge clear of the seat, the outer on the lining."""
    inner = LAYOUT["console"]["inner"]
    outer = space.wall_x(s, LAYOUT["console"]["top_z"]) - 0.002
    return inner, (inner + outer) / 2, outer


def consoles(g, uv, kit, atlas, space):
    c = LAYOUT["console"]
    top, floor = c["top_z"], LAYOUT["floor_z"]
    for side in (1, -1):
        # the body: a lofted box following the lining, its top level; the inner wall faces the seat
        stations = bi.spaced(c["s0"], c["s1"], 5)
        rings = []
        for s in stations:
            inner, _, _ = console_x(space, side, s)
            mid = (floor + top) / 2
            x_floor, x_mid, x_top = (space.wall_x(s, z) - 0.002 for z in (floor + 0.01, mid, top))
            rings.append([P(s, side * q, z) for q, z in ((inner, floor), (x_floor, floor), (x_mid, mid), (x_top, top),
                                                         (inner, top), (inner, mid))])
        g.put(loft_piece(uv, rings, lambda i: "structure", along=Y), None, "console")
        # the top skin in one strip of console paint, and its plates
        for title, s0, s1, controls in CONSOLES[side]:
            sub_panel(g, uv, kit, atlas, space, side, title, s0, s1, controls)
        if side > 0:
            throttle_quadrant(g, uv, kit, atlas, space)
        else:
            stick_base(g, uv, kit, atlas, space)


def sub_panel(g, uv, kit, atlas, space, side, title, s0, s1, controls):
    """A Dzus plate 3 mm proud of the console top, two fasteners at opposite corners, its controls and legends."""
    _, cx, _ = console_x(space, side, (s0 + s1) / 2)
    top = LAYOUT["console"]["top_z"] + 0.003
    hw = PLATE_WIDTH / 2
    sc = (s0 + s1) / 2
    g.put(block(uv, s0, s1, side * (cx - hw), side * (cx + hw), top - 0.004, top, lambda i: "console" if i == 1 else "metal"),
          None, "console")
    g.put(kit.placard(atlas.label(title)), on_top(s0 + 0.010, side * cx, top), "console")
    for s, dx in ((s0 + 0.008, -hw + 0.008), (s1 - 0.008, hw - 0.008)):
        g.put(kit.fastener(), on_top(s, side * (cx + dx), top), "console")
    for kind, ds, dx, legend in controls or ():
        s, x = sc + ds, side * (cx + dx)
        if kind == "window":  # a recessed readout
            rect = atlas.label(legend, ink="lens_red", paper="recess", cell=(44, 13))
            g.put(block(uv, s - 0.0065, s + 0.0065, x - 0.016, x + 0.016, top, top + 0.003, lambda i: "recess"), None,
                  "console")
            g.put(kit.placard(rect), on_top(s, x, top + 0.003), "console")
            continue
        m = on_top(s, x, top)
        if kind in ("toggle", "guarded"):
            for piece in kit.toggle() + (kit.guard() if kind == "guarded" else []):
                g.put(piece, m, "console")
        elif kind == "knob":
            g.put(kit.knob(), m, "console")
        elif kind == "key":
            g.put(kit.key(legend), m, "console")
            continue
        elif kind == "blinker":
            g.put(kit.indicator("lens_green", body="keyside"), m, "console")
        elif kind == "button":
            g.put(kit.indicator("lens_clear", legend[:4]), m, "console")
            continue
        g.put(kit.placard(atlas.label(legend)), on_top(s + LEGEND_AFT[kind], x, top), "console")


def throttle_quadrant(g, uv, kit, atlas, space):
    """The plate the stock throttle stands over, its slot through the grip's travel, the detents and the friction
    knob."""
    st = STOCK["throttle"][0][:4] + (STOCK["throttle"][0][4], STOCK["throttle"][-1][5])
    s0, s1 = LAYOUT["console"]["s0"] + 0.006, 4.05
    inner, cx, outer = console_x(space, 1, (s0 + s1) / 2)
    z0 = LAYOUT["console"]["top_z"]
    z1 = z0 + 0.004
    travel = (st[4] - STOCK["throttle_pivot"][2]) * math.sin(math.radians(STOCK["throttle_deg"]))
    a, b = st[0] - travel - 0.010, st[1] + 0.006
    xs0, xs1 = (st[2] + st[3]) / 2 - 0.012, (st[2] + st[3]) / 2 + 0.012
    for q in ((s0, a, inner, outer), (b, s1, inner, outer), (a, b, inner, xs0), (a, b, xs1, outer)):
        g.put(block(uv, q[0], q[1], q[2], q[3], z0, z1, lambda i: "console" if i == 1 else "metal"), None, "console")
    for ds, name in ((a + 0.004, "AB"), (b - 0.024, "IDLE")):
        g.put(block(uv, ds, ds + 0.020, xs0 - 0.014, xs0 - 0.001, z1, z1 + 0.006, lambda i: "metal"), None, "console")
        g.put(kit.placard(atlas.label(name)), on_top(ds + 0.010, xs0 - 0.030, z1), "console")
    for s, x in ((s0 + 0.008, inner + 0.008), (s1 - 0.008, outer - 0.008)):
        g.put(kit.fastener(), on_top(s, x, z1), "console")
    knob = (b + 0.024, inner + 0.030)
    g.put(kit.knob(), on_top(knob[0], knob[1], z1), "console")
    g.put(kit.placard(atlas.label("FRICT")), on_top(knob[0] + LEGEND_AFT["knob"], knob[1], z1), "console")


def stick_base(g, uv, kit, atlas, space):
    """The plate the stock side stick stands on, with an arm rest behind it and a trim panel ahead."""
    s0, s1 = LAYOUT["console"]["s0"] + 0.006, 4.05
    inner, cx, outer = console_x(space, -1, (s0 + s1) / 2)
    z0 = LAYOUT["console"]["top_z"]
    g.put(block(uv, s0, s1, -outer, -inner, z0, z0 + 0.004, lambda i: "console" if i == 1 else "metal"), None, "console")
    for s, x in ((s0 + 0.008, inner + 0.008), (s1 - 0.008, outer - 0.008)):
        g.put(kit.fastener(), on_top(s, -x, z0 + 0.004), "console")
    g.put(kit.placard(atlas.label("TRIM")), on_top(s0 + 0.012, -(inner + 0.030), z0 + 0.004), "console")
    g.put(kit.knob(), on_top(s0 + 0.036, -(inner + 0.030), z0 + 0.004), "console")


def ledge_rows(space, side, columns):
    """The sill ledge along one side: (s, |x| in, |x| out, top z) per station, from the lining's top out to just inside
    the shut hood, LEDGE_DROP under the glass seam; the hood's longeron comes down over the gap, P5's fixed-sill flange
    stands behind it. The ledge stays under every place the hood's vertices pass through as it opens, then is pulled in
    and down a segment at a time until the swept hood's faces clear it."""
    rows = []
    for s in columns:
        sx, sz = space.seam(s)
        top = sz - LEDGE_DROP
        for _ in range(2):
            x_in = space.wall_x(s, top - 0.030)
            x_out = min(sx - 0.004, min(space.hood_x(s, z, side) for z in bi.spaced(top - 0.035, top + 0.005, 4)) - 0.008)
            x_out = max(x_out, x_in + 0.010)
            top = min(sz - LEDGE_DROP, space.sweep_floor(s, side * x_in, side * x_out) - 0.008)
        rows.append([s, x_in, x_out, top])
    for _ in range(40):
        hits = [i for i in range(len(rows) - 1) if space.swept.overlap(ledge_tree(rows[i:i + 2], side))]
        if not hits:
            break
        for i in set(hits) | {i + 1 for i in hits}:
            rows[i][2] = max(rows[i][1] + 0.010, rows[i][2] - 0.003)
            rows[i][3] -= 0.004
    else:
        raise ValueError("cockpit: the sill ledge cannot clear the opening hood at s %.2f" % rows[hits[0]][0])
    return [tuple(r) for r in rows]


def ledge_tree(rows, side):
    """A BVH of the ledge between two rows, a hair inside its faces."""
    verts, polys = [], []
    for s, x_in, x_out, top in rows:
        verts += [P(s, side * q, z) for q, z in ((x_in + 0.001, top - 0.029), (x_in + 0.001, top - 0.001),
                                                 (x_out - 0.001, top - 0.001), (x_out - 0.001, top - 0.029))]
    polys = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]
    return BVHTree.FromPolygons(verts, polys)


def tub(g, uv, kit, atlas, space):
    """Lining sheets on both walls up to the sill ledge, the ledge itself, frame ribs, wiring looms, the floor, the
    footwell's front wall and kick panels, the rear bulkhead, the rudder pedals."""
    floor = LAYOUT["floor_z"]
    s_front, s_back = LAYOUT["footwell_s"], LAYOUT["bulkhead"][0]
    columns = bi.spaced(s_front, s_back, 16)
    for side in (1, -1):
        rows = ledge_rows(space, side, columns)
        rings = [[P(s, side * q, z) for q, z in ((x_in, top - 0.030), (x_in, top), (x_out, top), (x_out, top - 0.030))]
                 for s, x_in, x_out, top in rows]
        g.put(loft_piece(uv, rings, "structure", along=Y), None, "tub")
        # the lining, in cells from the floor to the ledge
        heights = (0.0, 0.25, 0.5, 0.75, 1.0)
        grid = [[P(s, side * space.wall_x(s, floor + (top - 0.030 - floor) * f), floor + (top - 0.030 - floor) * f)
                 for s, _, _, top in rows] for f in heights]
        g.put(grid_sheet(uv, grid, "lining", along=Y), None, "tub")
        for rs in LAYOUT["ribs"]:
            top = float(np.interp(rs, [r[0] for r in rows], [r[3] for r in rows])) - 0.032
            # over a console the rib starts above the throttle and the stick
            z0 = 0.47 if LAYOUT["console"]["s0"] < rs < LAYOUT["console"]["s1"] else floor
            pts = [(space.wall_x(rs, z), z) for z in bi.spaced(z0, top, 4)]
            rings = [[P(rs + ds, side * x, z) for x, z in pts] + [P(rs + ds, side * (x - 0.026), z) for x, z in pts[::-1]]
                     for ds in (-0.0165, 0.0165)]
            g.put(loft_piece(uv, rings, "structure", along=Z), None, "tub")
            for z in (z0 + 0.04, top - 0.03):
                x = space.wall_x(rs, z) - 0.026
                g.put(kit.fastener(), frame(P(rs, side * x, z), Z, Vector((-side, 0.0, 0.0))), "tub")
        # two wiring looms along the lining under the ledge, in the footwell and aft of the throttle and stick
        for s0, s1 in ((s_front + 0.05, 3.70), (4.07, s_back - 0.03)):
            for drop in (0.020, 0.045):
                pts = []
                for s in bi.spaced(s0, s1, 4):
                    top = float(np.interp(s, [r[0] for r in rows], [r[3] for r in rows])) - 0.030
                    z = top - drop
                    pts.append(P(s, side * (space.wall_x(s, z) - 0.014), z))
                g.put(tube(uv, pts, 0.011, 6, "knurl"), None, "tub")
        breakers(g, uv, kit, atlas, space, side)
    # the floor in tread cells, the footwell wall, kick panels
    xs = bi.spaced(-1, 1, 6)
    grid = []
    for s in bi.spaced(s_front, s_back, 13):
        w = space.wall_x(s, floor + 0.005)
        grid.append([P(s, f * w, floor) for f in xs])
    g.put(grid_sheet(uv, grid, "floor", along=X), None, "tub")
    zs = bi.spaced(floor, 0.45, 5)
    wall = [[P(s_front, f * space.wall_x(s_front, z), z) for f in xs] for z in zs]
    g.put(grid_sheet(uv, wall, "lining", along=X), None, "tub")
    pl = LAYOUT["panel"]
    top_z = pl["z0"] - 0.014
    top_s = pl["at"][0] + (pl["at"][2] - top_z) * math.tan(TILT)
    for side in (1, -1):
        foot = [P(3.50, side * q, floor) for q in bi.spaced(0.20, space.wall_x(3.50, floor) - 0.003, 3)]
        head = [P(top_s, side * q, top_z) for q in bi.spaced(0.26, space.wall_x(top_s, top_z) - 0.003, 3)]
        g.put(grid_sheet(uv, [foot, [a.lerp(b, 0.5) for a, b in zip(foot, head)], head], "lining", along=Y), None, "tub")
    # the rear bulkhead behind the seat, up to the ledge line, and the deck aft of it under the hood's tail, closing
    # the cockpit back to the aft bow at the seam line
    s0, s1 = LAYOUT["bulkhead"]
    sx, sz = space.seam(s0)
    fs = bi.spaced(-1, 1, 7)
    rows = []
    for t in bi.spaced(0.0, 1.0, 5):
        rows.append([P(s0, f * (space.wall_x(s0, floor) * (1 - t) + (sx - 0.020) * t),
                       floor + (sz - 0.025 + 0.05 * (1 - f * f) - floor) * t) for f in fs])
    g.put(grid_sheet(uv, rows, "lining", along=X), None, "tub")
    deck = []
    for s in bi.spaced(s0, 5.03, 3):
        sx, sz = space.seam(s)
        deck.append([P(s, f * (sx - 0.020), sz - 0.025 + 0.05 * (1 - f * f)) for f in fs])
    g.put(grid_sheet(uv, deck, "structure", along=X), None, "tub")
    for f in (-0.6, 0.6):
        for z in (0.30, 0.55):
            g.put(kit.fastener(), frame(P(s0, f * 0.30, z), Z, -Y), "tub")
    pedals(g, uv, kit)


def breakers(g, uv, kit, atlas, space, side):
    """A circuit-breaker panel low on each footwell wall: a plate, four rows of six breakers and their legends."""
    s0, s1, z0, z1 = 3.16, 3.54, 0.03, 0.25
    sc, zc = (s0 + s1) / 2, (z0 + z1) / 2
    inward = Vector((-side, 0.0, 0.0))
    at = lambda s, z, lift=0.0: P(s, side * (space.wall_x(s, z) - 0.004 - lift), z)
    corners = [at(s, z) for s in (s0, s1) for z in (z0, z1)]
    outer = [corners[0], corners[1], corners[3], corners[2]]
    g.put(loft_piece(uv, [outer, [p + inward * 0.004 for p in outer]], "console", along=Y), None, "tub")
    for r, title in enumerate(("PRI", "SEC", "AUX", "ARM")):
        z = z1 - 0.030 - 0.048 * r
        for i in range(6):
            s = s0 + 0.045 + 0.058 * i
            g.put(kit.breaker(), frame(at(s, z, 0.004), Z, inward), "tub")
        g.put(kit.placard(atlas.label(title)), frame(at(s0 + 0.012, z, 0.004), Z, inward), "tub")


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


def slab_piece(uv, outer, inner, spec, along=None):
    """A closed slab between two grids of points (rows by columns)."""
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
    return solid(uv, verts, faces, spec, along=along)


def hood_frame_inner(uv, kit, glass, proxy=False):
    """The hood's inner frame (Cockpit rule 32): a shell of three bows and two longerons over the hood frame's own
    members, the glass_inset in from the inner glass, then fasteners and the canopy lock handle. proxy: the shell
    alone, coarser, for the exterior stand-in."""
    g = Gather("canopy_frame_proxy" if proxy else "canopy_frame_inner")
    a, u = hood_planes()
    d0, d1 = FRAME["glass_inset"], FRAME["glass_inset"] + FRAME["depth"]
    cols = 9 if proxy else 25
    # each bow a ridged band: its middle row stands deeper than its edges
    bows = [(canopy.joint(a, u, 0.002), canopy.joint(a, u, 0.0235), canopy.joint(a, u, 0.045)),
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
        g.put(slab_piece(uv, outer, inner, "frame"), None, "frame")
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
        g.put(slab_piece(uv, rows_o, rows_i, "frame"), None, "frame")
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


def windscreen_frame_inner(uv, kit, glass):
    """The windscreen's inner frame: its arch just ahead of the joint and its two posts, over the outer frame's
    members, with fasteners."""
    g = Gather("windscreen_frame_inner")
    a, u = hood_planes()
    d0, d1 = FRAME["glass_inset"], FRAME["glass_inset"] + FRAME["depth"]
    f0, fm, f1 = canopy.joint(a, u, -0.042), canopy.joint(a, u, -0.022), canopy.joint(a, u, -0.002)
    left, right = glass.seam(f0, 1), glass.seam(f0, -1)
    r = canopy.glass_at(glass.tree, f0, left)[2]
    outer, inner = member(glass, (f0, fm, f1), bi.spaced(left - 0.004 / r, right + 0.004 / r, 25), d0,
                          (d1, d1 + 0.010, d1))
    g.put(slab_piece(uv, outer, inner, "frame"), None, "frame")
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
        g.put(slab_piece(uv, rows_o, rows_i, "frame"), None, "frame")
        # the base rail along the windscreen's foot, over the outer frame's
        rows_o, rows_i = [], []
        for s in bi.spaced(2.40, 2.93, 6):
            f = canopy.station(s)
            seam = glass.seam(f, side)
            r = canopy.glass_at(glass.tree, f, seam)[2]
            psis = [seam, seam - side * 0.032 / r]
            rows_o.append([glass.at(f, q, d0) for q in psis])
            rows_i.append([glass.at(f, q, d1) for q in psis])
        g.put(slab_piece(uv, rows_o, rows_i, "frame"), None, "frame")
        for s in bi.spaced(2.6, under_arch - 0.06, 2):
            f = canopy.station(s)
            at0, at1 = glass.at(f, side * psi, d1), glass.at(f, side * psi, d0)
            g.put(kit.fastener(), frame(at0, Y, at0 - at1), "hardware")
    for p in bi.spaced(left - 0.08, right + 0.08, 5):
        at0, at1 = glass.at(fm, p, d1 + 0.010), glass.at(fm, p, d0)
        g.put(kit.fastener(), frame(at0, fm[2], at0 - at1), "hardware")
    return g


# --- proxies, screens, lamps ---------------------------------------------------------------------------------------

def cockpit_proxy(uv, space):
    """The interior's exterior stand-in on Matte_black: the front office, the consoles, the walls, floor and
    bulkhead, coarse."""
    g = Gather("cockpit_proxy")
    floor = LAYOUT["floor_z"]
    g.put(glare_shield(uv), None, "proxy")
    pl = LAYOUT["panel"]
    vb, vt = panel_v(pl["z0"]), panel_v(pl["z1"])
    g.put(stack(uv, [ring_rect(pl["half_width"], (vt - vb) / 2, -pl["thickness"]),
                     ring_rect(pl["half_width"], (vt - vb) / 2, 0.0)], "structure"),
          on_panel(0.0, (vt + vb) / 2), "proxy")
    c = LAYOUT["console"]
    columns = bi.spaced(LAYOUT["footwell_s"], LAYOUT["bulkhead"][0], 16)
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
        g.put(grid_sheet(uv, grid, "lining"), None, "proxy")
    grid = [[P(s, f * space.wall_x(s, floor), floor) for f in bi.spaced(-1, 1, 7)] for s in columns]
    g.put(grid_sheet(uv, grid, "floor"), None, "proxy")
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
    coaming(g, uv, space, "proxy")
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


def warning_lamps(uv, lamps):
    """The master warning and caution lenses, set into their bodies on the glare shield: 22 tris each."""
    g = Gather(WARNING_LAMPS)
    w, d, h = 17.1 * MM - 4 * 1.15 * MM, 16.4 * MM - 4 * 1.15 * MM, 9.5 * MM
    flat = cockpit_atlas.Rect(0.0, 0.0, 1.0, 1.0, 1.0, 1.0)
    for m in lamps:
        rings = [ring_rect(w / 2, d / 2, h - 1.2 * MM, 1.5 * MM, 1), ring_rect(w / 2, d / 2, h + 0.4 * MM, 1.5 * MM, 1)]
        g.put(stack(lambda spec, pts, box=None, along=None: rect_uvs(pts, flat), rings, flat, bottom_hidden=True), m,
              "lamp")
    return g


# --- build ---------------------------------------------------------------------------------------------------------

def build(p, mats):
    """Build the cockpit's renderers and pivots under cockpit_cell and the canopy hinge. Runs after parts.organise:
    the cockpit hangs from the organised part tree. Returns the new objects."""
    O = bpy.data.objects
    space = Space(p)
    atlas = cockpit_atlas.Atlas()
    uv = UV(atlas)
    kit = Kit(uv, atlas)
    mat = bpy.data.materials.get(SLOT) or materials.material(SLOT, (0.33, 0.34, 0.35, 1.0), 0.0, 0.6)

    glass = Glass(space)
    hood_inner = hood_frame_inner(uv, kit, glass)
    windscreen_inner = windscreen_frame_inner(uv, kit, glass)
    frame_proxy = hood_frame_inner(uv, kit, glass, proxy=True)
    space.hood_sweep([hood_inner, frame_proxy])
    interior = Gather(INTERIOR)
    screens, lamps = front_office(interior, uv, kit, atlas)
    coaming(interior, uv, space, "front")
    consoles(interior, uv, kit, atlas, space)
    tub(interior, uv, kit, atlas, space)
    proxy = cockpit_proxy(uv, space)
    screen = tac_screen(screens)
    lamp = warning_lamps(uv, lamps)
    atlas.write(os.path.join(REPO, "art", "export", "textures"))
    LAST["atlas"], LAST["groups"] = atlas, {k: interior.tris(k) for k in GROUPS}
    LAST["frame_shell"] = hood_inner.tris("frame")

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
    print("cockpit: interior %d (front %d, consoles %d, tub %d), hood frame %d, windscreen frame %d, screen %d, "
          "lamps %d, proxies %d + %d" % (interior.tris(), *[interior.tris(k) for k in GROUPS], hood_inner.tris(),
                                         windscreen_inner.tris(), screen.tris(), lamp.tris(), proxy.tris(),
                                         frame_proxy.tris()))
    return made


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
    pos, tris, uv, area, _ = mesh_arrays(O[INTERIOR])
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
    out["swatch_at"] = [tuple(round(q, 3) for q in sxz(Vector(pos[tris[i]].mean(0)))) for i in flat[:4]]
    key = Counter(tuple(np.round(np.sort(t.reshape(-1)), 4)) for t in uv[ua > 1e-10])
    out["repeated_uv_tris"] = int(sum(c for c in key.values() if c > 1))
    # the panel face: triangles mapped into the panel's unique region
    x0, y0, pw, ph = cockpit_atlas.PANEL
    in_panel = (uv[:, :, 0].min(1) >= x0 / cockpit_atlas.W - 1e-6) & (uv[:, :, 0].max(1) <= (x0 + pw) / cockpit_atlas.W + 1e-6) \
        & (uv[:, :, 1].min(1) >= 1 - (y0 + ph) / cockpit_atlas.H - 1e-6)
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
    top_z = DISPLAYS["A"]["top_z"]
    fwd = (EYE[0] - LAYOUT["panel"]["at"][0])
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
    band("display_width", a["size"][0])

    # the glare shield and everything on it under the over-nose line
    pos, tris, _, _, _ = mesh_arrays(O[INTERIOR])
    gl = LAYOUT["glare"]
    on_glare = [Vector(p) for p in pos if gl["s0"] - 0.001 <= p[1] + bi.S0 <= gl["s1"] + 0.001 and abs(p[0]) > LAYOUT["hud"]["half_width"] + 0.01]
    high = [v for v in on_glare if v.z > over_nose_z(v.y + bi.S0) - LAYOUT["over_nose_margin"]]
    if high:
        v = max(high, key=lambda v: v.z - over_nose_z(v.y + bi.S0))
        problems.append("glare shield above the over-nose line at s %.3f x %.3f z %.3f" % sxz(v))

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
            problems.append("display %s: %d of 25 eye rays blocked" % ("ABC"[k], blocked))

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
    centre = on_panel(0.0, -0.03).translation
    shoot("panel", centre + PANEL_N * 0.62, centre, fov=70, up=PANEL_UP)
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
    top = DISPLAYS["A"]["top_z"] - EYE[2]
    fwd = EYE[0] - LAYOUT["panel"]["at"][0]
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
    shoot("checker_panel", centre + PANEL_N * 0.62, centre, fov=70, up=PANEL_UP)
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
