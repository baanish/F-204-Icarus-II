# Changelog

## 0.1.1 (unreleased)

- The Icarus no longer falls apart in a Boscali hangar's aircraft preview, and Boscali players can fly it from the aircraft menu. With no Boscali livery, the menu failed before it set the preview up; Boscali players now get all four PALA liveries there.
- The aircraft menu picks the Bare Metal livery for the Icarus by default, on both sides, instead of a random one.

## 0.1.0 (2026-10-27)

The first version of the F-204 Icarus II, a Primeva interceptor based on the F-104 Starfighter.

- A flyable jet with a first-pass damage model, with breakable parts and internal structure. A missile hit tears off wings, the engine and tail surfaces.
- A custom cockpit on the game's own displays and HUD, with a live standby attitude ball, fuel gauge and clock.
- Six stations: wingtip rails, one underwing pylon a side (single store or twin air-to-air rack), and semi-recessed conformal belly stations whose missiles drop clear before their motors light. Four standard loadouts: Interceptor, Air Superiority, Strike and Close Support. No gun.
- Droppable Starfighter tip tanks, 170 US gal each, on the default Interceptor loadout. They burn before the internal fuel and drop as a pair.
- A modern afterburning turbojet: Mach 2.50 at 10 km and Mach 2.78 at 15 km measured in game before the latest tail and fuel changes, with an iris nozzle that opens with afterburner and vectors thrust up to 4 degrees.
- Automatic leading-edge and trailing-edge flaps, speed brakes, and F-104-style landing gear with doors.
- Four PALA liveries: Navy, Black, Desert splinter, and Bare Metal with its own metallic finish.
- Its own engine, gear and belly-scrape sounds.
- Its own map and plane select icon.
- In the stock operations Breakout, Confrontation, Domination, Escalation and Terminal Control (and their co-op versions), Primeva's AI fields the Icarus and one factory per mission builds it, behind the `[Missions] StockMissionSupply` setting, on by default.
- Live tuning of the engine, afterburner, thrust vectoring, wing and drag area and AI speeds from `BepInEx/config/baanish.icarus.cfg`, locked to the shipped values while another player is connected.
