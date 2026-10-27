using System.Collections.Generic;
using HarmonyLib;

namespace Icarus;

/// <summary>
/// Every Icarus livery is Primeva's, so the game's livery list for a Boscali Icarus comes back empty, and the aircraft menu
/// indexes it regardless (LoadoutSelector.CurrentLivery). At a BDF airbase that threw out of the hangar preview before the
/// game moved the preview's parts onto its no-collision layer, so its nested panels and trays struck each other at up to
/// 120 g and tore off; the same throw stops the Fly button's spawn. An empty list for the Icarus gets its first livery,
/// the one a Boscali Icarus from a mission or the AI already wears. Primeva's own list is untouched.
/// </summary>
static class LiveryFallback
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("livery-fallback", typeof(LoadoutSelector), nameof(LoadoutSelector.GetLiveryOptions),
            postfix: AccessTools.Method(typeof(LiveryFallback), nameof(AfterGetLiveryOptions))),
    };

    static void AfterGetLiveryOptions(List<(LiveryKey key, string label)> resultsList, AircraftDefinition aircraft)
    {
        if (IcarusPlugin.FeaturesOff.Contains("livery-fallback") || resultsList.Count > 0 ||
            aircraft == null || aircraft.jsonKey != IcarusPlugin.JsonKey || aircraft.aircraftParameters.liveries.Count == 0) return;
        resultsList.Add((new LiveryKey(0), aircraft.aircraftParameters.liveries[0].name));
    }
}
