"""Read vertex positions from an AssetRipper YAML Mesh asset (stream 0 position channel)."""
import re, struct
from pathlib import Path
SIZES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}

def positions(mesh_path):
    t = Path(mesh_path).read_text(errors='replace')
    vd = t[t.index('m_VertexData:'):]
    n = int(re.search(r'm_VertexCount: (\d+)', vd)[1])
    chans = re.findall(r'- stream: (\d+)\s+offset: (\d+)\s+format: (\d+)\s+dimension: (\d+)', vd.split('m_DataSize')[0])
    chans = [tuple(map(int, c)) for c in chans]
    s0 = [c for c in chans if c[0] == 0 and (c[3] & 0xF) > 0]
    stride = max(c[1] + SIZES[c[2]] * (c[3] & 0xF) for c in s0)
    hexdata = re.search(r'_typelessdata: ([0-9a-f]+)', vd)[1]
    raw = bytes.fromhex(hexdata)
    pos = chans[0]
    assert pos[2] == 0 and (pos[3] & 0xF) == 3, pos
    return [struct.unpack_from('<3f', raw, i * stride + pos[1]) for i in range(n)]

def triangles(mesh_path):
    """Triangle vertex-index triples of every triangle submesh (index buffer, firstByte, indexCount, baseVertex)."""
    t = Path(mesh_path).read_text(errors='replace')
    fmt = int(re.search(r'm_IndexFormat: (\d)', t)[1])
    raw = bytes.fromhex(re.search(r'm_IndexBuffer: ([0-9a-f]*)', t)[1])
    size = 2 if fmt == 0 else 4
    out = []
    for m in re.finditer(r'firstByte: (\d+)\s+indexCount: (\d+)\s+topology: (\d+)\s+baseVertex: (\d+)', t.split('m_Shapes:')[0]):
        first, count, topo, base = map(int, m.groups())
        if topo != 0: continue
        idx = struct.unpack_from('<%d%s' % (count, 'H' if size == 2 else 'I'), raw, first)
        out.extend(tuple(base + i for i in idx[k:k + 3]) for k in range(0, count - 2, 3))
    return out
