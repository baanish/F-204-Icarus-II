"""Writes the Icarus's test missions into tests/scenarios/ from NO-Agentic-Framework's templates, never by hand:
the player's Icarus parked on Sandrift Airbase's runway, airborne near Sandrift at 3 km, airborne over Ignus at 10 and
15 km with about 160 km of map ahead, a loopback group mission with two Icarus slots, and a Hyperion carrier at sea for
the game's AI to fly from and the player to land on. Every Icarus flies clean but the carrier landing's, which carries
its arrestor hook.
  python tests/scenarios/make_missions.py
"""
import copy
import json
import math
import os
import pathlib

here = pathlib.Path(__file__).resolve().parent
config_path = here.parents[1] / 'tools/local-paths.json'
config = json.loads(config_path.read_text()) if config_path.is_file() else {}
templates = os.environ.get('ICARUS_MISSION_TEMPLATES') or config.get('mission_templates')
if not templates:
    raise ValueError('Set ICARUS_MISSION_TEMPLATES or mission_templates in tools/local-paths.json to the framework templates folder')
TEMPLATES = pathlib.Path(templates)
if not TEMPLATES.is_absolute():
    TEMPLATES = here.parents[1] / TEMPLATES
if not TEMPLATES.is_dir():
    raise ValueError('The configured mission templates folder does not exist')

AIRCRAFT, TITLE = "baanish_icarus", "F-204 Icarus II"
# The Icarus's AircraftDefinition, as the build's rest-pose report logs it: spawnOffset (0, 1.49, -0.62), restRotation.x
# -0.21 (nose up). Four hardpoint sets (Wingtip, Inner Wing, Conformal, Tail Hook); four empty keys fly it clean, and a
# list of any other length silently loads the default loadout (WeaponManager.InitializeWeaponManager).
SPAWN_UP, REST_PITCH = 1.49, -0.21
CLEAN = {"Selected": [{"Key": ""} for _ in range(4)]}
HOOK = "baanish_icarus_tail_hook"  # the Tail Hook set's one mount (IcarusAuthor.TailHook.cs)

# Sandrift's runway surface under runway_start's spot (x 27877, z -19300) is 136.93 m, as the framework's make_missions.py
# measured it; the origin starts spawnOffset.y plus 0.12 m above it, as runway_start does for the KR-67.
SANDRIFT_SURFACE = 136.93
# Ignus is x -81,920 to 81,920 and z -40,960 to 40,960 (MapSize 163,840 x 81,920, read by the Centurion's map diagnostic).
# Starting 3.9 km in from the west edge, heading east, leaves about 160 km ahead; z -25,000 leaves 66 km north for a turn.
IGNUS = {"Type": "GameWorldPrefab", "Path": "Terrain_naval"}
IGNUS_X, IGNUS_Z = -78000.0, -25000.0


def rotation(yaw_deg, pitch_deg):
    """Unity quaternion for yaw about +y, then pitch about the local x axis (negative x is nose up)."""
    cy, sy = math.cos(math.radians(yaw_deg) / 2), math.sin(math.radians(yaw_deg) / 2)
    cp, sp = math.cos(math.radians(pitch_deg) / 2), math.sin(math.radians(pitch_deg) / 2)
    return {"x": round(cy * sp, 6), "y": round(sy * cp, 6), "z": round(-sy * sp, 6), "w": round(cy * cp, 6)}


def icarus(slot, fuel, position=None, rot=None, speed=None):
    slot.update(type=AIRCRAFT, savedLoadout=copy.deepcopy(CLEAN), fuel=fuel)
    if position:
        slot["globalPosition"] = position
    if rot:
        slot["rotation"] = rot
    if speed is not None:
        slot["startingSpeed"] = speed


def save(m, name, description):
    m["missionSettings"]["description"] = f"{TITLE} test mission: {description}"
    (here / f"{name}.mission.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    print(f"{name}.mission.json: {description}")


def template(name):
    return json.loads((TEMPLATES / f"{name}.mission.json").read_text(encoding="utf-8"))


m = template("runway_start")
icarus(m["aircraft"][0], 1.0, {"x": 27877.0, "y": round(SANDRIFT_SURFACE + SPAWN_UP + 0.12, 2), "z": -19300.0}, rotation(0, REST_PITCH), 0.0)
save(m, "icarus_runway", "the player's Icarus for Primeva parked on Sandrift Airbase's runway (Heartland) facing north, at rest, "
     "full fuel, clean, for fly mode=takeoff; no opponent.")

# Sandrift's runway Start is (27839, -19545), heading 4.3 (the framework's runway read, as its sortie example lands there).
# 19 km out on its extended centreline at 1,200 m is the framework landing example's straight-in hand-over. 23% fuel leaves
# about 20% on final after the roughly 100 s inbound at low throttle (offline fuel model: core fuel 0.45 to 2.5 kg per check).
hdg = math.radians(4.3)
m = template("airborne")
icarus(m["aircraft"][0], 0.23, {"x": round(27839 - math.sin(hdg) * 19000, 1), "y": 1200.0, "z": round(-19545 - math.cos(hdg) * 19000, 1)},
       rotation(4.3, 0), 150.0)
save(m, "icarus_sandrift_final_19km", "the player's Icarus for Primeva at 1,200 m MSL, 150 m/s, 19 km out on Sandrift Airbase's runway "
     "centreline (Heartland), heading 004, 23% fuel, clean, for a straight-in fly mode=land; no opponent.")

for name, alt, speed, fuel, what in [
    ("icarus_ignus_10km", 10000.0, 650.0, 1.0, "full fuel, for the 10 km top speed and full-afterburner endurance"),
    ("icarus_ignus_15km", 15000.0, 700.0, 1.0, "full fuel, for the 15 km top speed"),
    ("icarus_ignus_60kft", 18288.0, 700.0, 1.0, "full fuel, for the 60,000 ft top speed"),
    ("icarus_ignus_3km_fast", 3000.0, 480.0, 0.6, "60% fuel, for low-altitude supersonic handling"),
    ("icarus_ignus_1km_fast", 1000.0, 410.0, 0.5, "half fuel, for full-stick pulls and rolls near Mach 1.2 low down"),
    ("icarus_ignus_10km_half", 10000.0, 400.0, 0.5, "half fuel, for the sustained turn"),
    ("icarus_ignus_13km_40", 13000.0, 520.0, 0.4, "40% fuel, for hands-off pitch hold below half fuel"),
    ("icarus_ignus_3km_300", 3000.0, 300.0, 0.5, "half fuel, for the full-aileron roll rate at 300 m/s"),
    ("icarus_ignus_3km_250", 3000.0, 250.0, 0.5, "half fuel, for the speed brakes opening and closing at 250 m/s"),
]:
    m = template("airborne")
    m["MapKey"] = IGNUS
    icarus(m["aircraft"][0], fuel, {"x": IGNUS_X, "y": alt, "z": IGNUS_Z}, rotation(90, 0), speed)
    save(m, name, f"the player's Icarus for Primeva airborne over Ignus at {alt:,.0f} m MSL (x {IGNUS_X:.0f}, z {IGNUS_Z:.0f}), heading 090, "
         f"{speed:.0f} m/s, with about 160 km of map ahead; {what}; clean; no opponent.")

# Full-stick loads with a full tip tank on each wingtip (the Wingtip set's baanish_icarus_tip_tank mount) and full fuel:
# 570 kg on each outer wing box, the heaviest the crank between the boxes carries.
m = template("airborne")
m["MapKey"] = IGNUS
icarus(m["aircraft"][0], 1.0, {"x": IGNUS_X, "y": 1000.0, "z": IGNUS_Z}, rotation(90, 0), 410.0)
m["aircraft"][0]["savedLoadout"]["Selected"][0]["Key"] = "baanish_icarus_tip_tank"
save(m, "icarus_ignus_1km_fast_tanks", f"the player's Icarus for Primeva airborne over Ignus at 1,000 m MSL (x {IGNUS_X:.0f}, z {IGNUS_Z:.0f}), "
     "heading 090, 410 m/s, full fuel and a full tip tank on each wingtip, for full-stick pulls with the heaviest outer wings; no opponent.")

# Full tip tanks at 3,000 m, 2 km short of the world origin heading east at 300 m/s: a hard turn there stays within a
# few km of the origin, where float32 world positions resolve to a fraction of a millimetre, so the drawn wing's seams can
# be read near their true size (at the other missions' 77 km out positions round to 7.8 mm).
m = template("airborne")
m["MapKey"] = IGNUS
icarus(m["aircraft"][0], 1.0, {"x": -2000.0, "y": 3000.0, "z": 0.0}, rotation(90, 0), 300.0)
m["aircraft"][0]["savedLoadout"]["Selected"][0]["Key"] = "baanish_icarus_tip_tank"
save(m, "icarus_ignus_origin_tanks", "the player's Icarus for Primeva over Ignus at 3,000 m MSL, 2 km west of the world origin, heading 090, 300 m/s, "
     "full fuel and a full tip tank on each wingtip, for drawn seams read where float32 positions are finest; no opponent.")

# Eight Icarus inside the 10 km a jet keeps its per-part bodies from the camera (Aircraft.CheckPhysicsLod), for frame time
# with a full flight: the player's and seven AI wingmen 400 m apart in a line abreast to the north.
m = template("airborne")
m["MapKey"] = IGNUS
icarus(m["aircraft"][0], 0.5, {"x": IGNUS_X, "y": 10000.0, "z": IGNUS_Z}, rotation(90, 0), 400.0)
for k in range(1, 8):
    wing = copy.deepcopy(m["aircraft"][0])
    wing.update(UniqueName=f"Icarus_Wing{k}", playerControlled=False, playerControlledPriority=-1)
    wing["globalPosition"] = {"x": IGNUS_X, "y": 10000.0, "z": IGNUS_Z + 400.0 * k}
    m["aircraft"].append(wing)
save(m, "icarus_ignus_10km_eight", f"the player's Icarus and seven AI Icarus for Primeva over Ignus at 10,000 m MSL, 400 m apart in a "
     f"line abreast to the north of x {IGNUS_X:.0f}, z {IGNUS_Z:.0f}, heading 090 at 400 m/s, half fuel, clean, for frame time with "
     "eight Icarus near the camera; no opponent.")

m = template("group_airborne")
m["aircraft"] = m["aircraft"][:2]
for slot in m["aircraft"]:
    icarus(slot, 0.5)
save(m, "icarus_group", "two player slots, an Icarus each for Primeva at 3,000 m MSL heading north at 220 m/s, 1 km apart, "
     "7 km south of Sandrift Airbase (Heartland), half fuel, clean, for a loopback host and client; no opponent.")

# The Hyperion, Primeva's, where the game's own Carrier Duel puts it on Ignus (FleetCarrier1, heading about 092, open
# sea), holding still: no waypoints. Primeva's supply holds Icarus airframes for a player who joins on the carrier.
CARRIER = {"type": "FleetCarrier1", "faction": "Primeva", "globalPosition": {"x": -44692.49, "y": 5.63970947, "z": -36468.8672},
           "rotation": {"x": 0.0, "y": 0.719034255, "z": 0.0, "w": 0.6949746}, "CaptureStrength": {"IsOverride": False, "Value": 100.0},
           "CaptureDefense": {"IsOverride": False, "Value": 0.0}, "UniqueName": "Hyperion", "holdPosition": True, "skill": 0.7,
           "waypoints": []}


def carrier_mission(template_name):
    m = template(template_name)
    m["MapKey"] = IGNUS
    m["ships"] = [copy.deepcopy(CARRIER)]
    for faction in m["factions"]:
        if faction["factionName"] == "Primeva":
            faction["supplies"] = [s for s in faction.get("supplies", []) if s["UnitType"] != AIRCRAFT] + [{"UnitType": AIRCRAFT, "Count": 4}]
    return m


# Astern of the Hyperion on its heading, 15 km out at 1,200 m and 150 m/s with the hook and 20% fuel, the landing
# AI's 75 m/s approach weight (IcarusAuthor.Identity.cs LowFuelLandingMass), for fly mode=land onto its deck.
CARRIER_HDG = 2 * math.degrees(math.atan2(CARRIER["rotation"]["y"], CARRIER["rotation"]["w"]))
m = carrier_mission("airborne")
back = 15000.0
c = CARRIER["globalPosition"]
icarus(m["aircraft"][0], 0.2, {"x": round(c["x"] - math.sin(math.radians(CARRIER_HDG)) * back, 1), "y": 1200.0,
                               "z": round(c["z"] - math.cos(math.radians(CARRIER_HDG)) * back, 1)}, rotation(CARRIER_HDG, 0), 150.0)
m["aircraft"][0]["savedLoadout"]["Selected"][3]["Key"] = HOOK
save(m, "icarus_hyperion_final", f"the player's Icarus for Primeva 15 km astern of the Hyperion carrier (Ignus) at 1,200 m MSL, 150 m/s, "
     f"heading {CARRIER_HDG:03.0f} as the carrier, 20% fuel, clean but for its arrestor hook, for fly mode=land onto the deck; no opponent.")

# The game's own AI on the Hyperion: Primeva holds only Icarus airframes and no airbase but the carrier (Ignus's fields
# held by nobody and disabled, as the game's Carrier Duel holds them), with room for one AI aircraft, so the faction AI
# spawns an Icarus in one of the carrier's hangars with a standard loadout (every one carries the hook), launches it
# over the ski jump and, finding nothing to fight, brings it home to the deck. Boscali flies nothing. A run needs a
# player: the player's Icarus holds 30 km north at 6,000 m, out of the AI's count (reduceAIPerFriendlyPlayer 0).
# Ignus's fields as Carrier Duel lists them: (name, centre, selection point, capture range).
DUEL_AIRBASES = [
    ("City Airport", (2206.0, 8.08, 4153.0), (1847.0, 8.975, 3635.0), 2100.0),
    ("SE Airbase", (74648.0, 0.0, -28520.0), (73798.7, 13.29, -30105.7), 2600.0),
    ("NW Airbase", (-75861.8359, 13.6, 33605.4922), (-76375.8359, 10.97, 33652.69), 2283.0),
    ("Island7 Airstrip", (-37929.875, 14.6, 11240.9443), (-38201.08, 14.6, 11257.0439), 713.0),
    ("Island9 Airstrip", (-13454.6, 11.0, 30503.2), (-13327.36, 11.038, 31289.8), 1100.0),
    ("Island14 Airstrip", (55365.0, 10.0, -27038.0), (55121.8, 9.84, -27373.5), 1032.0),
    ("SW Airbase", (-74591.8, 12.5, -28639.36), (-75528.51, 9.38, -28557.09), 1394.0),
    ("NE Airbase", (69687.6, 11.58, 26056.8), (70792.99, 7.72999954, 26749.83), 1592.0),
    ("Island5 Airstrip", (42140.1, 9.64, -213.2), (42324.8, 6.65000057, 95.2), 879.0),
]
xyz = lambda v: dict(zip("xyz", v))
m = carrier_mission("airborne")
c = CARRIER["globalPosition"]
icarus(m["aircraft"][0], 1.0, {"x": c["x"], "y": 6000.0, "z": c["z"] + 30000.0}, rotation(CARRIER_HDG, 0), 250.0)
m["airbases"] = [{"IsOverride": True, "faction": "None", "UniqueName": n, "DisplayName": n, "Disabled": True, "Capturable": False,
                  "CaptureDefense": 10.0, "CaptureRange": r, "Center": xyz(c), "SelectionPosition": xyz(sel), "Tower": "",
                  "VerticalLandingPoints": [], "ServicePoints": [], "roads": {"roads": []}, "runways": []}
                 for n, c, sel, r in DUEL_AIRBASES]
for faction in m["factions"]:
    primeva = faction["factionName"] == "Primeva"
    faction["supplies"] = [{"UnitType": AIRCRAFT, "Count": 4}] if primeva else []
    faction["AIAircraftLimit"] = 1 if primeva else 0
    faction["reduceAIPerFriendlyPlayer"] = 0
save(m, "icarus_hyperion_ai", "the player's Icarus 30 km north of the Hyperion at 6,000 m, out of the AI's count; Primeva's only airbase the Hyperion carrier (Ignus, at rest where the game's Carrier Duel "
     "puts it) and its only supply four Icarus, room for one AI aircraft, for the game's AI to spawn, launch and recover an Icarus there; "
     "Boscali flies nothing.")
