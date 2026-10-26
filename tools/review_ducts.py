"""Measure the intake ducts and fuel cells of the built Icarus, and render the duct and fuel review views.

pwsh -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/review_ducts.py -- --tag after

Writes <out>/<tag>/measurements.json and the views (cutaway clay: the skin hidden, ducts blue, fuel orange, engine
grey, stowed gear and wells dark; and a look into each intake with the skin on). Areas are flow areas on station
planes: inside the ducts' walls, outside the shock cones, from the meshes themselves.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "art/blender"))
import build_icarus as bi  # noqa: E402
import internals  # noqa: E402
import review_sheet as rs  # noqa: E402

GRID = 0.004  # metres between area samples on a station plane


def segments(obj, s):
    """Where obj crosses the station plane s, as (x, z) segments."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-7,
                                 plane_co=bi.P(s, 0.0, 0.0), plane_no=Vector((0, 1, 0)))
    out = [((e.verts[0].co.x, e.verts[0].co.z), (e.verts[1].co.x, e.verts[1].co.z))
           for e in cut["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    bm.free()
    return out


def even_odd_area(segs, x_range=None):
    """Area inside an even number of crossings of the segments (inside the duct, outside the cone), by sampling."""
    if not segs:
        return 0.0
    xs = [q[0] for seg in segs for q in seg]
    zs = [q[1] for seg in segs for q in seg]
    x0, x1 = (min(xs), max(xs)) if x_range is None else x_range
    count = 0
    z = min(zs) + GRID / 2
    while z < max(zs):
        hits = sorted(a[0] + (z - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                      for a, b in segs if (a[1] > z) != (b[1] > z))
        for left, right in zip(hits[0::2], hits[1::2]):
            lo, hi = max(left, x0), min(right, x1)
            if hi > lo:
                count += (hi - lo) / GRID
        z += GRID
    return count * GRID * GRID


def duct_areas(stations):
    O = bpy.data.objects
    ducts = [O["intake_duct_L"], O["intake_duct_R"]]
    rows = []
    for s in stations:
        segs = [seg for d in ducts for seg in segments(d, s)]
        left = even_odd_area([g for g in segs if g[0][0] + g[1][0] >= 0], (0.0, 9.0))
        both = even_odd_area(segs)
        zs = [q[1] for g in segs for q in g]
        rows.append({"s": round(s, 3), "per_side_m2": round(left, 4), "total_m2": round(both, 4),
                     "floor_z": round(min(zs), 3) if zs else None})
    return rows


def capture():
    """The intake opening seen from ahead: inside the duct's first ring at the lip, outside the body ring just ahead
    and the shock cone, per side; and the lip annulus (the duct's first ring less the cone)."""
    import propulsion

    p = bi.PARAMS
    s, cx, cz, r = p["duct"][0]
    lip = p["intake"][0][0]
    stations = bi.fuselage_stations(p)
    ahead = bi.blended_ring(p, stations[stations.index(lip) - 1])
    sc = p["shock_cone"]
    cone_r = propulsion.cone_radius(sc, lip)
    seen = annulus = 0
    x = cx - r
    while x < cx + r:
        z = cz - r
        while z < cz + r:
            if (x - cx) ** 2 + (z - cz) ** 2 < r * r and (x - sc["x"]) ** 2 + (z - cz) ** 2 > cone_r ** 2:
                annulus += 1
                if not propulsion.inside(Vector((x, 0.0, z)), ahead):
                    seen += 1
            z += GRID
        x += GRID
    return {"open_seen_from_ahead_m2": round(seen * GRID * GRID, 4), "lip_annulus_m2": round(annulus * GRID * GRID, 4)}


def volume_centroid(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    total, moment = 0.0, Vector()
    for f in bm.faces:
        a, b, c = (v.co for v in f.verts)
        v = a.dot(b.cross(c)) / 6.0
        total += v
        moment += v * (a + b + c) / 4.0
    bm.free()
    return abs(total), moment / total if total else Vector()


def fuel():
    cells = {}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.get("role") == "fuel_tank" or o.name.startswith("wing_spar_"):
            if o.get("fuel_kg") is None:
                continue
            vol, c = volume_centroid(o)
            cells[o.name] = {"fuel_kg": o["fuel_kg"], "holds_kg": o.get("volume_holds_kg"),
                             "volume_m3": o.get("volume_m3"), "centroid_s": round(c.y + bi.S0, 3)}
    total = sum(c["fuel_kg"] for c in cells.values())
    holds = sum(c["holds_kg"] or 0 for c in cells.values())
    fuselage_holds = sum(c["holds_kg"] or 0 for n, c in cells.items() if not n.startswith("wing_spar_"))
    station = sum(c["fuel_kg"] * c["centroid_s"] for c in cells.values()) / total
    return {"cells": cells, "fuel_kg": round(total, 1), "fuselage_cells_hold_kg": round(fuselage_holds, 1),
            "fuel_centroid_s": round(station, 3), "design_fuel_kg": internals.INTERNALS["design_fuel_kg"],
            "note": "wing cells' holds sit on their wing_spar part; their volume is not in holds_kg here"}


def duct_to_gear():
    """Least distance from the ducts to the main gear stowed (gear up, doors shut), vertex to face both ways."""
    import gear

    O = bpy.data.objects
    ducts = [O["intake_duct_L"], O["intake_duct_R"]]
    legs = [m for leg in ("L", "R") for m in gear.leg_meshes(leg)]
    import stations

    out = {}
    with gear.posed(gear.all_folds(1.0)):
        bpy.context.view_layer.update()
        gt, dt = stations.tree_of(legs), stations.tree_of(ducts)
        a = min((gt.find_nearest(o.matrix_world @ v.co)[3], o.matrix_world @ v.co) for o in ducts for v in o.data.vertices)
        b = min((dt.find_nearest(o.matrix_world @ v.co)[3], o.matrix_world @ v.co) for o in legs for v in o.data.vertices)
        d, at = min(a, b, key=lambda t: t[0])
        out["stowed_gear_m"] = round(d, 4)
        out["stowed_at_s_x_z"] = [round(at.y + bi.S0, 3), round(at.x, 3), round(at.z, 3)]
    return out


def triangles():
    import budget
    import propulsion
    import parts

    icarus = bpy.data.collections["Icarus"]
    out = {k: budget.measure(icarus, v) for k, v in propulsion.BUDGET.items() if k.startswith("intake")}
    out["fuel_cells"] = budget.measure(icarus, parts.BUDGET["fuel_cells"])
    out["structure_cores"] = budget.measure(icarus, parts.BUDGET["structure_cores"])
    return out


VIEWS = {  # name: (location, target, ortho half-width or lens, ortho); orthographic views run nose left
    "top": ((0.0, 0.6, 30.0), (0.0, 0.6, 0.0), 3.4, True),
    "side": ((30.0, 0.6, 0.25), (0.0, 0.6, 0.25), 3.4, True),
    "below": ((0.0, 0.6, -30.0), (0.0, 0.6, 0.0), 3.4, True),
    "three_quarter": ((3.4, -3.6, 2.6), (0.0, 0.7, 0.2), 32, False),
}
LOOK_IN = {  # down each branch from ahead and outboard of its lip, and head on
    "look_into_L": ((1.35, -3.6, 0.36), (0.20, 0.8, 0.30), 40),
    "look_into_R": ((-1.35, -3.6, 0.36), (-0.20, 0.8, 0.30), 40),
    "head_on_L": ((0.8, -16.0, 0.22), (0.8, -1.0, 0.22), 140),
    "head_on_R": ((-0.8, -16.0, 0.22), (-0.8, -1.0, 0.22), 140),
}
COLOURS = {"intake_duct_": (0.20, 0.45, 0.85, 1), "fuel_": (0.95, 0.55, 0.15, 1), "engine_core": (0.55, 0.55, 0.55, 1),
           "gear_": (0.25, 0.25, 0.28, 1)}
MAIN_GEAR = tuple("gear_%s_%s" % (kind, side) for kind in ("leg", "wheel", "arm", "strut", "piston") for side in "LR")


def aim(cam, location, target, ortho):
    """Point cam at target; orthographic views keep the nose to the left, perspective ones the sky up."""
    from mathutils import Matrix

    f = (Vector(target) - Vector(location)).normalized()
    right = Vector((0, 1, 0)) if ortho else f.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(f)
    cam.matrix_world = Matrix.Translation(location) @ Matrix((right, up, -f)).transposed().to_4x4()


def shoot(scene, name, location, target, size, ortho, path, res):
    cam = rs.camera("Y_" + name)
    cam.data.type = "ORTHO" if ortho else "PERSP"
    if ortho:
        cam.data.ortho_scale = size * 2
    else:
        cam.data.lens = size
    cam.data.clip_start, cam.data.clip_end = 0.01, 100
    aim(cam, location, target, ortho)
    rs.render_view(scene, cam, str(path), res)


def render(out):
    """Clay: every mesh in the aircraft's own collections takes a flat colour; the cutaways hide all but the ducts,
    engine, stowed main gear and (fuel views) the fuel cells, the look-ins keep the skin in light grey."""
    import gear

    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)
    scene = rs.setup_scene()
    scene.render.film_transparent = False
    scene.display.shading.background_type = "WORLD"
    scene.world.color = (0.80, 0.82, 0.85)
    scene.display.shading.color_type = "OBJECT"
    for name in ("Colliders", "LOD1", "References"):
        c = bpy.data.collections.get(name)
        if c:
            c.hide_render = True
    meshes = [o for name in ("Icarus", "Internals") if bpy.data.collections.get(name)
              for o in bpy.data.collections[name].all_objects if o.type == "MESH"]
    kind = {o.name: next((k for k in COLOURS if o.name.startswith(k)), None) for o in meshes}
    kind.update({o.name: None for o in meshes if kind[o.name] == "gear_" and not o.name.startswith(MAIN_GEAR)})
    with gear.posed(gear.all_folds(1.0)):
        bpy.context.view_layer.update()
        wheel = bpy.data.objects["gear_wheel_L_visible"]
        zs = [(wheel.matrix_world @ v.co).z for v in wheel.data.vertices]
        print("review_ducts: stowed left tyre spans z %.3f to %.3f" % (min(zs), max(zs)), flush=True)
        for subject in ("ducts", "fuel"):
            for o in meshes:
                k = kind[o.name]
                o.hide_render = not (k and (subject == "fuel" or k != "fuel_"))
                if k:
                    o.color = COLOURS[k]
            for view, (location, target, size, ortho) in VIEWS.items():
                shoot(scene, view, location, target, size, ortho, out / ("%s_%s.png" % (subject, view)), (1600, 1000))
    for o in meshes:
        o.hide_render = False
        if not kind[o.name]:
            o.color = (0.86, 0.86, 0.84, 1)
    for view, (location, target, lens) in LOOK_IN.items():
        shoot(scene, view, location, target, lens, False, out / (view + ".png"), (1400, 1000))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out", type=Path, default=REPO / ".cache/review/share/y_duct")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    out = args.out / args.tag
    out.mkdir(parents=True, exist_ok=True)
    bi.build_cached()
    stations = [round(6.90 + 0.05 * i, 3) for i in range(51)]
    report = {"capture_per_side": capture(), "sections": duct_areas(stations), "fuel": fuel(),
              "duct_to_gear": duct_to_gear(), "triangles": triangles()}
    e = internals.INTERNALS["engine"]
    face_r = e["radius"] * 0.92
    report["engine_face"] = {"s": e["face_s"], "radius": round(face_r, 4), "area_m2": round(math.pi * face_r ** 2, 4)}
    (out / "measurements.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("DUCT REVIEW " + json.dumps({k: v for k, v in report.items() if k != "sections"}), flush=True)
    for row in report["sections"]:
        print("section", row)
    if not args.no_render:
        render(out)


if __name__ == "__main__":
    main()
