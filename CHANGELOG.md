# Changelog

## 0.2.0 (unreleased)

- The Icarus no longer falls apart in a Boscali hangar's aircraft preview, and Boscali players can fly it from the aircraft menu. With no Boscali livery, the menu failed before it set the preview up; Boscali players now get all four PALA liveries there.
- The aircraft menu picks the Bare Metal livery for the Icarus by default, on both sides, instead of a random one.
- The Icarus unlocks at rank 2, beside the Brawler, instead of rank 3.
- The fuselage breaks up in finer pieces: the side panels part at the lower lap joint and at the mid frame, the dorsal cover splits in two, and the frame and stringer truss over the top comes away in two halves, showing the tanks under it. Like the wing and tail, the panels show no seam while attached.
- The tail breaks up in more pieces: the tail cone with the speed brakes can come off behind the engine, and the afterburner section separates from the engine. Braces keep the tail stiff in hard pulls, and no seam opens while the pieces are attached.
- Each wing breaks up in more pieces: the outer wing can come off at the crank, taking its share of the lift with it, and the wing skin is four panels a side instead of one. The joint at the crank never shows in hard pulls.
- The skin tears like a stock jet's: panel joints and rivet rows stay standing while damage opens the skin bay by bay with torn edges. It used to lose about half its skin in round holes by 80% health, starting with the clean metal.
- The skin is drawn from both sides, as on most stock jets: a damage hole or a broken section shows the inside of the skin instead of the sky through the far wall.
- The wing's ribs and fuel tanks no longer show through the top of the wing in hard pulls. A wing skin that tears off still falls away on its own.
- The leading-edge flaps also droop with angle of attack, as the Brawler's slats do: from 10 degrees, fully down by 20, on top of the low-speed droop.
- The wing pylons carry the GPO-N nuclear bomb, at tactical (1.5 kt) or strategic (250 kt) yield, one per pylon.
- Tip tanks have their own line art in the weapon panel and loadout menu, and selecting them no longer brings up the bombing sight.
- The tip tanks hang from the Wingtip station beside the MMR-S3 and IRM-S2, so the loadout menu has one wingtip slot instead of two, and they release outboard from either tip. Mission files that still list a fourth Icarus loadout entry lose their tip tanks.
- Dropping the tip tanks once they are nearly empty no longer tears the jet apart.
- New setting, off by default: Fun > HelipadSpawn lets players spawn the Icarus on helipads, standing on its tail with the gear up, and full afterburner launches it straight up. It is for the memes and not balanced. The AI never spawns there.

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
