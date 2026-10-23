"""Skin relief drawn from the airframe's own panel layout: seams, fasteners and closed access panels.

Every feature is a distance in world metres measured at texel centres, so a line keeps one width in texels and stays
continuous across UV cuts and mirrored islands. Panel faces between features are flat. Frames, spars, ribs and the
fuselage body sections come from structure.json (art/blender/pilot2_skin.py structure); the fin, stabilator, ventral
fin and control surfaces take their chord from their own baked texels.
"""
import numpy as np

# World x, longitudinal y, z; the port is shut and has no gun opening.
ACCESS_PANELS = (
    ('closed_gun_port', ('skin_forward_L', 'skin_forward_R'), -3.95, 0.15, 0.48, 0.24),
    ('aux_door', ('skin_mid_L', 'skin_mid_R'), 1.55, 0.32, 0.45, 0.32),
    ('under_vent', ('skin_aft_L', 'skin_aft_R'), 4.35, -0.28, 0.52, 0.24),
)
# Art decision: a 0.11 m fuel filler on the upper fixed wing, inside the wing tank box.
FUEL_FILLER = {'x': 2.45, 'chord_fraction': .42, 'radius': .055}

SEAM_HALF_WIDTH = .0045  # m: a 1 mm joint reads as a line about three texels wide at 300 px/m
FASTENERS = {'rivet': {'radius': .0042, 'pitch': .028},  # 8.4 mm universal heads
             'screw': {'radius': .0055, 'pitch': .045}}  # access-panel and box-cover screws
ROW_OFFSET = .015  # m from a joint to each fastener row
DEPTH_MM = {'seam': .7, 'rivet': .3, 'screw': .45}

FUSELAGE = ('skin_forward', 'skin_mid', 'skin_aft', 'dorsal_cover', 'intake_duct')
# Longitudinal lap joints, degrees above the body lobe's centre: on the corner longerons, 45 degrees off vertical
# (internals.py stringers). Other stringers carry no row, so the bays between stay flat.
FUSELAGE_SEAMS_DEG = (45, -45)
JOINT_EVERY = 2  # a skin butt joint at every second frame; the frames between carry one rivet row
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


def row_distance(across, along, offset, pitch):
    """Distance to the nearest fastener of a row `offset` from a line, spaced `pitch` along it."""
    return np.hypot(across - offset, np.abs((along / pitch + .5) % 1 - .5) * pitch)


class Layout:
    """Per-texel feature distances over the evaluated texels; the nearest feature of each kind wins."""

    def __init__(self, count):
        self.seam = np.full(count, np.inf)
        self.fastener = {kind: np.full(count, np.inf) for kind in FASTENERS}
        self.cell = np.zeros(count, np.int64)
        self.counts = {}

    def add_seam(self, where, distance, name):
        self.seam[where] = np.minimum(self.seam[where], abs(distance))
        self.counts[name] = self.counts.get(name, 0) + int((abs(distance) < SEAM_HALF_WIDTH).sum())

    def add_row(self, where, across, along, offsets, kind, name):
        pitch = FASTENERS[kind]['pitch']
        distance = np.min([row_distance(across, along, offset, pitch) for offset in offsets], axis=0)
        self.fastener[kind][where] = np.minimum(self.fastener[kind][where], distance)
        self.counts[name] = self.counts.get(name, 0) + int((distance < FASTENERS[kind]['radius']).sum())


def chord_fraction(span, y, bin_m=.02):
    """Leading and trailing edge of a lifting part along its span, measured from its own texels."""
    edges = np.arange(span.min(), span.max() + bin_m, bin_m)
    index = np.clip(np.digitize(span, edges) - 1, 0, len(edges) - 1)
    le, te = np.full(len(edges), np.inf), np.full(len(edges), -np.inf)
    np.minimum.at(le, index, y)
    np.maximum.at(te, index, y)
    valid = np.isfinite(le) & (te - le > .02)
    centres = edges[valid] + bin_m / 2
    le_at, te_at = np.interp(span, centres, le[valid]), np.interp(span, centres, te[valid])
    return (y - le_at) / np.maximum(te_at - le_at, 1e-3), te_at - le_at


def strake_mask(x, half_width, normal):
    return (x > half_width + .05) & (abs(normal[:, 2]) > .55)


def fuselage(layout, where, pos, normal, part_names, structure, breaks, report):
    x, y, z = abs(pos[:, 0]), pos[:, 1], pos[:, 2]
    s = y + structure['S0']
    sections = np.array(structure['fuselage_sections'])
    zmid = np.interp(s, sections[:, 0], sections[:, 1])
    half_width = np.interp(s, sections[:, 0], sections[:, 2])
    theta, radius = np.arctan2(z - zmid, x), np.hypot(x, z - zmid)
    arc = theta * radius
    frame = structure['frames']
    frames = np.arange(frame['s0'], frame['s1'] + 1e-6, frame['pitch'])
    clear = [f for f in frames if min(abs(f - b) for b in breaks) > .15]
    joints = [f for i, f in enumerate(frames) if i % JOINT_EVERY == 1 and f in clear]
    plain = [f for f in clear if f not in joints]
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
        layout.add_seam(where[near], edge[near], 'access_panel_seam')
        layout.add_row(where[near], edge[near], along[near], (-ROW_OFFSET,), 'screw', 'access_panel_screws')
        covered |= on & (edge < -.004)
        panel_cell[on & (edge < 0)] = 100 + index
    # The wing-root strake on the mid skins takes the wing layout instead.
    covered |= strake_mask(x, half_width, normal)
    body = (x <= half_width + .03) & ~covered
    offset, joint_cell = offset_to_line(s, joints)
    layout.add_seam(where[body], offset[body], 'frame_joint_seam')
    layout.add_row(where[body], offset[body], arc[body], (-ROW_OFFSET, ROW_OFFSET), 'rivet', 'frame_joint_rivets')
    frame_offset, _ = offset_to_line(s, plain)
    layout.add_row(where[~covered], frame_offset[~covered], arc[~covered], (0,), 'rivet', 'frame_rivets')
    break_offset, _ = offset_to_line(s, breaks)
    near_break = ~covered & (abs(break_offset) < .05)
    layout.add_row(where[near_break], abs(break_offset[near_break]), arc[near_break], (ROW_OFFSET,), 'rivet',
                   'section_break_rivets')
    lap = body & (s > frames[0]) & (s < frames[-1]) & np.char.startswith(part_names, 'skin_')
    angle, lap_cell = offset_to_line(np.degrees(theta), FUSELAGE_SEAMS_DEG)
    across = np.radians(angle) * radius
    layout.add_seam(where[lap], across[lap], 'lap_joint_seam')
    layout.add_row(where[lap], across[lap], s[lap], (-ROW_OFFSET, ROW_OFFSET), 'rivet', 'lap_joint_rivets')
    layout.cell[where] = np.where(panel_cell > 0, panel_cell, joint_cell * 8 + lap_cell)
    report['fuselage'] = {'frames': len(frames), 'butt_joints_s': [round(float(j), 3) for j in joints],
                          'riveted_frames_s': [round(float(f), 3) for f in plain],
                          'section_breaks_s': [round(float(b), 3) for b in breaks],
                          'lap_joints_deg': list(FUSELAGE_SEAMS_DEG)}


def wing(layout, where, pos, normal, structure, report):
    x, y = abs(pos[:, 0]), pos[:, 1]
    profile = np.array(structure['wing_profile'])
    le = np.interp(x, profile[:, 1], profile[:, 0]) - structure['S0']
    chord = np.interp(x, profile[:, 1], profile[:, 3])
    fraction = (y - le) / chord
    spars = structure['spars']
    offset, cell = offset_to_line(fraction, (spars['front_f'], spars['rear_f']))
    layout.add_seam(where, offset * chord, 'spar_seam')
    layout.add_row(where, offset * chord, x, (-ROW_OFFSET, ROW_OFFSET), 'screw', 'spar_screws')
    x0, x1 = .62, profile[-1, 1] - .06
    ribs = np.linspace(x0, x1, int((x1 - x0) / spars['rib_pitch']) + 1)
    rib_offset, _ = offset_to_line(x, ribs)
    box = (fraction > spars['front_f'] + .01) & (fraction < spars['rear_f'] - .01)
    layout.add_row(where[box], rib_offset[box], y[box], (0,), 'rivet', 'rib_rivets')
    le_f = np.interp(FUEL_FILLER['x'], profile[:, 1], profile[:, 0]) - structure['S0']
    c_f = np.interp(FUEL_FILLER['x'], profile[:, 1], profile[:, 3])
    centre = np.array([FUEL_FILLER['x'], le_f + FUEL_FILLER['chord_fraction'] * c_f])
    ring = np.hypot(x - centre[0], y - centre[1]) - FUEL_FILLER['radius']
    upper = (normal[:, 2] > .5) & (abs(ring) < .03)
    layout.add_seam(where[upper], ring[upper], 'fuel_filler_seam')
    angle = np.arctan2(y - centre[1], x - centre[0]) * (FUEL_FILLER['radius'] + .014)
    layout.add_row(where[upper], ring[upper], angle[upper], (.014,), 'screw', 'fuel_filler_screws')
    layout.cell[where] = cell
    report['wing'] = {'spar_fractions': [spars['front_f'], spars['rear_f']], 'ribs_x': [round(float(r), 3) for r in ribs],
                      'fuel_filler': FUEL_FILLER}


def lifting(layout, where, pos, name, report):
    axis, joints, rows, rib_pitch = LIFTING[name]
    span = abs(pos[:, 0]) if axis == 'x' else pos[:, 2]
    y = pos[:, 1]
    fraction, chord = chord_fraction(span, y)
    _, cell = offset_to_line(fraction, sorted(joints + rows))
    if joints:
        across = offset_to_line(fraction, joints)[0] * chord
        layout.add_seam(where, across, name + '_seam')
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
                    'rib_pitch_m': rib_pitch}


def layout_fields(position, normal, part, names, domain, structure):
    """Seam, rivet and screw profiles (0 to 1), panel ids and a report for every texel in `domain`."""
    where = np.flatnonzero(domain)
    pos, nrm = position.reshape(-1, 3)[where].astype(np.float64), normal.reshape(-1, 3)[where].astype(np.float64)
    ids = part.ravel()[where]
    part_names = np.array([''] + list(names))[ids]
    layout = Layout(len(where))
    report = {}
    s = position[..., 1] + structure['S0']
    breaks = sorted({round(float(edge), 3) for name in names if name.startswith('skin_')
                     for selected in [part == names.index(name) + 1]
                     for edge in (s[selected].min(), s[selected].max())})
    family = np.array([name.startswith(FUSELAGE) for name in [''] + list(names)])[ids]
    fuselage(layout, np.flatnonzero(family), pos[family], nrm[family], part_names[family], structure,
             breaks, report)
    is_wing = part_names == 'wing_skin_L'
    x = abs(pos[:, 0])
    sections = np.array(structure['fuselage_sections'])
    half_width = np.interp(pos[:, 1] + structure['S0'], sections[:, 0], sections[:, 2])
    strake = ((part_names == 'skin_mid_L') | (part_names == 'skin_mid_R')) & strake_mask(x, half_width, nrm)
    selected = is_wing | strake
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
    panel = np.zeros(part.size, np.int64)
    panel[where] = ids.astype(np.int64) * 4096 + layout.cell
    fields['panel'] = panel.reshape(part.shape)
    report.update({'seam_half_width_m': SEAM_HALF_WIDTH, 'fasteners': FASTENERS, 'row_offset_m': ROW_OFFSET,
                   'depth_mm': DEPTH_MM, 'feature_texels': layout.counts,
                   'policy': 'flat panel faces; relief only at joints, fastener rows, access panels and the fuel filler'})
    return fields, report


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
