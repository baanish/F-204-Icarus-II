"""Write bullet_hits.mission.json: a gun-only Ifrit behind a clean Icarus.

Run python tests/scenarios/make_bullet_hit_mission.py. The scenario routes the AI target straight north.
"""
import json
from pathlib import Path

here = Path(__file__).resolve().parent
mission = json.loads((here / "playtest_gun_kills.mission.json").read_text(encoding="utf-8"))
mission["aircraft"] = mission["aircraft"][:2]
player = mission["aircraft"][0]
player["startingSpeed"] = 220
player["savedLoadout"] = {"Selected": [{"Key": "autocannon_27mm_internal"}] + [{"Key": ""} for _ in range(6)]}
target = mission["aircraft"][1]
target["UniqueName"] = "BulletTarget"
target["startingSpeed"] = 220
target["globalPosition"] = dict(player["globalPosition"])
target["globalPosition"]["z"] += 180
target["savedLoadout"] = {"Selected": [{"Key": ""} for _ in range(3)]}
mission["objectives"] = mission["objectives"][:1]
mission["objectives"][0]["Outcomes"] = ["Reveal bullet target"]
mission["outcomes"] = [{"Type": "RevealUnit", "UniqueName": "Reveal bullet target", "UnitsToReveal": ["BulletTarget"]}]
mission["missionSettings"]["description"] = "Icarus bullet interception test. Gun-only Ifrit at 8,000 m, heading north at 220 m/s. A clean AI Icarus spawns 180 m ahead at the same speed. The scenario routes it straight north and fires a short gun burst."
output = here / "bullet_hits.mission.json"
output.write_text(json.dumps(mission, indent=2) + "\n", encoding="utf-8")
print(output)
