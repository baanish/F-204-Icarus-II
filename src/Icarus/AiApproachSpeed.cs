using HarmonyLib;
using UnityEngine;

namespace Icarus;

static class AiApproachSpeed
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-approach-speed", typeof(AIPilotLandingState), "StabilizedApproach",
            prefix: AccessTools.Method(typeof(AiApproachSpeed), nameof(BeforeStabilizedApproach)),
            postfix: AccessTools.Method(typeof(AiApproachSpeed), nameof(AfterStabilizedApproach))),
    };

    static void BeforeStabilizedApproach(bool checkMode, Aircraft ___aircraft,
        AircraftParameters ___aircraftParameters, float ___adjustedLandingSpeed,
        Airbase ___airbase, out float __state)
    {
        __state = -1f;
        if (checkMode || ___aircraft == null || ___aircraft.definition.jsonKey != IcarusPlugin.JsonKey
            || ___airbase == null || ___airbase.AttachedAirbase) return;

        // AutopilotPlane's low-speed bank bias must use the same mass-adjusted threshold
        // as the landing state. Restore the shared parameters after this synchronous call.
        __state = ___aircraftParameters.landingSpeed;
        ___aircraftParameters.landingSpeed = ___adjustedLandingSpeed;
    }

    static void AfterStabilizedApproach(float __state, Aircraft ___aircraft,
        AircraftParameters ___aircraftParameters,
        ControlInputs ___controlInputs, float ___adjustedLandingSpeed)
    {
        if (__state < 0f) return;
        ___aircraftParameters.landingSpeed = __state;

        // The stock distance allowance keeps the slick Icarus fast well into runway final.
        // Use its weight-adjusted landing target throughout final, retaining the stock 5 m/s
        // throttle margin and any lower throttle demanded by the flare.
        Vector3 airVelocity = ___aircraft.rb.velocity
            - NetworkSceneSingleton<LevelInfo>.i.GetWind(___aircraft.GlobalPosition());
        float forwardSpeed = Vector3.Dot(___aircraft.transform.forward, airVelocity);
        ___controlInputs.throttle = Mathf.Min(___controlInputs.throttle,
            Mathf.Clamp01((___adjustedLandingSpeed + 5f - forwardSpeed) * 0.1f));
    }
}
