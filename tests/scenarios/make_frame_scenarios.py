"""Regenerate the frame-time comparisons: python tests/scenarios/make_frame_scenarios.py."""
import copy
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_scenario(path):
    text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
    return json.loads(re.sub(r",\s*([}\]])", r"\1", text))


def generate():
    template = read_scenario(HERE / "breakup_missile_hit.scenario.jsonc")
    for jet, title in (("baanish_icarus", "Icarus"), ("Fighter1", "FS-12 Revoker")):
        for count in (1, 8):
            source = "icarus_ignus_10km_half" if count == 1 else "icarus_ignus_10km_eight"
            scenario = copy.deepcopy(template)
            scenario["steps"] = [s for s in scenario["steps"]
                                 if s.get("label") != "a primary structural part detaches in the air"]
            scenario["steps"][0]["require"]["all"][1]["eq"] = jet
            scenario["steps"][0]["label"] = f"the {title} airborne at 10 km"
            scenario["steps"][11]["label"] = f"the missile hits the {title}"
            if jet == "baanish_icarus":
                scenario["steps"].insert(1, {
                    "require": {"path": "mods.baanish.icarus.loadout", "eq": "||"},
                    "label": "loadout: all three hardpoint sets empty", "within": 3})
                scenario["mission"] = source + ".mission.json"
            else:
                mission = json.loads((HERE / (source + ".mission.json")).read_text())
                mission["missionSettings"]["description"] = (
                    f"Frame-time comparison: {count} FS-12 Revoker at 10,000 m, 400 m/s, half fuel, "
                    "stock default loadout; seven wingmen 400 m apart when present.")
                for index, aircraft in enumerate(mission["aircraft"]):
                    aircraft["type"] = jet
                    aircraft["UniqueName"] = f"Revoker_{index}"
                    aircraft["savedLoadout"] = {"Selected": []}
                mission_name = f"frames_{jet}_{count}.mission.json"
                (HERE / mission_name).write_text(json.dumps(mission, indent=2) + "\n", encoding="utf-8", newline="\n")
                scenario["mission"] = mission_name
            name = f"frames_{jet}_{count}.scenario.jsonc"
            header = (
                f"// Frame time with {count} {title} aircraft at 10 km, 400 m/s and half fuel over Ignus.\n"
                "// Pass: the missile hits. Measure p95 over 10 s intact, 10 s after the hit and 30 s of debris.\n"
                "// Only the player's aircraft is hit; seven AI wingmen remain in the eight-aircraft comparison.\n"
                "// Compare alternating runs with tools/frame_gate.py at the first buildable change to parts, colliders or per-frame code.\n"
                f"// From the repo root: no-agentic run --uncapped tests/scenarios/{name}\n")
            body = json.dumps({k: v for k, v in scenario.items() if k != "steps"}, indent=2)[:-2]
            body += ',\n  "steps": [\n'
            body += ',\n'.join('    ' + json.dumps(s) for s in scenario["steps"])
            body += '\n  ]\n}\n'
            (HERE / name).write_text(header + body, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generate()
