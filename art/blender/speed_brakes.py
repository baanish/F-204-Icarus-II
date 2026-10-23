"""Speed brakes as on the F-104: a flush panel low on each side of the aft fuselage, hinged at its front edge and
opening outward on the stock Airbrake, with the well it covers and a hydraulic actuator between the two.

PARAMS["speed_brake"] places the panel: the s range and height band of skin it covers, snapped to the fuselage loft's
own stations and ring columns, so the hole is whole skin faces and the panel's outer face lies on them. The parts
follow the stock aircraft (the FS-12 Revoker's panel and well, the VTOLTrainer1's actuator):

- speed_brake_<side>_visible, the panel: skin on its outer face and edges; on jet_mechanical a tray inside, with a
  rim, two stringers and the rib across them that carries the actuator's clevis, and two hinge knuckles.
- speed_brake_well_<side>: the well behind it on jet_mechanical, with the fixed hinge brackets and the actuator's
  anchor. It joins the fuselage_aft core (merge_into), as the gear wells join theirs, and faces inward.
- speed_brake_<side>_cylinder on fuselage_aft and speed_brake_<side>_rod on the hinge: the actuator, each with its
  origin at its eye and local Y along its axis toward the other's eye. The game turns only the hinge, so in Unity
  each aims at the other's eye with an AimConstraint that the Airbrake enables while the brakes are open, as the
  stock VTOLTrainer1 aims its piston (IcarusAuthor.Aero.cs BuildSpeedBrakes). aim_actuators() poses them the same
  way here, and check() opens the brakes with them.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

import build_icarus as bi
import checks

# The panel, its well and its actuator, in metres.
SHAPE = {
    "gap": 0.006,  # panel to the hole's aft, upper and lower edges
    "hinge_gap": 0.013,  # hinge axis behind the hole's front edge
    "hinge_ahead": 0.009,  # and ahead of the panel's front edge, so the fixed brackets clear the panel
    "hinge_drop": 0.008,  # hinge axis inside the front edge's outermost point, so the knuckles barely stand proud
    "knuckle": 0.06,  # each hinge this far along it from the actuator
    "knuckle_r": 0.010,
    "frame_depth": 0.020,  # the panel's edges, rim and ribs, below its outer face
    "sheet_depth": 0.004,  # the panel's inner sheet between them
    "rim": 0.025,
    "rib": 0.012,
    "stringer": 0.085,  # each stringer this far from the actuator
    "clevis_aft": 0.30,  # the rod's eye, and the rib carrying it, aft of the hinge
    "clevis_depth": 0.045,  # the rod's eye below the panel's outer face
    "well_floor": 0.07,  # the well's floor inside the hole's upper and lower edges
    "anchor_aft": 0.04,  # the cylinder's eye aft of the hinge
    "anchor_up": 0.027,  # and above the well floor
    "barrel_r": 0.022,
    "barrel_start": 0.032,  # from the cylinder's eye
    "rod_r": 0.009,
    "engage": 0.03,  # least length of rod inside the barrel, fully open
}
NAMES = {side: ("speed_brake_" + side, "speed_brake_%s_rod" % side, "speed_brake_%s_cylinder" % side) for side in "LR"}
# Triangles per brake: panel and actuator (the well counts in the fuselage_aft core's).
BUDGET = {name: {"target": 480, "cap": 480, "exact": (name + "_visible", rod, cylinder)}
          for name, rod, cylinder in NAMES.values()}
CLOSEUPS = {"speed_brake": (Vector((2.1, 6.6, -0.75)), Vector((0.62, 4.9, 0.0)))}


class Patch:
    """The skin the left brake covers, addressed in metres: sm aft of the hole's front edge, am up its arc from the
    lower edge. Points are bilinear over the loft's own facets, so the panel's outer face lies on the skin around it."""

    def __init__(self, p):
        import stations

        sb = p["speed_brake"]
        st = bi.fuselage_stations(p)
        j0, j1 = (min(range(len(st)), key=lambda j: abs(st[j] - s)) for s in (sb["s0"], sb["s1"]))
        if any(stations.carve_shapes(p, st[j]) for j in range(j0, j1 + 1)):
            raise ValueError("speed brakes: the store trough reaches their stations, where it moves the ring columns")
        rings = [bi.blended_ring(p, st[j]) for j in range(j0, j1 + 1)]
        mid = rings[len(rings) // 2]
        cols = sorted((k for k, v in enumerate(mid) if v.x > 0.05 and sb["z0"] <= v.z <= sb["z1"]), key=lambda k: mid[k].z)
        if any((b - a) % bi.RING != 1 for a, b in zip(cols, cols[1:])):
            raise ValueError("speed brakes: the ring columns of the z0..z1 band do not run in order")
        self.s = [st[j] for j in range(j0, j1 + 1)]
        self.grid = [[r[k] for k in cols] for r in rings]
        self.arc = [0.0]
        for c in range(1, len(cols)):
            self.arc.append(self.arc[-1] + sum((g[c] - g[c - 1]).length for g in self.grid) / len(self.grid))
        self.length, self.width = self.s[-1] - self.s[0], self.arc[-1]

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
        n = (self.point(sm + e, am) - self.point(sm - e, am)).cross(self.point(sm, am + e) - self.point(sm, am - e))
        return n.normalized() if n.x > 0 else -n.normalized()

    def at(self, sm, am, depth=0.0):
        return self.point(sm, am) - self.normal(sm, am) * depth


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


CELL = 0.15  # longest sheet cell along the panel


def split(a, b):
    """a, b and the fewest points between them that keep every step within CELL."""
    n = math.ceil((b - a) / CELL - 1e-9)
    return [a + (b - a) * i / n for i in range(n + 1)]


def pivot_frame(at, axis, toward):
    """An actuator piece's frame: origin at its eye, X along the hinge, Y at the other piece's eye."""
    y = (toward - at).normalized()
    return Matrix.Translation(at) @ Matrix((axis, y, axis.cross(y))).transposed().to_4x4()


def build(p, mats):
    """Both brakes: hinge, panel, actuator and well each side, and their holes cut from the fuselage skin."""
    sh = SHAPE
    patch = Patch(p)
    skin, mech = mats["body"], mats["mechanical"]
    # The hinge runs along the front edge's chord, lifted to just inside its outermost point and set hinge_ahead of
    # it: every point of the panel then lies aft of and inside the hinge, so it swings clear of the hole's front edge.
    front, lo, hi = sh["hinge_gap"] + sh["hinge_ahead"], sh["gap"], patch.width - sh["gap"]
    edge = [patch.at(front, lo + (hi - lo) * i / 8) for i in range(9)]
    x_axis = (edge[-1] - edge[0]).normalized()
    aft = Vector((0.0, 1.0, 0.0))
    aft = (aft - x_axis * x_axis.dot(aft)).normalized()
    out = x_axis.cross(aft)
    out = out if out.x > 0 else -out
    lift = max((q - edge[0]).dot(out) for q in edge) - sh["hinge_drop"]
    origin = edge[0] + out * lift - aft * sh["hinge_ahead"]
    middle = (patch.at(front, patch.width / 2) - origin).dot(x_axis)

    def hp(t, a, n):
        """t along the hinge from the actuator's plane, a aft of the hinge axis and n out from it."""
        return origin + x_axis * (middle + t) + aft * a + out * n

    def plane(q):
        """q in the actuator's plane: its (a, n)."""
        d = q - origin
        return d.dot(aft), d.dot(out)

    # The well: the hole's edges run inward along the skin's normal in each section, to a floor inside them.
    g = patch.grid

    def section_normal(a, b):
        n = Vector((0.0, 1.0, 0.0)).cross(b - a).normalized()
        return n if n.x > 0 else -n

    floor = [(r[0] - section_normal(r[0], r[1]) * sh["well_floor"], r[-1] - section_normal(r[-2], r[-1]) * sh["well_floor"])
             for r in g]
    j, fj = patch.locate(patch.s, patch.s[0] + sh["hinge_gap"] + sh["anchor_aft"])
    f_lo, f_hi = (floor[j][i].lerp(floor[j + 1][i], fj) for i in (0, 1))
    on_plane = f_lo.lerp(f_hi, (middle - (f_lo - origin).dot(x_axis)) / (f_hi - f_lo).dot(x_axis))
    anchor = hp(0.0, *plane(on_plane + section_normal(f_lo, f_hi) * sh["anchor_up"]))
    floor_n = plane(on_plane)[1]
    clevis_a, clevis_n = plane(patch.at(sh["hinge_gap"] + sh["clevis_aft"], patch.width / 2, sh["clevis_depth"]))
    eye = hp(0.0, clevis_a, clevis_n)

    panel = Shell()
    end = patch.length - sh["gap"]
    outer_u = [front + (end - front) * i / 4 for i in range(5)]
    outer_v = [lo + (hi - lo) * i / 8 for i in range(9)]
    outer = {(i, k): panel.vert(patch.at(u, v)) for i, u in enumerate(outer_u) for k, v in enumerate(outer_v)}
    for i in range(4):
        for k in range(8):
            panel.face([outer[i, k], outer[i + 1, k], outer[i + 1, k + 1], outer[i, k + 1]], 0)
    # Inside, a heightfield on jet_mechanical: the rim, stringers and clevis rib at frame depth, the sheet between.
    rim, rib, mid = sh["rim"], sh["rib"] / 2, patch.width / 2
    rib_u = sh["hinge_gap"] + sh["clevis_aft"]
    # The sheet is cut every CELL along the panel: the aft fuselage is concave lengthwise where the area-rule waist
    # ends, and a longer chord would bow out through the outer face.
    us = [front] + split(front + rim, rib_u - rib) + split(rib_u + rib, end - rim) + [end]
    vs = [lo, lo + rim, mid - sh["stringer"] - rib, mid - sh["stringer"] + rib, mid + sh["stringer"] - rib,
          mid + sh["stringer"] + rib, hi - rim, hi]
    frame_u, frame_v = {0, us.index(rib_u - rib), len(us) - 2}, {0, 2, 4, len(vs) - 2}

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
    sides = [([(u, outer[i, 0]) for i, u in enumerate(outer_u)], [(u, iv(i, 0, rim_d)) for i, u in enumerate(us)]),
             ([(u, outer[i, 8]) for i, u in enumerate(outer_u)], [(u, iv(i, len(vs) - 1, rim_d)) for i, u in enumerate(us)]),
             ([(v, outer[0, k]) for k, v in enumerate(outer_v)], [(v, iv(0, k, rim_d)) for k, v in enumerate(vs)]),
             ([(v, outer[4, k]) for k, v in enumerate(outer_v)], [(v, iv(len(us) - 1, k, rim_d)) for k, v in enumerate(vs)])]
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
    for c in (-sh["knuckle"], sh["knuckle"]):
        panel.tube([ring(hp(c + t, 0.0, 0.0), aft, out, sh["knuckle_r"], 6) for t in (-0.015, 0.015)], 1)
    for side in (1, -1):
        t0, t1 = sorted((side * 0.0135, side * 0.0185))
        panel.box(lambda i, j, k: hp((t0, t1)[i], clevis_a + (-0.022, 0.022)[j], clevis_n + (-0.020, sh["clevis_depth"] - sh["sheet_depth"])[k]), 1)

    # The well: walls from the hole's edges to the floor, the floor across, facing into the void; the fixed hinge
    # brackets either side of each knuckle, and the cylinder's anchor cheeks.
    well = Shell()
    void = (g[len(g) // 2][len(g[0]) // 2] + 0.5 * (floor[len(g) // 2][0] + floor[len(g) // 2][1])) / 2
    for j in range(len(g) - 1):
        for quad in ([g[j][0], g[j + 1][0], floor[j + 1][0], floor[j][0]], [g[j][-1], g[j + 1][-1], floor[j + 1][1], floor[j][1]],
                     [floor[j][0], floor[j][1], floor[j + 1][1], floor[j + 1][0]]):
            well.face([well.vert(q) for q in quad], 0, toward=void)
    for j in (0, len(g) - 1):
        well.face([well.vert(q) for q in g[j] + [floor[j][1], floor[j][0]]], 0, toward=void)
    hardware_start = len(well.faces)
    for c in (-sh["knuckle"], sh["knuckle"]):
        for side in (1, -1):
            t0, t1 = sorted((c + side * 0.017, c + side * 0.031))
            well.box(lambda i, j, k: hp((t0, t1)[i], (0.0005 - sh["hinge_gap"], 0.005)[j], (-0.024, 0.005)[k]), 0)
    anchor_a, anchor_n = plane(anchor)
    for side in (1, -1):
        t0, t1 = sorted((side * 0.0155, side * 0.0205))
        well.box(lambda i, j, k: hp((t0, t1)[i], anchor_a + (-0.020, 0.020)[j], (floor_n - 0.003, anchor_n + 0.014)[k]), 0)

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
    well_obj = well.realise("speed_brake_well_L", (mech,))
    hardware = well_obj.data.attributes.new(name="exterior_hardware", type="INT", domain="FACE")
    hardware.data.foreach_set("value", [int(i >= hardware_start) for i in range(len(well.faces))])
    well_obj["merge_into"] = "fuselage_aft"
    left += [rod_obj, cylinder_obj, well_obj]
    parts = left + bi.mirror_part(left)
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


def check(icarus):
    """Open each brake through its travel in steps of parts.SWEEP_STEP with its actuator aimed: the rod stays at least
    engage inside the barrel and short of its far end, and neither the panel nor either actuator piece meets the skin
    or the fuselage_aft core (the well, its brackets, the frames), nor the actuator the panel."""
    import budget
    import parts

    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("speed brakes: over the triangle caps: " + "; ".join(over))
    O = bpy.data.objects
    fixed = {n: checks.tree(O[n]) for n in ("fuselage_aft", "skin_aft_L", "skin_aft_R")}
    problems, poses, least = [], 0, math.inf
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
    print("speed brakes: panels and actuators clear through %d poses; the rod stays %.3f m inside the barrel" % (poses, least))
