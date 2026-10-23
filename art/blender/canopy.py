"""The canopy: a fixed windscreen, the hood hinged along its left sill, their frames, and the design eye point the
cockpit is fitted to.

The glass is lofted from PROFILE and kept where it stands above the fuselage skin, in two layers: outer panes on
fighter1_canopy, which the cockpit view hides, and inner panes GLASS_GAP inside them on fighter1_canopy_int, which the
cockpit view draws and the game cracks. The hood's frame (sill rails and three bows) is the canopy part's mesh, on the
skin. The windscreen's arch, posts and base rails, and the fixed sill beside the hood, merge into the forward skin
panels, split at x = 0. Every frame straddles the glass, placed by raycasts against the panes and the uncut fuselage.

The hood turns about its left sill line, which rises aft, so the joint between windscreen and hood lies in the plane
square to that hinge: each point of the opening hood stays in its own such plane, and none swings forward into the
windscreen.

    build(p, mats)                       # from build_icarus._build
    blender --background --factory-startup --python art/blender/canopy.py -- <out_dir>   # build and render the review
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_icarus as bi  # noqa: E402
import gear  # noqa: E402
import materials  # noqa: E402
from solids import X, Y, Z, Solids, bvh, hit, must  # noqa: E402

CANOPY = {"windscreen_end_s": 2.95, "open_deg": 75}
# Shut, the glass and its frames run on under the skin, the spine and the windscreen's edge: the hood seats in
# them. Opening, it may only lift out of that seat, and must be clear of the fuselage from SEAT_RELEASE_DEG on.
SEAT_RELEASE_DEG = 40
FUSELAGE = ("skin_forward_L", "skin_forward_R", "dorsal_cover", "windscreen", "windscreen_inner")
# Sections (s, half width, z top, z bottom): a half ellipse over a 2 cm lip. Round the eye the widest point sits on the
# skin, so the glass walls meet the fuselage where they are steepest; aft of it the hood keeps its old seam, the lip
# standing about 4 cm proud as it tapers into the spine.
PROFILE = [
    (2.32, 0.300, 0.640, 0.456),
    (2.70, 0.340, 0.880, 0.470),
    (3.00, 0.375, 1.045, 0.478),
    (3.35, 0.405, 1.140, 0.498),
    (4.00, 0.425, 1.145, 0.547),
    (4.40, 0.425, 1.128, 0.586),
    (4.70, 0.390, 1.100, 0.700),
    (5.10, 0.310, 1.035, 0.820),
]
WINDSCREEN_ROWS, HOOD_ROWS, RING = 4, 9, 40  # loft stations ahead of and behind windscreen_end_s; points per section
GLASS_GAP = 0.004  # the inner panes sit this far inside the outer ones
FRAME_HALF = 0.006  # frames straddle the glass by this much either side
HINGE_CLEAR = 0.035  # the hinge line stands this far outboard of the left seam, at the fixed sill's outer edge
SKIN = "Icarus_Body"
# The design eye, (s, x, z) as in PARAMS: where the stock seat's pilot looks from. tools/export_blockout.py writes it to
# blockout.json, and the Unity author fits the cockpit to it.
EYE = (4.365, 0.0, 0.885)
# Cockpit rule 27, from the eye to the inner glass and the cockpit cell's sill: (low, high) metres.
EYE_BANDS = {"overhead": (0.23, 0.36), "side": (0.35, 0.46), "sill": (0.27, 0.35)}
OVER_NOSE_SLOPE = 0.2876  # the glare shield stays under this 16 degree line down from the eye
# Object names the other modules and the Unity author build against.
FRAME = "canopy_visible"  # the hood's frame, under the "canopy" hinge
GLASS_OUTER, GLASS_INNER = "canopy_glass_outer", "canopy_glass_inner"  # the hood's panes, under the hinge too
WINDSCREEN, WINDSCREEN_INNER = "windscreen", "windscreen_inner"  # the windscreen's panes, the inner one its child
# part name -> (parent, dry mass kg); parts.full_tree adds these to its own
TREE = {
    "windscreen": ("cockpit_cell", 0),
}
# Triangles per component: target and cap (budget.py sums them). WINDSCREEN counts the outer pane by its exact name,
# not as a prefix that would take windscreen_inner and the cockpit's windscreen_frame_inner too; GLASS_CAP holds each
# layer of both panes in check(). The windscreen frame and the fixed sill count in the forward skin panels they merge
# into; build() holds them to DETAIL_CAPS.
BUDGET = {
    "hood_frame": {"target": 420, "cap": 480, "objects": (FRAME,)},
    "hood_glass": {"target": 600, "cap": 1500, "objects": (GLASS_OUTER,)},
    "windscreen_glass": {"target": 400, "cap": 1100, "exact": (WINDSCREEN,)},
    "hood_glass_inner": {"target": 600, "cap": 1500, "objects": (GLASS_INNER,), "cockpit": True},
}
GLASS_CAP = 2050
DETAIL_CAPS = {"windscreen_frame": 480, "fixed_sill": 400}
SILL_ROWS, BOW_COLUMNS, ARCH_COLUMNS = 10, 12, 9
# Review close-ups (review_sheet.py): name -> (camera, target), Blender axes.
CLOSEUPS = {
    "canopy_34": (Vector((2.4, -7.6, 2.3)), Vector((0.0, -4.3, 0.95))),
    "canopy_sill_left": (Vector((1.6, -5.2, 1.4)), Vector((0.35, -4.2, 0.75))),
}


def build(p, mats):
    outer_mat = materials.material("fighter1_canopy", (0.10, 0.16, 0.22, 0.45), 0.0, 0.05)
    inner_mat = materials.material("fighter1_canopy_int", (0.12, 0.18, 0.24, 0.25), 0.0, 0.05)
    fuselage = bpy.data.objects["fuselage"]
    skin = bvh([fuselage])
    solid = build_canopy(p, outer_mat)
    cut = cut_edge(fuselage, solid)
    sheet = above_skin(solid, skin)
    glass = bvh([solid])  # the frames are placed on the whole shape, which runs on under the skin
    bpy.data.objects.remove(solid, do_unlink=True)

    s0, s1 = CANOPY["windscreen_end_s"], PROFILE[-1][0]
    hood, rails = Solids(), {}
    for side in (1, -1):
        rails[side] = sill_rail(hood, glass, skin, bi.spaced(s0, s1 - 0.004, 8), side)
    a, u = hinge_line(rails[1])
    for i, bow in enumerate(((joint(a, u, 0.003), joint(a, u, 0.035)), (station(4.07), station(4.13)),
                             (station(5.05), station(s1 - 0.004)))):
        rows = []
        for f in bow:
            left, right = seam_psi(glass, skin, f, 1), seam_psi(glass, skin, f, -1)
            r = glass_at(glass, f, left)[2]
            rows.append((f, bi.spaced(left + 0.004 / r, right - 0.004 / r, BOW_COLUMNS)))
        glass_band(hood, glass, rows, SKIN, extend=0.010 if i == 2 else None)  # the aft bow overhangs the end cap
    if hood.tris() > BUDGET["hood_frame"]["cap"]:
        raise ValueError("canopy: hood frame is %d triangles, over %d" % (hood.tris(), BUDGET["hood_frame"]["cap"]))

    windscreen = split(sheet, WINDSCREEN, a, u, ahead=True)
    hood_glass = split(sheet, GLASS_OUTER, a, u, ahead=False)
    bpy.data.objects.remove(sheet, do_unlink=True)
    windscreen_inner = inner_pane(WINDSCREEN_INNER, windscreen, inner_mat)
    hood_inner = inner_pane(GLASS_INNER, hood_glass, inner_mat)
    # Glass gets no collider or LOD1 hull; the windscreen, a part in TREE, takes its role from parts.organise.
    for obj, role in ((hood_glass, "visual"), (windscreen_inner, "cockpit_view"), (hood_inner, "cockpit_view")):
        obj["role"] = role
        obj["mass_kg"] = 0
    import parts  # imports this module back

    parts.recentre(windscreen)  # organise recentres its parts: done here, that moves nothing, so the child stays put
    windscreen_inner.parent = windscreen
    windscreen_inner.matrix_parent_inverse = windscreen.matrix_world.inverted()

    made = bi.hinged("canopy", mesh_object("canopy_frame", hood), gear.frame_on(a, u))
    bpy.context.view_layer.update()  # the frame's matrix_local is stale until the new parenting is evaluated
    # opened, the hood swings up and over to the left: its right edge rises and moves toward the hinge
    made[0]["travel_deg"] = gear.opening_travel(made[0], CANOPY["open_deg"], lambda pts: max(q.z for q in pts) + min(q.x for q in pts))
    for pane in (hood_glass, hood_inner):
        pane.data.transform(made[0].matrix_world.inverted())
        pane.parent = made[0]

    tris = {"windscreen_frame": 0, "fixed_sill": 0}
    for side, sd in ((1, "L"), (-1, "R")):
        frame, sill = windscreen_frame(glass, skin, a, u, side), Solids()
        fixed_sill(sill, glass, skin, [(s, side * x) for s, x in cut if side * x > 0], s0, s1 - 0.004, side)
        tris["windscreen_frame"] += frame.tris()
        tris["fixed_sill"] += sill.tris()
        made += [detail("windscreen_frame_" + sd, frame, "skin_forward_" + sd), detail("canopy_sill_" + sd, sill, "skin_forward_" + sd)]
    over = ["%s %d > %d" % (k, n, DETAIL_CAPS[k]) for k, n in tris.items() if n > DETAIL_CAPS[k]]
    if over:
        raise ValueError("canopy: skin detail over budget: " + "; ".join(over))
    print("canopy: hood frame %d, windscreen frame %d, fixed sill %d triangles" % (hood.tris(), tris["windscreen_frame"], tris["fixed_sill"]))
    return made + [hood_glass, hood_inner, windscreen, windscreen_inner]


def check(icarus):
    """The glass within its caps, the eye geometry in Cockpit rule 27's bands, and the hood opening clear of the
    windscreen."""
    count = lambda name: sum(len(f.vertices) - 2 for f in bpy.data.objects[name].data.polygons)
    import budget

    over = budget.over_caps(icarus, BUDGET)
    for layer, names in (("outer", (GLASS_OUTER, WINDSCREEN)), ("inner", (GLASS_INNER, WINDSCREEN_INNER))):
        if sum(map(count, names)) > GLASS_CAP:
            over.append("%s glass %d > %d" % (layer, sum(map(count, names)), GLASS_CAP))
    if over:
        raise ValueError("canopy over budget: " + "; ".join(over))
    eye = eye_geometry(EYE)
    misses = ["%s %.3f outside %.2f to %.2f" % (k, eye[k], *band) for k, band in EYE_BANDS.items()
              if not band[0] <= eye[k] <= band[1]]
    if misses:
        raise ValueError("canopy: eye at %s: %s" % (EYE, "; ".join(misses)))
    clashes = opening_clashes(bpy.data.objects["canopy"])
    if clashes:
        raise ValueError("canopy: the opening hood meets the windscreen at " + "; ".join(clashes))
    seat, gap = opening_sweep(bpy.data.objects["canopy"])
    risen = [k for k in range(1, len(seat)) if seat[k][1] > seat[k - 1][1]]
    caught = [(a, n) for a, n in seat if a >= SEAT_RELEASE_DEG - 1e-6 and n]
    if risen or caught:
        raise ValueError("canopy: the opening hood does not lift clear of the fuselage: face pairs in contact by angle "
                         + ", ".join("%.1f deg %d" % s for s in seat))
    print("canopy: the opening hood lifts out of its seat (%d face pairs shut, %s) and clears the fuselage from %.0f deg, "
          "least gap %.4f m on to full travel" % (seat[0][1], ", ".join("%.1f deg %d" % s for s in seat[1:] if s[1]),
                                                   SEAT_RELEASE_DEG, gap))
    at = bi.P(*EYE)
    faces = [(o.matrix_world @ f.center - at).dot(o.matrix_world.to_3x3() @ f.normal) < 0
             for o in (bpy.data.objects[GLASS_INNER], bpy.data.objects[WINDSCREEN_INNER]) for f in o.data.polygons]
    print("canopy: eye (s %.3f, z %.3f) overhead %.3f, side %.3f, sill %.3f below; over the nose %.1f deg; "
          "hood opens %.0f deg clear of the windscreen; %d of %d inner glass faces face the eye"
          % (EYE[0], EYE[2], eye["overhead"], eye["side"], eye["sill"], eye["over_nose_deg"],
             bpy.data.objects["canopy"]["travel_deg"], sum(faces), len(faces)))


# --- the glass -----------------------------------------------------------------------------------------------------

def section(s, hw, top, bot):
    """One section, RING points from the left side up over the crown: a half ellipse over the lip."""
    zmid = bot + 0.02
    points = []
    for k in range(RING):
        a = 2 * math.pi * k / RING
        c, sn = math.cos(a), math.sin(a)
        e, h = (2.0, top - zmid) if sn >= 0 else (4.0, zmid - bot)
        points.append(bi.P(s, hw * bi.superellipse(c, e), zmid + h * bi.superellipse(sn, e)))
    return points


def build_canopy(p, mat):
    """The closed canopy shape, faces outward; parts.organise cuts the cockpit opening with it. p is unused: the shape
    is PROFILE."""
    end = CANOPY["windscreen_end_s"]
    stations = bi.spaced(PROFILE[0][0], end, WINDSCREEN_ROWS) + bi.spaced(end, PROFILE[-1][0], HOOD_ROWS)[1:]
    obj = bi.loft("canopy", [section(*row) for row in bi.resample(PROFILE, stations)], cap_back=True, cap_front=True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    return bi.finish(obj, mat)


def centre_z(s):
    """Height of the canopy's centre line: the widest point of its section."""
    s = min(max(s, PROFILE[0][0]), PROFILE[-1][0])
    return bi.resample(PROFILE, [s])[0][3] + 0.02


def mesh_object(name, solids):
    obj = bpy.data.objects.new(name, solids.mesh(name))
    bi.TARGET.objects.link(obj)
    return obj


def detail(name, solids, part):
    """Skin detail that parts.merge_details joins into part's mesh."""
    obj = mesh_object(name, solids)
    obj["merge_into"] = part
    return obj


def keep_faces(name, source, keep, cut=None):
    """A copy of source holding the faces keep(face) accepts, after an optional bisect by cut = (point, normal)."""
    me = source.data.copy()
    bm = bmesh.new()
    bm.from_mesh(me)
    if cut:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=cut[0], plane_no=cut[1])
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep(f)], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.name = name
    obj = bpy.data.objects.new(name, me)
    bi.TARGET.objects.link(obj)
    return obj


def above_skin(solid, skin):
    """The solid's faces with a corner above the fuselage skin (the end caps stay whole)."""
    above = lambda v: hit(skin, v.co, Z) is None
    return keep_faces("canopy_sheet", solid, lambda f: len(f.verts) > 4 or any(above(v) for v in f.verts))


def split(sheet, name, a, u, ahead):
    """The windscreen (ahead) or the hood's pane: the sheet cut by the joint plane through a, square to the hinge u."""
    side = -1 if ahead else 1
    obj = keep_faces(name, sheet, lambda f: side * (f.calc_center_median() - a).dot(u) > 0, (a, u))
    unroll_uvs(obj)
    return obj


def inner_pane(name, outer, mat):
    """outer's twin GLASS_GAP inside it, facing in, on mat."""
    me = outer.data.copy()
    me.name = name
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    moved = [v.co - v.normal * GLASS_GAP for v in bm.verts]
    for v, co in zip(bm.verts, moved):
        v.co = co
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.materials.clear()
    me.materials.append(mat)
    obj = bpy.data.objects.new(name, me)
    bi.TARGET.objects.link(obj)
    return obj


def unroll_uvs(obj):
    """UVs inside the clear window of the stock canopy texture both glass materials sample (fighter1_canopy_int_b,
    the Revoker hood's outline, clear inside and an opaque tan border outside, set to repeat): u round the section
    with the crown at 0.5, v along the length from 0.30 (the outline's narrow nose lies below) to 0.95. UVs run past
    0..1 sampled the border, which showed through the glass as a tan Y from the cockpit."""
    me = obj.data
    layer = me.uv_layers.new(name="UVMap")
    s0, s1 = PROFILE[0][0], PROFILE[-1][0]
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        s = co.y + bi.S0
        psi = math.atan2(co.x, co.z - centre_z(s))
        layer.data[loop.index].uv = (0.5 + 0.4 * max(-1.0, min(1.0, psi / (math.pi / 2))),
                                     0.30 + 0.65 * min(max((s - s0) / (s1 - s0), 0.0), 1.0))


def cut_edge(fuselage, solid):
    """(s, x) of the edge parts.organise will cut in the fuselage skin with the canopy solid, above the wing."""
    import parts  # imports this module back

    cut = fuselage.copy()
    cut.data = fuselage.data.copy()
    bi.TARGET.objects.link(cut)
    parts.drop_inside(cut, solid)
    bm = bmesh.new()
    bm.from_mesh(cut.data)
    bm.transform(cut.matrix_world)
    points = [(v.co.y + bi.S0, v.co.x) for e in bm.edges if e.is_boundary for v in e.verts if v.co.z > 0.3]
    bm.free()
    data = cut.data
    bpy.data.objects.remove(cut, do_unlink=True)
    bpy.data.meshes.remove(data)
    return points


# --- frames --------------------------------------------------------------------------------------------------------

def station(s):
    """Ray frame of the station plane at s: origin on the centre line, up, and the plane's normal."""
    return bi.P(s, 0.0, centre_z(s)), Z, Y


def hinge_line(seam):
    """The hood's hinge: a point and axis along the left sill, HINGE_CLEAR outboard of the left seam's widest point and
    level with the seam where it runs lowest, held square to x (the hood narrows aft) so the joint is symmetric. The
    seam is lowest at the joint and rises ever faster aft, so the line through its joint end with the shallowest
    slope that stays under the rest is the one that hugs it. Every point of the hood then sits inboard of the hinge and
    no lower than it but for the seat under the skin, and lifts out as the hood opens. The chord from end to end ran
    7 cm above and 5 cm inboard of the seam mid-hood and swung the lower left edge down and in, through the fixed sill
    and the skin, all the way open."""
    first = seam[0]
    slope = min((q.z - first.z) / (q.y - first.y) for q in seam[1:])
    a = Vector((max(q.x for q in seam) + HINGE_CLEAR, first.y, first.z))
    return a, Vector((0.0, 1.0, slope)).normalized()


def joint(a, u, offset):
    """Ray frame of the plane square to the hinge axis u through a (the joint), moved offset along u."""
    up = (Z - u * u.dot(Z)).normalized()
    on_line = Vector((0.0, a.y, a.z))
    origin = on_line + up * ((centre_z(a.y + bi.S0) - a.z) / up.z)
    return origin + u * offset, up, u


def ray(frame, psi, side=1):
    origin, up, _ = frame
    return origin, X * side * math.sin(psi) + up * math.cos(psi)


def glass_at(glass, frame, psi):
    """Glass point, outward normal in the frame's plane, and distance from the origin, at angle psi from the crown
    (+ toward the left)."""
    origin, d = ray(frame, psi)
    point, n = must(hit(glass, origin, d), "glass at %s, %.2f rad" % (tuple(round(c, 3) for c in origin), psi))
    n = -n  # hit() faces the normal back toward the origin
    n -= frame[2] * n.dot(frame[2])
    return point, n.normalized(), (point - origin).length


def seam_psi(glass, skin, frame, side):
    """Angle from the crown (signed by side) where the glass goes under the fuselage skin, as seen from outside: a ray
    in from that direction toward the origin meets the skin before the glass."""
    def under(psi):
        origin, d = ray(frame, psi, side)
        on_glass, on_skin = hit(glass, origin + d * 2.0, -d, 2.0), hit(skin, origin + d * 2.0, -d, 2.0)
        if on_skin is None:
            return False
        return on_glass is None or (on_skin[0] - origin).length > (on_glass[0] - origin).length + 1e-4
    lo, hi = 0.0, next(a for a in (0.6 * math.pi, 0.7 * math.pi, 0.8 * math.pi, 0.9 * math.pi) if under(a))
    if under(lo):
        raise ValueError("canopy crown under the skin at %s" % (tuple(round(c, 3) for c in frame[0]),))
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        lo, hi = (lo, mid) if under(mid) else (mid, hi)
    return side * 0.5 * (lo + hi)


def glass_band(out, glass, rows, mat, extend=None, taper_end=False):
    """A frame band straddling the glass: rows of (frame, [psi...]); extend shifts the last row aft (s) to overhang a
    cap, and taper_end thins the last row to a sliver on the glass, so the band dies out with no end face to catch
    light."""
    outer, inner = [], []
    for i, (frame, psis) in enumerate(rows):
        o_row, i_row = [], []
        last = i == len(rows) - 1
        for psi in psis:
            point, n, _ = glass_at(glass, frame, psi)
            if extend and last:
                point = point + Y * extend
            half = 0.0005 if taper_end and last else FRAME_HALF
            o_row.append(point + n * half)
            i_row.append(point - n * half)
        outer.append(o_row)
        inner.append(i_row)
    out.slab(outer, inner, mat)


def smooth(values, passes=2):
    v = list(values)
    for _ in range(passes):
        v = [v[0]] + [(a + 2 * b + c) / 4 for a, b, c in zip(v, v[1:], v[2:])] + [v[-1]]
    return v


def sill_rail(out, glass, skin, stations, side):
    """The hood's sill rail on one side, from its seam up the glass; returns the seam point at each station."""
    frames = [station(s) for s in stations]
    psis = smooth([seam_psi(glass, skin, f, side) for f in frames])
    rows, seam = [], []
    for f, psi in zip(frames, psis):
        point, _, r = glass_at(glass, f, psi)
        seam.append(point)
        rows.append((f, [psi + side * 0.004 / r, psi - side * 0.0175 / r, psi - side * 0.035 / r]))
    glass_band(out, glass, rows, SKIN)
    return seam


def windscreen_frame(glass, skin, a, u, side):
    """One half of the windscreen's frame: the arch from the seam to the crown just ahead of the joint, the post at 40
    degrees and the base rail along the seam, both running back under the arch."""
    out = Solids()
    rows = []
    for f in (joint(a, u, -0.035), joint(a, u, -0.003)):
        seam = seam_psi(glass, skin, f, side)
        r = glass_at(glass, f, seam)[2]
        rows.append((f, bi.spaced(seam + side * 0.004 / r, 0.0, ARCH_COLUMNS)))
    glass_band(out, glass, rows, SKIN)
    psi = side * math.radians(40)
    under_arch = glass_at(glass, joint(a, u, -0.02), psi)[0].y + bi.S0
    start = next(s for s in bi.spaced(PROFILE[0][0], under_arch, 40) if hit(glass, *ray(station(s), psi)) is not None) + 0.03
    rows = []
    for s in bi.spaced(under_arch, start, 5):  # aft to front: the post thins out onto the glass at its front
        r = glass_at(glass, station(s), psi)[2]
        rows.append((station(s), [psi - 0.015 / r, psi + 0.015 / r]))
    glass_band(out, glass, rows, SKIN, taper_end=True)
    base = [station(s) for s in bi.spaced(PROFILE[0][0] + 0.04, CANOPY["windscreen_end_s"] - 0.01, 6)]
    rows = []
    for f, psi in zip(base, smooth([seam_psi(glass, skin, f, side) for f in base])):
        r = glass_at(glass, f, psi)[2]
        rows.append((f, [psi + side * 0.004 / r, psi - side * 0.025 / r]))
    glass_band(out, glass, rows, SKIN)
    return out


def fixed_sill(out, glass, skin, cut, s0, s1, side):
    """The fixed sill on the fuselage, 8 mm proud, across the skin's cut edge beside the hood. The cut steps ring by
    ring (whole skin faces are dropped), so the sill's outer edge lies past the outermost cut point within a skin ring
    either way, smoothed, and its inner edge clears the hood's sill rail or, where the cut leaves skin inside the hood's
    wall, covers it. Inboard of the skin the top runs on the skin's tangent line, which a convex skin stays under, and a
    3 cm flange drops from the inner edge so nothing stepped shows with the hood open. cut holds (s, distance out from
    the centreline) on this side."""
    ss = sorted({round(s, 3) for s, _ in cut if s0 - 0.3 < s < s1 + 0.3})
    ring = max(b - a for a, b in zip(ss, ss[1:]))
    samples = bi.spaced(s0, s1, 3 * SILL_ROWS - 2)
    outer = smooth([max(u for t, u in cut if abs(t - s) <= ring) for s in samples], 3)[::3]
    rows = samples[::3]
    inner = []
    for s in rows:
        f = station(s)
        wall = side * glass_at(glass, f, seam_psi(glass, skin, f, side))[0].x
        inside = [u for t, u in cut if abs(t - s) <= ring and wall - 0.05 < u]
        inner.append(min([wall + 0.010] + [u - 0.004 for u in inside]))  # the rail stands 6 mm off the glass
    top, low = [], []
    for s, u_edge, u_in in zip(rows, outer, smooth(inner, 3)):
        zc = centre_z(s)
        u_out = max(u_edge + 0.004, u_in + 0.012)
        sk = [must(hit(skin, bi.P(s, side * u, zc + 0.5), -Z, 0.75), "the sill at s %.2f" % s)[0]
              for u in (u_out, u_out + 0.012)]
        slope = (sk[1].z - sk[0].z) / 0.012
        n = Vector((-side * slope, 0.0, 1.0)).normalized()
        on_line = lambda u: bi.P(s, side * u, sk[0].z + slope * (u - u_out))
        lip, mid = on_line(u_in), on_line(0.5 * (u_in + u_out))
        step = X * side * 0.006
        top.append([lip - Z * 0.03, lip + Z * 0.008, mid + n * 0.008] + [q + n * 0.008 for q in sk])
        low.append([lip - Z * 0.03 + step, lip - Z * 0.003 + step, mid - n * 0.003] + [q - n * 0.003 for q in sk])
    out.slab(top, low, SKIN)


# --- measurement ---------------------------------------------------------------------------------------------------

def eye_geometry(eye_sxz):
    """Cockpit rule 27's distances from an eye (s, x, z): to the inner glass overhead and either side, and the
    cockpit cell's sill top below it; and the steepest look down over the nose the skin allows, in degrees."""
    O = bpy.data.objects
    eye = bi.P(*eye_sxz)
    glass = bvh([O[GLASS_INNER], O[WINDSCREEN_INNER]])
    reach = lambda d: must(hit(glass, eye, d), "inner glass from the eye")[0] - eye
    cell = O["cockpit_cell"]
    sill = max(q.z for q in (cell.matrix_world @ v.co for v in cell.data.vertices)
               if abs(q.y - eye.y) < 0.1 and abs(q.x) > 0.2 and q.z < eye.z)
    skin = bvh([o for o in bi.TARGET.all_objects if o.type == "MESH" and o.get("role") == "skin"])
    over = next(d / 10 for d in range(400) if hit(skin, eye, Vector((0, -math.cos(math.radians(d / 10)), -math.sin(math.radians(d / 10)))), 20) is not None)
    return {"overhead": reach(Z).length, "side": min(reach(X).length, reach(-X).length), "sill": eye.z - sill,
            "over_nose_deg": over}


def opening_clashes(hinge, steps=8):
    """Hinge angles at which the hood (frame and panes) overlaps anything of the forward skin or windscreen ahead of
    the joint plane, which runs through the hinge's origin square to its axis."""
    O = bpy.data.objects
    a, u = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
    bm = bmesh.new()
    for name in ("skin_forward_L", "skin_forward_R", WINDSCREEN):
        me = O[name].data.copy()
        me.transform(O[name].matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if any((v.co - a).dot(u) > -0.001 for v in f.verts)], context="FACES")
    from mathutils.bvhtree import BVHTree

    fixed = BVHTree.FromBMesh(bm)
    bm.faces.ensure_lookup_table()
    centres = [f.calc_center_median() for f in bm.faces]
    bm.free()
    hood = [o for o in hinge.children if o.type == "MESH"]
    clashes = []
    for k in range(1, steps + 1):
        angle = hinge["travel_deg"] * k / steps
        turn = Matrix.Translation(a) @ Matrix.Rotation(math.radians(angle), 4, u) @ Matrix.Translation(-a)
        moved = bmesh.new()
        for o in hood:
            me = o.data.copy()
            me.transform(turn @ o.matrix_world)
            moved.from_mesh(me)
            bpy.data.meshes.remove(me)
        pairs = fixed.overlap(BVHTree.FromBMesh(moved))
        if pairs:
            at = centres[pairs[0][0]]
            clashes.append("%.0f deg at (s %.3f, x %.3f, z %.3f)" % (angle, at.y + bi.S0, at.x, at.z))
        moved.free()
    return clashes


def opening_sweep(hinge, step_deg=2.5):
    """The hood (every mesh on the hinge) through its travel against the fuselage it seats in (FUSELAGE): face pairs
    in contact at each angle, and the least distance from a hood vertex to the fuselage from SEAT_RELEASE_DEG on."""
    from mathutils.bvhtree import BVHTree

    O = bpy.data.objects
    a, u = hinge.matrix_world.translation, hinge.matrix_world.col[0].xyz.normalized()
    fixed = bvh([O[n] for n in FUSELAGE])
    hood = [o for o in hinge.children if o.type == "MESH"]
    steps = int(math.ceil(abs(hinge["travel_deg"]) / step_deg))
    seat, gap = [], math.inf
    for k in range(steps + 1):
        angle = hinge["travel_deg"] * k / steps
        turn = Matrix.Translation(a) @ Matrix.Rotation(math.radians(angle), 4, u) @ Matrix.Translation(-a)
        verts, polys = [], []
        for o in hood:
            base = len(verts)
            verts += [turn @ o.matrix_world @ v.co for v in o.data.vertices]
            polys += [tuple(base + i for i in f.vertices) for f in o.data.polygons]
        seat.append((abs(angle), len(BVHTree.FromPolygons(verts, polys).overlap(fixed))))
        if abs(angle) >= SEAT_RELEASE_DEG - 1e-6:
            gap = min(gap, min(fixed.find_nearest(v)[3] for v in verts))
    return seat, gap


# --- review renders ------------------------------------------------------------------------------------------------

def render_review(out_dir):
    """The canopy review set: closed and open three-quarter views, the frame close-up, the glass wireframe, the side
    section through the eye with the sill and the over-nose line, and the view from the eye through the inner glass."""
    import review_sheet

    os.makedirs(out_dir, exist_ok=True)
    scene = review_sheet.setup_scene()
    O = bpy.data.objects
    hinge = O["canopy"]
    shut = hinge.matrix_basis.copy()

    def shoot(name, loc, target, lens=50, ortho=0.0, clip=0.01, res=(1600, 1000)):
        cam = review_sheet.camera("CanopyCam_" + name)
        cam.data.type = "ORTHO" if ortho else "PERSP"
        cam.data.ortho_scale = ortho or cam.data.ortho_scale
        cam.data.lens = lens
        cam.data.clip_start = clip
        cam.data.clip_end = 200
        cam.location = loc
        cam.rotation_euler = (target - loc).to_track_quat("-Z", "Y").to_euler()
        review_sheet.render_view(scene, cam, os.path.join(out_dir, name + ".png"), res)

    marks = []

    def mark(name, points, radius, colour):
        mat = materials.material("CanopyReview_" + name, colour)
        for i, q in enumerate(points):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=q, segments=12, ring_count=6)
            marks.append(bpy.context.object)
            marks[-1].data.materials.append(mat)

    eye = bi.P(*EYE)
    mark("eye", [eye], 0.03, (1.0, 0.25, 0.1, 1.0))
    mark("over_nose", [eye + Vector((0, -d, -d * OVER_NOSE_SLOPE)) for d in bi.spaced(0.5, 2.4, 32)], 0.006, (1.0, 0.8, 0.1, 1.0))
    shoot("closed_34", Vector((2.6, -8.2, 2.5)), Vector((0.0, -4.2, 0.85)))
    shoot("frame_closeup", *CLOSEUPS["canopy_sill_left"])
    shoot("side", Vector((6.0, -4.1, 0.85)), Vector((0.0, -4.1, 0.85)), ortho=3.4)
    shoot("front", Vector((0.0, -12.0, 0.8)), Vector((0.0, -4.0, 0.8)), ortho=1.7)
    scene.world.color = (0.8, 0.8, 0.8)  # the section and the wireframe read against a light ground
    scene.render.film_transparent = False
    shoot("section", Vector((5.0, -4.1, 0.75)), Vector((0.0, -4.1, 0.75)), ortho=3.4, clip=5.0)
    scene.render.film_transparent = True
    # The cockpit view hides the outer panes and the internals round the pilot, which the cockpit interior covers.
    exterior = [O[n] for n in (GLASS_OUTER, WINDSCREEN)] + [o for o in bi.TARGET.all_objects if o.type == "MESH"
                                                            and o.get("role") not in ("skin", "canopy", "visual", "cockpit_view")]
    for o in exterior + marks[:1]:
        o.hide_render = True
    shoot("eye_view", eye, eye + Vector((0, -1.0, -0.12)), lens=23.5)
    for o in exterior + marks[:1]:
        o.hide_render = False
    glass = [O[n] for n in (GLASS_OUTER, WINDSCREEN)]
    hidden = [o for o in bi.TARGET.all_objects if o.type == "MESH" and o not in glass] + marks
    for o in hidden:
        o.hide_render = True
    for o in glass:
        o.modifiers.new("wire", "WIREFRAME").thickness = 0.004
    scene.render.film_transparent = False
    shoot("glass_wire", Vector((2.6, -8.2, 2.5)), Vector((0.0, -4.2, 0.85)))
    scene.render.film_transparent = True
    for o in glass:
        o.modifiers.remove(o.modifiers["wire"])
    for o in hidden:
        o.hide_render = False
    hinge.matrix_basis = shut @ Matrix.Rotation(math.radians(hinge["travel_deg"]), 4, "X")
    shoot("open_34", Vector((-2.8, -7.8, 2.6)), Vector((0.1, -4.2, 0.9)))
    shoot("open_front", Vector((0.0, -12.0, 1.0)), Vector((0.0, -4.0, 1.0)), ortho=2.4)
    hinge.matrix_basis = shut
    for o in marks:
        bpy.data.objects.remove(o, do_unlink=True)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = os.path.abspath(args[0] if args else ".cache/review/canopy")
    cube = bpy.data.objects.get("Cube")  # the factory-startup scene's default cube would sit in every render
    if cube is not None:
        bpy.data.objects.remove(cube, do_unlink=True)
    print("icarus:", {k: v for k, v in bi.build_cached().items() if k != "references"})
    render_review(out)
    print("canopy renders:", out)
