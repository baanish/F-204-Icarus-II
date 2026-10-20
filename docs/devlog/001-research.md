# 001: Research

Before any art, the plan went through two rounds of stress-testing and ten research questions.

**Interrogating the plan.** The owner was grilled on the plan question by question (role, speed, stations, faction, how art and tuning work), then three reviewers from different model families (Grok, GPT-6.1 Sol, Claude Opus) attacked the settled plan independently. They found no reason to drop it, and ten things to change. The biggest: the first plan assumed every tuning value could be changed live, and two reviewers found on their own that the game copies control rates and airfoil curves into its physics data once, at spawn or at mission load. The tuning design now follows how the game stores each value (see [Tuning](../VISION.md#tuning)). The other large change moved the first flight-model check forward to the rough blockout, before any detail work depends on the wing shape.

**Ten research questions**, run in parallel by GPT-6.1 Sol against the decompiled game, the game's asset data, the wiki and other mods:

| Question | What came back |
|---|---|
| How stock and modded cockpits are built | Stock cockpits are aircraft-specific meshes driven by shared display scripts; the F-99 Shrike mod bundles its own geometry on stock scripts. The Icarus gets a custom cockpit on stock scripts. |
| Drop tanks | Three mods do it, in two ways; none syncs fuel quantity in multiplayer explicitly. Tip tanks became a stretch goal. |
| Factories and faction supply | Missions set each faction's reserves and each factory's product; a plugin can add both on the host after load. |
| Live tuning write paths | Engine values and areas are read live; control rates and centre of lift need writes into the physics data; curves need a mission restart. |
| Stripping the donor | The Revoker's canards provide all its pitch control, so the Icarus needs a real all-moving tail; weapon stations and loadouts must be rebuilt together. |
| Leading-edge flaps | The A-19 Brawler's slats are a stock `HighLiftDevice` that grows wing area and moves the slats directly. |
| Engine sizing | A replica of the game's flight model, checked against the Revoker's published top speed, gives the first-cut numbers in the [vision](../VISION.md#performance). |
| F-104 reference data | Dimensions, wing area, weights, J79 thrust and 20 fuselage stations for the generator. |
| Prior art | The MiG-21K Koshchei mod is the nearest neighbour; the FS-41 Eclipse mod claims Mach 2.85, so the Icarus is not chasing a speed record. |
| What carries over from the MRB-100 Centurion mod | The export pipeline, startup and AI-supply fixes, and the donor-authoring pattern; hot tuning, supply injection and factories are new work. |

Next: the exterior silhouette, iterated live in Blender.
