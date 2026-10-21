"""Read stock prefabs and meshes from the game export (tools/local-paths.json game_export), and print a prefab's
hierarchy with transforms, meshes (tris, bounds), materials and scripts.

python tools/stores/prefab_tree.py <PrefabName> [--filter REGEX]

Positions are local; each row also shows the position in the prefab root's frame and the mesh AABB transformed into
that frame (min..max).
"""
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stores import paths


def asset_index(root, *folders):
    """GUID -> asset path for every asset under root's folders (all of root when none are named), from the .meta
    files AssetRipper writes beside each asset."""
    metas = [m for f in folders for m in (root / f).glob("*.meta")] if folders else root.rglob("*.meta")
    index = {}
    for meta in metas:
        with open(meta, "rb") as f:
            found = re.search(rb"guid: ([0-9a-f]{32})", f.read(200))
        if found:
            index[found[1].decode()] = str(meta)[:-len(".meta")]
    return index


def docs_of(path):
    text = path.read_text(errors='replace')
    ms = list(re.finditer(r'^--- !u!(\d+) &(-?\d+).*\n', text, re.M))
    out = {}
    for i, m in enumerate(ms):
        body = text[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(text)]
        out[int(m[2])] = dict(type=int(m[1]), body=body, line=text[:m.start()].count('\n') + 1)
    return out


def f3(body, key):
    m = re.search(key + r': \{x: ([-+\dEe.]+), y: ([-+\dEe.]+), z: ([-+\dEe.]+)(?:, w: ([-+\dEe.]+))?\}', body)
    return tuple(float(v) for v in m.groups() if v is not None) if m else None


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx, aw*bz + ax*by - ay*bx + az*bw, aw*bw - ax*bx - ay*by - az*bz)


def qrot(q, v):
    x, y, z, w = q
    p = (v[0], v[1], v[2], 0.0)
    r = qmul(qmul(q, p), (-x, -y, -z, w))
    return r[:3]


def euler(q):
    # Unity ZXY convention, degrees
    x, y, z, w = q
    sinx = 2 * (w*x - y*z)
    ex = math.degrees(math.asin(max(-1, min(1, sinx))))
    ey = math.degrees(math.atan2(2*(w*y + x*z), 1 - 2*(x*x + y*y)))
    ez = math.degrees(math.atan2(2*(w*z + x*y), 1 - 2*(x*x + z*z)))
    return tuple(round(v, 1) + 0.0 for v in (ex, ey, ez))


def mesh_info(index, guid):
    p = index.get(guid)
    if not p or not p.endswith('.asset'):
        return (Path(p).name if p else guid, None, None, None)
    head = Path(p).read_text(errors='replace')
    tris = sum(int(x) for x in re.findall(r'indexCount: (\d+)', head.split('m_Shapes:')[0])) // 3
    sub = len(re.findall(r'indexCount:', head.split('m_Shapes:')[0]))
    aabb = re.search(r'm_LocalAABB:\s*\n\s*m_Center: \{x: ([-+\dEe.]+), y: ([-+\dEe.]+), z: ([-+\dEe.]+)\}\s*\n\s*m_Extent: \{x: ([-+\dEe.]+), y: ([-+\dEe.]+), z: ([-+\dEe.]+)\}', head)
    aabb = tuple(float(v) for v in aabb.groups()) if aabb else None
    return (Path(p).stem, tris, sub, aabb)


def main():
    name = sys.argv[1]
    flt = sys.argv[sys.argv.index('--filter') + 1] if '--filter' in sys.argv else None
    root = paths.load()["game_export"]
    index = asset_index(root)
    docs = docs_of(root / 'GameObject' / (name + '.prefab'))
    gos = {fid: d for fid, d in docs.items() if d['type'] == 1}
    comps = {}
    for fid, d in docs.items():
        m = re.search(r'm_GameObject: \{fileID: (-?\d+)\}', d['body'])
        if m and d['type'] != 1: comps.setdefault(int(m[1]), []).append((fid, d))
    tf = {}
    for go, cs in comps.items():
        for fid, d in cs:
            if d['type'] in (4, 224):
                b = d['body']
                father = int(re.search(r'm_Father: \{fileID: (-?\d+)\}', b)[1])
                children = [int(c) for c in re.findall(r'- \{fileID: (-?\d+)\}', b.split('m_Children:')[1].split('m_Father')[0])]
                tf[fid] = dict(go=go, pos=f3(b, 'm_LocalPosition'), rot=f3(b, 'm_LocalRotation'), scl=f3(b, 'm_LocalScale'), father=father, children=children)
    roots = [t for t, v in tf.items() if v['father'] == 0]
    def walk(t, depth, wpos, wrot, wscl, pathname):
        v = tf[t]; go = v['go']
        nm = re.search(r'm_Name: (.*)', gos[go]['body'])[1]
        active = re.search(r'm_IsActive: (\d)', gos[go]['body'])[1]
        pth = (pathname + '/' if pathname else '') + nm
        s = v['scl']; ls = (s[0]*wscl[0], s[1]*wscl[1], s[2]*wscl[2])
        p = qrot(wrot, tuple(v['pos'][i]*wscl[i] for i in range(3)))
        np = tuple(wpos[i] + p[i] for i in range(3)); nr = qmul(wrot, v['rot'])
        info = []
        for fid, d in comps.get(go, []):
            b = d['body']
            if d['type'] == 33:
                g = re.search(r'm_Mesh: \{fileID: -?\d+, guid: (\w+)', b)
                if g:
                    mn, tris, sub, aabb = mesh_info(index, g[1])
                    s2 = f'MESH {mn} tris={tris} sub={sub}'
                    if aabb:
                        c, e = aabb[:3], aabb[3:]
                        pts = []
                        for sx in (-1, 1):
                            for sy in (-1, 1):
                                for sz in (-1, 1):
                                    lp = tuple((c[i] + [sx, sy, sz][i]*e[i]) * ls[i] for i in range(3))
                                    rp = qrot(nr, lp); pts.append(tuple(np[i] + rp[i] for i in range(3)))
                        lo = [round(min(q[i] for q in pts), 3) for i in range(3)]; hi = [round(max(q[i] for q in pts), 3) for i in range(3)]
                        s2 += f' rootAABB x[{lo[0]},{hi[0]}] y[{lo[1]},{hi[1]}] z[{lo[2]},{hi[2]}]'
                    info.append(s2)
            elif d['type'] in (23, 137):
                mats = [Path(index.get(g, g)).stem for g in re.findall(r'guid: (\w+)', b.split('m_Materials:')[1].split('m_StaticBatchInfo')[0])] if 'm_Materials:' in b else []
                en = re.search(r'm_Enabled: (\d)', b)[1]
                info.append(f"{'SKIN' if d['type']==137 else 'RENDER'} en={en} mats={mats}")
            elif d['type'] == 114:
                g = re.search(r'm_Script: \{fileID: -?\d+, guid: (\w+)', b)
                sc = Path(index.get(g[1], g[1])).stem if g else '?'
                info.append(f'MB {sc}@{d["line"]}')
            elif d['type'] not in (4, 224):
                info.append(f'C{d["type"]}')
        e = euler(v['rot'])
        line = f"{'  '*depth}{nm}{'' if active=='1' else ' [inactive]'} @{gos[go]['line']} lpos={tuple(round(x,3) for x in v['pos'])} leul={e} lscl={v['scl']} rootpos={tuple(round(x,3) for x in np)} rooteul={euler(nr)} | {'; '.join(info)}"
        if not flt or re.search(flt, pth, re.I): print(line)
        for c in v['children']:
            if c in tf: walk(c, depth + 1, np, nr, ls, pth)
    for r in roots: walk(r, 0, (0, 0, 0), (0, 0, 0, 1), (1, 1, 1), '')


if __name__ == '__main__':
    main()
