"""The arrestor hook and the fairing it stows in, for carrier landings on the Hyperion.

The hook is the stock Compass's (TailHook_Trainer): 1.953 m from hinge to point, turned on its local X by the game's
TailHook between a stowed and a deployed angle, and caught by a wire when the line from its hinge to its point crosses
one (TailHook.FixedUpdate's Physics.Linecast). It is a store on its own Tail Hook hardpoint set, not part geometry: this
module builds its arm, shoe and trunnion in its own collection (as tip_tanks.py keeps the tank in Stores), its mesh in the hook transform's frame (export), and
IcarusAuthor.TailHook.cs clones the Compass mount around it.

It stows flush in a fairing grown from the ventral fin, the owner's pick of four designs (variant D, 2026-10-29): the
fin keeps its forward half; from its thickest line (FIN_CUT, chord fraction 0.5 at root and tip, where its web is as
thick as it gets) its web runs on aft to the nozzle, and its lower edge widens into a pod POD wide that hangs up to
0.26 m below the tail cone. The hook lies in a slot in the pod's bottom on a straight line (LINE) with its hinge at
HINGE_S, behind the kept fin, so it never swings toward it, and its point under the nozzle. The fairing is a skin patch
(the generator's own smooth-union fields: the body's, the web's and the pod's) joined into the ventral fin's mesh, so it
rides the tail cone with the fin (parts.LATE_PARENTS), takes the fin's livery and adds no renderer; the loft's faces it
covers are deleted, and the slot's well is dark like the gear wells. The fin gets collider hulls on the tail cone
(hulls.fin_hulls), kept off the hook's line from hinge to point in every pose (check): the linecast has no layer mask,
and a hit on the jet's own collider backs the hook off as it would a deck.

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
PATCH_OUT = 0.0006  # the patch stands this far outside the true surface, over the old skin's facets
ROW_STEP = 0.10  # metres between the patch's rows; the hook's are finer at its point
COLUMNS = (14, 7, 14)  # points across the patch left of the slot, across it, and right of it
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
    """The ventral fin's half thickness at its thickest line, at height z."""
    _, z_root, c_root, _, z_tip, c_tip = fin_sections(p)
    f = min(1.0, max(0.0, (z - z_tip) / (z_root - z_tip)))
    return p["ventral_fin"]["thickness"] * (c_tip + (c_root - c_tip) * f) * bi.airfoil(0.5)


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


def row(p, s, w):
    """The outline at s split at x = -w and w: (left, slot, right) resampled to COLUMNS, the slot's ends shared."""
    c = contour(p, s)
    (pl, kl), (pr, kr) = at_x(c, -w, -1), at_x(c, w, 1)
    left = np.vstack([c[:kl], pl])
    mid = np.vstack([pl, c[kl:kr + 1], pr])
    right = np.vstack([pr, c[kr + 1:]])
    return resample(left, COLUMNS[0]), resample(mid, COLUMNS[1]), resample(right, COLUMNS[2])


def offset(pts, d):
    t = np.gradient(pts, axis=0)
    t /= np.linalg.norm(t, axis=1)[:, None]
    return pts + np.column_stack([t[:, 1], -t[:, 0]]) * d


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
    """The fairing patch with its slot and well, tagged to join the ventral fin (parts.merge_details)."""
    rows = patch_rows(hook)
    verts, faces, skin_faces, grid, slot_cols, well_rows = [], [], [], [], None, []
    for s in rows:
        w = hook.width(s) + GAP
        if not hook.in_slot(s):  # split inside the web, which is narrower than the slot ahead of the pod
            w = min(w, 0.6 * fin_web_half(p, fin_sections(p)[4]))
        left, mid, right = row(p, s, w)
        out = offset(np.vstack([left, mid[1:-1], right]), PATCH_OUT)
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
    xs = np.linspace(-w, w, COLUMNS[1])
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
    skin_faces.append((edge_l, floor_l, upper[0], lifted[slot_cols[0]]))
    skin_faces.append((floor_r, edge_r, lifted[slot_cols[1]], upper[-1]))
    obj = bi.mesh_object(FAIRING, verts, skin_faces + well_faces)
    obj.data.materials.append(mats["body"])
    obj.data.materials.append(mats["gear_bay"])
    for poly in obj.data.polygons:
        poly.material_index = 1 if poly.index >= len(skin_faces) else 0
        poly.use_smooth = poly.material_index == 0
    orient(obj, p, hook, z_floor)
    obj["merge_into"] = "ventral_fin"
    return obj, z_floor


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


def cut_fin():
    """Today's fin keeps its forward half; the fairing's web runs on from the cut."""
    ob = bpy.data.objects["ventral_fin"]
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    mwi = ob.matrix_world.inverted()
    cut = fin_cut(bi.PARAMS)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=mwi @ W(cut, 0, 0),
                           plane_no=(mwi.to_3x3() @ Vector((0, 1, 0))).normalized(), clear_outer=True)
    bm.to_mesh(ob.data)
    bm.free()


def clear_loft(p, hook, z_floor):
    """Delete the loft's faces the fairing covers, and those inside the slot that the well's floor would not hide."""
    ob = bpy.data.objects["fuselage"]
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    mw = ob.matrix_world
    kill = []
    for f in bm.faces:
        c = mw @ f.calc_center_median()
        s = c.y + S0
        vs = [mw @ v.co for v in f.verts]
        if all(hook.cut <= v.y + S0 <= hook.s_t and abs(v.x) < x_edge(p, v.y + S0) for v in vs) and c.z < 0.3:
            kill.append(f)
        elif hook.s_f - 0.02 <= s <= hook.s_t + 0.01 and abs(c.x) < hook.width(min(max(s, hook.s_f), hook.s_t)) + GAP + 0.025:
            if c.z < z_floor[min(z_floor, key=lambda r: abs(r - s))] + 0.005:
                kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return len(kill)


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
    """The fairing, the fin's cut, the loft's faces under it, and the hook in its collection, posed stowed."""
    _contours.clear()
    hook = Hook(p)
    fairing, z_floor = build_fairing(p, mats, hook)
    cut_fin()
    cleared = clear_loft(p, hook, z_floor)
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
    bi.finish(obj, mats["strut"], smooth=False)
    layer = me.uv_layers.new(name="UVMap")  # a flat bare-metal slot, but Unity builds tangents from UVs
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        layer.data[loop.index].uv = (co.y + co.x, co.z + co.x)
    obj["stowed_deg"] = stowed
    obj["hinge_s_z"] = [hook.s_h, hook.z_h]
    obj["point_s_z"] = [hook.s_t, hook.z_t]
    obj["slot_front_s"] = hook.s_f
    obj["fin_cut_s"] = hook.cut
    obj["loft_faces_cleared"] = cleared
    obj["well_floor"] = [[s, z] for s, z in sorted(z_floor.items())]
    obj["main_contact_s_z"] = list(main_contact())
    pose_hook(obj, 0.0)
    obj["deployed_deg"] = stowed - deployed_swing(obj)
    return fairing, obj


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
    """The ventral fin's collider hulls, on the tail cone it rides (parts.LATE_PARENTS): the kept fin, the pod ahead of
    the slot, and the pod above the well's floor in two lengths, each clipped FIN_HULL_INSIDE inside the body's skin.
    None reaches the slot, so the hook's line from hinge to point meets none in any pose (check). Runs after
    hulls.rebuild_pieces, which carves the tail cone's shells afresh; returns how many."""
    import hulls
    from parts import LATE_PARENTS

    p, obj, fin = bi.PARAMS, bpy.data.objects[NAME], bpy.data.objects["ventral_fin"]
    cut, s_f = obj["fin_cut_s"], obj["slot_front_s"]
    floor = np.array(obj["well_floor"])
    host = bpy.data.objects[LATE_PARENTS["ventral_fin"]]
    _contours.clear()

    def inside(v):
        s = v.y + S0
        top = float(at_x(contour(p, min(max(s, cut), floor[-1, 0]), fairing=False), 0.0, 1)[0][1]) + FIN_HULL_INSIDE
        return Vector((v.x, v.y, min(v.z, top)))

    pts = [fin.matrix_world @ v.co for v in fin.data.vertices]
    above = lambda v: v.z > np.interp(v.y + S0, floor[:, 0], floor[:, 1]) + FIN_HULL_INSIDE
    mid = (s_f + floor[-1, 0]) / 2
    groups = [[v for v in pts if v.y + S0 < cut + 0.002],
              [v for v in pts if cut - 0.002 < v.y + S0 < s_f - 0.005],
              [v for v in pts if s_f - 0.005 <= v.y + S0 < mid + 0.05 and above(v)],
              [v for v in pts if mid - 0.05 <= v.y + S0 and above(v)]]
    shapes = []
    for group in groups:
        if len(group) < 8:
            continue
        bm = hulls.capped([inside(v) for v in group], FIN_HULL_TRIS)
        if hulls.solid(bm):
            shapes.append(bm)
        else:
            bm.free()
    return hulls.attach_colliders(host, shapes, bpy.data.collections["Colliders"])


def segment_gap(tree, a, b, steps=40):
    """Least distance from the segment a-b to a BVH tree, and whether a ray along it hits the tree."""
    d = b - a
    hit = tree.ray_cast(a, d.normalized(), d.length)[0] is not None
    least = min(tree.find_nearest(a.lerp(b, i / steps))[3] for i in range(steps + 1))
    return least, hit


def check(icarus):
    """Swing the hook stowed to deployed: it keeps CLEAR from the fin and fairing ahead of the slot, the engine and
    nozzle, and the well and skin, and its line from hinge to point (the game's catch linecast) keeps CLEAR from
    every collider hull and never crosses one. Its length is the Compass's; it hangs from the tail cone."""
    import budget
    import checks

    problems = budget.over_caps(icarus, BUDGET)
    O = bpy.data.objects
    obj = O.get(NAME)
    if obj is None or COLLECTION not in [c.name for c in obj.users_collection]:
        raise ValueError("tail hook: no %s in the %s collection" % (NAME, COLLECTION))
    from parts import LATE_PARENTS, TREE

    # the tail cone in a split build; until the split (the skin bake's whole build), its tree parent
    if O["ventral_fin"].parent is None or O["ventral_fin"].parent.name not in (LATE_PARENTS["ventral_fin"], TREE["ventral_fin"][0]):
        problems.append("the ventral fin hangs on %s, not the tail cone" % O["ventral_fin"].parent)
    hinge = obj.matrix_world.translation.copy()
    length = (hook_point(obj) - hinge).length
    if abs(length - LENGTH) > 0.001:
        problems.append("hinge to point %.4f m, not the Compass's %.3f" % (length, LENGTH))
    fin = O["ventral_fin"]
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
    colliders = [o for o in bpy.data.collections["Colliders"].objects if o.type == "MESH"]
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
          "(swing %.2f deg); least: %s; deployed point %.3f m past the deck level, %.3f m at %.1f deg; tail strike %.2f deg"
          % (budget.tris(obj), obj["hinge_s_z"][0], obj["hinge_s_z"][1], length, obj["stowed_deg"], obj["deployed_deg"], swing,
             ", ".join("%s %.4f" % kv for kv in least.items()), reach[0.0], reach[AOA], AOA, strike))


def export(to_unity, icarus):
    """The hook for blockout.json: its key, the part it hangs on, its hinge (world, Unity axes) and TailHook's angles.
    Its mesh is in the hook transform's frame, which the mount turns 180 degrees about X at the hinge."""
    obj = bpy.data.objects[NAME]
    return {"key": KEY, "part": "fuselage_tail", "hinge_unity": to_unity(obj.matrix_world.translation),
            "length": LENGTH, "stowed_deg": round(obj["stowed_deg"], 3), "deployed_deg": round(obj["deployed_deg"], 3)}
