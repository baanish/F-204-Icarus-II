"""Run alternating Icarus/Revoker frame-time comparisons, or summarize one saved queue."""
import argparse
import json
import math
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JETS = ("baanish_icarus", "Fighter1")
PHASES = ("intact", "breakup", "debris")
# The framework's --uncapped mode uses the game's maximum cap, 1000 FPS.
UNCAPPED_FPS = 1000


def frame_times(folder):
    verdict = json.loads((folder / "verdict.json").read_text(encoding="utf-8"))
    if verdict["verdict"] not in ("PASS", "MEASURED"):
        raise ValueError(f"{folder.name}: incomplete or failed run")
    events = [json.loads(line) for line in (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if not any(e.get("name") == "missile_end" and e.get("result") == "hit" for e in events):
        raise ValueError(f"{folder.name}: missile hit missing")
    result = {}
    for phase in PHASES:
        frames = [e for e in events if e.get("name") == "frames" and e.get("label") == phase]
        if len(frames) != 1 or frames[0]["frames"] <= 0:
            raise ValueError(f"{folder.name}: {phase} window missing or repeated")
        frame = frames[0]
        value = frame["p95_ms"]
        if not math.isfinite(value) or value <= 0 or frame["vsync"] != 0 or frame["fps_cap"] not in (-1, UNCAPPED_FPS):
            raise ValueError(f"{folder.name}: invalid or capped {phase} window")
        result[phase] = value
    return result


def print_table(entries):
    table = {}
    for jet in JETS:
        for count in (1, 8):
            runs = [frame_times(ROOT / e["folder"]) for e in entries if e["jet"] == jet and e["count"] == count]
            if not runs:
                raise ValueError(f"missing {jet} with {count} aircraft")
            table[jet, count] = {p: statistics.median(r[p] for r in runs) for p in PHASES}
    print("Aircraft | Count | Phase | Runs | Median p95 ms | Ratio to Revoker | Per extra jet ms")
    print("--- | --- | --- | --- | --- | --- | ---")
    for jet in JETS:
        for count in (1, 8):
            n = sum(e["jet"] == jet and e["count"] == count for e in entries)
            for phase in PHASES:
                value = table[jet, count][phase]
                ratio = value / table["Fighter1", count][phase]
                extra = f"{(value - table[jet, 1][phase]) / 7:.3f}" if count == 8 else "n/a"
                print(f"{jet} | {count} | {phase} | {n} | {value:.3f} | {ratio:.3f} | {extra}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", default="no-agentic", help="Framework executable")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--manifest", type=Path, default=Path(".cache/frame-gate/queue.json"))
    parser.add_argument("--table-only", action="store_true", help="Read the manifest without starting the game")
    args = parser.parse_args()
    manifest = ROOT / args.manifest
    if args.table_only:
        print_table(json.loads(manifest.read_text(encoding="utf-8")))
        return
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if manifest.exists():
        parser.error("manifest exists; choose a new --manifest to keep build comparisons separate")
    queue = [(jet, count) for _ in range(args.repeats) for count in (1, 8) for jet in JETS]
    for jet, count in dict.fromkeys(queue):
        subprocess.run([args.runner, "lint", f"tests/scenarios/frames_{jet}_{count}.scenario.jsonc"], cwd=ROOT, check=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    manifest.write_text("[]\n", encoding="utf-8")
    for jet, count in queue:
        scenario = f"frames_{jet}_{count}"
        runs = ROOT / ".agentic/runs"
        before = set(runs.glob(f"*-{scenario}"))
        subprocess.run([args.runner, "run", "--uncapped", f"tests/scenarios/{scenario}.scenario.jsonc"], cwd=ROOT, check=True)
        created = set(runs.glob(f"*-{scenario}")) - before
        if len(created) != 1:
            raise ValueError(f"expected one new run for {scenario}, found {len(created)}")
        folder = created.pop()
        frame_times(folder)
        entries.append({"jet": jet, "count": count, "folder": folder.relative_to(ROOT).as_posix()})
        manifest.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print_table(entries)


if __name__ == "__main__":
    main()
