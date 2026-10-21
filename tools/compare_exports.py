"""Compare two export folders for content, ignoring what Blender's FBX writer changes on every run.

python tools/compare_exports.py <folder-a> <folder-b>

Two exports of the same scene differ in bytes: each FBX carries its creation time, and the writer derives object
UIDs from Python's per-process string hash. This compares each FBX's node tree with the timestamp dropped and every
UID renumbered in order of first use, and blockout.json with its FBX hashes dropped, so it passes exactly when the
exports carry the same meshes, transforms, materials and properties. Any other file must match byte for byte.
Exits nonzero on a difference. To compare against a commit: git archive <rev> art/export | tar -x -C <folder>.
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrub_fbx import read_tree


def fbx_content(data):
    """The node tree with CreationTimeStamp dropped and every int64 UID renumbered by first use."""
    tree, _ = read_tree(data)
    # a UID is the first property of each object and document; connections and properties refer to them
    owned = {struct.unpack_from("<q", node[1][0], 1)[0] for top in tree if top[0] in (b"Objects", b"Documents")
             for node in top[2] if node[1] and node[1][0][:1] == b"L"}
    uids = {}

    def prop(p):
        if p[:1] == b"L":
            value = struct.unpack_from("<q", p, 1)[0]
            if value in owned:
                return ("uid", uids.setdefault(value, len(uids) + 1))
        return p

    def walk(nodes):
        return [(name, [prop(p) for p in props], walk(children))
                for name, props, children in nodes if name != b"CreationTimeStamp"]

    return walk(tree)


def blockout_content(text):
    data = json.loads(text)
    data.pop("source_sha256", None)
    for part in data.get("parts", {}).values():
        part.pop("sha256", None)
    return data


def differences(a, b):
    names = sorted({p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()}
                   | {p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()})
    out = []
    for name in names:
        fa, fb = a / name, b / name
        if not fa.is_file() or not fb.is_file():
            out.append(f"{name}: only in {a if fa.is_file() else b}")
        elif name.endswith(".fbx"):
            if fbx_content(fa.read_bytes()) != fbx_content(fb.read_bytes()):
                out.append(f"{name}: FBX content differs")
        elif name == "blockout.json":
            ja, jb = blockout_content(fa.read_text(encoding="utf-8")), blockout_content(fb.read_text(encoding="utf-8"))
            if ja != jb:
                keys = sorted(k for k in ja.get("parts", {}).keys() | jb.get("parts", {}).keys()
                              if ja.get("parts", {}).get(k) != jb.get("parts", {}).get(k))
                top = sorted(k for k in ja.keys() | jb.keys() if k != "parts" and ja.get(k) != jb.get(k))
                out.append(f"{name}: differs in {', '.join(top + keys[:8])}{' ...' if len(keys) > 8 else ''}")
        elif fa.read_bytes() != fb.read_bytes():
            out.append(f"{name}: bytes differ")
    return out, len(names)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    found, count = differences(Path(sys.argv[1]), Path(sys.argv[2]))
    for line in found:
        print("  " + line)
    if found:
        raise SystemExit(f"EXPORT COMPARE FAIL: {len(found)} of {count} files differ in content")
    print(f"EXPORT COMPARE PASS: {count} files carry the same content")


if __name__ == "__main__":
    main()
