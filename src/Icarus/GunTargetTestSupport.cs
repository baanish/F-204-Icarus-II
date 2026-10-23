using System;
using System.Runtime.CompilerServices;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Test support for the "Icarus - gun kills" mission: only server AI Icarus units whose mission UniqueName starts with
/// "Gun target " hold 200 m/s of true airspeed, about 390 knots: the slowest the Icarus holds level at the mission's
/// 8,000 m (at 154 m/s, 300 knots, it sank 10 to 13 m/s). A proportional/integral throttle controller runs
/// after combat AI writes its inputs, with conditional integration to prevent windup at idle or full throttle.
/// It changes only throttle; cruiseThrottle, other units, player aircraft and flight steering keep stock behavior.
/// </summary>
static class GunTargetTestSupport
{
    const string Feature = "gun-target-test-speed";
    const float TargetSpeed = 200f;
    const float ProportionalGain = 0.02f, IntegralGain = 0.002f;
    static readonly ConditionalWeakTable<Pilot, SpeedController> Controllers = new();

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(AIPilotCombatModes), nameof(AIPilotCombatModes.FixedUpdateState),
            postfix: AccessTools.Method(typeof(GunTargetTestSupport), nameof(AfterCombatInputs))),
    };

    static void AfterCombatInputs(Pilot pilot)
    {
        if (IcarusPlugin.FeaturesOff.Contains(Feature)) return;
        Aircraft aircraft = pilot.aircraft;
        if (aircraft == null || !aircraft.IsServer || !aircraft.LocalSim || aircraft.playerRef.Valid()
            || pilot.playerControlled || pilot.dead || pilot.ejected || aircraft.disabled
            || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey
            || aircraft.UniqueName == null || !aircraft.UniqueName.StartsWith("Gun target ", StringComparison.Ordinal)) return;

        Vector3 wind = NetworkSceneSingleton<LevelInfo>.i.GetWind(aircraft.GlobalPosition());
        float speed = (aircraft.CockpitRB().velocity - wind).magnitude;
        aircraft.GetInputs().throttle = Controllers.GetValue(pilot, _ => new SpeedController()).Throttle(speed, Time.fixedDeltaTime);
    }

    internal sealed class SpeedController
    {
        float trim = 0.35f;

        internal float Throttle(float speed, float dt)
        {
            float error = TargetSpeed - speed;
            float demand = trim + ProportionalGain * error;
            if ((demand > 0f || error > 0f) && (demand < 1f || error < 0f))
                trim = Mathf.Clamp01(trim + IntegralGain * error * dt);
            return Mathf.Clamp01(trim + ProportionalGain * error);
        }
    }
}
