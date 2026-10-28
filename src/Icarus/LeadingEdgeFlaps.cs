using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The Icarus's leading-edge flaps also droop with angle of attack: from 10 degrees, fully down by 20, on top of the
/// stock speed schedule (IcarusAuthor.Aero.cs), since the jet holds 20 degrees happily (the owner's range). The game's
/// own AoA term (HighLiftDevice.FixedUpdate) ramps over a single degree past alphaMin, as the Brawler's slats do at 12, so
/// before each step this sets alphaMin one degree under the current AoA and alphaFactor to the wanted share: the stock
/// code then adds exactly that share, and moves, animates and adds area as it does for any slat. The share stops where
/// the speed schedule plus AoA reach full droop, so the device never runs past fully deployed and lags coming back.
/// </summary>
static class LeadingEdgeFlaps
{
    const string Feature = "lef-aoa";
    const float AlphaStartDeg = 10f, AlphaFullDeg = 20f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(HighLiftDevice), "FixedUpdate",
            prefix: AccessTools.Method(typeof(LeadingEdgeFlaps), nameof(BeforeFixedUpdate))),
    };

    static readonly AccessTools.FieldRef<HighLiftDevice, Aircraft> AircraftOf = AccessTools.FieldRefAccess<HighLiftDevice, Aircraft>("aircraft");
    static readonly AccessTools.FieldRef<HighLiftDevice, float> SpeedDeployed = AccessTools.FieldRefAccess<HighLiftDevice, float>("speedDeployed");
    static readonly AccessTools.FieldRef<HighLiftDevice, float> SpeedRetracted = AccessTools.FieldRefAccess<HighLiftDevice, float>("speedRetracted");
    static readonly AccessTools.FieldRef<HighLiftDevice, float> AlphaMin = AccessTools.FieldRefAccess<HighLiftDevice, float>("alphaMin");
    static readonly AccessTools.FieldRef<HighLiftDevice, float> AlphaFactor = AccessTools.FieldRefAccess<HighLiftDevice, float>("alphaFactor");

    static void BeforeFixedUpdate(HighLiftDevice __instance)
    {
        Aircraft aircraft = AircraftOf(__instance);
        // IcarusAuthor.Aero.cs names them lef_L and lef_R.
        if (aircraft == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey || !__instance.name.StartsWith("lef_")) return;
        // The same speed share and AoA as the stock FixedUpdate.
        float bySpeed = Mathf.Clamp01(1f - Mathf.Max(aircraft.speed - SpeedDeployed(__instance), 0f) / (SpeedRetracted(__instance) - SpeedDeployed(__instance)));
        Vector3 velocity = __instance.transform.InverseTransformDirection(aircraft.rb.velocity);
        float alpha = Mathf.Abs(Mathf.Atan2(velocity.y, velocity.z) * Mathf.Rad2Deg);
        AlphaMin(__instance) = alpha - 1f;
        AlphaFactor(__instance) = Mathf.Min(Mathf.InverseLerp(AlphaStartDeg, AlphaFullDeg, alpha), 1f - bySpeed);
        IcarusPlugin.Log.Stage("lef-aoa", $"{__instance.name}: AoA {alpha:0.0} deg, {aircraft.speed:0} m/s, droop share by speed {bySpeed:0.00} plus by AoA {AlphaFactor(__instance):0.00}");
    }
}
