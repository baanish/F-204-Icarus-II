"""Find lookups of retired part names: the skin families the breakup split cuts into pieces survive only as family names
(art/blender/parts.py family, IcarusAuthor SkinFamily), so code that looks one up as a part reaches nothing.

python tools/check_retired_names.py [name ...]

Searches src/, unity/Assets/Icarus/, art/blender/ and tools/ for each retired name (all of them, or those named) in a
lookup form: an index (O[...], all_objects[...], Parts[...], Meshes[...]), a call Part(...), an == comparison, a dict
key or TREE row, or "<stem>" + side where the name is <stem> plus a side. A prefix that still matches the pieces
(startswith, StartsWith, a prefix tuple) is no lookup, and lines that go through the family helpers are allowed;
ALLOW names the files and names that hold a family on purpose. Exits nonzero with each hit.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("src", "unity/Assets/Icarus", "art/blender", "tools")
# Retired as part names; each survives as a family name.
RETIRED = ("wing_skin_L", "wing_skin_R", "skin_mid_L", "skin_mid_R", "skin_aft_L", "skin_aft_R", "dorsal_cover")
# (file, name): the family whole on purpose. parts.py's TREE builds each family before split_pieces cuts it; the skin bake
# and its reviews read the split=False build, where the families are whole.
ALLOW = {
    ("art/blender/parts.py", name) for name in RETIRED
} | {
    ("art/blender/bake_skin.py", name) for name in RETIRED
} | {
    ("art/blender/skin_review.py", name) for name in RETIRED
} | {
    ("art/blender/pilot2_skin.py", name) for name in RETIRED
} | {
    ("art/blender/lights.py", name) for name in ("wing_skin_L", "wing_skin_R", "dorsal_cover", "skin_mid_L")
} | {
    ("tools/check_retired_names.py", name) for name in RETIRED
} | {
    ("tools/test_breakup_split.py", name) for name in RETIRED
}
HELPERS = ("family_objects", "family(", "FamilyParts", "FamilyVertices", "SkinFamily", "parts.family")


def forms(name):
    q = r"""["']""" + re.escape(name) + r"""["']"""
    out = [r"\[\s*" + q + r"\s*\]", r"Part\(\s*" + q, r"==\s*" + q, q + r"\s*==", q + r"\s*:"]
    if name.endswith(("_L", "_R")):
        out.append(r"""["']""" + re.escape(name[:-1]) + r"""["']\s*\+""")
    return re.compile("|".join(out))


def main():
    names = sys.argv[1:] or RETIRED
    hits = []
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            if path.suffix not in (".py", ".cs") or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO).as_posix()
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for name in names:
                if (rel, name) in ALLOW:
                    continue
                pattern = forms(name)
                for number, line in enumerate(lines, 1):
                    if pattern.search(line) and not any(h in line for h in HELPERS):
                        hits.append("%s:%d: %s: %s" % (rel, number, name, line.strip()))
    if hits:
        print("RETIRED NAMES: %d lookups\n  %s" % (len(hits), "\n  ".join(hits)))
        sys.exit(1)
    print("RETIRED NAMES: none of %s looked up" % ", ".join(names))


if __name__ == "__main__":
    main()
