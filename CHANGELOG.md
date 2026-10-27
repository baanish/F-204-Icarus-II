# Changelog

## 0.0.1 (unreleased)

The first version of the F-204 Icarus II, a Primeva interceptor based on the F-104 Starfighter.

- A flyable jet with a first-pass damage model: breakable parts and internal structure; a missile hit tears off wings, the engine and tail surfaces.
- A custom cockpit on the game's own displays and HUD, with a live standby attitude ball, fuel gauge and clock.
- Six stations: wingtip rails, one underwing pylon a side (single store or twin air-to-air rack), and semi-recessed conformal belly stations whose missiles drop clear before their motors light. Four standard loadouts: Interceptor, Air Superiority, Strike and Close Support. No gun.
- Droppable Starfighter tip tanks, 170 US gal each, on the default Interceptor loadout: burned before the internal fuel, dropped as a pair.
- A modern afterburning turbojet: Mach 2.50 at 10 km and Mach 2.78 at 15 km measured in game, with an iris nozzle that opens with afterburner and vectors thrust up to 4 degrees.
- Automatic leading-edge and trailing-edge flaps, speed brakes, and F-104-style landing gear with doors.
- Four PALA liveries: Navy, Black, Desert splinter, and Bare Metal with its own metallic finish.
- Its own engine, gear and belly-scrape sounds.
- Its own map and plane select icon.
- In the stock operations Breakout, Confrontation, Domination, Escalation and Terminal Control (and their co-op versions), Primeva's AI fields the Icarus and one factory per mission builds it, behind the `[Missions] StockMissionSupply` setting, on by default.
- Live tuning of the engine, afterburner, thrust vectoring, wing and drag area and AI speeds from `BepInEx/config/baanish.icarus.cfg`, locked to the shipped values while another player is connected.
