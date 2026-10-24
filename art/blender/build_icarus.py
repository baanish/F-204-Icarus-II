"""F-204 Icarus II exterior generator.

Rebuilds the aircraft from PARAMS into the `Icarus` collection. Run it inside a live Blender session
(exec the file) or headless:

    blender --background --factory-startup --python art/blender/build_icarus.py

Axes follow the export contract the Unity author expects: metres, nose -Y, up +Z, left +X. Positions in PARAMS are
given as station `s` (metres aft of the radome tip), lateral `x` and height `z` above the radome tip.
"""
import math
import os
from functools import lru_cache

import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so internals.py imports in a headless run
import geometry_cache

# Station 0 (the radome tip) sits this far ahead of the origin.
S0 = 8.0

PARAMS = {
    # Fuselage body: (s, half width, z top, z bottom, top exponent). Lower half is a half ellipse whose vertical
    # radius equals the half width; a top exponent below 2 pinches the upper half into the dorsal spine. Intake
    # fairings and the wing-root fillet are blended into these sections (see "blend"), so the outer skin is one surface.
    "fuselage": [
        (0.00, 0.000, 0.03, 0.03, 2.0),
        (0.35, 0.120, 0.14, -0.08, 2.0),
        (1.00, 0.260, 0.34, -0.23, 2.0),
        (2.00, 0.400, 0.59, -0.37, 2.0),
        (3.00, 0.500, 0.72, -0.45, 2.0),
        (4.00, 0.585, 0.86, -0.51, 1.8),
        (4.90, 0.610, 1.00, -0.51, 1.6),
        (6.20, 0.640, 1.04, -0.51, 1.5),
        (8.00, 0.650, 1.04, -0.48, 1.5),
        (10.0, 0.650, 1.06, -0.42, 1.5),
        (12.2, 0.650, 1.07, -0.39, 1.5),
        (13.2, 0.640, 1.02, -0.30, 1.6),
        (14.0, 0.610, 0.94, -0.21, 1.8),  # the boat tail steepens progressively to the nozzle
        (14.6, 0.540, 0.85, -0.11, 1.9),
        (15.0, 0.450, 0.78, -0.04, 2.0),
        (15.2, 0.390, 0.76, -0.02, 2.0),  # a circle just over the nozzle, closed by an end cap
    ],
    "canopy": [  # (s, half width, z top, z bottom)
        (2.32, 0.30, 0.64, 0.50),
        (2.70, 0.34, 0.88, 0.50),
        (3.00, 0.37, 1.04, 0.52),
        (3.35, 0.39, 1.13, 0.55),
        (4.00, 0.39, 1.10, 0.62),
        (4.70, 0.37, 1.07, 0.75),
        (5.10, 0.30, 1.03, 0.85),
    ],
    # Intake fairings: (s, outer half width, z centre, half height). Each is an elliptical lobe whose inner edge sits at
    # intake_inner_x inside the body; the first row is the lip, where the lobe starts and the duct face is drawn.
    "intake": [
        (6.85, 0.955, 0.22, 0.44),
        (7.60, 0.990, 0.22, 0.44),
        (8.60, 0.990, 0.22, 0.43),
        (10.0, 0.940, 0.22, 0.40),
        (11.4, 0.830, 0.22, 0.35),
        (12.6, 0.680, 0.22, 0.26),
        (13.6, 0.090, 0.22, 0.01),  # shrinks to a point inside the body, so the fairing fades with no bulge
    ],
    # With the rows above, a 0.44 m circle at the lip whose centre is buried in the body: it stands 0.31 m proud,
    # a slim profile with the same opening area as a smaller, more protruding intake.
    "intake_inner_x": 0.075,
    "intake_lip_round": 0.15,  # metres over which the lip grows from 90% to full size
    "blend": 0.24,
    # Area-rule waist: the whole cross-section (body, fairings, spine and belly) scales radially by up to depth,
    # a cosine-squared dip over centre_s +/- half_length, so it pinches in plan and in profile. A look only: the
    # game's drag has no cross-section term.
    "area_rule": {"centre_s": 10.8, "half_length": 2.6, "depth": 0.10},  # smooth-union radius between body, intakes and fillets
    "wing_fillet": {"reach": 0.30, "half_thickness": 0.07},  # beyond the body side, along the wing root
    "probe": {"length": 1.15, "radius": 0.022, "base_radius": 0.07, "base_length": 0.40},
    # Two cone angles, like the F-104's "double-shock" centre body: a fine tip, then a steeper base. A full cone
    # sunk into the body side, with a dark bleed slot ring near its base.
    "shock_cone": {"apex_s": 6.15, "break_s": 6.90, "break_r": 0.132, "base_s": 7.40, "radius": 0.30, "x": 0.58,
                   "bleed_s": 7.22},
    # The duct runs from just inside the lip to the engine face, narrowing and turning toward the centreline:
    # (s, centre x, centre z, radius).
    "duct": [(6.86, 0.515, 0.22, 0.386), (7.80, 0.47, 0.24, 0.37), (8.80, 0.38, 0.28, 0.33), (9.60, 0.30, 0.31, 0.30)],
    # Lifting surfaces: list of (s of leading edge, x, z, chord) from root to tip, plus thickness ratio.
    # No wing fence at the crank: considered and left off, since the strake and crank vortices and the leading-edge
    # flaps already keep the outboard panel's flow attached.
    # Cranked arrow: a strake rising from the intake fairing just behind the lip (about 72 degrees), a rounded
    # crank, and a 35 degree outboard panel; trailing edge nearly unswept. The first two rows are buried in the fairing
    # so the wing meets the body without a gap; rows are (s of leading edge, x, trailing edge s) here and expanded
    # with the anhedral below.
    "wing": {
        "planform": [(8.00, 0.58, 12.05), (7.00, 0.92, 12.04), (7.48, 1.10, 12.03), (8.27, 1.40, 12.00),
                     (8.80, 1.60, 11.98), (9.20, 1.75, 11.97), (9.45, 1.93, 11.95), (10.45, 3.40, 11.75)],
        "anhedral_deg": 10.0,
        "root_z": 0.20,
        "thickness": 0.034,
    },
    # The root rows curve the leading edge concavely down into the spine, which is the fin's fillet. The lowest
    # row sits under the tapering tail's top line and ends where the body does, so no gap opens under the fin;
    # the trailing edge ends above the nozzle exit.
    "fin": {
        "sections": [(12.00, 0.0, 0.70, 3.20), (12.25, 0.0, 0.98, 3.40), (12.90, 0.0, 1.30, 2.75),
                     (13.30, 0.0, 1.60, 2.35), (14.68, 0.0, 2.88, 1.00)],
        "thickness": 0.05,
    },
    # Control surfaces cut from the wing and fin: (name, span from, span to, chord fraction from, to, end gaps). Span
    # is x on the wing, z on the fin; chord fractions are of the local full chord, and the one inside the chord is the
    # hinge line's (a leading-edge device hinges on its aft edge, the rest on their front edge). The end gaps are the
    # metres between each end of the surface and the box: the ends are streamwise, and a surface turning on a hinge
    # swept and drooped out of the span plane swings them spanwise, so each gap is the least that clears its travel
    # (parts.surface_sweep). Each becomes a hinge empty with the surface as its _visible child.
    "wing_surfaces": [
        ("lef_L", 1.956, 3.274, 0.00, 0.154, (0.006, 0.006)),  # automatic leading-edge flap, outboard of the crank
        ("flap_L", 1.086, 2.014, 0.786, 1.00, (0.018, 0.008)),
        ("aileron_L", 2.086, 3.274, 0.746, 1.00, (0.010, 0.006)),
    ],
    "fin_surfaces": [("rudder", 1.156, 2.544, 0.686, 1.00, (0.012, 0.008))],
    # A surface's hinged edge is a round nose about its hinge line, nested in a cove of the same shape in the box,
    # surface_cove_gap metres larger, so it turns through its travel with no slot opening and only skin in view.
    "surface_cove_gap": 0.003,
    # Authored travel in degrees from the built pose, the one source IcarusAuthor.Aero.cs reads (blockout.json,
    # each hinge's deflection_deg): ailerons, rudder and stabilators both ways; flaps and leading-edge flaps droop;
    # the speed brakes open outward.
    "surface_travel": {"aileron": 20, "rudder": 25, "stabilator": 15, "flap": 25, "lef": 20, "speed_brake": 60},
    "stabilator_pivot_s": 15.45,
    # Speed brakes on the aft fuselage sides, hinged at the front (speed_brakes.py builds them), each its own skin
    # panel with its edges on the panel lines (art/textures/panels.py): s0 on the butt joint at frame 13.0, s1 one
    # fastener row (15 mm) ahead of frame 13.6's rivet row; deg0 on the lower lap joint, the ring column 45 degrees
    # under the body lobe's centre, and deg1 the column just under the centre. The loft's nearest stations move onto
    # s0 and s1 (fuselage_stations); speed_brakes.check holds the outline to the panel lines.
    "speed_brake": {"s0": 13.0, "s1": 13.585, "deg0": -45.0, "deg1": -3.75},
    # Squared off: the trailing edge runs straight across at the root's trailing edge instead of the F-104's V,
    # with a small 45 degree cut at the tip's trailing corner. Left-hand sections; the stabilator is one piece, its
    # sides meeting behind the fin-tip fairing. Its root row stands surface_cove_gap outboard of the fairing's
    # radius, and the cut-out between the roots follows the fairing's outline, the same gap clear through the whole
    # travel (build_stabilator).
    "stabilator": {
        "sections": [(14.804, 0.063, 2.82, 1.886), (15.342, 1.62, 2.82, 1.348), (15.41, 1.815, 2.82, 1.085)],
        "thickness": 0.045,
    },
    # The fin-tip fairing round the stabilator pivot, as on the F-104: a body of revolution about a fore-aft axis at
    # height z, from s0 to s1, hiding the fin tip, faired into the fin's sides below by a fillet of radius fillet.
    "fin_fairing": {"z": 2.83, "s0": 14.62, "s1": 15.75, "radius": 0.06, "fillet": 0.05},
    "ventral_fin": {
        "sections": [(10.85, 0.0, -0.22, 2.25), (10.95, 0.0, -0.62, 2.05)],  # root buried above the rising belly
        "thickness": 0.05,
    },
    # Iris nozzle: a fixed shroud, then a ring of hinged petals with seals between them. Each petal hangs on its own
    # hinge empty (local X along the hinge) under one gimbal empty, so the plugin can open the iris with afterburner
    # and deflect it for thrust vectoring. The built pose is dry thrust: petals angled inward.
    "nozzle": {"z": 0.37, "shroud_start": 15.0, "ring_s": 15.30, "ring_r": 0.36, "shroud_r": 0.385, "duct_r": 0.33,
               "petals": 16, "petal_length": 0.48, "petal_root_w": 0.141, "petal_tip_w": 0.113,
               "petal_thickness": 0.012, "dry_angle_deg": -9.0, "seal_inset": 0.012},
    # Reference drawings shown as image empties: file, px per metre, pixel of the radome tip, plane.
    "references": {
        "dir": ".cache/reference",
        "top": {"file": "top.png", "px_per_m": 35.8, "nose_px": (55, 130)},
        "side": {"file": "side.png", "px_per_m": 35.5, "nose_px": (27, 127)},
        "front": {"file": "front.png", "px_per_m": 46.5, "centre_px": (159.5, 152)},
    },
}

def wing_sections(w):
    """Planform rows (s_le, x, s_te) to lifting-surface sections (s_le, x, z, chord) with the anhedral applied."""
    x0 = w["planform"][0][1]
    t = math.tan(math.radians(w["anhedral_deg"]))
    return [(le, x, w["root_z"] - (x - x0) * t, te - le) for le, x, te in w["planform"]]


RING = 96  # vertices around a fuselage section; the intakes span only a fraction of each ring
TROUGH_LIP_COLUMNS = (19 * RING // 24, 23 * RING // 24)  # 16 spans across each arch keep its chords clear of the stores
# Over the trough's ramps the keel's columns inboard of TROUGH_KEEL_COLUMN keep their even angles, and the body side's
# beyond TROUGH_SIDE_COLUMN ease back to theirs (blended_ring).
TROUGH_KEEL_COLUMN, TROUGH_SIDE_COLUMN = 3 * RING // 4 + RING // 48, 23 * RING // 24 + RING // 48
CHORD = 22  # points along each airfoil surface over the full chord; a piece of the chord takes its share, at least 6
SPAN_STEP = 0.4  # most metres between the span stations of a lifting-surface piece


def P(s, x, z):
    return Vector((x, s - S0, z))


# --- interpolation -------------------------------------------------------------------------------------------------

def pchip(xs, ys, x):
    """Monotone cubic interpolation, so stations never overshoot between table rows."""
    n = len(xs)
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    i = max(j for j in range(n - 1) if xs[j] <= x)
    t = (x - xs[i]) / h[i]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]


def resample(table, stations):
    cols = list(zip(*table))
    return [[s] + [pchip(cols[0], col, s) for col in cols[1:]] for s in stations]


def spaced(s0, s1, n, nose_bias=False):
    """n stations from s0 to s1; nose_bias packs them toward s0 for a smooth radome."""
    out = []
    for i in range(n):
        t = i / (n - 1)
        if nose_bias:
            t = 1 - math.cos(t * math.pi / 2)
        out.append(s0 + (s1 - s0) * t)
    return out


# --- mesh builders -------------------------------------------------------------------------------------------------

def superellipse(c, e):
    return math.copysign(abs(c) ** (2.0 / e), c)


def body_ring(s, hw, top, bot, e_top, e_bot=2.0, xc=0.0, zmid=None, count=144):
    """A superellipse section of count points (the canopy's)."""
    zmid = bot + hw if zmid is None else zmid
    zmid = min(zmid, top)
    ring = []
    for k in range(count):
        a = 2 * math.pi * k / count
        c, sn = math.cos(a), math.sin(a)
        e = e_top if sn >= 0 else e_bot
        x = xc + hw * superellipse(c, e)
        z = zmid + (top - zmid if sn >= 0 else zmid - bot) * superellipse(sn, e)
        ring.append(P(s, x, z))
    return ring


def loft(name, rings, tip_front=None, cap_back=False, cap_front=False):
    verts, faces = [], []
    if tip_front is not None:
        verts.append(tip_front)
    base = len(verts)
    n = len(rings[0])
    for r in rings:
        verts.extend(r)
    if tip_front is not None:
        faces += [(0, base + (k + 1) % n, base + k) for k in range(n)]
    for j in range(len(rings) - 1):
        a, b = base + j * n, base + (j + 1) * n
        faces += [(a + k, a + (k + 1) % n, b + (k + 1) % n, b + k) for k in range(n)]
    if cap_back:
        last = base + (len(rings) - 1) * n
        faces.append(tuple(last + k for k in range(n)))
    if cap_front:
        faces.append(tuple(base + k for k in range(n))[::-1])
    return mesh_object(name, verts, faces)


def airfoil(t):
    """Biconvex half thickness at chord fraction t (sharp leading and trailing edges, like the F-104)."""
    return 2.0 * t * (1.0 - t)


def lifting_surface(name, sections, thickness, thick_axis):
    """Sections: (s_le, x, z, chord) root to tip. thick_axis: 'z' for wings, 'x' for a fin."""
    ts = [0.5 * (1 - math.cos(math.pi * i / (CHORD - 1))) for i in range(CHORD)]
    rings = []
    for s_le, x, z, chord in sections:
        upper, lower = [], []
        for t in ts:
            half = airfoil(t) * thickness * chord
            dx, dz = (0.0, half) if thick_axis == "z" else (half, 0.0)
            upper.append(P(s_le + t * chord, x + dx, z + dz))
            lower.append(P(s_le + t * chord, x - dx, z - dz))
        rings.append(upper + lower[-2:0:-1])
    n = len(rings[0])
    verts = [v for r in rings for v in r]
    faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) * n + (k + 1) % n, (j + 1) * n + k)
             for j in range(len(rings) - 1) for k in range(n)]
    faces.append(tuple((len(rings) - 1) * n + k for k in range(n)))
    faces.append(tuple(range(n))[::-1])
    return mesh_object(name, verts, faces)


# --- scene plumbing ------------------------------------------------------------------------------------------------

def collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    for obj in list(col.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    return col


TARGET = None


def mesh_object(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new(name, me)
    TARGET.objects.link(obj)
    return obj


def finish(obj, mat, smooth=True):
    obj.data.materials.append(mat)
    if smooth:
        obj.data.shade_smooth()
        obj.data.set_sharp_from_angle(angle=math.radians(40))
    return obj


# --- parts ---------------------------------------------------------------------------------------------------------

def smin(a, b, k):
    """Polynomial smooth minimum: a union of two fields with a fillet of radius about k."""
    h = max(k - abs(a - b), 0.0) / k
    return min(a, b) - h * h * k * 0.25


def lobe(dx, dz, a, b_top, b_bot, e_top=2.0, e_bot=2.0):
    """Approximate signed distance to a superellipse with separate upper and lower halves."""
    b, e = (b_top, e_top) if dz >= 0 else (b_bot, e_bot)
    q = (abs(dx) / a) ** e + (abs(dz) / b) ** e
    return (q ** (1.0 / e) - 1.0) * min(a, b)


def ramp(s, s0, s1, s2, s3):
    """0 before s0, rising to 1 by s1, falling back to 0 between s2 and s3."""
    if s <= s0 or s >= s3:
        return 0.0
    if s < s1:
        return math.sin(0.5 * math.pi * (s - s0) / (s1 - s0)) ** 2
    if s > s2:
        return math.cos(0.5 * math.pi * (s - s2) / (s3 - s2)) ** 2
    return 1.0


def fuselage_shapes(p, s):
    """The lobes whose smooth union is the outer skin at station s, as (field function, centre z)."""
    hw, top, bot, e_top = [pchip([r[0] for r in p["fuselage"]], [r[i] for r in p["fuselage"]], s) for i in (1, 2, 3, 4)]
    zmid = min(bot + hw, top)
    shapes = [lambda x, z: lobe(x, z - zmid, hw, top - zmid, zmid - bot, e_top)]
    intake = p["intake"]
    if intake[0][0] <= s <= intake[-1][0]:
        _, xo, zc, hh = resample(intake, [s])[0]
        grow = 0.9 + 0.1 * min(1.0, (s - intake[0][0]) / p["intake_lip_round"])
        xi = p["intake_inner_x"]
        a, cx = (xo - xi) / 2 * grow, xi + (xo - xi) / 2
        for side in (1, -1):
            shapes.append(lambda x, z, side=side, a=a, cx=cx, zc=zc, b=hh * grow: lobe(x - side * cx, z - zc, a, b, b))
    (le0, x0, z0, c0), (le1, x1, _, c1) = wing_sections(p["wing"])[:2]
    le_at = le0 + (le1 - le0) * (hw - x0) / (x1 - x0)
    te_at = le0 + c0 + (le1 + c1 - le0 - c0) * (hw - x0) / (x1 - x0)
    f = ramp(s, le_at - 0.1, le_at + 0.6, te_at - 1.2, te_at + 0.4)
    if f > 0:
        wf = p["wing_fillet"]
        a, b = 0.05 + wf["reach"] * f, 0.02 + wf["half_thickness"] * f
        for side in (1, -1):
            # As the fillet fades it also sinks into the body, so the smooth union stops inflating the skin
            # before the lobe is dropped (a lobe resting on the skin would leave a step where it ends).
            cx = hw - 0.05 - 0.5 * (1.0 - f)
            shapes.append(lambda x, z, side=side, a=a, b=b, cx=cx: lobe(x - side * cx, z - z0, a, b, b))
    return shapes, zmid


def skin_field(p, s):
    """The outer skin's field at station s before the trough is cut (negative inside), and the ring centre's z."""
    shapes, zc = fuselage_shapes(p, s)
    # At the lip the intake meets the body almost sharply, so it reads as a slice of a circle; the fillet fades in
    # behind it.
    behind_lip = s - p["intake"][0][0]
    k = p["blend"] * (0.12 + 0.88 * min(1.0, behind_lip / 1.2)) if behind_lip >= 0 else p["blend"]

    def field(x, z):
        d = shapes[0](x, z)
        for f in shapes[1:]:
            d = smin(d, f(x, z), k)
        return d

    return field, zc


@geometry_cache.ring
def blended_ring(p, s, angles=None):
    skin, zc = skin_field(p, s)
    import stations

    carves = stations.carve_shapes(p, s)  # the conformal trough, cut out of the union

    def field(x, z):
        d = skin(x, z)
        return max(d, -min(c(x, z) for c in carves)) if carves else d

    ar = p["area_rule"]
    u = (s - ar["centre_s"]) / ar["half_length"]
    squeeze = 1.0 - ar["depth"] * math.cos(0.5 * math.pi * u) ** 2 if abs(u) < 1 else 1.0

    @lru_cache(maxsize=None)
    def radius(a, sample):
        c, sn = math.cos(a), math.sin(a)
        r_out, step, r = 0.0, 0.02, 0.0
        inside = sample(0.0, zc) < 0
        while r < 3.0:  # keep the outermost inside-to-outside crossing, so concave fillets resolve
            r_next = r + step
            now = sample(r_next * c, zc + r_next * sn) < 0
            if inside and not now:
                lo, hi = r, r_next
                for _ in range(20):
                    mid = 0.5 * (lo + hi)
                    if sample(mid * c, zc + mid * sn) < 0:
                        lo = mid
                    else:
                        hi = mid
                r_out = 0.5 * (lo + hi)
            inside, r = now, r_next
        return r_out

    sample_angles = angles if angles is not None else [2 * math.pi * i / RING for i in range(RING)]
    if angles is None:
        # Fixed lip columns stop the trough wandering between angular samples from ring to ring.
        def on_skin(a):
            r = radius(a, skin)
            return min(c(r * math.cos(a), zc + r * math.sin(a)) for c in carves)

        lips = []
        if carves:
            samples = [(sample_angles[i], on_skin(sample_angles[i])) for i in range(3 * RING // 4, RING)]
            samples.append((2 * math.pi, on_skin(2 * math.pi)))
            for (a, da), (b, db) in zip(samples, samples[1:]):
                if (da < 0) != (db < 0):
                    for _ in range(20):
                        mid = (a + b) / 2
                        if (on_skin(mid) < 0) == (da < 0):
                            a = mid
                        else:
                            b = mid
                    lips.append((a + b) / 2)
        ramp = stations.ramp_lips(p, s)
        if ramp and len(lips) != 2:
            # Near a ramp's tip and past it the lip columns follow its walls' edges, easing back to their even
            # angles, so the ramp ends without a fan of skewed faces.
            edges, hold, _ = ramp
            angle = lambda q: math.atan2(q[1] - zc, q[0]) % (2 * math.pi)
            evens = sorted(2 * math.pi * i / RING for i in TROUGH_LIP_COLUMNS)
            lips = sorted(even + hold * (angle(q) - even) for even, q in zip(evens, sorted(edges, key=angle)))
        if len(lips) == 2:
            # End the redistribution at the body side. Moving its upper skin columns with the trough lips
            # twists the intake fairing when the trough ends and those columns return to uniform angles. Over the
            # ramps the keel's columns keep their even angles: the nose gear doors take their outline from them
            # (gear.door_patch). The body side's columns ease back to theirs along the whole ramp, not only past its
            # tip, where they would twist the wing root's fillet.
            anchors = [(3 * RING // 4, 1.5 * math.pi), (TROUGH_LIP_COLUMNS[0], lips[0]),
                       (TROUGH_LIP_COLUMNS[1], lips[1]), (RING, 2 * math.pi)]
            if ramp:
                even = 2 * math.pi * TROUGH_SIDE_COLUMN / RING
                side = (lips[1] + 2 * math.pi) / 2
                anchors[1:1] = [(TROUGH_KEEL_COLUMN, 2 * math.pi * TROUGH_KEEL_COLUMN / RING)]
                anchors[-1:-1] = [(TROUGH_SIDE_COLUMN, side + ramp[2] * (even - side))]
            for (i0, a), (i1, b) in zip(anchors, anchors[1:]):
                for i in range(i0, i1):
                    angle = a + (b - a) * (i - i0) / (i1 - i0)
                    sample_angles[i % RING] = angle
                    sample_angles[(3 * RING // 2 - i) % RING] = (math.pi - angle) % (2 * math.pi)
    ring = []
    for a in sample_angles:
        c, sn = math.cos(a), math.sin(a)
        r_out = radius(a, field)
        ring.append(P(s, r_out * c * squeeze, zc + r_out * sn * squeeze))
    return ring


def fuselage_stations(p):
    lip = p["intake"][0][0]
    out = (spaced(0.0, 3.0, 14, nose_bias=True)[1:] + spaced(3.0, lip - 0.004, 20)[1:]
           + spaced(lip, lip + 0.6, 8) + spaced(lip + 0.6, p["fuselage"][-1][0], 50)[1:])
    import stations

    for lo, hi, rings in stations.ramp_stations(p):  # the trough's ramps take their own rings
        out = sorted([s for s in out if not lo - 0.06 < s < hi + 0.06] + rings)
    for edge in (p["speed_brake"]["s0"], p["speed_brake"]["s1"]):  # the brakes' holes are whole skin faces
        out[min(range(len(out)), key=lambda i: abs(out[i] - edge))] = edge
    return out


@geometry_cache.ring
def skin_ring(p, s):
    """Section of the rendered loft, so internal fits cannot bridge a differently sampled SDF contour."""
    stations = fuselage_stations(p)
    if s <= stations[0] or s >= stations[-1]:
        return blended_ring(p, s)
    i = next(i for i, end in enumerate(stations[1:]) if s <= end)
    a, b = stations[i:i + 2]
    t = (s - a) / (b - a)
    return [v.lerp(w, t) for v, w in zip(blended_ring(p, a), blended_ring(p, b))]


def build_fuselage(p, mat, duct_mat):
    table = p["fuselage"]
    lip = p["intake"][0][0]
    stations = fuselage_stations(p)
    rings = [blended_ring(p, s) for s in stations]
    obj = loft("fuselage", rings, tip_front=P(0.0, 0.0, table[0][2]))  # open at the tail: the nozzle shroud fills it
    finish(obj, mat)
    lip_columns = set(TROUGH_LIP_COLUMNS) | {3 * RING // 2 - i for i in TROUGH_LIP_COLUMNS}
    import stations as stores

    for edge in obj.data.edges:
        a, b = [i - 1 for i in edge.vertices]
        if a >= 0 and a % RING == b % RING and a % RING in lip_columns:
            if all(stores.carve_shapes(p, stations[i // RING]) for i in (a, b)):
                edge.use_edge_sharp = True
    obj.data.materials.append(duct_mat)
    # The faces between the last ring ahead of the lip and the lip itself would close the intakes; delete them so
    # the openings look into the ducts.
    j = stations.index(lip) - 1
    zc = fuselage_shapes(p, lip)[1]
    # Angular redistribution alone is not an intake opening. Compare the skin at the lip ring's own angles.
    ahead = blended_ring(p, stations[j], [math.atan2(v.z - zc, v.x) for v in rings[j + 1]])
    step = [(Vector((b.x, b.z)) - Vector((a.x, a.z))).length for a, b in zip(ahead, rings[j + 1])]
    # A stationary endpoint belongs to the skin bridge between the trough and the intake.
    opening = [RING + j * RING + k for k in range(RING) if min(step[k], step[(k + 1) % RING]) > 0.005]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in opening], context="FACES_ONLY")
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def inward_fix(obj, axis_point):
    """Flip the mesh if its first wall face points away from axis_point, so the inside is the visible side."""
    poly = obj.data.polygons[0]
    if poly.normal.dot(axis_point - poly.center) < 0:
        obj.data.flip_normals()


def build_probe(p, mat):
    """Pitot boom: a rounded tip, a straight boom, and a base that flares smoothly into the radome."""
    pr = p["probe"]
    z = p["fuselage"][0][2]
    tip = -pr["length"]
    profile = [(tip, 0.008), (tip + 0.015, 0.016), (tip + 0.05, pr["radius"]), (-pr["base_length"], pr["radius"])]
    flare = 6
    for i in range(1, flare + 1):
        t = i / flare
        profile.append((-pr["base_length"] + t * (pr["base_length"] + 0.05),
                        pr["radius"] + (pr["base_radius"] - pr["radius"]) * t * t * (3 - 2 * t)))
    profile.append((0.30, pr["base_radius"]))
    sides = 32
    rings = [[P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / sides for k in range(sides)]]
             for s, r in profile]
    return finish(loft("probe", rings, tip_front=P(-pr["length"] - 0.02, 0.0, z)), mat)


def section_at(sections, u, axis):
    """Section (s_le, x, z, chord) interpolated at span position u (x on a wing, z on a fin)."""
    key = 1 if axis == "x" else 2
    for a, b in zip(sections, sections[1:]):
        if a[key] <= u <= b[key] + 1e-9:
            t = (u - a[key]) / (b[key] - a[key])
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
    raise ValueError("span position %.3f outside the sections" % u)


def span_stations(sections, axis, u0, u1, breaks=()):
    """Span positions from u0 to u1 (x on a wing, z on a fin): every section row and break between them, so the
    planform's kinks stay exact, with the gaps subdivided to at most SPAN_STEP."""
    key = 1 if axis == "x" else 2
    marks = sorted({u0, u1} | {u for u in [s[key] for s in sections] + list(breaks) if u0 < u < u1})
    out = [u0]
    for a, b in zip(marks, marks[1:]):
        n = max(1, math.ceil((b - a) / SPAN_STEP - 1e-9))
        out += [a + (b - a) * i / n for i in range(1, n + 1)]
    return out


def strip(name, sections, stations, thickness, axis, count=None, clamp=False):
    """A closed piece of a lifting surface. stations: (u, f0, f1) along the span; each ring spans chord fractions
    f0..f1 of the full-chord airfoil, so neighbouring pieces share one airfoil, with count points a side (by default
    in proportion to the widest span of chord). Two stations at the same u with different fractions make the wall at
    a cutout's end. With clamp, every ring samples the full chord and the ends of each such wall, and pulls the points
    outside its own f0..f1 onto its own ends, so a ring cut short shares its points with the full rings beside it and
    one piece runs on through the cut."""
    count = count or max(6, round(CHORD * max(f1 - f0 for _, f0, f1 in stations)))
    full = [0.5 * (1 - math.cos(math.pi * i / (count - 1))) for i in range(count)]
    if clamp:
        span = [u for u, _, _ in stations]
        full = sorted(set(full) | {f for u, f0, f1 in stations if span.count(u) > 1 for f in (f0, f1)})
    rings = []
    for u, f0, f1 in stations:
        s_le, x, z, chord = section_at(sections, u, axis)
        ts = [min(max(t, f0), f1) for t in full] if clamp else [f0 + (f1 - f0) * t for t in full]
        upper, lower = [], []
        for t in ts:
            half = max(airfoil(t) * thickness * chord, 0.0015)
            d = Vector((0.0, 0.0, half)) if axis == "x" else Vector((half, 0.0, 0.0))
            base = P(s_le + t * chord, x, z)
            upper.append(base + d)
            lower.append(base - d)
        rings.append(upper + lower[::-1])
    return welded(loft(name, rings, cap_back=True, cap_front=True))


def welded(obj):
    """Weld the points two rings at one u share, so the wall between them carries no zero-area faces (the importer
    drops them and the slot's triangles no longer match the export)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(obj.data)
    bm.free()
    return obj


# --- control surfaces ----------------------------------------------------------------------------------------------
# A control surface's hinged edge is a round nose about its hinge line, and the box it is cut from ends in a cove of
# the same shape surface_cove_gap larger, both swept along the span: as the surface turns, its nose stays the same
# distance inside the cove, so the gap is the same at every deflection and the skin covers it, as on a real wing.
# Every ring lies in a span plane (x on the wing, z on the fin), the nose and cove points on circles about the hinge
# line square to it, so the surfaces' ends and the box's cut-out ends are span planes too.

SURFACE_ARC = 7  # points round a surface's nose between its two skins
BOX_SKIN = 13  # points along each face of the box between its leading and trailing closures
BOX_CLOSURE = 10  # points round the box's leading or trailing closure: a cove, or the airfoil round its edge


def skin_point(sections, u, t, side, thickness, axis):
    """The airfoil's upper (side 1) or lower (side -1) skin at chord fraction t and span u."""
    s_le, x, z, chord = section_at(sections, u, axis)
    half = side * max(airfoil(t) * thickness * chord, 0.0015)
    return P(s_le + t * chord, x, z) + (Vector((0.0, 0.0, half)) if axis == "x" else Vector((half, 0.0, 0.0)))


def hinge_line(sections, cut, axis):
    """A cut's hinge line: its ends on the chord line at the hinge fraction and the surface's ends, and the hinge
    frame (X along it, Y as close to aft as it allows). aft: the surface lies aft of its hinge; reach: the span the
    box's cove runs, the surface's and its end gaps."""
    _, u0, u1, f0, f1, (gap0, gap1) = cut
    f = f1 if f0 == 0.0 else f0
    a, b = [P(s_le + f * chord, x, z) for s_le, x, z, chord in (section_at(sections, u, axis) for u in (u0, u1))]
    frame = hinge_frame(a, b)
    return {"a": a, "b": b, "aft": f0 > 0.0, "key": 0 if axis == "x" else 2, "reach": (u0 - gap0, u1 + gap1),
            "X": frame.col[0].xyz, "Y": frame.col[1].xyz, "Z": frame.col[2].xyz}


def hinge_at(h, u):
    """The point of the hinge line at span u."""
    k = h["key"]
    return h["a"] + (h["b"] - h["a"]) * ((u - h["a"][k]) / (h["b"][k] - h["a"][k]))


def hinge_fraction(sections, h, u, axis):
    s_le, _, _, chord = section_at(sections, u, axis)
    return (hinge_at(h, u).y + S0 - s_le) / chord


def polar(h, p, u):
    """Distance of p from the hinge line and its angle about it (from Y towards Z)."""
    d = p - hinge_at(h, u)
    return math.hypot(d.dot(h["Y"]), d.dot(h["Z"])), math.atan2(d.dot(h["Z"]), d.dot(h["Y"]))


def arc(h, u, start, end, through, count):
    """count points strictly between the points start and end, round the hinge line the way that passes the angle
    through, the radius blending from one end's to the other's, each slid along the hinge line into span plane u."""
    (r0, a0), (r1, a1) = polar(h, start, u), polar(h, end, u)
    sweep = (a1 - a0) % (2 * math.pi)
    if (through - a0) % (2 * math.pi) > sweep:
        sweep -= 2 * math.pi
    out = []
    for i in range(1, count + 1):
        r, a = r0 + (r1 - r0) * i / (count + 1), a0 + sweep * i / (count + 1)
        d = (h["Y"] * math.cos(a) + h["Z"] * math.sin(a)) * r
        out.append(hinge_at(h, u) + d - h["X"] * (d[h["key"]] / h["X"][h["key"]]))
    return out


def nose_radius(sections, h, u, thickness, axis):
    """The surface's nose radius at span u: as far from the hinge line as its skins at the hinge."""
    t = hinge_fraction(sections, h, u, axis)
    return max(polar(h, skin_point(sections, u, t, side, thickness, axis), u)[0] for side in (1, -1))


def cove_lips(sections, h, u, thickness, axis, gap):
    """Chord fractions (upper, lower) where the box's skins meet its cove round the hinge at span u."""
    radius = nose_radius(sections, h, u, thickness, axis) + gap
    t_hinge = hinge_fraction(sections, h, u, axis)
    lips = []
    for side in (1, -1):
        near, far = t_hinge, max(0.0, t_hinge - 0.5) if h["aft"] else min(1.0, t_hinge + 0.5)
        for _ in range(48):
            mid = (near + far) / 2
            if polar(h, skin_point(sections, u, mid, side, thickness, axis), u)[0] > radius:
                far = mid
            else:
                near = mid
        lips.append(far)
    return tuple(lips)


def box_span(sections, axis, hinges):
    """Span stations of a fixed box: its sections, and the ends of its cut-outs."""
    key = 1 if axis == "x" else 2
    u0, u1 = sections[0][key], sections[-1][key]
    return span_stations(sections, axis, u0, u1, [u for h in hinges.values() for u in h["reach"] if u0 < u < u1])


def box(name, sections, thickness, axis, hinges, cove_gap):
    """The fixed box of a lifting surface, with a cove round each control surface's hinge over the cut-out's reach.
    Each ring runs: upper skin, trailing closure, lower skin, leading closure. A closure is the cove where a surface
    is cut out, and the airfoil round its edge elsewhere; the skins end at the cove's lips, and between cut-outs at
    fractions blended from the lips either side, so at a cut-out's end two rings at one u share their skins and the
    closures between them make its end wall."""

    def open_cut(u, aft, inclusive):
        for name_, h in hinges.items():
            a, b = h["reach"]
            if h["aft"] == aft and (a <= u <= b if inclusive else a < u < b):
                return name_
        return None

    stations = box_span(sections, axis, hinges)
    splits = {}
    for aft, default in ((True, 0.85), (False, 0.15)):
        known = {}
        for u in stations:
            name_ = open_cut(u, aft, True)
            if name_:
                known[u] = cove_lips(sections, hinges[name_], u, thickness, axis, cove_gap)
        for u in stations:
            below = [v for v in known if v <= u]
            above = [v for v in known if v >= u]
            if not known:
                splits[u, aft] = (default, default)
            elif not below or not above:
                splits[u, aft] = known[max(below) if below else min(above)]
            else:
                a, b = max(below), min(above)
                w = 0.0 if a == b else (u - a) / (b - a)
                splits[u, aft] = tuple(x + (y - x) * w for x, y in zip(known[a], known[b]))

    half = BOX_CLOSURE // 2
    rings = []
    for u in stations:
        # at a cut-out's end, the ring outside it then the one inside, or the other way round
        for aft_cut, fore_cut in dict.fromkeys([(open_cut(v, True, False), open_cut(v, False, False))
                                                for v in (u - 1e-6, u + 1e-6)]):
            (fu, fl), (au, al) = splits[u, False], splits[u, True]
            skin = lambda t, side: skin_point(sections, u, t, side, thickness, axis)
            upper = [skin(fu + (au - fu) * i / (BOX_SKIN - 1), 1) for i in range(BOX_SKIN)]
            lower = [skin(fl + (al - fl) * i / (BOX_SKIN - 1), -1) for i in range(BOX_SKIN)][::-1]
            if aft_cut:
                trailing = arc(hinges[aft_cut], u, upper[-1], lower[0], math.pi, BOX_CLOSURE)
            else:
                trailing = ([skin(au + (1 - au) * i / half, 1) for i in range(1, half + 1)]
                            + [skin(1 - (1 - al) * i / half, -1) for i in range(half)])
            if fore_cut:
                leading = arc(hinges[fore_cut], u, lower[-1], upper[0], 0.0, BOX_CLOSURE)
            else:
                leading = ([skin(fl * (1 - i / half), -1) for i in range(1, half + 1)]
                           + [skin(fu * i / half, 1) for i in range(half)])
            rings.append(upper + trailing + lower + leading)
    return welded(loft(name, rings, cap_back=True, cap_front=True))


def hinge_frame(a, b):
    """Hinge empty matrix: origin at a, X along the hinge a->b, Y as close to aft as the hinge allows.

    Wing hinges run inboard to outboard, so Z is up on the left and down on the right: a positive rotation about X
    raises a left trailing edge and lowers a right one, and droops a right leading-edge flap. The rudder's X runs
    up the fin, so positive moves its trailing edge to the right (-X)."""
    x_axis = (b - a).normalized()
    y_axis = Vector((0.0, 1.0, 0.0))
    y_axis = (y_axis - x_axis * x_axis.dot(y_axis)).normalized()
    z_axis = x_axis.cross(y_axis)
    return Matrix.Translation(a) @ Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()


def hinged(name, mesh_obj, frame, parent=None):
    """Re-express mesh_obj in the hinge frame and hang it from a new hinge empty called name."""
    mesh_obj.name = mesh_obj.data.name = name + "_visible"  # frees the name for the hinge
    hinge = empty(name, frame, parent)
    hinge["hinge_axis"] = "X"
    mesh_obj.data.transform(frame.inverted())
    mesh_obj.parent = hinge
    return [hinge, mesh_obj]


def surface_travel(p, name):
    """The authored travel of a hinged surface, by its name less the side suffix (PARAMS["surface_travel"])."""
    return p["surface_travel"][name[:-2] if name.endswith(("_L", "_R")) else name]


def control_surface(p, cut, sections, h, thickness, axis, box_stations, mat):
    """A hinged surface from its hinge line to its trailing edge (or, for a leading-edge device, from its leading edge
    to its hinge line), its hinged edge a round nose. Its rings stand at its ends and at the box's stations between,
    so nose and cove are drawn alike."""
    name, u0, u1, f0, f1, _ = cut
    count = max(6, round(CHORD * (f1 - f0)))
    rings = []
    for u in [u0] + [v for v in box_stations if u0 < v < u1] + [u1]:
        t = hinge_fraction(sections, h, u, axis)
        skin = lambda f, side: skin_point(sections, u, f, side, thickness, axis)
        if h["aft"]:
            upper = [skin(t + (1 - t) * i / (count - 1), 1) for i in range(count)]
            lower = [skin(1 - (1 - t) * i / (count - 1), -1) for i in range(count)]
            rings.append(upper + lower + arc(h, u, lower[-1], upper[0], math.pi, SURFACE_ARC))
        else:
            upper = [skin(t * i / (count - 1), 1) for i in range(count)]
            lower = [skin(t * (1 - i / (count - 1)), -1) for i in range(count)]
            rings.append(upper + arc(h, u, upper[-1], lower[0], 0.0, SURFACE_ARC) + lower)
    obj = finish(loft(name, rings, cap_back=True, cap_front=True), mat)
    parts = hinged(name, obj, hinge_frame(h["a"], h["b"]))
    parts[0]["deflection_deg"] = surface_travel(p, name)
    return parts


def build_box(p, name, sections, thickness, axis, cuts, mats):
    """A fixed box and the control surfaces cut from it."""
    hinges = {cut[0]: hinge_line(sections, cut, axis) for cut in cuts}
    parts = [finish(box(name, sections, thickness, axis, hinges, p["surface_cove_gap"]), mats["body"])]
    stations = box_span(sections, axis, hinges)
    for cut in cuts:
        parts += control_surface(p, cut, sections, hinges[cut[0]], thickness, axis, stations, mats["body"])
    return parts


def mirror_part(parts):
    """Right-hand twins of left-hand parts, mirrored across x = 0. A twin hinge is rebuilt from the mirrored hinge
    line, so its X still runs inboard to outboard and its frame stays right-handed."""
    flip = Matrix.Scale(-1, 4, (1, 0, 0))
    out = []
    for obj in parts:
        if obj.type == "EMPTY":
            a = obj.matrix_world.translation.copy()
            b = a + obj.matrix_world.col[0].xyz
            twin = empty(obj.name.replace("_L", "_R"), hinge_frame(flip @ a, flip @ b))
            for key in obj.keys():  # hinge_axis, deflection_deg
                twin[key] = obj[key]
            out.append(twin)
    for obj in parts:
        if obj.type != "MESH":
            continue
        twin = obj.copy()
        twin.data = obj.data.copy()
        twin.name = twin.data.name = obj.name.replace("_L", "_R")
        TARGET.objects.link(twin)
        if obj.parent is not None:
            parent = bpy.data.objects[obj.parent.name.replace("_L", "_R")]
            twin.data.transform(parent.matrix_world.inverted() @ flip @ obj.parent.matrix_world)
            twin.parent = parent
        else:
            twin.data.transform(flip)
        twin.data.flip_normals()
        out.append(twin)
    return out


def build_surfaces(p, mats):
    left = build_box(p, "wing_L", wing_sections(p["wing"]), p["wing"]["thickness"], "x", p["wing_surfaces"], mats)
    parts = left + mirror_part(left)
    parts += build_box(p, "fin", p["fin"]["sections"], p["fin"]["thickness"], "z", p["fin_surfaces"], mats)
    parts.append(build_fin_fairing(p, mats["body"]))
    vf = p["ventral_fin"]
    parts.append(finish(lifting_surface("ventral_fin", vf["sections"], vf["thickness"], "x"), mats["body"]))
    return parts + build_stabilator(p, mats)


def build_stabilator(p, mats):
    """The all-moving stabilator as one piece, tip to tip, cut round the fin-tip fairing. Its root wall stands beside
    the fairing, and behind the fairing's tail the cut-out runs from the root to the centreline through span stations
    at the corners of the fairing's outline offset by surface_cove_gap, each at the chord where the stabilator clears
    the fairing by that gap through its whole travel; where the straight edge between two stations dips closer, both
    move back."""
    st, gap = p["stabilator"], p["surface_cove_gap"]
    sections = [(s, -x, z, c) for s, x, z, c in reversed(st["sections"])] + st["sections"]
    s_le, root_x, z, chord = st["sections"][0]
    pivot = P(p["stabilator_pivot_s"], 0.0, z)
    turns = [Matrix.Rotation(math.radians(a), 3, "X") for a in sweep_angles(surface_travel(p, "stabilator"))]
    outline, axis_z = fairing_outline(p), p["fin_fairing"]["z"]

    def clearance(x, s, skins=True):
        """Least distance from the fairing, over the travel, of the stabilator's front edge at span x and chord
        position s: its wall from skin to skin, and with skins, the skins just behind it."""
        t = (s - s_le) / chord
        lower, upper = [skin_point(sections, root_x, t, side, st["thickness"], "x") for side in (-1, 1)]
        points = [lower.lerp(upper, i / 6) for i in range(7)]
        if skins:
            points += [skin_point(sections, root_x, t + 0.005 * i / chord, side, st["thickness"], "x")
                       for i in range(1, 9) for side in (-1, 1)]
        for v in points:
            v.x = x
        return min(fairing_distance(outline, axis_z, pivot + turn @ (v - pivot)) for turn in turns for v in points)

    def least(clear, lo, hi):
        """The least value in lo..hi at which clear holds, which it does at hi."""
        if clear(lo):
            return lo
        for _ in range(32):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if clear(mid) else (mid, hi)
        return hi

    widest = max(r for _, r in outline)
    tail = outline[max(i for i, (_, r) in enumerate(outline) if r == widest):]  # from its widest point aft

    def cut_at(u):
        return least(lambda s: clearance(u, s) >= gap, tail[0][0], s_le + chord)

    spans = [0.0] + [u for u in (miter(a, b, c, gap)[1] for a, b, c in zip(tail, tail[1:], tail[2:])) if u < root_x]
    contour = [[u, cut_at(u)] for u in sorted(spans)] + [[root_x, cut_at(root_x - 1e-4)]]
    for _ in range(20):
        shorts = []
        for a, b in zip(contour, contour[1:]):
            short = gap - min(clearance(a[0] + (b[0] - a[0]) * i / 8, a[1] + (b[1] - a[1]) * i / 8)
                              for i in range(1, 8))
            shorts.append(short)
            if short > 1e-5:
                a[1], b[1] = a[1] + short + 1e-4, b[1] + short + 1e-4
        if max(shorts) <= 1e-5:
            break
    else:
        raise ValueError("stabilator cut-out: the edge between its stations stays closer than the gap to the fairing: "
                         + ", ".join("(%.4f, %.4f)" % tuple(c) for c in contour) + " short by "
                         + ", ".join("%.5f" % s for s in shorts))

    def front(u):
        """The chord fraction where the stabilator starts at span u inside its root."""
        u = abs(u)
        for (ua, sa), (ub, sb) in zip(contour, contour[1:]):
            if ua <= u <= ub:
                return (sa + (sb - sa) * (u - ua) / (ub - ua) - s_le) / chord
        raise ValueError("span %.4f outside the stabilator's cut-out" % u)

    stations = []
    tip = sections[-1][1]
    for u in span_stations(sections, "x", -tip, tip, [w * u for u, _ in contour for w in (-1, 1)]):
        if abs(abs(u) - root_x) < 1e-9:  # the root wall: the full ring outside it, the cut one inside
            for f0 in ((0.0, front(u)) if u < 0 else (front(u), 0.0)):
                stations.append((u, f0, 1.0))
        else:
            stations.append((u, front(u) if abs(u) < root_x else 0.0, 1.0))
    obj = strip("stabilator", sections, stations, st["thickness"], "x", clamp=True)
    wall_end, steps = contour[-1][1], math.ceil((contour[-1][1] - s_le) / 0.01)
    if min(clearance(root_x, s_le + (wall_end - s_le) * i / steps, skins=False) for i in range(steps + 1)) < gap - 1e-6:
        raise ValueError("stabilator root %.3f m out stands closer than %.3f m to the fin-tip fairing" % (root_x, gap))
    print("stabilator cut-out (span, s): " + ", ".join("(%.4f, %.4f)" % (u, s) for u, s in contour))
    obj = finish(obj, mats["body"])
    parts = hinged("stabilator", obj, Matrix.Translation(pivot))
    parts[0]["deflection_deg"] = surface_travel(p, "stabilator")
    return parts


def sweep_angles(travel, step=0.5):
    """Angles from -travel to travel, at most step degrees apart."""
    n = math.ceil(2 * travel / step)
    return [-travel + 2 * travel * i / n for i in range(n + 1)]


def miter(a, b, c, gap):
    """The corner at b of the outline a-b-c, (s, radius) points, offset outward by gap: the point gap from both of
    its edges."""
    def normal(p, q):
        ds, dr = q[0] - p[0], q[1] - p[1]
        length = math.hypot(ds, dr)
        return -dr / length, ds / length

    (n1s, n1r), (n2s, n2r) = normal(a, b), normal(b, c)
    ms, mr = n1s + n2s, n1r + n2r
    scale = gap / (ms * n1s + mr * n1r)
    return b[0] + ms * scale, b[1] + mr * scale


def fairing_outline(p):
    """The fin-tip fairing's outline, (s, radius) from its nose point on the axis to its tail point."""
    f = p["fin_fairing"]
    r, s0, s1 = f["radius"], f["s0"], f["s1"]
    nose, tail = 0.10, 0.10
    out = [(s0, 0.0)]
    out += [(s0 + nose * (1 - math.cos(math.radians(d))), 0.97 * r * math.sin(math.radians(d))) for d in (25, 50, 70, 90)]
    out += [(s0 + 0.38, 0.97 * r), (s0 + 0.53, r), (s1 - 0.25, r), (s1 - 0.13, 0.97 * r)]
    out += [(s1 - tail + tail * math.sin(math.radians(d)), 0.97 * r * math.cos(math.radians(d))) for d in (30, 55, 75)]
    return out + [(s1, 0.0)]


def fairing_distance(outline, z, v):
    """Distance from the point v to the fin-tip fairing's body of revolution, its outline about an axis at height z,
    negative inside. Its sections are drawn inside their circles, and its fillets into the fin lie under it, closer in
    than the stabilator reaches."""
    s, rho = v.y + S0, math.hypot(v.x, v.z - z)
    best, inside = math.inf, False
    for (sa, ra), (sb, rb) in zip(outline, outline[1:]):
        ds, dr = sb - sa, rb - ra
        t = max(0.0, min(1.0, ((s - sa) * ds + (rho - ra) * dr) / (ds * ds + dr * dr)))
        best = min(best, math.hypot(s - sa - t * ds, rho - ra - t * dr))
        inside = inside or (sa <= s <= sb and rho < ra + dr * (s - sa) / ds)
    return -best if inside else best


FAIRING_INSET = 0.0015  # how far inside the fin's skin a fillet comes down, clear of the skin's faceting
FAIRING_FOOT = 0.01  # how far below its fillet the fairing runs on down inside the fin
FAIRING_TAPER = 0.35  # fin chord fraction over which a fillet grows from nothing at the fin's leading and trailing edges
FAIRING_ROW = 0.12  # most metres between the fairing's sections


def fin_chord(p, s, z):
    """The fin's chord fraction and half thickness at (s, z), or None off its planform."""
    fin = p["fin"]["sections"]
    if not fin[0][2] <= z <= fin[-1][2]:
        return None
    s_le, _, _, chord = section_at(fin, z, "z")
    t = (s - s_le) / chord
    return (t, airfoil(t) * p["fin"]["thickness"] * chord) if 0.0 <= t <= 1.0 else None


def fairing_ring(p, s, radius):
    """The fin-tip fairing's section at s: a circle, and below it a fillet each side tangent to the circle and to the
    fin's skin (FAIRING_INSET inside it), running on FAIRING_FOOT down into the fin. Behind the fin the fillets, feet
    and the circle's lowest point are one point. Points run anticlockwise looking aft, from the left equator over the
    top, down the right side, across inside the fin and up the left."""
    f = p["fin_fairing"]
    fin = fin_chord(p, s, f["z"] - radius)
    t, half = fin if fin else (0.0, 0.0)
    ramp = min(t, 1.0 - t, FAIRING_TAPER) / FAIRING_TAPER if fin else 0.0
    k = f["fillet"] * ramp * ramp * (3 - 2 * ramp)
    w = max(half - FAIRING_INSET, 0.0)
    if w >= radius:
        raise ValueError("the fin is thicker than the fin-tip fairing at s %.3f" % s)
    cx = w + k
    cy = -math.sqrt((radius + k) ** 2 - cx * cx)  # the fillet's centre, radius + k from the axis
    a1 = math.atan2(cy, cx)  # where the fillet meets the circle
    a0 = math.atan2(-cy, -cx)  # the same point, round the fillet's centre
    side = [(radius * math.cos(a1 * i / 4), radius * math.sin(a1 * i / 4)) for i in range(1, 5)]
    fillet = [(cx + k * math.cos(b), cy + k * math.sin(b)) for b in (a0 + (math.pi - a0) * i / 3 for i in (1, 2))]
    lower = side + fillet + [(w, cy), (w, cy - min(FAIRING_FOOT, half))]
    top = [(radius * math.cos(math.pi * i / 8), radius * math.sin(math.pi * i / 8)) for i in range(9)]
    ring = top + [(-x, y) for x, y in lower] + list(reversed(lower))
    return [P(s, x, f["z"] + y) for x, y in ring]


def build_fin_fairing(p, mat):
    """The fin-tip fairing: a round-ended body of revolution round the stabilator pivot, covering the fin tip and
    faired into the fin by fillets (fairing_ring). It is detail of the fin skin and joins that part's mesh
    (parts.merge_details)."""
    f = p["fin_fairing"]
    outline = fairing_outline(p)
    rows = [outline[1]]
    for (sa, ra), (sb, rb) in zip(outline[1:-2], outline[2:-1]):  # FAIRING_ROW apart, so the fillets follow the fin
        n = math.ceil((sb - sa) / FAIRING_ROW - 1e-9)
        rows += [(sa + (sb - sa) * i / n, ra + (rb - ra) * i / n) for i in range(1, n + 1)]
    rings = [fairing_ring(p, s, radius) for s, radius in rows]
    n = len(rings[0])
    verts = [P(outline[0][0], 0.0, f["z"]), P(outline[-1][0], 0.0, f["z"])] + [v for r in rings for v in r]
    ring = lambda j, k: 2 + j * n + k % n
    faces = [(0, ring(0, k + 1), ring(0, k)) for k in range(n)]
    faces += [(ring(j, k), ring(j, k + 1), ring(j + 1, k + 1), ring(j + 1, k))
              for j in range(len(rings) - 1) for k in range(n)]
    faces += [(1, ring(len(rings) - 1, k), ring(len(rings) - 1, k + 1)) for k in range(n)]
    obj = finish(welded(mesh_object("fin_fairing", verts, faces)), mat)
    obj["merge_into"] = "fin_skin"
    return obj


def empty(name, matrix, parent=None):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = 0.12
    TARGET.objects.link(obj)
    obj.parent = parent
    obj.matrix_world = matrix
    return obj


def build_references(p, repo):
    ref = p["references"]
    col = collection("References")
    folder = os.path.join(repo, ref["dir"])
    placed = []
    for view in ("top", "side", "front"):
        spec = ref[view]
        path = os.path.join(folder, spec["file"])
        if not os.path.exists(path):
            continue
        img = bpy.data.images.load(path, check_existing=True)
        w, h = img.size
        k = spec["px_per_m"]
        emp = bpy.data.objects.new("ref_" + view, None)
        emp.empty_display_type = "IMAGE"
        emp.data = img
        emp.empty_display_size = max(w, h) / k
        emp.empty_image_offset = (-0.5, -0.5)
        emp.color[3] = 0.5
        emp.use_empty_image_alpha = True
        cx, cy = w / 2, h / 2
        if view == "top":
            nx, ny = spec["nose_px"]
            emp.rotation_euler = (0, 0, math.radians(90))
            emp.location = ((cy - ny) / k, -S0 + (cx - nx) / k, -2.5)
        elif view == "side":
            nx, ny = spec["nose_px"]
            emp.rotation_euler = (math.radians(90), 0, math.radians(90))
            emp.location = (-4.0, -S0 + (cx - nx) / k, (ny - cy) / k)
        else:
            ux, uy = spec["centre_px"]
            emp.rotation_euler = (math.radians(90), 0, 0)
            emp.location = ((cx - ux) / k, 10.0, (uy - cy) / k)
        emp.empty_image_side = "FRONT"
        emp.show_empty_image_perspective = False
        col.objects.link(emp)
        placed.append(emp.name)
    return placed


def metrics(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for o in objs:
        if o.type != "MESH":
            continue
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    wing = wing_sections(PARAMS["wing"])
    # Reference area: the exposed panels plus the root chord carried in to the centreline, both sides.
    area = wing[0][3] * wing[0][1]
    for (_, xa, _, ca), (_, xb, _, cb) in zip(wing, wing[1:]):
        area += (ca + cb) / 2 * (xb - xa)
    area *= 2
    sweeps = [round(math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])), 1) for a, b in zip(wing, wing[1:])]
    return {
        "length_m": round(hi.y - lo.y, 3),
        "span_m": round(hi.x - lo.x, 3),
        "height_above_nose_m": round(hi.z, 3),
        "wing_ref_area_m2": round(area, 2),
        "wing_le_sweep_deg": sweeps,
    }


def build(repo=None, overrides=None):
    """Rebuild the aircraft. overrides replaces top-level PARAMS entries for this build only (variant renders)."""
    global TARGET, PARAMS
    base = PARAMS
    if overrides:
        PARAMS = dict(base, **overrides)
    geometry_cache.clear()
    try:
        return _build(repo)
    finally:
        PARAMS = base
        geometry_cache.clear()


def build_cached(repo=None, overrides=None):
    """Reuse a checked aircraft in a fresh script; build() always regenerates it."""
    import build_cache

    return build_cache.load_or_build(repo, overrides)


# The package modules, in check order. Each carries build(p, mats), check(icarus), a BUDGET (budget.py) and CLOSEUPS
# (review_sheet.py).
MODULES = ("parts", "speed_brakes", "propulsion", "canopy", "gear", "lights", "stations", "hulls", "cockpit", "uvs")


def modules():
    import importlib

    return [importlib.import_module(name) for name in MODULES]


def _build(repo):
    global TARGET
    repo = repo or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    TARGET = collection("Icarus")
    import materials

    mats = materials.build()
    p = PARAMS
    import canopy
    import cockpit
    import gear
    import lights
    import propulsion
    import speed_brakes
    import stations

    fuselage = build_fuselage(p, mats["body"], mats["duct"])
    parts = [fuselage, build_probe(p, mats["strut"])]  # a bare-metal boom in every livery
    parts += gear.cut_doors(fuselage)
    parts += canopy.build(p, mats)
    parts += propulsion.build(p, mats)
    parts += build_surfaces(p, mats)
    parts += speed_brakes.build(p, mats)
    parts += gear.build(p, mats)
    parts += lights.build(p, mats)
    parts += stations.build(p, mats)
    import internals  # imports this module back for its helpers, so it loads after them

    internals.build(p, collection("Internals"), mats)
    import parts as part_tree

    tree = part_tree.organise(p, TARGET, bpy.data.collections["Internals"], mats["structure"])
    part_tree.merge_details(TARGET)
    parts += cockpit.build(p, mats)  # hangs from the organised part tree
    bpy.context.view_layer.update()
    import hulls

    hull_count = hulls.build(TARGET)
    part_tree.open_bays(TARGET)  # render meshes only, after the hulls
    speed_brakes.clear_wells(TARGET)
    import uvs

    uvs.unwrap(TARGET)
    import checks

    checks.intake_wing_junction(TARGET)
    checks.fuel_cell_clearance(TARGET)
    checks.internals_inside_skin(TARGET)
    checks.interior_visibility(TARGET)
    checks.structure_clear_of_bays(TARGET)
    checks.canopy_fit(TARGET)
    checks.pilot_eye_leaks(TARGET)
    for module in modules():
        module.check(TARGET)
    import budget

    print(budget.report(TARGET))
    refs = build_references(p, repo)
    bpy.context.view_layer.update()  # children's world matrices follow their new parents only after an update
    out = metrics([o for o in TARGET.objects])
    out["parts"] = len(TARGET.objects)
    out["damage_parts"] = len(tree)
    out.update(hull_count)
    tagged = [o for o in TARGET.all_objects if "mass_kg" in o]
    out["fuel_kg"] = round(sum(o.get("fuel_kg", 0.0) for o in TARGET.all_objects), 1)  # tanks and wing spars
    out["dry_mass_kg"] = round(sum(o["mass_kg"] for o in tagged), 1)
    out["references"] = refs
    return out


if __name__ == "__main__":
    # Run as a script this file is __main__, but the other modules import build_icarus: build through that one copy,
    # so TARGET and PARAMS are the ones they read.
    import build_icarus

    print("icarus:", build_icarus.build_cached())
