"""Check that the skin pieces of a split export carry their family's UVs: every skin corner of a piece in the new export
has the UV the old export's family has at that point, an old corner's own UV or the UV interpolated along the old
edge the cut split, within 1e-6. It ties the skin maps, baked from the families (bake_skin.py builds with split False),
to the pieces.

tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/check_uv_families.py -- <old export> <new export>

A corner matches against the old faces that hold its point (as a corner or on an edge): first the face the new face
was cut from (one that holds all its corners), then those facing the same way (an exporter's triangles of a cut cap
match none whole), then the one whose surface lies nearest the new face's centre, so a corner on a UV seam is judged
on its own side of it. Exits nonzero on any mismatch.
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "art/blender"))
from parts import SKIN, SKIN_FAMILIES, family

ON = 5e-5  # metres: a point this close to an old corner or edge lies on it (blockout.json pivots are rounded to 1e-5)
UV_TOL = 1e-6


def skin_faces(folder, prefix):
    """{family: [(world corners, corner UVs)]} of every skin family's parts in an export folder. Each FBX holds its
    part's mesh in the part's own frame, so its corners move by the part's pivot (no skin part is rotated)."""
    parts = json.loads((folder / "blockout.json").read_text(encoding="utf-8"))["parts"]
    out = {}
    for name, entry in sorted(parts.items()):
        if not entry.get("fbx") or not name.startswith(SKIN_FAMILIES):
            continue
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=str(folder / entry["fbx"]))
        new = [o for o in bpy.data.objects if o not in before]
        obj = next(o for o in new if o.name.split(".")[0] == name)
        for o in new:
            o.name = prefix + o.name
        me = obj.data
        uv = me.uv_layers.active.data
        pivot = Vector(entry["pivot_blender"])
        faces = out.setdefault(family(name), [])
        for poly in me.polygons:
            if not me.materials[poly.material_index].name.startswith(SKIN):
                continue
            faces.append(([obj.matrix_world @ me.vertices[me.loops[i].vertex_index].co + pivot for i in poly.loop_indices],
                          [uv[i].uv.copy() for i in poly.loop_indices]))
    return out


def normal(corners):
    """A polygon's unit normal (Newell's method, so a non-planar one still gets its mean)."""
    n = Vector()
    for a, b in zip(corners, corners[1:] + corners[:1]):
        n += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
    return n.normalized()


def expected(point, faces, candidates):
    """The UVs the old faces holding point give it, nearest face first."""
    out = []
    for k in candidates:
        corners, uvs = faces[k]
        for i, (a, ua) in enumerate(zip(corners, uvs)):
            if (point - a).length <= ON:
                out.append(ua)
                break
            b, ub = corners[(i + 1) % len(corners)], uvs[(i + 1) % len(uvs)]
            closest, t = intersect_point_line(point, a, b)
            if 0 <= t <= 1 and (closest - point).length <= ON:
                out.append(ua.lerp(ub, t))
                break
    return out


def main():
    old_dir, new_dir = (Path(p) for p in sys.argv[sys.argv.index("--") + 1:][:2])
    old = skin_faces(old_dir, "old_")
    new = skin_faces(new_dir, "new_")
    problems, checked = [], 0
    if set(old) != set(new):
        problems.append("families differ: %s against %s" % (sorted(old), sorted(new)))
    for name in sorted(set(old) & set(new)):
        faces = old[name]
        verts = [co for corners, _ in faces for co in corners]
        polys, start = [], 0
        for corners, _ in faces:
            polys.append(list(range(start, start + len(corners))))
            start += len(corners)
        tree = BVHTree.FromPolygons(verts, polys)
        for corners, uvs in new[name]:
            centre = sum(corners, Vector()) / len(corners)
            # how far each old face's surface lies from the new face's centre: the face it was cut from lies on it
            surface = {k: d for _, _, k, d in tree.find_nearest_range(centre, 0.5)}
            facing = normal(corners)
            near = [{k for _, _, k, _ in tree.find_nearest_range(point, 2 * ON)} for point in corners]
            # the face a cut face came from holds every one of its corners
            source = set.intersection(*near)
            for point, uv, held in zip(corners, uvs, near):
                candidates = sorted(held, key=lambda k: (k not in source, normal(faces[k][0]).dot(facing) < 0.95,
                                                         surface.get(k, float("inf"))))
                want = expected(point, faces, candidates)
                checked += 1
                if not want:
                    problems.append("%s: corner %s lies on no old face" % (name, tuple(round(c, 5) for c in point)))
                elif (want[0] - uv).length > UV_TOL:
                    problems.append("%s: corner %s has UV %s, the family %s" % (
                        name, tuple(round(c, 5) for c in point), tuple(uv), tuple(want[0])))
    if problems:
        counts = {}
        for problem in problems:
            counts[problem.split(":")[0]] = counts.get(problem.split(":")[0], 0) + 1
        print("UV FAMILIES FAIL: %d of %d corners (%s): %s" % (len(problems), checked, ", ".join("%s %d" % kv for kv in sorted(counts.items())), "; ".join(problems[:20])))
        sys.exit(1)
    print("UV FAMILIES PASS: %d skin corners in %d families carry their family's UVs" % (checked, len(new)))


if __name__ == "__main__":
    main()
