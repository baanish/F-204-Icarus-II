"""The arrestor hook and the fairing it stows in, for carrier landings on the Hyperion.

The hook is the stock Compass's (TailHook_Trainer): 1.953 m from hinge to point, turned on its local X by the game's
TailHook between a stowed and a deployed angle, and caught by a wire when the line from its hinge to its point crosses
one (TailHook.FixedUpdate's Physics.Linecast). It is a store on its own Tail Hook hardpoint set, not part geometry: this
module builds its arm, shoe and trunnion in its own collection (as tip_tanks.py keeps the tank in Stores), its mesh in the hook transform's frame (export), and
IcarusAuthor.TailHook.cs clones the Compass mount around it.

It stows flush in a fairing grown from the ventral fin, the owner's pick of four designs (variant D, 2026-10-29), which
comes with the hook: without it the Icarus keeps its original ventral fin. Variant D's fin (HOOKED_FIN) is a copy of the
original cut at its thickest line (FIN_CUT, chord fraction 0.5 at root and tip, where its web is as thick as it gets);
from there its web runs on aft to the nozzle, and its lower edge widens into a pod POD wide that hangs up to 0.26 m
below the tail cone. The hook lies in a slot in the pod's bottom on a straight line (LINE) with its hinge at HINGE_S,
behind the original fin's trailing edge, so it never swings toward either fin, and its point under the nozzle. The
fairing is a skin patch (the generator's own smooth-union fields: the body's, the web's and the pod's) joined into
HOOKED_FIN's mesh and welded to the kept fin at the cut, its first row the fin's own end section vertex for vertex and its
columns following the fin's root and tip corner aft (row), so the two are one surface. It lies just outside the
belly's loft where it covers it, which stays whole (the well's floor is below it at every
station), so it rides the tail cone with the fins (parts.LATE_PARENTS) and takes their livery; the slot's well is dark
like the gear wells. The Tail Hook hardpoint shows one fin or the other, the stock way (Hardpoint.Plug and pylonOptions,
IcarusAuthor.TailHook.cs). The original fin gets collider hulls on the tail cone, and HOOKED_FIN's web and pod get theirs
in their own collection (fin_hulls), which the mount carries and the plugin puts on the tail cone while the hook is
fitted (src/Icarus/TailHookFairing.cs). Both sets keep off the hook's line from hinge to point in every pose (check):
the linecast has no layer mask, and a hit on the jet's own collider backs the hook off as it would a deck.

Frame: Blender, nose -Y, up +Z, left +X; station s = y + 8.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import build_icarus as bi

KEY = "baanish_icarus_tail_hook"
NAME = "tail_hook"
COLLECTION = "TailHook"
FAIRING = "ventral_fin_fairing"
HOOKED_FIN = "ventral_fin_hooked"  # variant D's fin and fairing, drawn only with the hook fitted
HULL = "tail_hook_hull"  # HOOKED_FIN's own collider hulls, exported with the hook
HULLS = "TailHookHulls"  # their collection
LENGTH = 1.953  # the Compass hook, hinge to hookEnd (TailHook_Trainer.prefab), so the catch reach is the donor's
HINGE_S = 13.20  # behind the kept fin's trailing edge
# The pod's bottom, the hook's line: (s, z) at two stations, the fin's tip height ahead of it, rounded into it over CORNER.
LINE = ((13.06, -0.575), (15.16, -0.150))
CORNER = 0.04
# The pod: half width, half height and superellipse exponent, grown along the web's lower edge over POD_GROW metres
# from the cut; K the fillet of its union with the body.
POD, POD_GROW, K = (0.10, 0.10, 2.5), 1.0, 0.05
X_EDGE = 0.28  # the fairing patch's half width, where it lies on the old skin
# The hook: arm and shoe half widths, depth at the hinge and at the shoe, shoe length and the taper into it, the gap
# to the slot's walls; the notch in its point's underside faces forward, so a wire slides into the throat.
ARM_W, SHOE_W, D0, D1, SHOE, TAPER, GAP = 0.045, 0.070, 0.11, 0.085, 0.30, 0.12, 0.010
# Deployed, the point sits this far below the deck at level attitude with the gear free, so it reaches the deck at
# every nose-up attitude (the Compass's reaches 0.17 m).
OVERTRAVEL = 0.15
# The hook wears the airframe skin with every UV on one point of the atlas, as the tip tank does: the fairing's left
# flank at PAINT_S, mid-height on the pod, a clean panel well ahead of its joint (art/textures/panels.py
# BARE_AFT_JOINT_S), so it takes the fin's paint in every livery, and the plugin hands it the livery the jet wears. Its
# UVs spread over SPREAD of the atlas round the point (a few texels), so Unity can build tangents.
PAINT_S, SPREAD = 13.70, 0.0008
PATCH_OUT = 0.0006  # the patch stands this far outside the true surface, over the old skin's facets
PATCH_FADE = 0.01  # and lies on the true surface where it stands this far off the old skin: the web, flush with the fin
ROW_STEP = 0.10  # metres between the patch's rows; the hook's are finer at its point
# Points across each half of the patch: over the body to the web's root, down the web to the split (the slot's edge, or
# ahead of the slot the web's lower corner), and across between the splits.
COLUMNS = (6, 9, 7)
SEAM = 0.001  # most the fairing's first row may stand off the kept fin's end section (check)
# Clearances the swing must keep (check): the fin and fairing ahead of the slot, the engine and nozzle, the well and
# skin, and the hook's line to every collider hull of the jet.
CLEAR = {"fin_ahead_of_slot": 0.030, "afterburner_nozzle": 0.040, "well_and_skin": 0.002, "line_to_hulls": 0.010}
SWEEP_STEPS = 40
AOA = 6.6  # the AI's approach angle of attack at 30 m (approach_speed, 2026-10-20): the landing attitude measured
BUDGET = {"tail_hook": {"target": 1300, "cap": 1400, "collection": COLLECTION}}
CLOSEUPS = {
    "tail_hook_side": (Vector((4.2, 6.0, -0.9)), Vector((0.0, 5.6, -0.3))),
    "tail_hook_below": (Vector((1.6, 7.6, -2.8)), Vector((0.0, 5.6, -0.35))),
}
TREE = {}

S0 = bi.S0


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def smax(a, b, k):
    return -bi.smin(-a, -b, k)


def fin_sections(p):
    (le_root, _, z_root, c_root), (le_tip, _, z_tip, c_tip) = p["ventral_fin"]["sections"]
    return le_root, z_root, c_root, le_tip, z_tip, c_tip


def fin_cut(p):
    """The station where the kept fin ends: its thickest line (the biconvex section's chord fraction 0.5)."""
    le_root, _, c_root, le_tip, _, c_tip = fin_sections(p)
    cut = le_tip + 0.5 * c_tip
    if abs(le_root + 0.5 * c_root - cut) > 1e-6:
        raise ValueError("tail hook: the ventral fin's thickest line is not one station (%.4f, %.4f)"
                         % (le_root + 0.5 * c_root, cut))
    return cut


def fin_web_half(p, z):
    """The ventral fin's half thickness at its thickest line, at height z, as its loft draws it: the cut crosses the facet
    between the chord points either side of the line (bi.lifting_surface), which share a thickness, the biconvex's being
    symmetric."""
    _, z_root, c_root, _, z_tip, c_tip = fin_sections(p)
    f = min(1.0, max(0.0, (z - z_tip) / (z_root - z_tip)))
    t = 0.5 * (1 - math.cos(math.pi * ((bi.CHORD - 1) // 2) / (bi.CHORD - 1)))
    return p["ventral_fin"]["thickness"] * (c_tip + (c_root - c_tip) * f) * bi.airfoil(t)


def zline(p, s):
    (s0, z0_), (s1, z1) = LINE
    return smax(fin_sections(p)[4], z0_ + (z1 - z0_) * (s - s0) / (s1 - s0), CORNER)


def body_field(p, s):
    skin, zc = bi.skin_field(p, s)
    sq = bi.area_squeeze(p, s)
    return lambda x, z: skin(x / sq, zc + (z - zc) / sq) * sq


def fairing_field(p, s):
    """The skin with the fin's web (flat-bottomed on the line) smooth-unioned with the pod, then with the body."""
    body = body_field(p, s)
    z_tip = fin_sections(p)[4]
    g = smooth((s - fin_cut(p)) / POD_GROW)
    zb = zline(p, s)
    A, B, e = POD
    a = fin_web_half(p, z_tip) + (A - fin_web_half(p, z_tip)) * g
    kb, kr = 0.001 + 0.03 * g, 0.002 + (K - 0.002) * g  # no fillets at the cut, where the kept fin is sharp
    web = lambda x, z: max(abs(x) - fin_web_half(p, z), zb - z)
    pod = lambda x, z: bi.lobe(x, z - zb - B, a, B, B, e, e)
    return lambda x, z: bi.smin(body(x, z), bi.smin(web(x, z), pod(x, z), kb), kr)


def x_edge(p, s):
    return min(X_EDGE, 0.88 * bi.pchip([r[0] for r in p["fuselage"]], [r[1] for r in p["fuselage"]], s))


_contours = {}


def contour(p, s, fairing=True, h=0.002):
    """The section's lower outline at s for |x| <= x_edge, left to right, as an (n, 2) array (marching squares)."""
    key = (round(s, 5), fairing)
    if key in _contours:
        return _contours[key]
    f = fairing_field(p, s) if fairing else body_field(p, s)
    xe = x_edge(p, s)
    xs = np.arange(-xe - 0.012 + 0.137 * h, xe + 0.012 + 1e-9, h)  # off-grid, so a flat bottom never lies on a row
    zs = np.arange(zline(p, s) - 0.08 + 0.291 * h, 0.30, h)
    F = np.array([[f(x, z) for x in xs] for z in zs])
    pts, segs = {}, []

    def node(q):
        q = (round(q[0], 7), round(q[1], 7))
        return pts.setdefault(q, len(pts))

    def cross(i0, j0, i1, j1):
        a, b = F[j0, i0], F[j1, i1]
        t = a / (a - b)
        return (xs[i0] + t * (xs[i1] - xs[i0]), zs[j0] + t * (zs[j1] - zs[j0]))

    for j in range(len(zs) - 1):
        for i in range(len(xs) - 1):
            c = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            hits = []
            for e in range(4):
                (ia, ja), (ib, jb) = c[e], c[(e + 1) % 4]
                if (F[ja, ia] < 0) != (F[jb, ib] < 0):
                    hits.append(cross(ia, ja, ib, jb))
            if len(hits) == 2:
                segs.append((node(hits[0]), node(hits[1])))
            elif len(hits) == 4:  # saddle: the centre's sign says which diagonal pair is joined
                joined = ((F[j, i] + F[j, i + 1] + F[j + 1, i + 1] + F[j + 1, i]) < 0) == (F[j, i] < 0)
                pairs = ((0, 1), (2, 3)) if joined else ((3, 0), (1, 2))
                segs += [(node(hits[a]), node(hits[b])) for a, b in pairs]
    coords = {v: k for k, v in pts.items()}
    adj = {}
    for a, b in segs:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    start = min((n for n in adj if len(adj[n]) == 1), key=lambda n: coords[n][0])
    chain, seen, cur = [start], {start}, start
    while True:
        nxt = [n for n in adj[cur] if n not in seen]
        if not nxt:
            break
        cur = nxt[0]
        seen.add(cur)
        chain.append(cur)
    c = np.array([coords[n] for n in chain])
    if c[0, 0] > c[-1, 0]:
        c = c[::-1]
    c = trim(c, -xe, xe)
    _contours[key] = c
    return c


def trim(c, x0, x1):
    i = next(k for k in range(len(c) - 1) if c[k, 0] <= x0 <= c[k + 1, 0])
    j = next(k for k in range(len(c) - 1, 0, -1) if c[k - 1, 0] <= x1 <= c[k, 0])
    lerp = lambda a, b, x: a + (b - a) * (x - a[0]) / (b[0] - a[0])
    return np.vstack([lerp(c[i], c[i + 1], x0), c[i + 1:j], lerp(c[j - 1], c[j], x1)])


def at_x(c, x, side):
    """Where c's bottom run crosses x (of all crossings, the lowest), and the split index row() uses."""
    best = None
    for i in range(len(c) - 1):
        a, b = c[i], c[i + 1]
        if a[0] != b[0] and min(a[0], b[0]) <= x <= max(a[0], b[0]):
            q = a + (b - a) * (x - a[0]) / (b[0] - a[0])
            if best is None or q[1] < best[0][1]:
                best = (q, i + 1 if side < 0 else i)
    if best is None:
        raise ValueError("tail hook: no outline crossing at x=%.3f" % x)
    return best


def z0(p, s):
    """The fairing's bottom on the centre line."""
    return float(at_x(contour(p, s), 0.0, 1)[0][1])


def resample(seg, n):
    d = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(seg, axis=0), axis=1))])
    t = np.linspace(0, d[-1], n)
    return np.column_stack([np.interp(t, d, seg[:, 0]), np.interp(t, d, seg[:, 1])])


def nearest(c, q):
    """The point of polyline c nearest q, and the index of the segment it lies on."""
    a, d = c[:-1], np.diff(c, axis=0)
    t = np.clip(((q - a) * d).sum(1) / np.maximum((d * d).sum(1), 1e-18), 0, 1)
    pts = a + d * t[:, None]
    k = int(np.argmin(np.linalg.norm(pts - q, axis=1)))
    return pts[k], k


def web_root(p, s):
    """Where the web's left flank meets the body before their fillet, (x, z): at the cut, the kept fin's root on the skin."""
    body, zc = body_field(p, s), bi.skin_field(p, s)[1]
    lo, hi = zline(p, s), zc
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if body(-fin_web_half(p, mid), mid) > 0 else (lo, mid)
    return np.array([-fin_web_half(p, lo), lo])


def row(p, s, w, slot):
    """The outline at s as (left, mid, right), mirrored about the centre line and resampled to COLUMNS: left runs over
    the body to the web's root, then down the web (and the pod) to the split at x = -w in the slot, ahead of it at the
    web's lower corner; mid runs across between the splits, its ends shared. Each column follows one feature of the
    section from row to row, so from the cut on the fairing's columns are the kept fin's own root and tip corner."""
    c = contour(p, s)
    root, kr = nearest(c, web_root(p, s))
    zb = zline(p, s)
    if slot:
        split, ks = at_x(c, -w, -1)
        ks -= 1
    else:
        split, ks = nearest(c, np.array([-fin_web_half(p, zb), zb]))
    centre, kc = at_x(c, 0.0, -1)
    kc -= 1
    if not kr <= ks <= kc:
        raise ValueError("tail hook: the section at s %.3f runs out of order (root, split, centre)" % s)
    body = np.vstack([c[:kr + 1], root])
    side = np.vstack([root, c[kr + 1:ks + 1], split])
    left = np.vstack([resample(body, COLUMNS[0]), resample(side, COLUMNS[1])[1:]])
    half = resample(np.vstack([split, c[ks + 1:kc + 1], centre]), (COLUMNS[2] + 1) // 2)
    mirror = lambda q: q[::-1] * (-1, 1)
    return left, np.vstack([half, mirror(half)[1:]]), mirror(left)


def fin_section(p, pts):
    """The cut row put on the kept fin's end section: its root and flank columns on the flank, its splits on the tip's
    corners, the columns between on the tip. Returns the row and its web part, the seam hooked_fin splits the fin at."""
    z_tip = fin_sections(p)[4]
    root, corner = COLUMNS[0] - 1, COLUMNS[0] + COLUMNS[1] - 2
    out, n = pts.copy(), len(pts)
    for k in range(root, n - root):
        x, z = pts[k]
        j, sign = min(k, n - 1 - k), (-1 if k < n / 2 else 1)
        out[k] = ((sign * fin_web_half(p, z), z) if j < corner else
                  (sign * fin_web_half(p, z_tip), z_tip) if j == corner else (x, z_tip))
    return out, out[root:n - root]


def offset(pts, d):
    t = np.gradient(pts, axis=0)
    t /= np.linalg.norm(t, axis=1)[:, None]
    return pts + np.column_stack([t[:, 1], -t[:, 0]]) * np.asarray(d)[:, None]


def W(s, x, z):
    return Vector((x, s - S0, z))


class Hook:
    """The hook's stations along the slot: hinge, point, the slot's front wall, and the arm's width and depth."""

    def __init__(self, p):
        self.p = p
        self.cut = fin_cut(p)
        self.s_h = HINGE_S
        self.z_h = z0(p, self.s_h) + D0 / 2
        lo, hi = self.s_h + 1.7, self.s_h + 2.1
        for _ in range(14):  # the point on the slot's bottom line, LENGTH from the hinge
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if self.gap(mid) < 0 else (lo, mid)
        self.s_t = (lo + hi) / 2
        self.z_t = z0(p, self.s_t) + 0.003
        self.s_f = self.s_h - D0 / 2 - GAP

    def gap(self, s):
        return math.hypot(s - self.s_h, z0(self.p, s) + 0.003 - self.z_h) - LENGTH

    def width(self, s):
        u = min(1.0, max(0.0, (s - (self.s_t - SHOE - TAPER)) / TAPER))
        return ARM_W + (SHOE_W - ARM_W) * u

    def depth(self, s):
        u = min(1.0, max(0.0, (s - self.s_h) / (self.s_t - SHOE - self.s_h)))
        return D0 + (D1 - D0) * u

    def notch(self, s):
        a, b = self.s_t - 0.25, self.s_t - 0.11
        if not a < s < b:
            return 0.0
        return 0.036 * math.sin(math.pi * ((s - a) / (b - a)) ** 0.6)  # a steep aft wall: the throat faces forward

    def in_slot(self, s):
        return self.s_f - 1e-3 <= s <= self.s_t + 1e-3

    def stowed_tip_deg(self):
        return math.degrees(math.atan2(self.z_t - self.z_h, self.s_t - self.s_h))


def patch_rows(hook):
    rows = set(round(x, 4) for x in np.arange(hook.cut, hook.s_t, ROW_STEP))
    rows |= {round(hook.s_f, 4), round(hook.s_h, 4), round(hook.s_t - SHOE - TAPER, 4), round(hook.s_t - SHOE, 4),
             round(hook.s_t, 4)}
    return sorted(s for s in rows if hook.cut <= s <= hook.s_t + 1e-3)


def build_fairing(p, mats, hook):
    """The fairing patch with its slot and well, tagged to join the ventral fin (parts.merge_details), and the web part
    of its first row, which is the kept fin's end section (fin_section)."""
    rows = patch_rows(hook)
    verts, faces, skin_faces, grid, slot_cols, well_rows = [], [], [], [], None, []
    for s in rows:
        w = hook.width(s) + GAP
        left, mid, right = row(p, s, w, hook.in_slot(s))
        pts, body = np.vstack([left, mid[1:-1], right]), body_field(p, s)
        out = offset(pts, [PATCH_OUT * (1 - smooth(body(x, z) / PATCH_FADE)) for x, z in pts])
        if s == hook.cut:
            out, seam = fin_section(p, out)
        grid.append(len(verts))
        verts += [W(s, x, z) for x, z in out]
        slot_cols = (len(left) - 1, len(left) - 1 + len(mid) - 1)
        if hook.in_slot(s):
            well_rows.append((s, w, out[slot_cols[0]], out[slot_cols[1]], out[slot_cols[0]:slot_cols[1] + 1]))
    ncol = len(verts) // len(rows)
    for j in range(len(rows) - 1):
        a, b = grid[j], grid[j + 1]
        cut = hook.in_slot(rows[j]) and hook.in_slot(rows[j + 1])
        for k in range(ncol - 1):
            if not (cut and slot_cols[0] <= k < slot_cols[1]):
                skin_faces.append((a + k, a + k + 1, b + k + 1, b + k))
    # the well: floor clear of the hook's top, walls down to the slot's edges, front wall; it faces into the slot
    z_floor = {}
    for s, w, pl, pr, mid in well_rows:
        z_floor[s] = z0(p, s) + 0.003 + hook.depth(s) + 0.012 + (max(mid[:, 1]) - min(mid[:, 1]))
    well_faces, fl = [], []
    for s, w, pl, pr, mid in well_rows:
        fl.append(len(verts))
        verts += [W(s, pl[0], pl[1]), W(s, -w, z_floor[s]), W(s, w, z_floor[s]), W(s, pr[0], pr[1])]
    for a, b in zip(fl, fl[1:]):
        well_faces += [(a, b, b + 1, a + 1), (a + 1, b + 1, b + 2, a + 2), (a + 2, b + 2, b + 3, a + 3)]
    s, w, pl, pr, mid = well_rows[0]
    i = len(verts)
    verts += [W(s, x, z) for x, z in mid] + [W(s, w, z_floor[s]), W(s, -w, z_floor[s])]
    well_faces.append(tuple(range(i, len(verts))))
    # aft cap: from the new outline up to the old one, sampled at the new outline's own points (the two run tangent at
    # the patch's edges, so any other sampling crosses itself), and across the well's mouth from its floor up; one
    # welded strip, as a concave n-gon unwraps folded
    s = rows[-1]
    w = hook.width(s) + GAP
    old = contour(p, s, fairing=False)
    top = lambda x, z: max(float(np.interp(x, old[:, 0], old[:, 1])) + PATCH_OUT, z)

    def lift(k):
        v = verts[grid[-1] + k]
        z = top(v.x, v.z)
        if z - v.z < 1e-4:
            return grid[-1] + k
        verts.append(W(s, v.x, z))
        return len(verts) - 1

    def strip(bottom, upper):
        for (a, b), (c, d) in zip(zip(bottom, bottom[1:]), zip(upper, upper[1:])):
            face = [a, b] + ([d] if d != b else []) + ([c] if c != a else [])
            if len(face) >= 3:
                skin_faces.append(tuple(face))

    lifted = {}
    for ks in (range(0, slot_cols[0] + 1), range(slot_cols[1], ncol)):
        lifted.update((k, lift(k)) for k in ks)
        strip([grid[-1] + k for k in ks], [lifted[k] for k in ks])
    floor_l, floor_r = fl[-1] + 1, fl[-1] + 2
    xs = np.linspace(-w, w, COLUMNS[2])
    bottom = [floor_l]
    for x in xs[1:-1]:
        verts.append(W(s, x, z_floor[s]))
        bottom.append(len(verts) - 1)
    bottom.append(floor_r)
    upper = []
    for x in xs:
        verts.append(W(s, x, top(x, z_floor[s] + 0.002)))
        upper.append(len(verts) - 1)
    strip(bottom, upper)
    edge_l, edge_r = grid[-1] + slot_cols[0], grid[-1] + slot_cols[1]  # the mouth band's sides, across the walls' foot
    for face in ((edge_l, floor_l, upper[0], lifted[slot_cols[0]]), (floor_r, edge_r, lifted[slot_cols[1]], upper[-1])):
        xz = [(verts[i].x, verts[i].z) for i in face]
        if abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xz, xz[1:] + xz[:1]))) > 1e-9:  # none where the wall's foot is on the outline
            skin_faces.append(face)
    obj = bi.mesh_object(FAIRING, verts, skin_faces + well_faces)
    obj.data.materials.append(mats["body"])
    obj.data.materials.append(mats["gear_bay"])
    for poly in obj.data.polygons:
        poly.material_index = 1 if poly.index >= len(skin_faces) else 0
        poly.use_smooth = poly.material_index == 0
    obj.data.set_sharp_from_angle(angle=math.radians(40))  # as bi.finish shades the fin: its tip's corner runs on sharp
    orient(obj, p, hook, z_floor)
    obj["merge_into"] = HOOKED_FIN
    return obj, z_floor, seam


def orient(obj, p, hook, z_floor):
    """Wind the skin faces out of the fairing and the well's faces into the slot (the game culls back faces)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    flip = []
    for f in bm.faces:
        c, n = f.calc_center_median(), f.normal
        s = c.y + S0
        if f.material_index == 0:
            field = fairing_field(p, min(max(s, hook.cut), hook.s_t))
            outward = field(c.x + 0.003 * n.x, c.z + 0.003 * n.z) > field(c.x - 0.003 * n.x, c.z - 0.003 * n.z)
            if abs(n.y) > 0.9:  # the aft cap faces aft
                outward = n.y > 0
        else:
            centre = Vector((0.0, c.y, z0(p, min(max(s, hook.s_f), hook.s_t)))) - c
            outward = n.dot(centre) > 0 if abs(n.y) < 0.9 else n.y > 0  # the front wall faces aft, into the slot
        if not outward:
            flip.append(f)
    bmesh.ops.reverse_faces(bm, faces=flip)
    bm.to_mesh(obj.data)
    bm.free()


def hooked_fin(seam):
    """HOOKED_FIN: a copy of the ventral fin that keeps its forward half; the fairing's web runs on from the cut. The cut's
    edges are split at the fairing's first row (seam, (x, z) on the cut), so the two weld there (weld_seam)."""
    fin = bpy.data.objects["ventral_fin"]
    ob = fin.copy()
    ob.data = fin.data.copy()
    ob.name = ob.data.name = HOOKED_FIN
    for coll in fin.users_collection:
        coll.objects.link(ob)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    mwi = ob.matrix_world.inverted()
    cut = fin_cut(bi.PARAMS)
    res = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=mwi @ W(cut, 0, 0),
                                 plane_no=(mwi.to_3x3() @ Vector((0, 1, 0))).normalized(), clear_outer=True)
    edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge) and e.is_valid]
    for x, z in seam:
        co = mwi @ W(cut, x, z)
        if any((v.co - co).length < 1e-5 for e in edges for v in e.verts):
            continue
        e = min(edges, key=lambda e: segment_distance(co, *(v.co for v in e.verts)))
        if segment_distance(co, *(v.co for v in e.verts)) > 1e-5:
            raise ValueError("tail hook: the fairing's first row leaves the kept fin's end section at x %.4f z %.4f" % (x, z))
        a, b = e.verts
        new, v = bmesh.utils.edge_split(e, a, (co - a.co).dot(b.co - a.co) / (b.co - a.co).length_squared)
        v.co = co
        edges.append(new)
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def segment_distance(q, a, b):
    d = b - a
    t = min(1.0, max(0.0, (q - a).dot(d) / d.length_squared)) if d.length_squared else 0.0
    return (a + d * t - q).length


def weld_seam(icarus):
    """Weld the fairing's first row to the kept fin's cut edges, which hooked_fin split at its points, so fin and fairing
    are one surface: shading and UVs run on across the cut. Runs after parts.merge_details joins the fairing in."""
    fin = bpy.data.objects[HOOKED_FIN]
    y = fin_cut(bi.PARAMS) - S0
    mw = fin.matrix_world
    bm = bmesh.new()
    bm.from_mesh(fin.data)
    on_cut = [v for v in bm.verts if abs((mw @ v.co).y - y) < 1e-5]
    bmesh.ops.remove_doubles(bm, verts=on_cut, dist=1e-5)
    for e in bm.edges:  # the cut runs between faces tangent across it; the fin's corner is its chordwise edges
        if len(e.link_faces) == 2 and all(abs((mw @ v.co).y - y) < 1e-5 for v in e.verts):
            e.smooth = True
    bm.to_mesh(fin.data)
    bm.free()


def hook_mesh(p, hook):
    """The arm and shoe, flush in the slot when stowed, and the trunnion through the hinge, in world space."""
    rows = set(round(x, 4) for x in np.arange(hook.s_h, hook.s_t, ROW_STEP))
    rows |= {round(hook.s_h - D0 / 2 + 0.002, 4), round(hook.s_h - D0 / 2 * 0.7, 4), round(hook.s_h - D0 / 2 * 0.35, 4),
             round(hook.s_t - SHOE - TAPER, 4), round(hook.s_t - SHOE, 4), round(hook.s_t, 4)}
    rows |= set(round(x, 4) for x in np.arange(hook.s_t - 0.26, hook.s_t - 0.09, 0.015))
    rows = sorted(s for s in rows if hook.s_h - D0 / 2 < s <= hook.s_t + 1e-3)
    verts, faces, NB = [], [], 7
    for s in rows:
        w = hook.width(s)
        c = contour(p, max(s, hook.cut))
        xs = np.linspace(-w, w, NB)
        bot = np.array([at_x(c, x, -1 if x < 0 else 1)[0][1] for x in xs]) + 0.003 + hook.notch(s)
        top = z0(p, s) + 0.003 + hook.depth(s) + (max(bot) - min(bot))
        zl, zh = bot, np.full(NB, top)
        if s < hook.s_h:  # the nose, rounded about the hinge
            r = math.sqrt(max(0.0, (D0 / 2) ** 2 - (hook.s_h - s) ** 2))
            zl = np.maximum(zl, hook.z_h - r)
            zh = np.minimum(zh, hook.z_h + r)
        ch = 0.3 * w
        sec = list(zip(xs, zl)) + [(w, zh[-1] - ch), (w - ch, zh[-1]), (-(w - ch), zh[0]), (-w, zh[0] - ch)]
        verts += [W(s, x, z) for x, z in sec]
    n = NB + 4
    for j in range(len(rows) - 1):
        a, b = j * n, (j + 1) * n
        faces += [(a + k, b + k, b + (k + 1) % n, a + (k + 1) % n) for k in range(n)]
    faces.append(tuple(range(n)))
    faces.append(tuple(range((len(rows) - 1) * n, len(rows) * n))[::-1])
    # the trunnion: a 20-sided cylinder across the hinge, inside the well's walls
    half, r, base = hook.width(hook.s_h) + GAP - 0.003, 0.028, len(verts)
    for side in (-1, 1):
        verts += [W(hook.s_h + r * math.cos(2 * math.pi * k / 20), side * half, hook.z_h + r * math.sin(2 * math.pi * k / 20))
                  for k in range(20)]
    faces += [(base + k, base + (k + 1) % 20, base + 20 + (k + 1) % 20, base + 20 + k) for k in range(20)]
    faces += [tuple(base + k for k in range(20))[::-1], tuple(base + 20 + k for k in range(20))]
    return verts, faces


# Blender vectors to Unity's (export_blockout.to_unity), and the Unity rotation about its X the game's TailHook turns.
C = Matrix(((-1, 0, 0), (0, 0, 1), (0, -1, 0)))


def unity_x(deg):
    a = math.radians(deg)
    return Matrix(((1, 0, 0), (0, math.cos(a), -math.sin(a)), (0, math.sin(a), math.cos(a))))


def hook_rotation(local_x_deg):
    """The hook transform's rotation in Blender world for TailHook's local X angle: the mount turns its hinge 180
    degrees about X, as the Compass's does, so hookEnd at local -Z (LENGTH) points aft, its tip local_x_deg - 180
    degrees above horizontal."""
    return (C.inverted() @ unity_x(180.0) @ unity_x(local_x_deg) @ C).to_4x4()


def build(p, mats):
    """Variant D's fin and fairing beside the original fin, and the hook in its collection, posed stowed."""
    _contours.clear()
    hook = Hook(p)
    fairing, z_floor, seam = build_fairing(p, mats, hook)
    fin = hooked_fin(seam)
    verts, faces = hook_mesh(p, hook)
    hinge = W(hook.s_h, 0.0, hook.z_h)
    stowed = 180.0 + hook.stowed_tip_deg()
    frame = Matrix.Translation(hinge) @ hook_rotation(stowed)
    to_local = frame.inverted()
    me = bpy.data.meshes.new(NAME)
    me.from_pydata([tuple(to_local @ v) for v in verts], [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new(NAME, me)
    bi.collection(COLLECTION).objects.link(obj)
    obj.matrix_world = frame
    bi.finish(obj, mats["body"], smooth=False)
    me.uv_layers.new(name="UVMap")  # on the fairing's paint once the atlas is unwrapped (paint)
    obj["stowed_deg"] = stowed
    obj["hinge_s_z"] = [hook.s_h, hook.z_h]
    obj["point_s_z"] = [hook.s_t, hook.z_t]
    obj["slot_front_s"] = hook.s_f
    obj["fin_cut_s"] = hook.cut
    obj["well_floor"] = [[s, z] for s, z in sorted(z_floor.items())]
    obj["main_contact_s_z"] = list(main_contact())
    pose_hook(obj, 0.0)
    obj["deployed_deg"] = stowed - deployed_swing(obj)
    return fairing, fin, obj


def paint(icarus):
    """The hook's UVs round the fairing's paint point (PAINT_S). Runs after uvs.unwrap."""
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform

    import uvs

    fin, obj = bpy.data.objects[HOOKED_FIN], bpy.data.objects[NAME]
    me = fin.data
    me.calc_loop_triangles()
    uv = me.uv_layers["UVMap"].data
    tris = [t for t in me.loop_triangles if me.materials[t.material_index].name == uvs.SKIN]
    corners = [[fin.matrix_world @ me.vertices[i].co for i in t.vertices] for t in tris]
    tree = BVHTree.FromPolygons([v for c in corners for v in c], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))],
                                all_triangles=True)
    at, _, index, _ = tree.ray_cast(W(PAINT_S, 1.0, zline(bi.PARAMS, PAINT_S) + POD[1]), Vector((-1, 0, 0)), 2.0)
    if at is None:
        raise ValueError("tail hook paint: no fairing skin at the paint point")
    point = barycentric_transform(at, *corners[index], *[Vector((*uv[i].uv, 0)) for i in tris[index].loops]).to_2d()
    layer = obj.data.uv_layers["UVMap"]
    for loop in obj.data.loops:
        co = obj.data.vertices[loop.vertex_index].co
        layer.data[loop.index].uv = point + SPREAD * Vector((co.x / ARM_W / 4, co.z / LENGTH))
    obj["paint_uv"] = list(point)
    return point


def main_contact():
    """The main tyre's lowest point with the gear free, (s, z): the pivot of every attitude measured here."""
    wheel = bpy.data.objects["gear_wheel_L_visible"]
    low = min((wheel.matrix_world @ v.co for v in wheel.data.vertices), key=lambda v: v.z)
    return low.y + S0, low.z


def hook_point(obj):
    """hookEnd in world: LENGTH along the hook frame's local -Z (Unity), which is Blender local +Y."""
    return obj.matrix_world @ (C.inverted() @ Vector((0.0, 0.0, -LENGTH)))


def pose_hook(obj, swing_deg):
    """Swing the hook's point down by swing_deg from stowed."""
    loc = obj.matrix_world.translation.copy()
    obj.matrix_world = Matrix.Translation(loc) @ hook_rotation(obj["stowed_deg"] - swing_deg)
    bpy.context.view_layer.update()


def height(v, theta, contact, comp=0.0):
    """Height of world point v above a deck pitched theta degrees nose up about the main tyre's contact."""
    t = math.radians(theta)
    return (v.z - (contact[1] + comp)) * math.cos(t) - (v.y + S0 - contact[0]) * math.sin(t)


def hook_low(obj, theta, comp=0.0):
    contact = obj["main_contact_s_z"]
    m = obj.matrix_world
    return min(height(m @ v.co, theta, contact, comp) for v in obj.data.vertices)


def deployed_swing(obj):
    lo, hi = 5.0, 80.0
    for _ in range(30):  # the point OVERTRAVEL below the deck at level attitude, gear free
        mid = (lo + hi) / 2
        pose_hook(obj, mid)
        lo, hi = (mid, hi) if hook_low(obj, 0.0) > -OVERTRAVEL else (lo, mid)
    pose_hook(obj, 0.0)
    return (lo + hi) / 2


FIN_HULL_TRIS = 32  # each of the fin's collider hulls (hulls.capped)
FIN_HULL_INSIDE = 0.01  # how far a fin hull reaches up inside the body's skin, and stands clear above the well's floor


def fin_hulls(icarus):
    """The fins' collider hulls, each clipped FIN_HULL_INSIDE inside the body's skin. The original fin's, ahead of the
    cut and behind it, go on the tail cone it rides (parts.LATE_PARENTS) for every loadout. HOOKED_FIN's web ahead of
    the slot and its pod above the well's floor, in two lengths, go in their own collection (HULLS; its kept half is
    the original fin's), which the mount carries (export). None reaches the slot, so the hook's line from hinge
    to point meets none in any pose (check). Runs after hulls.rebuild_pieces, which carves the tail cone's shells afresh;
    returns how many go on the tail cone."""
    import hulls
    from parts import LATE_PARENTS

    p, obj = bi.PARAMS, bpy.data.objects[NAME]
    cut, s_f = obj["fin_cut_s"], obj["slot_front_s"]
    floor = np.array(obj["well_floor"])
    host = bpy.data.objects[LATE_PARENTS["ventral_fin"]]
    _contours.clear()

    def inside(v):
        s = v.y + S0
        top = float(at_x(contour(p, min(max(s, cut), floor[-1, 0]), fairing=False), 0.0, 1)[0][1]) + FIN_HULL_INSIDE
        return Vector((v.x, v.y, min(v.z, top)))

    def shapes(groups):
        out = []
        for group in groups:
            if len(group) < 8:
                continue
            bm = hulls.capped([inside(v) for v in group], FIN_HULL_TRIS)
            if hulls.solid(bm):
                out.append(bm)
            else:
                bm.free()
        return out

    def points(name):
        fin = bpy.data.objects[name]
        return [fin.matrix_world @ v.co for v in fin.data.vertices]

    pts = points("ventral_fin")
    original = shapes([[v for v in pts if v.y + S0 < cut + 0.002], [v for v in pts if v.y + S0 > cut - 0.002]])
    pts = points(HOOKED_FIN)
    above = lambda v: v.z > np.interp(v.y + S0, floor[:, 0], floor[:, 1]) + FIN_HULL_INSIDE
    mid = (s_f + floor[-1, 0]) / 2
    hooked = shapes([[v for v in pts if cut - 0.002 < v.y + S0 < s_f - 0.005],
                     [v for v in pts if s_f - 0.005 <= v.y + S0 < mid + 0.05 and above(v)],
                     [v for v in pts if mid - 0.05 <= v.y + S0 and above(v)]])
    store = bi.collection(HULLS)
    store.hide_render = True
    for i, bm in enumerate(hooked):
        me = bpy.data.meshes.new("%s%d" % (HULL, i))
        bm.to_mesh(me)
        bm.free()
        hull = bpy.data.objects.new(me.name, me)
        store.objects.link(hull)
        hull.display_type = "WIRE"
    return hulls.attach_colliders(host, original, bpy.data.collections["Colliders"])


def hull_objects():
    """HOOKED_FIN's collider hulls (fin_hulls), world space."""
    return sorted(bpy.data.collections[HULLS].objects, key=lambda o: o.name) if HULLS in bpy.data.collections else []


def segment_gap(tree, a, b, steps=40):
    """Least distance from the segment a-b to a BVH tree, and whether a ray along it hits the tree."""
    d = b - a
    hit = tree.ray_cast(a, d.normalized(), d.length)[0] is not None
    least = min(tree.find_nearest(a.lerp(b, i / steps))[3] for i in range(steps + 1))
    return least, hit


def seam_fit(p):
    """How the fairing meets the kept fin below the old skin: the farthest its first row stands off the original fin's
    section at the cut, the farthest a corner of that section lies from the row, and how many of HOOKED_FIN's edges on
    the cut stay open."""
    cut = fin_cut(p)
    body = body_field(p, cut)
    outside = lambda v: body(v.x, v.z) > SEAM
    on_cut = lambda v: abs(v.co.y + S0 - cut) < 1e-4
    fin = bpy.data.objects["ventral_fin"]
    bm = bmesh.new()
    bm.from_mesh(fin.data)
    bm.transform(fin.matrix_world)
    res = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=W(cut, 0, 0),
                                 plane_no=Vector((0, 1, 0)))
    section = [[v.co.copy() for v in e.verts] for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    corners = [v.co.copy() for v in res["geom_cut"] if isinstance(v, bmesh.types.BMVert) and outside(v.co)]
    bm.free()
    hooked = bpy.data.objects[HOOKED_FIN]
    bm = bmesh.new()
    bm.from_mesh(hooked.data)
    bm.transform(hooked.matrix_world)
    first = [v.co.copy() for v in bm.verts if on_cut(v) and outside(v.co)
             and any(f.calc_center_median().y + S0 > cut for f in v.link_faces)]
    open_edges = sum(1 for e in bm.edges if e.is_boundary and all(on_cut(v) for v in e.verts)
                     and outside((e.verts[0].co + e.verts[1].co) / 2))
    bm.free()
    if not first or not corners:
        return math.inf, math.inf, open_edges
    off = max(min(segment_distance(v, a, b) for a, b in section) for v in first)
    missed = max(min((v - c).length for v in first) for c in corners)
    return off, missed, open_edges


def check(icarus):
    """Swing the hook stowed to deployed: it keeps CLEAR from the fin and fairing ahead of the slot, the engine and
    nozzle, and the well and skin, and its line from hinge to point (the game's catch linecast) keeps CLEAR from
    every collider hull and never crosses one. Its length is the Compass's; it hangs from the tail cone. The fairing
    starts on the kept fin's own section, welded to it (seam_fit)."""
    import budget
    import checks

    problems = budget.over_caps(icarus, BUDGET)
    O = bpy.data.objects
    obj = O.get(NAME)
    if obj is None or COLLECTION not in [c.name for c in obj.users_collection]:
        raise ValueError("tail hook: no %s in the %s collection" % (NAME, COLLECTION))
    from parts import LATE_PARENTS, TREE

    # the tail cone in a split build; until the split (the skin bake's whole build), its tree parent
    for name in ("ventral_fin", HOOKED_FIN):
        if O[name].parent is None or O[name].parent.name not in (LATE_PARENTS[name], TREE[name][0]):
            problems.append("%s hangs on %s, not the tail cone" % (name, O[name].parent))
    p = bi.PARAMS
    le_root, _, c_root, _, _, _ = fin_sections(p)
    aft = max((O["ventral_fin"].matrix_world @ v.co).y + S0 for v in O["ventral_fin"].data.vertices)
    if abs(aft - (le_root + c_root)) > 0.005:
        problems.append("the original fin ends at s %.3f, not its trailing edge %.3f" % (aft, le_root + c_root))
    # the belly's loft stays whole under the fairing, so the well's floor must stay below it, at least as far as the
    # patch stands over it (it meets the belly at the slot's aft end, where the cap closes the well)
    _contours.clear()
    belly = min(float(at_x(contour(p, s, fairing=False), 0.0, 1)[0][1]) - z for s, z in obj["well_floor"])
    if belly < PATCH_OUT:
        problems.append("the well's floor comes within %.4f m of the original belly" % belly)
    seam = seam_fit(p)
    if max(seam[:2]) > SEAM or seam[2]:
        problems.append("the fairing's first row stands %.4f m off the kept fin's end section, %.4f m from its corners, "
                        "with %d edges open on the cut (needs %.3f, none open)" % (*seam, SEAM))
    hinge = obj.matrix_world.translation.copy()
    length = (hook_point(obj) - hinge).length
    if abs(length - LENGTH) > 0.001:
        problems.append("hinge to point %.4f m, not the Compass's %.3f" % (length, LENGTH))
    fin = O[HOOKED_FIN]
    s_f = obj["slot_front_s"]
    fin_ahead = checks.tree(fin)
    fin_ahead_faces = [(fin.matrix_world @ f.center).y + S0 < s_f - 0.003 for f in fin.data.polygons]
    bm = bmesh.new()
    bm.from_mesh(fin.data)
    bm.transform(fin.matrix_world)
    bmesh.ops.delete(bm, geom=[f for f, keep in zip(bm.faces, fin_ahead_faces) if not keep], context="FACES")
    from mathutils.bvhtree import BVHTree
    fin_ahead = BVHTree.FromBMesh(bm)
    bm.free()
    trees = {"fin_ahead_of_slot": fin_ahead,
             "afterburner_nozzle": checks.tree([o for o in icarus.all_objects if o.type == "MESH"
                                                 and o.name.startswith(("engine_afterburner", "nozzle"))]),
             "well_and_skin": checks.tree([fin] + [o for o in icarus.all_objects if o.type == "MESH"
                                                   and o.name.startswith("skin_aft_rear_")])}
    # the jet's colliders with the hook fitted: the airframe's and the mount's
    colliders = [o for o in bpy.data.collections["Colliders"].objects if o.type == "MESH"] + hull_objects()
    if not hull_objects():
        problems.append("no %s hulls in %s" % (HOOKED_FIN, HULLS))
    hulls = checks.tree(colliders)
    swing = obj["stowed_deg"] - obj["deployed_deg"]
    least = {k: math.inf for k in list(trees) + ["line_to_hulls"]}
    crossings = []
    for i in range(SWEEP_STEPS + 1):
        pose_hook(obj, swing * i / SWEEP_STEPS)
        pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
        for k, tree in trees.items():
            least[k] = min(least[k], min(tree.find_nearest(v)[3] for v in pts))
        gap, hit = segment_gap(hulls, hinge, hook_point(obj))
        least["line_to_hulls"] = min(least["line_to_hulls"], gap)
        if hit:
            crossings.append(round(swing * i / SWEEP_STEPS, 1))
    pose_hook(obj, 0.0)
    for k, limit in CLEAR.items():
        if least[k] < limit:
            problems.append("%s %.4f m from the hook (needs %.3f)" % (k, least[k], limit))
    if crossings:
        problems.append("the catch line crosses a collider hull at swing %s deg" % crossings)
    # attitudes: the point's reach below the deck and the airframe's least height, at the AI's landing attitude
    contact = obj["main_contact_s_z"]
    pose_hook(obj, swing)
    reach = {theta: round(-hook_low(obj, theta), 3) for theta in (0.0, AOA)}
    pose_hook(obj, 0.0)
    strike = min(math.degrees(math.atan2(v.z - contact[1], v.y + S0 - contact[0]))
                 for o in icarus.all_objects if o.type == "MESH" and not o.name.startswith("gear_")
                 for v in [o.matrix_world @ w.co for w in o.data.vertices] if v.y + S0 > contact[0] + 0.05)
    if problems:
        raise ValueError("tail hook check: " + "; ".join(problems))
    print("tail hook check PASS: %d triangles, hinge s %.3f z %.3f, length %.4f m, local X %.2f stowed / %.2f deployed "
          "(swing %.2f deg); least: %s; deployed point %.3f m past the deck level, %.3f m at %.1f deg; tail strike %.2f deg; "
          "seam %.5f m off the fin's section, %.5f m from its corners"
          % (budget.tris(obj), obj["hinge_s_z"][0], obj["hinge_s_z"][1], length, obj["stowed_deg"], obj["deployed_deg"], swing,
             ", ".join("%s %.4f" % kv for kv in least.items()), reach[0.0], reach[AOA], AOA, strike, *seam[:2]))


def export(to_unity, icarus):
    """The hook for blockout.json: its key, the part it hangs on, its hinge (world, Unity axes), TailHook's angles, the
    fin it shows and HOOKED_FIN's hulls. Its mesh is in the hook transform's frame, which the mount turns 180 degrees
    about X at the hinge; the hulls, moved here into the part's frame, go on the part as its own colliders."""
    from parts import LATE_PARENTS

    obj = bpy.data.objects[NAME]
    part = LATE_PARENTS["ventral_fin"]
    to_part = bpy.data.objects[part].matrix_world.inverted()
    for hull in hull_objects():
        hull.data.transform(to_part @ hull.matrix_world)
        hull.matrix_world = Matrix.Identity(4)
    return {"key": KEY, "part": part, "hinge_unity": to_unity(obj.matrix_world.translation),
            "length": LENGTH, "stowed_deg": round(obj["stowed_deg"], 3), "deployed_deg": round(obj["deployed_deg"], 3),
            "fin": "ventral_fin", "hooked_fin": HOOKED_FIN, "hulls": [hull.name for hull in hull_objects()]}
