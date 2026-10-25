"""Exact distances between triangle meshes, and the rotations the clearance checks pose meshes with.

A mesh is (verts, tris): an (n, 3) float array and an (m, 3) index array. Two meshes are distance zero apart when a
triangle of one crosses a triangle of the other; otherwise their distance is the least of every vertex-to-triangle
and edge-to-edge distance between them, which is the exact minimum over both surfaces.
"""
import numpy as np

CHUNK = 1_000_000  # pairs per vectorised batch


def quat_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def axis_quat(axis, degrees):
    h = np.radians(degrees) / 2
    return tuple(np.asarray(axis, float) * np.sin(h)) + (float(np.cos(h)),)


def bounds(verts):
    return verts.min(0), verts.max(0)


def box_gap(a, b):
    """Distance between two axis-aligned boxes (lo, hi); 0 when they overlap."""
    d = np.maximum(0.0, np.maximum(a[0] - b[1], b[0] - a[1]))
    return float(np.sqrt((d * d).sum()))


def edges(verts, tris):
    """Each distinct edge of the triangles once, without zero-length ones."""
    e = np.unique(np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1), axis=0)
    return e[np.linalg.norm(verts[e[:, 0]] - verts[e[:, 1]], axis=1) > 1e-9]


def _pairs(n, m):
    """Row ranges so each batch holds at most CHUNK of the n x m pairs."""
    step = max(1, CHUNK // max(1, m))
    return [(i, min(n, i + step)) for i in range(0, n, step)]


def point_triangle(p, a, b, c):
    """Distances (n, m) from points p (n, 3) to triangles a, b, c (m, 3) each (Ericson 5.1.5, vectorised)."""
    p = p[:, None, :]
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = p - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = p - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        den = 1.0 / (va + vb + vc)
        v, w = vb * den, vc * den
        q = a + ab * v[..., None] + ac * w[..., None]  # inside the face
        t_ab = d1 / (d1 - d3)
        t_ac = d2 / (d2 - d6)
        t_bc = (d4 - d3) / ((d4 - d3) + (d5 - d6))
    regions = [
        (d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (d6 >= 0) & (d5 <= d6),
        (vc <= 0) & (d1 >= 0) & (d3 <= 0), (vb <= 0) & (d2 >= 0) & (d6 <= 0),
        (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0),
    ]
    points = [np.broadcast_to(a, q.shape), np.broadcast_to(b, q.shape), np.broadcast_to(c, q.shape),
              a + ab * t_ab[..., None], a + ac * t_ac[..., None], b + (c - b) * t_bc[..., None]]
    for mask, at in zip(regions[::-1], points[::-1]):  # the first region that holds wins, as in the scalar version
        q = np.where(mask[..., None], at, q)
    return np.sqrt(((p - q) ** 2).sum(-1))


def segment_segment(p1, q1, p2, q2):
    """Distances (n, m) between segments p1q1 (n, 3) and p2q2 (m, 3) (Ericson 5.1.9, vectorised)."""
    p1, q1 = p1[:, None, :], q1[:, None, :]
    d1, d2 = q1 - p1, q2 - p2
    r = p1 - p2
    a, e, f = (d1 * d1).sum(-1), (d2 * d2).sum(-1), (d2 * r).sum(-1)
    c, b = (d1 * r).sum(-1), (d1 * d2).sum(-1)
    denom = a * e - b * b
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(denom > 1e-12, np.clip((b * f - c * e) / denom, 0, 1), 0.0)
        t = (b * s + f) / e
        s = np.where(t < 0, np.clip(-c / a, 0, 1), np.where(t > 1, np.clip((b - c) / a, 0, 1), s))
    t = np.clip(t, 0, 1)
    c1, c2 = p1 + d1 * s[..., None], p2 + d2 * t[..., None]
    return np.sqrt(((c1 - c2) ** 2).sum(-1))


def segments_cross(p, q, a, b, c):
    """(n, m) true where segment pq (n, 3) crosses triangle abc (m, 3) (Moller-Trumbore, vectorised)."""
    d = (q - p)[:, None, :]
    e1, e2 = b - a, c - a
    h = np.cross(d, e2)
    det = (e1 * h).sum(-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / det
        s = p[:, None, :] - a
        u = (s * h).sum(-1) * inv
        k = np.cross(s, e1)
        v = (d * k).sum(-1) * inv
        t = (e2 * k).sum(-1) * inv
    return (np.abs(det) > 1e-12) & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= 1)


def _near(verts, tris, box, reach):
    """The triangles of a mesh within reach of a box (lo, hi), by their own boxes, without zero-area ones."""
    t = verts[tris]
    lo, hi = t.min(1), t.max(1)
    area = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
    keep = np.all((hi >= box[0] - reach) & (lo <= box[1] + reach), axis=1) & (area > 1e-12)
    return tris[keep]


def _candidates(a, b, reach):
    """Pairs of primitives whose boxes can be within reach, in batches of at most CHUNK pairs."""
    alo, ahi = a.min(1), a.max(1)
    blo, bhi = b.min(1), b.max(1)
    # Round outwards so a pair on the distance boundary is still tested by the original formulas.
    reach = np.nextafter(reach, np.inf)
    for i, j in _pairs(len(a), len(b)):
        keep = np.ones((j - i, len(b)), bool)
        for axis in range(3):
            keep &= ahi[i:j, axis, None] >= blo[:, axis] - reach
            keep &= alo[i:j, axis, None] <= bhi[:, axis] + reach
        rows, cols = np.nonzero(keep)
        if len(rows):
            yield rows + i, cols


def mesh_distance(a, b, reach):
    """Exact distance between meshes a and b when it is under reach; otherwise a lower bound of at least reach."""
    (va, ta), (vb, tb) = a, b
    gap = box_gap(bounds(va), bounds(vb))
    if gap >= reach:
        return gap
    ta, tb = _near(va, ta, bounds(vb), reach), _near(vb, tb, bounds(va), reach)
    if len(ta) == 0 or len(tb) == 0:
        return reach
    best = reach
    ea, eb = edges(va, ta), edges(vb, tb)
    for (pv, pt, e), (qv, qt) in (((va, ta, ea), (vb, tb)), ((vb, tb, eb), (va, ta))):
        points = pv[np.unique(pt)]
        triangles = qv[qt]
        for rows, cols in _candidates(points[:, None, :], triangles, best):
            A, B, C = (triangles[cols, k, None, :] for k in range(3))
            best = min(best, float(point_triangle(points[rows], A, B, C).min()))
        for rows, cols in _candidates(pv[e], triangles, best):
            A, B, C = (triangles[cols, k, None, :] for k in range(3))
            if segments_cross(pv[e[rows, 0]], pv[e[rows, 1]], A, B, C).any():
                return 0.0
    for rows, cols in _candidates(va[ea], vb[eb], best):
        best = min(best, float(segment_segment(va[ea[rows, 0]], va[ea[rows, 1]],
                                              vb[eb[cols, 0], None, :], vb[eb[cols, 1], None, :]).min()))
    return best


def segment_distance(p, q, mesh):
    """Exact distance from segment pq to a mesh: 0 when it crosses a triangle."""
    verts, tris = mesh
    tris = _near(verts, tris, (np.minimum(p, q), np.maximum(p, q)), np.inf)
    A, B, C = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    seg_p, seg_q = np.asarray([p], float), np.asarray([q], float)
    if segments_cross(seg_p, seg_q, A, B, C).any():
        return 0.0
    e = edges(verts, tris)
    return float(min(point_triangle(np.asarray([p, q], float), A, B, C).min(),
                     segment_segment(seg_p, seg_q, verts[e[:, 0]], verts[e[:, 1]]).min()))
