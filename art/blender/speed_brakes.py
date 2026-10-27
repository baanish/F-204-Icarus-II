"""Speed brakes as on the F-104: a flush panel low on each side of the aft fuselage, hinged at its front edge and
opening outward on the stock Airbrake, with the well it covers and a hydraulic ram between frame 13.0 and the panel.

PARAMS["speed_brake"] places the panel: its own skin panel, its edges on the skin's panel lines (art/textures/panels.py)
and on the fuselage loft's own stations and ring columns, so the hole is whole skin faces and the panel's outer face
lies on them. The parts follow the stock aircraft (the FS-12 Revoker's panel and well, the VTOLTrainer1's actuator):

- speed_brake_<side>_visible, the panel: skin on its outer face and edges; on jet_mechanical a tray inside, with a
  rim, two stringers, a rib across it under the actuator's fitting (a clevis of two gussets), and two hinge knuckles.
- speed_brake_well_lip_<side>: skin down the hole's edges, joined into the skin_aft panel (merge_into), so the hairline
  seam round the shut panel shows skin on both faces.
- speed_brake_well_<side>: the closed well behind it, its walls and floor on the opaque dark Icarus_Duct (a wall this
  size on jet_mechanical would reach the stock texture's lightening holes and show sky), and the channel down its
  floor that the cylinder lies in shut, down to the anchor fitting on frame 13.0 (Patch.channel). Its airframe stands
  on them a step lighter, on Icarus_WellDetail: ribs with rivet rows, two hydraulic lines and the anchor fitting
  (well_detail); the fixed hinge knuckles and the fitting's pin heads are on jet_mechanical. It joins the
  fuselage_aft core (merge_into) and faces inward; clear_wells cuts the core's frames and stringers back from it.
- speed_brake_<side>_cylinder on fuselage_aft and speed_brake_<side>_rod on the hinge: the actuator, each with its
  origin at its eye and local Y along its axis toward the other's eye. The game turns only the hinge, so in Unity
  each aims at the other's eye with an AimConstraint that the Airbrake enables while the brakes are open, as the
  stock VTOLTrainer1 aims its piston (IcarusAuthor.Aero.cs BuildSpeedBrakes). aim_actuators() poses them the same
  way here, and check() opens the brakes with them.

The hinge axis lies just outboard of the front edge's outermost point. The front edge is curved round the fuselage
and the axis is straight, so every other point of the panel and of the hole's front edge lies inside the axis:
opening, the panel's front edge only moves aft and out, and the seam can stay a hairline all round. The knuckles on
that axis stand a few millimetres proud of the skin, as a piano hinge's do.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
import numpy as np

import build_icarus as bi
import checks

# The panel, its well and its actuator, in metres.
SHAPE = {
    "gap": 0.0025,  # panel to the hole's edges all round
    "hinge_ahead": 0.001,  # hinge axis ahead of the panel's front edge
    "hinge_lift": 0.001,  # and outboard of the outermost point of the hole's and the panel's front edges
    "lip": 0.025,  # skin down the hole's edges
    "knuckle": 0.035,  # each hinge this far along it from the actuator, where the skin is within 2 mm of the axis
    "knuckle_r": 0.005,
    "knuckle_length": 0.02,  # the panel's knuckle; a fixed one either side of it
    "bracket_length": 0.012,
    "frame_depth": 0.020,  # the panel's edges, rim and ribs, below its outer face
    "sheet_depth": 0.004,  # the panel's inner sheet between them
    "rim": 0.025,
    "tip_rim": 0.045,  # the free edge's rim, wider
    "rib": 0.012,  # the stringers' width
    "stringer": 0.085,  # each stringer this far from the actuator
    "well_floor": 0.07,  # the well's floor inside the hole's upper and lower edges
    # The actuator, in its plane across the hinge (a aft of the hinge axis, n out from it). The cylinder's eye sits deep
    # in the fuselage on a fitting on frame 13.0, the well's front wall, in a channel below the well floor, and the
    # rod's on a fitting across the panel's inner face: the ram pushes out and aft across the hinge line, so it holds a
    # moment arm of 0.12 m or more (least_arm) all the way open. The anchor's depth sets the arm: the engine, 0.21 m in
    # at the frame, bounds it.
    "anchor": (0.045, -0.175),
    "bracket": 0.38,  # the rod's eye this far aft of the hole's front edge, on the actuator's plane
    "eye_depth": 0.085,  # and this far below the panel's outer face: deeper and it meets the well floor shut
    "bracket_rib": 0.024,  # the panel's rib under the fitting, across it
    "channel": 0.05,  # half the width of the channel the cylinder lies in
    "channel_clear": 0.008,  # the channel's walls this far from the barrel shut and from the anchor fitting
    "barrel_r": 0.022,
    "barrel_start": 0.032,  # from the cylinder's eye
    "rod_r": 0.009,
    "engage": 0.03,  # least length of rod inside the barrel, fully open
    "least_arm": 0.12,  # the ram's least moment arm about the hinge over the travel (check)
    "engine_clear": 0.01,  # the well and the actuator this far from the engine (check)
    "clear": 0.008,  # the core's structure cut back from the well, along the well's vertex normals (4.6 mm or more)
}
# The panel knuckle's and the fixed knuckles' sections about the hinge axis, degrees from aft toward out. Each piece
# keeps to the angles the other side never sweeps: the panel's turns up to 60 degrees and so must stop short of 120
# (forward, where the fixed skin lies), the fixed ones start above the 60 the panel's outer face reaches.
KNUCKLE_DEG = {"panel": (-90.0, 110.0), "fixed": (65.0, 265.0)}
# The well's airframe (well_detail), metres: two ribs across the walls and floor, each a land standing off the wall
# with a rivet row along its floor run; and two hydraulic lines out of the lower wall into the anchor fitting, each
# (station sm where it leaves the wall, its t on the floor, the sm where it drops into the channel, its t down the
# channel's wall, its end's n from the anchor's), t along the hinge from the actuator's plane: each line keeps 4 mm
# or more from the channel's wall and the cylinder's 22 mm barrel, and crosses the other only at different depths.
RIBS = {"at": (0.26, 0.43), "width": 0.02, "height": 0.008, "rivet_pitch": 0.03, "rivet_r": 0.0025, "rivet_end": 0.03}
LINES = {"r": 0.004, "sides": 5, "runs": ((0.10, -0.060, 0.057, -0.034, 0.008), (0.124, -0.070, 0.114, -0.044, -0.010))}
NAMES = {side: ("speed_brake_" + side, "speed_brake_%s_rod" % side, "speed_brake_%s_cylinder" % side) for side in "LR"}
# Triangles per brake: panel and actuator (the well counts in the fuselage_aft core's, its lip in the skin's). The panel
# takes the skin's rings over it (build_icarus TAIL_FINE).
BUDGET = {name: {"target": 528, "cap": 528, "exact": (name + "_visible", rod, cylinder)}
          for name, rod, cylinder in NAMES.values()}
CLOSEUPS = {"speed_brake": (Vector((2.1, 6.9, -0.75)), Vector((0.62, 5.25, 0.05)))}


class Patch:
    """The skin the left brake covers, addressed in metres: sm aft of the hole's front edge, am up its arc from the
    lower edge. Points are bilinear over the loft's own facets, so the panel's outer face lies on the skin around it.
    Depths run along the skin's section normal, in the station's plane, as the well's walls do."""

    def __init__(self, p):
        import stations

        sb = p["speed_brake"]
        st = bi.fuselage_stations(p)
        j0, j1 = st.index(sb["s0"]), st.index(sb["s1"])  # fuselage_stations puts both on the loft
        if any(stations.carve_shapes(p, st[j]) for j in range(j0, j1 + 1)):
            raise ValueError("speed brakes: the store trough reaches their stations, where it moves the ring columns")
        rings = [bi.blended_ring(p, st[j]) for j in range(j0, j1 + 1)]
        mid = rings[len(rings) // 2]
        zc = bi.fuselage_shapes(p, st[j0 + len(rings) // 2])[1]
        self.angle = lambda v: math.degrees(math.atan2(v.z - zc, v.x))  # about the body lobe's centre, as panels.py
        cols = sorted((k for k, v in enumerate(mid) if v.x > 0.05 and sb["deg0"] - 0.5 <= self.angle(v) <= sb["deg1"] + 0.5),
                      key=lambda k: mid[k].z)
        if any((b - a) % bi.RING != 1 for a, b in zip(cols, cols[1:])):
            raise ValueError("speed brakes: the ring columns of the deg0..deg1 band do not run in order")
        self.s = [st[j] for j in range(j0, j1 + 1)]
        self.grid = [[r[k] for k in cols] for r in rings]
        self.arc = [0.0]
        for c in range(1, len(cols)):
            self.arc.append(self.arc[-1] + sum((g[c] - g[c - 1]).length for g in self.grid) / len(self.grid))
        self.length, self.width = self.s[-1] - self.s[0], self.arc[-1]
        # The well's outline: at each hole point the skin's section normal (one-sided at the upper and lower edges,
        # so each wall is flat), and the floor's corners well_floor inside the upper and lower edges.
        last = len(cols) - 1
        self.inward = [[section_normal(r[max(k - 1, 0)], r[min(k + 1, last)]) for k in range(len(cols))]
                       for r in self.grid]
        self.floor = [(r[0] - n[0] * SHAPE["well_floor"], r[-1] - n[-1] * SHAPE["well_floor"])
                      for r, n in zip(self.grid, self.inward)]

    def hinge(self):
        """The hinge axis along the front edge's chord, lifted just outboard of its outermost point and set
        hinge_ahead of it: every point of the panel and of the hole's front edge lies inside the axis, so opening never
        moves the panel forward. Returns the axis's origin, its direction x_axis (lower edge to upper), aft and out
        across it, and middle, the actuator's plane along it from the origin."""
        sh = SHAPE
        front, lo, hi = sh["gap"], sh["gap"], self.width - sh["gap"]
        edge = [self.at(front, lo + (hi - lo) * i / 16) for i in range(17)]
        x_axis = (edge[-1] - edge[0]).normalized()
        aft = Vector((0.0, 1.0, 0.0))
        aft = (aft - x_axis * x_axis.dot(aft)).normalized()
        out = x_axis.cross(aft)
        out = out if out.x > 0 else -out
        fronts = edge + [self.at(front, v) for v in self.arc] + self.grid[0]
        lift = max((q - edge[0]).dot(out) for q in fronts) + sh["hinge_lift"]
        origin = edge[0] + out * lift - aft * sh["hinge_ahead"]
        middle = (self.at(front, self.width / 2) - origin).dot(x_axis)
        return origin, x_axis, aft, out, middle

    def floor_at(self, sm, f):
        """The well floor at sm, f of the way across from its lower corner to its upper."""
        j, fj = self.locate(self.s, self.s[0] + sm)
        lo, hi = (self.floor[j][i].lerp(self.floor[j + 1][i], fj) for i in (0, 1))
        return lo.lerp(hi, f)

    def channel(self):
        """The channel below the well floor that the cylinder lies in shut, in the actuator's plane: its front a (the
        well's front wall), its floor's n under the anchor fitting, the a where that flat meets the floor's slope up
        under the shut barrel (channel_clear below it), the floor's n at the aft end and the aft end's a,
        channel_clear past the barrel's gland."""
        sh = SHAPE
        origin, x_axis, aft, out, middle = self.hinge()
        a0 = (self.grid[0][0] - origin).dot(aft)
        anchor, eye = self.actuator()
        axis = (eye - anchor).normalized()  # (a, n), rising aft
        down = Vector((axis.y, -axis.x))
        gland = anchor + axis * ((eye - anchor).length - 0.030)
        a_end = gland.x + down.x * sh["barrel_r"] + sh["channel_clear"]
        deep = anchor.y - 0.022 - sh["channel_clear"] / 2  # the anchor fitting's lugs reach 0.022 below the eye
        under = anchor + down * (sh["barrel_r"] + sh["channel_clear"])  # a point on the line under the barrel
        n_at = lambda a: under.y + axis.y * (a - under.x) / axis.x
        a_k = under.x + axis.x * (deep - under.y) / axis.y
        return a0, deep, a_k, n_at(a_end), a_end

    def actuator(self):
        """The cylinder's eye and the rod's, shut, as (a, n) in the actuator's plane."""
        sh = SHAPE
        origin, x_axis, aft, out, middle = self.hinge()
        q = self.at(sh["bracket"], self.width / 2)
        eye = Vector(((q - origin).dot(aft), (q - origin).dot(out) - sh["eye_depth"]))
        return Vector(sh["anchor"]), eye

    @staticmethod
    def locate(marks, x):
        i = next((k for k in range(len(marks) - 2) if x < marks[k + 1]), len(marks) - 2)
        return i, (x - marks[i]) / (marks[i + 1] - marks[i])

    def point(self, sm, am):
        j, fj = self.locate(self.s, self.s[0] + sm)
        c, fc = self.locate(self.arc, am)
        g = self.grid
        return g[j][c].lerp(g[j][c + 1], fc).lerp(g[j + 1][c].lerp(g[j + 1][c + 1], fc), fj)

    def normal(self, sm, am, e=0.01):
        """The skin's normal in the station's plane."""
        n = self.point(sm, am + e) - self.point(sm, am - e)
        return section_normal(Vector(), Vector((n.x, 0.0, n.z)))

    def at(self, sm, am, depth=0.0):
        return self.point(sm, am) - self.normal(sm, am) * depth

    def voids(self, side=1):
        """The well's void and its channel's, each closed, Blender world space, side -1 for the right. The well's:
        each station's ring is the hole's edge across the skin, then the floor's corners. The channel's: its section
        in the actuator's plane, from above the well floor down to its own, across its width."""
        rings = [[Vector((side * q.x, q.y, q.z)) for q in r + [f[1], f[0]]] for r, f in zip(self.grid, self.floor)]
        n = len(rings[0])
        faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
                 for j in range(len(rings) - 1) for k in range(n)]
        faces += [tuple(range(n))[::-1], tuple((len(rings) - 1) * n + k for k in range(n))]
        origin, x_axis, aft, out, middle = self.hinge()
        a0, deep, a_k, n_end, a_end = self.channel()
        top = (self.floor_at(0.0, 0.5) - origin).dot(out) + 0.01  # inside the well's void all along
        section = [(a0, top), (a_end, top), (a_end, n_end), (a_k, deep), (a0, deep)]
        w = SHAPE["channel"]
        channel = [origin + x_axis * (middle + t) + aft * a + out * n for t in (-w, w) for a, n in section]
        channel = [Vector((side * q.x, q.y, q.z)) for q in channel]
        m = len(section)
        sides = [(k, (k + 1) % m, m + (k + 1) % m, m + k) for k in range(m)]
        return [([q for r in rings for q in r], faces),
                (channel, sides + [tuple(range(m))[::-1], tuple(m + k for k in range(m))])]


def section_normal(a, b):
    """The outward normal, in the station's plane, of the skin running from a to b round the section."""
    n = Vector((0.0, 1.0, 0.0)).cross(b - a).normalized()
    return n if n.x > 0 else -n


class Shell:
    """One object's vertices and faces, each face on a material slot."""

    def __init__(self):
        self.verts, self.faces, self.slots = [], [], []

    def vert(self, co):
        self.verts.append(co.copy())
        return len(self.verts) - 1

    def face(self, ids, slot, toward=None, away=None):
        """A face; turned so its normal points toward a point (a well's void) or away from one (a solid's centre)."""
        ids = list(ids)
        if toward is not None or away is not None:
            pts = [self.verts[i] for i in ids]
            centre = sum(pts, Vector()) / len(pts)
            normal = sum((a.cross(b) for a, b in zip(pts, pts[1:] + pts[:1])), Vector())
            if normal.dot(toward - centre if toward is not None else centre - away) < 0:
                ids.reverse()
        self.faces.append(ids)
        self.slots.append(slot)

    def solid(self, points, faces, slot):
        """A closed convex piece, its faces turned outward."""
        ids = [self.vert(q) for q in points]
        centre = sum(points, Vector()) / len(points)
        for f in faces:
            self.face([ids[i] for i in f], slot, away=centre)

    def box(self, corner, slot):
        """A box from corner(i, j, k) for i, j, k in 0, 1."""
        self.solid([corner(i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1)],
                   [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)], slot)

    def tube(self, rings, slot):
        """A closed tube through rings of equal count, capped at both ends."""
        n = len(rings[0])
        faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
                 for j in range(len(rings) - 1) for k in range(n)]
        faces += [tuple(range(n)), tuple((len(rings) - 1) * n + k for k in range(n))]
        self.solid([q for r in rings for q in r], faces, slot)

    def prism(self, section, slot):
        """A closed prism between two copies of a section (a polygon, convex or not), turned outward by its volume."""
        a, b = section
        n = len(a)
        pts = a + b
        faces = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
        faces += [tuple(range(n))[::-1], tuple(n + k for k in range(n))]
        rel = [q - pts[0] for q in pts]  # small coordinates: mathutils works in single precision
        volume = sum(rel[f[0]].dot(rel[f[i]].cross(rel[f[i + 1]])) for f in faces for i in range(1, len(f) - 1))
        ids = [self.vert(q) for q in pts]
        for f in faces:
            self.faces.append([ids[i] for i in (f if volume > 0 else f[::-1])])
            self.slots.append(slot)

    def realise(self, name, materials):
        obj = bi.mesh_object(name, self.verts, self.faces)
        if len(obj.data.polygons) != len(self.slots):
            raise ValueError("speed brakes: %s lost faces in validation" % name)
        bi.finish(obj, materials[0])
        for mat in materials[1:]:
            obj.data.materials.append(mat)
        for poly, slot in zip(obj.data.polygons, self.slots):
            poly.material_index = slot
        return obj


def ring(centre, u, v, r, n):
    return [centre + (u * math.cos(2 * math.pi * k / n) + v * math.sin(2 * math.pi * k / n)) * r for k in range(n)]


def pie(degrees, r, segments):
    """A knuckle's section about the hinge axis: the axis and an arc, as (aft, out) points."""
    d0, d1 = (math.radians(d) for d in degrees)
    return [(0.0, 0.0)] + [(r * math.cos(d0 + (d1 - d0) * i / segments), r * math.sin(d0 + (d1 - d0) * i / segments))
                           for i in range(segments + 1)]


def pivot_frame(at, axis, toward):
    """An actuator piece's frame: origin at its eye, X along the hinge, Y at the other piece's eye."""
    y = (toward - at).normalized()
    return Matrix.Translation(at) @ Matrix((axis, y, axis.cross(y))).transposed().to_4x4()


def build(p, mats):
    """Both brakes: hinge, panel, actuator, well and lip each side, and their holes cut from the fuselage skin."""
    sh = SHAPE
    patch = Patch(p)
    skin, mech, dark = mats["body"], mats["mechanical"], mats["duct"]
    front, end, lo, hi = sh["gap"], patch.length - sh["gap"], sh["gap"], patch.width - sh["gap"]
    origin, x_axis, aft, out, middle = patch.hinge()

    def hp(t, a, n):
        """t along the hinge from the actuator's plane, a aft of the hinge axis and n out from it."""
        return origin + x_axis * (middle + t) + aft * a + out * n

    def plane(q):
        """q in the actuator's plane: its (a, n)."""
        d = q - origin
        return d.dot(aft), d.dot(out)

    def knuckle(shell, t0, t1, degrees, slot):
        section = pie(degrees, sh["knuckle_r"], 3)
        shell.prism([[hp(t, a, n) for a, n in section] for t in (t0, t1)], slot)

    # The actuator's ends (SHAPE's anchor, bracket and eye_depth): the cylinder's eye deep in the channel on frame
    # 13.0's fitting, the rod's in a clevis on the panel's fitting.
    g, floor = patch.grid, patch.floor
    (anchor_a, anchor_n), (clevis_a, clevis_n) = patch.actuator()
    anchor, eye = hp(0.0, anchor_a, anchor_n), hp(0.0, clevis_a, clevis_n)

    panel = Shell()
    # The outer face on the loft's own stations and columns, so it lies on the skin's facets.
    outer_u = [front] + [s - patch.s[0] for s in patch.s[1:-1]] + [end]
    outer_v = [lo] + patch.arc[1:-1] + [hi]
    outer = {(i, k): panel.vert(patch.at(u, v)) for i, u in enumerate(outer_u) for k, v in enumerate(outer_v)}
    for i in range(len(outer_u) - 1):
        for k in range(len(outer_v) - 1):
            panel.face([outer[i, k], outer[i + 1, k], outer[i + 1, k + 1], outer[i, k + 1]], 0)
    # Inside, a heightfield on jet_mechanical: the rims and stringers at frame depth, the sheet between, its cells
    # broken at the loft's stations (the aft fuselage is concave lengthwise, and a longer chord would bow out through
    # the outer face), and a rib across it under the actuator's fitting.
    rim, rib, mid = sh["rim"], sh["rib"] / 2, patch.width / 2
    bracket = (sh["bracket"] - sh["bracket_rib"] / 2, sh["bracket"] + sh["bracket_rib"] / 2)
    rim_us = {front, front + rim, end - sh["tip_rim"], end} | {u for u in outer_u[1:-1] if front + rim < u < end - sh["tip_rim"]}
    us = sorted(rim_us | set(bracket))
    vs = [lo, lo + rim, mid - sh["stringer"] - rib, mid - sh["stringer"] + rib, mid + sh["stringer"] - rib,
          mid + sh["stringer"] + rib, hi - rim, hi]
    frame_u, frame_v = {0, len(us) - 2, us.index(bracket[0])}, {0, 2, 4, len(vs) - 2}

    def depth(i, k):
        return sh["frame_depth"] if i in frame_u or k in frame_v else sh["sheet_depth"]

    inner = {}

    def iv(i, k, d):
        if (i, k, d) not in inner:
            inner[i, k, d] = panel.vert(patch.at(us[i], vs[k], d))
        return inner[i, k, d]

    for i in range(len(us) - 1):
        for k in range(len(vs) - 1):
            d = depth(i, k)
            panel.face([iv(i, k, d), iv(i + 1, k, d), iv(i + 1, k + 1, d), iv(i, k + 1, d)], 1)
            if i + 2 < len(us) and depth(i + 1, k) != d:
                e = depth(i + 1, k)
                panel.face([iv(i + 1, k, d), iv(i + 1, k + 1, d), iv(i + 1, k + 1, e), iv(i + 1, k, e)], 1)
            if k + 2 < len(vs) and depth(i, k + 1) != d:
                e = depth(i, k + 1)
                panel.face([iv(i, k + 1, d), iv(i + 1, k + 1, d), iv(i + 1, k + 1, e), iv(i, k + 1, e)], 1)
    # The skin's edges join the outer face to the rim, triangles zipped between their different breaks: the rim's own,
    # not the rib's, which would change the skin's faces and so the whole skin atlas's packing.
    rim_d = sh["frame_depth"]
    first, last_u, last_v = 0, len(outer_u) - 1, len(outer_v) - 1
    sides = [([(u, outer[i, first]) for i, u in enumerate(outer_u)], [(u, iv(i, 0, rim_d)) for i, u in enumerate(us) if u in rim_us]),
             ([(u, outer[i, last_v]) for i, u in enumerate(outer_u)], [(u, iv(i, len(vs) - 1, rim_d)) for i, u in enumerate(us) if u in rim_us]),
             ([(v, outer[first, k]) for k, v in enumerate(outer_v)], [(v, iv(0, k, rim_d)) for k, v in enumerate(vs)]),
             ([(v, outer[last_u, k]) for k, v in enumerate(outer_v)], [(v, iv(len(us) - 1, k, rim_d)) for k, v in enumerate(vs)])]
    for top, bottom in sides:
        a = b = 0
        while a < len(top) - 1 or b < len(bottom) - 1:
            if b == len(bottom) - 1 or (a < len(top) - 1 and top[a + 1][0] <= bottom[b + 1][0]):
                panel.face([top[a][1], top[a + 1][1], bottom[b][1]], 0)
                a += 1
            else:
                panel.face([top[a][1], bottom[b + 1][1], bottom[b][1]], 0)
                b += 1
    # Two hinge knuckles on the axis, and the actuator's fitting: two gussets standing off the inner sheet across the
    # rib, either side of the rod's eye, a clevis.
    half = sh["knuckle_length"] / 2
    for c in (-sh["knuckle"], sh["knuckle"]):
        knuckle(panel, c - half, c + half, KNUCKLE_DEG["panel"], 1)
    cheek = [plane(patch.at(sh["bracket"] - 0.06, mid, sh["sheet_depth"] + 0.002)),
             plane(patch.at(sh["bracket"] + 0.045, mid, sh["sheet_depth"] + 0.002)), (clevis_a, clevis_n - 0.018)]
    for side in (1, -1):
        t0, t1 = sorted((side * 0.0135, side * 0.0185))
        panel.prism([[hp(t, a, n) for a, n in cheek] for t in (t0, t1)], 1)

    # The lip: skin from the hole's edges lip deep. The well below it: walls on to the floor and the floor across,
    # all facing into the void, on the dark slot. The floor runs in three strips, the middle one open down to the
    # channel (Patch.channel) as far aft as the cylinder lies below it; the channel's walls and floor close it, and
    # the well's front wall runs on down the channel's. The fixed knuckles either side of each panel knuckle and the
    # anchor fitting's pin heads are on jet_mechanical.
    lip_shell, well = Shell(), Shell()
    inward = patch.inward
    lip = [[q - n * sh["lip"] for q, n in zip(r, ns)] for r, ns in zip(g, inward)]
    void = (g[len(g) // 2][len(g[0]) // 2] + 0.5 * (floor[len(g) // 2][0] + floor[len(g) // 2][1])) / 2
    rows = len(g)
    t_of = lambda q: (q - origin).dot(x_axis) - middle
    w = sh["channel"]
    a0, deep, a_k, n_end, a_end = patch.channel()
    sm_of = lambda a: a - a0  # the stations' planes lie square to aft, so a and sm differ by a constant

    def across(sm):
        """The floor at sm: its lower corner, the channel's lower and upper edges, its upper corner."""
        f0, f1 = patch.floor_at(sm, 0.0), patch.floor_at(sm, 1.0)
        return [f0] + [f0.lerp(f1, (t - t_of(f0)) / (t_of(f1) - t_of(f0))) for t in (-w, w)] + [f1]

    def bottom(a):
        return deep if a <= a_k else deep + (n_end - deep) * (a - a_k) / (a_end - a_k)

    for jj in range(rows - 1):
        for k in (0, -1):
            lip_shell.face([lip_shell.vert(q) for q in (g[jj][k], g[jj + 1][k], lip[jj + 1][k], lip[jj][k])], 0, toward=void)
        for quad in ([lip[jj][0], lip[jj + 1][0], floor[jj + 1][0], floor[jj][0]],
                     [lip[jj][-1], lip[jj + 1][-1], floor[jj + 1][1], floor[jj][1]]):
            well.face([well.vert(q) for q in quad], 0, toward=void)
    breaks = sorted({s - patch.s[0] for s in patch.s} | {sm_of(a_k), sm_of(a_end)})
    breaks[0], breaks[-1] = 0.0, patch.length  # the first and last stations exactly, so the corners are the floor's own
    sink = hp(0.0, (a0 + a_end) / 2, (deep + plane(patch.floor_at(0.0, 0.5))[1]) / 2)  # inside the channel
    for s0, s1 in zip(breaks, breaks[1:]):
        r0, r1 = across(s0), across(s1)
        open_ = s1 <= sm_of(a_end) + 1e-9
        for i in ((0, 2) if open_ else (0, 1, 2)):
            well.face([well.vert(q) for q in (r0[i], r0[i + 1], r1[i + 1], r1[i])], 0, toward=void)
        if open_:
            b0, b1 = (bottom(s + a0) for s in (s0, s1))
            low = [[hp(t, s + a0, b) for t in (-w, w)] for s, b in ((s0, b0), (s1, b1))]
            for i, edge in ((0, 1), (1, 2)):  # the side walls, under the channel's edges
                well.face([well.vert(q) for q in (r0[edge], r1[edge], low[1][i], low[0][i])], 0, toward=sink)
            well.face([well.vert(q) for q in (low[0][0], low[0][1], low[1][1], low[1][0])], 0, toward=sink)
    r_end = across(sm_of(a_end))
    well.face([well.vert(q) for q in (r_end[1], r_end[2], hp(w, a_end, n_end), hp(-w, a_end, n_end))], 0, toward=sink)
    for jj in (0, rows - 1):
        for k in range(len(g[0]) - 1):
            lip_shell.face([lip_shell.vert(q) for q in (g[jj][k], g[jj][k + 1], lip[jj][k + 1], lip[jj][k])], 0, toward=void)
        wall = lip[jj] + [floor[jj][1], floor[jj][0]]
        if jj == 0:  # the front wall, notched down the channel
            r0 = across(0.0)
            wall = lip[jj] + [floor[jj][1], r0[2], hp(w, a0, deep), hp(-w, a0, deep), r0[1], floor[jj][0]]
        well.face([well.vert(q) for q in wall], 0, toward=void)
    well_detail(well, patch, lip, void, hp, t_of, (a0, anchor_a, anchor_n))
    hardware_start = len(well.faces)
    gap = 0.0005  # between each fixed knuckle and the panel's
    for c in (-sh["knuckle"], sh["knuckle"]):
        for side in (1, -1):
            t0, t1 = sorted((c + side * (half + gap), c + side * (half + gap + sh["bracket_length"])))
            knuckle(well, t0, t1, KNUCKLE_DEG["fixed"], 1)
    # The anchor fitting on frame 13.0, on the detail slot: a plate on the channel's front wall, a tapered lug either
    # side of the cylinder's eye and a pin head outside each. The pin stops at the lugs: the cylinder's eye turns
    # between them.
    plate = a0 + 0.010
    well.box(lambda i, j, k: hp((-w + 0.003, w - 0.003)[i], (a0 - 0.002, plate)[j], (deep + 0.003, anchor_n + 0.040)[k]), 2)
    lug = [(plate - 0.002, anchor_n - 0.022), (anchor_a, anchor_n - 0.012), (anchor_a + 0.012, anchor_n),
           (anchor_a, anchor_n + 0.012), (plate - 0.002, anchor_n + 0.030)]
    for side in (1, -1):
        t0, t1 = sorted((side * 0.0155, side * 0.0205))
        well.prism([[hp(t, a, n) for a, n in lug] for t in (t0, t1)], 2)
        t0, t1 = sorted((side * 0.0200, side * 0.0245))
        head = [(anchor_a + 0.0045 * math.cos(math.pi * i / 3), anchor_n + 0.0045 * math.sin(math.pi * i / 3)) for i in range(6)]
        well.prism([[hp(t, a, n) for a, n in head] for t in (t0, t1)], 1)

    # The actuator, built along its axis closed: the barrel's gland stops short of the clevis, the rod short of the
    # barrel's far end.
    closed = (eye - anchor).length
    gland, rod_length = closed - 0.030, closed - 0.045
    cylinder, rod = Shell(), Shell()
    x, y, z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    cylinder.box(lambda i, j, k: Vector(((-0.013, 0.013)[i], (-0.016, 0.036)[j], (-0.016, 0.016)[k])), 0)
    cylinder.tube([ring(y * sh["barrel_start"], x, z, sh["barrel_r"], 8), ring(y * (gland - 0.010), x, z, sh["barrel_r"], 8),
                   ring(y * gland, x, z, sh["rod_r"] + 0.004, 8)], 0)
    rod.box(lambda i, j, k: Vector(((-0.011, 0.011)[i], (-0.014, 0.014)[j], (-0.014, 0.014)[k])), 0)
    rod.tube([ring(y * 0.010, x, z, sh["rod_r"], 6), ring(y * rod_length, x, z, sh["rod_r"], 6)], 0)

    frame = bi.hinge_frame(origin, origin + x_axis)
    left = bi.hinged("speed_brake_L", panel.realise("speed_brake_L", (skin, mech)), frame)
    left[0]["deflection_deg"] = bi.surface_travel(p, "speed_brake_L")
    rod_obj = rod.realise("speed_brake_L_rod", (mech,))
    rod_obj.data.transform(frame.inverted() @ pivot_frame(eye, x_axis, anchor))
    rod_obj.parent = left[0]
    cylinder_obj = cylinder.realise("speed_brake_L_cylinder", (mech,))
    cylinder_obj.data.transform(pivot_frame(anchor, x_axis, eye))
    for obj, reach in ((rod_obj, rod_length), (cylinder_obj, gland)):
        obj["role"] = "visual"
        obj["reach_m"] = round(reach, 5)  # how far it runs from its eye along its axis
    cylinder_obj["parent_part"] = "fuselage_aft"  # parts.organise hangs it there
    well_obj = well.realise("speed_brake_well_L", (dark, mech, mats["well_detail"]))
    hardware = well_obj.data.attributes.new(name="exterior_hardware", type="INT", domain="FACE")
    hardware.data.foreach_set("value", [int(i >= hardware_start) for i in range(len(well.faces))])
    well_obj["merge_into"] = "fuselage_aft"
    lip_obj = lip_shell.realise("speed_brake_well_lip_L", (skin,))
    lip_obj["merge_into"] = "skin_aft_L"
    left += [rod_obj, cylinder_obj, well_obj, lip_obj]
    parts = left + bi.mirror_part(left)
    bpy.data.objects["speed_brake_well_lip_R"]["merge_into"] = "skin_aft_R"  # mirror_part copies the left's
    # mirror_part leaves meshes in their parent's frame; each actuator piece moves its origin to its eye.
    flip = Matrix.Scale(-1, 4, (1, 0, 0))
    for side, to_side in (("L", Matrix()), ("R", flip)):
        name, rod_name, cylinder_name = NAMES[side]
        hinge = bpy.data.objects[name]
        axis = hinge.matrix_world.col[0].xyz.normalized()
        a, e = to_side @ anchor, to_side @ eye
        piece = pivot_frame(a, axis, e)
        bpy.data.objects[cylinder_name].data.transform(piece.inverted())
        bpy.data.objects[cylinder_name].matrix_world = piece
        piece = hinge.matrix_world.inverted() @ pivot_frame(e, axis, a)
        bpy.data.objects[rod_name].data.transform(piece.inverted())
        bpy.data.objects[rod_name].matrix_basis = piece
    cut_holes(patch)
    return parts


def well_detail(well, patch, lip, void, hp, t_of, anchor):
    """The well's airframe, on its detail slot (2), so the open well reads as structure rather than a void: RIBS
    standing off the walls and floor with a rivet row along each, broken either side of the channel where it crosses
    one, and LINES, two hydraulic lines out of the lower wall, along the floor, over the channel's lower edge and down
    its wall into the anchor fitting's plate (anchor: the channel's front a, the anchor's a and n). All of it stays
    clear of the panel and the actuator through the travel (check() sweeps them against the well)."""
    a0, anchor_a, anchor_n = anchor
    w = SHAPE["channel"]
    channel_end = patch.channel()[4] - a0

    def section(sm):
        """The well's section at sm: lower lip foot, lower floor corner, upper floor corner, upper lip foot."""
        j, f = patch.locate(patch.s, patch.s[0] + sm)
        return [lip[j][0].lerp(lip[j + 1][0], f), patch.floor[j][0].lerp(patch.floor[j + 1][0], f),
                patch.floor[j][1].lerp(patch.floor[j + 1][1], f), lip[j][-1].lerp(lip[j + 1][-1], f)]

    def facing(a, b):
        """The normal, in the station's plane, of the wall running a to b, turned into the void."""
        n = Vector((0.0, 1.0, 0.0)).cross(b - a).normalized()
        return n if n.dot(void - (a + b) / 2) > 0 else -n

    def floor_point(sm, t, lift):
        _, f0, f1, _ = section(sm)
        u = (t - t_of(f0)) / (t_of(f1) - t_of(f0))
        return f0.lerp(f1, u) + facing(f0, f1) * lift

    def runs(sm, broken):
        """A rib's paths across the well at sm: one down the lower wall, over the floor and up the upper, or, broken,
        two, each stopping short of the channel's edge."""
        foot0, f0, f1, foot1 = section(sm)
        if not broken:
            return [[foot0, f0, f1, foot1]]
        return [[foot0, f0, floor_point(sm, -w - 0.004, 0.0)], [floor_point(sm, w + 0.004, 0.0), f1, foot1]]

    width, height = RIBS["width"], RIBS["height"]
    for sm in RIBS["at"]:
        broken = sm - width / 2 < channel_end
        for a_path, b_path in zip(*(runs(sm + ds, broken) for ds in (-width / 2, width / 2))):
            sides = []
            for path in (a_path, b_path):
                normals = [facing(a, b) for a, b in zip(path, path[1:])]
                at = [normals[0]] + [(m + n).normalized() for m, n in zip(normals, normals[1:])] + [normals[-1]]
                sides.append([(q - n * 0.001, q + n * height) for q, n in zip(path, at)])
            (a_side, b_side) = sides
            for i in range(len(a_side) - 1):
                ids = {key: well.vert(q) for key, q in (("a0b", a_side[i][0]), ("a0t", a_side[i][1]), ("a1b", a_side[i + 1][0]),
                                                         ("a1t", a_side[i + 1][1]), ("b0b", b_side[i][0]), ("b0t", b_side[i][1]),
                                                         ("b1b", b_side[i + 1][0]), ("b1t", b_side[i + 1][1]))}
                centre = sum((well.verts[v] for v in ids.values()), Vector()) / 8
                for quad in (("a0t", "a1t", "b1t", "b0t"), ("a0b", "a1b", "a1t", "a0t"), ("b0b", "b1b", "b1t", "b0t")):
                    well.face([ids[k] for k in quad], 2, away=centre)
                for end in ((0, "a0b", "b0b", "b0t", "a0t"), (len(a_side) - 2, "a1b", "b1b", "b1t", "a1t")):
                    if i == end[0]:
                        well.face([ids[k] for k in end[1:]], 2, away=centre)
        # the rivet rows along the rib's floor runs: three-sided heads standing on its top
        paths = runs(sm, broken)
        for f0, f1 in [(paths[0][1], paths[0][2])] + ([(paths[1][0], paths[1][1])] if broken else []):
            n = facing(f0, f1)
            along, across = (f1 - f0).normalized(), Vector((0.0, 1.0, 0.0))
            run = (f1 - f0).length
            count = int((run - 2 * RIBS["rivet_end"]) / RIBS["rivet_pitch"]) + 1
            for k in range(count):
                q = f0 + along * (RIBS["rivet_end"] + (run - 2 * RIBS["rivet_end"]) * k / max(count - 1, 1)) + n * height
                heads = [q + (along * math.cos(2 * math.pi * i / 3) + across * math.sin(2 * math.pi * i / 3)) * RIBS["rivet_r"]
                         - n * 0.0003 for i in range(3)]
                ids = [well.vert(v) for v in heads + [q + n * RIBS["rivet_r"] * 0.6]]
                for i in range(3):
                    well.face([ids[i], ids[(i + 1) % 3], ids[3]], 2, away=q - n * 0.001)
    r, lift = LINES["r"], LINES["r"] + 0.0005
    for k, (sm, t_floor, sm_drop, t_channel, dn) in enumerate(LINES["runs"]):
        foot, f0, f1, _ = section(sm)
        wall = facing(foot, f0)
        mid_wall = foot.lerp(f0, 0.5)
        path = [mid_wall - wall * 0.004, mid_wall + wall * lift,
                f0 + (f1 - f0).normalized() * 0.03 + facing(f0, f1) * lift,
                floor_point(sm, t_floor, lift), floor_point(sm_drop, t_floor, lift),
                floor_point(sm_drop, -w + 0.004, lift + 0.003), floor_point(sm_drop, t_channel, -0.008),
                hp(t_channel, a0 + sm_drop, anchor_n + dn), hp(t_channel, a0 + 0.008, anchor_n + dn)]
        rings = []
        for i, q in enumerate(path):
            tangent = ((path[min(i + 1, len(path) - 1)] - q).normalized() + (q - path[max(i - 1, 0)]).normalized()).normalized()
            u = tangent.cross(Vector((0.0, 1.0, 0.0)) if abs(tangent.y) < 0.9 else Vector((1.0, 0.0, 0.0))).normalized()
            v = tangent.cross(u)
            rings.append(ring(q, u, v, r, LINES["sides"]))
        n_side = LINES["sides"]
        ids = [[well.vert(p) for p in rg] for rg in rings]
        for i in range(len(rings) - 1):
            centre = (path[i] + path[i + 1]) / 2
            for c in range(n_side):
                well.face([ids[i][c], ids[i][(c + 1) % n_side], ids[i + 1][(c + 1) % n_side], ids[i + 1][c]], 2, away=centre)


def cut_holes(patch):
    """Delete the fuselage skin faces the panels cover, both sides: those whose corners are all the patch's points."""
    points = [q for r in patch.grid for q in r]
    tree = KDTree(2 * len(points))
    for i, q in enumerate(points):
        tree.insert(q, 2 * i)
        tree.insert(Vector((-q.x, q.y, q.z)), 2 * i + 1)
    tree.balance()
    fuselage = bpy.data.objects["fuselage"]
    bm = bmesh.new()
    bm.from_mesh(fuselage.data)
    hole = [f for f in bm.faces if all(tree.find(v.co)[2] < 1e-5 for v in f.verts)]
    expected = 2 * (len(patch.grid) - 1) * (len(patch.grid[0]) - 1)
    if len(hole) != expected:
        raise ValueError("speed brakes: %d skin faces under the panels, expected %d" % (len(hole), expected))
    bmesh.ops.delete(bm, geom=hole, context="FACES_ONLY")
    bm.to_mesh(fuselage.data)
    bm.free()


def clear_wells(icarus):
    """Cut the fuselage_aft core's frames, stringers and break walls (its Icarus_Frame faces) back SHAPE["clear"] from
    both wells and their channels, so an open well shows only its own walls, as parts.open_bays clears the gear bays.
    Render mesh only: run after the hulls, which keep the whole frames."""
    import internals
    import parts

    patch = Patch(bi.PARAMS)
    cutters = []
    for side in (1, -1):
        for verts, faces in patch.voids(side):
            void = bi.mesh_object("speed_brake_void", verts, faces)  # world space, as cut_shells wants
            cutters.append(internals.grown(void, SHAPE["clear"]))
            me = void.data
            bpy.data.objects.remove(void)
            bpy.data.meshes.remove(me)
    parts.cut_structure(icarus, bpy.data.objects["fuselage_aft"], cutters)


def aim_actuators():
    """Pose each actuator for its hinge's current turn as the AimConstraints do in game: the cylinder about its eye and
    the rod about its own, each aimed at the other's eye, turning about the hinge axis. Update the view layer first."""
    for name, rod_name, cylinder_name in NAMES.values():
        hinge, rod, cylinder = (bpy.data.objects[n] for n in (name, rod_name, cylinder_name))
        axis = hinge.matrix_world.col[0].xyz.normalized()
        a, e = cylinder.matrix_world.translation.copy(), rod.matrix_world.translation.copy()
        cylinder.matrix_world = pivot_frame(a, axis, e)
        rod.matrix_world = pivot_frame(e, axis, a)


def posed_tree(obj, matrix):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(matrix)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree


def panel_lines(p):
    """The fuselage's panel lines round the brakes as art/textures/panels.py draws them: butt joints (seams), the
    riveted frames between them, the lap joints' planes (signed distances, positive above, at a point), the fastener
    rows' offset from a joint and the seam's half width."""
    import internals
    import parts

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "textures"))
    import panels

    table = p["fuselage"]
    # The body centre heights pilot2_skin.py writes to structure.json for panels.py.
    sections = [[float(s), bi.fuselage_shapes(p, float(s))[1]] for s in np.arange(table[0][0], table[-1][0], .05)]
    lines = panels.fuselage_lines({"frames": internals.INTERNALS["frames"], "fuselage_sections": sections},
                                  (parts.RADOME_END, parts.FORWARD_END, parts.MID_END, table[-1][0]))
    laps = lambda v: [float(d) for d in panels.lap_distances(abs(v.x), v.y + bi.S0, v.z, lines)]
    return lines["joints"], lines["plain"], laps, panels.ROW_OFFSET, panels.SEAM_HALF_WIDTH


def outline_on_panel_lines(p, patch):
    """Each brake is its own skin panel: its front edge on a butt joint, its aft edge one fastener row ahead of a
    riveted frame, its lower edge within the lower lap joint's groove all along, and no joint, riveted frame or lap
    joint crossing the hole."""
    joints, riveted, laps, row, half_width = panel_lines(p)
    s0, s1 = patch.s[0], patch.s[-1]
    problems = []
    if min(abs(s0 - j) for j in joints) > 1e-4:
        problems.append("front edge s %.4f is on no butt joint %s" % (s0, joints))
    if min(abs(s1 + row - f) for f in riveted) > 1e-4:
        problems.append("aft edge s %.4f is not %.3f m ahead of a riveted frame %s" % (s1, row, riveted))
    lower = max(abs(laps(r[0])[1]) for r in patch.grid)
    if lower > half_width:
        problems.append("lower edge strays %.1f mm from the lower lap joint" % (lower * 1000))
    problems += ["s %.3f line crosses the hole" % s for s in joints + riveted if s0 + 1e-4 < s < s1 - 1e-4]
    distances = [laps(v) for r in patch.grid for v in r]
    if max(d[0] for d in distances) > -half_width or min(d[1] for d in distances) < -half_width:
        problems.append("a lap joint crosses the hole")
    return problems


def well_sealed(icarus, patch):
    """Look in through each hole, its panel and actuator left out: every ray's first face the game draws (turned
    toward it) lies on the well, its channel, what stands in them or the hinge fittings over them (exterior hardware),
    never on structure, the engine or sky past them. Returns the rays cast and the problems."""
    skip = {n for name, rod, cylinder in NAMES.values() for n in (name + "_visible", rod, cylinder)}
    verts, faces, hardware = [], [], []
    for obj in icarus.objects:
        if obj.type != "MESH" or obj.name in skip or obj.get("role") == "cockpit_view":
            continue
        offset = len(verts)
        verts.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        faces.extend(tuple(offset + i for i in f.vertices) for f in obj.data.polygons)
        flags = obj.data.attributes.get("exterior_hardware")
        hardware.extend(bool(flags and flags.data[f.index].value) for f in obj.data.polygons)
    scene = BVHTree.FromPolygons(verts, faces)
    sh, rays, problems = SHAPE, 0, []
    for side in (1, -1):
        flip = lambda v: Vector((side * v.x, v.y, v.z))
        voids = [BVHTree.FromPolygons(*v) for v in patch.voids(side)]
        on_well = lambda q: any(t.find_nearest(q)[3] < 0.002 or checks.inside_closed(t, q) for t in voids)
        for i in range(9):
            for k in range(7):
                sm = sh["gap"] + (patch.length - 2 * sh["gap"]) * i / 8
                am = sh["gap"] + (patch.width - 2 * sh["gap"]) * k / 6
                n = flip(patch.normal(sm, am))
                q = flip(patch.point(sm, am)) + n * 0.001
                aft = Vector((0.0, 1.0, 0.0))
                across = n.cross(aft).normalized()
                for u in (-0.8, 0.0, 0.8):
                    for v in (-0.8, 0.0, 0.8):
                        d = (-n + aft * u + across * v).normalized()
                        origin, hit, index = q, None, None
                        for _ in range(64):  # faces turned away are culled: look on through them
                            hit, normal, index, _ = scene.ray_cast(origin, d)
                            if hit is None or normal.dot(d) < 0:
                                break
                            origin = hit + d * 1e-5
                        rays += 1
                        if hit is None or not (hardware[index] or on_well(hit)):
                            problems.append("a view in through the %s hole at sm %.2f am %.2f sees %s" % (
                                "LR"[side < 0], sm, am, "sky" if hit is None else "past the well at %s" % tuple(round(c, 3) for c in hit)))
    return rays, problems


def channel_floor(patch, step=0.01):
    """Points every step over the channel's floor and aft wall, left side, world space."""
    origin, x_axis, aft, out, middle = patch.hinge()
    a0, deep, a_k, n_end, a_end = patch.channel()
    top = (patch.floor_at(0.0, 0.5) - origin).dot(out)
    path = [(a0, top), (a0, deep), (a_k, deep), (a_end, n_end), (a_end, top)]
    points = []
    w = SHAPE["channel"]
    for (a1, n1), (a2, n2) in zip(path, path[1:]):
        count = max(1, math.ceil(math.hypot(a2 - a1, n2 - n1) / step))
        for i in range(count + 1):
            a, n = a1 + (a2 - a1) * i / count, n1 + (n2 - n1) * i / count
            points += [origin + x_axis * (middle + t) + aft * a + out * n
                       for t in (-w + 2 * w * j / math.ceil(2 * w / step) for j in range(math.ceil(2 * w / step) + 1))]
    return points


def check(icarus):
    """Open each brake through its travel in steps of parts.SWEEP_STEP with its actuator aimed: the rod stays at least
    engage inside the barrel and short of its far end, the ram holds least_arm or more of moment arm about the hinge,
    and neither the panel nor either actuator piece meets the skin (its lip included), the fuselage_aft core (the
    well, its channel, knuckles and anchor fitting, the frames) or the engine, nor the actuator the panel. The channel
    keeps engine_clear from the engine, every view in through the holes ends on the well (well_sealed), and the
    outline stays on the skin's panel lines."""
    import budget
    import parts

    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("speed brakes: over the triangle caps: " + "; ".join(over))
    patch = Patch(bi.PARAMS)
    problems = outline_on_panel_lines(bi.PARAMS, patch)
    O = bpy.data.objects
    fixed = {n: checks.tree(O[n]) for n in ("fuselage_aft", "skin_aft_L", "skin_aft_R", "engine_core")}
    engine = fixed["engine_core"]
    nearest = min(engine.find_nearest(Vector((side * q.x, q.y, q.z)))[3] for q in channel_floor(patch) for side in (1, -1))
    if nearest < SHAPE["engine_clear"]:
        problems.append("the channel comes %.4f m from the engine" % nearest)
    poses, least = 0, math.inf
    arms, lengths = [], []
    for name, rod_name, cylinder_name in NAMES.values():
        hinge, panel, rod, cylinder = O[name], O[name + "_visible"], O[rod_name], O[cylinder_name]
        axis = hinge.matrix_world.col[0].xyz.normalized()
        to_hinge = hinge.matrix_world.inverted()
        panel_local, rod_local = to_hinge @ panel.matrix_world, to_hinge @ rod.matrix_world
        a = cylinder.matrix_world.translation.copy()
        centre = sum((v.co for v in panel.data.vertices), Vector()) / len(panel.data.vertices)

        def turned(deg):
            return hinge.matrix_world @ Matrix.Rotation(math.radians(deg), 4, "X")

        sign = 1 if abs((turned(1.0) @ panel_local @ centre).x) > abs((turned(-1.0) @ panel_local @ centre).x) else -1
        travel = hinge["deflection_deg"]
        steps = math.ceil(travel / parts.SWEEP_STEP)
        for i in range(steps + 1):
            deg = sign * travel * i / steps
            pose = turned(deg)
            e = (pose @ rod_local).translation
            length = (e - a).length
            inside = cylinder["reach_m"] + rod["reach_m"] - length
            least = min(least, inside)
            if inside < SHAPE["engage"] or length - rod["reach_m"] < SHAPE["barrel_start"]:
                problems.append("%s at %+.1f deg: rod %.3f m inside the barrel" % (name, deg, inside))
            # the moment arm: the hinge axis's distance from the ram's line, square to both
            arm = abs((hinge.matrix_world.translation - a).dot(axis.cross((e - a).normalized())))
            if arm < SHAPE["least_arm"]:
                problems.append("%s at %+.1f deg: the ram's moment arm is %.3f m" % (name, deg, arm))
            if name == "speed_brake_L":
                arms.append(arm)
                lengths.append(length)
            posed = {panel.name: posed_tree(panel, pose @ panel_local), rod.name: posed_tree(rod, pivot_frame(e, axis, a)),
                     cylinder.name: posed_tree(cylinder, pivot_frame(a, axis, e))}
            for piece, others in ((panel.name, fixed), (rod.name, dict(fixed, **{panel.name: posed[panel.name]})),
                                  (cylinder.name, dict(fixed, **{panel.name: posed[panel.name]}))):
                problems += ["%s at %+.1f deg meets %s" % (piece, deg, n) for n, t in others.items() if posed[piece].overlap(t)]
            poses += 1
    rays, leaks = well_sealed(icarus, patch)
    problems += leaks
    if problems:
        raise ValueError("speed brakes: " + "; ".join(problems[:20]) + (" (%d in all)" % len(problems) if len(problems) > 20 else ""))
    print("speed brakes: panels and actuators clear through %d poses; the rod stays %.3f m inside the barrel; the ram's "
          "moment arm %.3f m shut, %.3f m half open, %.3f m open; stroke %.3f m (%.3f to %.3f m between eyes); channel "
          "%.3f m off the engine; %d views in through the holes end on the wells; outline on the panel lines" % (
              poses, least, arms[0], arms[len(arms) // 2], arms[-1], max(lengths) - min(lengths), min(lengths),
              max(lengths), nearest, rays))
