"""Sample installed position-light visibility using the local stock meshes.

14 CFR 25.1385(c), 25.1387(b,c,d): ahead to 110 degrees outboard for the
wing lamps, and 70 degrees either side of dead aft for the white rear lamp. 25.1389(b)(2)
references 25.1393: vertical coverage extends to 90 degrees above and below.
https://www.ecfr.gov/current/title-14/section-25.1387
https://www.ecfr.gov/current/title-14/section-25.1393
This is a geometric check, not a photometric certification. Zero blocked samples
is the deliberate policy; a one-degree grid includes every intensity-band edge,
the horizon and both poles, but cannot prove continuity between samples.
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import solids

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from stores import paths
from stores.geometry import axis_quat, quat_matrix
from stores.lights import stock_lens, wingtip_keys
from stores.mounts import load_mount
from stores.prefab_tree import asset_index

STEP_DEG = 1
STABILATOR_STEP_DEG = 0.5


def aft_occluders(icarus):
    """Fixed airframe plus the union of the rudder and nozzle extreme poses.

    The stabilator and its fitting are checked separately at every half degree.
    Unioning the other controls is deliberately conservative: a clear ray must
    clear all their sampled poses, so combinations cannot hide an obstruction.
    """
    import build_icarus as bi
    import propulsion

    objects = [o for o in icarus.all_objects if o.type == "MESH" and o.get("role") != "cockpit_view"]
    stabilator = icarus.all_objects["stabilator"]
    moving = set(stabilator.children_recursive)
    rudder = icarus.all_objects["rudder"]
    moving.update(rudder.children_recursive)
    nozzle_names = {"nozzle_sync_ring"}
    nozzle_names.update(o.name for o in objects if o.name.startswith(("nozzle_petal_", "nozzle_seal_", "nozzle_link_", "nozzle_ram_")))
    fixed = solids.bvh([o for o in objects if o not in moving and o.name not in nozzle_names])
    vertices, faces = [], []

    def add(obj, matrix):
        base = len(vertices)
        vertices.extend(matrix @ v.co for v in obj.data.vertices)
        faces.extend(tuple(base + i for i in p.vertices) for p in obj.data.polygons)

    travel = float(rudder["deflection_deg"])
    for angle in (-travel, 0, travel):
        turn = rudder.matrix_world @ Matrix.Rotation(math.radians(angle), 4, "X") @ rudder.matrix_world.inverted()
        for obj in objects:
            if obj in rudder.children_recursive:
                add(obj, turn @ obj.matrix_world)
    for pose in propulsion.envelope():
        matrices = propulsion.actuation_matrices(bi.PARAMS, **pose)
        for kind in ("petal", "seal"):
            for i in range(bi.PARAMS["nozzle"]["petals"]):
                hinge = icarus.all_objects["nozzle_%s_%02d" % (kind, i)]
                obj = icarus.all_objects[hinge.name + "_visible"]
                matrices[obj.name] = propulsion.nozzle_hinge_matrix(bi.PARAMS, kind, i, **pose) @ hinge.matrix_world.inverted() @ obj.matrix_world
        for name, matrix in matrices.items():
            obj = icarus.all_objects[name]
            if obj.type == "MESH":
                add(obj, matrix)
    return [fixed, BVHTree.FromPolygons(vertices, faces)]


def measure_aft(icarus):
    lamp = icarus.all_objects["light_nav_aft"]
    hinge = icarus.all_objects["stabilator"]
    occluders = aft_occluders(icarus)
    attached = [o for o in hinge.children_recursive if o.type == "MESH"]
    travel = float(hinge["deflection_deg"])
    samples = []
    for az in range(-70, 71, STEP_DEG):
        for el in range(-90, 91, STEP_DEG):
            a, e = math.radians(az), math.radians(el)
            samples.append((az, el, Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))))
    lamp.data.calc_loop_triangles()
    emitters = []
    for tri in lamp.data.loop_triangles:
        points = [lamp.matrix_world @ lamp.data.vertices[i].co for i in tri.vertices]
        emitters.append((sum(points, Vector()) / 3, (points[1] - points[0]).cross(points[2] - points[0]).normalized()))
    rows = []
    attached_tree = solids.bvh(attached)
    for k in range(-round(travel / STABILATOR_STEP_DEG), round(travel / STABILATOR_STEP_DEG) + 1):
        angle = k * STABILATOR_STEP_DEG
        turn = hinge.matrix_world @ Matrix.Rotation(math.radians(angle), 4, "X") @ hinge.matrix_world.inverted()
        inverse = turn.inverted()
        # Rays against the attached meshes stay in their rest pose. Other meshes
        # stay in aircraft space. No scene transforms are changed by the check.
        posed = [(turn @ point, turn.to_3x3() @ normal) for point, normal in emitters]
        blocked = []
        for az, el, direction in samples:
            clear = False
            for point, normal in posed:
                if normal.dot(direction) <= 1e-7:
                    continue
                start = point + direction * 0.00001
                if (all(tree.ray_cast(start, direction, 40)[0] is None for tree in occluders)
                        and attached_tree.ray_cast(inverse @ start, inverse.to_3x3() @ direction, 40)[0] is None):
                    clear = True
                    break
            if not clear:
                blocked.append([az, el])
        row = dict(stabilator_deg=angle, total=len(samples), blocked=len(blocked), fraction=len(blocked) / len(samples), examples=blocked[:8])
        rows.append(row)
    worst = max(rows, key=lambda row: row["fraction"])
    print("aft nav visibility: %d poses, worst %+g deg, %d/%d blocked (%.6f%%), examples %s" %
          (len(rows), worst["stabilator_deg"], worst["blocked"], worst["total"], 100 * worst["fraction"], worst["examples"]), flush=True)
    return dict(azimuth_deg=[-70, 70], elevation_deg=[-90, 90], step_deg=STEP_DEG,
                stabilator_step_deg=STABILATOR_STEP_DEG, worst_fraction=worst["fraction"], results=rows)


def blender(v):
    return Vector((-v[0], -v[2], v[1]))


def unity(v):
    return np.array((-v[0], v[2], -v[1]))


def stock_geometry():
    root = paths.load()["game_export"]
    index = asset_index(root, "Mesh")
    mounts = {key: load_mount(root, index, key) for key in wingtip_keys(REPO)}
    lenses = {side: stock_lens(index, side, (0, 0, 0)) for side in ("L", "R")}
    return mounts, lenses


def tip_stations(icarus):
    result = {}
    for side, sign in (("L", -1), ("R", 1)):
        wing = icarus.all_objects["wing_skin_" + side]
        verts = np.array([unity(wing.matrix_world @ v.co) for v in wing.data.vertices])
        outer = np.abs(verts[:, 0]).max()
        tip = verts[np.abs(verts[:, 0]) > outer - 0.001]
        leading, trailing = tip[:, 2].max(), tip[:, 2].min()
        pos = np.array((sign * (outer - 0.005), (tip[:, 1].max() + tip[:, 1].min()) / 2,
                        leading - 0.545 * (leading - trailing)))
        result[side] = (pos, quat_matrix(axis_quat((0, 0, 1), sign * 90)))
    return result


def lamp_meshes(icarus, lenses):
    result = {}
    for obj in icarus.all_objects:
        if obj.get("light") == "nav":
            verts, tris = lenses[obj.name[-1]]
            result[obj.name] = (np.array([unity(obj.matrix_world @ blender(v)) for v in verts]), tris)
    return result


def mesh_tree(mesh):
    verts, tris = mesh
    return BVHTree.FromPolygons([blender(v) for v in verts], tris.tolist(), all_triangles=True)


def measure(icarus):
    mounts, lenses = stock_geometry()
    lamps = lamp_meshes(icarus, lenses)
    stations = tip_stations(icarus)
    airframe = solids.bvh([o for o in icarus.all_objects if o.type == "MESH" and o.get("role") != "cockpit_view"])
    emitters = {}
    for name, (verts, tris) in lamps.items():
        points = [blender(v) for v in verts]
        faces = [[points[i] for i in t] for t in tris]
        # The Unity-to-Blender basis reflects handedness, so reverse the winding.
        emitters[name] = [(sum(f, Vector()) / 3, (f[2] - f[0]).cross(f[1] - f[0]).normalized()) for f in faces]
    results = []
    for key, (mesh, _) in mounts.items():
        stores = [mesh_tree((pos + mesh[0] @ rot.T, mesh[1])) for pos, rot in stations.values()]
        for side, sign in (("L", 1), ("R", -1)):
            names = [name for name in lamps if name.endswith("_" + side)]
            blocked, each, examples, total = 0, dict.fromkeys(names, 0), [], 0
            for az in range(0, 111, STEP_DEG):
                for el in range(-90, 91, STEP_DEG):
                    a, e = math.radians(az), math.radians(el)
                    direction = Vector((sign * math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
                    visible = []
                    for name in names:
                        clear = any(normal.dot(direction) > 1e-7 and
                                    all(tree.ray_cast(point + direction * 0.00001, direction, 40)[0] is None
                                        for tree in [airframe] + stores)
                                    for point, normal in emitters[name])
                        visible.append(clear)
                        each[name] += not clear
                    total += 1
                    if not any(visible):
                        blocked += 1
                        if len(examples) < 8:
                            examples.append([az, el])
            row = dict(side=side, store=key, total=total, blocked=blocked, fraction=blocked / total,
                       lamps={n: dict(blocked=b, fraction=b / total) for n, b in each.items()}, examples=examples)
            results.append(row)
            print("nav visibility: %s %s %d/%d blocked (%.6f%%), examples %s" %
                  (side, key, blocked, total, 100 * blocked / total, examples), flush=True)
    return dict(step_deg=STEP_DEG, azimuth_deg=[0, 110], elevation_deg=[-90, 90], results=results,
                positions_unity={n: unity(icarus.all_objects[n].matrix_world.translation).tolist() for n in lamps},
                store_bounds={k: (m[0].max(0) - m[0].min(0)).tolist() for k, (m, _) in mounts.items()})


def check(icarus):
    result = measure(icarus)
    if any(r["blocked"] for r in result["results"]):
        raise ValueError("lights: position-light sector has blocked rays with a loaded wingtip store")
    result["aft"] = measure_aft(icarus)
    if result["aft"]["worst_fraction"]:
        raise ValueError("lights: rear position-light sector has blocked rays across stabilator travel")
    print("nav visibility PASS: zero blocked directions for every allowed tip store and rear lamp pose")
    return result
