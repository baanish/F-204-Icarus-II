"""Closed solids for detail geometry, and raycasts that place them on the built meshes.

A Solids gathers vertices and faces with a material name per face and becomes one mesh; tag the object
merge_into = "<part>" and parts.merge_details joins it into that part. The builders below (lathe, cylinder, box,
beam, sweep, tube) add to a Solids; bvh, hit, onto and must find the surface to put them on.
"""
import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


class Solids:
    """Closed solids gathered into one mesh, with a material name per face."""

    def __init__(self):
        self.verts, self.faces, self.mats = [], [], []

    def add(self, verts, faces, mat):
        """mat: one material name for every face, or a list with one per face."""
        base = len(self.verts)
        self.verts += [Vector(v) for v in verts]
        self.faces += [tuple(base + i for i in f) for f in faces]
        self.mats += mat if isinstance(mat, list) else [mat] * len(faces)

    def tris(self):
        return sum(len(f) - 2 for f in self.faces)

    def loft(self, rings, mat):
        """Rings of equal length, closed loops; a ring of one point is a tip; end rings are capped."""
        verts, faces, starts = [], [], []
        for r in rings:
            starts.append(len(verts))
            verts += r
        for (a, ra), (b, rb) in zip(zip(starts, rings), zip(starts[1:], rings[1:])):
            if len(ra) == 1:
                faces += [(a, b + (k + 1) % len(rb), b + k) for k in range(len(rb))]
            elif len(rb) == 1:
                faces += [(a + k, a + (k + 1) % len(ra), b) for k in range(len(ra))]
            else:
                n = len(ra)
                faces += [(a + k, a + (k + 1) % n, b + (k + 1) % n, b + k) for k in range(n)]
        if len(rings[0]) > 1:
            faces.append(tuple(range(len(rings[0])))[::-1])
        if len(rings[-1]) > 1:
            faces.append(tuple(starts[-1] + k for k in range(len(rings[-1]))))
        self.add(verts, faces, mat)

    def slab(self, outer, inner, mat):
        """A closed slab between two grids of points (rows by columns) of the same shape."""
        rows, cols = len(outer), len(outer[0])
        o = lambda i, j: i * cols + j
        n = rows * cols
        faces = []
        for i in range(rows - 1):
            for j in range(cols - 1):
                faces.append((o(i, j), o(i + 1, j), o(i + 1, j + 1), o(i, j + 1)))
                faces.append((n + o(i, j + 1), n + o(i + 1, j + 1), n + o(i + 1, j), n + o(i, j)))
        for j in range(cols - 1):
            faces.append((o(0, j), o(0, j + 1), n + o(0, j + 1), n + o(0, j)))
            faces.append((n + o(rows - 1, j), n + o(rows - 1, j + 1), o(rows - 1, j + 1), o(rows - 1, j)))
        for i in range(rows - 1):
            faces.append((o(i, 0), n + o(i, 0), n + o(i + 1, 0), o(i + 1, 0)))
            faces.append((o(i + 1, cols - 1), n + o(i + 1, cols - 1), n + o(i, cols - 1), o(i, cols - 1)))
        self.add([p for row in outer for p in row] + [p for row in inner for p in row], faces, mat)

    def box(self, corners, mat):
        """Eight corners: the bottom four then the top four, each in loop order."""
        self.add(corners, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], mat)

    def mesh(self, name, sharp_deg=40):
        """The solids as one mesh, slots in the order their materials first appear."""
        names = list(dict.fromkeys(self.mats))
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in self.verts], [], self.faces)
        for n in names:
            me.materials.append(bpy.data.materials[n])
        me.polygons.foreach_set("material_index", [names.index(m) for m in self.mats])
        me.validate()
        me.update()
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(sharp_deg))
        return me


def frame_at(normal):
    """Tangent (as close to aft as the surface allows), side and normal at a surface point."""
    n = normal.normalized()
    t = Y - n * n.dot(Y)
    t = t.normalized() if t.length > 1e-6 else X.copy()
    return t, n.cross(t), n


def disc(c, t, b, r, count):
    return [c + (t * math.cos(2 * math.pi * k / count) + b * math.sin(2 * math.pi * k / count)) * r
            for k in range(count)]


def basis(axis, ref=None):
    a = axis.normalized()
    ref = ref or (Z if abs(a.z) < 0.9 else Y)
    u = (ref - a * a.dot(ref)).normalized()
    return a, u, a.cross(u)


def lathe(out, origin, axis, profile, segs, mat, ref=None, loop=False, cap_mats=None):
    """Revolve (t along axis, r) about axis through origin. loop closes the profile on itself (a tyre); otherwise
    both ends get a cap, on cap_mats (front, back)."""
    a, u, w = basis(axis, ref)
    verts = [origin + a * t + (u * math.cos(2 * math.pi * k / segs) + w * math.sin(2 * math.pi * k / segs)) * r
             for t, r in profile for k in range(segs)]
    n = len(profile)
    bands = range(n if loop else n - 1)
    faces = [(j * segs + k, j * segs + (k + 1) % segs, (j + 1) % n * segs + (k + 1) % segs, (j + 1) % n * segs + k)
             for j in bands for k in range(segs)]
    mats = [mat] * len(faces)
    if not loop:
        faces += [tuple(range(segs))[::-1], tuple((n - 1) * segs + k for k in range(segs))]
        mats += list(cap_mats or (mat, mat))
    out.add(verts, faces, mats)


def cylinder(out, a, b, r, segs, mat, ref=None):
    lathe(out, a, b - a, [(0.0, r), ((b - a).length, r)], segs, mat, ref)


def box(out, centre, axes, half, mat):
    ax, ay, az = (v.normalized() * h for v, h in zip(axes, half))
    verts = [centre + ax * i + ay * j + az * k for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)]
    out.add(verts, [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)], mat)


def beam(out, p0, p1, width_axis, width, height, mat):
    """A box from p0 to p1, width measured along width_axis (made square to the beam)."""
    along = p1 - p0
    _, wa, ha = basis(along, width_axis)
    box(out, (p0 + p1) / 2, (along, wa, ha), (along.length / 2, width / 2, height / 2), mat)


def sweep(out, frames, profile, mat):
    """Sweep a closed 2D profile (b, n) through frames (origin, b axis, n axis), capped at both ends."""
    m = len(profile)
    verts = [o + b * pb + n * pn for o, b, n in frames for pb, pn in profile]
    faces = [(j * m + k, j * m + (k + 1) % m, (j + 1) * m + (k + 1) % m, (j + 1) * m + k)
             for j in range(len(frames) - 1) for k in range(m)]
    faces += [tuple(range(m))[::-1], tuple((len(frames) - 1) * m + k for k in range(m))]
    out.add(verts, faces, mat)


def tube(out, points, r, segs, mat):
    """A capped round tube through points, its rings square to the path."""
    frames = []
    for i, p in enumerate(points):
        t = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
        _, u, w = basis(t, frames[-1][1] if frames else None)
        frames.append((p, u, w))
    ring = [(r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
    sweep(out, frames, ring, mat)


def bvh(objs):
    """One BVH tree over objs in world space."""
    bm = bmesh.new()
    for o in objs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree


def hit(tree, origin, direction, dist=5.0):
    """First hit as (point, normal facing the ray's origin), or None."""
    loc, nrm, _, _ = tree.ray_cast(origin, direction.normalized(), dist)
    if loc is None:
        return None
    return loc, (nrm if nrm.dot(direction) < 0 else -nrm).normalized()


def must(found, what):
    if found is None:
        raise ValueError("detail placement: no surface under " + what)
    return found


def onto(tree, point, normal, what, reach=0.15):
    """Project point onto the surface along -normal, from outside."""
    return must(hit(tree, point + normal * reach, -normal, 2 * reach), what)
