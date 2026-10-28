"""The peaks a flight scenario run reached, read from its trace: roll rate and roll command, load factor, the joint
nearest its break, each wing crank's tip movement, each drawn wing and tail part's drawn and physical offsets, and the
thrust line's turn.

python tools/flight_peaks.py <run folder> [<run folder> ...] [--since <mark>] [--json]

Samples (own.roll_rate_dps, own.ctl.in.roll, own.load_g) come from the trace's samples after the mark (default: the
whole run). The plugin's stage lines give the rest (src/Icarus/TailFlex.cs, WingSkinFollow.cs): "joint-load: nearest
break: <joint> <load over limit>", "wing-crank-<side>: tip_mm=<mm> joint=<load>", "thrust-line: turn_deg=<deg>", and the "wing-skin-<piece>",
"wing-draw-<part>" and "tail-draw-<part>" lines' physical_mm and drawn_mm while attached, each part's offset off its rest
in the frame of the part its seam meets, and their ulp_mm, the float32 spacing of world positions where the jet was (the
finest two bodies can be drawn apart); a sample whose drawn_mm is over its own ulp_mm counts as drawn over spacing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

JOINT = re.compile(r"joint-load: nearest break: (\S+) ([0-9.]+)")
CRANK = re.compile(r"wing-crank-(\w): tip_mm=([0-9.]+) joint=([0-9.NaN]+)")
ULP = re.compile(r"ulp_mm=([0-9.]+)")
THRUST = re.compile(r"thrust-line: turn_deg=([0-9.]+)")
SKIN = re.compile(r"(?:wing-skin|wing-draw|tail-draw)-(\S+): g=([-0-9.]+) physical_mm=([0-9.NaN]+) .*attached=(\w+) drawn_mm=([0-9.NaN]+)")


def peaks(run, since=None):
    events = [json.loads(line) for line in (Path(run) / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line]
    start = 0.0
    if since:
        start = next((e["t"] for e in events if e.get("name") == "mark" and e.get("label") == since), None)
        if start is None:
            raise ValueError("%s: no mark %s" % (run, since))
    out = {"run": Path(run).name, "roll_rate_dps": 0.0, "roll_command": 0.0, "load_g": 0.0, "joint": (0.0, None),
           "crank_mm": {}, "crank_joint": {}, "skin_drawn_mm": {}, "skin_physical_mm": {}, "ulp_mm": 0.0,
           "drawn_over_spacing": 0, "thrust_turn_deg": 0.0}
    for e in events:
        if e["t"] < start:
            continue
        own = e.get("own") if e.get("k") == "s" else None
        if own:
            out["roll_rate_dps"] = max(out["roll_rate_dps"], abs(own.get("roll_rate_dps") or 0.0))
            out["roll_command"] = max(out["roll_command"], abs(((own.get("ctl") or {}).get("in") or {}).get("roll") or 0.0))
            out["load_g"] = max(out["load_g"], own.get("load_g") or 0.0)
        text = e.get("text", "") if e.get("k") == "l" else ""
        m = JOINT.search(text)
        if m and float(m.group(2)) > out["joint"][0]:
            out["joint"] = (float(m.group(2)), m.group(1))
        m = CRANK.search(text)
        if m:
            out["crank_mm"][m.group(1)] = max(out["crank_mm"].get(m.group(1), 0.0), float(m.group(2)))
            if m.group(3) != "NaN":
                out["crank_joint"][m.group(1)] = max(out["crank_joint"].get(m.group(1), 0.0), float(m.group(3)))
        m = THRUST.search(text)
        if m:
            out["thrust_turn_deg"] = max(out["thrust_turn_deg"], float(m.group(1)))
        m = SKIN.search(text)
        if m and m.group(4) == "True" and m.group(5) != "NaN":
            out["skin_drawn_mm"][m.group(1)] = max(out["skin_drawn_mm"].get(m.group(1), 0.0), float(m.group(5)))
            out["skin_physical_mm"][m.group(1)] = max(out["skin_physical_mm"].get(m.group(1), 0.0), float(m.group(3)))
            ulp = ULP.search(text)
            if ulp:
                out["ulp_mm"] = max(out["ulp_mm"], float(ulp.group(1)))
                out["drawn_over_spacing"] += float(m.group(5)) > float(ulp.group(1))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--since")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = [peaks(run, args.since) for run in args.runs]
    if args.json:
        print(json.dumps(results, indent=2))
        return
    for r in results:
        print("%s: roll rate %.1f deg/s (roll command %.2f), %.2f g, nearest joint %s %.2f; crank tip mm %s, crank joint %s; "
              "thrust line turn %.3f deg; float spacing up to %.4f mm, %d samples drawn over it; drawn parts mm %s, physical mm %s" % (r["run"], r["roll_rate_dps"], r["roll_command"], r["load_g"], r["joint"][1],
                                                          r["joint"][0], r["crank_mm"], r["crank_joint"], r["thrust_turn_deg"], r["ulp_mm"], r["drawn_over_spacing"], r["skin_drawn_mm"],
                                                          r["skin_physical_mm"]))


if __name__ == "__main__":
    sys.exit(main())
