"""How an Icarus came apart in one scenario run: which parts broke their own joint, which fell with them, and how big the
largest piece shed was.

python tools/breakup_report.py <run folder> [<run folder> ...] [--blockout art/export/blockout.json] [--json]

A part's own joint breaking is logged by the plugin as a "[Icarus] joint-break <part>" line (PartContactLog.cs) in the
run's trace; those are the independent detaches. A lump is a part whose own joint broke plus every descendant still on
it then, weighed by the dry masses in blockout.json (fuel left out, since its level varies); the descendants are the
cascaded detaches (the game raises no "part_detached" for them: they never drift from their parent). The hit is the
first "missile_end" event with result "hit" (else the first "damage" event). The root, fuselage_mid ("Icarus" in
game), is the aircraft and never a lump. "part_detached" events time the 5th and 10th part the game saw come off.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT, ROOT_IN_GAME = "fuselage_mid", "Icarus"
BREAK = re.compile(r"\[Icarus\] joint-break (\S+):")
DAMAGE = re.compile(r"\[Icarus\] damage (\S+): pierce ([\d.]+), blast ([\d.]+), fire ([\d.]+), impact ([\d.]+)")


def part_tree(blockout):
    """{part: (parent part or None, dry kg)}. A hinged surface's part is its hinge, which carries no mesh: its mass is
    on the <hinge>_visible child."""
    entries = json.loads(Path(blockout).read_text(encoding="utf-8"))["parts"]
    masses = {}
    for name, entry in entries.items():
        mass = (entry.get("props") or {}).get("mass_kg")
        if mass is None:
            continue
        hinge = entry.get("blender_parent")
        if name.endswith("_visible") and hinge == name[:-len("_visible")]:
            name = hinge
        masses[name] = masses.get(name, 0.0) + mass

    def parent(name):
        up = entries[name].get("blender_parent")
        while up is not None and up not in masses:
            up = entries[up].get("blender_parent")
        return up

    return {name: (parent(name), mass) for name, mass in masses.items()}


def game_name(part):
    return ROOT_IN_GAME if part == ROOT else part


def report(run, tree):
    events = [json.loads(line) for line in (Path(run) / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line]
    hit = next((e["t"] for e in events if e.get("name") == "missile_end" and e.get("result") == "hit"), None)
    if hit is None:
        hit = next((e["t"] for e in events if e.get("name") == "damage"), None)
    if hit is None:
        raise ValueError("%s: no hit and no damage in the trace" % run)
    by_game = {game_name(p): p for p in tree}
    detached = {}
    for e in events:
        if e.get("name") == "part_detached" and e["t"] >= hit:
            detached.setdefault(by_game.get(e["part"], e["part"]), e["t"] - hit)
    broke = {}
    damage = {}
    for e in events:
        if e.get("k") != "l" or e["t"] < hit:
            continue
        m = BREAK.search(e.get("text", ""))
        if m:
            broke.setdefault(by_game.get(m.group(1), m.group(1)), e["t"] - hit)
        m = DAMAGE.search(e.get("text", ""))
        if m:
            name = by_game.get(m.group(1), m.group(1))
            # Blast only: pierce, fire and impact also land while the pieces tumble and hit each other.
            damage[name] = damage.get(name, 0.0) + float(m.group(3))
    children = {}
    for name, (parent, _) in tree.items():
        children.setdefault(parent, []).append(name)

    def lump(part, at):
        """The part and its descendants with mass still on it at time at: a descendant whose own joint broke by then is
        its own lump."""
        out, todo = [], [part]
        while todo:
            p = todo.pop()
            out.append(p)
            todo += [c for c in children.get(p, ()) if not (c in broke and broke[c] <= at)]
        return [p for p in out if tree[p][1] > 0]

    lumps = sorted(((sum(tree[p][1] for p in lump(part, at)), part, at, len(lump(part, at)))
                    for part, at in broke.items() if part != ROOT and part in tree), reverse=True)
    order = sorted(detached.values())
    return {
        "run": Path(run).name,
        "hit_t": round(hit, 2),
        "independent": len([p for p in broke if p != ROOT]),
        "independent_within_2s": len([p for p, t in broke.items() if p != ROOT and t <= 2.0]),
        "cascaded": sum(n - 1 for _, _, _, n in lumps),
        "detached": len(detached),
        "t_5th_s": round(order[4], 2) if len(order) >= 5 else None,
        "t_10th_s": round(order[9], 2) if len(order) >= 10 else None,
        "largest_lump_kg": round(lumps[0][0], 1) if lumps else 0.0,
        "largest_lump": "%s (%d parts, +%.2f s)" % (lumps[0][1], lumps[0][3], lumps[0][2]) if lumps else None,
        "lumps": [{"part": part, "kg": round(kg, 1), "parts": n, "t_s": round(at, 2)} for kg, part, at, n in lumps],
        "blast_by_family": {k: round(v, 1) for k, v in sorted(damage.items(), key=lambda kv: -kv[1])},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--blockout", default=str(REPO / "art/export/blockout.json"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    tree = part_tree(args.blockout)
    results = [report(run, tree) for run in args.runs]
    if args.json:
        print(json.dumps(results, indent=2))
        return
    for r in results:
        print("%s: %d independent (%d within 2 s of the hit), %d cascaded; 5th at %s s, 10th at %s s; largest lump %.0f kg, %s"
              % (r["run"], r["independent"], r["independent_within_2s"], r["cascaded"], r["t_5th_s"], r["t_10th_s"],
                 r["largest_lump_kg"], r["largest_lump"]))
    if len(results) > 1:
        print("median: %s independent within 2 s, largest lump %.0f kg" % (
            statistics.median(r["independent_within_2s"] for r in results),
            statistics.median(r["largest_lump_kg"] for r in results)))


if __name__ == "__main__":
    sys.exit(main())
