"""The Starfighter tip tank: a droppable store for the Tip Tank hardpoint set, one on each wingtip in place of a missile.

The F-104's tip tanks held 170 US gal each (643 L; 2,210 lb of JP-4 the pair, F-104G technical data), on a body about
5.44 m long and 0.52 m across: the 1/4-scale replica tank of the NS Modelers F-104 kit is 1,360 mm by 130 mm. Here the
body is a tangent-ogive nose, a short cylinder over the tip chord and a longer tangent-ogive tail cone, with a small
horizontal fin each side and one on top at the tail. No fin below: one there would reach the runway before the
airframe's tail strike (Stores rule 13).

The tank is a store, not part of the airframe: it lives in the Stores collection, its mesh in the mount's frame (the
hardpoint at its origin, the aircraft root's axes, Stores rule 7), so one mount serves both tips and the body is
symmetric across its vertical plane. The hardpoint sits on the tank's axis, outboard of the tip face by the radius less
EMBED, so the wing's tip face runs EMBED into the tank's side along the whole tip chord, as on the real jet.

The tank carries a stock nav lens on top and one underneath, each on a boss (LENSES): a 0.52 m body outboard of the
tip blocks the wing's own lenses outboard, so the tank's lenses light the sector while it hangs, and the plugin
(src/Icarus/TipTanks.cs) shows each the state and colour of the wing lens beside it. nav_visibility.measure holds the
tank's sector to zero blocked directions.

It wears the airframe skin with every face's UVs on one point of the skin atlas: the upper faces on a clean panel of
the wing's upper skin, the lower on its lower skin (PAINT), so the tank takes the jet's paint, two-tone where the
livery is, and the plugin hands it the livery the jet wears.
"""
import math

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import barycentric_transform

import build_icarus as bi
import solids

# The body: length and radius (the replica's 5.44 m and 0.52 m), the nose and tail cone lengths, the tail's end radius,
# and the cylinder between them. RINGS samples each cone, SEGMENTS the circumference.
TANK = {"length": 5.44, "radius": 0.26, "nose": 2.0, "tail": 2.24, "end": 0.02, "rings": (14, 12), "segments": 32}
# The tip face runs EMBED into the tank's side; the tank's cylinder is centred on the tip chord.
EMBED = 0.03
# Fins at the tail: root leading and trailing edge back from the tail's start, tip chord, sweep of the tip's leading
# edge, thickness, and each fin's tip as a distance from the axis, by its angle about the axis (degrees from
# outboard-left, +x, round through up): the two horizontal fins and the top one. The horizontal fins stay inside the
# body's own radius, so the inboard one keeps the tank's bounds outboard of the wing's nav lenses (Stores rule 14).
FIN = {"root": (0.95, 1.85), "tip_chord": 0.30, "sweep": 0.40, "thickness": 0.014, "tips": {0: 0.255, 90: 0.41, 180: 0.255}}
# The lens bosses: how far each stands proud of the cylinder, how deep it reaches in, and where along the tank, metres
# back from the hardpoint (forward of the fins, on the cylinder).
LENSES = {"proud": 0.002, "depth": 0.012, "station": -0.20}
# The skin points the paint comes from: the wing's upper and lower surface at this span and chord fraction, a clean
# panel between the spars, where every livery is one flat colour for three texels round the point
# (tools/review_tip_tanks.py paint.json). Each face's UVs spread over SPREAD of the atlas round its point (a few
# texels), so Unity can build tangents.
PAINT = {"span": 2.25, "chord": 0.40}
SPREAD = 0.0008
# Fuel and mass. 643 L of jet fuel at 0.78 kg/L is 501 kg; the shell, baffles and fins are an estimate from the
# MiG-29 mod's PTB tanks (about 120 kg empty for 1,500 L), scaled to 643 L. src/Icarus/TipTanks.cs carries the same
# fuel figure; the Unity author sets the store's full mass from both.
FUEL_KG, DRY_KG = 500.0, 70.0
CAPACITY_L = 643.5  # 170 US gal
SKIN_GAUGE = 0.004  # the shell's thickness, off the outer surface, for the internal volume
# The collider capsule: inside the body where the tip face meets it, so it never touches the wing skin's hull (A14).
CAPSULE_RADIUS = 0.22

STORES = "Stores"
NAME = "tip_tank"
KEY = "baanish_icarus_tip_tank"
BUDGET = {"tip_tank": {"target": 1900, "cap": 2000, "collection": STORES}}
CLOSEUPS = {}
TREE = {}


def profile():
    """(t, r): stations from the nose (t 0) to the tail end with the body's radius."""
    T = TANK
    R, ln, lt = T["radius"], T["nose"], T["tail"]
    cyl = T["length"] - ln - lt
    nose_rho = (R * R + ln * ln) / (2 * R)
    tail_drop = R - T["end"]
    tail_rho = (tail_drop * tail_drop + lt * lt) / (2 * tail_drop)
    n_nose, n_tail = T["rings"]
    out = []
    for k in range(n_nose + 1):
        x = ln * (1 - math.cos(0.5 * math.pi * k / n_nose))  # finer at the tip
        out.append((x, math.sqrt(max(0.0, nose_rho ** 2 - (ln - x) ** 2)) + R - nose_rho))
    out.append((ln + cyl / 2, R))
    for k in range(n_tail + 1):
        x = lt * (k / n_tail) ** 1.15
        out.append((ln + cyl + x, math.sqrt(max(0.0, tail_rho ** 2 - x * x)) + R - tail_rho))
    out[0] = (0.0, 0.0)
    return out


def radius_at(t):
    rows = profile()
    if not 0 <= t <= rows[-1][0]:
        return 0.0
    for (t0, r0), (t1, r1) in zip(rows, rows[1:]):
        if t0 <= t <= t1:
            return r0 + (r1 - r0) * (t - t0) / (t1 - t0)
    return 0.0


def nose_offset():
    """The nose's distance ahead of the hardpoint: the cylinder's middle is at the hardpoint."""
    return TANK["nose"] + (TANK["length"] - TANK["nose"] - TANK["tail"]) / 2


def tip(icarus):
    """The left wing's tip face: outer x, mid-thickness z, leading and trailing edge y (Blender world)."""
    wing = icarus.all_objects["wing_skin_L"]
    verts = [wing.matrix_world @ v.co for v in wing.data.vertices]
    outer = max(v.x for v in verts)
    face = [v for v in verts if v.x > outer - 0.001]
    return dict(x=outer, z=(max(v.z for v in face) + min(v.z for v in face)) / 2,
                le=min(v.y for v in face), te=max(v.y for v in face))


def hardpoint(icarus):
    """The left Tip Tank hardpoint, Blender world: on the tank's axis, the cylinder's middle at the tip chord's."""
    t = tip(icarus)
    return Vector((t["x"] + TANK["radius"] - EMBED, (t["le"] + t["te"]) / 2, t["z"]))


def lens_anchors():
    """Each lens's bounds centre and frame in the mount, Blender axes: the top one up, the lower one turned over."""
    height = TANK["radius"] + LENSES["proud"] + LENS_HALF_HEIGHT
    top = Matrix.Translation((0, LENSES["station"], height))
    bottom = Matrix.Translation((0, LENSES["station"], -height)) @ Matrix.Rotation(math.pi, 4, "Y")
    return {"top": top, "bottom": bottom}


# The stock lens's base sits this far under its bounds centre (fighter1_navLight: 0.0162 m tall).
LENS_HALF_HEIGHT = 0.0081


def body(segments):
    """Vertices and faces of the body of revolution, nose apex first, in the mount frame."""
    rows = profile()
    ahead = nose_offset()
    verts, faces = [Vector((0, rows[0][0] - ahead, 0))], []
    rings = []
    for t, r in rows[1:]:
        ring = []
        for k in range(segments):
            a = 2 * math.pi * k / segments
            ring.append(len(verts))
            verts.append(Vector((r * math.cos(a), t - ahead, r * math.sin(a))))
        rings.append(ring)
    first = rings[0]
    for k in range(segments):
        faces.append((0, first[(k + 1) % segments], first[k]))
    for a, b in zip(rings, rings[1:]):
        for k in range(segments):
            faces.append((a[k], a[(k + 1) % segments], b[(k + 1) % segments], b[k]))
    end = len(verts)
    verts.append(Vector((0, rows[-1][0] - ahead, 0)))
    last = rings[-1]
    for k in range(segments):
        faces.append((last[k], last[(k + 1) % segments], end))
    return verts, [away(verts, f, Vector((0, sum(verts[i].y for i in f) / len(f), 0))) for f in faces]  # out from the axis


def fins(verts, faces):
    """The tail fins as thin slabs, each root buried 0.01 m into the cone."""
    ahead = nose_offset()
    tail0 = TANK["length"] - TANK["tail"]
    le, te = (tail0 + d for d in FIN["root"])
    half = FIN["thickness"] / 2
    for degrees, reach in FIN["tips"].items():
        a = math.radians(degrees)
        out, side = Vector((math.cos(a), 0, math.sin(a))), Vector((-math.sin(a), 0, math.cos(a)))
        # (t along the tank, radial distance from the axis), root front, root back, tip back, tip front
        plan = [(le, radius_at(le) - 0.01), (te, radius_at(te) - 0.01),
                (le + FIN["sweep"] + FIN["tip_chord"], reach), (le + FIN["sweep"], reach)]
        base = len(verts)
        for s in (-1, 1):
            for t, r in plan:
                verts.append(out * r + side * (s * half) + Vector((0, t - ahead, 0)))
        centre = sum(verts[base:], Vector()) / 8
        for f in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
            faces.append(away(verts, tuple(base + i for i in f), centre))


def lens_foot():
    """The stock lens's eight-edge base, centred, as (lateral, along) pairs in Blender axes."""
    import nav_visibility

    _, lenses = nav_visibility.stock_geometry()
    verts = lenses["L"][0]
    base_y = min(v[1] for v in verts)
    foot = [v for v in verts if abs(v[1] - base_y) < 0.000002]
    if len(foot) != 8:
        raise ValueError("tip tank: expected the stock lens's eight-edge base")
    return [(-v[0], -v[2]) for v in foot]


def bosses(verts, faces):
    """A boss under each lens: the lens's foot outline from inside the body up to LENSES["proud"] above the
    cylinder, its top flat under the lens base."""
    foot = sorted(lens_foot(), key=lambda p: math.atan2(p[1], p[0]))
    for up in (1, -1):
        base = len(verts)
        for height in (TANK["radius"] - LENSES["depth"], TANK["radius"] + LENSES["proud"]):
            for x, y in foot:
                verts.append(Vector((x, y + LENSES["station"], up * height)))
        n = len(foot)
        centre = sum(verts[base:], Vector()) / (2 * n)
        for k in range(n):
            j = (k + 1) % n
            faces.append(away(verts, (base + k, base + j, base + n + j, base + n + k), centre))
        faces.append(away(verts, tuple(base + n + k for k in range(n)), centre))


def away(verts, face, centre):
    """The face wound so its normal points away from centre."""
    pts = [verts[i] for i in face]
    normal = (pts[1] - pts[0]).cross(pts[2] - pts[0])
    return face if normal.dot(sum(pts, Vector()) / len(pts) - centre) >= 0 else face[::-1]


def skin_uv(icarus, side_up):
    """The atlas UV of the wing's skin at PAINT, on its upper (side_up 1) or lower surface."""
    wing = icarus.all_objects["wing_skin_L"]
    wing.data.calc_loop_triangles()
    triangles = list(wing.data.loop_triangles)
    points = [[wing.matrix_world @ wing.data.vertices[i].co for i in t.vertices] for t in triangles]
    from mathutils.bvhtree import BVHTree

    tree = BVHTree.FromPolygons([v for tri in points for v in tri], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(triangles))],
                                all_triangles=True)
    import stations

    le, z, chord = stations.wing_at(bi.PARAMS["wing"], PAINT["span"])
    at, _, index, _ = tree.ray_cast(bi.P(le + PAINT["chord"] * chord, PAINT["span"], z + side_up * 2), Vector((0, 0, -side_up)), 5)
    if at is None:
        raise ValueError("tip tank paint: no wing skin at the paint point")
    uv = wing.data.uv_layers["UVMap"].data
    return barycentric_transform(at, *points[index], *[Vector((*uv[i].uv, 0)) for i in triangles[index].loops]).to_2d()


def paint(obj, icarus):
    """Every face's UVs round the upper or lower paint point, by which side of the axis plane it faces."""
    points = {1: skin_uv(icarus, 1), -1: skin_uv(icarus, -1)}
    layer = obj.data.uv_layers.new(name="UVMap")
    length = TANK["length"]
    for poly in obj.data.polygons:
        point = points[1 if poly.center.z >= 0 else -1]
        for i in poly.loop_indices:
            co = obj.data.vertices[obj.data.loops[i].vertex_index].co
            a = math.atan2(co.z, co.x) / math.pi  # -1 to 1 round the axis
            layer.data[i].uv = point + Vector((SPREAD * 0.5 * a, SPREAD * (co.y / length)))
    obj["paint_uv"] = [list(points[1]), list(points[-1])]


def build(p, mats, icarus):
    """The tank in the Stores collection, placed on the left tip for views and checks; its mesh is in the mount's
    frame."""
    collection = bi.collection(STORES)
    verts, faces = body(TANK["segments"])
    fins(verts, faces)
    bosses(verts, faces)
    mesh = bpy.data.meshes.new(NAME)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.validate()
    mesh.update()
    obj = bpy.data.objects.new(NAME, mesh)
    collection.objects.link(obj)
    obj.matrix_world = Matrix.Translation(hardpoint(icarus))
    bi.finish(obj, mats["body"])
    paint(obj, icarus)
    return obj


def stations_world(icarus):
    """Both Tip Tank hardpoints' world matrices, left then right (rotation 0)."""
    hp = hardpoint(icarus)
    return {"L": Matrix.Translation(hp), "R": Matrix.Translation(Vector((-hp.x, hp.y, hp.z)))}


def volume():
    """Internal volume, litres: the body less the shell's gauge."""
    rows = profile()
    v = 0.0
    for (t0, r0), (t1, r1) in zip(rows, rows[1:]):
        a, b = max(0.0, r0 - SKIN_GAUGE), max(0.0, r1 - SKIN_GAUGE)
        v += math.pi * (t1 - t0) * (a * a + a * b + b * b) / 3
    return v * 1000


def export(to_unity, icarus):
    """The tank for blockout.json: its key, the left hardpoint (world, Unity axes), the lens anchors and collider in the
    mount frame (Unity axes), and its fuel and mass."""
    anchors = {}
    for name, m in lens_anchors().items():
        anchors[name] = {"position": to_unity(m.translation), "roll_deg": 180.0 if name == "bottom" else 0.0}
    return {"key": KEY, "hardpoint_unity": to_unity(hardpoint(icarus)), "lenses": anchors,
            "length": TANK["length"], "radius": TANK["radius"], "capsule_radius": CAPSULE_RADIUS,
            "centre_unity": to_unity(Vector((0, TANK["length"] / 2 - nose_offset(), 0))),
            "fuel_kg": FUEL_KG, "dry_kg": DRY_KG, "volume_l": round(volume(), 1)}


def check(icarus):
    import budget

    problems = budget.over_caps(icarus, BUDGET)
    obj = bpy.data.objects.get(NAME)
    if obj is None or obj.users_collection[0].name != STORES:
        raise ValueError("tip tanks: no %s in the %s collection" % (NAME, STORES))
    if [m.name for m in obj.data.materials] != ["Icarus_Body"]:
        problems.append("the tank wears %s, not the skin alone" % [m.name for m in obj.data.materials])
    litres = volume()
    if litres < CAPACITY_L:
        problems.append("internal volume %.0f L is under the 170 US gal (%.0f L) it carries" % (litres, CAPACITY_L))
    # The tip face inside the tank along the whole tip chord: each corner of the tip section within the body.
    t = tip(icarus)
    hp = hardpoint(icarus)
    half = bi.PARAMS["wing"]["thickness"] * (t["te"] - t["le"]) / 2
    worst = math.inf
    for y in (t["le"], t["te"]):
        for dz in (-half, half):
            along = y - hp.y + nose_offset()
            radial = math.hypot(t["x"] - hp.x, t["z"] + dz - hp.z)
            worst = min(worst, radius_at(along) - radial)
    if worst < 0.005:
        problems.append("the tip face stands %.3f m clear of the tank's skin" % -worst)
    # The wing's own nav lenses stay outside the tank's bounds, fins and bosses included, as Stores rule 14 measures them;
    # 0.03 m covers the lens's and its fairing's half-width beyond the lens anchor.
    lens_x = max((o.matrix_world.translation.x for o in icarus.all_objects if o.get("light") == "nav" and o.name.endswith("_L")))
    inboard = hp.x + min(v.co.x for v in obj.data.vertices)
    if inboard <= lens_x + 0.03:
        problems.append("the tank's bounds reach the wing's nav lens (%.3f m apart)" % (inboard - lens_x))
    if problems:
        raise ValueError("tip tanks check: " + "; ".join(problems))
    print("tip tanks check PASS: %d triangles, %.0f L inside (%.0f L carried, %.0f kg of fuel), tip face %.3f m inside "
          "the body, hardpoint %s" % (budget.measure(icarus, BUDGET["tip_tank"]), litres, CAPACITY_L, FUEL_KG, worst,
                                      tuple(round(c, 4) for c in hp)))
