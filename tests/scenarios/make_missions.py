"""Writes the Icarus's test missions into tests/scenarios/ from NO-Agentic-Framework's templates, never by hand:
the player's Icarus parked on Sandrift Airbase's runway, airborne near Sandrift at 3 km, airborne over Ignus at 10 and
15 km with about 160 km of map ahead, and a loopback group mission with two Icarus slots. Every Icarus flies clean.
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
# -0.21 (nose up). Three hardpoint sets (Wingtip, Inner Wing, Conformal); three empty keys fly it clean, and a list of
# any other length silently loads the default loadout (WeaponManager.InitializeWeaponManager).
SPAWN_UP, REST_PITCH = 1.49, -0.21
CLEAN = {"Selected": [{"Key": ""} for _ in range(3)]}

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
# about 20% on final after the roughly 100 s inbound at low throttle (core fuel 0.45 to 2.5 kg per check, R14).
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
]:
    m = template("airborne")
    m["MapKey"] = IGNUS
    icarus(m["aircraft"][0], fuel, {"x": IGNUS_X, "y": alt, "z": IGNUS_Z}, rotation(90, 0), speed)
    save(m, name, f"the player's Icarus for Primeva airborne over Ignus at {alt:,.0f} m MSL (x {IGNUS_X:.0f}, z {IGNUS_Z:.0f}), heading 090, "
         f"{speed:.0f} m/s, with about 160 km of map ahead; {what}; clean; no opponent.")

m = template("group_airborne")
m["aircraft"] = m["aircraft"][:2]
for slot in m["aircraft"]:
    icarus(slot, 0.5)
save(m, "icarus_group", "two player slots, an Icarus each for Primeva at 3,000 m MSL heading north at 220 m/s, 1 km apart, "
     "7 km south of Sandrift Airbase (Heartland), half fuel, clean, for a loopback host and client; no opponent.")

# South Boscali General Aviation (Primeva here) has revetments, a medium hangar and two helipads; the Icarus is offered only at its
# helipads, so two peers joining there each take one. With no player slots the peers join at the airbase as a player does from the map.
m = template("group_airborne")
m["aircraft"] = []
save(m, "icarus_helipad", "no player slots, for peers that join at South Boscali General Aviation (Heartland, Primeva), whose two "
     "helipads are the only hangars that take an Icarus; no opponent.")
