"""Wingtip lamp clearance against rendered store bounds and physical colliders, including containment."""
import re

import numpy as np

from stores import meshverts
from stores.bodies import mesh_path
from stores.geometry import bounds, box_gap, quat_matrix, segment_distance


def stock_lens(index, side, anchor=None):
    path = mesh_path(index, "fighter1_navLight_" + side)
    verts = np.asarray(meshverts.positions(path), float)
    tris = np.asarray(meshverts.triangles(path), int).reshape(-1, 3)
    if len(tris) != 14:
        raise ValueError("stock nav lens must have 14 triangles: " + path)
    if anchor is not None:
        verts = np.asarray(anchor) + verts - (verts.min(0) + verts.max(0)) / 2
    return verts, tris


def wingtip_keys(repo):
    source = (repo / "unity/Assets/Icarus/Editor/IcarusAuthor.Identity.cs").read_text()
    first = re.search(r"StationKeys\s*=\s*\{\s*new\[\]\s*\{([^}]+)\}", source)
    if first is None:
        raise ValueError("cannot read the Wingtip mount list from StationKeys")
    keys = re.findall(r'"([^"]+)"', first[1])
    if not keys:
        raise ValueError("empty Wingtip mount list")
    return keys


def check_tip_lamps(stations, lamps, mounts):
    """Rendered AABBs conservatively enclose every store triangle. Collider checks include their interiors."""
    results = []
    for hp_name, pos, rot in stations:
        for key, (mesh, colliders) in mounts.items():
            store_bounds = bounds(pos + mesh[0] @ rot.T)
            for name, lamp in lamps:
                gap = box_gap(bounds(lamp[0]), store_bounds)
                for collider in colliders:
                    if collider["trigger"]:
                        continue
                    centre = pos + rot @ np.asarray(collider["centre"])
                    frame = rot @ quat_matrix(collider["rot"])
                    if collider["kind"] == "Capsule":
                        half = frame[:, collider["axis"]] * collider["half_len"]
                        distance = segment_distance(centre - half, centre + half, lamp) - collider["r"]
                    elif collider["kind"] == "Box":
                        # An oriented box's world AABB also includes its whole interior.
                        half = np.abs(frame) @ np.asarray(collider["half"])
                        distance = box_gap(bounds(lamp[0]), (centre - half, centre + half))
                    else:
                        raise ValueError("unsupported store collider: " + collider["kind"])
                    gap = min(gap, distance)
                results.append((gap, name, hp_name, key))
                print(f"{name} | {hp_name} | {key} | envelope gap {gap:.6f} m")
    if not results:
        raise ValueError("no tip lamp/store pairs checked")
    gap, name, hp, key = min(results)
    passed = gap > 0.00001
    print(f"Stores rule 14 {'PASS' if passed else 'FAIL'}: {len(results)} lamp/store pairs, "
          f"least envelope gap {gap:.6f} m, {name}, {key} on {hp}")
    return passed
