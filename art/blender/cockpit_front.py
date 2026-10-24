"""The front office of the cockpit (cockpit.py builds the rest): the display face with the two main displays, the
standby stem under it, the angled wing panels either side of the stem, the hood over the displays with its rounded rim
running down both sides as cheeks to the console fronts, the coaming forward to the windscreen's foot under the rim's
sight line, the missile warning lamps, and the lower pedestal between the knees.

The layout follows fighter practice and the stock Vortex, Ifrit and Revoker (owner, 2026-10-22):
- display face, under the rim: the missile warning lamps, two groups of two over the main displays' top outboard
  corners, as the Vortex, Ifrit and OA-27 place theirs, the master warning (left) and master caution (right) inboard
  of them; then A, the tactical display (radar or targeting camera), and B, stores and engine, side by side;
- stem: the standby attitude indicator (a working ball) and C, the flight instruments;
- left wing: armament, gear, flaps; right wing: D, the system status display, the caution panel, fuel and the clock;
- pedestal: lighting and anti-ice.
Every group sits on its own plate, set into its face, with fasteners and a legend.

Positions are (s, x, z) as in cockpit.py. A face's local frame (cockpit.frame) has X to the pilot's right, Y up the
face, Z toward the pilot.
"""
import math

from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon

import build_icarus as bi
import canopy
import cockpit as ck
import cockpit_atlas
from cockpit import MM, P, X, Y, Z, EYE, Face, Piece, frame, over_nose_z, eye_point, plane_sheet, rect, ring_rect, \
    ring_circle, rounded, stack, walls

ALONG = math.atan(canopy.OVER_NOSE_SLOPE)  # the hood and its rim run along the over-nose line
A_DIR = Vector((0.0, math.cos(ALONG), math.sin(ALONG)))  # aft along it
TILT = math.radians(25.0)  # the display face leans back this far, so it faces the eye
FACE_N = Vector((0.0, math.cos(TILT), math.sin(TILT)))
FACE_UP = Vector((0.0, -math.sin(TILT), math.cos(TILT)))
FRONT = {
    # the main displays' glass top edge, 12.5 degrees under the eye as the stock main displays' (12.2 to 13.2): low
    # enough that display A's centre stays 0.25 m under the eye (Cockpit rule 16); the face above it, under the rim,
    # carries the warning lamps. Raised from under the 16 degree line along the face's own slope, so the cheeks and
    # wings stay as far forward of the stock throttle's sweep as they stood.
    "glass_top": (3.5361, 0.700),
    "half_width": 0.300,  # the display face, between the cheeks
    "stem_half_width": 0.130,
    "face_bottom_z": 0.479,  # the display face's bottom edge; the stem runs on down
    "stem_bottom_z": 0.307,  # the wings hinge on the stem's sides, so its height is theirs
    # the top frame narrow: it stands under the rim, which hides most of it from the eye
    "bezel": {"side": 0.024, "top": 0.012, "bottom": 0.026, "column": 0.020, "height": 0.006, "step": 0.0025},
    "rim": {"depth": 0.074, "behind": 0.05, "thickness": 0.026, "radius": 0.010, "corner": 0.045, "seg": 6},
    "margin": 0.005,  # under the over-nose line
    # the wings turn about the stem's side edges, their outer edges toward the eye, to land on the cheeks' inner faces
    "wing_yaw": 14.0,
    "pedestal": {"s0": 3.58, "half_width": 0.105},
}
# The coaming deck between the windscreen and the rim runs under this line (the old 16 degree over-nose line): the rim,
# on the over-nose line, hides it from the eye, so it stays low and clear of the windscreen and the hood's front bow.
DECK_SLOPE = 0.2876


def deck_z(s):
    """The coaming deck's line at station s."""
    return EYE[2] - DECK_SLOPE * (EYE[0] - s)


def face_frame():
    """The display face's placement: origin on the glass top line at the centreline."""
    s, z = FRONT["glass_top"]
    return frame(P(s, 0.0, z), FACE_UP, FACE_N)


def face_y(z):
    """Local Y on the display face of height z."""
    return (z - FRONT["glass_top"][1]) / math.cos(TILT)


# --- the screen layout ----------------------------------------------------------------------------------------------

def glass(name):
    d = ck.DISPLAYS[name]
    x0, y0, x1, y1 = d["canvas"]
    return (x1 - x0) / d["px_per_m"], (y1 - y0) / d["px_per_m"]


def screen_uv(name):
    x0, y0, x1, y1 = ck.DISPLAYS[name]["canvas"]
    W, H = ck.TAC_SCREEN_PX
    return x0 / W, y0 / H, x1 / W, y1 / H


def main_glass():
    """Displays A and B side by side under the glass top line: (x0, x1, height) each in face X, A on the pilot's left."""
    bz = FRONT["bezel"]
    (wa, ha), (wb, hb) = glass("A"), glass("B")
    total = wa + bz["column"] + wb
    a0 = -total / 2
    return {"A": (a0, a0 + wa, ha), "B": (a0 + wa + bz["column"], total / 2, hb)}


# --- generic pieces -------------------------------------------------------------------------------------------------

# --- the display face and the main displays -------------------------------------------------------------------------

def rim_section(depth=None):
    """The rim's section (a along A_DIR from the face's edge, b out from the opening), counter-clockwise from the
    buried back of its inner face round the rolled aft lip to the back of its outer face."""
    r = FRONT["rim"]
    a1, b1, rr, seg = depth or r["depth"], r["thickness"], r["radius"], r["seg"]
    pts = [(-r["behind"], 0.0)]
    for cx, cy, a0 in ((a1 - rr, rr, -90.0), (a1 - rr, b1 - rr, 0.0)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pts.append((-r["behind"], b1))
    return pts


def face_top_y():
    """Local Y where the display face meets the rim's underside: the rim's top runs FRONT margin under the over-nose
    line, its underside the rim's thickness below that."""
    m = face_frame()
    thick = FRONT["rim"]["thickness"]
    b_up = Vector((0.0, -math.sin(ALONG), math.cos(ALONG)))
    lo, hi = 0.0, 0.08
    for _ in range(40):
        y = (lo + hi) / 2
        p = m @ Vector((0.0, y, 0.0))
        top = p + b_up * thick
        s = top.y + bi.S0
        if top.z > over_nose_z(s) - FRONT["margin"]:
            hi = y
        else:
            lo = y
    return lo


def rim_path(y_top, y_bottom):
    """The rim's path on the display face's plane, in face X, Y: up the pilot's left side (face -X) from y_bottom,
    round the top corners and across, down the right side; with the outward normal in the face at each point."""
    hw, rc, seg = FRONT["half_width"], FRONT["rim"]["corner"], 8
    pts = []
    for y in bi.spaced(y_bottom, y_top - rc, 12)[:-1]:
        pts.append(((-hw, y), (-1.0, 0.0)))
    for cx, a0 in ((-hw + rc, 180.0), (hw - rc, 90.0)):
        for i in range(seg + 1):
            a = math.radians(a0 - 90.0 * i / seg)
            n = (math.cos(a), math.sin(a))
            pts.append(((cx + rc * n[0], y_top - rc + rc * n[1]), n))
        if cx < 0:
            for x in bi.spaced(-hw + rc, hw - rc, 12)[1:-1]:
                pts.append(((x, y_top), (0.0, 1.0)))
    for y in bi.spaced(y_top - rc, y_bottom, 12)[1:]:
        pts.append(((hw, y), (1.0, 0.0)))
    return pts


def rim_rings(y_top, y_bottom, section=None, at_a=None):
    """World rings of the rim's section along rim_path; at_a: only the outer-face point at that a (the hood's join)."""
    m = face_frame()
    b_top = Vector((0.0, -math.sin(ALONG), math.cos(ALONG)))
    rings = []
    for (x, y), (nx, ny) in rim_path(y_top, y_bottom):
        sec = section or rim_section(rim_depth(y))
        o = m @ Vector((x, y, 0.0))
        side = m.to_3x3() @ Vector((nx, 0.0, 0.0))  # outward across the face
        # b: outward from the opening, perpendicular to A_DIR, turning from up (top run) to sideways (cheeks)
        b = side * abs(nx) + b_top * max(ny, 0.0)
        b = (b - A_DIR * b.dot(A_DIR)).normalized()
        if at_a is not None:
            rings.append(o + A_DIR * at_a + b * FRONT["rim"]["thickness"])
        else:
            rings.append([o + A_DIR * a + b * bb for a, bb in sec])
    return rings


def rim_depth(y):
    """The rim stands its full depth round the hood and down the cheeks to 0.50 m, then narrows to 50 mm by 0.43 m,
    clear of the stock throttle's grip beside it."""
    z = FRONT["glass_top"][1] + y * math.cos(TILT)
    t = min(max((z - 0.43) / 0.07, 0.0), 1.0)
    return 0.050 + (FRONT["rim"]["depth"] - 0.050) * t


def rim(g, atlas):
    """The hood's rounded rim over the displays, turning down both sides of the panel as cheeks to the console fronts."""
    y_top = face_top_y()
    y_bottom = face_y(ck.LAYOUT["console"]["top_z"])
    rings = rim_rings(y_top, y_bottom)
    # an open sweep: its section's buried back stays open, the ends meet the consoles
    chart = atlas.chart("rim", "rim")
    k = len(rings[0])
    verts = [p for r in rings for p in r]
    faces = [(j * k + i, (j + 1) * k + i, (j + 1) * k + i + 1, j * k + i + 1)
             for j in range(len(rings) - 1) for i in range(k - 1)]
    flat = ck.grid_chart([r for r in rings], chart)
    piece = Piece(sheet=True, keep=True)
    piece.add(verts, faces, [[flat[q] for q in f] for f in faces])
    g.put(piece, None, "front")
    return y_top, y_bottom


def display_face(g, kit, atlas, uv):
    """The display face over the stem: its visible margins round the main displays' bezel (the bezel covers the rest),
    the bezel, the keys, the titles; returns the screen quads and the face (for the stem's placements)."""
    m = face_frame()
    hw = FRONT["half_width"]
    y_top = face_top_y()
    y_bot = face_y(FRONT["face_bottom_z"])
    bz = FRONT["bezel"]
    lay = main_glass()
    gx0, gx1 = lay["A"][0], lay["B"][1]
    gh = max(lay["A"][2], lay["B"][2])
    bx0, bx1 = gx0 - bz["side"], gx1 + bz["side"]
    by0, by1 = -gh - bz["bottom"], bz["top"]
    if by1 > y_top - 0.002 or bx1 > hw - 0.002:
        raise ValueError("cockpit: the main displays' bezel (%.3f, %.3f) passes the face (%.3f, %.3f)" % (bx1, by1, hw, y_top))
    # the face's margins round the bezel, each its own chart so the bezel's area wastes no texels
    for name, (x0, y0, x1, y1) in (("face_top", (-hw, by1, hw, y_top)), ("face_bottom", (-hw, y_bot, hw, by0)),
                                   ("face_left", (-hw, by0, bx0, by1)), ("face_right", (bx1, by0, hw, by1))):
        if x1 - x0 > 1e-4 and y1 - y0 > 1e-4:
            g.put(plane_sheet(atlas.chart("panel", name), rect(x0, y0, x1, y1)), m, "front")
    # the bezel: one dark frame round both glasses, rolled at its outer edge, a step down to each glass
    screens = []
    g.put(dual_bezel(uv, lay, bz), m, "front")
    for name in ("A", "B"):
        x0, x1, h = lay[name]
        screens.append((ck.quad(m @ Matrix.Translation(((x0 + x1) / 2, -h / 2, 0.0)), x1 - x0, h, ck.BEZEL["screen_z"]),
                        screen_uv(name)))
    lift = bz["height"]
    # keys at the stock key's size on raised key bars: A's left side and bottom, B's right side and bottom; the
    # brightness rockers in the outer bottom corners, the contrast rockers down the column between the two
    bar_h = 0.002
    up = lambda x, y, z=0.0: m @ Matrix.Translation((x, y, lift + z))

    def bar(x0, y0, x1, y1):
        g.put(stack(uv, [ring_rect((x1 - x0) / 2, (y1 - y0) / 2, 0.0, 0.002, 1),
                         ring_rect((x1 - x0) / 2 - 0.0007, (y1 - y0) / 2 - 0.0007, bar_h, 0.0015, 1)],
                    "bezel", top_uv="bezel", bottom_hidden=True), up((x0 + x1) / 2, (y0 + y1) / 2), "front")
    for name, side, legends in (("A", -1, ("NAV", "RST", "VIEW", "CNTR", "MAP")), ("B", 1, ("SEL", "STEP", "QTY", "JETT", "ENG"))):
        x0, x1, h = lay[name]
        xs = x0 - bz["side"] / 2 if side < 0 else x1 + bz["side"] / 2
        ys = [-0.022 - i * 0.0315 for i in range(len(legends))]  # A's soft keys beside the canvas's NAV, RESET, VIEW, CNTR
        bar(xs - 0.0085, ys[-1] - 0.0075, xs + 0.0085, ys[0] + 0.0075)
        for y, legend in zip(ys, legends):
            g.put(kit.key(legend), up(xs, y, bar_h), "front")
    for name, legends in (("A", ("A/A", "A/G", "NAV", "RDR", "EO", "EW")), ("B", ("WPN", "FUEL", "ENG", "HYD", "BIT"))):
        x0, x1, h = lay[name]
        n, yk = len(legends), -h - bz["bottom"] / 2
        xs = [(x0 + x1) / 2 + 0.034 * (i - (n - 1) / 2) for i in range(n)]
        bar(xs[0] - 0.0095, yk - 0.0075, xs[-1] + 0.0095, yk + 0.0075)
        for x, legend in zip(xs, legends):
            g.put(kit.key(legend), up(x, yk, bar_h), "front")
    for x, y, legend in ((lay["A"][0] - bz["side"] / 2, -lay["A"][2] - bz["bottom"] / 2, "BRT"),
                         (lay["B"][1] + bz["side"] / 2, -lay["B"][2] - bz["bottom"] / 2, "BRT"),
                         ((lay["A"][1] + lay["B"][0]) / 2, -0.030, "CON"), ((lay["A"][1] + lay["B"][0]) / 2, -0.150, "CON")):
        for piece in kit.rocker("+\n" + legend + "\n-"):
            g.put(piece, up(x, y), "front")
    for x, y in ((bx0 + 0.008, by1 - 0.008), (bx1 - 0.008, by1 - 0.008), ((lay["A"][1] + lay["B"][0]) / 2, by1 - 0.008),
                 ((lay["A"][1] + lay["B"][0]) / 2, by0 + 0.008)):
        g.put(kit.fastener(), up(x, y), "front")
    # titles under each display: what it shows
    for name in ("A", "B"):
        x0, x1, _ = lay[name]
        lab = atlas.label(ck.DISPLAYS[name]["title"], cap_mm=5.0)
        g.put(kit.placard(lab), m @ Matrix.Translation(((x0 + x1) / 2, (by0 + y_bot) / 2, 0.0)), "front")
    return screens, y_top


def dual_bezel(uv, lay, bz):
    """The frame round displays A and B: an outer rounded rect rolled at its edge, a flat top, and for each glass a
    step down into its well, the screen 1.5 mm over the face."""
    gh = max(lay["A"][2], lay["B"][2])
    x0, x1 = lay["A"][0] - bz["side"], lay["B"][1] + bz["side"]
    y0, y1 = -gh - bz["bottom"], bz["top"]
    hgt, step = bz["height"], bz["step"]
    piece = Piece(sheet=True, keep=True)

    def ring(pts, z):
        return [Vector((x, y, z)) for x, y in pts]

    def band(lo, hi, spec):
        n = len(lo)
        for i in range(n):
            quad = [lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]]
            piece.add(quad, [(0, 1, 2, 3)], [uv(spec, quad)])
    outer = rounded(x0, y0, x1, y1, 0.010, 3)
    roll = rounded(x0 + 0.0015, y0 + 0.0015, x1 - 0.0015, y1 - 0.0015, 0.0085, 3)
    band(ring(outer, 0.0), ring(outer, hgt - 0.0015), "bezel")
    band(ring(outer, hgt - 0.0015), ring(roll, hgt), "bezel")
    # the top: the outline less the two wells, flat
    wells = []
    for name in ("A", "B"):
        a0, a1, h = lay[name]
        wells.append(rounded(a0 - 0.002, -h - 0.002, a1 + 0.002, 0.002, 0.003, 1))
    polys = [ring(roll, hgt)] + [ring(w, hgt) for w in wells]
    tris = tessellate_polygon(polys)
    flat = [p for poly in polys for p in poly]
    for t in tris:
        pts = [flat[i] for i in t]
        if _normal_z(pts) < 0:
            pts = pts[::-1]
        piece.add(pts, [(0, 1, 2)], [uv("bezel", pts)])
    for w in wells:
        n = len(w)
        floor = ring(w, 0.0005)  # under the screen quad, closing the 2 mm ring round it
        tris = tessellate_polygon([floor])
        for t in tris:
            pts = [floor[i] for i in t]
            if _normal_z(pts) < 0:
                pts = pts[::-1]
            piece.add(pts, [(0, 1, 2)], [uv("bezel_dark", pts)])
        top = ring(w, hgt)
        mid = ring(w, hgt - step)
        inner = ring([(x * 1.0, y * 1.0) for x, y in w], 0.0005)
        for i in range(n):  # the well's wall, facing in
            quad = [top[i], mid[i], mid[(i + 1) % n], top[(i + 1) % n]]
            piece.add(quad, [(0, 1, 2, 3)], [uv("bezel_dark", quad)])
            quad = [mid[i], inner[i], inner[(i + 1) % n], mid[(i + 1) % n]]
            piece.add(quad, [(0, 1, 2, 3)], [uv("bezel_dark", quad)])
    return piece


def _normal_z(pts):
    a, b, c = pts[0], pts[1], pts[2]
    return (b - a).cross(c - a).z


# --- the stem, the wings and the pedestal ---------------------------------------------------------------------------

def stem(g, kit, atlas, uv):
    """The display face's stem between the knees, carrying the standby instruments: the attitude indicator and C, the
    flight-instrument display."""
    m = face_frame()
    sw = FRONT["stem_half_width"]
    y0, y1 = face_y(FRONT["stem_bottom_z"]), face_y(FRONT["face_bottom_z"])
    face = Face("stem", m, rect(-sw, y0, sw, y1), atlas.chart("panel", "stem"))
    # C, the flight instruments, with its frame, right of centre; the standby attitude indicator on the left
    cx, cy = 0.044, (y0 + y1) / 2 - 0.006
    ax, ay = -0.070, cy + 0.004
    sb = STANDBY
    window = [(ax + p[0], ay + p[1]) for p in ring_circle(sb["opening"] + 0.0005, 0.0, 16)]
    top = face.pocket(g, kit, uv, -sw + 0.008, y0 + 0.010, sw - 0.008, y1 - 0.004, "STBY INSTR", 4,
                      floor_holes=[display_hole("C", cx, cy), window])
    screens = [small_display(g, kit, uv, top, "C", cx, cy)]
    standby(g, kit, atlas, uv, top(ax, ay))
    for dx in (-0.022, 0.022):  # cage and brightness
        g.put(kit.knob(small=True), top(ax + dx, ay - 0.045), "front")
    face.close(g)
    return face, screens


# The standby attitude indicator: a working ball behind a black mask with the roll scale, in the bezel the painted dial
# had. The ball is world-steady in pitch and roll about the case's own axes (StandbyInstruments.cs turns it); at rest its
# horizon crosses the window's centre. Metres: the bezel's radius, the window's, the ball's, how deep its centre sits
# under the plate.
STANDBY = {"r": 0.030, "opening": 0.020, "ball": 0.0235, "centre": -0.0215, "tube": -0.012, "lon": 20, "lat": 12}
# The live dials' needles and hands: (object, the dial's tile, length and width at the hub over the dial face's radius,
# height over it). The plugin turns each about the dial's axis from straight up: fuel over the 270 degree scale,
# hours and minutes from the game's time of day.
NEEDLES = {"dial_fuel": [("cockpit_fuel_needle", 0.82, 0.075, 0.0003)],
           "dial_clock": [("cockpit_clock_hour", 0.55, 0.085, 0.0003), ("cockpit_clock_minute", 0.82, 0.060, 0.0007)]}
MOVERS = {}  # object name -> (Gather, pivot): the instruments' moving parts, each its own renderer (cockpit.build)


def standby(g, kit, atlas, uv, m):
    """The standby indicator at placement m (on its plate): the bezel, the mask over the ball with the roll scale, a
    short tube from the mask's window down past the ball's edge, the fixed amber aircraft symbol, and the ball."""
    sb = STANDBY
    r, o = sb["r"], sb["opening"]
    face = r - 4 * MM
    rings = [ring_circle(r, 0.0, 24), ring_circle(r, 6 * MM, 24), ring_circle(r - 3 * MM, 6 * MM, 24),
             ring_circle(face, 3 * MM, 24), ring_circle(o, 3 * MM, 24), ring_circle(o, sb["tube"], 24)]
    specs = ["bezel", "bezel", "recess", atlas.tile("standby_ring"), "recess"]
    piece = Piece(sheet=True, keep=True)
    rings = [[Vector(p) for p in ring] for ring in rings]
    for a, b, spec in zip(rings, rings[1:], specs):
        for i in range(len(a)):
            quad = [a[i], a[(i + 1) % len(a)], b[(i + 1) % len(a)], b[i]]
            mapped = uv(spec, quad, box=(-face, -face, face, face)) if not isinstance(spec, str) else \
                uv(spec, quad, along=quad[1] - quad[0])
            piece.add(quad, [(0, 1, 2, 3)], [mapped])
    g.put(piece, m, "front")
    amber = atlas.tile("lens_amber")
    for x, hw, hh in ((-0.0085, 0.0045, 0.0007), (0.0085, 0.0045, 0.0007), (0.0, 0.0011, 0.0011)):
        g.put(stack(uv, [ring_rect(hw, hh, 2.3 * MM), ring_rect(hw, hh, 2.9 * MM)], "guard", top_uv=amber),
              m @ Matrix.Translation((x, 0.0, 0.0)), "front")
    MOVERS["cockpit_standby_ball"] = (standby_ball(atlas, m @ Matrix.Translation((0.0, 0.0, sb["centre"]))),
                                      m @ Vector((0.0, 0.0, sb["centre"])))


def standby_ball(atlas, m):
    """The ball at placement m: polar axis up the case (local Y), longitude 0 toward the pilot (local Z), unrolled
    onto the standby_ball tile with its back half mirrored."""
    sb = STANDBY
    tile = atlas.tile("standby_ball")
    g = ck.Gather("cockpit_standby_ball")
    nl, nt = sb["lon"], sb["lat"]

    def point(i, j):
        lat, lon = math.pi * (j / nt - 0.5), 2 * math.pi * i / nl - math.pi
        return Vector((sb["ball"] * math.cos(lat) * math.sin(lon), sb["ball"] * math.sin(lat),
                       sb["ball"] * math.cos(lat) * math.cos(lon))), (math.degrees(lat), math.degrees(lon))

    def tex(lat, lon):
        fold = lon if abs(lon) <= 90 else math.copysign(180, lon) - lon
        return tile.frac((fold + 90) / 180, (lat + 90) / 180)
    piece = Piece()
    for j in range(nt):
        for i in range(nl):
            corners = [point(i, j), point(i + 1, j), point(i + 1, j + 1), point(i, j + 1)]
            if j == 0:
                corners = [corners[0], corners[2], corners[3]]
                corners[0] = (corners[0][0], (corners[0][1][0], (point(i, j)[1][1] + point(i + 1, j)[1][1]) / 2))
            elif j == nt - 1:
                corners = corners[:3]
                corners[2] = (corners[2][0], (corners[2][1][0], (point(i, j)[1][1] + point(i + 1, j)[1][1]) / 2))
            piece.add([c[0] for c in corners], [tuple(range(len(corners)))], [[tex(*c[1]) for c in corners]])
    g.put(piece, m, "ball")
    return g


def needles(atlas, m, dial, r):
    """The needle or hands of a live dial of face radius r at placement m, pointing straight up, each its own
    Gather in MOVERS, pivoting on the dial's centre."""
    tile = atlas.tile("needle")
    for name, length, width, lift in NEEDLES.get(dial, []):
        L, w = length * r, width * r
        z = 3 * MM + lift  # over the dial's face (Kit.dial)
        blade = [(-w / 2, -0.12 * L), (w / 2, -0.12 * L), (w / 6, L), (0.0, L + 0.6 * w), (-w / 6, L)]
        hub = [(0.55 * w * math.cos(a), 0.55 * w * math.sin(a)) for a in [2 * math.pi * k / 8 for k in range(8)]]
        piece = Piece(sheet=True, keep=True)
        for outline, dz in ((blade, 0.0), (hub, 0.0001)):
            pts = [Vector((x, y, z + dz)) for x, y in outline]
            piece.add(pts, [tuple(range(len(pts)))], [ck.rect_uvs(pts, tile)])
        g = ck.Gather(name)
        g.put(piece, m, "needle")
        MOVERS[name] = (g, m @ Vector((0.0, 0.0, 0.0)))


SUNK = 0.0035  # the small displays' wells run this far under their plates; the screen 2 mm above the well's floor


def display_hole(name, x, y):
    """The hole a small display's well needs through its plate, in the plate's metres."""
    w, h = glass(name)
    return rounded(x - w / 2 - 0.002, y - h / 2 - 0.002, x + w / 2 + 0.002, y + h / 2 + 0.002, 0.004, 2)


def small_display(g, kit, uv, top, name, x, y, title=True, keys_below=True):
    """A small display's frame, sunk through its plate (display_hole), keys under and beside it, brightness and
    contrast rockers, its title over it; returns its screen quad."""
    w, h = glass(name)
    m = top(x, y)
    g.put(kit.bezel(w, h, 0.011, 0.003, hgt=0.0045, sunk=SUNK), m, "front")
    for i, legend in enumerate(("1", "2", "3", "4") if keys_below else ()):
        g.put(kit.key(legend), top(x + (i - 1.5) * 0.019, y - h / 2 - 0.0185), "front")
    for sx in (-1, 1):  # three keys up each side
        for i in range(3):
            g.put(kit.key("ABC"[i] if sx < 0 else "DEF"[i]), top(x + sx * (w / 2 + 0.0185), y + 0.022 * (1 - i)), "front")
    for sx, legend in ((-1, "BRT"), (1, "CON")) if keys_below else ():  # rockers either side of the key row
        for piece in kit.rocker("+\n" + legend + "\n-"):
            g.put(piece, top(x + sx * (2.5 * 0.019 + 0.009), y - h / 2 - 0.0185), "front")
    if title:
        lab = kit.atlas.label(ck.DISPLAYS[name]["title"], cap_mm=3.5)
        g.put(kit.placard(lab), top(x, y + h / 2 + 0.011 + lab.h_m / 2 + 0.002), "front")
    return ck.quad(m, w, h, 0.002 - SUNK), screen_uv(name)  # 6 mm under the frame's face


def wing_frame(side):
    """A wing panel's placement, side +1 for the pilot's left: origin at its inner top corner, the stem's outer top
    corner, local Y up the stem's side edge (the display face's up), the face turned about that edge by wing_yaw so
    its outer edge comes toward the eye. The wing and the stem share that edge."""
    m = face_frame()
    corner = m @ Vector((-side * FRONT["stem_half_width"], face_y(FRONT["face_bottom_z"]), 0.0))
    turn = Matrix.Rotation(math.radians(FRONT["wing_yaw"]), 3, FACE_UP)
    if (turn @ Vector((side, 0.0, 0.0))).y < 0:  # the outer edge comes aft (+Y), toward the eye
        turn = Matrix.Rotation(-math.radians(FRONT["wing_yaw"]), 3, FACE_UP)
    n = turn @ FACE_N
    return frame(corner, FACE_UP, n), n, corner


def wing_size():
    """(width, height) of a wing: across from the stem's edge to the cheek's inner face, and the stem's height."""
    width = (FRONT["half_width"] - FRONT["stem_half_width"]) / math.cos(math.radians(FRONT["wing_yaw"]))
    return width, face_y(FRONT["face_bottom_z"]) - face_y(FRONT["stem_bottom_z"])


def wing_outline(side):
    """The wing's outline in its own frame, counter-clockwise seen from the pilot: inner edge on the stem's, outer
    edge on the cheek's inner face, top edge from the face's bottom corner, bottom edge level with the stem's."""
    m, _, _ = wing_frame(side)
    w, h = wing_size()
    x = -side * w  # local X is the pilot's right
    out = [(min(0.0, x), -h), (max(0.0, x), -h), (max(0.0, x), 0.0), (min(0.0, x), 0.0)]
    return m, out


# The wing plates, in the wing's local metres from its centre: x to the pilot's right, y up. (title, x0, y0, x1, y1,
# fasteners, controls); a control is (kind, x, y, legend) from the plate's centre.
WINGS = {
    1: [("ARMAMENT", 0.002, 0.004, 0.084, 0.088, 4,
         [("guarded", -0.022, 0.006, "MASTER ARM"), ("jett", 0.020, 0.016, "JETT"), ("button", 0.008, -0.022, "A/A"),
          ("button", 0.030, -0.022, "A/G")]),
        ("GEAR", -0.084, -0.018, -0.006, 0.088, 6,
         [("lamp_green", -0.020, 0.032, "N"), ("lamp_green", -0.020, 0.012, "L"), ("lamp_green", -0.020, -0.008, "R"),
          ("lamp_red", -0.020, -0.030, "TRANS"), ("gear", 0.022, -0.014, None)]),
        ("FLAPS", 0.002, -0.086, 0.084, -0.002, 4,
         [("toggle3", -0.010, -0.004, "UP\nTO\nLDG"), ("lamp_green", 0.024, 0.010, "FLAP")]),
        ("HOOK", -0.084, -0.086, -0.006, -0.026, 4, [("toggle", 0.0, -0.004, "HOOK")])],
    -1: [("SYS STATUS", -0.080, -0.030, 0.042, 0.088, 4, [("display", -0.002, -0.003, "D")]),
         ("CAUTION", 0.045, -0.030, 0.084, 0.088, 4, [("caution", 0.0, -0.004, None)]),
         ("FUEL", -0.084, -0.090, 0.000, -0.035, 4, [("dial", -0.014, -0.001, "dial_fuel"), ("key", 0.026, 0.010, "FWD"),
                                                       ("key", 0.026, -0.010, "AFT")]),
         ("CLOCK", 0.004, -0.090, 0.084, -0.035, 4, [("dial", -0.012, -0.001, "dial_clock"), ("knob", 0.026, -0.006, "SET")])],
}


def wings(g, kit, atlas, uv):
    """The two wing panels either side of the stem, and their plates; returns the D screen quad and the faces."""
    screens, faces = [], []
    for side in (1, -1):
        m, outline = wing_outline(side)
        cx = sum(p[0] for p in outline) / 4
        cy = sum(p[1] for p in outline) / 4
        face = Face("wing_L" if side > 0 else "wing_R", m, outline, atlas.chart("panel", "wing%d" % side))
        for title, x0, y0, x1, y1, n, controls in WINGS[side]:
            px, py = cx + (x0 + x1) / 2, cy + (y0 + y1) / 2
            holes = [display_hole(legend, px + dx, py + dy) for kind, dx, dy, legend in controls if kind == "display"]
            top = face.pocket(g, kit, uv, cx + x0, cy + y0, cx + x1, cy + y1, title, n, floor_holes=holes)
            for kind, dx, dy, legend in controls:
                x, y = px + dx, py + dy
                if kind == "display":
                    screens.append(small_display(g, kit, uv, top, legend, x, y, title=False, keys_below=False))
                elif kind == "caution":
                    for i, text in enumerate(("FUEL", "HYD", "OIL", "GEN", "ENG", "FCS", "OXY", "ECS")):
                        col, row = i % 2, i // 2
                        g.put(kit.indicator("lens_amber", text), top(x - 0.0095 + 0.019 * col, y + 0.028 - 0.0195 * row),
                              "front")
                else:
                    control(g, kit, atlas, top, kind, x, y, legend)
        face.close(g)
        faces.append(face)
        # the wing's box: its bottom edge closed back to the stem's line
    return screens, faces


def control(g, kit, atlas, top, kind, x, y, legend):
    """One control on a plate (top: the plate's placement maker), with its legend."""
    if kind in ("toggle", "guarded", "toggle3"):
        for piece in kit.guard() if kind == "guarded" else kit.toggle():
            g.put(piece, top(x, y), "front")
        lab = atlas.label(legend, cap_mm=3.0, box=True)
        g.put(kit.placard(lab), top(x, y - (0.028 if kind == "guarded" else 0.017) - lab.h_m / 2), "front")
    elif kind == "knob":
        g.put(kit.knob(), top(x, y), "front")
        lab = atlas.label(legend, cap_mm=3.0)
        g.put(kit.placard(lab), top(x, y - 0.017 - lab.h_m / 2), "front")
    elif kind == "button":
        g.put(kit.indicator("lens_clear", legend), top(x, y), "front")
    elif kind == "jett":
        g.put(kit.placard(atlas.tile("hatch"), size=(0.030, 0.030)), top(x, y), "front")
        g.put(kit.indicator("lens_red", legend), top(x, y), "front")
    elif kind.startswith("lamp_"):
        g.put(kit.indicator(kind.replace("lamp_", "lens_"), legend), top(x, y), "front")
    elif kind == "key":
        g.put(kit.key(legend), top(x, y), "front")
    elif kind == "dial":
        g.put(kit.dial(legend, 0.0235), top(x, y), "front")
        needles(atlas, top(x, y), legend, 0.0235 - 4 * MM)
    elif kind == "gear":
        gear_handle(g, kit, top, x, y)


def gear_handle(g, kit, top, x, y):
    """The gear handle in its slot, down: a lever out of the plate ending in a wheel-shaped knob."""
    uv = kit.uv
    g.put(stack(uv, [ring_rect(0.007, 0.030, 0.0), ring_rect(0.007, 0.030, 1.5 * MM)], "recess", bottom_hidden=True),
          top(x, y), "front")
    base = top(x, y - 0.022, 1.5 * MM)
    lever = base @ Matrix.Rotation(math.radians(-35), 4, "X")
    g.put(stack(uv, [ring_circle(3.5 * MM, 0.0, 10), ring_circle(3.0 * MM, 0.042, 10)], "metal"), lever, "front")
    wheel = [ring_circle(16 * MM, 0.0, 20), ring_circle(17 * MM, 3 * MM, 20), ring_circle(17 * MM, 9 * MM, 20),
             ring_circle(15.5 * MM, 12 * MM, 20), ring_circle(6 * MM, 12.5 * MM, 20)]
    g.put(stack(uv, wheel, ["knurl", "knurl", "knurl", "metal"], top_uv="metal"),
          lever @ Matrix.Translation((0.0, 0.0, 0.040)), "front")
    for text, dy in (("UP", 0.024), ("DN", -0.024)):
        lab = kit.atlas.label(text, cap_mm=3.5)
        g.put(kit.placard(lab), top(x - 0.020, y + dy), "front")


def closures(g, atlas, uv):
    """The mitres and boxes round the wings: each wing's top edge meets the display face's bottom edge in a triangular
    mitre turned to the eye (the two share the stem's corner, the wing's outer corner stands aft of the face's on the
    cheek); under each wing its bottom closes back toward the footwell, out of the eye's sight."""
    m = face_frame()
    hw = FRONT["half_width"]
    y_bot = face_y(FRONT["face_bottom_z"])
    back = 0.07
    faces = []
    for side in (1, -1):
        wm, outline = wing_outline(side)
        w, h = wing_size()
        corner = wm @ Vector((0.0, 0.0, 0.0))
        face_out = m @ Vector((-side * hw, y_bot, 0.0))
        wing_out = wm @ Vector((-side * w, 0.0, 0.0))
        # the mitre's own frame: X along the face's bottom edge, Y up toward the wing's outer corner
        n = (face_out - corner).cross(wing_out - corner).normalized()
        if n.dot(eye_point() - corner) < 0:
            n = -n
        bm = frame(corner, (wing_out - corner), n)
        inv = bm.inverted()
        tri = [tuple((inv @ p).xy) for p in (corner, face_out, wing_out)]
        if ck._area(tri) < 0:
            tri = tri[::-1]
        face = Face("mitre_L" if side > 0 else "mitre_R", bm, tri, atlas.chart("panel", "mitre%d" % side))
        faces.append(face.close(g))
        # the wing's bottom, back toward the footwell
        bottom = [wm @ Vector((0.0, -h, 0.0)), wm @ Vector((-side * w, -h, 0.0))]
        quad = [bottom[0], bottom[1], bottom[1] + Vector((0.0, -back, 0.0)), bottom[0] + Vector((0.0, -back, 0.0))]
        g.put(ck.sheet(uv, quad, "structure"), None, "front")
    return faces


def pedestal(g, kit, atlas, uv):
    """The lower pedestal between the knees: a box from the stem's foot down to the floor, its aft face a plate of
    lighting knobs and anti-ice toggles."""
    pd = FRONT["pedestal"]
    m = face_frame()
    z_top = FRONT["stem_bottom_z"]
    s_aft = (m @ Vector((0.0, face_y(z_top), 0.0))).y + bi.S0
    hw, floor = pd["half_width"], ck.LAYOUT["floor_z"]
    fm = frame(P(s_aft, 0.0, (z_top + floor) / 2), Z, Y)
    h = (z_top - floor) / 2
    face = Face("pedestal", fm, rect(-hw, -h, hw, h - 0.004), atlas.chart("console", "pedestal"))
    top = face.pocket(g, kit, uv, -hw + 0.008, -0.010, hw - 0.008, h - 0.012, "LIGHTS / ANTI-ICE", 4)
    for x, text in ((-0.055, "INST"), (-0.018, "CSL"), (0.018, "FLOOD")):
        g.put(kit.knob(), top(x, h - 0.060), "front")
        lab = atlas.label(text, cap_mm=3.0)  # over the knob: the face stands upright, seen from above
        g.put(kit.placard(lab), top(x, h - 0.037), "front")
    for x, text in ((0.058, "PITOT"),):
        for piece in kit.toggle():
            g.put(piece, top(x, h - 0.060), "front")
        lab = atlas.label(text, cap_mm=3.0, box=True)
        g.put(kit.placard(lab), top(x, h - 0.037), "front")
    for x, text in ((-0.040, "ENG ICE"), (0.040, "WSHLD")):
        for piece in kit.toggle():
            g.put(piece, top(x, 0.004), "front")
        lab = atlas.label(text, cap_mm=3.0, box=True)
        g.put(kit.placard(lab), top(x, 0.027), "front")
    face.close(g)
    # the box's sides and top, forward to s0
    s0 = pd["s0"]
    for side in (1, -1):
        quad = [P(s0, side * hw, floor), P(s_aft, side * hw, floor), P(s_aft, side * hw, z_top), P(s0, side * hw, z_top)]
        g.put(ck.sheet(uv, quad, "structure"), None, "front")
    return face


# --- the side panels ---

SIDE_PANELS = {
    # (title, controls): a control is (kind, x, y, legend), x outboard from the panel's centre line, y up its slope
    1: ("BRAKES", [("button", 0.0, 0.118, "ANTI\nSKID"), ("button", -0.012, 0.072, "NWS"), ("button", 0.016, 0.072, "PARK")]),
    -1: ("ECS", [("knob", 0.0, 0.118, "TEMP"), ("button", -0.012, 0.066, "DEFOG"), ("button", 0.016, 0.066, "RAM")]),
}
SIDE_PANEL = {"low": (ck.LAYOUT["console"]["s0"], ck.LAYOUT["console"]["top_z"]), "high": (3.680, 0.470), "inner": 0.339}


def side_panels(g, kit, atlas, uv, space):
    """Outboard of each cheek, the console kicks up toward the panel: a sloped face from the console's front edge up
    to the cheek's height, between the cheek and the lining, facing the eye, with its own plate. It closes the bare
    wall the eye saw there: its bottom edge on the console top's front edge, its outer edge along the lining, which
    stands wider low down than at the top."""
    (s0, z0), (s1, z1) = SIDE_PANEL["low"], SIDE_PANEL["high"]
    up = (P(s1, 0.0, z1) - P(s0, 0.0, z0)).normalized()
    normal = Vector((0.0, -up.z, up.y)) if up.z > 0 else Vector((0.0, up.z, -up.y))
    if normal.y < 0:
        normal = -normal
    length = (P(s1, 0.0, z1) - P(s0, 0.0, z0)).length
    faces = []
    for side in (1, -1):
        x_in = SIDE_PANEL["inner"]
        x_out = min(space.wall_x(s, z) for s, z in ((s0, z0), (s1, z1), ((s0 + s1) / 2, (z0 + z1) / 2))) - 0.004
        xc = (x_in + x_out) / 2
        m = frame(P(s0, side * xc, z0), up, normal)
        hw = (x_out - x_in) / 2
        inv = m.inverted()
        edge = [inv @ P(s0 + (s1 - s0) * f, side * (space.wall_x(s0 + (s1 - s0) * f, z0 + (z1 - z0) * f) - 0.002),
                          z0 + (z1 - z0) * f) for f in bi.spaced(0.0, 1.0, 5)]
        inner = [inv @ P(s, side * x_in, z) for s, z in ((s1, z1), (s0, z0))]
        outline = [tuple(p.xy) for p in edge + inner]
        if ck._area(outline) < 0:
            outline = outline[::-1]
        face = Face("side%d" % side, m, outline, atlas.chart("console", "side_panel%d" % side))
        title, controls = SIDE_PANELS[side]
        top = face.pocket(g, kit, uv, -hw + 0.006, 0.040, hw - 0.006, length - 0.006, title, 4, "front")
        for kind, x, y, legend in controls:
            control(g, kit, atlas, top, kind, -side * x, y, legend)
        face.close(g)
        faces.append(face)
    return faces


# --- the hood and the coaming ---------------------------------------------------------------------------------------

def shroud(g, atlas, uv, space, y_top, group="front", proxy=False):
    """One dark shroud from the windscreen's front to the rim: forward of the hood's glass its sides run up the inner
    skin to the glass's foot, so the eye sees no bay below the windscreen; under the hood, clear of the opening hood's
    sweep, its sides drop at the cheeks' outer face. Its top runs FRONT margin under the over-nose line. Its last row is
    the rim's buried outer edge, so the two meet."""
    s0, s_coam, inset = ck.LAYOUT["coaming"]
    margin = FRONT["margin"]
    deck = lambda s: deck_z(s) - margin
    rows_s = sorted(set(bi.spaced(s0, s_coam, 8) + bi.spaced(3.08, 3.40, 5) + [canopy.CANOPY["windscreen_end_s"]]))
    foot = {s: row[3] - 0.010 for s, row in zip(rows_s, bi.resample(canopy.PROFILE, rows_s))}
    hood_w = FRONT["half_width"] + FRONT["rim"]["thickness"]
    skirt_z = 0.462
    n = 13 if proxy else 17  # the rim hides the deck from the eye: coarse, on a strip
    if proxy:
        rows_s = rows_s[::2]
    rows = []
    for s in rows_s:
        z0 = deck(s)
        if s <= 3.0:
            # ahead of the hood the deck rises to just under the windscreen's foot: a sight line that low meets the
            # skin anyway, so the deck hides no more of the view over the nose, and no well opens under the glass
            z0 = max(z0, foot[s] - WINDSCREEN_DECK)
            side = [(space.skin_x(s, z, inset), z) for z in bi.spaced(foot[s], z0, 4)]
        else:
            # under the hood: the skirt at the cheeks' outer face
            t = 1.0
            x_end = (1 - t) * space.skin_x(s, foot[s], inset) + t * hood_w
            z_end = (1 - t) * foot[s] + t * skirt_z
            w_top = (1 - t) * space.skin_x(s, min(z0, foot[s] - 0.001), inset) + t * hood_w
            side = [(x_end, z_end)] + [((1 - f) * x_end + f * w_top, (1 - f) * z_end + f * z0) for f in (0.5, 1.0)]
        sill_limit = space.sill_limit(s, min(z for _, z in side), max(z for _, z in side)) - 0.006
        side = [(min(x, space.skin_x(s, z, 0.006), sill_limit,
                     space.hood_x(s, z, 1) - 0.010, space.hood_x(s, z, -1) - 0.010), z)
                for x, z in side]
        w = side[-1][0]
        line = [P(s, x, z) for x, z in side] + [P(s, w * f, z0) for f in bi.spaced(1, -1, 9)[1:-1]] + \
            [P(s, -x, z) for x, z in side[::-1]]
        rows.append(resample_line(line, n))
    # the last rows: the rim's buried outer edge, from the cheeks' skirt height over the top
    r = FRONT["rim"]
    edge = rim_rings(y_top, face_y(skirt_z), at_a=-r["behind"])
    rows.append(resample_line(edge, n))
    g.put(ck.grid_sheet(uv, rows, "structure"), None, group)
    # the front wall at the windscreen's front: the first section filled up to 5 mm over the skin's line over the top
    s, first = rows_s[0], rows[0]
    over, under = (space.internals.ring_at(space.p, s, d) for d in (-0.005, inset))
    arc = [o if abs(o.x) < 0.12 else u for o, u in zip(over, under) if u.z > foot[s] + 0.01]
    arc.sort(key=lambda v: -math.atan2(v.x, v.z - foot[s]))
    arc = [first[0]] + [P(s, v.x, v.z) for v in arc] + [first[-1]]
    wall = resample_line(arc, n)
    g.put(ck.grid_sheet(uv, [first, wall], "structure"), None, group)


WINDSCREEN_DECK = 0.004  # the coaming deck's top under the windscreen's foot line (PROFILE bottom less 10 mm)


def windscreen_deck_z(s):
    """The coaming deck's top ahead of the hood: under the windscreen's foot, or the deck line where higher."""
    foot = bi.resample(canopy.PROFILE, [s])[0][3] - 0.010
    return max(deck_z(s) - FRONT["margin"], foot - WINDSCREEN_DECK)


def resample_line(points, n):
    """n points spaced evenly by arc length along a polyline."""
    pts = [Vector(p) for p in points]
    run = [0.0]
    for a, b in zip(pts, pts[1:]):
        run.append(run[-1] + (b - a).length)
    out = []
    for i in range(n):
        t = run[-1] * i / (n - 1)
        k = max(j for j in range(len(run) - 1) if run[j] <= t + 1e-12) if t < run[-1] else len(run) - 2
        f = (t - run[k]) / max(run[k + 1] - run[k], 1e-12)
        out.append(pts[k].lerp(pts[k + 1], min(max(f, 0.0), 1.0)))
    return out


# --- the missile warning lamps --------------------------------------------------------------------------------------

LAMPS = {
    # two groups of two, one over each of the main displays' top outboard corners, as the Vortex, Ifrit and OA-27 place
    # theirs: rectangular lenses side by side in a dark housing with no legend, as the OA-27's (30.5 x 13.5 mm, 33 mm
    # apart), at the Ifrit's lens size (17.5 x 10.6 mm); .cache/board/lamps/
    "lens": (0.020, 0.013), "pitch": 0.023, "housing": (0.050, 0.024, 0.007), "seg": 2,
    "inset": 0.034,  # the housing's centre in from the bezel's outboard edge
    "master_inset": 0.084,  # the master warning (left) and caution (right) lamps' centres, inboard of the housings
}


def lamp_housings(g, kit, atlas, uv, y_top):
    """On the display face over the bezel, under the rim: over each outboard top corner a lamp housing with two dark
    red lenses (the lamps unlit), and inboard of it the master warning (left) or caution (right) push lamp. Returns the
    lens placements for the lamp mesh."""
    lw, lh = LAMPS["lens"]
    hw_, hh, hd = LAMPS["housing"]
    lenses = []
    m = face_frame()
    bz = FRONT["bezel"]
    lay = main_glass()
    bx = lay["B"][1] + bz["side"]  # the bezel's outboard edge, |face X|
    y = bz["top"] + 0.003 + hh / 2  # just over the bezel's top
    if y + hh / 2 > y_top - 0.002:
        raise ValueError("cockpit: the warning lamps (to y %.3f) pass the display face's top (%.3f)" % (y + hh / 2, y_top))
    for side in (1, -1):
        hm = m @ Matrix.Translation((-side * (bx - LAMPS["inset"]), y, 0.0))
        rings = [ring_rect(hw_ / 2, hh / 2, 0.0, 0.004, 2), ring_rect(hw_ / 2, hh / 2, hd - 0.0015, 0.004, 2),
                 ring_rect(hw_ / 2 - 0.0015, hh / 2 - 0.0015, hd, 0.0028, 2)]
        g.put(stack(uv, rings, "bezel", top_uv="bezel", bottom_hidden=True), hm, "front")
        for dx in (LAMPS["pitch"] / 2, -LAMPS["pitch"] / 2):
            lm = hm @ Matrix.Translation((dx, 0.0, hd))
            # the lens stands 0.6 mm proud of the housing's face, the lit lamp 0.5 mm over it
            lens = [ring_rect(lw / 2, lh / 2, -0.0012, 0.003, LAMPS["seg"]), ring_rect(lw / 2, lh / 2, 0.0006, 0.003, LAMPS["seg"])]
            g.put(stack(uv, lens, "bezel_dark", top_uv=atlas.tile("lens_off"), bottom_hidden=True), lm, "front")
            lenses.append(lm @ Matrix.Translation((0.0, 0.0, 0.0011)))
        g.put(kit.indicator("lens_red" if side > 0 else "lens_amber", "MASTER\nWARN" if side > 0 else "MASTER\nCAUT"),
              m @ Matrix.Translation((-side * (bx - LAMPS["master_inset"]), y, 0.0)), "front")
    return lenses


def lamp_mesh(lenses):
    """The missile warning lamps on CockpitWarningLight (lightRenderers): a domed lens over each unlit one, 12 tris."""
    g = ck.Gather(ck.WARNING_LAMPS)
    lw, lh = LAMPS["lens"]
    flat = lambda spec, pts, box=None, along=None: [(0.5, 0.5)] * len(pts)
    for m in lenses:
        ring = [Vector(p) for p in ring_rect(lw / 2 - 0.0004, lh / 2 - 0.0004, 0.0, 0.0028, 2)]
        apex = Vector((0.0, 0.0, 0.0012))
        piece = Piece(sheet=True, keep=True)
        k = len(ring)
        piece.add(ring + [apex], [(i, (i + 1) % k, k) for i in range(k)], [[(0.5, 0.5)] * 3 for _ in range(k)])
        g.put(piece, m, "lamp")
    return g


# --- the whole front office ------------------------------------------------------------------------------------------

def build(g, kit, atlas, uv, space):
    """Everything forward of the consoles; returns the screen quads (A, B, C, D in DISPLAYS' order), the lamp
    placements and the faces (for the layout plan)."""
    MOVERS.clear()
    screens, y_top = display_face(g, kit, atlas, uv)
    y_rim_top, _ = rim(g, atlas)
    st, c_screen = stem(g, kit, atlas, uv)
    d_screen, faces = wings(g, kit, atlas, uv)
    faces += closures(g, atlas, uv)
    ped = pedestal(g, kit, atlas, uv)
    faces += side_panels(g, kit, atlas, uv, space)
    shroud(g, atlas, uv, space, y_top)
    lenses = lamp_housings(g, kit, atlas, uv, y_top)
    screens = screens + c_screen + d_screen
    # the display face, for the panel-cover check: drawn round the bezel by display_face, not as a Face
    hw = FRONT["half_width"]
    shown = Face("display", face_frame(), rect(-hw, face_y(FRONT["face_bottom_z"]), hw, y_top), None)
    return screens, lenses, [shown, st] + faces + [ped]
