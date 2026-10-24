"""Panel seam checks on the composed skin: the seams close into panels, and every seam is straight.

Run from the repository root after `compose_skin.py compose`:  python art/textures/panel_checks.py

Closure works on the shipped groove field alone. Texels off the grooves are joined into panels across UV cuts and
across the fuselage skin's part boundaries (one loft, so one sheet) wherever the surface is continuous in 3D; part
boundaries elsewhere and creases are physical edges. A seam texel dangles when the panel on one side of it is the
panel on the other side, which happens all along a seam that stops short instead of ending on another seam or edge.
Straightness finds the thinnest slab holding each straight seam piece's centreline texels and reports its half width.
"""
import json
import sys

import numpy as np
from scipy.ndimage import label
from scipy.optimize import minimize
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from rasterize import OUT, PX_PER_M, extend_geometry
from panels import FUSELAGE, SEAM_HALF_WIDTH, layout_fields

STRUCTURE = OUT.parents[1] / 'p9b-round2/structure.json'
GROOVE = .25  # a texel at least this deep in the seam profile (2.7 mm from a seam's centre) belongs to the seam
CENTRE_M = .0005  # centreline texels, for straightness
JOIN_M = .004  # texels this close in 3D across a UV cut or sheet boundary are one surface
SIDE_M = .015  # how far either side of a seam texel the panels are sampled
EDGE_M = .008  # seam texels this close to a physical edge run along it, and have only one side
DANGLING_MAX_M = .02  # the longest dangling run allowed (corner texels at a T junction)
STRAIGHT_MAX_MM = 1.0  # centreline texels sit within CENTRE_M of the seam; the rest is the seam's own deviation
CLOSED_OUTLINES = ('access_panel_seam', 'fuel_filler_seam')  # rounded outlines, closed by themselves
MIN_PANEL_M2 = .0025


def groups_of(names):
    """Sheet id per part id: the fuselage skin parts are one sheet, every other part its own."""
    return np.array([0] + [0 if name.startswith(FUSELAGE) else i for i, name in enumerate(names, 1)])


def closure(position, normal, part, names, groove):
    used = part > 0
    off = used & (groove < GROOVE)
    sheet = groups_of(names)[part]
    labels = np.zeros(part.shape, np.int64)
    islands = np.zeros(part.shape, np.int64)
    count = island_count = 0
    for pid in np.unique(part[used]):
        mine = part == pid
        ys, xs = np.nonzero(mine)
        box = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        lab, n = label(off[box] & mine[box])
        labels[box][lab > 0] = lab[lab > 0] + count
        count += n
        lab, n = label(mine[box])
        islands[box][lab > 0] = lab[lab > 0] + island_count
        island_count += n
    # Island border texels: a 4-neighbour outside the island.
    border = np.zeros(part.shape, bool)
    for axis in (0, 1):
        for step in (1, -1):
            border |= used & (np.roll(islands, step, axis) != islands)
    edges, boundary_points, summary = [], [], {}
    for group in np.unique(sheet[used]):
        mine = off & (sheet == group)
        points, normals = position[mine].astype(np.float64), normal[mine].astype(np.float64)
        tree = cKDTree(points)
        own_labels, own_islands = labels[mine], islands[mine]
        rim = np.flatnonzero(border[mine])
        distance, index = tree.query(points[rim], k=12, distance_upper_bound=JOIN_M)
        valid = np.isfinite(distance)
        index = np.where(valid, index, 0)
        across = valid & (own_islands[index] != own_islands[rim][:, None])
        across &= (normals[index] * normals[rim][:, None]).sum(-1) > .5
        rows, cols = np.nonzero(across)
        edges.append(np.stack((own_labels[rim][rows], own_labels[index[rows, cols]])))
        # Rim texels with no surface across them are physical edges (part boundaries, open edges, creases).
        boundary_points.append((group, points[rim[~across.any(1)]]))
    edges = np.concatenate(edges, axis=1)
    graph = coo_matrix((np.ones(edges.shape[1]), (edges[0], edges[1])), shape=(count + 1, count + 1))
    _, root = connected_components(graph, directed=False)
    panel = np.where(off, root[labels], -1)
    seam_texels = used & (groove >= GROOVE)
    dangling = []
    for group, edge_points in boundary_points:
        mine = off & (sheet == group)
        points = position[mine].astype(np.float64)
        tree = cKDTree(points)
        roots = panel[mine]
        seam = seam_texels & (sheet == group)
        seam_points = position[seam].astype(np.float64)
        if not len(seam_points):
            continue
        _, index = tree.query(seam_points, k=96, distance_upper_bound=SIDE_M)
        found = index < len(points)
        sampled = np.where(found, roots[np.minimum(index, len(points) - 1)], -1)
        sampled.sort(axis=1)
        distinct = ((np.diff(sampled, axis=1) != 0) & (sampled[:, 1:] >= 0)).sum(1) + (sampled[:, 0] >= 0)
        near_edge = np.zeros(len(seam_points), bool)
        if len(edge_points):
            near_edge = cKDTree(edge_points).query(seam_points, distance_upper_bound=EDGE_M)[0] < EDGE_M
        flagged = (distinct <= 1) & ~near_edge
        dangling.append(np.flatnonzero(seam)[flagged])
    dangling = np.concatenate(dangling) if dangling else np.zeros(0, np.int64)
    areas = np.bincount(panel[panel >= 0]) / PX_PER_M ** 2
    summary['panels'] = int((areas >= MIN_PANEL_M2).sum())
    summary['dangling_texels'] = int(len(dangling))
    return panel, dangling, summary


def dangling_runs(position, part, names, dangling, seam_id, seam_names, S0):
    """Group dangling texels into runs 8 mm apart; each run's length, place and seam pieces."""
    if not len(dangling):
        return []
    points = position.reshape(-1, 3)[dangling].astype(np.float64)
    pairs = cKDTree(points).query_pairs(.008, output_type='ndarray')
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(points),) * 2)
    _, run = connected_components(graph, directed=False)
    runs = []
    for r in np.unique(run):
        p = points[run == r]
        ids = seam_id.ravel()[dangling[run == r]]
        extent = np.linalg.norm(p.max(0) - p.min(0))
        runs.append({'length_m': round(float(extent), 4), 'texels': int(len(p)),
                     'centre_s_x_z': [round(float(p[:, 1].mean() + S0), 3), round(float(p[:, 0].mean()), 3),
                                      round(float(p[:, 2].mean()), 3)],
                     'parts': sorted({names[i - 1] for i in part.ravel()[dangling[run == r]]}),
                     'seams': sorted({seam_names[i] for i in ids if i >= 0})})
    return sorted(runs, key=lambda entry: -entry['length_m'])


def plane_deviation(points):
    """Farthest point from the best plane through `points`: half the thickness of the thinnest slab holding them all.

    A least-squares plane is only the starting guess. Where a seam runs along the texel grid, its centreline texels
    come in clusters along a near-line, and the least-squares plane tilts about that line by more than the band.
    """
    q = points - points.mean(0)
    start = np.linalg.svd(q, full_matrices=False)[2][-1]

    def half_width(angles):
        a, b = angles
        r = q @ np.array([np.sin(a) * np.cos(b), np.sin(a) * np.sin(b), np.cos(a)])
        return (r.max() - r.min()) / 2

    angles = [np.arccos(np.clip(start[2], -1, 1)), np.arctan2(start[1], start[0])]
    best = half_width(angles)
    for _ in range(3):  # restarts: the slab width is not smooth in the angles
        found = minimize(half_width, angles, method='Nelder-Mead', options={'xatol': 1e-9, 'fatol': 1e-10})
        if found.fun >= best - 1e-9:
            break
        best, angles = found.fun, found.x
    return best


def straightness(position, seam_distance, seam_id, seam_names, used):
    """Farthest centreline texel from its piece's best plane, in mm, for every straight seam piece."""
    centre = used & (seam_distance < CENTRE_M) & (seam_id >= 0)
    points, ids = position[centre].astype(np.float64), seam_id[centre]
    result = {}
    for i in np.unique(ids):
        name = seam_names[i]
        p = points[ids == i]
        if name.startswith(CLOSED_OUTLINES) or len(p) < 20:
            continue
        result[name] = round(float(plane_deviation(p) * 1000), 2)
    return result


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
    panel, dangling, report = closure(pos, normal, part, names, groove)
    runs = dangling_runs(pos, part, names, dangling, fields['seam_id'], layout_report['seam_pieces'], structure['S0'])
    straight = straightness(pos, fields['seam_distance'], fields['seam_id'], layout_report['seam_pieces'], used)
    worst = max(straight.items(), key=lambda item: item[1])
    report.update({'dangling_runs': runs[:40], 'dangling_runs_count': len(runs),
                   'longest_dangling_m': runs[0]['length_m'] if runs else 0.0,
                   'straightness_max_mm': worst[1], 'straightness_worst_piece': worst[0],
                   'straightness_mm': straight, 'seam_half_width_m': SEAM_HALF_WIDTH,
                   'thresholds': {'dangling_max_m': DANGLING_MAX_M, 'straight_max_mm': STRAIGHT_MAX_MM,
                                  'groove': GROOVE, 'join_m': JOIN_M, 'side_m': SIDE_M, 'edge_m': EDGE_M}})
    if write:
        (OUT / 'panel_checks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"panel seams: {report['panels']} panels, {len(runs)} dangling runs (longest "
          f"{report['longest_dangling_m'] * 1000:.0f} mm), every straight seam within {worst[1]:.2f} mm of its plane (worst {worst[0]})")
    problems = []
    if runs and runs[0]['length_m'] > DANGLING_MAX_M:
        problems += [f"seam stops mid-panel: {r['length_m'] * 1000:.0f} mm at s,x,z {r['centre_s_x_z']} on "
                     f"{'/'.join(r['parts'])} ({', '.join(r['seams'])})" for r in runs if r['length_m'] > DANGLING_MAX_M]
    problems += [f'{name} strays {mm:.2f} mm from its plane' for name, mm in straight.items() if mm > STRAIGHT_MAX_MM]
    if problems:
        raise ValueError('panel seams: ' + '; '.join(problems[:20]) + (f' ({len(problems)} in all)' if len(problems) > 20 else ''))
    print('PANEL SEAM CHECK PASS')
    return report


if __name__ == '__main__':
    check(write='--no-write' not in sys.argv)
