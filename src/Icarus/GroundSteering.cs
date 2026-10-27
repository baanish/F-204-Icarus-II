using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The airborne yaw damper also reaches LandingGear through the aircraft's shared ControlInputs. On the Icarus this
/// closes an unstable loop through the nosewheel servo and tyre forces. Give the nosewheel its own inputs with pilot
/// yaw, while the rudder and thrust vectoring retain the filtered command.
/// </summary>
static class GroundSteering
{
    static readonly FieldInfo NoseGear = AccessTools.Field(typeof(ControlsFilter.FlyByWire), "noseGear");
    static readonly FieldInfo GearInputs = AccessTools.Field(typeof(LandingGear), "controlInputs");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ground-steering", typeof(ControlsFilter), nameof(ControlsFilter.Filter),
            postfix: AccessTools.Method(typeof(GroundSteering), nameof(AfterFilter))),
    };

    static void AfterFilter(ControlsFilter __instance, Aircraft ___aircraft, ControlInputs inputs, Vector3 rawInputs)
    {
        if (IcarusPlugin.FeaturesOff.Contains("ground-steering")) return;
        if (___aircraft == null || ___aircraft.definition == null || ___aircraft.definition.jsonKey != IcarusPlugin.JsonKey) return;
        var gear = (LandingGear)NoseGear.GetValue(__instance.GetFlyByWire());
        if (gear == null) return;

        var steering = GearInputs.GetValue(gear) as ControlInputs;
        if (steering == null || ReferenceEquals(steering, inputs))
        {
            steering = new ControlInputs();
            GearInputs.SetValue(gear, steering);
        }

        // LandingGear reads only these three fields. Braking and throttle keep the aircraft's filtered values.
        steering.yaw = rawInputs.y;
        steering.brake = inputs.brake;
        steering.throttle = inputs.throttle;
    }
}
