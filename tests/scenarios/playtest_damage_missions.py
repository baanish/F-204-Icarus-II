"""Generate owner-flown destruction missions; optionally verify their saved copies.

Run from any directory: python tests/scenarios/playtest_damage_missions.py
After no-agentic lint --save-mission: rerun with --verify-saved.
Based on NO-Moonshot/tests/agentic/playtest_damage_missions.py.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
ICARUS = "baanish_icarus"
AIR_TO_AIR = ["AAM1_single", "AAM4_single", "baanish_icarus_AAM2_conformal"]
INTERCEPTOR = ["autocannon_27mm_internal", "AAM4_triple_internal", "AAM4_triple_internal",
               "AAM3_single_internal", "AAM2_double", "AAM1_double", ""]
# The Ifrit's stock loadout: the gun, three AAM-29 Scythes in each main bay, an IRM-S2 in each side bay.
IFRIT_STANDARD = ["autocannon_27mm_internal", "AAM2_triple_internal", "AAM2_triple_internal", "AAM3_single_internal", "", "", ""]
TARGET = ["", "bomb_500_single", ""]
# Combat AI clamps targetHeight to 8000 in AIPilotCombatModes.cs:1261. Starting
# there avoids its +5 m/s target-height drift at lower altitudes (:506-516).
# This is an AGL cap, not an MSL hold: Autopilot.cs:215-231 adds terrain height.
TARGET_ALTITUDE = 8000
# The targets' waypoint: 103 km north of their start, about 8 minutes at 200 m/s, and clear of the airfield at
# z 34,000. Targets that reach their waypoint circle and descend, so it must lie beyond the fight.
ROUTE_END_Z = 70000


def rotation(heading):
    yaw = math.radians(heading) / 2
    return {"x": 0.0, "y": math.sin(yaw), "z": 0.0, "w": math.cos(yaw)}


def aircraft(template, name, kind, faction, position, heading, speed, keys, player=False):
    unit = copy.deepcopy(template)
    unit.update(type=kind, faction=faction, UniqueName=name, playerControlled=player,
                playerControlledPriority=0, globalPosition=dict(zip(("x", "y", "z"), position)),
                rotation=rotation(heading), startingSpeed=speed, fuel=0.6,
                skill=1.0, bravery=0.5, livery=0, liveryType="Builtin", liveryName="",
                savedLoadout={"Selected": [{"Key": key} for key in keys]})
    return unit


def objective(kind, name, faction, outcomes=(), hidden=True, **fields):
    return {"Type": kind, "UniqueName": name, "Faction": faction, "DisplayName": name,
            "Hidden": hidden, "Outcomes": list(outcomes), **fields}


def base():
    mission = json.loads((HERE / "icarus_ignus_10km.mission.json").read_text(encoding="utf-8"))
    template = copy.deepcopy(mission["aircraft"][0])
    for key in ("aircraft", "vehicles", "ships", "buildings", "scenery", "containers", "missiles", "pilots"):
        mission[key] = []
    mission["objectives"] = []
    mission["outcomes"] = []
    for faction in mission["factions"]:
        faction.update(supplies=[], AIAircraftLimit=0, reserveAirframes=0,
                       extraReservesPerPlayer=0, preventJoin=faction["factionName"] != "Primeva")
    return mission, template


def shot_down():
    mission, template = base()
    mission["missionSettings"]["description"] = (
        "Icarus - shot down. Fly a Primeva F-204 Icarus II over Ignus at 9,000 m MSL, "
        "heading 090, 280 m/s, 60% fuel. Interceptor load: two MMR-S3, two AAM-36 Scimitars "
        "and two conformal AAM-29 Scythes. Two Boscali KR-67 Ifrits approach from 22 km; "
        "four more spawn at 120 seconds farther east. Each has the internal 27 mm gun "
        "with 540 rounds, six Scimitars, four Scythes, four MMR-S3 and two IRM-S2. "
        "No other combat units or automatic reinforcements. Let the enemy hit you to inspect destruction.")
    mission["aircraft"].append(aircraft(template, "Agentic_Own", ICARUS, "Primeva",
                                       (-78000, 9000, -10000), 90, 280, AIR_TO_AIR, player=True))
    for i, lateral in enumerate((-1500, 1500), 1):
        unit = aircraft(template, f"Interceptor {i}", "Multirole1", "Boscali",
                        (-56000, 9500, -10000 + lateral), 270, 330, INTERCEPTOR)
        unit["bravery"] = 5.0
        mission["aircraft"].append(unit)
    wave = []
    for i, lateral in enumerate((-4500, -1500, 1500, 4500), 3):
        name = f"Interceptor {i}"
        wave.append(name)
        unit = aircraft(template, name, "Multirole1", "Boscali",
                        (-18000, 10000, -10000 + lateral), 270, 330, INTERCEPTOR)
        unit["bravery"] = 5.0
        mission["aircraft"].append(unit)
    mission["objectives"] = [
        objective("None", "Mission Start", "Boscali", ["Start second wave timer", "Locate player"]),
        objective("WaitSeconds", "Second wave timer", "Boscali",
                  ["Spawn second wave", "Locate player"], seconds=120),
    ]
    mission["outcomes"] = [
        {"Type": "StartObjective", "UniqueName": "Start second wave timer", "objectivesToStart": ["Second wave timer"]},
        {"Type": "SpawnUnit", "UniqueName": "Spawn second wave", "UnitsToSpawn": wave},
        {"Type": "RevealUnit", "UniqueName": "Locate player", "UnitsToReveal": ["Agentic_Own"]},
    ]
    return mission


def gun_kills():
    mission, template = base()
    mission["missionSettings"]["description"] = (
        "Icarus - gun kills. Fly a Primeva KR-67 Ifrit at 8,000 m MSL, heading 000, "
        "330 m/s, in its standard loadout: the 27 mm gun with 540 rounds, six AAM-29 Scythes and two IRM-S2s. Four Boscali F-204 Icarus II "
        "targets start level at 8,000 m and 200 m/s, in trail 1 km apart, the first 1.8 km ahead. "
        "They follow a distant same-altitude northbound waypoint along western Ignus, with two GPO-500 "
        "bombs each and all other stations empty. The bombs prevent the unarmed AI's return to base "
        "without giving it an air-to-air weapon. Starting at the AI's 8,000 m AGL cap avoids the "
        "usual sustained climb over sea. Saved missions cannot enforce an exact MSL altitude or speed: "
        "terrain following, radar warnings, avoidance and damage can change flight, and cruise throttle "
        "can accelerate the targets. Approach promptly with radar off. No escorts or reinforcements. "
        "Restart to repeat. Level flight is a source-based best effort, not a flight-tested guarantee.")
    mission["aircraft"].append(aircraft(template, "Agentic_Own", "Multirole1", "Primeva",
                                       (-74000, TARGET_ALTITUDE, -35000), 0, 330, IFRIT_STANDARD, player=True))
    names = []
    for i in range(1, 5):
        name = f"Gun target {i}"
        names.append(name)
        mission["aircraft"].append(aircraft(template, name, ICARUS, "Boscali",
                                           (-74000, TARGET_ALTITUDE, -33200 + (i - 1) * 1000), 0, 200, TARGET))
    mission["objectives"] = [
        objective("None", "Mission Start", "Primeva", ["Start flight route", "Show gun targets"]),
        objective("ReachWaypoints", "Icarus northbound route", "Boscali", completeOrder="CompleteAny",
                  completeSomePercent=0.5, completeOnEnterRange=False,
                  waypoints=[{"Position": {"x": -74000, "y": TARGET_ALTITUDE, "z": ROUTE_END_Z}, "Range": 1000}]),
        objective("DestroyUnits", "Shoot down four Icarus targets", "Primeva", hidden=False,
                  completeOrder="CompleteAll", completeSomePercent=1.0, targetUnits=names),
    ]
    mission["outcomes"] = [
        {"Type": "StartObjective", "UniqueName": "Start flight route",
         "objectivesToStart": ["Icarus northbound route", "Shoot down four Icarus targets"]},
        {"Type": "RevealUnit", "UniqueName": "Show gun targets", "UnitsToReveal": names},
    ]
    return mission


def artifacts():
    for name, mission in (("shot_down", shot_down()), ("gun_kills", gun_kills())):
        stem = f"playtest_{name}"
        keys = {ICARUS}
        for unit in mission["aircraft"]:
            if unit["type"] == ICARUS:
                keys.update(s["Key"] for s in unit["savedLoadout"]["Selected"] if s["Key"])
        scenario = {
            "mission": f"{stem}.mission.json", "mods": "mirror",
            "plugins": ["installed:com.nikkorap.blueprinter", "../../.cache/build-staging/dotnet",
                        "content:../../build/icarus_0.0.1.nobp host=com.nikkorap.blueprinter keys=" + ",".join(sorted(keys))],
            "measure": True, "timeout": 18000,
            "steps": [{"record": {"path": "own.alt_msl_m"}, "label": "Record the player's starting altitude"}],
        }
        yield f"Icarus - {name.replace('_', ' ')}", stem, mission, scenario


def verify_contracts():
    shot, gun = shot_down(), gun_kills()
    assert len(shot["aircraft"]) == 7
    assert shot["aircraft"][0]["globalPosition"]["y"] == 9000
    assert shot["aircraft"][0]["savedLoadout"]["Selected"] == [{"Key": k} for k in AIR_TO_AIR]
    assert shot["objectives"][1]["seconds"] == 120
    assert shot["outcomes"][1]["UnitsToSpawn"] == [f"Interceptor {i}" for i in range(3, 7)]
    assert len(gun["aircraft"]) == 5
    assert gun["aircraft"][0]["savedLoadout"]["Selected"] == [{"Key": k} for k in IFRIT_STANDARD]
    targets = gun["aircraft"][1:]
    assert [u["globalPosition"] for u in targets] == [
        {"x": -74000, "y": 8000, "z": z} for z in (-33200, -32200, -31200, -30200)]
    assert all(u["startingSpeed"] == 200 and u["rotation"] == rotation(0) for u in targets)
    assert all(u["savedLoadout"]["Selected"] == [{"Key": ""}, {"Key": "bomb_500_single"}, {"Key": ""}]
               for u in targets)
    assert gun["objectives"][1]["waypoints"] == [
        {"Position": {"x": -74000, "y": 8000, "z": ROUTE_END_Z}, "Range": 1000}]
    for mission in (shot, gun):
        assert sum(u["playerControlled"] for u in mission["aircraft"]) == 1
        assert all(f["AIAircraftLimit"] == 0 and not f["supplies"] for f in mission["factions"])
        units = {u["UniqueName"] for u in mission["aircraft"]}
        objectives = {o["UniqueName"] for o in mission["objectives"]}
        outcomes = {o["UniqueName"] for o in mission["outcomes"]}
        for obj in mission["objectives"]:
            assert set(obj["Outcomes"]) <= outcomes
            assert set(obj.get("targetUnits", [])) <= units
        for outcome in mission["outcomes"]:
            assert set(outcome.get("objectivesToStart", [])) <= objectives
            assert set(outcome.get("UnitsToSpawn", []) + outcome.get("UnitsToReveal", [])) <= units
    print("VERIFIED mission contracts: wave timing, loadouts, altitude policy, spacing and references")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-saved", action="store_true", help="also compare the mission-list files byte for byte")
    args = parser.parse_args()
    verify_contracts()
    saved_root = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow/Shockfront/NuclearOption/Missions"
    for title, stem, mission, scenario in artifacts():
        for suffix, data in (("mission.json", mission), ("scenario.jsonc", scenario)):
            path = HERE / f"{stem}.{suffix}"
            encoded = (json.dumps(data, indent=2) + "\n").encode("utf-8")
            path.write_bytes(encoded)
            print(f"{path}: sha256 {hashlib.sha256(encoded).hexdigest()}")
        if args.verify_saved:
            saved = saved_root / title / f"{title}.json"
            generated = HERE / f"{stem}.mission.json"
            if saved.read_bytes() != generated.read_bytes():
                raise ValueError(f"Saved mission differs from generated data: {saved}")
            print(f"VERIFIED byte-identical: {saved}")


if __name__ == "__main__":
    main()
