using HarmonyLib;

namespace Icarus;

/// <summary>
/// The stock taxi AI drives every type alike, up to about 15 m/s and through turns near 14 m/s. On the Icarus's
/// F-104 gear (2.48 m main track, centre of mass about 1.5 m up) that lifts the inside wheel, and the drooped outer
/// wing scrapes the apron at about 20 degrees of roll; the AI then counts itself stuck or damaged, parks and returns
/// the jet to supply, so no AI Icarus ever reached the runway (Escalation observer runs, 2026-10-30). Cap the AI's
/// taxi speed on the Icarus only. The takeoff roll is AIPilotTakeoffState, so it keeps full speed; players are
/// untouched (owner's call, 2026-10-30, over widening the gear).
/// </summary>
static class AiTaxiSpeed
{
    /// <summary>At 8 m/s a 15 m taxiway turn pulls about 0.45 g, against a tip-up near 0.75 g.</summary>
    public const float MaxTaxiSpeed = 8f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-taxi-speed", typeof(AIPilotTaxiState), nameof(AIPilotTaxiState.FixedUpdateState),
            postfix: AccessTools.Method(typeof(AiTaxiSpeed), nameof(AfterFixedUpdateState))),
    };

    static void AfterFixedUpdateState(Pilot pilot)
    {
        if (IcarusPlugin.FeaturesOff.Contains("ai-taxi-speed")) return;
        Aircraft aircraft = pilot.aircraft;
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey
            || aircraft.speed <= MaxTaxiSpeed) return;

        // Throttle stays above 0, where the Airbrake would open the speed brakes.
        ControlInputs inputs = aircraft.GetInputs();
        inputs.throttle = 0.01f;
        inputs.brake = 1f;
    }
}
