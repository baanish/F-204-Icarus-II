using System.Collections.Generic;
using HarmonyLib;

namespace Icarus;

/// <summary>
/// The aircraft menu starts the Icarus in its faction's Bare Metal, the main livery on both sides, where the game would
/// pick one at random: with no saved choice, LoadoutSelector.LoadDefaults takes Random.Range(0, liveryOptions.Count). The
/// choice is made before that first load: the prefix saves the customization LoadDefaults would build (loadouts[1] at
/// the default fuel level) with Bare Metal's menu option, so the game loads that livery once through its own saved branch.
/// Setting it after the load would not stick, since LiveryBehaviour.SetKey drops a second key while the first livery is
/// still loading. The entry lasts only that call: stock saves a choice only on the player's first change (SaveDefaults,
/// from a weapon dropdown), never for a preview, so the finalizer takes it out again unless the game replaced it, and a
/// fresh preview picks Bare Metal again. A saved choice is left alone.
/// </summary>
static class BareMetalFirstPick
{
    /// <summary>
    /// The Bare Metal liveries' indices in the aircraft's livery list, PALA's and BDF's (IcarusAuthor.LiverySpecs lists
    /// the liveries by id; A13 checks these two against it).
    /// </summary>
    internal const int PalaBareMetal = 3, BdfBareMetal = 6;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("bare-metal-first-pick", typeof(LoadoutSelector), nameof(LoadoutSelector.LoadDefaults),
            prefix: AccessTools.Method(typeof(BareMetalFirstPick), nameof(BeforeLoadDefaults)),
            finalizer: AccessTools.Method(typeof(BareMetalFirstPick), nameof(AfterLoadDefaults))),
    };

    // LoadoutSelector.AssignAircraft fills liveryOptions (RefreshLiveryOptions) before it calls LoadDefaults, so the menu
    // option is the faction's own list's.
    static void BeforeLoadDefaults(Aircraft ___aircraft, List<(LiveryKey key, string label)> ___liveryOptions,
        out AircraftCustomization? __state)
    {
        __state = null;
        if (IcarusPlugin.FeaturesOff.Contains("bare-metal-first-pick") || ___aircraft == null ||
            ___aircraft.definition.jsonKey != IcarusPlugin.JsonKey ||
            GameManager.aircraftCustomization.ContainsKey(___aircraft.definition)) return;
        int option = ___liveryOptions.FindIndex(o => o.key.Type == LiveryKey.KeyType.Builtin &&
            (o.key.Index == PalaBareMetal || o.key.Index == BdfBareMetal));
        if (option < 0) return;
        var parameters = ___aircraft.definition.aircraftParameters;
        __state = new AircraftCustomization(parameters.loadouts[1], parameters.DefaultFuelLevel, option);
        GameManager.aircraftCustomization.Add(___aircraft.definition, __state);
    }

    // A finalizer, so a throwing LoadDefaults cannot leave the entry saved either.
    static System.Exception? AfterLoadDefaults(Aircraft ___aircraft, AircraftCustomization? __state, System.Exception? __exception)
    {
        if (__state != null && GameManager.aircraftCustomization.TryGetValue(___aircraft.definition, out var saved) && saved == __state)
            GameManager.aircraftCustomization.Remove(___aircraft.definition);
        return __exception;
    }
}
