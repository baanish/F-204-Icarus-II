using System.Collections.Generic;
using HarmonyLib;

namespace Icarus;

/// <summary>
/// The aircraft menu's livery list for the Icarus, on both sides. Every Icarus livery is Primeva's, so the game's list for
/// a Boscali Icarus comes back empty, and the menu indexes it regardless (LoadoutSelector.CurrentLivery). At a BDF airbase
/// that threw out of the hangar preview before the game moved the preview's parts onto its no-collision layer, so its
/// nested panels and trays struck each other at up to 120 g and tore off; the same throw stops the Fly button's spawn. An
/// empty list for the Icarus gets every PALA livery. With no saved choice the menu then picks Bare Metal, the main livery
/// (the owner's choice), where the game would pick one at random (LoadoutSelector.LoadDefaults).
/// </summary>
static class LiveryFallback
{
    const string DefaultLivery = "PALA Bare Metal";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("livery-fallback", typeof(LoadoutSelector), nameof(LoadoutSelector.GetLiveryOptions),
            postfix: AccessTools.Method(typeof(LiveryFallback), nameof(AfterGetLiveryOptions))),
        new("livery-fallback", typeof(LoadoutSelector), nameof(LoadoutSelector.LoadDefaults),
            prefix: AccessTools.Method(typeof(LiveryFallback), nameof(BeforeLoadDefaults)),
            postfix: AccessTools.Method(typeof(LiveryFallback), nameof(AfterLoadDefaults))),
    };

    static void AfterGetLiveryOptions(List<(LiveryKey key, string label)> resultsList, AircraftDefinition aircraft)
    {
        if (IcarusPlugin.FeaturesOff.Contains("livery-fallback") || resultsList.Count > 0 ||
            aircraft == null || aircraft.jsonKey != IcarusPlugin.JsonKey) return;
        var liveries = aircraft.aircraftParameters.liveries;
        for (int i = 0; i < liveries.Count; i++)
        {
            resultsList.Add((new LiveryKey(i), liveries[i].name));
        }
    }

    // Whether the player had a saved choice for this aircraft before LoadDefaults ran; only a fresh pick is replaced.
    static void BeforeLoadDefaults(Aircraft ___aircraft, out bool __state) =>
        __state = ___aircraft != null && GameManager.aircraftCustomization.ContainsKey(___aircraft.definition);

    static void AfterLoadDefaults(LoadoutSelector __instance, Aircraft ___aircraft, List<(LiveryKey key, string label)> ___liveryOptions, bool __state)
    {
        if (__state || IcarusPlugin.FeaturesOff.Contains("livery-fallback") || ___aircraft == null ||
            ___aircraft.definition.jsonKey != IcarusPlugin.JsonKey) return;
        int index = ___liveryOptions.FindIndex(o => o.label == DefaultLivery);
        if (index < 0) return;
        // The dropdown is a TextMeshPro type this plugin doesn't reference, so it is set through Harmony's Traverse.
        Traverse.Create(__instance).Field("liveryDropdown").Method("SetValueWithoutNotify", index).GetValue();
        ___aircraft.SetLiveryKey(___liveryOptions[index].key, loadIfUnspawned: true);
    }
}
