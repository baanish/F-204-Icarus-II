"""Speed brakes as on the F-104: a flush panel low on each side of the aft fuselage, hinged at its front edge and
opening outward on the stock Airbrake, with the well it covers and a hydraulic actuator between the two.

PARAMS["speed_brake"] places the panel: its own skin panel, its edges on the skin's panel lines (art/textures/panels.py)
and on the fuselage loft's own stations and ring columns, so the hole is whole skin faces and the panel's outer face
lies on them. The parts follow the stock aircraft (the FS-12 Revoker's panel and well, the VTOLTrainer1's actuator):

- speed_brake_<side>_visible, the panel: skin on its outer face and edges; on jet_mechanical a tray inside, with a
  rim, two stringers and the wide tip rim at its free edge that carries the actuator's clevis, and two hinge knuckles.
- speed_brake_well_lip_<side>: skin down the hole's edges, joined into the skin_aft panel (merge_into), so the hairline
  seam round the shut panel shows skin on both faces.
- speed_brake_well_<side>: the closed well behind it, its walls and floor on the opaque dark Icarus_Duct (a wall this
  size on jet_mechanical would reach the stock texture's lightening holes and show sky). Its airframe stands on
  them a step lighter, on Icarus_WellDetail: ribs with rivet rows, two hydraulic lines and the actuator's anchor
  bracket (well_detail); the fixed hinge knuckles and the bracket's pin heads are on jet_mechanical. It joins the
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
    "tip_rim": 0.045,  # the free edge's rim, wider: it carries the actuator's clevis, at the tip
    # The rod's eye this far ahead of the free edge: any closer and the clevis cheeks, hanging below the panel, swing
    # aft into the hole's aft lip as the panel starts to open.
    "clevis_tip": 0.03,
    "rib": 0.012,  # the stringers' width
    "stringer": 0.085,  # each stringer this far from the actuator
    "clevis_depth": 0.045,  # the rod's eye below the panel's outer face
    "well_floor": 0.07,  # the well's floor inside the hole's upper and lower edges
    "anchor_aft": 0.04,  # the cylinder's eye aft of the hole's front edge
    "anchor_up": 0.027,  # and above the well floor
    "barrel_r": 0.022,
    "barrel_start": 0.032,  # from the cylinder's eye
    "rod_r": 0.009,
    "engage": 0.03,  # least length of rod inside the barrel, fully open
    "clear": 0.008,  # the core's structure cut back from the well, along the well's vertex normals (4.6 mm or more)
}
# The panel knuckle's and the fixed knuckles' sections about the hinge axis, degrees from aft toward out. Each piece
# keeps to the angles the other side never sweeps: the panel's turns up to 60 degrees and so must stop short of 120
# (forward, where the fixed skin lies), the fixed ones start above the 60 the panel's outer face reaches.
KNUCKLE_DEG = {"panel": (-90.0, 110.0), "fixed": (65.0, 265.0)}
# The well's airframe (well_detail), metres: two ribs across the walls and floor, each a land standing off the wall
# with a rivet row along its floor run, behind the actuator's path; and two hydraulic lines out of the lower wall
# into the anchor bracket, each (station sm, its t on the floor run, sm and t where it turns forward, its end aft of the
# anchor), t along the hinge from the actuator's plane, kept outside the cylinder's 22 mm barrel.
RIBS = {"at": (0.26, 0.43), "width": 0.02, "height": 0.008, "rivet_pitch": 0.03, "rivet_r": 0.0025, "rivet_end": 0.03}
LINES = {"r": 0.004, "sides": 5, "runs": ((0.10, -0.050, 0.058, -0.032, -0.004), (0.124, -0.062, 0.072, -0.044, 0.010))}
NAMES = {side: ("speed_brake_" + side, "speed_brake_%s_rod" % side, "speed_brake_%s_cylinder" % side) for side in "LR"}
# Triangles per brake: panel and actuator (the well counts in the fuselage_aft core's, its lip in the skin's).
BUDGET = {name: {"target": 480, "cap": 480, "exact": (name + "_visible", rod, cylinder)}
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
        self.edge_deg = (self.angle(mid[cols[0]]), self.angle(mid[cols[-1]]))
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

    def void(self, side=1):
        """The well's void, closed, Blender world space: each station's ring is the hole's edge across the skin, then
        the floor's corners; side -1 for the right."""
        rings = [[Vector((side * q.x, q.y, q.z)) for q in r + [f[1], f[0]]] for r, f in zip(self.grid, self.floor)]
        n = len(rings[0])
        faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
                 for j in range(len(rings) - 1) for k in range(n)]
        faces += [tuple(range(n))[::-1], tuple((len(rings) - 1) * n + k for k in range(n))]
        return [q for r in rings for q in r], faces


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
    # The hinge runs along the front edge's chord, lifted just outboard of its outermost point and set hinge_ahead of
    # it: every point of the panel and of the hole's front edge lies inside the axis, so opening never moves the
    # panel forward.
    edge = [patch.at(front, lo + (hi - lo) * i / 16) for i in range(17)]
    x_axis = (edge[-1] - edge[0]).normalized()
    aft = Vector((0.0, 1.0, 0.0))
    aft = (aft - x_axis * x_axis.dot(aft)).normalized()
    out = x_axis.cross(aft)
    out = out if out.x > 0 else -out
    fronts = edge + [patch.at(front, v) for v in patch.arc] + patch.grid[0]
    lift = max((q - edge[0]).dot(out) for q in fronts) + sh["hinge_lift"]
    origin = edge[0] + out * lift - aft * sh["hinge_ahead"]
    middle = (patch.at(front, patch.width / 2) - origin).dot(x_axis)

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

    # The actuator's ends: the cylinder's eye low in the well near the hinge, the rod's in a clevis across the tip
    # rim at the panel's free edge, so the actuator pushes the panel where it has the most leverage.
    g, floor = patch.grid, patch.floor
    j, fj = patch.locate(patch.s, patch.s[0] + sh["anchor_aft"])
    f_lo, f_hi = (floor[j][i].lerp(floor[j + 1][i], fj) for i in (0, 1))
    on_plane = f_lo.lerp(f_hi, (middle - (f_lo - origin).dot(x_axis)) / (f_hi - f_lo).dot(x_axis))
    anchor = hp(0.0, *plane(on_plane + section_normal(f_lo, f_hi) * sh["anchor_up"]))
    floor_n = plane(on_plane)[1]
    clevis_a, clevis_n = plane(patch.at(end - sh["clevis_tip"], patch.width / 2, sh["clevis_depth"]))
    eye = hp(0.0, clevis_a, clevis_n)

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
    # the outer face).
    rim, rib, mid = sh["rim"], sh["rib"] / 2, patch.width / 2
    us = sorted({front, front + rim, end - sh["tip_rim"], end} | {u for u in outer_u[1:-1] if front + rim < u < end - sh["tip_rim"]})
    vs = [lo, lo + rim, mid - sh["stringer"] - rib, mid - sh["stringer"] + rib, mid + sh["stringer"] - rib,
          mid + sh["stringer"] + rib, hi - rim, hi]
    frame_u, frame_v = {0, len(us) - 2}, {0, 2, 4, len(vs) - 2}

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
    # The skin's edges join the outer face to the rim, triangles zipped between their different breaks.
    rim_d = sh["frame_depth"]
    first, last_u, last_v = 0, len(outer_u) - 1, len(outer_v) - 1
    sides = [([(u, outer[i, first]) for i, u in enumerate(outer_u)], [(u, iv(i, 0, rim_d)) for i, u in enumerate(us)]),
             ([(u, outer[i, last_v]) for i, u in enumerate(outer_u)], [(u, iv(i, len(vs) - 1, rim_d)) for i, u in enumerate(us)]),
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
    # Two hinge knuckles on the axis, and the clevis cheeks either side of the rod's eye.
    half = sh["knuckle_length"] / 2
    for c in (-sh["knuckle"], sh["knuckle"]):
        knuckle(panel, c - half, c + half, KNUCKLE_DEG["panel"], 1)
    for side in (1, -1):
        t0, t1 = sorted((side * 0.0135, side * 0.0185))
        panel.box(lambda i, j, k: hp((t0, t1)[i], clevis_a + (-0.016, 0.016)[j], clevis_n + (-0.020, sh["clevis_depth"] - sh["frame_depth"])[k]), 1)

    # The lip: skin from the hole's edges lip deep. The well below it: walls on to the floor and the floor across,
    # all facing into the void, on the dark slot; the fixed knuckles either side of each panel knuckle and the
    # cylinder's anchor cheeks on jet_mechanical.
    lip_shell, well = Shell(), Shell()
    inward = patch.inward
    lip = [[q - n * sh["lip"] for q, n in zip(r, ns)] for r, ns in zip(g, inward)]
    void = (g[len(g) // 2][len(g[0]) // 2] + 0.5 * (floor[len(g) // 2][0] + floor[len(g) // 2][1])) / 2
    rows = len(g)
    for jj in range(rows - 1):
        for k in (0, -1):
            lip_shell.face([lip_shell.vert(q) for q in (g[jj][k], g[jj + 1][k], lip[jj + 1][k], lip[jj][k])], 0, toward=void)
        for quad in ([lip[jj][0], lip[jj + 1][0], floor[jj + 1][0], floor[jj][0]],
                     [lip[jj][-1], lip[jj + 1][-1], floor[jj + 1][1], floor[jj][1]],
                     [floor[jj][0], floor[jj][1], floor[jj + 1][1], floor[jj + 1][0]]):
            well.face([well.vert(q) for q in quad], 0, toward=void)
    for jj in (0, rows - 1):
        for k in range(len(g[0]) - 1):
            lip_shell.face([lip_shell.vert(q) for q in (g[jj][k], g[jj][k + 1], lip[jj][k + 1], lip[jj][k])], 0, toward=void)
        well.face([well.vert(q) for q in lip[jj] + [floor[jj][1], floor[jj][0]]], 0, toward=void)
    anchor_a, anchor_n = plane(anchor)
    well_detail(well, patch, lip, void, hp, lambda q: (q - origin).dot(x_axis) - middle, anchor_a, floor_n)
    hardware_start = len(well.faces)
    gap = 0.0005  # between each fixed knuckle and the panel's
    for c in (-sh["knuckle"], sh["knuckle"]):
        for side in (1, -1):
            t0, t1 = sorted((c + side * (half + gap), c + side * (half + gap + sh["bracket_length"])))
            knuckle(well, t0, t1, KNUCKLE_DEG["fixed"], 1)
    # The anchor bracket, on the detail slot: a base plate on the floor, a tapered cheek either side of the cylinder's
    # eye and a pin head outside each. The pin stops at the cheeks: the cylinder's eye turns between them.
    base, top = floor_n - 0.003, anchor_n + 0.012
    well.box(lambda i, j, k: hp((-0.027, 0.027)[i], anchor_a + (-0.028, 0.028)[j], (base, floor_n + 0.004)[k]), 2)
    cheek = [(-0.024, base), (0.024, base), (0.024, floor_n + 0.008), (0.010, top), (-0.010, top), (-0.024, floor_n + 0.008)]
    for side in (1, -1):
        t0, t1 = sorted((side * 0.0155, side * 0.0205))
        well.prism([[hp(t, anchor_a + a, n) for a, n in cheek] for t in (t0, t1)], 2)
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


def well_detail(well, patch, lip, void, hp, t_of, anchor_a, floor_n):
    """The well's airframe, on its detail slot (2), so the open well reads as structure rather than a void: RIBS
    standing off the walls and floor with a rivet row along each, and LINES, two hydraulic lines out of the lower
    wall, along the floor and into the anchor bracket's lower cheek (its swivel port). All of it stays low on the
    walls, clear of the panel and the actuator through the travel (check() sweeps them against the well)."""
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

    width, height = RIBS["width"], RIBS["height"]
    for sm in RIBS["at"]:
        sides = []
        for ds in (-width / 2, width / 2):
            path = section(sm + ds)
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
        # the rivet row along the rib's floor run: three-sided heads standing on its top
        _, f0, f1, _ = section(sm)
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
    for k, (sm, t_floor, sm_turn, t_turn, a_end) in enumerate(LINES["runs"]):
        foot, f0, f1, _ = section(sm)
        wall = facing(foot, f0)
        mid_wall = foot.lerp(f0, 0.5)
        path = [mid_wall - wall * 0.004, mid_wall + wall * lift,
                f0 + (f1 - f0).normalized() * 0.03 + facing(f0, f1) * lift,
                floor_point(sm, t_floor, lift), floor_point(sm_turn, t_turn, lift),
                hp(-0.0185, anchor_a + a_end, floor_n + 0.012)]
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
    both wells, so an open well shows only its own walls, as parts.open_bays clears the gear bays. Render mesh only:
    run after the hulls, which keep the whole frames."""
    import internals
    import parts

    patch = Patch(bi.PARAMS)
    cutters = []
    for side in (1, -1):
        void = bi.mesh_object("speed_brake_void", *patch.void(side))  # world space, as cut_shells wants
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
    riveted frames between them, the lap joints' angles, and the fastener rows' offset from a joint."""
    import internals
    import parts

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "textures"))
    import panels

    fr = internals.INTERNALS["frames"]
    frames = [fr["s0"] + fr["pitch"] * i for i in range(int(round((fr["s1"] - fr["s0"]) / fr["pitch"])) + 1)]
    breaks = (parts.RADOME_END, parts.FORWARD_END, parts.MID_END)
    clear = [f for f in frames if min(abs(f - b) for b in breaks) > .15]
    joints = [f for i, f in enumerate(frames) if i % panels.JOINT_EVERY == 1 and f in clear]
    return joints, [f for f in clear if f not in joints], panels.FUSELAGE_SEAMS_DEG, panels.ROW_OFFSET


def outline_on_panel_lines(p, patch):
    """Each brake is its own skin panel: its front edge on a butt joint, its aft edge one fastener row ahead of a
    riveted frame, its lower edge on a lap joint, and no joint, riveted frame or lap joint crossing the hole."""
    joints, riveted, laps, row = panel_lines(p)
    s0, s1 = patch.s[0], patch.s[-1]
    deg0, deg1 = patch.edge_deg
    problems = []
    if min(abs(s0 - j) for j in joints) > 1e-4:
        problems.append("front edge s %.4f is on no butt joint %s" % (s0, joints))
    if min(abs(s1 + row - f) for f in riveted) > 1e-4:
        problems.append("aft edge s %.4f is not %.3f m ahead of a riveted frame %s" % (s1, row, riveted))
    if min(abs(deg0 - d) for d in laps) > 0.05:
        problems.append("lower edge at %.2f deg is on no lap joint %s" % (deg0, laps))
    problems += ["s %.3f line crosses the hole" % s for s in joints + riveted if s0 + 1e-4 < s < s1 - 1e-4]
    problems += ["%.1f deg lap joint crosses the hole" % d for d in laps if deg0 + 0.05 < d < deg1 - 0.05]
    return problems


def check(icarus):
    """Open each brake through its travel in steps of parts.SWEEP_STEP with its actuator aimed: the rod stays at least
    engage inside the barrel and short of its far end, and neither the panel nor either actuator piece meets the skin
    (its lip included) or the fuselage_aft core (the well, its knuckles and anchor, the frames), nor the actuator the
    panel. The outline stays on the skin's panel lines."""
    import budget
    import parts

    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("speed brakes: over the triangle caps: " + "; ".join(over))
    problems = outline_on_panel_lines(bi.PARAMS, Patch(bi.PARAMS))
    O = bpy.data.objects
    fixed = {n: checks.tree(O[n]) for n in ("fuselage_aft", "skin_aft_L", "skin_aft_R")}
    poses, least = 0, math.inf
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
            posed = {panel.name: posed_tree(panel, pose @ panel_local), rod.name: posed_tree(rod, pivot_frame(e, axis, a)),
                     cylinder.name: posed_tree(cylinder, pivot_frame(a, axis, e))}
            for piece, others in ((panel.name, fixed), (rod.name, dict(fixed, **{panel.name: posed[panel.name]})),
                                  (cylinder.name, dict(fixed, **{panel.name: posed[panel.name]}))):
                problems += ["%s at %+.1f deg meets %s" % (piece, deg, n) for n, t in others.items() if posed[piece].overlap(t)]
            poses += 1
    if problems:
        raise ValueError("speed brakes: " + "; ".join(problems[:20]) + (" (%d in all)" % len(problems) if len(problems) > 20 else ""))
    print("speed brakes: panels and actuators clear through %d poses; the rod stays %.3f m inside the barrel; "
          "outline on the panel lines" % (poses, least))
