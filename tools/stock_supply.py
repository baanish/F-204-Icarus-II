"""Check the plugin's stock-mission factory table against the stock missions.

python -I tools/stock_supply.py

src/Icarus/StockMissionSupply.cs names, per built-in mission, the Primeva factory whose Revoker production becomes the
Icarus's. The plugin matches the factory by UniqueName and its stock production type, so a wrong name does nothing in
game. This reads the table and the missions in tools/local-paths.json's game export (Resources/missions) and checks each
entry names one building there, of the plugin's faction, building the plugin's Revoker key. It prints each mission's
Revoker supply before and after, and any mission with a Primeva Revoker factory the table leaves out. The last line is
"STOCK SUPPLY PASS" or "STOCK SUPPLY FAIL: ...", and a FAIL exits 1.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stores import paths  # noqa: E402

SOURCE = paths.REPO / "src" / "Icarus" / "StockMissionSupply.cs"


def const(text, name):
    match = re.search(rf'const (?:string|int) {name} = "?([^";]+)"?;', text)
    if not match:
        raise SystemExit(f"{SOURCE}: no const {name}")
    return match[1]


def main():
    text = SOURCE.read_text(encoding="utf-8")
    faction, revoker, reserve = const(text, "Faction"), const(text, "Revoker"), const(text, "StartingReserve")
    table = dict(re.findall(r'\["([^"]+)"\] = "([^"]+)"', text))
    if not table:
        raise SystemExit(f"{SOURCE}: no Factories entries")
    covered = len(table)
    missions = paths.load()["game_export"] / "Resources" / "missions"
    problems = []
    for path in sorted(missions.glob("*.json")):
        mission = json.loads(path.read_text(encoding="utf-8-sig"))
        factories = [b for b in mission.get("buildings", []) if b.get("faction") == faction
                     and (b.get("factoryOptions") or {}).get("productionType") == revoker]
        supplies = [f for f in mission.get("factions", []) if f.get("factionName") == faction]
        start = sum(s["Count"] for f in supplies for s in f.get("supplies", []) if s["UnitType"] == revoker)
        target = table.pop(path.stem, None)
        if target is None:
            if factories:
                print(f"not covered: {path.stem}, {faction} {revoker} factories {[b['UniqueName'] for b in factories]}")
            continue
        named = [b for b in mission.get("buildings", []) if b.get("UniqueName") == target]
        if len(named) != 1:
            problems.append(f"{path.stem}: {len(named)} buildings named {target}")
            continue
        building = named[0]
        options = building.get("factoryOptions") or {}
        if building.get("faction") != faction or options.get("productionType") != revoker or not options.get("productionTime", 0) > 0:
            problems.append(f"{path.stem}: {target} is {building.get('faction')} building {options.get('productionType')} "
                            f"every {options.get('productionTime')} s, not {faction} building {revoker}")
            continue
        others = [b["UniqueName"] for b in factories if b["UniqueName"] != target]
        print(f"{path.stem}: {target} builds the Icarus every {options['productionTime']:.0f} s; {faction} starts with "
              f"{reserve} Icarus and {start} {revoker}; {revoker} factories left {others}")
    problems += [f"{name}: no {name}.json in {missions}" for name in sorted(table)]
    if problems:
        print("STOCK SUPPLY FAIL: " + "; ".join(problems))
        sys.exit(1)
    print(f"STOCK SUPPLY PASS: {covered} missions")


if __name__ == "__main__":
    main()
