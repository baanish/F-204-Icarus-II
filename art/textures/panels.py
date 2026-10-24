"""Skin relief drawn from the airframe's own panel layout: seams, fasteners and closed access panels.

Every feature is a distance in world metres measured at texel centres, so a line keeps one width in texels and stays
continuous across UV cuts and mirrored islands. Panel faces between features are flat. Frames, spars, ribs and the
fuselage body sections come from structure.json (art/blender/pilot2_skin.py structure); the fin, stabilator, ventral
fin and control surfaces take their chord from their own baked texels.

Every seam is a plane section of the skin, so it is straight on the airframe, and every seam ends on another seam or
on a physical edge (a part boundary or crease), so the seams close into panels. panel_checks.py holds both.
"""
import numpy as np

# World x, longitudinal y, z; the port is shut and has no gun opening.
ACCESS_PANELS = (
    ('closed_gun_port', ('skin_forward_L', 'skin_forward_R'), -3.95, 0.15, 0.48, 0.24),
    ('aux_door', ('skin_mid_L', 'skin_mid_R'), 1.55, 0.32, 0.45, 0.32),
    ('under_vent', ('skin_aft_L', 'skin_aft_R'), 4.35, -0.04, 0.52, 0.20),  # on the side, clear above the lower lap joint
)
# Art decision: a 0.11 m fuel filler on the upper fixed wing, inside the wing tank box.
FUEL_FILLER = {'x': 2.45, 'chord_fraction': .42, 'radius': .055}

SEAM_HALF_WIDTH = .0045  # m: a 1 mm joint reads as a line about three texels wide at 300 px/m
FASTENERS = {'rivet': {'radius': .0042, 'pitch': .028},  # 8.4 mm universal heads
             'screw': {'radius': .0055, 'pitch': .045}}  # access-panel and box-cover screws
ROW_OFFSET = .015  # m from a joint to each fastener row
DEPTH_MM = {'seam': .7, 'rivet': .3, 'screw': .45}

# The fuselage skin sheet: one loft split into these parts, continuous across their boundaries. The intake ducts
# and shock cones inside them carry no panel lines.
FUSELAGE = ('skin_forward', 'skin_mid', 'skin_aft', 'dorsal_cover')
# Longitudinal lap joints, degrees above the body lobe's centre: on the corner longerons, 45 degrees off vertical
# (internals.py stringers). Other stringers carry no row, so the bays between stay flat. Each bay between butt joints
# takes the plane through the 45 degree lines at its two joints, so a lap joint is straight in every bay and meets
# the next bay's on the butt joint.
FUSELAGE_SEAMS_DEG = (45, -45)
JOINT_EVERY = 2  # a skin butt joint at every second frame; the frames between carry one rivet row
# Unpainted aft fuselage on every livery: the skin aft of this butt joint and below both upper lap joints (the
# panels round the tailpipe and the speed brakes in them), and the nozzle.
BARE_AFT_JOINT_S = 13.0
# (span axis, chord fractions with a joint, chord fractions with a fastener row only, rib pitch m or None)
LIFTING = {'fin_skin': ('z', (.18,), (.92,), None),
           'stabilator_visible': ('x', (.2,), (.72,), None),
           'ventral_fin': ('z', (), (.25, .8), None),
           'lef_L_visible': ('x', (), (.9,), .32),
           'flap_L_visible': ('x', (), (.1,), .32),
           'aileron_L_visible': ('x', (), (.1,), .32),
           'rudder_visible': ('z', (), (.1,), .32)}


def bump(distance, radius):
    """Smooth quartic profile: 1 on the feature, 0 at radius; its slope stays within one texel's band."""
    t = np.clip(distance / radius, 0, 1)
    return (1 - t * t) ** 2


def offset_to_line(value, lines):
    """Signed offset from the nearest line and the index of the cell between lines."""
    padded = np.concatenate(([-np.inf], np.sort(np.asarray(lines, float)), [np.inf]))
    index = np.searchsorted(padded, value)
    below, above = value - padded[index - 1], padded[index] - value
    return np.where(below < above, below, -above), index - 1


def nearest_line(value, lines):
    """Signed offset from the nearest line and that line's index in sorted order."""
    offset, cell = offset_to_line(value, lines)
    return offset, np.where(offset > 0, cell - 1, cell)


def row_distance(across, along, offset, pitch):
    """Distance to the nearest fastener of a row `offset` from a line, spaced `pitch` along it."""
    return np.hypot(across - offset, np.abs((along / pitch + .5) % 1 - .5) * pitch)


def polyline(x, xs, ys):
    """Piecewise straight line through (xs, ys), continued straight past both ends."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    y = np.interp(x, xs, ys)
    y = np.where(x < xs[0], ys[0] + (x - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0]), y)
    return np.where(x > xs[-1], ys[-1] + (x - xs[-1]) * (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]), y)


class Layout:
    """Per-texel feature distances over the evaluated texels; the nearest feature of each kind wins.

    `seam_id` names the straight seam piece nearest each texel (an index into `seam_names`); panel_checks.py fits one
    plane to each piece.
    """

    def __init__(self, count):
        self.seam = np.full(count, np.inf)
        self.seam_id = np.full(count, -1, np.int64)
        self.seam_names = []
        self.fastener = {kind: np.full(count, np.inf) for kind in FASTENERS}
        self.cell = np.zeros(count, np.int64)
        self.counts = {}

    def add_seam(self, where, distance, name, piece=None):
        distance = abs(distance)
        piece = np.zeros(len(where), np.int64) if piece is None else np.asarray(piece, np.int64)
        keys = np.unique(piece)
        ids = len(self.seam_names) + np.searchsorted(keys, piece)
        self.seam_names += [f'{name}:{key}' for key in keys]
        closer = distance < self.seam[where]
        self.seam[where[closer]] = distance[closer]
        self.seam_id[where[closer]] = ids[closer]
        self.counts[name] = self.counts.get(name, 0) + int((distance < SEAM_HALF_WIDTH).sum())

    def add_row(self, where, across, along, offsets, kind, name):
        pitch = FASTENERS[kind]['pitch']
        distance = np.min([row_distance(across, along, offset, pitch) for offset in offsets], axis=0)
        self.fastener[kind][where] = np.minimum(self.fastener[kind][where], distance)
        self.counts[name] = self.counts.get(name, 0) + int((distance < FASTENERS[kind]['radius']).sum())


def chord_fraction(span, y, bin_m=.02):
    """Chord fraction and chord of a lifting part, its leading and trailing edges taken as straight lines along the
    span fitted to its own texels (inner 80% of the span), so a constant fraction is a straight line."""
    edges = np.arange(span.min(), span.max() + bin_m, bin_m)
    index = np.clip(np.digitize(span, edges) - 1, 0, len(edges) - 1)
    le, te = np.full(len(edges), np.inf), np.full(len(edges), -np.inf)
    np.minimum.at(le, index, y)
    np.maximum.at(te, index, y)
    valid = np.isfinite(le) & (te - le > .02)
    centres = edges[valid] + bin_m / 2
    lo, hi = centres.min(), centres.max()
    inner = (centres >= lo + .1 * (hi - lo)) & (centres <= hi - .1 * (hi - lo))
    le_at = np.polyval(np.polyfit(centres[inner], le[valid][inner], 1), span)
    te_at = np.polyval(np.polyfit(centres[inner], te[valid][inner], 1), span)
    return (y - le_at) / np.maximum(te_at - le_at, 1e-3), te_at - le_at


def skin_breaks(position, part, names, s0):
    """Stations where the fuselage skin parts start and end (section breaks), from their texels."""
    s = position[..., 1] + s0
    return sorted({round(float(edge), 3) for name in names if name.startswith('skin_')
                   for selected in [part == names.index(name) + 1]
                   for edge in (s[selected].min(), s[selected].max())})


def fuselage_lines(structure, breaks):
    """Butt joints, riveted frames and the lap joints' bay ends (knots) with the body centre height at each."""
    frame = structure['frames']
    frames = np.round(np.arange(frame['s0'], frame['s1'] + 1e-6, frame['pitch']), 6)
    clear = [float(f) for f in frames if min(abs(f - b) for b in breaks) > .15]
    joints = [f for i, f in enumerate(frames) if i % JOINT_EVERY == 1 and f in clear]
    plain = [f for f in clear if f not in joints]
    knots = sorted({float(frames[0]), *joints, float(breaks[-1])})
    sections = np.array(structure['fuselage_sections'])
    return {'frames': frames, 'joints': joints, 'plain': plain, 'knots': knots,
            'knot_zc': np.interp(knots, sections[:, 0], sections[:, 1])}


def lap_distances(x, s, z, lines):
    """Signed distance (m, positive above) to each lap joint's plane in the texel's bay; x is the absolute x."""
    zc = np.interp(s, lines['knots'], lines['knot_zc'])
    return [(z - zc) * np.cos(np.radians(a)) - x * np.sin(np.radians(a)) for a in FUSELAGE_SEAMS_DEG]


def fuselage(layout, where, pos, normal, part_names, structure, breaks, report):
    x, y, z = abs(pos[:, 0]), pos[:, 1], pos[:, 2]
    s = y + structure['S0']
    sections = np.array(structure['fuselage_sections'])
    zmid = np.interp(s, sections[:, 0], sections[:, 1])
    theta, radius = np.arctan2(z - zmid, x), np.hypot(x, z - zmid)
    arc = theta * radius
    lines = fuselage_lines(structure, breaks)
    joints, plain, knots = lines['joints'], lines['plain'], lines['knots']
    covered = np.zeros(len(s), bool)
    panel_cell = np.zeros(len(s), np.int64)
    for index, (name, allowed, cy, cz, width, tall) in enumerate(ACCESS_PANELS, 1):
        on = np.isin(part_names, allowed) & (abs(normal[:, 0]) > .3)
        if not on.any():
            continue
        corner = .02
        qy, qz = abs(y - cy) - width / 2 + corner, abs(z - cz) - tall / 2 + corner
        edge = np.hypot(np.maximum(qy, 0), np.maximum(qz, 0)) + np.minimum(np.maximum(qy, qz), 0) - corner
        along = np.where(qy > qz, z - cz, y - cy)
        near = on & (edge < .03)
        layout.add_seam(where[near], edge[near], 'access_panel_seam:' + name)
        layout.add_row(where[near], edge[near], along[near], (-ROW_OFFSET,), 'screw', 'access_panel_screws')
        covered |= on & (edge < -.004)
        panel_cell[on & (edge < 0)] = 100 + index
    # Butt joints run the whole way round the skin, ending only on access panels and physical edges. No line is
    # drawn where the skin lies in a seam's own plane (a speed brake well's walls).
    skin = ~covered
    offset, joint_index = nearest_line(s, joints)
    _, joint_cell = offset_to_line(s, joints)
    ring = skin & (abs(normal[:, 1]) < .9)
    layout.add_seam(where[ring], offset[ring], 'frame_joint_seam', joint_index[ring])
    layout.add_row(where[skin], offset[skin], arc[skin], (-ROW_OFFSET, ROW_OFFSET), 'rivet', 'frame_joint_rivets')
    frame_offset, _ = offset_to_line(s, plain)
    layout.add_row(where[skin], frame_offset[skin], arc[skin], (0,), 'rivet', 'frame_rivets')
    break_offset, _ = offset_to_line(s, breaks)
    near_break = skin & (abs(break_offset) < .05)
    layout.add_row(where[near_break], abs(break_offset[near_break]), arc[near_break], (ROW_OFFSET,), 'rivet',
                   'section_break_rivets')
    upper, lower = lap_distances(x, s, z, lines)
    nearer_lower = abs(lower) < abs(upper)
    across = np.where(nearer_lower, lower, upper)
    bay = np.searchsorted(knots, s)
    a = np.radians(np.where(nearer_lower, FUSELAGE_SEAMS_DEG[1], FUSELAGE_SEAMS_DEG[0]))
    side = pos[:, 0] < 0  # the right side's lap joints are the mirror planes
    in_plane = abs(-np.sin(a) * np.where(side, -1, 1) * normal[:, 0] + np.cos(a) * normal[:, 2]) > .9
    lap = skin & (s > knots[0]) & (s < knots[-1]) & ~in_plane
    layout.add_seam(where[lap], across[lap], 'lap_joint_seam', (4 * bay + 2 * nearer_lower + side)[lap])
    layout.add_row(where[lap], across[lap], s[lap], (-ROW_OFFSET, ROW_OFFSET), 'rivet', 'lap_joint_rivets')
    lap_cell = (lower > 0).astype(np.int64) + (upper > 0)
    layout.cell[where] = np.where(panel_cell > 0, panel_cell, joint_cell * 4 + lap_cell)
    report['fuselage'] = {'frames': len(lines['frames']), 'butt_joints_s': [round(j, 3) for j in joints],
                          'riveted_frames_s': [round(f, 3) for f in plain],
                          'section_breaks_s': [round(float(b), 3) for b in breaks],
                          'lap_joints_deg': list(FUSELAGE_SEAMS_DEG),
                          'lap_joint_bays_s': [round(k, 3) for k in knots],
                          'lap_joint_centre_z': [round(float(zc), 4) for zc in lines['knot_zc']]}


def wing(layout, where, pos, normal, structure, report):
    """Spar joints are straight in plan from the visible root to the crank rib, and from there to the tip, where a
    chordwise rib joint on the leading-edge flap's inboard end closes the panels either side of the crank."""
    x, y = abs(pos[:, 0]), pos[:, 1]
    profile = np.array(structure['wing_profile'])
    sections = structure['wing_sections']
    rib_x = min(row[1] for row in structure['wing_surfaces'] if row[0].startswith('lef'))
    knots_x = [sections[1][1], rib_x, sections[-1][1]]  # the first row is buried in the fillet
    le_k = np.interp(knots_x, profile[:, 1], profile[:, 0]) - structure['S0']
    chord_k = np.interp(knots_x, profile[:, 1], profile[:, 3])
    spars = structure['spars']
    plan = []  # signed distance in plan, positive aft, to each spar's straight pieces
    for f in (spars['front_f'], spars['rear_f']):
        line = polyline(x, knots_x, le_k + f * chord_k)
        slope = np.where(x < rib_x, (le_k[1] - le_k[0] + f * (chord_k[1] - chord_k[0])) / (knots_x[1] - knots_x[0]),
                         (le_k[2] - le_k[1] + f * (chord_k[2] - chord_k[1])) / (knots_x[2] - knots_x[1]))
        plan.append((y - line) / np.hypot(1, slope))
    outboard = (x > rib_x).astype(np.int64)
    rear = abs(plan[1]) < abs(plan[0])
    across = np.where(rear, plan[1], plan[0])
    layout.add_seam(where, across, 'spar_seam', 2 * rear + outboard)
    layout.add_row(where, across, x, (-ROW_OFFSET, ROW_OFFSET), 'screw', 'spar_screws')
    layout.add_seam(where, x - rib_x, 'crank_rib_seam')
    layout.add_row(where, x - rib_x, y, (-ROW_OFFSET, ROW_OFFSET), 'rivet', 'crank_rib_rivets')
    x0, x1 = .62, profile[-1, 1] - .06
    ribs = np.linspace(x0, x1, int((x1 - x0) / spars['rib_pitch']) + 1)
    ribs = ribs[abs(ribs - rib_x) > .1]  # the crank rib's joint rows stand in for the rib beside it
    rib_offset, _ = offset_to_line(x, ribs)
    box = (plan[0] > .02) & (plan[1] < -.02)
    layout.add_row(where[box], rib_offset[box], y[box], (0,), 'rivet', 'rib_rivets')
    le_f = np.interp(FUEL_FILLER['x'], profile[:, 1], profile[:, 0]) - structure['S0']
    c_f = np.interp(FUEL_FILLER['x'], profile[:, 1], profile[:, 3])
    centre = np.array([FUEL_FILLER['x'], le_f + FUEL_FILLER['chord_fraction'] * c_f])
    ring = np.hypot(x - centre[0], y - centre[1]) - FUEL_FILLER['radius']
    upper = (normal[:, 2] > .5) & (abs(ring) < .03)
    layout.add_seam(where[upper], ring[upper], 'fuel_filler_seam')
    angle = np.arctan2(y - centre[1], x - centre[0]) * (FUEL_FILLER['radius'] + .014)
    layout.add_row(where[upper], ring[upper], angle[upper], (.014,), 'screw', 'fuel_filler_screws')
    cell = (plan[0] > 0).astype(np.int64) + (plan[1] > 0)
    layout.cell[where] = cell + 3 * outboard + 6 * ((cell > 0) & (normal[:, 2] < 0))
    report['wing'] = {'spar_fractions': [spars['front_f'], spars['rear_f']], 'spar_knots_x': knots_x,
                      'crank_rib_x': rib_x, 'ribs_x': [round(float(r), 3) for r in ribs], 'fuel_filler': FUEL_FILLER}


def lifting(layout, where, pos, name, report):
    axis, joints, rows, rib_pitch = LIFTING[name]
    span = abs(pos[:, 0]) if axis == 'x' else pos[:, 2]
    y = pos[:, 1]
    fraction, chord = chord_fraction(span, y)
    _, cell = offset_to_line(fraction, sorted(joints + rows))
    if joints:
        across, index = nearest_line(fraction, joints)
        across = across * chord
        side = (pos[:, 0] < 0) if axis == 'x' else np.zeros(len(y), bool)  # mirrored halves are separate planes
        layout.add_seam(where, across, name + '_seam', 2 * index + side)
        layout.add_row(where, across, span, (-ROW_OFFSET, ROW_OFFSET), 'rivet', name + '_joint_rivets')
    if rows:
        across = offset_to_line(fraction, rows)[0] * chord
        layout.add_row(where, across, span, (0,), 'rivet', name + '_spar_rivets')
    if rib_pitch:
        start = span.min() + rib_pitch / 2
        ribs = np.arange(start, span.max(), rib_pitch)
        if len(ribs):
            rib_offset, _ = offset_to_line(span, ribs)
            inside = (fraction > .1) & (fraction < .9)
            layout.add_row(where[inside], rib_offset[inside], y[inside], (0,), 'rivet', name + '_rib_rivets')
    layout.cell[where] = cell
    report[name] = {'span_axis': axis, 'joint_fractions': list(joints), 'row_fractions': list(rows),
                    'rib_pitch_m': rib_pitch, 'edges': 'straight leading and trailing edges fitted to the texels'}


def layout_fields(position, normal, part, names, domain, structure):
    """Seam, rivet and screw profiles (0 to 1), panel ids, seam pieces and a report for every texel in `domain`."""
    where = np.flatnonzero(domain)
    pos, nrm = position.reshape(-1, 3)[where].astype(np.float64), normal.reshape(-1, 3)[where].astype(np.float64)
    ids = part.ravel()[where]
    part_names = np.array([''] + list(names))[ids]
    layout = Layout(len(where))
    report = {}
    breaks = skin_breaks(position, part, names, structure['S0'])
    family = np.array([name.startswith(FUSELAGE) for name in [''] + list(names)])[ids]
    fuselage(layout, np.flatnonzero(family), pos[family], nrm[family], part_names[family], structure,
             breaks, report)
    selected = part_names == 'wing_skin_L'
    wing(layout, np.flatnonzero(selected), pos[selected], nrm[selected], structure, report)
    for name in LIFTING:
        selected = part_names == name
        if selected.any():
            lifting(layout, np.flatnonzero(selected), pos[selected], name, report)
    seam = np.zeros(part.size, np.float32)
    seam[where] = bump(layout.seam, SEAM_HALF_WIDTH)
    fields = {'seam': seam.reshape(part.shape)}
    for kind, spec in FASTENERS.items():
        values = np.zeros(part.size, np.float32)
        values[where] = bump(layout.fastener[kind], spec['radius'])
        fields[kind] = values.reshape(part.shape)
    # Panel ids follow the seams: the fuselage skin is one sheet across its part boundaries (group 0).
    panel = np.zeros(part.size, np.int64)
    panel[where] = np.where(family, 0, ids.astype(np.int64)) * 4096 + layout.cell
    fields['panel'] = panel.reshape(part.shape)
    for key, values, empty in (('seam_distance', layout.seam, np.inf), ('seam_id', layout.seam_id, -1)):
        full = np.full(part.size, empty, values.dtype)
        full[where] = values
        fields[key] = full.reshape(part.shape)
    report.update({'seam_half_width_m': SEAM_HALF_WIDTH, 'fasteners': FASTENERS, 'row_offset_m': ROW_OFFSET,
                   'depth_mm': DEPTH_MM, 'feature_texels': layout.counts, 'seam_pieces': layout.seam_names,
                   'policy': 'flat panel faces; relief only at joints, fastener rows, access panels and the fuel filler; '
                             'every seam a plane section ending on another seam or a physical edge'})
    return fields, report


def bare_aft(position, part, names, structure):
    """Weight 1 on the unpainted aft fuselage: the skin aft of the BARE_AFT_JOINT_S butt joint and below both upper
    lap joints, the speed brakes (panels inside it) and the nozzle. Its edges are those seams, and the material
    changes across the groove's width, so the edge sits in the joint with no texel step."""
    lines = fuselage_lines(structure, skin_breaks(position, part, names, structure['S0']))
    if BARE_AFT_JOINT_S not in lines['joints']:
        raise ValueError(f'The bare aft fuselage must start on a butt joint {lines["joints"]}')
    x, s, z = abs(position[..., 0]), position[..., 1] + structure['S0'], position[..., 2]
    upper = lap_distances(x, s, z, lines)[FUSELAGE_SEAMS_DEG.index(45)]
    ramp = lambda d: (lambda t: t * t * (3 - 2 * t))(np.clip(d / (2 * SEAM_HALF_WIDTH) + .5, 0, 1))
    skin = np.isin(part, [i + 1 for i, name in enumerate(names) if name.startswith(FUSELAGE)])
    whole = np.isin(part, [i + 1 for i, name in enumerate(names) if name.startswith(('speed_brake_', 'nozzle'))])
    return np.where(skin, ramp(s - BARE_AFT_JOINT_S) * ramp(-upper), whole.astype(np.float64))


def surface_height(fields, px_per_m):
    """Height in texels from the feature profiles: grooves and dimpled fastener heads."""
    mm = -(DEPTH_MM['seam'] * fields['seam'] + DEPTH_MM['rivet'] * fields['rivet'] + DEPTH_MM['screw'] * fields['screw'])
    return mm * px_per_m / 1000


def tangent_normal(height, used, strength=1.8):
    # Image rows run opposite to UV V, so the tangent Y slope has the opposite sign to X.
    gy, gx = np.gradient(height)
    normal = np.stack((-gx * strength, gy * strength, np.ones_like(height)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    normal[~used] = (0, 0, 1)
    return normal * 0.5 + 0.5
