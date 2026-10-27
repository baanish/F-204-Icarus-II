"""Build Icarus headlessly and export part-local FBXs plus blockout.json.

blender --background --factory-startup --python-exit-code 1 --python tools/export_blockout.py -- [--out DIR]

The Icarus collection holds meshes and hinge empties. Every hinge has local X along
its axis and a <name>_visible mesh child. Optional Colliders and LOD1 meshes must
be identity-parented to their owner. Pivots and axes are world-space; mesh bounds
are part-local. hinge_axis_unity is world-space positive Blender hinge X. Each mesh part lists its uv_layers, and
design_eye is the canopy's design eye point (canopy.EYE), world-space, and conformal the conformal
hardpoint and the Icarus's own conformal mounts (stations.export), and tip_tank the tip tank store (tip_tanks.export) with its own
FBX, in the mount's frame.
Blender (x, y, z) maps to Unity (-x, z, -y), in metres.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "art/blender"))
from scrub_fbx import scrub_file
import build_icarus
import canopy
import stations
import tip_tanks

MAX_HULL = 255


def to_unity(v):
    return [round(-v[0], 5), round(v[2], 5), round(-v[1], 5)]


def axes_unity(rotation):
    """Conjugate the object's rotation by the Blender-to-Unity basis change."""
    m = rotation.to_matrix()
    basis = {"right": Vector((-1, 0, 0)), "up": Vector((0, 0, 1)), "forward": Vector((0, -1, 0))}
    return {key: to_unity(m @ v) for key, v in basis.items()}


def bounds_unity(lo, hi):
    a, b = to_unity(lo), to_unity(hi)
    return [[min(a[i], b[i]) for i in range(3)], [max(a[i], b[i]) for i in range(3)]]


def json_value(value):
    if hasattr(value, "to_list"):
        return value.to_list()
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def evaluated_mesh(obj, name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    mesh.name = name
    return mesh


def tris(mesh):
    return sum(len(p.vertices) - 2 for p in mesh.polygons)


def material_tris(mesh):
    counts = [0] * len(mesh.materials)
    for p in mesh.polygons:
        counts[p.material_index] += len(p.vertices) - 2
    return [[m.name if m else "", n] for m, n in zip(mesh.materials, counts) if n > 0]


def children_in(collection_name, objects):
    coll = bpy.data.collections.get(collection_name)
    result = {}
    if coll is None:
        return result
    for obj in sorted(coll.all_objects, key=lambda o: o.name):
        if obj.type != "MESH" or obj.parent is None or obj.parent.name not in objects:
            raise ValueError(f"{collection_name}/{obj.name} must be a mesh parented to an Icarus part")
        offset = obj.parent.matrix_world.inverted() @ obj.matrix_world
        if any(abs(offset[i][j] - Matrix.Identity(4)[i][j]) > 1e-5 for i in range(4) for j in range(4)):
            raise ValueError(f"{obj.name} is not at an identity transform under {obj.parent.name}")
        result.setdefault(obj.parent.name, []).append(obj)
    return result


def mesh_bounds(mesh):
    return [[min(v.co[i] for v in mesh.vertices) for i in range(3)],
            [max(v.co[i] for v in mesh.vertices) for i in range(3)]]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_fbx(path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
        # Triangulate n-gons before Unity can discard one under its own projection.
        tri = obj.modifiers.new("export_ngons", "TRIANGULATE")
        tri.min_vertices, tri.ngon_method, tri.keep_custom_normals = 5, "BEAUTY", True
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH", "EMPTY"},
                             apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                             bake_space_transform=True, mesh_smooth_type="FACE", use_tspace=False, colors_type="LINEAR",
                             add_leaf_bones=False, bake_anim=False, path_mode="STRIP")
    scrub_file(path)


def remove_previous(out):
    manifest = out / "blockout.json"
    if not manifest.exists():
        return
    previous = json.loads(manifest.read_text(encoding="utf-8"))
    for part in previous.get("parts", {}).values():
        name = part.get("fbx")
        if not name:
            continue
        if Path(name).name != name or not name.endswith(".fbx"):
            raise ValueError(f"invalid previous FBX name: {name}")
        (out / name).unlink(missing_ok=True)
    manifest.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "art/export")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    out = args.out.resolve()
    build_icarus.build_cached()
    coll = bpy.data.collections.get("Icarus")
    if coll is None:
        raise ValueError("generator did not create the Icarus collection")
    objs = [o for o in coll.all_objects if o.type in ("MESH", "EMPTY")]
    by_name = {o.name: o for o in objs}
    if not any(o.type == "MESH" for o in objs):
        raise ValueError("Icarus has no mesh parts")
    for obj in objs:
        scale = obj.matrix_world.decompose()[2]
        if any(abs(s - 1) > 1e-5 for s in scale):
            raise ValueError(f"{obj.name}: scale {tuple(round(s, 5) for s in scale)} is not 1; apply it in the generator")
        if obj.parent and obj.parent.name not in by_name:
            raise ValueError(f"{obj.name}: parent is outside Icarus")
        if "hinge_axis" in obj:
            visible = by_name.get(obj.name + "_visible")
            if (obj.type != "EMPTY" or obj["hinge_axis"] != "X" or visible is None
                    or visible.type != "MESH" or visible.parent != obj):
                raise ValueError(f"{obj.name}: expected an X hinge with its own _visible mesh child")
    colliders = children_in("Colliders", by_name)
    lods = children_in("LOD1", by_name)
    parent_of = {o.name: o.parent.name if o.parent else None for o in objs}
    tank_layout = tip_tanks.export(to_unity, coll)  # reads the wing by its name, before the renames below
    # Free the part names: Unity names each imported mesh after its FBX node.
    for obj in objs:
        obj.name = "source_" + obj.name
    scratch = bpy.data.collections.new("export_scratch")
    bpy.context.scene.collection.children.link(scratch)
    out.mkdir(parents=True, exist_ok=True)
    remove_previous(out)
    report = {}
    for name, obj in sorted(by_name.items()):
        pivot, rotation, _ = obj.matrix_world.decompose()
        props = {k: json_value(obj[k]) for k in obj.keys() if not k.startswith("_")}
        entry = {"fbx": None, "blender_parent": parent_of[name], "pivot_blender": [round(c, 5) for c in pivot],
                 "pivot_unity": to_unity(pivot), "axes_unity": axes_unity(rotation), "props": props,
                 "bounds_unity": None}
        report[name] = entry
        if "hinge_axis" in props:
            entry["hinge_axis_unity"] = to_unity(rotation @ Vector((1, 0, 0)))
        if obj.type == "EMPTY":
            continue
        meshes = [(name, evaluated_mesh(obj, name))]
        pieces = []
        for i, collider in enumerate(colliders.get(name, [])):
            piece_name = f"{name}_colmesh{i}"
            mesh = evaluated_mesh(collider, piece_name)
            if len(mesh.vertices) > MAX_HULL or tris(mesh) > MAX_HULL:
                raise ValueError(f"{piece_name}: {len(mesh.vertices)} vertices, {tris(mesh)} triangles; limit {MAX_HULL}")
            pieces.append({"name": piece_name, "verts": len(mesh.vertices), "tris": tris(mesh),
                           "bounds_unity": bounds_unity(*mesh_bounds(mesh))})
            meshes.append((piece_name, mesh))
        lod = None
        if name in lods:
            if len(lods[name]) != 1:
                raise ValueError(f"{name}: expected one LOD1 hull")
            lod = evaluated_mesh(lods[name][0], f"{name}_lod1")
            meshes.append((lod.name, lod))
        temps = [bpy.data.objects.new(n, m) for n, m in meshes]
        for temp in temps:
            scratch.objects.link(temp)
        fbx = out / f"{name}.fbx"
        export_fbx(fbx, temps)
        render = meshes[0][1]
        lo, hi = mesh_bounds(render)
        entry.update({"fbx": fbx.name, "sha256": sha256(fbx),
                      "bounds_blender": [[round(c, 5) for c in v] for v in (lo, hi)],
                      "bounds_unity": bounds_unity(lo, hi), "tris": tris(render),
                      "materials": material_tris(render), "uv_layers": [layer.name for layer in render.uv_layers],
                      "colliders": pieces,
                      "lod1": {"tris": tris(lod)} if lod else None})
        for temp in temps:
            bpy.data.objects.remove(temp, do_unlink=True)
        for _, mesh in meshes:
            bpy.data.meshes.remove(mesh)
    # The tip tank, a store: its mesh in the mount's frame, so the temporary object sits at the origin.
    tank = bpy.data.objects[tip_tanks.NAME]
    tank.name = "source_" + tip_tanks.NAME
    mesh = evaluated_mesh(tank, tip_tanks.NAME)
    temp = bpy.data.objects.new(tip_tanks.NAME, mesh)
    scratch.objects.link(temp)
    fbx = out / f"{tip_tanks.NAME}.fbx"
    export_fbx(fbx, [temp])
    lo, hi = mesh_bounds(mesh)
    store = dict(tank_layout, fbx=fbx.name, sha256=sha256(fbx), tris=tris(mesh),
                 bounds_unity=bounds_unity(lo, hi), materials=material_tris(mesh), uv_layers=[l.name for l in mesh.uv_layers])
    bpy.data.objects.remove(temp, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    source = REPO / "art/blender/build_icarus.py"
    eye = build_icarus.P(*canopy.EYE)
    manifest = {"source_generator": source.relative_to(REPO).as_posix(), "source_sha256": sha256(source),
                "axes": "Unity = (-x, z, -y) of Blender; pivots and hinge_axis_unity are world-space; bounds are part-local (in axes_unity)",
                "design_eye": {"blender": [round(c, 5) for c in eye], "unity": to_unity(eye)},
                "conformal": stations.export(to_unity),
                "tip_tank": store,
                "parts": report}
    (out / "blockout.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    count = sum(p["fbx"] is not None for p in report.values())
    print(f"EXPORT PASS: {count} meshes and {len(report) - count} empties to {out}")


if __name__ == "__main__":
    main()
