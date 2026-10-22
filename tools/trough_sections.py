"""Section drawings, clearances and review renders for the conformal trough and the inner wing pylons.

python tools/trough_sections.py [out_dir]     # default .cache/review/wave2/P6/latest
python tools/trough_sections.py --profiles    # the body envelopes art/blender/stations.py MOUNTS keeps

The first form builds the Icarus in Blender twice (with the trough, and without it for the old belly line), slices the
skin, intake ducts and fuel cells, hangs each conformal store's stock missile mesh in the Icarus's own mount (layout
from stations.MOUNTS) and renders it from below, the side and three-quarter, and renders the left pylon empty (plug)
and loaded. Back outside Blender it draws one section per conformal store at the missile's mid-length and prints, per
store: how much of the body sits above the old belly line, the rendered missile's least gap to the trough skin, and
its fins' least gap to the intake ducts. The stock missile meshes come from tools/local-paths.json's game export and
stay local: nothing here is committed but the numbers.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "art" / "blender"))
from stores import paths  # noqa: E402

STOCK = {"AAM1_single": "AAM1", "AAM3_single": "AAM3", "AAM2_single": "AAM2"}
INNER_STORE = "AAM1_single"  # the store hung on the pylon for its loaded render


def to_blender(v):
    """A Unity root-frame vector to Blender axes (Unity = (-x, z, -y) of Blender)."""
    return (-v[0], -v[2], v[1])


def missile_mesh(index, name):
    import numpy as np
    from stores import bodies, meshverts

    path = bodies.mesh_path(index, name)
    return np.array(meshverts.positions(path)), np.asarray(meshverts.triangles(path))


def profiles():
    from stores import bodies
    from stores.mounts import load_mount
    from stores.prefab_tree import asset_index

    root = paths.load()["game_export"]
    index = asset_index(root, "Mesh")
    for mount, mesh in STOCK.items():
        nodes = {}
        _, colliders = load_mount(root, index, mount, nodes)
        cap = next(c for c in colliders if c["kind"] == "Capsule")
        node = nodes[cap["name"]]
        prof = bodies.body_radius(index, mesh)
        r = max(q for _, q in prof)
        centre = cap["centre"][2] - node[0][2]
        height = 2 * (cap["half_len"] + cap["r"])
        print(f'"{mount}": capsule ({centre:.3f}, {height:.2f}), body {bodies.envelope(prof, r, centre, height)}')


# --- inside Blender ---------------------------------------------------------------------------------------------

def blender_main(out):
    import bpy
    from mathutils import Vector

    import build_icarus as bi
    import review_sheet
    import stations
    from stores.mounts import load_mount
    from stores.prefab_tree import asset_index

    local = paths.load()
    index = asset_index(local["game_export"], "Mesh")
    names = ("skin_", "intake_duct", "fuel_")

    def slice_parts(stations_s):
        out_parts = {}
        for obj in bpy.data.collections["Icarus"].all_objects:
            if obj.type != "MESH" or not obj.name.startswith(names):
                continue
            me = obj.data
            me.calc_loop_triangles()
            w = [obj.matrix_world @ v.co for v in me.vertices]
            per = {}
            for s in stations_s:
                y = s - bi.S0
                segs = []
                for t in me.loop_triangles:
                    p = [w[i] for i in t.vertices]
                    d = [q.y - y for q in p]
                    pts = []
                    for a in range(3):
                        b = (a + 1) % 3
                        if (d[a] < 0) != (d[b] < 0):
                            q = p[a] + (p[b] - p[a]) * (d[a] / (d[a] - d[b]))
                            pts.append((round(q.x, 5), round(q.z, 5)))
                    if len(pts) == 2:
                        segs.append(pts)
                per["%.3f" % s] = segs
            out_parts[obj.name] = per
        return out_parts

    c = stations.CONFORMAL
    layout = stations.export(lambda v: [-v[0], v[2], -v[1]])
    span = [round(5.0 + 0.05 * i, 3) for i in range(90)]
    mids = {k: round(c["s"] - m["centre"], 3) for k, m in stations.MOUNTS.items()}
    cuts = sorted(set(span) | set(mids.values()))

    # The old belly line: the same build with no trough.
    carve, check = stations.carve_shapes, stations.check
    stations.carve_shapes, stations.check = (lambda p, s: []), (lambda icarus: None)
    bi.build()
    before = slice_parts(cuts)
    stations.carve_shapes, stations.check = carve, check
    bi.build()
    after = slice_parts(cuts)

    # Missile meshes in the mount frame (Unity axes), then the hardpoint's frame in Blender: each store hung both sides.
    stores = {}
    for key, m in layout["mounts"].items():
        verts, tris = missile_mesh(index, STOCK[key])
        pitch = math.radians(m["pitch"])
        rows = []
        for v in verts:  # Unity Euler x: +pitch turns +z (the nose) down
            y = v[1] * math.cos(pitch) - v[2] * math.sin(pitch)
            z = v[1] * math.sin(pitch) + v[2] * math.cos(pitch)
            rows.append((v[0] + m["position"][0], y + m["position"][1], z + m["position"][2]))
        stores[key] = (rows, tris.tolist(), m["shoe"])

    def hang(name, rows, tris, hp, mat):
        """A mesh given in a hardpoint frame (Unity axes, the root's orientation) placed at Blender point hp."""
        vs = [Vector(hp) + Vector((-x, -z, y)) for x, y, z in rows]
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in vs], [], [tuple(t) for t in tris])
        obj = bpy.data.objects.new(name, me)
        bpy.data.collections["Icarus"].objects.link(obj)
        obj.data.materials.append(mat)
        return obj

    def material(name, rgba):
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.diffuse_color = rgba
        return mat

    red, grey = material("Review_Store", (0.75, 0.18, 0.12, 1)), material("Review_Shoe", (0.85, 0.85, 0.2, 1))
    for obj in list(bpy.data.objects):  # the factory scene's cube, lamp and camera
        if obj.name in ("Cube", "Light", "Camera"):
            bpy.data.objects.remove(obj, do_unlink=True)
    scene = review_sheet.setup_scene()
    for col in ("Colliders", "LOD1"):
        if col in bpy.data.collections:
            bpy.data.collections[col].hide_render = True

    def shoot(name, loc, target, lens=50, res=(1400, 900)):
        cam = review_sheet.camera("P6_" + name)
        cam.data.type = "PERSP"
        cam.data.lens = lens
        cam.data.clip_start = 0.01
        cam.location = Vector(loc)
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        review_sheet.render_view(scene, cam, str(Path(out) / (name + ".png")), res)

    hp_l = bi.P(c["s"], c["x"], c["z"])
    for key, (rows, tris, shoe) in stores.items():
        placed = []
        for side in (1, -1):
            hp = bi.P(c["s"], side * c["x"], c["z"])
            placed.append(hang("store_%s_%d" % (key, side), rows, tris, hp, red))
            placed.append(hang("shoe_%s_%d" % (key, side), shoe, [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
                                                                  (0, 4, 6, 2), (1, 3, 7, 5)], hp, grey))
        mid = bi.P(mids[key], c["x"], c["z"] - 0.1)
        shoot("%s_below" % key, mid + Vector((0.0, 0.0, -4.5)) + Vector((0.6, 0.0, 0.0)), mid, 35)
        shoot("%s_side" % key, mid + Vector((5.0, 0.0, -0.6)), mid, 40)
        shoot("%s_three_quarter" % key, mid + Vector((2.6, -3.2, -1.7)), mid, 40)
        for obj in placed:
            bpy.data.objects.remove(obj, do_unlink=True)
    shoot("trough_empty_below", bi.P(7.4, 0.6, -4.6), bi.P(7.4, 0.3, -0.3), 35)
    shoot("trough_empty_three_quarter", bi.P(4.4, 2.6, -1.9), bi.P(7.4, 0.45, -0.3), 40)

    # The pylon: empty (the blade hidden, the plug shown), then loaded (the blade shown, the plug hidden).
    blade, plug = bpy.data.objects["pylon_inner_L"], bpy.data.objects["pylon_inner_plug_L"]
    pts = [blade.matrix_world @ v.co for v in blade.data.vertices]
    low = min(q.z for q in pts)
    nose = min((q for q in pts if q.z < low + 0.01), key=lambda q: q.y)
    hp = Vector((sum(q.x for q in pts) / len(pts), nose.y, low))
    (verts, tris), _ = load_mount(local["game_export"], index, INNER_STORE)
    view = (hp + Vector((2.2, -2.4, -0.9)), hp + Vector((0.0, 0.5, 0.15)))
    blade.hide_render, plug.hide_render = True, False
    shoot("pylon_empty", *view, 45)
    shoot("pylon_empty_side", hp + Vector((3.2, 0.5, -0.1)), hp + Vector((0.0, 0.5, 0.1)), 45)
    store = hang("pylon_store", verts.tolist(), tris.tolist(), hp, red)
    blade.hide_render, plug.hide_render = False, True
    shoot("pylon_loaded", *view, 45)
    shoot("pylon_loaded_side", hp + Vector((3.2, 0.5, -0.1)), hp + Vector((0.0, 0.5, 0.1)), 45)
    bpy.data.objects.remove(store, do_unlink=True)

    # Fins: the missile mesh points above the axis that lie off the body (X fins), for the duct gap.
    data = {"layout": layout, "conformal": c, "gap": stations.GAP, "mids": mids, "cuts": cuts,
            "before": before, "after": after,
            "hardpoint_left": list(hp_l), "pylon_hardpoint_left": list(hp),
            "stores": {k: {"rows": r, "tris": t, "shoe": s} for k, (r, t, s) in stores.items()}}
    (Path(out) / "sections.json").write_text(json.dumps(data), encoding="utf-8")
    print("TROUGH SECTIONS DUMPED", out)


# --- outside Blender: drawings and numbers ----------------------------------------------------------------------

def store_world(data, key, side=1):
    """The store's missile mesh in Blender axes, hung at the left (side 1) or right hardpoint."""
    import numpy as np

    c = data["conformal"]
    rows = np.array(data["stores"][key]["rows"], float)
    return np.stack([side * c["x"] - rows[:, 0], c["s"] - rows[:, 2], c["z"] + rows[:, 1]], axis=1)  # (x, s, z)


def slice_store(verts, tris, s):
    import numpy as np

    tri = verts[np.asarray(tris)]
    d = tri[:, :, 1] - s
    segs = []
    for a in range(3):
        b = (a + 1) % 3
        m = (d[:, a] < 0) != (d[:, b] < 0)
        f = d[m, a] / (d[m, a] - d[m, b])
        segs.append(tri[m, a] + (tri[m, b] - tri[m, a]) * f[:, None])
    return np.concatenate(segs)[:, [0, 2]] if segs else np.zeros((0, 2))


def seg_points(segs, step=0.004):
    import numpy as np

    out = []
    for a, b in segs:
        a, b = np.array(a), np.array(b)
        n = max(1, int(np.linalg.norm(b - a) / step))
        out += [a + (b - a) * i / n for i in range(n + 1)]
    return np.array(out) if out else np.zeros((0, 2))


def belly_z(parts, s, x):
    zs = []
    for name, per in parts.items():
        if not name.startswith("skin_"):
            continue
        for a, b in per.get("%.3f" % s, []):
            if (a[0] - x) * (b[0] - x) <= 0 and a[0] != b[0]:
                zs.append(a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))
    return min(zs) if zs else None


def axis_at(data, key, s):
    """Height of a conformal missile's axis at station s, left side."""
    c, m = data["conformal"], data["layout"]["mounts"][key]
    return c["z"] + m["position"][1] + (s - (c["s"] - m["position"][2])) * math.tan(math.radians(m["pitch"]))


def report(out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = json.loads((Path(out) / "sections.json").read_text(encoding="utf-8"))
    c = data["conformal"]
    lines = []
    for key in data["stores"]:
        verts = store_world(data, key)
        tris = data["stores"][key]["tris"]
        s_lo, s_hi = verts[:, 1].min(), verts[:, 1].max()
        skin_gap, fin_gap, buried = (9.0, None), (9.0, None), []
        for s in data["cuts"]:
            if not s_lo < s < s_hi:
                continue
            sec = slice_store(verts, tris, s)
            if not len(sec):
                continue
            skin = seg_points([sg for n, per in data["after"].items() if n.startswith("skin_") for sg in per.get("%.3f" % s, [])])
            ducts = seg_points([sg for n, per in data["after"].items() if n.startswith("intake_duct") for sg in per.get("%.3f" % s, [])])
            if len(skin):
                # the body only: the X fins stand at 45 degrees off the axis and pass through the skin by design
                rel = sec - np.array([c["x"], axis_at(data, key, s)])
                ang = np.degrees(np.arctan2(rel[:, 1], rel[:, 0])) % 90
                body = sec[(ang < 25) | (ang > 65)]
                d_body = np.sqrt(((body[:, None, :] - skin[None, :, :]) ** 2).sum(-1)).min() if len(body) else 9.0
                if d_body < skin_gap[0]:
                    skin_gap = (d_body, s)
            if len(ducts):
                d = np.sqrt(((sec[:, None, :] - ducts[None, :, :]) ** 2).sum(-1)).min()
                if d < fin_gap[0]:
                    fin_gap = (d, s)
            old = belly_z(data["before"], s, c["x"])
            column = sec[np.abs(sec[:, 0] - c["x"]) < 0.02][:, 1]  # the body's top and bottom on the station's line
            if old is not None and len(column) and column.max() - column.min() > 0.1:
                top, bottom = column.max(), column.min()
                buried.append((s, (top - old) / (top - bottom)))
        mid = data["mids"][key]
        at_mid = min(buried, key=lambda b: abs(b[0] - mid))[1] if buried else float("nan")
        lines.append(f"{key}: body above the old belly line {at_mid:.2f} of its depth at mid-length (s {mid:.2f}), "
                     f"median {np.median([b for _, b in buried]):.2f}, range {min(b for _, b in buried):.2f} to "
                     f"{max(b for _, b in buried):.2f}; missile body to trough skin {skin_gap[0]:.3f} m (s {skin_gap[1]:.2f}); "
                     f"missile (fins included) to intake duct {fin_gap[0]:.3f} m (s {fin_gap[1]:.2f})")

        # The drawing at mid-length: left station, looking forward.
        fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
        s_key = "%.3f" % mid
        for parts, style in ((data["before"], dict(color="0.6", lw=1.0, ls=":")), (data["after"], None)):
            for name, per in parts.items():
                if style is not None and not name.startswith("skin_"):
                    continue
                st = style or dict(color="black" if name.startswith("skin_") else "tab:blue" if name.startswith("intake") else "tab:orange",
                                   lw=1.4 if name.startswith("skin_") else 1.0)
                for a, b in per.get(s_key, []):
                    ax.plot([a[0], b[0]], [a[1], b[1]], **st)
        sec = slice_store(verts, tris, mid)
        ax.plot(sec[:, 0], sec[:, 1], ".", color="tab:red", ms=1.5)
        m = data["layout"]["mounts"][key]
        r = m["capsule_radius"]
        ax.add_patch(plt.Circle((c["x"], axis_at(data, key, mid)), r, fill=False, ls="--", color="tab:red", lw=0.8))
        ax.plot([c["x"]], [c["z"]], "k+", ms=10)
        ax.set_xlim(0.0, 1.1)
        ax.set_ylim(-0.6, 0.35)
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)
        ax.set_xlabel("x, m (left of the centreline)")
        ax.set_ylabel("z, m (Blender)")
        ax.set_title(f"{key} conformal, section at s {mid:.2f} (missile mid-length), looking forward\n"
                     "skin black, old belly dotted, intake duct blue, fuel cells orange, missile red, collider dashed, hardpoint +",
                     fontsize=8)
        fig.tight_layout()
        fig.savefig(Path(out) / f"{key}_section.png")
        plt.close(fig)
    text = "\n".join(lines)
    (Path(out) / "trough.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if args and args[0] == "--blender":
        blender_main(args[1])
        return
    if args and args[0] == "--profiles":
        profiles()
        return
    out = (Path(args[0]) if args else REPO / ".cache/review/wave2/P6/latest").resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths.load()
    run = subprocess.run(["pwsh", "-NoProfile", "-File", str(REPO / "tools/Run-Blender.ps1"), "--background", "--factory-startup",
                          "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--blender", str(out)],
                         capture_output=True, text=True)
    if "TROUGH SECTIONS DUMPED" not in run.stdout:
        sys.stdout.write(run.stdout[-4000:] + run.stderr[-2000:])
        raise SystemExit("the Blender pass failed")
    report(out)


if __name__ == "__main__":
    main()
