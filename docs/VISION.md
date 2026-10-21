# F-204 Icarus II: vision

The F-204 Icarus II is a flyable aircraft mod for [Nuclear Option](https://store.steampowered.com/app/2168680/Nuclear_Option/): the F-104 Starfighter, rebuilt for the game's near future. It keeps the Starfighter's shape and its reason to exist, a manned missile that climbs and runs faster than anything it chases, and gives it newer materials, a modern afterburning turbojet, and the sensors and datalink every aircraft in the game carries.

The game has no Starfighter. This fills that slot.

The mod is also a demonstration of building game content with AI agents. Claude and GPT models do the research, art, code and testing, and a person reviews every iteration. The [devlog](devlog/) shows each step: what changed, why, and what it looked like.

## The aircraft

| | |
|---|---|
| Faction | Primeva (PALA) |
| Role | Interceptor first; light strike as a secondary loadout |
| Gun | None |
| Stations | 6: per side, a wingtip rail, one underwing pylon (a single store, or a twin rack of air-to-air missiles), one conformal fuselage station. Stock game weapons only, and few advanced ones: the AAM-36 long-range missile and the AGM-68 against armour, but no anti-radiation or anti-ship missiles |
| Fidelity | Full: working cockpit with displays, breakable parts, internal structure |

### Performance

The Icarus is a rocket sled. It reaches Mach 2.5 and beyond at altitude, and pays for it: about five minutes of fuel on full afterburner, and an inefficient cruise without it, because it is still a turbojet, only a better one.

Below transonic speed it handles better than the real Starfighter but is still not a dogfighter. A cranked wing and automatic leading-edge flaps keep it controllable and bring the approach down to about 270 km/h at low fuel; it bleeds energy in a sustained turn and wins on speed and climb.

First-cut numbers, predicted offline from a replica of the game's flight model and not yet flown:

| | First cut | Real F-104G |
|---|---|---|
| Empty mass | 5,800 kg | 6,348 kg |
| Internal fuel | 2,400 kg | |
| Core thrust / afterburner | 65 kN / +45 kN | 44 kN / 70 kN total (J79-GE-11A) |
| Wing area | 18.2 m² | 18.2 m² |
| Level top speed | Mach 2.58 at 10 km, Mach 2.83 at 15 km | about Mach 2 |
| Full afterburner endurance | about 300 s | |
| Approach | 76 m/s at 20% fuel | |

The same replica predicts the stock FS-12 Revoker's top speed within 0.2 km/h of the published figure, which is the reason to trust it for a starting point. Every number above is a tuning knob (see [Tuning](#tuning)) and will move in playtest.

### Shape

Largely faithful to the F-104, with changes so it is not a one-to-one copy, each to be judged in live iterations rather than fixed up front:

- a cranked-arrow wing in place of the straight trapezoid
- the strake carried forward to the side of the intake
- a squared-off tail
- leading-edge flaps, in the spirit of the A-19 Brawler's slats
- a waisted fuselage at the wing root. In Nuclear Option this is a look only: drag comes from each part's drag area plus one global bump around Mach 1, with no cross-section term, so area ruling buys nothing in the flight model.

### Cockpit

A custom cockpit: a modernized US-style layout with Primeva components in it, modelled and textured to the level of the stock cockpits (how their buttons, panels and labels are actually built), and driven by the game's own display, HUD and instrument scripts rather than a new UI framework.

## How it is built

- **Exterior art** is a Blender Python generator, written from the first iteration. An AI model runs it inside a live Blender session through Blender MCP, so each change is a parameter edit visible in seconds. Every iteration also reruns on an empty scene, and the mesh that ships always comes from a clean background run, so the approved look can be rebuilt from the repo alone.
- **In game**, Unity editor scripts author the aircraft onto a stock donor prefab, the FS-12 Revoker, and strip what the Icarus does not have: thrust vectoring, canards, the internal cannon and the weapon bays. The build produces a Blueprinter bundle and a BepInEx plugin.
- **Factions and supply**: the plugin adds the Icarus to Primeva's aircraft supply in stock missions and lets factories produce it, behind a setting that is on by default.

### Tuning

One tuning file in `BepInEx/config` holds the flight model and engine values, and the plugin applies it to the jet you are flying when the file is saved. The Configuration Manager menu (F1) exposes the most-used knobs.

What can change in flight follows how the game stores each value:

| Change | Applies |
|---|---|
| Thrust, engine speed limit, altitude curve, fuel burn, afterburner | in flight |
| Wing and drag areas | in flight |
| Control-surface rates, centre of lift, flap areas | in flight, written into the game's physics data |
| Mass and fuel capacity | on respawn |
| Airfoil lift and drag curves | on mission restart |

The Unity build bakes the same file into the aircraft, so shipped values have one source. Once another player is connected, every machine uses the shipped values, so everyone flies the same jet.

## Stages

1. Research (done)
2. Exterior silhouette
3. Rough blockout in game: scale, eye point, gear, camera, the donor strip, and a first flight-model check against the targets above
4. Freeze the wing planform
5. Exterior detail
6. Cockpit
7. Full in-game build, multiplayer on two PCs
8. Flight model
9. Polish
10. Custom audio

Stretch goal: droppable tip tanks on the wingtip stations.
