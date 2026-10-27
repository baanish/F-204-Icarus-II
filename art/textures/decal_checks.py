"""Decal placement check on the composed skin: every decal prints whole on clear skin.

Run from the repository root after `compose_skin.py compose`:  python art/textures/decal_checks.py

Each placement in insignia.PLACEMENTS, on each side, must be:
- whole: every inked source pixel lands on a side-facing or upper-facing texel of its parts, so no edge, crease or leading edge
  clips it;
- clear of physical edges: inked texels stay EDGE_CLEAR_M from every edge of their skin sheet (the canopy cut and
  sill, control-surface gaps, the fin root), found as in panel_checks.py: island rims with no surface across them;
- uncovered: no other part (a canopy frame or sill rail) lies over the ink within COVER_M of the skin;
- clear of panel seams: inked texels stay SEAM_CLEAR_M from every seam centreline, which keeps them off the joint
  and its rivet rows. Real aircraft paint markings over butt and lap joints, so PAINT_OVER may name, per placement,
  the joints it crosses on purpose. An access panel outline never: that panel opens, as canopies and control
  surfaces do, and those are edges above;
- clear of light fittings: inked texels stay FITTING_CLEAR_M from every formation lens and its rim
  (structure.json 'fittings');
- off the Bare Metal high-visibility bands, which every livery's placement shares.
"""
import json
import sys

import numpy as np
from scipy.ndimage import label
from scipy.spatial import cKDTree

from bare_metal import visibility_bands
from insignia import PLACEMENTS, SIDE_FACING, TOP_PARTS, covered, projection_coordinates, sources
from panel_checks import JOIN_M, STRUCTURE, groups_of
from panels import FASTENERS, ROW_OFFSET, layout_fields
from rasterize import OUT, extend_geometry, sample

INK = .01  # decal alpha above which a texel shows ink
EDGE_CLEAR_M = .03
SEAM_CLEAR_M = ROW_OFFSET + FASTENERS['rivet']['radius']  # 19.2 mm: past the rivet heads either side of a joint
COVER_M = (.003, .01, .02, .04)  # heights above an inked texel where another part's skin must not be
COVER_RADIUS_M = .006
FITTING_CLEAR_M = .03
WHOLE_TOLERANCE_M = .006  # nearest side-facing texel to an inked source pixel, in the side projection (2 texels)
# Seam pieces (panels.py names, before any ':') each placement may cross on purpose. Empty: none crosses a seam.
PAINT_OVER = {}


def rim_edges(position, normal, part, names, sheet_parts):
    """Points on the physical edges of the sheet holding `sheet_parts`: island rim texels with no surface across."""
    sheets = groups_of(names)
    group = {sheets[names.index(n) + 1] for n in sheet_parts}
    mine = (part > 0) & np.isin(sheets[part], list(group))
    islands = np.zeros(part.shape, np.int64)
    count = 0
    for pid in np.unique(part[mine]):
        lab, n = label(part == pid)
        islands[lab > 0] = lab[lab > 0] + count
        count += n
    border = np.zeros(part.shape, bool)
    for axis in (0, 1):
        for step in (1, -1):
            border |= mine & (np.roll(islands, step, axis) != islands)
    points, normals, own = position[mine].astype(np.float64), normal[mine].astype(np.float64), islands[mine]
    rim = np.flatnonzero(border[mine])
    distance, index = cKDTree(points).query(points[rim], k=12, distance_upper_bound=JOIN_M)
    valid = np.isfinite(distance)
    index = np.where(valid, index, 0)
    across = valid & (own[index] != own[rim][:, None]) & ((normals[index] * normals[rim][:, None]).sum(-1) > .5)
    return points[rim[~across.any(1)]]


def fitting_points(structure, step=.005):
    """Points every `step` metres over every fitting triangle."""
    points = []
    for triangles in structure.get('fittings', {}).values():
        for a, b, c in np.asarray(triangles, np.float64):
            n = max(2, int(max(np.linalg.norm(b - a), np.linalg.norm(c - a)) / step) + 1)
            i, j = np.mgrid[:n + 1, :n + 1]
            keep = i + j <= n
            points.append(a + np.outer(i[keep] / n, b - a) + np.outer(j[keep] / n, c - a))
    return np.concatenate(points) if points else np.zeros((0, 3))


def whole(position, side_mask, placement, decal, to_uv, side):
    """Inked source pixels with no eligible texel under them in the placement's projection."""
    _, _, _, cy, cz, width, height = placement
    ph, pw = decal.shape[:2]
    stride = max(1, int(.003 / max(width / pw, height / ph)))  # source pixels about 3 mm apart
    v, u = np.mgrid[:ph:stride, :pw:stride]
    ink = decal[v, u, 3] > .5
    u, v = u[ink] / (pw - 1), v[ink] / (ph - 1)
    # Invert the same affine projection used by the compositor, including the right wing's signed x centre and the
    # quarter-turned lettering, whose u follows the second coordinate.
    centre = cy * side if placement[2][0] in TOP_PARTS else cy
    u0, v0 = to_uv(np.array([centre, centre + 1, centre]), np.array([cz, cz, cz + 1]), side)
    step = np.array([[u0[1] - u0[0], u0[2] - u0[0]], [v0[1] - v0[0], v0[2] - v0[0]]])
    y, z = np.array([[centre], [cz]]) + np.linalg.solve(step, np.stack((u - u0[0], v - v0[0])))
    texels = projection_coordinates(position[side_mask], placement)
    if not len(texels):
        return len(y), [cy, cz]
    distance, _ = cKDTree(texels).query(np.stack((y, z), -1), distance_upper_bound=WHOLE_TOLERANCE_M)
    missing = ~np.isfinite(distance)
    return int(missing.sum()), ([round(float(y[missing].mean()), 3), round(float(z[missing].mean()), 3)]
                                if missing.any() else None)


def check(write=True):
    atlas = np.load(OUT / 'atlas_geometry.npz')
    pos, normal, part = atlas['position'][..., :3], atlas['normal'][..., :3], atlas['part']
    names = json.loads((OUT / 'atlas_triangles.json').read_text())['parts']
    structure = json.loads(STRUCTURE.read_text())
    used = part > 0
    groove = np.load(OUT / 'surface_fields.npz')['groove']
    extended_pos, extended_normal, extended_part, domain, _, _ = extend_geometry(pos, normal, part)
    fields, layout_report = layout_fields(extended_pos, extended_normal, extended_part, names, domain, structure)
    if not np.array_equal(fields['seam'], groove):
        raise ValueError('The composed groove field is not the current panel layout; rerun compose_skin.py compose')
    seam_pieces = layout_report['seam_pieces']
    if any(seam.startswith('access_panel_seam') for seams in PAINT_OVER.values() for seam in seams):
        raise ValueError('decal placement: an access panel opens, so no decal may paint over its outline')
    decals = sources()
    fittings = fitting_points(structure)
    fitting_tree = cKDTree(fittings) if len(fittings) else None
    sheets = groups_of(names)
    edges_by_sheet = {}
    report, problems = {}, []
    for placement in PLACEMENTS:
        label_, source, allowed, cy, cz, width, height = placement
        decal = decals[source]
        selected, side, to_uv = covered(pos, normal, part, names, placement, decal)
        top = allowed[0] in TOP_PARTS
        coordinates = projection_coordinates(pos, placement)
        u, v = to_uv(coordinates[..., 0], coordinates[..., 1], side)
        alpha = np.zeros(part.shape, np.float32)
        alpha[selected] = sample(decal, u[selected], v[selected])[:, 3]
        sheet = tuple(sorted({int(sheets[names.index(n) + 1]) for n in allowed}))
        if sheet not in edges_by_sheet:
            edges_by_sheet[sheet] = cKDTree(rim_edges(pos, normal, part, names, allowed))
        edge_tree = edges_by_sheet[sheet]
        own = np.isin(sheets[part], list(sheet)) & used
        reach = max(width, height) / 2 + .1
        across = abs(coordinates[..., 0]) if top else coordinates[..., 0]
        near = used & ~own & (abs(across - cy) < reach) & (abs(coordinates[..., 1] - cz) < reach)
        others = pos[near].astype(np.float64)
        other_tree = cKDTree(others) if len(others) else None
        allowed_seams = set(PAINT_OVER.get(label_, ()))
        entry = {}
        for name, sign in (('left', 1), ('right', -1)):
            ink = selected & (alpha > INK) & (side == sign)
            p, n = pos[ink].astype(np.float64), normal[ink].astype(np.float64)
            missing, where = whole(pos, selected & (side == sign), placement, decal, to_uv, sign)
            edge = float(edge_tree.query(p)[0].min()) if len(p) else 0.0
            cover = 0
            if other_tree is not None and len(p):
                hit = np.zeros(len(p), bool)
                for height_m in COVER_M:
                    hit |= other_tree.query(p + n * height_m, distance_upper_bound=COVER_RADIUS_M)[0] < COVER_RADIUS_M
                cover = int(hit.sum())
            distance, ids = fields['seam_distance'][ink], fields['seam_id'][ink]
            close = distance < SEAM_CLEAR_M
            crossed = sorted({seam_pieces[i] for i in ids[close] if i >= 0})
            barred = [s for s in crossed if s.split(':')[0] not in allowed_seams]
            nearest = seam_pieces[ids[np.argmin(distance)]] if len(distance) and ids[np.argmin(distance)] >= 0 else None
            fitting = float(fitting_tree.query(p)[0].min()) if fitting_tree is not None and len(p) else None
            bands = int((visibility_bands(pos[ink]) > 0).sum())
            missing_key = 'missing_at_xy' if top else 'missing_at_yz'
            entry[name] = {'ink_texels': int(ink.sum()), 'missing_ink_px': missing, missing_key: where,
                           'edge_clear_m': round(edge, 4), 'covered_texels': cover,
                           'seam_clear_m': round(float(distance.min()), 4) if len(distance) else None,
                           'nearest_seam': nearest, 'seams_crossed': crossed,
                           'fitting_clear_m': round(fitting, 4) if fitting is not None else None, 'band_texels': bands}
            where_text = f'{label_} ({name})'
            if not ink.any():
                problems.append(f'{where_text} prints no ink')
                continue
            if missing:
                problems.append(f'{where_text} is clipped: {missing} inked px off its skin near '
                                f'{"x,y" if top else "y,z"} {where}')
            if edge < EDGE_CLEAR_M:
                problems.append(f'{where_text} is {edge * 1000:.0f} mm from a physical edge (min {EDGE_CLEAR_M * 1000:.0f})')
            if cover:
                problems.append(f'{where_text} lies under another part on {cover} texels')
            if barred:
                problems.append(f'{where_text} crosses {", ".join(barred)} ({distance.min() * 1000:.0f} mm from a seam '
                                f'centre, min {SEAM_CLEAR_M * 1000:.1f})')
            if fitting is not None and fitting < FITTING_CLEAR_M:
                problems.append(f'{where_text} is {fitting * 1000:.0f} mm from a light fitting (min {FITTING_CLEAR_M * 1000:.0f})')
            if bands:
                problems.append(f'{where_text} reaches the Bare Metal bands on {bands} texels')
        centre_key = 'centre_xy' if top else 'centre_yz'
        report[label_] = {'source': source, 'parts': list(allowed), centre_key: [cy, cz], 'size_m': [width, height],
                          'paint_over': sorted(allowed_seams), **entry}
    result = {'placements': report, 'fittings': sorted(structure.get('fittings', {})),
              'thresholds': {'ink_alpha': INK, 'edge_clear_m': EDGE_CLEAR_M, 'seam_clear_m': SEAM_CLEAR_M,
                             'cover_heights_m': COVER_M, 'cover_radius_m': COVER_RADIUS_M,
                             'fitting_clear_m': FITTING_CLEAR_M, 'whole_tolerance_m': WHOLE_TOLERANCE_M,
                             'side_facing_normal_x': SIDE_FACING, 'upper_facing_normal_z': SIDE_FACING}, 'problems': problems}
    if write:
        (OUT / 'decal_checks.json').write_text(json.dumps(result, indent=2) + '\n')
    for label_, entry in report.items():
        sides = [entry['left'], entry['right']]
        clear = lambda key: min((s[key] for s in sides if s[key] is not None), default=None)
        fitting = clear('fitting_clear_m')
        print(f"decal {label_}: edge {clear('edge_clear_m') * 1000:.0f} mm, seam {clear('seam_clear_m') * 1000:.0f} mm "
              f"({entry['left']['nearest_seam']})" + (f', fitting {fitting * 1000:.0f} mm' if fitting is not None else ''))
    if problems:
        raise ValueError('decal placement: ' + '; '.join(problems))
    print(f'DECAL PLACEMENT CHECK PASS: {len(report)} placements a side whole, uncovered, '
          f'{EDGE_CLEAR_M * 1000:.0f} mm from edges, {SEAM_CLEAR_M * 1000:.1f} mm from seams')
    return result


if __name__ == '__main__':
    check(write='--no-write' not in sys.argv)
