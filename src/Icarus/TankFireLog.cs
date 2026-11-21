using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Stage lines for fuel tank fires on every aircraft, stock ones included, so an Icarus fire can be read against a
/// stock jet's in the same mission: each tank that lights, with the sphere its fire damages once a second
/// (FuelTank.FuelTankFire: the part's GetAverageRadius times 1.5 about the tank) and the parts with colliders inside it.
/// </summary>
static class TankFireLog
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("tank-fire-log", typeof(FuelTank), nameof(FuelTank.UpdateStatus),
            prefix: AccessTools.Method(typeof(TankFireLog), nameof(BeforeUpdateStatus)), diagnostic: true),
    };

    // Resolved on the diagnostic's first run, not with PatchTargets: the plugin reads PatchTargets at startup, so a
    // field a game update renames would otherwise fail the type's initializer and stop the whole plugin loading.
    static AccessTools.FieldRef<FuelTank, bool>? lit;
    static AccessTools.FieldRef<FuelTank, UnitPart>? tankPart;

    static void BeforeUpdateStatus(FuelTank __instance, bool onFire)
    {
        if (!IcarusPlugin.Log.StageEnabled || !onFire || IcarusPlugin.FeaturesOff.Contains("tank-fire-log")) return;
        lit ??= AccessTools.FieldRefAccess<FuelTank, bool>("onFire");
        tankPart ??= AccessTools.FieldRefAccess<FuelTank, UnitPart>("part");
        if (lit(__instance)) return;
        UnitPart part = tankPart(__instance);
        float radius = part.GetAverageRadius() * 1.5f;
        var inside = Physics.OverlapSphere(__instance.transform.position, radius)
            .Select(c => c.GetComponent<UnitPart>()).Where(p => p != null && p.parentUnit == part.parentUnit)
            .GroupBy(p => p.name).Select(g => g.Key + (g.Count() > 1 ? " x" + g.Count() : "")).OrderBy(n => n);
        IcarusPlugin.Log.Stage($"tank-fire {part.parentUnit.UniqueName} {part.name}",
            $"{(part.parentUnit is Aircraft a && a.definition != null ? a.definition.jsonKey : "?")} tank lit, {__instance.fuelMass:0} kg; spread radius {radius:0.00} m " +
            $"about {part.xform.InverseTransformPoint(__instance.transform.position):F2}, own parts inside: {string.Join(", ", inside)}", everyOccurrence: true);
    }
}
