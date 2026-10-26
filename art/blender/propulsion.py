"""Intakes and the iris nozzle: the shock cones with their bleed bands, the ducts to the compressor face, the nozzle
shroud with its afterburner, its hinged petals and seals, and the actuation that drives them.

The nozzle is a fixed shroud, then a ring of hinged petals with seals between them. Each petal hangs on its own hinge
empty (local X along the hinge) under one gimbal empty, so the plugin can open the iris with afterburner and deflect
it for thrust vectoring. The built pose is dry thrust: petals angled inward.

The ducts and the tailpipe end on opaque backplates (Icarus_Duct): the stock jet_mechanical trim is alpha-clipped,
and a trim face broad enough to reach its lightening holes (trims.clipped) shows the airframe through.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import build_icarus as bi

# Triangles per component: target and cap (budget.py sums them). 500 of each intake's cap went to the gear doors.
BUDGET = {
    "intake_L": {"target": 3500, "cap": 4100, "objects": ("intake_duct_L",)},
    "intake_R": {"target": 3500, "cap": 4100, "objects": ("intake_duct_R",)},
    # The owner asked for visible mechanical detail: a bell-crank horn, spine and ribs on each of the 16 petals, and
    # eight ram mounts with gussets, pins and hydraulic lines on the shroud.
    "nozzle": {"target": 6100, "cap": 6600, "exact": ("nozzle",), "objects": ("nozzle_petal_", "nozzle_seal_")},
    # The owner asked for the actuation hardware the F-15 ACTIVE shows, with visible detail: a ring at the nozzle
    # root with a fork for each of 16 pinned arms and a lug for each of eight rams. Boxes and 6- to 10-sided tubes.
    "nozzle_actuation": {"target": 5000, "cap": 5400, "objects": ("nozzle_sync_ring", "nozzle_link_", "nozzle_ram_")},
}
# The P&W pitch/yaw balance beam nozzle (F-15 ACTIVE) drives its flaps from a sync ring that hydraulic rams on the
# fixed structure move; an arm from the ring to a clevis on each flap's back turns that flap on its hinge. Here the
# ring sits at the nozzle root, just clear of the shroud so it slides over the rolled lip, each arm (nozzle_link_*)
# runs back along its petal to the clevis, and the rams lie along the shroud from the skin's tail end to the ring.
# The ring follows the petals as the plugin poses them (sync_ring_matrix, and NozzleDriver in game), and the arms and
# rams aim from eye to eye. Metres and degrees.
ACTUATION = {
    "clevis": (0.08, 0.015),  # the clevis eye on each petal's back: along the petal from its hinge, above its face
    # The arms' eyes on the ring, aft of the hinge plane and radius: the ring's inner aft corner. The owner asked for
    # the ring at the root, as small as possible, but moving visibly. Inside the outline (radius 0.374) the arms lie
    # almost along their petals and the ring slides 4 mm; here it slides 16 mm at full opening and tilts 2 degrees
    # at full vectoring. Each 4 mm further out buys only about 2 mm more slide.
    "eye": (0.06, 0.390),
    # The ring's section about its eye plane, axial and radial: 6 by 5 mm, the least that seats the arms' eyes, its
    # inside clear of the shroud and its rolled lip (nozzle shroud_r) as it slides forward over them.
    "section": ((-0.006, 0.0), (0.390, 0.395)),
    # Ring angles of the eight rams: on seals, so they clear the arms, left-right and top-bottom symmetric.
    "rams": (33.75, 78.75, 101.25, 146.25, 213.75, 258.75, 281.25, 326.25),
    # Each ram's fixed eye, station and radius, on a bracket just aft of the skin's tail end, and its eye on the ring
    # (axial about the ring's eye plane, radius): the barrel lies along the shroud, the rod over the lip.
    "anchor": (15.215, 0.401),
    "ram_eye": (-0.003, 0.401),
    # The poses the rams are sized and checked for: Tuning's default full-afterburner opening and the vectoring limit
    # IcarusAuthor.Engine gives the Turbojet, both axes at once.
    "open_deg": (0.0, 15.0),
    "vector_deg": 4.0,
    "link_error": 0.004,  # the most a link may miss its clevis eye: the rigid ring fits 16 petals by least squares
}
# The Y-duct's mesh: rings from the lip to the engine face, and points along each half's wall (bi.duct_ring).
DUCT = {"stations": 35, "points": 33}
# The Y-duct's flow area, both sides, m2 (check_duct_areas): one constant tube from tube_s's first station to its
# second, the old cone-and-diffuser duct's throat, so the duct is nowhere narrower than it was; then a short blend to
# the engine face (internals.INTERNALS engine radius 0.46 less 8%, 0.563 m2) at face_s. merge_s: the branches meet
# no further aft than the cone-and-diffuser duct's did.
DUCT_AREAS = {"tube": 0.337, "face": 0.5628, "tube_s": (7.30, 9.20), "face_s": 9.60, "merge_s": 8.29}
# Review close-ups: name -> (camera location, look-at point), Blender axes.
CLOSEUPS = {
    "intake": (Vector((3.2, -6.6, 1.0)), Vector((0.8, -1.2, 0.2))),
    "intake_head_on": (Vector((0.8, -16.0, 0.22)), Vector((0.8, -1.0, 0.22))),
}


def build(p, mats):
    parts = build_nozzle(p, mats)
    parts += build_shock_cones(p, mats["body"])
    parts += build_ducts(p, mats)
    parts += build_mouth(p, mats)
    parts += compressor_faces(p, mats)
    parts += build_actuation(p, mats)
    return parts


def check(icarus):
    import budget

    over = budget.over_caps(icarus, BUDGET)
    if over:
        raise ValueError("propulsion: over triangle caps: " + "; ".join(over))
    ring = bpy.data.objects["nozzle_vector"]
    hinges = list(ring.children)
    if len(hinges) != 32 or any(h.get("hinge_axis") != "X" for h in hinges):
        raise ValueError("propulsion: nozzle_vector must have 32 X hinges")
    for hinge in hinges:
        vis = bpy.data.objects[hinge.name + "_visible"]
        if vis.parent != hinge or vis.get("role") != "visual":
            raise ValueError("propulsion: invalid petal visual " + vis.name)
        if [m.name for m in vis.data.materials] != ["Icarus_Body", "jet_mechanical"]:
            raise ValueError("propulsion: petal skin must be slot 0, inner face stock trim")
        ys = [v.co.y for v in vis.data.vertices]
        if abs(min(ys)) > 1e-6 or abs(max(ys) - bi.PARAMS["nozzle"]["petal_length"]) > 1e-6:
            raise ValueError("propulsion: petal length changed " + vis.name)
    actuation = check_actuation()
    areas = check_duct_areas(bi.PARAMS)
    print("propulsion check PASS: 32 X hinges with skin/trim visuals; " + actuation + "; " + areas + "; " + ", ".join(
        "%s %d/%d triangles" % (key, budget.measure(icarus, item), item["cap"]) for key, item in BUDGET.items()))


def duct_area(p, s, step=0.004):
    """The Y-duct's flow area at s, both sides: inside the wall (bi.duct_field), outside the shock cones."""
    sc = p["shock_cone"]
    zc = p["intake"][0][2]
    cone = cone_radius(sc, s)
    field, (cx, cz, r) = bi.duct_field(p, s)
    reach = r + 0.1
    count = sum(1 for i in range(int((cx + reach) / step)) for j in range(int(2 * reach / step))
                for x, z in [((i + 0.5) * step, cz - reach + (j + 0.5) * step)]
                if field(x, z) <= 0 and (x - sc["x"]) ** 2 + (z - zc) ** 2 > cone * cone)
    return 2 * count * step * step


def check_duct_areas(p):
    """The Y-duct is one constant tube: from just inside the lips, through the merge, to the blend before the engine
    face, the flow area stays at DUCT_AREAS tube, with no bulge and no waist; over the blend it never shrinks, and it
    ends at the face's area. Pinned to the values build_icarus.PARAMS["duct"] was solved for (tools/y_duct_design.py),
    the tube 20 cm2 either way (its rows' interpolation between solved stations), the face 5 cm2: the grid's sampling
    error is under 1 cm2."""
    (s0, s1), s_face = DUCT_AREAS["tube_s"], DUCT_AREAS["face_s"]
    if abs(p["duct"][-1][0] - s_face) > 1e-9:
        raise ValueError("propulsion: the Y-duct must end at the engine face's s %.2f" % s_face)
    tube = [(s, duct_area(p, s)) for s in [s0 + 0.05 * i for i in range(int(round((s1 - s0) / 0.05)) + 1)]]
    blend = [(s, duct_area(p, s)) for s in [s1 + 0.05 * i for i in range(int(round((s_face - s1) / 0.05)) + 1)]]
    problems = ["tube area %.4f m2 at s %.2f, pinned %.4f" % (a, s, DUCT_AREAS["tube"]) for s, a in tube
                if abs(a - DUCT_AREAS["tube"]) > 0.002]
    problems += ["area falls %.4f m2 from s %.2f" % (a - b, s) for (s, a), (_, b) in zip(blend, blend[1:])
                 if b < a - 0.002]
    if abs(blend[-1][1] - DUCT_AREAS["face"]) > 0.0005:
        problems.append("face area %.4f m2, pinned %.4f" % (blend[-1][1], DUCT_AREAS["face"]))
    merge = bi.duct_merge_s(p)
    if merge > DUCT_AREAS["merge_s"]:
        problems.append("the branches merge at s %.3f, aft of %.2f" % (merge, DUCT_AREAS["merge_s"]))
    if problems:
        raise ValueError("propulsion: Y-duct area schedule: " + "; ".join(problems))
    return ("Y-duct flow area %.3f to %.3f m2 from s %.2f to %.2f, rising to %.3f at the face; the branches merge at "
            "s %.3f" % (min(a for _, a in tube), max(a for _, a in tube), s0, s1, blend[-1][1], merge))


def check_actuation():
    """Over the envelope, as pose_nozzle poses it: every arm within link_error of its clevis eye, every rod inside its barrel, and no actuator piece touching a petal or seal, the
    ring and arms clear of the shroud and its lip, the rams clear of the ring and the arms. The rams' eyes sit in the
    shroud's brackets, by design. NozzleDriver finds each clevis eye at twice its arm
    mesh's bounds centre, so every arm must be symmetric about its middle."""
    import checks

    O = bpy.data.objects
    rest = actuation_rest(bi.PARAMS)
    count = bi.PARAMS["nozzle"]["petals"]
    (a0, a1), (r0, r1) = ACTUATION["section"]
    links = [O["nozzle_link_%02d" % i] for i in range(count)]
    rams = [(O["nozzle_ram_%d_cylinder" % k], O["nozzle_ram_%d_rod" % k]) for k in range(len(ACTUATION["rams"]))]
    ring = O["nozzle_sync_ring"]
    if any(o.parent != ring for o in links + [rod for _, rod in rams]) or any(c.parent != O["nozzle"] for c, _ in rams):
        raise ValueError("propulsion: links and rods must ride nozzle_sync_ring, cylinders the nozzle")
    for link in links:
        lo = Vector([min(v.co[i] for v in link.data.vertices) for i in range(3)])
        hi = Vector([max(v.co[i] for v in link.data.vertices) for i in range(3)])
        if ((lo + hi) - Vector((0.0, link["reach_m"], 0.0))).length > 1e-5:
            raise ValueError("propulsion: %s is not symmetric about its middle" % link.name)
    petals = [O["nozzle_%s_%02d_visible" % (kind, i)] for kind in ("petal", "seal") for i in range(count)]
    worst, lengths, clashes, moves = 0.0, [], set(), {}
    try:
        for pose in envelope():
            pose_nozzle(**pose)
            bpy.context.view_layer.update()
            for i, link in enumerate(links):
                clevis = O["nozzle_petal_%02d" % i].matrix_world @ rest["clevis"]
                worst = max(worst, (link.matrix_world @ Vector((0.0, link["reach_m"], 0.0)) - clevis).length)
            for cylinder, rod in rams:
                end = rod.matrix_world @ Vector((0.0, rod["reach_m"], 0.0))
                axis = cylinder.matrix_world.col[1].xyz
                along = (end - cylinder.matrix_world.translation).dot(axis)
                lengths.append((rod.matrix_world.translation - cylinder.matrix_world.translation).length)
                if not cylinder["barrel_start_m"] < along < cylinder["reach_m"] - 0.004:
                    raise ValueError("propulsion: %s leaves its barrel at %s (%.3f m)" % (rod.name, pose, along))
            shroud = O["nozzle"]
            trees = {o.name: checks.tree(o)
                     for o in petals + links + [ring, shroud] + [o for pair in rams for o in pair]}
            pairs = [(a, b) for a in links + [o for pair in rams for o in pair] + [ring] for b in petals]
            pairs += [(a, shroud) for a in links + [ring]]
            pairs += [(c, b) for c, _ in rams for b in [ring] + links]
            pairs += [(r, b) for _, r in rams for b in links]
            clashes |= {"%s %s" % (a.name, b.name) for a, b in pairs if trees[a.name].overlap(trees[b.name])}
            moves[tuple(pose.values())] = (ring.matrix_world.translation.y - rest["ring"].translation.y,
                                           math.degrees(ring.matrix_world.col[1].xyz.angle(Vector((0.0, 1.0, 0.0)))))
    finally:
        pose_nozzle()
        bpy.context.view_layer.update()
    if worst > ACTUATION["link_error"]:
        raise ValueError("propulsion: a link misses its clevis eye by %.4f m" % worst)
    if clashes:
        raise ValueError("propulsion: actuation touches " + "; ".join(sorted(clashes)))
    v, wide = ACTUATION["vector_deg"], max(ACTUATION["open_deg"])
    edge = max((w - Vector((0.0, w.y, bi.PARAMS["nozzle"]["z"]))).length
               for w in bi.blended_ring(bi.PARAMS, bi.fuselage_stations(bi.PARAMS)[-1]))
    return ("actuation clear over %d poses (ring r %.3f to %.3f m, %.0f by %.0f mm, %.0f mm proud of the shroud and %.0f "
            "mm of the skin's tail edge; slides %.1f mm at full open, tilts %.2f deg at full vector), arms within %.1f mm "
            "of their clevis eyes, rams %.3f to %.3f m" % (
                len(envelope()), r0, r1, (a1 - a0) * 1000, (r1 - r0) * 1000,
                (r1 - bi.PARAMS["nozzle"]["shroud_r"]) * 1000, (r1 - edge) * 1000, abs(moves[(wide, 0.0, 0.0)][0]) * 1000,
                moves[(0.0, v, v)][1], worst * 1000, min(lengths), max(lengths)))


def build_ducts(p, mats):
    """The Y-duct, faces pointing inward, from just inside the lip to the compressor face's dark backplate, as two
    mirrored halves: each intake's branch, and its half of the trunk the branches merge into, open on the centre line
    where it meets its twin. While the branches are apart each ring is a closed loop, its ends welded."""
    s0, s1 = p["duct"][0][0], p["duct"][-1][0]
    stations = bi.spaced(s0, s1, DUCT["stations"])
    rings = [[(x, s, z) for x, z in bi.duct_ring(p, s, DUCT["points"])] for s in stations]
    n = DUCT["points"]
    faces = [(j * n + k, j * n + k + 1, (j + 1) * n + k + 1, (j + 1) * n + k)
             for j in range(len(rings) - 1) for k in range(n - 1)]
    faces.append(tuple((len(rings) - 1) * n + k for k in range(n)))  # the backplate, closed along the centre line
    parts = []
    for side, name in ((1, "duct_L"), (-1, "duct_R")):
        verts = [bi.P(s, side * x, z) for ring in rings for x, s, z in ring]
        obj = bi.mesh_object(name, verts, faces)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-7)  # the closed loops' seams
        bm.to_mesh(obj.data)
        bm.free()
        _, cx, cz, _ = p["duct"][1]
        bi.inward_fix(obj, bi.P(stations[0], side * cx, cz))
        parts.append(bi.finish(obj, mats["mechanical"]))
        obj.data.materials.append(mats["duct"])
        obj.data.polygons[-1].material_index = 1  # the cap at the engine face
    return parts


def compressor_faces(p, mats):
    """In front of the trunk's backplate, the engine's compressor face: a spinner and a ring of 14 inlet guide vanes,
    each set 25 degrees to the duct axis. Trim, its left half joined into intake_duct_L and the mirror into _R: half
    the spinner and the seven vanes outboard of the centre line, none on it."""
    s, cx, cz, r = p["duct"][-1]
    half = [2 * math.pi * k / 12 for k in range(-3, 4)]  # bottom round the outboard side to the top
    spinner = [bi.P(s, cx + 0.085 * math.cos(a), cz + 0.085 * math.sin(a)) for a in half] + [bi.P(s - 0.15, cx, cz)]
    pieces = [(spinner, [(k, k + 1, 7) for k in range(6)] + [tuple(range(7))])]
    field, _ = bi.duct_field(p, s)
    for k in (-3, -2, -1, 0, 1, 2, 3):
        a = 2 * math.pi * k / 14
        radial = Vector((math.cos(a), 0, math.sin(a)))
        across = Vector((-math.sin(a), 0, math.cos(a)))
        frame = (Matrix.Translation(bi.P(s - 0.035, cx, cz)) @
                 Matrix((Vector((math.sin(a), 0, -math.cos(a))), Vector((0, 1, 0)), radial)).transposed().to_4x4() @
                 Matrix.Rotation(math.radians(25), 4, "Z"))
        # Each vane stops 6 mm short of the wall across its 25 mm chord, the flattened floor included.
        starts = [(cx + 0.025 * d * across.x, cz + 0.025 * d * across.z) for d in (-1, 0, 1)]
        reach = min(math.dist(o, bi.duct_exit(field, o, a, -9.0)[0]) for o in starts) - 0.006
        pieces.append(box(Vector((-0.002, -0.025, 0.08)), Vector((0.002, 0.025, reach)), frame))
    verts, faces = joined(pieces)
    parts = []
    for side, sd in ((1, "L"), (-1, "R")):
        obj = detail_mesh("compressor_face_" + sd, "intake_duct_" + sd, verts, faces, [mats["mechanical"]],
                          [0] * len(faces), side)
        import parts as part_tree

        part_tree.face_outward(obj)
        parts.append(obj)
    return parts


def cone_radius(sc, s):
    """The shock cone's radius at s: the cone from its apex to its base, then the elliptical cap; 0 outside both."""
    if sc["apex_s"] < s <= sc["base_s"]:
        return sc["radius"] * (s - sc["apex_s"]) / (sc["base_s"] - sc["apex_s"])
    t = (s - sc["base_s"]) / sc["cap"]
    return sc["radius"] * math.sqrt(1 - t * t) if 0 < t < 1 else 0.0


def build_shock_cones(p, mat):
    """Each shock cone from its tip to its cap's point, the cap's rings evenly round its ellipse."""
    sc = p["shock_cone"]
    zc = p["intake"][0][2]
    n = 48
    stations = [sc["apex_s"] + (sc["base_s"] - sc["apex_s"]) * i / 6 for i in range(1, 7)]
    stations += [sc["base_s"] + sc["cap"] * math.sin(math.pi / 2 * i / 5) for i in range(1, 5)]
    tail = sc["base_s"] + sc["cap"]
    faces = [(0, 1 + (k + 1) % n, 1 + k) for k in range(n)]
    faces += [(1 + j * n + k, 1 + j * n + (k + 1) % n, 1 + (j + 1) * n + (k + 1) % n, 1 + (j + 1) * n + k)
              for j in range(len(stations) - 1) for k in range(n)]
    last = 1 + (len(stations) - 1) * n
    faces += [(last + k, last + (k + 1) % n, last + n) for k in range(n)]
    parts = []
    for side, name in ((1, "shock_cone_L"), (-1, "shock_cone_R")):
        verts = [bi.P(sc["apex_s"], side * sc["x"], zc)]
        for s in stations:
            r = cone_radius(sc, s)
            verts += [bi.P(s, side * (sc["x"] + r * math.cos(a)), zc + r * math.sin(a))
                      for a in [2 * math.pi * k / n for k in range(n)]]
        cone = bi.finish(bi.mesh_object(name, verts + [bi.P(tail, side * sc["x"], zc)], faces), mat)
        import parts as part_tree

        part_tree.face_outward(cone)
        parts.append(cone)
    return parts


def lip_edge(p, skin):
    s, xo, cz, _ = p["intake"][0]
    cx = (xo + p["intake_inner_x"]) / 2
    bm = bmesh.new()
    bm.from_mesh(skin.data)
    bm.transform(skin.matrix_world)
    points = {v.index: v.co.copy() for e in bm.edges if e.is_boundary
              and all(abs(v.co.y + bi.S0 - s) < 1e-4 for v in e.verts)
              for v in e.verts if v.co.x > 0 and math.hypot(v.co.x - cx, v.co.z - cz) < 0.45}
    bm.free()
    if len(points) < 10:
        raise ValueError("propulsion: no intake opening edge")
    return sorted(points.values(), key=lambda v: math.atan2(v.z - cz, v.x - cx))


def inside(v, ring):
    """Whether v lies inside a fuselage section ring, seen along the axis (x and z)."""
    crossings = 0
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a.z > v.z) != (b.z > v.z) and v.x < a.x + (v.z - a.z) * (b.x - a.x) / (b.z - a.z):
            crossings += 1
    return crossings % 2 == 1


def detail_mesh(name, owner, verts, faces, mats, indices, side=1):
    if side < 0:
        verts = [Vector((-v.x, v.y, v.z)) for v in verts]
        faces = [f[::-1] for f in faces]
    obj = bi.mesh_object(name, verts, faces)
    for mat in mats:
        obj.data.materials.append(mat)
    for poly, index in zip(obj.data.polygons, indices):
        poly.material_index = index
    obj["merge_into"] = owner
    return obj


def build_mouth(p, mats):
    s, xo, cz, _ = p["intake"][0]
    cx = (xo + p["intake_inner_x"]) / 2
    ds, dx, dz, dr = p["duct"][0]
    edge = lip_edge(p, bpy.data.objects["fuselage"])
    rings = []
    for v in edge:
        radial = Vector((v.x - cx, 0, v.z - cz)).normalized()
        radius = math.hypot(v.x - cx, v.z - cz)
        # Ends just inside the duct's first ring, whose chords cut inside its radius, so no sliver opens between them.
        profile = [(0.006, -0.003)] + [(-0.006 * math.sin(t), -0.004 + 0.004 * math.cos(t))
                   for t in [math.pi * i / 4 for i in range(5)]] + [(ds - s + 0.02, dr - 0.004 - radius)]
        rings.append([bi.P(s + a, cx + (radius + b) * radial.x, cz + (radius + b) * radial.z)
                      for a, b in profile])
    verts = [v for row in rings for v in row]
    width = len(rings[0])
    faces = [(j * width + k, (j + 1) * width + k, (j + 1) * width + k + 1, j * width + k + 1)
             for j in range(len(rings) - 1) for k in range(width - 1)]
    indices = [1 if k == width - 2 else 0 for j in range(len(rings) - 1) for k in range(width - 1)]
    parts = [detail_mesh("intake_mouth_" + sd, "intake_duct_" + sd, verts, faces,
                         [mats["body"], mats["mechanical"]], indices, side)
             for side, sd in ((1, "L"), (-1, "R"))]
    return parts + mouth_corners(p, mats, edge)


def mouth_corners(p, mats, edge):
    """The lobe's open edge is an arc; past each end the opening runs on to the body ahead, leaving a wedge between
    the duct, the skin at the lip and the body ahead that looks into the fuselage. Close each with a trim sheet in
    the lip's plane, from just inside the duct out to the skin, in 3 degree steps to where the skin meets the body
    ahead, which hides the rest; the fuel cells fill the body ahead behind it. At the bottom the skin there is the
    trough's, which keeps its distance from the ducts (stations.DUCT_CLEARANCE), so the sheets are the skin's, not
    the duct's."""
    s, xo, cz, _ = p["intake"][0]
    cx = (xo + p["intake_inner_x"]) / 2
    ds, _, _, dr = p["duct"][0]
    stations = bi.fuselage_stations(p)
    ahead, at_lip = (bi.blended_ring(p, stations[stations.index(s) + j]) for j in (-1, 0))
    point = lambda a, r, t=s: bi.P(t, cx + r * math.cos(a), cz + r * math.sin(a))
    hidden = lambda a: inside(point(a, reach(at_lip, cx, cz, a) - 0.001), ahead)
    verts, faces = [], []
    for end, turn in ((0, -1), (-1, 1)):
        a = math.atan2(edge[end].z - cz, edge[end].x - cx) - turn * math.radians(3)  # overlapping the mouth
        start = len(verts)
        for step in range(31):
            if step == 30:
                raise ValueError("propulsion: the body ahead never hides the intake mouth's corner")
            if step and hidden(a):
                lo, hi = a - turn * math.radians(3), a
                for _ in range(16):
                    lo, hi = (lo, (lo + hi) / 2) if hidden((lo + hi) / 2) else ((lo + hi) / 2, hi)
                a = hi
            skin = reach(at_lip, cx, cz, a) + 0.001
            # From inside the duct start, folding forward to the lip's plane and out to just past the skin's edge.
            verts += [point(a, dr - 0.004, ds + 0.02), point(a, dr + 0.002, s - 0.001), point(a, skin, s - 0.001)]
            if step and hidden(a):
                break
            a += turn * math.radians(3)
        faces += [(start + 3 * j + k, start + 3 * j + k + 1, start + 3 * j + k + 4, start + 3 * j + k + 3)
                  for j in range((len(verts) - start) // 3 - 1) for k in range(2)]
    faces = facing(verts, faces, Vector((0, -1, 0)))  # seen from ahead, through the mouth
    return [detail_mesh("intake_corners_" + sd, "skin_mid_" + sd, verts, faces, [mats["mechanical"]],
                        [0] * len(faces), side) for side, sd in ((1, "L"), (-1, "R"))]


def reach(ring, cx, cz, a):
    """How far a ray from (cx, cz) at angle a runs, seen along the axis, before it meets a section ring."""
    d = (math.cos(a), math.sin(a))
    best = math.inf
    for p0, p1 in zip(ring, ring[1:] + ring[:1]):
        e = (p1.x - p0.x, p1.z - p0.z)
        w = (p0.x - cx, p0.z - cz)
        den = d[0] * e[1] - d[1] * e[0]
        if abs(den) < 1e-12:
            continue
        t = (w[0] * e[1] - w[1] * e[0]) / den
        u = (w[0] * d[1] - w[1] * d[0]) / den
        if t > 0 and 0 <= u <= 1:
            best = min(best, t)
    return best


def ring_points(s, r, z, n=bi.RING):
    return [bi.P(s, r * math.cos(a), z + r * math.sin(a)) for a in [2 * math.pi * k / n for k in range(n)]]


def plate(name, root_w, tip_w, length, thickness):
    """Chamfered petal in hinge space, with a rolled exit edge. Its axial extent stays exactly 0 to length."""
    c, bead = 0.003, 0.008
    half_width = lambda y: (root_w + (tip_w - root_w) * y / length) / 2
    section = lambda y, slope: [Vector((sign * (half_width(y - slope * z) - inset), y - slope * z, z))
                               for sign, inset, z in ((-1, 0, -thickness), (-1, 0, -c), (-1, c, 0),
                                                      (1, c, 0), (1, 0, -c), (1, 0, -thickness))]
    verts, faces = sweep_shape([section(0, 1), section(length - bead, 0)], cap=True)
    rim = [(length - bead + bead * math.cos(a), -thickness / 2 + bead * math.sin(a))
           for a in [math.pi * i / 3 for i in range(6)]]
    width = half_width(length - bead) - c
    v, f = sweep_shape([[Vector((x, y, z)) for y, z in rim] for x in (-width, width)], cap=True)
    offset = len(verts)
    verts += v
    faces += [tuple(offset + i for i in face) for face in f]
    obj = bi.mesh_object(name, verts, faces)
    import parts as part_tree

    part_tree.face_outward(obj)
    return obj


def sweep_shape(rings, closed=False, cap=False):
    n, m = len(rings[0]), len(rings)
    faces = [(j * n + k, j * n + (k + 1) % n, (j + 1) % m * n + (k + 1) % n, (j + 1) % m * n + k)
             for j in range(m if closed else m - 1) for k in range(n)]
    if cap:
        faces += [tuple(range(n))[::-1], tuple((m - 1) * n + k for k in range(n))]
    return [v for row in rings for v in row], faces


def nozzle_lip(n, mats):
    radius = 0.013
    profile = [(n["ring_s"] + radius * math.sin(t), n["shroud_r"] - radius + radius * math.cos(t))
               for t in [2 * math.pi * i / 6 for i in range(6)]]
    rings = [[bi.P(s, r * math.cos(a), n["z"] + r * math.sin(a)) for s, r in profile]
             for a in [2 * math.pi * k / 40 for k in range(40)]]
    verts, faces = sweep_shape(rings, closed=True)
    return detail_mesh("nozzle_lip", "nozzle", verts, faces, [mats["body"]], [0] * len(faces))


def facing(verts, faces, direction):
    """faces, each wound so its normal leans toward direction: an open sheet seen from one side."""
    out = []
    for face in faces:
        a, b, c = (verts[i] for i in face[:3])
        out.append(face if (b - a).cross(c - a).dot(direction) >= 0 else face[::-1])
    return out


def afterburner(n, mats):
    """The tailpipe's afterburner in front of its dark backplate, seen only from behind: a ring of 16 fuel spray
    bars, then two V-gutter flameholder rings joined by eight radial gutters, opening aft, round the tail cone."""
    s = n["shroud_start"] + 0.07
    vee = ((s + 0.008, -0.014), (s - 0.012, 0.0), (s + 0.008, 0.014))  # (station, offset across the gutter)
    verts, faces = [], []
    for r, count in ((0.12, 24), (0.24, 40)):
        start = len(verts)
        verts += [bi.P(t, (r + d) * math.cos(a), n["z"] + (r + d) * math.sin(a))
                  for a in [2 * math.pi * k / count for k in range(count)] for t, d in vee]
        faces += [(start + j * 3 + i, start + j * 3 + i + 1, start + (j + 1) % count * 3 + i + 1,
                   start + (j + 1) % count * 3 + i) for j in range(count) for i in range(2)]
    for k in range(8):
        a = 2 * math.pi * (k + 0.5) / 8
        radial, across = Vector((math.cos(a), 0, math.sin(a))), Vector((-math.sin(a), 0, math.cos(a)))
        start = len(verts)
        verts += [bi.P(t, 0, n["z"]) + radial * r + across * d for r in (0.134, 0.226) for t, d in vee]
        faces += [(start + i, start + i + 1, start + 4 + i, start + 3 + i) for i in range(2)]
    base = len(verts)
    verts += ring_points(n["shroud_start"] + 0.005, 0.09, n["z"], 16)
    verts.append(bi.P(n["shroud_start"] + 0.16, 0, n["z"]))
    faces += [(base + k, base + (k + 1) % 16, base + 16) for k in range(16)]
    faces = facing(verts, faces, Vector((0, 1, 0)))
    for k in range(16):
        a = 2 * math.pi * (k + 0.25) / 16
        radial = Vector((math.cos(a), 0, math.sin(a)))
        frame = Matrix.Translation(bi.P(s - 0.035, 0, n["z"])) @ Matrix(
            (Vector((math.sin(a), 0, -math.cos(a))), Vector((0, 1, 0)), radial)).transposed().to_4x4()
        bar_verts, bar_faces = box(Vector((-0.003, -0.003, 0.10)), Vector((0.003, 0.003, n["duct_r"] - 0.002)), frame)
        faces += [tuple(len(verts) + i for i in f) for f in bar_faces]
        verts += bar_verts
    if sum(len(f) - 2 for f in faces) > 600:
        raise ValueError("propulsion: afterburner exceeds 600 triangles")
    return detail_mesh("nozzle_afterburner", "nozzle", verts, faces, [mats["mechanical"]], [0] * len(faces))


def tail_seal(p, mats):
    """A dark ring closing the gap between the shroud and the fuselage's open tail end, which looks forward into the
    tail cone. Its outer edge sits 3 cm ahead, inside the narrowing skin yet wider than its last ring, so seen from
    behind it reaches under the skin's edge without cutting through it."""
    n = p["nozzle"]
    end = bi.blended_ring(p, bi.fuselage_stations(p)[-1])
    s = end[0].y + bi.S0 - 0.001
    verts = []
    for v in end:
        radial = Vector((v.x, 0.0, v.z - n["z"]))
        out = radial.length + 0.002
        radial.normalize()
        verts += [bi.P(s, 0.0, n["z"]) + radial * (n["shroud_r"] - 0.002), bi.P(s - 0.03, 0.0, n["z"]) + radial * out]
    count = len(end)
    faces = facing(verts, [(2 * k, 2 * k + 1, 2 * ((k + 1) % count) + 1, 2 * ((k + 1) % count))
                           for k in range(count)], Vector((0, 1, 0)))
    return detail_mesh("nozzle_tail_seal", "nozzle", verts, faces, [mats["duct"]], [0] * len(faces))


def box(lo, hi, frame=Matrix()):
    """An axis-aligned box from lo to hi in frame: (verts, faces), faces wound outward."""
    verts = [frame @ Vector((hi.x if i & 1 else lo.x, hi.y if i & 2 else lo.y, hi.z if i & 4 else lo.z))
             for i in range(8)]
    return verts, [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4), (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]


def tube(radius, y0, y1, sides, frame=Matrix()):
    """A capped prism of sides round local Y from y0 to y1 in frame: (verts, faces), faces wound outward."""
    rings = [[frame @ Vector((radius * math.cos(a), y, radius * math.sin(a)))
              for a in [2 * math.pi * k / sides for k in range(sides)]] for y in (y0, y1)]
    verts, faces = sweep_shape(rings, cap=True)
    return verts, [f[::-1] for f in faces]


def prism(profile, x0, x1, frame=Matrix()):
    """A convex (y, z) profile extruded along local X from x0 to x1 in frame: (verts, faces), faces wound outward."""
    verts = [frame @ Vector((x, y, z)) for x in (x0, x1) for y, z in profile]
    n = len(profile)
    faces = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)] + [tuple(range(n)), tuple(range(n, 2 * n))]
    centre = sum(verts, Vector()) / len(verts)
    return verts, [f if (verts[f[1]] - verts[f[0]]).cross(verts[f[2]] - verts[f[0]]).dot(
        sum((verts[i] for i in f), Vector()) / len(f) - centre) > 0 else f[::-1] for f in faces]


def pins(radius, inner, outer, frame=Matrix(), sides=6):
    """Pin heads either side of an eye: short tubes across local X from inner to outer and their mirror."""
    across = frame @ Matrix.Rotation(-math.pi / 2, 4, "Z")  # local Y onto X
    return [tube(radius, inner, outer, sides, across), tube(radius, -outer, -inner, sides, across)]


def segment(a, b, radius, sides=6):
    """A tube from point a to point b, run on by its radius at each end so joints close."""
    y = (b - a).normalized()
    x = y.orthogonal().normalized()
    frame = Matrix((x, y, x.cross(y))).transposed().to_4x4()
    return tube(radius, -radius, (b - a).length + radius, sides, Matrix.Translation(a) @ frame)


def joined(pieces):
    """(verts, faces) pieces as one (verts, faces)."""
    verts, faces = [], []
    for v, f in pieces:
        faces += [tuple(len(verts) + i for i in face) for face in f]
        verts += v
    return verts, faces


def nozzle_hinge_matrix(p, kind, i, open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """World matrix of one petal or seal hinge. Opening adds to every petal; vectoring tilts the exit: a petal at
    ring angle phi gains -pitch*sin(phi) - yaw*cos(phi), so a positive pitch points the exit down (nose-up moment)."""
    n = p["nozzle"]
    count = n["petals"]
    phi = 2 * math.pi * i / count + (math.pi / count if kind == "seal" else 0.0)
    radial = Vector((math.cos(phi), 0.0, math.sin(phi)))
    # X runs clockwise round the ring seen from behind, so X, aft and outward make a right-handed frame; a positive
    # rotation about X turns aft toward outward, opening the petal.
    hinge_x = Vector((math.sin(phi), 0.0, -math.cos(phi)))
    basis = Matrix((hinge_x, Vector((0.0, 1.0, 0.0)), radial)).transposed().to_4x4()
    inset = n["seal_inset"] if kind == "seal" else 0.0
    hinge_at = bi.P(n["ring_s"], 0.0, n["z"]) + radial * (n["ring_r"] - inset)
    angle = n["dry_angle_deg"] + open_deg - pitch_deg * math.sin(phi) - yaw_deg * math.cos(phi)
    return Matrix.Translation(hinge_at) @ basis @ Matrix.Rotation(math.radians(angle), 4, "X")


def pose_nozzle(open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """Pose the built nozzle and its actuation, the way the plugin will drive it in game."""
    for kind in ("petal", "seal"):
        for i in range(bi.PARAMS["nozzle"]["petals"]):
            hinge = bpy.data.objects["nozzle_%s_%02d" % (kind, i)]
            hinge.matrix_world = nozzle_hinge_matrix(bi.PARAMS, kind, i, open_deg, pitch_deg, yaw_deg)
    for name, matrix in actuation_matrices(bi.PARAMS, open_deg, pitch_deg, yaw_deg).items():  # the ring first
        bpy.data.objects[name].matrix_world = matrix


def build_nozzle(p, mats):
    n = p["nozzle"]
    z, s_ring, r = n["z"], n["ring_s"], n["ring_r"]
    # The engine's end cap is at shroud_start. Offset this visible face to avoid coplanar flicker in the chase view.
    shroud = bi.loft("nozzle_shroud", [ring_points(n["shroud_start"], n["shroud_r"], z, 64), ring_points(s_ring, n["shroud_r"], z, 64),
                                      ring_points(s_ring, n["duct_r"], z, 64), ring_points(n["shroud_start"] + 0.004, n["duct_r"], z, 64)],
                     cap_back=True)
    bi.finish(shroud, mats["body"])
    shroud.data.materials.append(mats["mechanical"])
    shroud.data.materials.append(mats["duct"])
    for poly in shroud.data.polygons[128:]:
        poly.material_index = 1
    shroud.data.polygons[-1].material_index = 2  # the end cap is the tailpipe's backplate
    gimbal = bi.empty("nozzle_vector", Matrix.Translation(bi.P(s_ring, 0.0, z)))
    parts = [shroud, gimbal, nozzle_lip(n, mats), afterburner(n, mats), tail_seal(p, mats)]
    count = n["petals"]
    for kind, w0, w1 in (("petal", n["petal_root_w"], n["petal_tip_w"]),
                         ("seal", n["petal_root_w"] * 0.7, n["petal_tip_w"] * 0.7)):
        for i in range(count):
            name = "nozzle_%s_%02d" % (kind, i)
            hinge = bi.empty(name, nozzle_hinge_matrix(p, kind, i), parent=gimbal)
            hinge["hinge_axis"] = "X"
            vis = plate(name + "_visible", w0, w1, n["petal_length"], n["petal_thickness"])
            vis.parent = hinge
            vis.data.materials.append(mats["body"])
            vis.data.materials.append(mats["mechanical"])
            for poly in vis.data.polygons:
                poly.material_index = 1 if poly.normal.z < -0.3 else 0
            vis["role"] = "visual"
            parts += [hinge, vis]
            if kind == "petal":
                parts.append(petal_clevis(name, hinge.matrix_world, mats))
    return parts


def petal_clevis(hinge_name, hinge, mats):
    """The bell-crank horn on a petal's back that its arm pins into: two cheek plates rising 4 cm off the petal either
    side of the arm's eye, a web between them behind it and pin heads outside, then a spine with two ribs down the
    petal. Trim, in the petal's hinge frame (X across, Y down the petal, Z out of its face); it rides the petal."""
    y, h = ACTUATION["clevis"]
    lo, hi = Vector, Vector
    cheek = ((y - 0.012, -0.002), (y + 0.070, -0.002), (y + 0.016, 0.040), (y - 0.012, 0.026))
    eye = hinge @ Matrix.Translation((0.0, y, h))
    pieces = [prism(cheek, sign * 0.0065, sign * 0.0095, hinge) for sign in (-1, 1)]
    pieces += [box(lo((-0.0066, y + 0.022, 0.002)), hi((0.0066, y + 0.050, 0.020)), hinge)]
    pieces += pins(0.0045, 0.0094, 0.0115, eye)
    pieces += [box(lo((-0.006, y + 0.068, -0.002)), hi((0.006, 0.30, 0.010)), hinge)]
    pieces += [box(lo((-0.020, at - 0.004, -0.002)), hi((0.020, at + 0.004, 0.007)), hinge) for at in (0.17, 0.24)]
    verts, faces = joined(pieces)
    return detail_mesh(hinge_name + "_clevis", hinge_name, verts, faces, [mats["mechanical"]], [0] * len(faces))


def actuation_rest(p):
    """The actuation at the dry pose: the sync ring's world matrix (its local Y the nozzle axis, aft), the arms'
    eyes on it in its frame, the clevis eye in a petal's hinge frame, the arm length, and each ram's eye on the
    ring (ring frame) and its anchor (world)."""
    n, a = p["nozzle"], ACTUATION
    clevis = Vector((0.0, *a["clevis"]))
    aft, radius = a["eye"]
    ring = Matrix.Translation(bi.P(n["ring_s"] + aft, 0.0, n["z"]))
    at = lambda deg, r, dy=0.0: Vector((r * math.cos(math.radians(deg)), dy, r * math.sin(math.radians(deg))))
    eyes = [at(360.0 * i / n["petals"], radius) for i in range(n["petals"])]
    dy, r_eye = a["ram_eye"]
    s, r = a["anchor"]
    return {"ring": ring, "clevis": clevis, "eyes": eyes,
            "length": (ring @ eyes[0] - nozzle_hinge_matrix(p, "petal", 0) @ clevis).length,  # petal 0 at angle 0
            "ram_eyes": [at(deg, r_eye, dy) for deg in a["rams"]],
            "anchors": [bi.P(s, 0, n["z"]) + at(deg, r) for deg in a["rams"]]}


def sync_ring_matrix(rest, petals):
    """The sync ring's world matrix for the petal hinges' world matrices, as NozzleDriver poses it in game. Each
    link, rigid, puts its ring eye on a sphere round its clevis eye; the eye's slide along the axis from rest that
    keeps the link's length, fitted over all the eyes by least squares, is the ring's slide and tilt."""
    ring = rest["ring"]
    inverse, axis = ring.inverted(), Vector((0.0, 1.0, 0.0))
    total, tilt, spread = 0.0, Vector(), 0.0
    for eye, hinge in zip(rest["eyes"], petals):
        d = eye - inverse @ (hinge @ rest["clevis"])
        b = d.dot(axis)
        root = math.sqrt(max(b * b - d.length_squared + rest["length"] ** 2, 0.0))
        slide = min(-b + root, -b - root, key=abs)
        total += slide
        tilt += eye * slide
        spread += eye.length_squared
    tilt *= 2.0 / spread
    turn = axis.rotation_difference((axis - tilt).normalized()).to_matrix().to_4x4()
    return ring @ Matrix.Translation(axis * (total / len(petals))) @ turn


def pivot(parent, origin, target, rest_target, across):
    """World matrix of an actuator piece: origin at its eye, local Y toward the other eye (target), local X across
    it; turned from its rest aim (rest_target) by the least rotation, as NozzleDriver turns it. All but parent are
    in parent's frame."""
    y = (rest_target - origin).normalized()
    x = (across - y * across.dot(y)).normalized()
    rest = Matrix((x, y, x.cross(y))).transposed()
    turn = y.rotation_difference(target - origin).to_matrix()
    return parent @ Matrix.Translation(origin) @ (turn @ rest).to_4x4()


def actuation_matrices(p, open_deg=0.0, pitch_deg=0.0, yaw_deg=0.0):
    """World matrices of the sync ring, then the links, the rams' cylinders and rods, for a nozzle pose."""
    rest = actuation_rest(p)
    hinges = [nozzle_hinge_matrix(p, "petal", i, open_deg, pitch_deg, yaw_deg) for i in range(p["nozzle"]["petals"])]
    ring = sync_ring_matrix(rest, hinges)
    inverse, rest_inverse = ring.inverted(), rest["ring"].inverted()
    across = lambda v: Vector((-v.z, 0.0, v.x))  # round the ring, at a ring-frame point
    out = {"nozzle_sync_ring": ring}
    for i, (eye, hinge) in enumerate(zip(rest["eyes"], hinges)):
        clevis_rest = rest_inverse @ (nozzle_hinge_matrix(p, "petal", i) @ rest["clevis"])
        out["nozzle_link_%02d" % i] = pivot(ring, eye, inverse @ (hinge @ rest["clevis"]), clevis_rest, across(eye))
    for k, (eye, anchor) in enumerate(zip(rest["ram_eyes"], rest["anchors"])):
        out["nozzle_ram_%d_cylinder" % k] = pivot(Matrix(), anchor, ring @ eye, rest["ring"] @ eye,
                                                  across(rest_inverse @ anchor))
        out["nozzle_ram_%d_rod" % k] = pivot(ring, eye, inverse @ anchor, rest_inverse @ anchor, across(eye))
    return out


def envelope():
    """The poses the actuation is sized and checked for (ACTUATION open_deg and vector_deg)."""
    v = ACTUATION["vector_deg"]
    return [{"open_deg": o, "pitch_deg": pitch, "yaw_deg": yaw}
            for o in ACTUATION["open_deg"] for pitch in (-v, 0.0, v) for yaw in (-v, 0.0, v)]


def build_actuation(p, mats):
    """The sync ring with a lug for each ram, the 16 arms, and four rams, each a cylinder on a bracket off the shroud
    and a rod on the ring, every piece with its origin at its eye. The rams are sized so each rod stays in its
    barrel over the envelope."""
    rest = actuation_rest(p)
    length = rest["length"]
    mech = mats["mechanical"]
    lo, hi = Vector, Vector
    frame_at = lambda v: Matrix((Vector((v.z, 0, -v.x)).normalized(), Vector((0, 1, 0)),
                                 Vector((v.x, 0, v.z)).normalized())).transposed().to_4x4()
    (a0, a1), (r0, r1) = ACTUATION["section"]
    rings = [[Vector((r * math.cos(a), dy, r * math.sin(a))) for dy, r in ((a0, r0), (a1, r0), (a1, r1), (a0, r1))]
             for a in [2 * math.pi * k / 48 for k in range(48)]]
    pieces = [sweep_shape(rings, closed=True)]
    for e in rest["eyes"]:  # a fork for each arm: cheeks either side of its eye, pin heads outside
        at = Matrix.Translation(e) @ frame_at(e)
        pieces += [box(lo((sign * 0.0065, -0.010, -0.008)), hi((sign * 0.0095, 0.009, r1 - e.xz.length)), at)
                   for sign in (-1, 1)]
        pieces += pins(0.0045, 0.0094, 0.0115, at)
    for e in rest["ram_eyes"]:  # a lug for each ram, its pin's heads outside
        at = Matrix.Translation(e) @ frame_at(e)
        pieces += [box(lo((-0.007, -0.007, r1 - 0.002 - e.xz.length)), hi((0.007, 0.007, 0.008)), at)]
        pieces += pins(0.0045, 0.0069, 0.009, at)
    ring = bi.finish(bi.mesh_object("nozzle_sync_ring", *joined(pieces)), mech, smooth=False)
    ring.matrix_world = rest["ring"]
    ring["parent_part"] = "nozzle"
    ring["role"] = "visual"  # no collider or LOD1 hull: it moves against the part it rides
    parts = [ring]

    lengths = [(ring_m @ eye - anchor).length for pose in envelope()
               for ring_m in [actuation_matrices(p, **pose)["nozzle_sync_ring"]]
               for eye, anchor in zip(rest["ram_eyes"], rest["anchors"])]
    shortest, longest = min(lengths), max(lengths)
    barrel = (0.01, shortest - 0.012)  # from the anchor eye; the rod's eye block never reaches the gland
    reach = (longest - barrel[1] + 0.006, shortest - barrel[0] - 0.004)  # rod 6 mm in at full stroke, clear at none
    if reach[0] > reach[1]:
        raise ValueError("propulsion: ram stroke %.3f m too long for its %.3f m length" % (longest - shortest, shortest))
    rod_length = sum(reach) / 2
    eye_block = box(lo((-0.006, -0.007, -0.007)), hi((0.006, 0.007, 0.007)))
    # An arm: a 10 by 12 mm bar between two 16 mm eyes with pin bosses, symmetric about its middle.
    arm_eye = lambda y: [box(lo((-0.005, y - 0.008, -0.008)), hi((0.005, y + 0.008, 0.008)))] + pins(
        0.0045, 0.0049, 0.006, Matrix.Translation((0.0, y, 0.0)))
    shapes = {"link": arm_eye(0.0) + arm_eye(length) +
                      [box(lo((-0.005, 0.008, -0.006)), hi((0.005, length - 0.008, 0.006)))],
              "cylinder": [eye_block, tube(0.008, *barrel, 10), tube(0.0095, barrel[1] - 0.008, barrel[1], 10),
                           tube(0.0095, barrel[0], barrel[0] + 0.006, 10)],  # barrel, gland and head collars
              "rod": [eye_block, tube(0.0045, 0.006, rod_length, 8)]}
    for name, matrix in actuation_matrices(p).items():
        kind = "link" if name.startswith("nozzle_link_") else name.split("_")[-1]
        if kind not in shapes:
            continue
        obj = bi.finish(bi.mesh_object(name, *joined(shapes[kind])), mech, smooth=False)
        if kind == "cylinder":
            obj["parent_part"] = "nozzle"
            obj["reach_m"] = round(barrel[1], 5)  # its gland, from its eye
            obj["barrel_start_m"] = barrel[0]
        else:
            obj.parent = ring
            obj["reach_m"] = round(rod_length if kind == "rod" else length, 5)  # its rod's end, or its far eye
        obj["role"] = "visual"
        obj.matrix_world = matrix
        parts.append(obj)
    for k, anchor in enumerate(rest["anchors"]):
        # Each ram's mount on the shroud: a base plate, cheeks either side of the cylinder's eye with pin heads
        # outside and gussets ahead, and its two hydraulic lines, from under the skin's tail edge along the shroud
        # into the barrel's head.
        local = anchor - Vector((0.0, anchor.y, p["nozzle"]["z"]))
        base = p["nozzle"]["shroud_r"] - 0.004 - local.length  # into the shroud, from the eye
        frame = Matrix.Translation(anchor) @ frame_at(local)
        pieces = [box(lo((-0.013, -0.014, base)), hi((0.013, 0.012, base + 0.005)), frame)]
        pieces += [box(lo((sign * 0.0065, -0.009, base)), hi((sign * 0.0095, 0.009, 0.010)), frame) for sign in (-1, 1)]
        pieces += [prism(((-0.014, base + 0.005), (-0.009, base + 0.005), (-0.009, 0.006)), sign * 0.0065,
                         sign * 0.0095, frame) for sign in (-1, 1)]
        pieces += pins(0.0045, 0.0094, 0.0115, frame)
        for sign in (-1, 1):
            points = [frame @ Vector((sign * x, y, z)) for x, y, z in
                      ((0.017, -0.030, -0.0145), (0.017, 0.012, -0.0145), (0.0075, 0.024, -0.003))]
            pieces += [segment(a, b, 0.0022) for a, b in zip(points, points[1:])]
        verts, faces = joined(pieces)
        parts.append(detail_mesh("nozzle_ram_%d_bracket" % k, "nozzle", verts, faces, [mech], [0] * len(faces)))
    return parts
