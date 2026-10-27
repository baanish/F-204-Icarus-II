# F-204 Icarus II: vision

The F-204 Icarus II is a flyable aircraft mod for [Nuclear Option](https://store.steampowered.com/app/2168680/Nuclear_Option/): the F-104 Starfighter, rebuilt for the game's near future. It keeps the Starfighter's shape and its reason to exist, a manned missile that climbs and runs faster than anything it chases, and gives it newer materials, a modern afterburning turbojet with a thrust-vectoring iris nozzle, and the sensors and datalink every aircraft in the game carries.

The game has no Starfighter. This fills that slot.

The mod is also a demonstration of building game content with AI agents. Claude and GPT models do the research, art, code and testing, and a person reviews every iteration. The [devlog](devlog/) shows each step: what changed, why, and what it looked like.

## The aircraft

| | |
|---|---|
| Faction | Primeva (PALA) |
| Role | Interceptor first; light strike as a secondary loadout |
| Gun | None |
| Stations | 6: per side, a droppable Starfighter tip tank (the default) or a wingtip missile rail, one underwing pylon (a single store, or a twin rack of air-to-air missiles), one conformal fuselage station. Stock game weapons only, and few advanced ones: the AAM-36 long-range missile and the AGM-68 against armour, but no anti-radiation or anti-ship missiles |
| Fidelity | Full: working cockpit with displays, breakable parts, internal structure |

### Performance

The Icarus is a rocket sled. It reaches Mach 2.5 and beyond at altitude, and pays for it: a little over six minutes of fuel on full afterburner, and an inefficient cruise without it, because it is still a turbojet, only a better one.

Below transonic speed it handles better than the real Starfighter but is still not a dogfighter. A cranked wing and automatic leading-edge flaps keep it controllable and bring the approach down to about 270 km/h at low fuel; it bleeds energy in a sustained turn and wins on speed and climb.

The first-cut numbers came from a replica of the game's flight model, which predicts the stock FS-12 Revoker's top speed within 0.2 km/h of the published figure. The jet has flown since, and the table now gives the current values. All of them are provisional and will move in playtest.

| | Icarus II, current | Real F-104G |
|---|---|---|
| Length | 16.69 m, the F-104's | 16.69 m |
| Wingspan | about 6.8 m without tip stores | 6.69 m |
| Wing area | 20.8 m² | 18.2 m² |
| Empty mass | 5,800 kg | 6,348 kg |
| Internal fuel | 3,082 kg (design load) | |
| Core thrust / afterburner | 65 kN / +45 kN | 44 kN / 70 kN total (J79-GE-11A) |
| Level top speed | Mach 2.50 at 10 km, Mach 2.78 at 15 km, measured in game | about Mach 2 |
| Full afterburner endurance | about 385 s (6.4 min), estimated | |
| Approach | 75 m/s at 20% fuel, design target | |

The top speeds were measured in game on 22 October 2026, before the tail was reshaped and the fuel grew from 2,320 kg to 3,082 kg. The endurance is an estimate: the full fuel load divided by the engine's full-afterburner burn of about 8 kg a second. It has not been flown at this fuel load.

### Shape

Largely faithful to the F-104, with changes so it is not a one-to-one copy, each judged in live iterations rather than fixed up front:

- a cranked-arrow wing in place of the straight trapezoid
- the strake carried forward to the side of the intake
- the F-104's T-tail, with a squared-off stabilator
- leading-edge flaps, in the spirit of the A-19 Brawler's slats
- a waisted fuselage at the wing root. In Nuclear Option this is a look only: drag comes from each part's drag area plus one global bump around Mach 1, with no cross-section term, so area ruling buys nothing in the flight model.
- an iris nozzle of 16 petals and 16 seals, which opens for afterburner and turns up to 4 degrees in pitch and yaw for thrust vectoring

### Cockpit

A custom cockpit: a modernized US-style layout with Primeva components in it, modelled and textured to the level of the stock cockpits (how their buttons, panels and labels are actually built), and driven by the game's own display, HUD and instrument scripts rather than a new UI framework. The one addition is a small plugin script that turns the standby attitude ball, the fuel gauge needle and the clock hands, which the stock scripts have no driver for.

## How it is built

- **Exterior art** is a Blender Python generator, written from the first iteration. An AI model runs it inside a live Blender session through Blender MCP, so each change is a parameter edit visible in seconds. Every iteration also reruns on an empty scene, and the mesh that ships always comes from a clean background run, so the approved look can be rebuilt from the repo alone.
- **In game**, Unity editor scripts author the aircraft onto a stock donor prefab, the FS-12 Revoker, and strip what the Icarus does not have: canards, the internal cannon and the weapon bays. The Revoker's thrust vectoring stays and drives the iris nozzle. The build produces a Blueprinter bundle and a BepInEx plugin.
- **Factions and supply**: the plugin adds the Icarus to Primeva's aircraft supply in stock missions and lets factories produce it, behind a setting that is on by default.

### Tuning

The plugin's config file, `BepInEx/config/baanish.icarus.cfg`, holds the flight-model scalars the game reads live, in its `[Tuning.*]` sections. Saving the file applies them to every Icarus in flight. Each value is also an ordinary BepInEx setting, so a configuration manager plugin, if you have one installed, can change it in game. A value below 0 means the shipped value.

| Live now | Values |
|---|---|
| Engine | thrust, speed limit, minimum air density, spool rate, idle and full fuel burn, altitude thrust curve |
| Afterburner | thrust, fuel burn |
| Thrust vectoring | pitch and yaw limits, airspeed cutoff |
| Aero | total wing area, total drag area |
| AI | corner, landing and takeoff speeds, turning radius |

The first plan made more of the flight model live: control-surface rates, centre of lift and flap areas in flight, mass and fuel capacity on respawn, and airfoil curves on mission restart. None of that is built. It stays on the list for later.

The Unity build bakes its own values, set in the authoring scripts, into the aircraft. It does not read the tuning file. The file only overrides the baked values at runtime. Once another player is connected, every machine uses the shipped values, so everyone flies the same jet.

## Stages

1. Research (done)
2. Exterior silhouette (done)
3. Rough blockout in game: scale, eye point, gear, camera, the donor strip, and a first flight-model check against the targets above (done)
4. Freeze the wing planform (done)
5. Exterior detail (done)
6. Cockpit (done)
7. Full in-game build (done); multiplayer tested on two PCs (not yet: so far host and client have run only on one PC)
8. Flight model (first in-game tuning done; to fly again after the latest fuel and tail changes)
9. Polish (in progress)
10. Custom audio (done: engine, gear travel and lock, belly scrape)

Droppable tip tanks, 170 US gal each and burned before the internal fuel, hang on the wingtips in place of a missile; the default Interceptor loadout carries them.
