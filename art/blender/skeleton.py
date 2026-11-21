"""The airframe's skeleton: frames, longerons, stringers, shelves, ribs, spars and the inner faces of the moving
surfaces, built coarse the way the stock jets build theirs.

A stock jet carries its structure on each part's own mesh, as material slots after the skin: frames, longerons, ribs
and spars on jet_mechanical, honeycomb on the inside of thin surfaces (the Revoker's and the Ifrit's prefabs: the
Revoker's fuselage part 378 skin and 2,482 jet_mechanical triangles, its wing1a 205 and 749, the Ifrit's aileron 288
skin and 88 honeycomb). Nothing inside is a part, joint or collider of its own. Here each piece is a mesh of its own,
tagged skeleton_owner with the part whose mesh it joins; role "visual" keeps it out of the colliders and LOD1 hulls
(hulls.SKIP_ROLES), and parent_part hangs it on that part (parts.organise), or on a surface's hinge.

The Revoker's members are deep flat strips: frames as arcs and posts that end on longerons, four or five stringers down
each side between them, equipment trays under the spine, and in the wings and fin a lattice of ribs about 0.25 m
apart across three spars. The skeleton follows that. Frames are box-section strips on a coarse copy of the skin's own
section (skin_ring, simplified to within FRAME tolerance), not smooth rings; where the Y-duct comes close to the skin
a frame runs shallower over it instead of being cut, and where a gear well opens to the skin it ends on the well's
wall. Each plane where a section breaks off gets a closing frame, deeper than the rest, so a broken section shows a
ring of structure rather than an open tube; ribs close the wing boxes and the fin.
"""
import fnmatch
import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import build_icarus as bi
import internals as interior

# Frames: how far the frame's outer face stays inside the skin, how far its coarse outline may stray from the skin's
# own section (so its chords cut no concave fillet: tolerance < inset), its depth into the body and its width along it.
FRAME = {"inset": 0.024, "tolerance": 0.02, "depth": 0.05, "flange": 0.03}
# A closing frame at a break plane, deeper than a frame so the broken face reads as a ring of structure; the root's
# front one deeper still, a bulkhead with a large lightening hole as the Revoker's forward bulkhead is.
CLOSING = {"depth": 0.10, "flange": 0.04}
BULKHEAD = {"depth": 0.15, "flange": 0.04}
# A frame over something close under the skin (the Y-duct, the engine) runs no deeper than the gap less this, and no
# shallower than min_depth; where even that will not fit, the cut ends it on what it meets.
CLEARANCE = {"gap": 0.006, "min_depth": 0.02}
LONGERON = {"width": 0.035, "depth": 0.03}
STRINGER = {"width": 0.024, "depth": 0.02}
# A sliver or a loose shard is no structure: no skeleton triangle narrower than this, no loose piece smaller across.
# A cut drops what it leaves smaller than drop_piece (a frame stub that short reads as debris).
SANE = {"min_altitude": 0.001, "min_piece": 0.08, "drop_piece": 0.15}
# The root section, fuselage_mid (parts.FORWARD_END to MID_END) with the dorsal truss over it (parts.TRUSS_BREAK). Its
# frames stand on the 0.6 m frame stations the panel lines are drawn on (internals.INTERNALS["frames"]), less 5.8,
# which the front closing frame stands in for; the closing frames stand just inside its two break planes and either
# side of the truss's. Longerons at these angles round the section's centre (degrees from the left side, +x): the
# upper pair on the truss's 45 degree edges (parts.shell_points), one down the spine, which is the truss's, and a
# chine pair along the fairings' undersides below the wing roots, which the lower frames end on where the wing roots
# and the gear wells stop them. Stringers between them at these angles, four over the top and two under each fairing
# and the keel, none along the fairings' outer sides, where a line from the centre runs out along the wing fillet.
ROOT = {"frames": (6.4, 7.0, 7.6, 8.8, 9.4, 10.0, 10.6), "closing": (5.63, 10.97), "truss_frame": 8.2,
        "longerons": {"upper": (45.0, 135.0), "spine": (90.0,), "chine": (-18.0, -162.0)},
        "stringers": (22.5, 67.5, 112.5, 157.5, -35.0, -145.0, -78.0, -102.0),
        # The truss's rear half runs on over the aft section under its dorsal cover (parts.DORSAL, to s 12.4): frame
        # arcs under that strip, and a closing arc at its end.
        "dorsal_frames": (11.6, 12.2), "dorsal_end": 12.37,
        # An equipment shelf under the spine in each bay from the intake lip aft, as the Revoker's trays under its
        # spine: at this height, clear above the Y-duct and the engine's face, its edges this far inside the skin, with
        # two boxes of avionics on it (s length, x width, z height).
        "shelf": {"z": 0.86, "edge": 0.07, "thickness": 0.012, "box": (0.22, 0.18, 0.11)}}
# The fuselage's other sections, on the same 0.6 m frame stations as the root (radome frames between them), each with
# a closing frame just inside every plane it breaks off at (parts.RADOME_END 1.6, FORWARD_END 5.6, MID_END 11.0,
# TAIL_START 13.0). Over the cockpit the forward section's frames stop under the cockpit opening (opening_floor, less
# sill_gap) and end on the cockpit cell's sill longerons; the cell's two bulkhead frames stand just outside the
# tub's ends (internals.INTERNALS cockpit_tub, which moves with the crew station). The aft section's frames leave the
# dorsal cover's strip to the truss; the tail cone's closing frame stops at the speed brakes' wells.
FORE = {"radome": (0.75, 1.20), "radome_end": 1.57, "frames": (2.2, 2.8, 3.4, 4.0, 4.6, 5.2), "closing": (1.63, 5.57),
        "sill_gap": 0.03, "tub_gap": 0.04,
        "stringers": (30.0, 150.0, -20.0, -160.0, -60.0, -120.0), "radome_stringers": (45.0, 135.0, -45.0, -135.0)}
AFT = {"frames": (11.6, 12.2, 12.6), "closing": (11.03, 12.97), "tail_frames": (13.66, 14.2, 14.8),
       "tail_closing": 13.03, "brake_deg": (-50.0, 2.0)}
# The engine: its compressor face (a hub and blades behind the Y-duct's backplate), flanged casings for the core and
# the afterburner section, sides round, on internals.INTERNALS engine's line. Coarse, as the Revoker's engine face is
# its only engine detail.
ENGINE = {"sides": 16, "blades": 12, "hub": 0.12, "flanges": (9.80, 10.9, 12.0, 13.10), "ab_flanges": (14.0, 14.9),
          "flange": (0.03, 0.025)}
# Each intake: frames round its duct branch, ahead of where the branches merge (PARAMS duct, before s 8.23), clear of
# the duct by gap; they ride the intake's duct, which a split build leaves on the root (parts.split_intakes). The first
# and last stand closing_depth deep, the intake's closing frames where it breaks from the body: behind the lip and
# ahead of the merge.
INTAKE = {"frames": (7.15, 7.6, 8.05), "points": 12, "gap": 0.008, "depth": 0.022, "closing_depth": 0.035}
# The ventral fin as the fin, smaller: spars, ribs, a leading-edge member, cut to the belly. The hooked variant's
# web: a keel bar along the hook pod's line (tail_hook.zline) and posts up to the belly.
VENTRAL = {"front": 0.25, "mid": 0.50, "rear": 0.78, "ribs": (-0.58, -0.50), "le": 0.04, "te": 0.94,
           "hooked_posts": (13.45, 13.95, 14.45, 14.90), "hooked_keel": (13.15, 15.0), "hooked_lift": 0.05}
# Rib thickness along the span, spar thickness along the chord; ribs and spars fill this share of the skin's depth.
RIB = {"thickness": 0.012, "depth": 0.80}
SPAR = {"thickness": 0.014}
# The left wing (inner box to bi.WING_CRANK, outer box to the tip): front, middle and rear spars, the front behind the
# leading-edge flap's hinge (0.154), the rear ahead of the aileron's (0.746); ribs about 0.18 m apart, a little closer
# than the Revoker's 0.25 m since the Icarus's wing is a third as deep, each in pieces between the spars, the first on
# the body's side and the crank's and tip's as closing ribs; a leading-edge member the inner box's rib noses end on (the
# outer box's leading edge is the leading-edge flap, hinged on its front spar); and a stringer under each skin. The
# wing is 3.4% thick, so ribs run from 4% of the chord (the nose is a few millimetres deep ahead of that), to 94%
# inboard of the flap, and across the flap stop at the rear spar, the crank rib at flap_te, clear of the flap's cove.
WING = {"front": 0.175, "mid": 0.45, "rear": 0.70,
        "inner_ribs": (1.15, 1.32, 1.49, 1.66, 1.82), "outer_ribs": (2.15, 2.35, 2.55, 2.75, 2.95, 3.15),
        "crank": bi.WING_CRANK, "crank_gap": 0.02, "tip": 3.37, "le": 0.04, "inner_te": 0.94, "flap_te": 0.72,
        "box": (0.19, 0.72), "stringers": (0.40,)}
# The fin: front, middle and rear spars ahead of the rudder's cove (hinge 0.718), ribs about 0.2 m apart up to a
# closing rib under where the fin-tip fairing's fillets run down inside the fin (build_icarus FAIRING_FOOT), a closing
# rib along the body's top line, and a stringer under each skin between the front and middle spars (the Revoker's
# vstab has rib caps and spars and few stringers).
FIN = {"front": 0.20, "mid": 0.42, "rear": 0.64, "ribs": (1.20, 1.40, 1.60, 1.80, 2.00, 2.20, 2.40), "tip": 2.57,
       "le": 0.04, "te": 0.94,
       # Inside the fin-tip fairing, above the fairing's floor across the fin (2.60 to 2.65) and under the fin's top
       # (2.82): a box carrying the stabilator's hinge, two ribs from behind the fairing's round nose (0.35 m long,
       # down into the fin's leading edge) aft, joined by webs on the middle and rear spars' lines and one under the
       # pivot. The fin's stringers went to pay for it: its ribs, three spars and leading-edge member hold the skin.
       "top_box": (2.68, 2.80), "top_chord": (0.30, 0.92)}
# The T-tail's junction inside the fin-tip fairing (build_icarus.fairing_ring), a load path from the stabilator into the
# fin: frames round the fairing at these stations, over the top and down its walls to the hinge box's height (below
# that the walls turn in toward the fin), the one at the stabilator's pivot deeper; a longeron down each wall at
# wall_z tying the frames together; a hinge beam across the fairing on the fin's top, between the two longerons and
# over the fin's hinge box, at the pivot (its length along the body, its height); and a pivot stub each side under the
# beam's ends, from beside the fin out to the fairing's wall.
JUNCTION = {"frames": (14.80, 15.95), "pivot_frame_depth": 0.03, "depth": 0.018, "inset": 0.006,
            "above": 2.70, "wall_z": 2.86, "beam": (0.30, 0.08), "stub": (0.040, 0.085, 0.035)}
# The stabilator, each half: a leading-edge member and front, middle and rear spars, ribs about 0.38 m apart in pieces
# between them (the Ifrit's elevator, a little larger, carries 431 jet_mechanical and 101 honeycomb triangles a side), a
# closing rib just outboard of its root wall beside the fairing and one at its tip. It is 4.5% thick, so its ribs run
# 4% to 94% of the chord.
STABILATOR = {"front": 0.15, "mid": 0.45, "rear": 0.80, "ribs": (0.45, 0.83, 1.21, 1.55), "root": 0.115,
              "tip": 1.79, "le": 0.04, "te": 0.94}
# A moving surface's inner face: a closed shell this share of the surface's depth, its faces turned in, on honeycomb
# as the stock surfaces are, from just behind its hinge (a leading-edge flap: just ahead of it).
SURFACE = {"depth": 0.75, "hinge_clear": 0.02, "edge": 0.97}

# Triangles per place: target and cap (parts.BUDGET merges these), out of about 18,000 for the whole jet. The stock
# comparison per part: the Revoker's fuselage 2,482 internal triangles, its wing (wing1b, wing1a, wing2, wingtip) 2,321
# a side, vstab1 and vstab2 824, flap 136, aileron 144, rudder 124.
BUDGET = {
    # the root and both truss halves, the rear one's run over the aft section under its dorsal cover included
    "skeleton_root": {"target": 4000, "cap": 4400, "objects": ("skel_fuselage_mid", "skel_fuselage_truss_")},
    "skeleton_wing_L": {"target": 1450, "cap": 1600, "objects": ("skel_wing_spar_L", "skel_wing_spar_outer_L")},
    "skeleton_wing_surfaces_L": {"target": 230, "cap": 260, "objects": ("skel_lef_L", "skel_flap_L", "skel_aileron_L")},
    # the fin and rudder, the T-tail junction in the fin-tip fairing (the fin skin's) and the stabilator
    "skeleton_tail": {"target": 2760, "cap": 2800,
                      "objects": ("skel_fin_spar", "skel_rudder", "skel_fin_skin", "skel_stabilator")},
    "skeleton_wing_R": {"target": 1450, "cap": 1600, "objects": ("skel_wing_spar_R", "skel_wing_spar_outer_R")},
    "skeleton_wing_surfaces_R": {"target": 230, "cap": 260, "objects": ("skel_lef_R", "skel_flap_R", "skel_aileron_R")},
    "skeleton_nose": {"target": 2400, "cap": 2700, "objects": ("skel_radome", "skel_fuselage_forward", "skel_cockpit_cell")},
    "skeleton_aft": {"target": 2650, "cap": 2950, "objects": ("skel_fuselage_aft", "skel_fuselage_tail")},
    "skeleton_engine": {"target": 1300, "cap": 1450, "objects": ("skel_engine_",)},
    "skeleton_intakes": {"target": 800, "cap": 900, "objects": ("skel_intake_duct_",)},
    "skeleton_ventral": {"target": 300, "cap": 400, "objects": ("skel_ventral_fin",)},
}


def tris(obj):
    return sum(len(f.vertices) - 2 for f in obj.data.polygons)


# --- section outlines ----------------------------------------------------------------------------------------------

def signed_area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def offset(pts, by, closed=True):
    """The (x, z) polygon moved by `by` (one distance, or one per point) to its inside along each corner's mitred
    normal (the miter capped at twice the distance). pts run anticlockwise."""
    n = len(pts)
    out = []
    for i in range(n):
        # the nearest distinct neighbours, so repeated points share their corner's normal
        j = next((k for k in range(1, n) if (Vector(pts[(i - k) % n]) - Vector(pts[i])).length > 1e-7), 1)
        m_ = next((k for k in range(1, n) if (Vector(pts[(i + k) % n]) - Vector(pts[i])).length > 1e-7), 1)
        prev = pts[(i - j) % n] if closed or i - j >= 0 else None
        nxt = pts[(i + m_) % n] if closed or i + m_ < n else None
        normals = []
        for a, b in ((prev, pts[i]), (pts[i], nxt)):
            if a is None or b is None:
                continue
            d = Vector((b[0] - a[0], b[1] - a[1]))
            if d.length > 1e-9:
                normals.append(Vector((-d.y, d.x)).normalized())  # left of an anticlockwise edge is inside
        m = sum(normals, Vector((0.0, 0.0))).normalized()
        k = min(2.0, 1.0 / max(m.dot(normals[0]), 0.5))
        b = by[i] if isinstance(by, (list, tuple)) else by
        out.append((pts[i][0] + m.x * b * k, pts[i][1] + m.y * b * k))
    return out


def simplify(polygons, tolerance):
    """Douglas-Peucker on closed polygons with the same columns (one section at several stations): the indices of the
    fewest columns whose chords stay within tolerance of every polygon."""
    pts = polygons[0]

    def dp(idx):
        far, at = 0.0, 0
        for poly in polygons:
            a, b = Vector(poly[idx[0] % len(pts)]), Vector(poly[idx[-1] % len(pts)])
            ab = b - a
            for k in range(1, len(idx) - 1):
                q = Vector(poly[idx[k] % len(pts)])
                t = max(0.0, min(1.0, (q - a).dot(ab) / ab.length_squared)) if ab.length_squared else 0.0
                d = (q - (a + ab * t)).length
                if d > far:
                    far, at = d, k
        if far <= tolerance:
            return [idx[0], idx[-1]]
        return dp(idx[:at + 1])[:-1] + dp(idx[at:])
    n = len(pts)
    i1 = max(range(n), key=lambda i: (Vector(pts[i]) - Vector(pts[0])).length)
    return dp(list(range(0, i1 + 1)))[:-1] + [i % n for i in dp(list(range(i1, n + 1)))[:-1]]


def ring2d(p, s, flip):
    """The skin's own section at s (bi.skin_ring) as (x, z) points, reversed when flip, so every station's runs the
    same way round and keeps its column numbers."""
    pts = [(v.x, v.z) for v in bi.skin_ring(p, s)]
    return pts[::-1] if flip else pts


class Section:
    """A frame's outline: the skin's section at s, inset, through the columns a simplification of it keeps. at(s')
    gives the same columns at another station, so a frame's two faces each follow the skin where they stand."""

    def __init__(self, p, s, flange=0.0, inset=FRAME["inset"], tolerance=FRAME["tolerance"]):
        self.p, self.inset = p, inset
        self.flip = signed_area(ring2d(p, s, False)) < 0
        self.columns = simplify([self.full(s + d) for d in (0.0, -flange / 2, flange / 2)], tolerance)
        self.pts = self.at(s)

    def full(self, s):
        return offset(ring2d(self.p, s, self.flip), self.inset)

    def at(self, s):
        full = self.full(s)
        return [full[i] for i in self.columns]


def section(p, s, inset=FRAME["inset"], tolerance=FRAME["tolerance"]):
    """The skin's own section at s, inset and simplified, as anticlockwise (x, z) points."""
    return Section(p, s, 0.0, inset, tolerance).pts


def ray_point(pts, centre, angle):
    """Where a ray from centre at angle (radians, from +x) leaves the polygon."""
    d = Vector((math.cos(angle), math.sin(angle)))
    c = Vector(centre)
    best = None
    for a, b in zip(pts, pts[1:] + pts[:1]):
        a, b = Vector(a), Vector(b)
        e = b - a
        den = d.x * e.y - d.y * e.x
        if abs(den) < 1e-12:
            continue
        t = ((a.x - c.x) * e.y - (a.y - c.y) * e.x) / den
        u = ((a.x - c.x) * d.y - (a.y - c.y) * d.x) / den
        if t > 0 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t > best):
            best = t
    return tuple(c + d * best)


def arcs(pts, inside):
    """Split a closed polygon into the open runs where inside(q) holds, anticlockwise, each ended on the crossing
    (found by bisection). A run is a list of (i, j, t): the point t of the way from pts[i] to pts[j], so it can be
    read off the same columns at another station (lerp_run)."""
    flags = [inside(q) for q in pts]
    n = len(pts)
    if all(flags):
        return [[(i, i, 0.0) for i in range(n)]]  # the whole ring: a closed run (is_closed)
    if not any(flags):
        return []
    start = next(i for i in range(n) if not flags[i - 1] and flags[i])

    def crossing(i, j):  # pts[i] outside, pts[j] inside
        lo, hi = 0.0, 1.0
        a, b = Vector(pts[i]), Vector(pts[j])
        for _ in range(30):
            mid = (lo + hi) / 2
            if inside(tuple(a.lerp(b, mid))):
                hi = mid
            else:
                lo = mid
        return (i, j, (lo + hi) / 2)
    out, run = [], None
    for k in range(n):
        i = (start + k) % n
        h = (i - 1) % n
        if flags[i] and not flags[h]:
            run = [crossing(h, i), (i, i, 0.0)]
        elif flags[i]:
            run.append((i, i, 0.0))
        elif flags[h]:
            run.append(crossing(i, h))
            out.append(run)
            run = None
    if run:
        out.append(run)
    return out


def is_closed(pts, run):
    """Whether a run from arcs is the whole ring."""
    return len(run) == len(pts) and all(i == j for i, j, _ in run)


def lerp_run(pts, run):
    return [tuple(Vector(pts[i]).lerp(Vector(pts[j]), t)) for i, j, t in run]


# --- meshes --------------------------------------------------------------------------------------------------------

def frame_mesh(name, rows, depth, closed=False):
    """A strip round the body through rows [(s, (x, z) run)], each run the skin's own section at its station: its
    outer face on the runs, its inner face depth (one, or one per run point) further in, closed across the first and
    last station's faces, and at the run's ends unless closed (the whole ring). Rows between the frame's two faces
    follow any skin ring there, so the strip keeps to the skin where it kinks (the trough's ramps)."""
    m, n = len(rows), len(rows[0][1])
    outer = [[bi.P(s, x, z) for x, z in run] for s, run in rows]
    inner = [[bi.P(s, x, z) for x, z in offset(run, depth, closed)] for s, run in rows]
    # a ring of 2m points round each run point: down the outer face from first to last row, back up the inner face
    loops = [[outer[r][i] for r in range(m)] + [inner[r][i] for r in reversed(range(m))] for i in range(n)]
    k = 2 * m
    verts = [v for loop in loops for v in loop]
    faces = [(i * k + j, (i + 1) % n * k + j, (i + 1) % n * k + (j + 1) % k, i * k + (j + 1) % k)
             for i in range(n if closed else n - 1) for j in range(k)]
    if not closed:
        faces += [tuple(range(k))[::-1], tuple((n - 1) * k + j for j in range(k))]
    return bi.mesh_object(name, verts, faces)


def bar(name, path, ups, width, depth):
    """A box-section bar along the 3D points path, its outer face on them, depth toward ups (unit vectors into the
    body at each point), width across."""
    verts = []
    for i, (q, up) in enumerate(zip(path, ups)):
        along = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        across = along.cross(up).normalized() * (width / 2)
        verts += [q - across, q + across, q + across + up * depth, q - across + up * depth]
    n = len(path)
    faces = [(4 * i + k, 4 * (i + 1) + k, 4 * (i + 1) + (k + 1) % 4, 4 * i + (k + 1) % 4)
             for i in range(n - 1) for k in range(4)]
    faces += [(3, 2, 1, 0), (4 * (n - 1), 4 * (n - 1) + 1, 4 * (n - 1) + 2, 4 * (n - 1) + 3)]
    return bi.mesh_object(name, verts, faces)


def joined(name, objs):
    """One mesh of objs (all world-placed at identity), the rest removed, a piece a cut left empty with them."""
    objs = [o for o in objs if o is not None]
    bm = bmesh.new()
    for o in objs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    # n-gons (a rib's flat faces) as triangles, which the trim projection (trims.project) and the export take one by one
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for o in objs:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    obj = bpy.data.objects.new(name, me)
    bi.TARGET.objects.link(obj)
    return obj


def triangulated(obj):
    """Triangulate the n-gons a boolean leaves, as the export would."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def overlaps(a, b):
    from checks import tree

    return bool(tree(a).overlap(tree(b)))


def altitude(face):
    """A triangle's least height, over its longest edge (any other face: infinite)."""
    if len(face.verts) != 3:
        return math.inf
    a, b, c = (v.co for v in face.verts)
    longest = max((b - a).length, (c - b).length, (a - c).length)
    return (b - a).cross(c - a).length / longest if longest else 0.0


def tidy(obj, drop=True):
    """Clear what a cut or a thin cap leaves that is no structure: zero-width slivers (their edges turned within
    flat faces, else dissolved), and with drop, pieces cut loose smaller than SANE's drop_piece across."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    flat = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(1.0) < math.radians(2)]
    bmesh.ops.beautify_fill(bm, faces=bm.faces[:], edges=flat)
    bmesh.ops.dissolve_degenerate(bm, dist=SANE["min_altitude"], edges=bm.edges)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    # What is left across a curve: turn each sliver's long edge where that leaves no sliver, and drop the slivers that
    # remain, a gap under a millimetre wide that no camera sees.
    for f in [f for f in bm.faces if altitude(f) < SANE["min_altitude"]]:
        if not f.is_valid or altitude(f) >= SANE["min_altitude"]:
            continue
        long = max(f.edges, key=lambda e: e.calc_length())
        if long.is_manifold:
            turned = bmesh.ops.rotate_edges(bm, edges=[long], use_ccw=False)["edges"]
            if turned and any(altitude(g) < SANE["min_altitude"] for e in turned for g in e.link_faces):
                bmesh.ops.rotate_edges(bm, edges=turned, use_ccw=True)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if altitude(f) < SANE["min_altitude"]], context="FACES_ONLY")
    seen, loose = set(), []
    for start in bm.verts:
        if start in seen:
            continue
        island, todo = [], [start]
        seen.add(start)
        while todo:
            v = todo.pop()
            island.append(v)
            for e in v.link_edges:
                w = e.other_vert(v)
                if w not in seen:
                    seen.add(w)
                    todo.append(w)
        lo = Vector([min(v.co[i] for v in island) for i in range(3)])
        hi = Vector([max(v.co[i] for v in island) for i in range(3)])
        if drop and (hi - lo).length < SANE["drop_piece"]:
            loose += island
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def cut_clear(obj, cutters):
    """obj less every cutter it meets."""
    hit = [c for c in cutters if overlaps(obj, c)]
    if hit:
        interior.subtract(interior.outward(obj), hit)
        tidy(obj)
    return obj


def box_mesh(name, centre, size):
    """An axis-aligned box, size (x, y, z) in Blender axes, about centre."""
    hx, hy, hz = (v / 2 for v in size)
    verts = [centre + Vector((sx * hx, sy * hy, sz * hz)) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return bi.mesh_object(name, verts, faces)


class Clearance:
    """How far in from the skin a frame may reach before it meets one of the solids (world BVH of their faces)."""

    def __init__(self, solids):
        from checks import tree

        self.trees = [tree(o) for o in solids]

    def gap(self, origin, direction, reach):
        hits = [t.ray_cast(origin, direction, reach)[3] for t in self.trees]
        return min([d for d in hits if d is not None] + [reach])


def tag(obj, owner, mat, parent=None):
    """A skeleton piece of owner's mesh, hung on parent (the owner by default)."""
    if not obj.data.materials:
        obj.data.materials.append(mat)
    tidy(obj, drop=False)  # the cuts already dropped their loose bits; small fittings stay
    if not obj.get("inner_face"):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        bm.free()
    obj["role"] = "visual"
    obj["skeleton_owner"] = owner
    obj["parent_part"] = parent or owner
    return obj


# --- the root section ----------------------------------------------------------------------------------------------

def upper(p, s):
    """Whether a section point lies over the truss's 45 degree edges (parts.shell_points)."""
    zc = bi.fuselage_shapes(p, s)[1]
    return lambda q: q[1] - zc > abs(q[0])


def wing_root_cutters(p):
    """The wing roots buried in the body, each grown by 10 mm, at half again the wing's depth: the box's own skin round
    the root stands proud of the plain airfoil."""
    w, out = p["wing"], []
    for side in (1, -1):
        root = bi.lifting_surface("skel_wing_cut", bi.wing_sections(w)[:4], w["thickness"] * 1.5, "z")
        if side < 0:
            root.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
            root.data.flip_normals()
        out.append(interior.grown(interior.outward(root), 0.010))
        bpy.data.objects.remove(root, do_unlink=True)
    return out


def root_cutters(p):
    """Solids the root's frames and longerons stand clear of: the Y-duct and the shock cones, the main gear wells and
    the wing roots buried in the body, each grown by 10 mm."""
    cutters = interior.duct_cutter(p, 0.010) + wing_root_cutters(p)
    g = 0.010
    grow = lambda boxes: [(s0 - g, s1 + g, x0 - g, x1 + g, z0 - g, z1 + g) for s0, s1, x0, x1, z0, z1 in boxes]
    main = interior.bay_boxes("main_gear_bay")
    keel = (*main[0][:2], -main[0][3], main[0][3], *main[0][4:])
    cutters.append(interior.boxes_solid("skel_well_cut", grow([keel] + main[1:] + interior.bay_boxes("main_gear_bay", -1)[1:]),
                                        [0] + list(range(1, len(main))) * 2))
    return cutters


def frame_piece(p, clear, sec, run, s0, s1, depth):
    """A frame strip between stations s0 and s1 on a run of a Section; over a solid close under the skin it runs only
    as deep as the gap allows (CLEARANCE)."""
    s = (s0 + s1) / 2
    pts = lerp_run(sec.at(s), run)
    closed = is_closed(sec.pts, run)
    depths = []
    for (x, z), (xi, zi) in zip(pts, offset(pts, 1.0, closed)):
        n = Vector((xi - x, 0.0, zi - z)).normalized()
        gap = clear.gap(bi.P(s, x, z), n, depth + CLEARANCE["gap"])
        depths.append(max(CLEARANCE["min_depth"], min(depth, gap - CLEARANCE["gap"])))
    stations = [s0] + [st for st in bi.fuselage_stations(p) if s0 + 1e-4 < st < s1 - 1e-4] + [s1]
    return frame_mesh("skel_frame", [(st, lerp_run(sec.at(st), run)) for st in stations], depths, closed)


def member_bar(p, name, deg, stations, size):
    """A longeron or stringer along the skin at angle deg round each station's section centre."""
    path, ups = [], []
    for st in stations:
        zc = bi.fuselage_shapes(p, st)[1]
        x, z = ray_point(section(p, st), (0.0, zc), math.radians(deg))
        path.append(bi.P(st, x, z))
        ups.append(Vector((-x, 0.0, zc - z)).normalized())
    return bar(name, path, ups, size["width"], size["depth"])


def finished(p, pieces, cutters, s_range, mat):
    """Each owner's pieces cut clear of the cutters, clipped 4 mm inside the skin over s_range where they reach it
    (internals.compartment_solid: where the skin turns sharply in, an inset outline can still cross it), joined into
    one tagged mesh per owner."""
    skin = interior.compartment_solid(p, 0.004, *s_range)
    out = []
    for owner, objs in pieces.items():
        if not objs:
            continue
        for o in objs:
            cut_clear(o, cutters)
            if overlaps(o, skin):
                interior.clip_to(o, skin)
                tidy(o)
        out.append(tag(joined("skel_" + owner, objs), owner, mat))
    bpy.data.objects.remove(skin, do_unlink=True)
    return out


def build_root(p, mats):
    import parts

    mat = mats["mechanical"]
    pieces = {"fuselage_mid": [], "fuselage_truss_front": [], "fuselage_truss_rear": []}
    truss = lambda s: "fuselage_truss_front" if s < parts.TRUSS_BREAK else "fuselage_truss_rear"
    cutters = root_cutters(p)
    clear = Clearance(cutters)

    def frame(owner, sec, run, s0, s1, depth):
        pieces[owner].append(frame_piece(p, clear, sec, run, s0, s1, depth))

    frames = ([(s, FRAME) for s in ROOT["frames"]] + [(ROOT["closing"][0], BULKHEAD)]
              + [(s, CLOSING) for s in ROOT["closing"][1:]])
    for s, kind in frames:
        sec = Section(p, s, kind["flange"])
        s0, s1 = s - kind["flange"] / 2, s + kind["flange"] / 2
        for run in arcs(sec.pts, upper(p, s)):
            frame(truss(s), sec, run, s0, s1, kind["depth"])
        for run in arcs(sec.pts, lambda q, up=upper(p, s): not up(q)):
            frame("fuselage_mid", sec, run, s0, s1, kind["depth"])
    # The truss frame: its lower arc a frame of the root's, its upper arc a closing frame each side of the break.
    s = ROOT["truss_frame"]
    sec = Section(p, s, 2 * CLOSING["flange"])
    for run in arcs(sec.pts, lambda q, up=upper(p, s): not up(q)):
        frame("fuselage_mid", sec, run, s - FRAME["flange"] / 2, s + FRAME["flange"] / 2, FRAME["depth"])
    for run in arcs(sec.pts, upper(p, s)):
        frame("fuselage_truss_front", sec, run, s - CLOSING["flange"], s - 0.001, CLOSING["depth"])
        frame("fuselage_truss_rear", sec, run, s + 0.001, s + CLOSING["flange"], CLOSING["depth"])
    dorsal = lambda q: q[1] > parts.DORSAL_Z and abs(q[0]) < parts.DORSAL_HALF_WIDTH
    edges = {1: [], -1: []}  # the dorsal arcs' ends, each side, aft from the root's aft closing frame
    for s, kind in [(ROOT["closing"][1], CLOSING)] + [(st, FRAME) for st in ROOT["dorsal_frames"]] + [(ROOT["dorsal_end"], CLOSING)]:
        sec = Section(p, s, kind["flange"])
        for run in arcs(sec.pts, dorsal):
            if s > ROOT["closing"][1]:
                frame("fuselage_truss_rear", sec, run, s - kind["flange"] / 2, s + kind["flange"] / 2, kind["depth"])
            for end in (run[0], run[-1]):
                (x, z), = lerp_run(sec.pts, [end])
                edges[1 if x > 0 else -1].append(bi.P(s, x, z))
    # Over the aft section the dorsal arcs end on a member each side along the cover's edges, not in the air.
    for path in edges.values():
        if len(path) > 1:
            ups = [Vector((-v.x, 0.0, -1.0)).normalized() for v in path]
            pieces["fuselage_truss_rear"].append(bar("skel_longeron", path, ups, LONGERON["width"], LONGERON["depth"]))
    # Longerons through every frame station; the spine's in two at the truss break, the rest at the intake lip, where
    # the fairings start abruptly and a longeron run straight across would leave the skin.
    stations = sorted([st for st, _ in frames] + [ROOT["truss_frame"]])
    split = lambda at: [[st for st in stations if st <= at], [st for st in stations if st >= at]]
    lip = p["intake"][0][0]
    members = [(deg, LONGERON, group) for group, angles in ROOT["longerons"].items() for deg in angles]
    members += [(deg, STRINGER, "stringer") for deg in ROOT["stringers"]]
    for deg, size, group in members:
        runs = split(lip)
        if group == "spine":
            front, rear = split(ROOT["truss_frame"])
            runs = [front, rear + list(ROOT["dorsal_frames"]) + [ROOT["dorsal_end"]]]
        over = 45.0 < deg < 135.0  # over the truss's edges: the truss's member
        for run in runs:
            if over and group == "stringer":  # a stringer over the truss parts with it at the truss break
                runs_here = [[st for st in run if st <= ROOT["truss_frame"]], [st for st in run if st >= ROOT["truss_frame"]]]
            else:
                runs_here = [run]
            for leg in [r for r in runs_here if len(r) > 1]:
                owner = truss(leg[0] + 0.01) if over else "fuselage_mid"
                pieces[owner].append(member_bar(p, "skel_" + group, deg, leg, size))
    # The equipment shelf and its boxes, bay by bay from the intake lip aft, each the truss half's over it.
    sh = ROOT["shelf"]
    bays = sorted(st for st, _ in frames if st > lip) + [ROOT["truss_frame"]]
    bays = sorted(bays)
    for a, b in zip(bays, bays[1:]):
        s0, s1 = a + CLOSING["flange"] / 2 + 0.01, b - CLOSING["flange"] / 2 - 0.01
        half = min(body_x(p, s, sh["z"]) for s in (s0, s1)) - sh["edge"]
        centre = bi.P((s0 + s1) / 2, 0.0, sh["z"] - sh["thickness"] / 2)
        owner = truss((s0 + s1) / 2)
        pieces[owner].append(box_mesh("skel_shelf", centre, (2 * half, s1 - s0, sh["thickness"])))
        bl, bw, bh = sh["box"]
        for side in (1, -1):
            pieces[owner].append(box_mesh("skel_avionics", bi.P((s0 + s1) / 2, side * half / 2, sh["z"] + bh / 2),
                                          (bw, min(bl, s1 - s0 - 0.04), bh)))
    out = finished(p, pieces, cutters, (ROOT["closing"][0] - 0.1, ROOT["dorsal_end"] + 0.1), mat)
    for c in cutters:
        bpy.data.objects.remove(c, do_unlink=True)
    return out


# --- the other sections, the engine and the intakes -----------------------------------------------------------------

def grown_boxes(name, boxes, g=0.010):
    """One closed solid of (s0, s1, x0, x1, z0, z1) boxes, each grown by g."""
    return interior.boxes_solid(name, [(s0 - g, s1 + g, x0 - g, x1 + g, z0 - g, z1 + g)
                                       for s0, s1, x0, x1, z0, z1 in boxes])


def compartment(name, entry, g=0.010):
    """An internals.INTERNALS box (s0, s1, half width, z0, z1), grown by g, as a solid."""
    s0, s1, hw, z0, z1 = interior.INTERNALS[entry]["box"]
    return box_mesh(name, bi.P((s0 + s1) / 2, 0.0, (z0 + z1) / 2), (2 * (hw + g), s1 - s0 + 2 * g, z1 - z0 + 2 * g))


def opening_floor(p, mats):
    """The cockpit opening's lowest edge at a station: the closed canopy shape parts.organise cuts the opening with
    (canopy.build_canopy, grown by canopy.FRAME_CLEAR), its section's lowest point, or None where it has none. Returns
    the function; it measures the shape once per station asked."""
    import canopy

    solid = canopy.build_canopy(p, mats["structure"])
    cache = {}

    def floor(s):
        if s not in cache:
            pts = interior.section_points(solid, s)
            cache[s] = min(z for _, z in pts) - canopy.FRAME_CLEAR if pts else None
        return cache[s]

    floor.solid = solid
    return floor


def section_angle(p, s, q):
    """A section point's angle round the section's centre, degrees from the left side (+x)."""
    return math.degrees(math.atan2(q[1] - bi.fuselage_shapes(p, s)[1], q[0]))


def ring_frames(p, clear, pieces, owner, s, kind, keep=lambda q: True):
    """The frame at s, as runs of its section where keep holds."""
    sec = Section(p, s, kind["flange"])
    for run in arcs(sec.pts, keep):
        pieces[owner].append(frame_piece(p, clear, sec, run, s - kind["flange"] / 2, s + kind["flange"] / 2,
                                         kind["depth"]))


def build_nose(p, mats):
    """The radome's, the forward section's and the cockpit cell's frames and members."""
    pieces = {"radome": [], "fuselage_forward": [], "cockpit_cell": []}
    tub = interior.INTERNALS["cockpit_tub"]["box"]
    cutters = [grown_boxes("skel_nose_well", interior.bay_boxes("nose_gear_bay")), compartment("skel_tub", "cockpit_tub")]
    solids = [compartment("skel_avionics", "avionics_nose"), compartment("skel_avionics_aft", "avionics_aft")]
    r = interior.INTERNALS["radar"]
    solids.append(box_mesh("skel_radar", bi.P((r["dish_s"] + r["s"][1]) / 2, 0.0, 0.03),
                           (2 * r["dish_r"], r["s"][1] - r["dish_s"] + 0.06, 2 * r["dish_r"])))
    clear = Clearance(cutters + solids)
    for s in FORE["radome"]:
        ring_frames(p, clear, pieces, "radome", s, FRAME)
    ring_frames(p, clear, pieces, "radome", FORE["radome_end"], CLOSING)
    floor = opening_floor(p, mats)

    def foot(s):
        """The opening's floor over a frame's width and the grown opening's reach either side of it."""
        found = [f for f in (floor(s + d) for d in (-0.05, 0.0, 0.05)) if f is not None]
        return min(found) if found else None
    foot.solid = floor.solid
    below_sill = lambda s: (lambda q: foot(s) is None or q[1] < foot(s) - FORE["sill_gap"])
    for s in FORE["frames"]:
        ring_frames(p, clear, pieces, "fuselage_forward", s, FRAME, below_sill(s))
    for s in FORE["closing"]:
        ring_frames(p, clear, pieces, "fuselage_forward", s, CLOSING, below_sill(s))
    # The cockpit cell's bulkhead frames just outside the tub's ends, and its sill longerons under the canopy's foot,
    # which the forward section's frames end on.
    for s in (tub[0] - FORE["tub_gap"], tub[1] + FORE["tub_gap"]):
        ring_frames(p, clear, pieces, "cockpit_cell", s, FRAME, below_sill(s))
    rows = p["canopy"]
    stations = [s for s in (rows[0][0] + (rows[-1][0] - rows[0][0]) * i / 10 for i in range(11)) if foot(s) is not None]
    for side in (1, -1):
        path = []
        for s in stations:
            z = foot(s) - FORE["sill_gap"] - LONGERON["width"] / 2
            # inside the skin at the bar's top and foot both, where the side curves in
            x = min(body_x(p, s, z + d) for d in (-LONGERON["width"] / 2, 0.0, LONGERON["width"] / 2))
            path.append(bi.P(s, side * (x - FRAME["inset"]), z))
        pieces["cockpit_cell"].append(bar("skel_sill", path, [Vector((-side, 0.0, 0.0))] * len(path),
                                          LONGERON["width"], LONGERON["depth"]))
    fwd = [FORE["closing"][0]] + list(FORE["frames"]) + [FORE["closing"][1]]
    for deg in FORE["stringers"]:
        pieces["fuselage_forward"].append(member_bar(p, "skel_stringer", deg, fwd, STRINGER))
    for deg in FORE["radome_stringers"]:
        pieces["radome"].append(member_bar(p, "skel_stringer", deg, list(FORE["radome"]) + [FORE["radome_end"]],
                                           STRINGER))
    out = finished(p, pieces, cutters, (0.5, FORE["closing"][1] + 0.1), mats["mechanical"])
    for o in cutters + solids + [foot.solid]:
        bpy.data.objects.remove(o, do_unlink=True)
    return out


def engine_axis(s):
    """The engine's centre (z) at station s, on internals.INTERNALS engine's line."""
    e = interior.INTERNALS["engine"]
    return e["z0"] + (e["z1"] - e["z0"]) * (s - e["face_s"]) / (e["end_s"] - e["face_s"])


def engine_radius(s):
    e = interior.INTERNALS["engine"]
    if s <= e["core_end_s"]:
        return e["radius"]
    return e["radius"] * 0.96 + (e["ab_radius"] - e["radius"] * 0.96) * (s - e["core_end_s"]) / (e["end_s"] - e["core_end_s"])


def circle(cx, cz, r, n, start=0.0):
    return [(cx + r * math.cos(start + 2 * math.pi * k / n), cz + r * math.sin(start + 2 * math.pi * k / n))
            for k in range(n)]


def engine_solid(name, s0, s1):
    """The engine's outline from s0 to s1 as a closed solid, for clearances."""
    n = ENGINE["sides"]
    rings = [[bi.P(s, x, z) for x, z in circle(0.0, engine_axis(s), engine_radius(s) + 0.005, n)] for s in (s0, s1)]
    return interior.outward(bi.loft(name, rings, cap_back=True, cap_front=True))


def build_engine(p, mats):
    """The engine's face, flanged core casing and afterburner section."""
    e, E = interior.INTERNALS["engine"], ENGINE
    n = E["sides"]
    width, height = E["flange"]

    def casing(name, s0, s1, steps):
        stations = [s0 + (s1 - s0) * i / steps for i in range(steps + 1)]
        rings = [[bi.P(s, x, z) for x, z in circle(0.0, engine_axis(s), engine_radius(s), n)] for s in stations]
        return bi.loft(name, rings)

    def flange(s):
        pts = circle(0.0, engine_axis(s), engine_radius(s) + height, n)
        return frame_mesh("skel_flange", [(s - width / 2, pts), (s + width / 2, pts)], height, closed=True)

    core = [casing("skel_casing", e["face_s"], e["core_end_s"], 3)] + [flange(s) for s in E["flanges"]]
    # the face: a hub, point forward, and blades set 30 degrees across the flow
    s, zc, hub = e["face_s"], engine_axis(e["face_s"]), E["hub"]
    tip = bi.P(s - 1.2 * hub, 0.0, zc)
    base = [bi.P(s, x, z) for x, z in circle(0.0, zc, hub, 8)]
    core.append(bi.mesh_object("skel_hub", [tip] + base, [(0, 1 + (k + 1) % 8, 1 + k) for k in range(8)]
                               + [tuple(range(1, 9))]))
    for k in range(E["blades"]):
        a = 2 * math.pi * (k + 0.5) / E["blades"]
        radial, across = Vector((math.cos(a), 0.0, math.sin(a))), Vector((-math.sin(a), 0.0, math.cos(a)))
        chord = (Vector((0.0, 1.0, 0.0)) * math.cos(math.radians(30)) + across * math.sin(math.radians(30))) * 0.03
        thick = Vector((0.0, 1.0, 0.0)).cross(radial) * 0.004
        centre = bi.P(s + 0.04, 0.0, zc)
        verts = [centre + radial * r + chord * c + thick * t for r in (hub + 0.01, engine_radius(s) - 0.02)
                 for c in (-1, 1) for t in (-1, 1)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        core.append(bi.mesh_object("skel_blade", verts, faces))
    ab = [casing("skel_casing", e["core_end_s"], e["end_s"], 2)] + [flange(s) for s in E["ab_flanges"]]
    mat = mats["mechanical"]
    return [tag(joined("skel_engine_core", core), "engine_core", mat),
            tag(joined("skel_engine_afterburner", ab), "engine_afterburner", mat)]


def build_aft(p, mats):
    """The aft section's and the tail cone's frames and members."""
    import parts

    pieces = {"fuselage_aft": [], "fuselage_tail": []}
    cutters = wing_root_cutters(p)
    e = interior.INTERNALS["engine"]
    solids = [engine_solid("skel_engine_cut", e["face_s"], e["end_s"])]
    solids += [o for o in bpy.data.objects if o.type == "MESH" and o.data.polygons and o.name.startswith(
        ("ventral_fin", "speed_brake_well"))]
    clear = Clearance(cutters + solids)
    dorsal = lambda q: q[1] > parts.DORSAL_Z and abs(q[0]) < parts.DORSAL_HALF_WIDTH
    off_dorsal = lambda s: (lambda q: s > parts.DORSAL[1] or not dorsal(q))
    for s in AFT["frames"]:
        ring_frames(p, clear, pieces, "fuselage_aft", s, FRAME, off_dorsal(s))
    for s in AFT["closing"]:
        ring_frames(p, clear, pieces, "fuselage_aft", s, CLOSING, off_dorsal(s))
    lo, hi = AFT["brake_deg"]
    clear_of_brakes = lambda s: (lambda q: not (lo < section_angle(p, s, q) < hi
                                                or lo < 180.0 - section_angle(p, s, q) < hi
                                                or lo < -180.0 - section_angle(p, s, q) < hi))
    ring_frames(p, clear, pieces, "fuselage_tail", AFT["tail_closing"], CLOSING, clear_of_brakes(AFT["tail_closing"]))
    for s in AFT["tail_frames"]:
        ring_frames(p, clear, pieces, "fuselage_tail", s, FRAME)
    aft = [AFT["closing"][0]] + list(AFT["frames"]) + [AFT["closing"][1]]
    tail = [AFT["tail_closing"]] + list(AFT["tail_frames"])
    for deg in (45.0, 135.0, -18.0, -162.0):
        pieces["fuselage_aft"].append(member_bar(p, "skel_longeron", deg, aft, LONGERON))
    for deg in (22.5, 157.5, -35.0, -145.0, -78.0, -102.0):
        pieces["fuselage_aft"].append(member_bar(p, "skel_stringer", deg, aft, STRINGER))
    # aft of the speed brakes' wells only, none across the wells' openings
    for deg in (45.0, 135.0, 90.0):
        pieces["fuselage_tail"].append(member_bar(p, "skel_longeron", deg, tail, LONGERON))
    for deg in (22.5, 157.5, 67.5, 112.5, -78.0, -102.0):
        pieces["fuselage_tail"].append(member_bar(p, "skel_stringer", deg, tail, STRINGER))
    for deg in (-35.0, -145.0):
        pieces["fuselage_tail"].append(member_bar(p, "skel_stringer", deg, tail[1:], STRINGER))
    out = finished(p, pieces, cutters, (AFT["closing"][0] - 0.1, AFT["tail_frames"][-1] + 0.2), mats["mechanical"])
    for o in cutters + solids[:1]:
        bpy.data.objects.remove(o, do_unlink=True)
    return out


def build_intakes(p, mats):
    """Frames round each intake's duct branch, owned by its duct."""
    I, out = INTAKE, []
    for side, sd in ((1, "L"), (-1, "R")):
        frames = []
        for s in I["frames"]:
            depth = I["closing_depth"] if s in (I["frames"][0], I["frames"][-1]) else I["depth"]
            _, cx, cz, r = bi.resample(p["duct"], [s])[0]
            pts = circle(side * cx, cz, r + I["gap"] + depth, I["points"])
            if signed_area(pts) < 0:
                pts.reverse()
            frames.append(frame_mesh("skel_frame", [(s - 0.012, pts), (s + 0.012, pts)], depth, closed=True))
        out.append(tag(joined("skel_intake_duct_" + sd, frames), "intake_duct_" + sd, mats["mechanical"]))
    return out


def mirrored(objs):
    """Right-hand twins of left-hand skeleton pieces, mirrored across x = 0, owned by the right-hand parts."""
    out = []
    for o in objs:
        twin = bpy.data.objects.new(o.name.replace("_L", "_R"), o.data.copy())
        bi.TARGET.objects.link(twin)
        twin.data.transform(o.matrix_world)
        twin.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
        twin.data.flip_normals()
        if o.get("inner_face"):
            twin["inner_face"] = True
        out.append(tag(twin, o["skeleton_owner"].replace("_L", "_R"), o.data.materials[0],
                       o["parent_part"].replace("_L", "_R")))
    return out


def build_ventral(p, mats):
    """The ventral fin's lattice, and the hooked variant's keel bar and posts."""
    import tail_hook

    V, vf = VENTRAL, p["ventral_fin"]
    sec, th = list(reversed(vf["sections"])), vf["thickness"]  # rows by rising z, as section_at reads them
    body = interior.inner_solid(p, -0.008, 10.6, 13.4, step=0.15)
    spars = (V["front"], V["mid"], V["rear"])
    z0, z1 = sec[0][2] + 0.02, sec[-1][2]
    pieces = [rib("skel_rib_tip", sec, "z", z0, V["le"], V["te"], th, 7)]
    for f in (V["le"],) + spars:
        pieces.append(spar("skel_spar", sec, "z", z0 + RIB["thickness"], z1, f, th))
    for u in V["ribs"]:
        pieces += rib_pieces(sec, "z", u, (V["le"],) + spars + (V["te"],), th)
    for o in pieces:
        cut_clear(o, [body])
    bpy.data.objects.remove(body, do_unlink=True)
    out = [tag(joined("skel_ventral_fin", pieces), "ventral_fin", mats["mechanical"])]
    bottom = lambda s: min(v.z for v in bi.skin_ring(p, s) if abs(v.x) < 0.05)
    lift = V["hooked_lift"]
    s0, s1 = V["hooked_keel"]
    keel = [bi.P(s, 0.0, tail_hook.zline(p, s) + lift) for s in (s0 + (s1 - s0) * i / 6 for i in range(7))]
    hooked = [bar("skel_keel", keel, [Vector((0.0, 0.0, 1.0))] * len(keel), 0.016, 0.025)]
    for s in V["hooked_posts"]:
        post = [bi.P(s, 0.0, tail_hook.zline(p, s) + lift + 0.02), bi.P(s, 0.0, bottom(s) - 0.03)]
        if post[1].z - post[0].z > 0.1:  # where the pod rises to the belly there is no room for one
            hooked.append(bar("skel_post", post, [Vector((0.0, 1.0, 0.0))] * 2, 0.016, 0.025))
    out.append(tag(joined("skel_ventral_fin_hooked", hooked), "ventral_fin_hooked", mats["mechanical"]))
    return out


# --- lifting surfaces ----------------------------------------------------------------------------------------------

def body_x(p, s, z):
    """How far out from the centre line the fuselage skin stands at station s and height z."""
    pts = [(v.x, v.z) for v in bi.skin_ring(p, s)]
    best = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        if (a[1] - z) * (b[1] - z) <= 0 and a[1] != b[1]:
            best = max(best, a[0] + (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]))
    return best


def rib(name, sections, axis, u, f0, f1, thickness, count):
    return bi.strip(name, sections, [(u - RIB["thickness"] / 2, f0, f1), (u + RIB["thickness"] / 2, f0, f1)],
                    thickness * RIB["depth"], axis, count=count)


def spar(name, sections, axis, u0, u1, f, thickness):
    stations = [(u, f - SPAR["thickness"] / 2, f + SPAR["thickness"] / 2) for u in bi.span_stations(sections, axis, u0, u1)]
    return bi.strip(name, sections, stations, thickness * RIB["depth"], axis, count=2)


def root_rib(name, sections, p, count=9):
    """The inner box's closing rib where the wing leaves the body: at each chord point it stands on the body's side, as
    far out as the skin there across the rib's whole depth (body_x at its top, middle and foot: the wing fillet bulges
    out above and below the wing), a rib's thickness thick."""
    w = p["wing"]
    rows = []
    for k in range(count):
        # from twice the other ribs' nose: at the root the strake's leading edge blends into the fairing's fillet
        t = 2 * WING["le"] + (WING["inner_te"] - 2 * WING["le"]) * k / (count - 1)
        # the span position where this chord point leaves the body, by fixed point on the planform
        u = 1.0
        for _ in range(8):
            s_le, x, z, chord = bi.section_at(sections, u, "x")
            h = bi.airfoil(t) * w["thickness"] * chord * RIB["depth"]
            u = max(sections[0][1], max(body_x(p, s_le + t * chord, z + d) for d in (-h, 0.0, h)) + 0.02)
        s_le, x, z, chord = bi.section_at(sections, u, "x")
        half = bi.airfoil(t) * w["thickness"] * chord * RIB["depth"]
        rows.append((s_le + t * chord, u, z, max(half, 0.0015)))
    rings = []
    for dx in (0.0, RIB["thickness"]):
        upper_ = [bi.P(s, u + dx, z + h) for s, u, z, h in rows]
        lower_ = [bi.P(s, u + dx, z - h) for s, u, z, h in rows]
        rings.append(upper_ + lower_[::-1])
    return bi.welded(bi.loft(name, rings, cap_back=True, cap_front=True))


def surface_shell(p, name, sections, thickness, axis, cut, count=4):
    """A moving surface's inner face: a closed shell inside its skin, faces turned in, from just clear of its hinge
    to near its far edge, between its end gaps."""
    sname, u0, u1, f0, f1, gaps = cut
    h = bi.hinge_line(sections, cut, axis)
    stations = []
    for u in bi.span_stations(sections, axis, u0 + gaps[0] + 0.006, u1 - gaps[1] - 0.006):
        t = bi.hinge_fraction(sections, h, u, axis)
        a, b = (t + SURFACE["hinge_clear"], SURFACE["edge"]) if h["aft"] else (1 - SURFACE["edge"], t - SURFACE["hinge_clear"])
        stations.append((u, a, b))
    obj = bi.strip("skel_" + sname, sections, stations, thickness * SURFACE["depth"], axis, count=count)
    interior.outward(obj)
    obj.data.flip_normals()
    obj["inner_face"] = True  # parts.face_outward leaves its faces turned in
    return obj


def rib_pieces(sections, axis, u, fractions, thickness):
    """A rib at span u in pieces between consecutive chord fractions, each piece stopping at the spar faces."""
    g = SPAR["thickness"] / 2
    return [rib("skel_rib", sections, axis, u, a + g, b - g, thickness, 3)
            for a, b in zip(fractions, fractions[1:])]


def skin_stringer(sections, axis, u0, u1, f, side, thickness):
    """A stringer along the span under one skin (side 1 upper or left, -1 lower or right) at chord fraction f, its
    outer face where the ribs' edges are, its depth toward the chord plane."""
    path, ups = [], []
    normal = Vector((0.0, 0.0, 1.0)) if axis == "x" else Vector((1.0, 0.0, 0.0))
    for u in bi.span_stations(sections, axis, u0, u1):
        s_le, x, z, chord = bi.section_at(sections, u, axis)
        half = bi.airfoil(f) * thickness * chord * RIB["depth"]
        path.append(bi.P(s_le + f * chord, x, z) + normal * (side * half))
        ups.append(normal * -side)
    return bar("skel_stringer", path, ups, STRINGER["width"], min(STRINGER["depth"], 0.5 * min(
        bi.airfoil(f) * thickness * bi.section_at(sections, u, axis)[3] * RIB["depth"]
        for u in bi.span_stations(sections, axis, u0, u1))))


def build_wing_L(p, mats):
    w, sec = p["wing"], bi.wing_sections(p["wing"])
    th, mat = w["thickness"], mats["mechanical"]
    W = WING
    body = interior.inner_solid(p, -0.008, 6.4, 12.6, step=0.15)  # 8 mm proud of the skin: no piece touches it
    # Built clear of the body (rows ~0.18 m apart follow the fairing's bulge), so no cut: the exact boolean reads the
    # curved rib as inside the body and leaves nothing of it.
    root_closing = root_rib("skel_rib_root", sec, p, count=24)
    inner = []
    root = sec[0][1] + 0.04
    # The crank ribs stand off the crank, where the skin parts and the leading-edge flap's cove walls start.
    crank_in, crank_out = W["crank"] - W["crank_gap"], W["crank"] + W["crank_gap"]
    flap_from = next(cut for cut in p["wing_surfaces"] if cut[0] == "flap_L")[1]
    spars = (W["front"], W["mid"], W["rear"])
    for f in (W["le"],) + spars:  # the leading-edge member first: the ribs' noses end on it
        inner.append(spar("skel_spar", sec, "x", root, crank_in, f, th))
    for u in W["inner_ribs"]:
        # outboard of the flap's inboard end the box stops at the flap's cove, just aft of the rear spar
        inner += rib_pieces(sec, "x", u, (W["le"],) + spars + ((W["inner_te"],) if u < flap_from else ()), th)
    inner.append(rib("skel_rib_te", sec, "x", 1.05, W["rear"] + SPAR["thickness"] / 2, W["inner_te"], th, 3))
    inner.append(rib("skel_rib_crank", sec, "x", crank_in, W["le"], W["flap_te"], th, 9))
    for f in W["stringers"]:
        for side in (1, -1):
            inner.append(skin_stringer(sec, "x", root, crank_in, f, side, th))
    for o in inner:
        cut_clear(o, [body])
    inner.append(root_closing)
    outer = [rib("skel_rib_crank", sec, "x", crank_out, *W["box"], th, 7),
             rib("skel_rib_tip", sec, "x", W["tip"], *W["box"], th, 7)]
    for f in spars:
        outer.append(spar("skel_spar", sec, "x", crank_out, W["tip"] - RIB["thickness"] / 2, f, th))
    for u in W["outer_ribs"]:
        outer += rib_pieces(sec, "x", u, spars, th)
    for f in W["stringers"]:
        for side in (1, -1):
            outer.append(skin_stringer(sec, "x", crank_out, W["tip"] - RIB["thickness"] / 2, f, side, th))
    bpy.data.objects.remove(body, do_unlink=True)
    out = [tag(joined("skel_wing_spar_L", inner), "wing_spar_L", mat),
           tag(joined("skel_wing_spar_outer_L", outer), "wing_spar_outer_L", mat)]
    for cut in p["wing_surfaces"]:
        out.append(tag(surface_shell(p, cut[0], sec, th, "x", cut), cut[0], mats["honeycomb"]))
    return out


def fin_root(p, sections, count=9):
    """The fin's closing rib along the body's top line, a rib's thickness thick."""
    f = p["fin"]
    rows = []
    for k in range(count):
        t = FIN["le"] + (FIN["te"] - FIN["le"]) * k / (count - 1)
        u = 1.0
        for _ in range(8):
            s_le, x, z, chord = bi.section_at(sections, u, "z")
            s = s_le + t * chord
            top = max(v.z for v in bi.skin_ring(p, min(s, 15.19)) if abs(v.x) < 0.05)
            u = max(sections[0][2], top + 0.02)
        s_le, x, z, chord = bi.section_at(sections, u, "z")
        rows.append((s_le + t * chord, u, max(bi.airfoil(t) * f["thickness"] * chord * RIB["depth"], 0.0015)))
    rings = []
    for dz in (0.0, RIB["thickness"]):
        rings.append([bi.P(s, h, u + dz) for s, u, h in rows] + [bi.P(s, -h, u + dz) for s, u, h in rows[::-1]])
    return bi.welded(bi.loft("skel_rib_root", rings, cap_back=True, cap_front=True))


def build_fin(p, mats):
    f, sec = p["fin"], p["fin"]["sections"]
    th, mat = f["thickness"], mats["mechanical"]
    body = interior.inner_solid(p, -0.008, 11.5, 15.4, step=0.15)
    root = 0.98
    pieces = [fin_root(p, sec), rib("skel_rib_tip", sec, "z", FIN["tip"], FIN["le"], FIN["rear"], th, 7)]
    spars = (FIN["front"], FIN["mid"], FIN["rear"])
    for fr in (FIN["le"],) + spars:  # the leading-edge member first: the ribs' noses end on it
        pieces.append(spar("skel_spar", sec, "z", root, FIN["tip"] - RIB["thickness"] / 2, fr, th))
    for u in FIN["ribs"]:
        pieces += rib_pieces(sec, "z", u, (FIN["le"],) + spars, th)
    # below the rudder the trailing edge is fixed: a rib out to it
    pieces.append(rib("skel_rib_te", sec, "z", 1.10, FIN["rear"] + SPAR["thickness"] / 2, FIN["te"], th, 3))
    # The hinge box: its two ribs, and webs between them on the middle and rear spars' lines and under the pivot.
    z0, z1 = FIN["top_box"]
    pieces += [rib("skel_rib_hinge", sec, "z", z, *FIN["top_chord"], th, 7) for z in (z0, z1)]
    s_le, _, _, chord = bi.section_at(sec, z1, "z")
    pivot_f = (p["stabilator_pivot_s"] - s_le) / chord
    for fr in (FIN["mid"], FIN["rear"], pivot_f):
        pieces.append(spar("skel_spar", sec, "z", z0 + RIB["thickness"] / 2, z1 - RIB["thickness"] / 2, fr, th))
    for o in pieces:
        cut_clear(o, [body])
    bpy.data.objects.remove(body, do_unlink=True)
    out = [tag(joined("skel_fin_spar", pieces), "fin_spar", mat)]
    for cut in p["fin_surfaces"]:
        out.append(tag(surface_shell(p, cut[0], sec, th, "z", cut), cut[0], mats["honeycomb"]))
    return out + build_junction(p, mats) + build_stabilator(p, mats)


def fairing_radius(p, s):
    """The fin-tip fairing's half width at s (build_icarus.fairing_outline)."""
    outline = bi.fairing_outline(p)
    for (sa, ra), (sb, rb) in zip(outline, outline[1:]):
        if sa <= s <= sb:
            return ra + (rb - ra) * (s - sa) / (sb - sa)
    return 0.0


def cylinder_x(name, s, z, x0, x1, r, sides=8):
    """A closed cylinder along x from x0 to x1 about (s, z)."""
    ring = lambda x: [bi.P(s + r * math.cos(2 * math.pi * k / sides), x, z + r * math.sin(2 * math.pi * k / sides))
                      for k in range(sides)]
    return bi.loft(name, [ring(x0), ring(x1)], cap_back=True, cap_front=True)


def build_junction(p, mats):
    """The T-tail junction in the fin-tip fairing: frames over the fin's top, the pivot fitting, the pivot stubs."""
    J, mat = JUNCTION, mats["mechanical"]
    pivot = p["stabilator_pivot_s"]
    frames = []
    def section_at(s, flip):
        ring = [(v.x, v.z) for v in bi.fairing_ring(p, s, fairing_radius(p, s))]
        return offset(ring[::-1] if flip else ring, J["inset"])

    half = 0.0125  # each frame's faces follow the fairing where they stand: it tapers fast toward its tail
    walls = {1: [], -1: []}  # where each frame crosses wall_z, for the longerons
    for s, depth in sorted([(s, J["depth"]) for s in J["frames"]] + [(pivot, J["pivot_frame_depth"])]):
        flip = signed_area([(v.x, v.z) for v in bi.fairing_ring(p, s, fairing_radius(p, s))]) < 0
        pts = section_at(s, flip)
        for run in arcs(pts, lambda q: q[1] > J["above"]):
            frames.append(frame_mesh("skel_frame", [(st, lerp_run(section_at(st, flip), run))
                                                    for st in (s - half, s + half)], depth))
        for side in (1, -1):
            x, z = ray_point(pts, (0.0, J["wall_z"]), 0.0 if side > 0 else math.pi)
            walls[side].append(bi.P(s, x, J["wall_z"]))
    for side, path in walls.items():
        frames.append(bar("skel_longeron", path, [Vector((-side, 0.0, 0.0))] * len(path), 0.022, 0.016))
    length, height = J["beam"]
    top = p["fin"]["sections"][-1][2]  # the fin's top, which the beam sits on
    span = 2 * (min(abs(path[[round(v.y + bi.S0, 3) for v in path].index(round(pivot, 3))].x) for path in walls.values())
                - 0.016)
    frames.append(box_mesh("skel_hinge_beam", bi.P(pivot, 0.0, top + height / 2 + 0.015), (span, length, height)))
    out = [tag(joined("skel_fin_skin", frames), "fin_skin", mat)]
    x0, x1, r = J["stub"]
    z = p["stabilator"]["sections"][0][2]
    stubs = [cylinder_x("skel_pivot", pivot, z, side * x0, side * x1, r) for side in (1, -1)]
    out.append(tag(joined("skel_stabilator_pivot", stubs), "stabilator", mat))
    return out


def build_stabilator(p, mats):
    """The stabilator's lattice, both halves, on the stabilator's hinge."""
    S, st = STABILATOR, p["stabilator"]
    sec, th = st["sections"], st["thickness"]
    spars = (S["front"], S["mid"], S["rear"])
    half = [rib("skel_rib_root", sec, "x", S["root"], S["le"], S["te"], th, 7),
            rib("skel_rib_tip", sec, "x", S["tip"], S["le"], S["te"], th, 7)]
    for f in (S["le"],) + spars:  # the leading-edge member first: the ribs' noses end on it
        half.append(spar("skel_spar", sec, "x", S["root"] + RIB["thickness"], S["tip"] - RIB["thickness"], f, th))
    for u in S["ribs"]:
        half += rib_pieces(sec, "x", u, (S["le"],) + spars, th)
    left = joined("skel_stabilator_L", half)
    right = bpy.data.objects.new("skel_stabilator_R", left.data.copy())
    bi.TARGET.objects.link(right)
    right.data.transform(bi.Matrix.Scale(-1, 4, (1, 0, 0)))
    right.data.flip_normals()
    return [tag(joined("skel_stabilator", [left, right]), "stabilator", mats["mechanical"])]


def build(p, mats):
    """The whole skeleton, into bi.TARGET."""
    wing_L = build_wing_L(p, mats)
    return (build_nose(p, mats) + build_root(p, mats) + build_aft(p, mats) + build_engine(p, mats)
            + build_intakes(p, mats) + wing_L + mirrored(wing_L) + build_fin(p, mats) + build_ventral(p, mats))


# The skin drawn from one side only, as the Ifrit draws its doors, flaps, nozzle, canopy frames and pylons: each has an
# inner face of its own or is closed, so the back-facing twin the Unity author gives every other skin triangle
# (IcarusAuthor.SkinFirst) would never show. Each is marked single_sided_skin for the Unity author, and budget.py counts
# no twins on it.
SINGLE_SIDED = ("gear_door_*_visible", "speed_brake_?_visible", "nozzle", "nozzle_petal_*_visible",
                "nozzle_seal_*_visible", "canopy_visible", "pylon_inner_*")
# Where a root rib (build_wing_L, fin_root) closes a box, the skin's own cap across that root goes: the wing boxes'
# root faces in the plane of their buried root, and the fin's bottom under the body's skin, found by a ray up from each
# downward face meeting that skin within reach. The stabilator keeps its root walls: the tail light's paint
# (lights.project_nav_paint) takes the nearest stabilator face, and its fairing's edge lies on the trailing edge, equally
# near two faces of different islands, so any face dropped there can turn that tie to the other island.
ROOT_CAPS = {"plane": 0.002, "reach": 0.5, "down": -0.3}


def open_root_caps(icarus):
    """Drop the skin caps across the wing boxes' and the fin's roots (ROOT_CAPS), and mark the
    single-sided skin (SINGLE_SIDED). Render meshes only, after the hulls, the UVs and the split (whose mass shares
    go by skin area), so nothing physical moves and every other island keeps its place in the atlas; returns a report
    line."""
    from parts import families

    lods = set(bpy.data.collections["LOD1"].objects) | set(bpy.data.collections["Colliders"].objects)
    meshes = [o for o in icarus.all_objects if o.type == "MESH" and o not in lods]
    body = bmesh.new()
    for o in meshes:
        if o.name.startswith(("skin_", "dorsal_cover")):
            me = o.data.copy()
            me.transform(o.matrix_world)
            body.from_mesh(me)
            bpy.data.meshes.remove(me)
    skin = BVHTree.FromBMesh(body)
    body.free()
    found = {"wing_skin_L": 0, "wing_skin_R": 0, "fin_skin": 0}
    owner = {o: next(iter(families(o) & set(found)), None) for o in meshes}
    roots = {name: min(abs((o.matrix_world @ v.co).x) for o in meshes if owner[o] == name for v in o.data.vertices)
             for name in ("wing_skin_L", "wing_skin_R")}
    up, near = Vector((0.0, 0.0, 1.0)), ROOT_CAPS["plane"]
    for o in meshes:
        name = owner[o]
        if name is None:
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        world = [o.matrix_world @ v.co for v in bm.verts]
        if name in roots:
            cap = lambda f: all(abs(abs(world[v.index].x) - roots[name]) < near for v in f.verts)
        else:
            def cap(f):
                normal = o.matrix_world.to_3x3() @ f.normal
                centre = sum((world[v.index] for v in f.verts), Vector()) / len(f.verts)
                return normal.z < ROOT_CAPS["down"] and skin.ray_cast(centre, up, ROOT_CAPS["reach"])[0] is not None
        gone = [f for f in bm.faces if cap(f)]
        found[name] += sum(len(f.verts) - 2 for f in gone)
        bmesh.ops.delete(bm, geom=gone, context="FACES")
        bm.to_mesh(o.data)
        bm.free()
    if not all(found.values()):
        raise ValueError("skeleton: no root cap found on %s" % [name for name, n in found.items() if not n])
    out = ["%s %d" % kv for kv in found.items()]
    marked = []
    for o in meshes:
        names = [m.name if m else "" for m in o.data.materials]
        if any(fnmatch.fnmatchcase(o.name, pattern) for pattern in SINGLE_SIDED) and "Icarus_Body" in names:
            o["single_sided_skin"] = True
            marked.append(o.name)
    return "skeleton: root caps dropped (%s); single-sided skin on %s" % (", ".join(sorted(out)), ", ".join(sorted(marked)))


# The meshes the skeleton is drawn in place of: the wing boxes' spar and rib plates, the fin's spar strip and the
# engine's tube. Their parts' colliders, masses and centre-of-mass markers are made from them before they go, and the
# checks still read them as those parts' envelopes; so they go last, after the checks, and the part stays as a node
# with no faces, marked drawn_by_skeleton (chunks.join_bare gives such a part no panels).
REPLACED = ("wing_spar_L", "wing_spar_R", "wing_spar_outer_L", "wing_spar_outer_R", "fin_spar", "engine_core",
            "engine_afterburner")


def retire_replaced(icarus):
    """Empty the meshes the skeleton is drawn in place of (REPLACED); returns a report line."""
    gone = []
    for o in icarus.all_objects:
        if o.name in REPLACED and o.type == "MESH":
            o.data.calc_loop_triangles()
            gone.append("%s %d" % (o.name, len(o.data.loop_triangles)))
            o.data.clear_geometry()
            o.data.materials.clear()
            o["drawn_by_skeleton"] = True
    return "skeleton: drawn in place of " + ", ".join(sorted(gone))


def insane(obj):
    """What in obj is no structure, as text: triangles narrower than SANE's min_altitude (slivers a cut leaves) and
    loose pieces smaller across than its min_piece (shards)."""
    out = []
    obj.data.calc_loop_triangles()
    co = [obj.matrix_world @ v.co for v in obj.data.vertices]
    for t in obj.data.loop_triangles:
        a, b, c = (co[i] for i in t.vertices)
        longest = max((b - a).length, (c - b).length, (a - c).length)
        if longest and (b - a).cross(c - a).length / longest < SANE["min_altitude"]:
            out.append("%s has a sliver triangle at %s" % (obj.name, tuple(round(v, 3) for v in (a + b + c) / 3)))
            break
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    seen = set()
    for start in bm.verts:
        if start in seen:
            continue
        island, todo = [], [start]
        seen.add(start)
        while todo:
            v = todo.pop()
            island.append(v.co.copy())
            for e in v.link_edges:
                w = e.other_vert(v)
                if w not in seen:
                    seen.add(w)
                    todo.append(w)
        lo = Vector([min(q[i] for q in island) for i in range(3)])
        hi = Vector([max(q[i] for q in island) for i in range(3)])
        if (hi - lo).length < SANE["min_piece"]:
            out.append("%s has a loose shard %.3f m across at %s" % (obj.name, (hi - lo).length,
                                                                    tuple(round(v, 3) for v in (lo + hi) / 2)))
            break
    bm.free()
    return out


def check(icarus):
    """Each piece inside the skin it hangs under, no sliver or loose shard in it, and every place within its cap;
    returns a report line."""
    import budget
    from checks import tree

    def sheet(obj):
        """obj's faces less its exterior hardware (an antenna's base buried in the body)."""
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        hardware = bm.faces.layers.int.get("exterior_hardware")
        if hardware is not None:
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[hardware]], context="FACES")
        bm.transform(obj.matrix_world)
        t = BVHTree.FromBMesh(bm)
        bm.free()
        return t

    pieces = [o for o in icarus.all_objects if o.type == "MESH" and "skeleton_owner" in o]
    skins = [o for o in icarus.all_objects if o.type == "MESH" and (o.get("role") in ("skin", "canopy")
                                                                     or o.name.startswith(("wing_skin_", "fin_skin")))]
    surfaces = {o.name: o for o in icarus.all_objects if o.type == "MESH" and o.name.endswith("_visible")}
    trees = {o.name: sheet(o) for o in skins}
    clashes = []
    for piece in pieces:
        own = tree(piece)
        clashes += ["%s cuts %s" % (piece.name, s.name) for s in skins if own.overlap(trees[s.name])]
        shell = surfaces.get(piece["skeleton_owner"] + "_visible")
        if shell is not None and own.overlap(tree(shell)):
            clashes.append("%s cuts %s" % (piece.name, shell.name))
        clashes += insane(piece)
    over = budget.over_caps(icarus, BUDGET)
    if clashes or over:
        raise ValueError("skeleton: " + "; ".join(clashes + over))
    return "skeleton: %d pieces, %s" % (len(pieces), ", ".join(
        "%s %d" % (name, budget.measure(icarus, item)) for name, item in BUDGET.items()))
