"""Missile body envelopes for the conformal mounts, measured from the stock missile meshes and colliders.

A body is the missile without its fins: the X fins stand at 45 degrees, so the radius is read only within 20 degrees
of the vertical and horizontal. The envelope is the larger of that radius and the mount's capsule collider, resized
to the body (art/blender/stations.py MOUNTS keeps the result as numbers; run tools/trough_sections.py --profiles to
regenerate them).
"""
import math
from pathlib import Path

import numpy as np

from stores import meshverts
from stores.mounts import load_mount


def mesh_path(index, name):
    path = next((p for p in index.values() if Path(p).name.lower() == name.lower() + ".asset"), None)
    if path is None:
        raise SystemExit(f"no mesh {name}.asset in the game export")
    return path


def slices(verts, tris, ts):
    """Section points of a mesh at each t along its local z."""
    tri = verts[tris]
    for t in ts:
        d = tri[:, :, 2] - t
        pts = []
        for a in range(3):
            b = (a + 1) % 3
            m = (d[:, a] < 0) != (d[:, b] < 0)
            f = d[m, a] / (d[m, a] - d[m, b])
            pts.append(tri[m, a] + (tri[m, b] - tri[m, a]) * f[:, None])
        yield t, np.concatenate(pts)


def body_radius(index, mesh, step=0.02):
    """[(t, r)] of the missile mesh's body along its own z, nose at +z."""
    path = mesh_path(index, mesh)
    v = np.array(meshverts.positions(path))
    tris = np.asarray(meshverts.triangles(path))
    ts = np.arange(v[:, 2].min() + 0.002, v[:, 2].max() - 0.002, step)
    out = []
    for t, pts in slices(v, tris, ts):
        ang = np.degrees(np.arctan2(pts[:, 1], pts[:, 0])) % 90
        body = pts[(ang < 20) | (ang > 70)]
        if len(body):  # a slice can miss the body's few vertices near a tip; skip it rather than read 0
            out.append((float(t), float(np.hypot(body[:, 0], body[:, 1]).max())))
    return [(float(v[:, 2].min()), 0.0)] + out + [(float(v[:, 2].max()), 0.0)]


def capsule(root, index, mount, missile_node):
    """The stock mount's capsule on the missile, in the missile's own frame: (centre z, height)."""
    _, colliders = load_mount(root, index, mount)
    cap = next(c for c in colliders if c["kind"] == "Capsule" and c["name"].endswith("/" + missile_node))
    return cap


def envelope(profile, radius, centre_z, height, tolerance=0.003):
    """The larger of the body and a capsule of that radius, simplified to rows a linear fit keeps within tolerance."""
    lo, hi = centre_z - height / 2, centre_z + height / 2
    rows = []
    for t, r in profile:
        c = 0.0
        if lo <= t <= hi:
            d = max(0.0, max(lo + radius - t, t - (hi - radius)))
            c = math.sqrt(max(0.0, radius * radius - d * d))
        rows.append((t, max(r, c)))
    for t in (lo, hi):  # the capsule's own ends, where it reaches past the mesh
        if t < rows[0][0] or t > rows[-1][0]:
            rows.append((t, 0.0))
    rows.sort()
    rows = [rows[0]] + [row for row in rows[1:-1] if row[1] > 0] + [rows[-1]]  # no dips to 0 inside the missile
    keep = [0]
    while keep[-1] < len(rows) - 1:
        i = keep[-1]
        j = i + 1
        while j + 1 < len(rows):
            (t0, r0), (t1, r1) = rows[i], rows[j + 1]
            ok = all(abs(r0 + (r1 - r0) * (t - t0) / (t1 - t0) - r) <= tolerance for t, r in rows[i + 1:j + 1])
            if not ok:
                break
            j += 1
        keep.append(j)
    return [(round(rows[k][0], 3), round(rows[k][1], 3)) for k in keep]
