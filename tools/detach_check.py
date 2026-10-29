"""Checks the parts an Icarus shed in a run against the plugin's "part-detached <UniqueName> <part>: id <id>" lines.

  python tools/detach_check.py peers <run>   breakup_peers: each peer must log the same nonempty (part, id) set for
                                             every Icarus that broke up, and at least two must have (both breakups).
  python tools/detach_check.py rearm <run>   damage_rearm_kill: the parts the game detached (trace part_detached) must
                                             be the parts the plugin logged, each with one id under 256.

Prints the comparison and exits 1 on any difference.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r"\[Icarus\] part-detached (\S+) (\S+): id (\d+)")


def logged(log):
    units = defaultdict(set)
    for line in Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
        if (m := LINE.search(line)):
            units[m[1]].add((m[2], int(m[3])))
    return units


def peers(run):
    host, client = (logged(Path(run) / "peers" / peer / "LogOutput.log") for peer in ("host", "client"))
    problems = []
    for unit in sorted(set(host) | set(client)):
        if host[unit] != client[unit]:
            problems.append(f"{unit}: host only {sorted(host[unit] - client[unit])}, "
                            f"client only {sorted(client[unit] - host[unit])}")
        print(f"{unit}: {len(host[unit])} parts on the host, {len(client[unit])} on the client")
    if len(set(host) & set(client)) < 2:
        problems.append(f"expected both breakups on both peers, got {sorted(set(host) & set(client))}")
    return problems


def rearm(run):
    run = Path(run)
    units = logged(run / "LogOutput.log")
    game = [json.loads(line)["part"] for line in (run / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if '"part_detached"' in line and json.loads(line).get("name") == "part_detached"]
    problems = []
    if len(units) != 1:
        return [f"expected one Icarus logging detachments, got {sorted(units)}"]
    (unit, parts), = units.items()
    ids = defaultdict(set)
    for part, part_id in parts:
        ids[part].add(part_id)
    if sorted(game) != sorted(ids):
        problems.append(f"game detached {sorted(game)}, plugin logged {sorted(ids)}")
    problems += [f"{part}: ids {sorted(found)}" for part, found in ids.items() if len(found) != 1 or max(found) >= 256]
    print(f"{unit}: game detached {len(game)} parts, plugin logged {len(ids)}")
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("peers", "rearm"):
        sys.exit(__doc__)
    problems = {"peers": peers, "rearm": rearm}[sys.argv[1]](sys.argv[2])
    for problem in problems:
        print("FAIL " + problem)
    print("DETACH CHECK " + ("FAIL" if problems else "PASS"))
    sys.exit(1 if problems else 0)
