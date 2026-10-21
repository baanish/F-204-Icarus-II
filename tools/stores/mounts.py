"""Stock weapon mounts from the game export: each mount prefab's rendered meshes (rail and store) and its colliders, in
the mount's own frame, which is the hardpoint's frame once hung.
"""
import re

import numpy as np

from stores import meshverts
from stores.prefab_tree import docs_of, f3, qmul, qrot

COLLIDER = {65: "Box", 136: "Capsule", 135: "Sphere", 64: "Mesh"}


def add(a, b):
    return tuple(a[i] + b[i] for i in range(3))


def load_mount(root, index, name):
    """(mesh, colliders): every enabled renderer's triangles merged into one mesh (verts, tris), and the colliders as
    dicts: kind, name, trigger, centre and rot, plus r, axis and half_len (capsule) or half (box)."""
    docs = docs_of(root / "GameObject" / (name + ".prefab"))
    gos = {fid: d for fid, d in docs.items() if d["type"] == 1}
    comps = {}
    for fid, d in docs.items():
        m = re.search(r"m_GameObject: \{fileID: (-?\d+)\}", d["body"])
        if m and d["type"] != 1:
            comps.setdefault(int(m[1]), []).append((fid, d))
    tf = {}
    for go, cs in comps.items():
        for fid, d in cs:
            if d["type"] == 4:
                b = d["body"]
                tf[fid] = dict(go=go, pos=f3(b, "m_LocalPosition"), rot=f3(b, "m_LocalRotation"), scl=f3(b, "m_LocalScale"),
                               father=int(re.search(r"m_Father: \{fileID: (-?\d+)\}", b)[1]),
                               children=[int(c) for c in re.findall(r"- \{fileID: (-?\d+)\}", b.split("m_Children:")[1].split("m_Father")[0])])
    verts, tris, colliders = [], [], []

    def walk(t, wp, wr, ws, path):
        v = tf[t]
        go = v["go"]
        nm = re.search(r"m_Name: (.*)", gos[go]["body"])[1]
        ls = tuple(v["scl"][i] * ws[i] for i in range(3))
        np_ = add(wp, qrot(wr, tuple(v["pos"][i] * ws[i] for i in range(3))))
        nr = qmul(wr, v["rot"])
        cs = comps.get(go, [])
        rendered = [d for _, d in cs if d["type"] == 23 and re.search(r"m_Enabled: 1", d["body"])]
        for _, d in cs:
            if d["type"] == 33 and rendered:
                g = re.search(r"m_Mesh: \{fileID: -?\d+, guid: (\w+)", d["body"])
                if g and index.get(g[1], "").endswith(".asset"):
                    mesh = index[g[1]]
                    base = sum(len(x) for x in verts)
                    verts.append([add(np_, qrot(nr, tuple(q[i] * ls[i] for i in range(3)))) for q in meshverts.positions(mesh)])
                    tris.append(np.asarray(meshverts.triangles(mesh), int).reshape(-1, 3) + base)
            if d["type"] in (65, 136):
                b = d["body"]
                c = f3(b, "m_Center") or (0, 0, 0)
                shape = dict(kind=COLLIDER[d["type"]], name=f"{path}/{nm}", trigger=re.search(r"m_IsTrigger: (\d)", b)[1] == "1",
                             centre=add(np_, qrot(nr, tuple(c[i] * ls[i] for i in range(3)))), rot=nr)
                if d["type"] == 65:
                    dims = f3(b, "m_Size")
                    shape["half"] = tuple(abs(dims[i] * ls[i]) / 2 for i in range(3))
                else:
                    r = float(re.search(r"m_Radius: ([-\d.e]+)", b)[1])
                    h = float(re.search(r"m_Height: ([-\d.e]+)", b)[1])
                    ax = int(re.search(r"m_Direction: (\d)", b)[1])
                    rr = r * max(abs(ls[i]) for i in range(3) if i != ax)
                    shape.update(axis=ax, r=rr, half_len=max(h * abs(ls[ax]), 2 * rr) / 2 - rr)
                colliders.append(shape)
        for child in v["children"]:
            if child in tf:
                walk(child, np_, nr, ls, (path + "/" if path else "") + nm)

    for t in [t for t, v in tf.items() if v["father"] == 0]:
        walk(t, (0, 0, 0), (0, 0, 0, 1), (1, 1, 1), "")
    mesh = (np.asarray([p for vs in verts for p in vs], float).reshape(-1, 3),
            np.concatenate(tris) if tris else np.zeros((0, 3), int))
    return mesh, colliders
