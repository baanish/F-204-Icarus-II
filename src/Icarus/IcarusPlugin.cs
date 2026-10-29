using System;
using System.Collections.Generic;
using System.Linq;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The F-204 Icarus II plugin: config (BepInEx/config/baanish.icarus.cfg), the "[Icarus]" logger, the Harmony install,
/// the startup hold, AI supply repair and stock-mission supply, the iris nozzle driver, the cockpit's live instruments, the tip tanks' fuel and the live tuning knobs.
/// </summary>
[BepInPlugin(Guid, "F-204 Icarus II", Version)]
public sealed class IcarusPlugin : BaseUnityPlugin
{
    public const string Guid = "baanish.icarus";
    public const string Version = "0.1.0";

    /// <summary>AircraftDefinition.jsonKey of the Icarus (IcarusAuthor.JsonKey).</summary>
    public const string JsonKey = "baanish_icarus";

    /// <summary>Seconds between a mission starting and the supply repair and stock-mission supply, so the HQs have loaded.</summary>
    const float SupplyRepairDelayS = 3f;

    static readonly PatchTarget[] PatchTargets = StartupHold.PatchTargets.Concat(IcarusSystems.PatchTargets).Concat(BulletHitLog.PatchTargets).Concat(JointAnchors.PatchTargets).Concat(PartContactLog.PatchTargets).Concat(ContactOffset.PatchTargets).Concat(TailFlex.PatchTargets).Concat(StockMissionSupply.PatchTargets).Concat(CockpitCamera.PatchTargets).Concat(GunTargetTestSupport.PatchTargets).Concat(BareMetalLivery.PatchTargets).Concat(GroundSteering.PatchTargets).Concat(TipTanks.PatchTargets).Concat(LiveryFallback.PatchTargets).Concat(HelipadLaunch.PatchTargets).Concat(LeadingEdgeFlaps.PatchTargets).Concat(DamageRegistrations.PatchTargets).ToArray();

    internal static IcarusLog Log = null!;

    /// <summary>Features whose patch target was missing or failed; their code stands down.</summary>
    internal static HashSet<string> FeaturesOff = new();

    ConfigEntry<bool> stageLogging = null!;
    Harmony harmony = null!;
    bool missionRunning;
    float supplyRepairAt = float.PositiveInfinity;

    void Awake()
    {
        Log = new IcarusLog(Logger);
        stageLogging = Config.Bind("Diagnostics", "StageLogging", true,
            "Log each stage the mod crosses (spawn, nozzle, tuning file), at most one line per key per second except opt-in BulletHits");
        Log.StageEnabled = stageLogging.Value;
        stageLogging.SettingChanged += (_, _) => Log.StageEnabled = stageLogging.Value;
        Log.Info($"F-204 Icarus II {Version} ({Guid}); Diagnostics.StageLogging={stageLogging.Value}");
        Tuning.Install(Config, Log);
        BulletHitLog.Install(Config);
        StockMissionSupply.Install(Config, Log);
        HelipadLaunch.Install(Config);
        DamageRegistrations.Install(Config);
        harmony = new Harmony(Guid);
        FeaturesOff = PatchTarget.InstallAll(harmony, PatchTargets, Log);
    }

    void OnDestroy() => harmony?.UnpatchSelf();

    /// <summary>The active loadout, including empty hardpoint sets, for scenario setup guards.</summary>
    public object? AgenticState()
    {
        if (!GameManager.GetLocalAircraft(out var aircraft) || aircraft.definition.jsonKey != JsonKey ||
            aircraft.Networkloadout == null) return null;
        return new { loadout = string.Join("|", aircraft.Networkloadout.weapons.Select(m => m != null ? m.jsonKey : "")) };
    }

    void Update()
    {
        Log.Tick();
        Tuning.Update();

        bool running = MissionManager.IsRunning;
        if (running && !missionRunning)
        {
            supplyRepairAt = Time.unscaledTime + SupplyRepairDelayS;
            Log.Stage("mission", "mission started");
        }
        else if (!running)
        {
            supplyRepairAt = float.PositiveInfinity;
        }

        missionRunning = running;
        if (Time.unscaledTime < supplyRepairAt)
        {
            return;
        }

        supplyRepairAt = float.PositiveInfinity;
        try
        {
            AiSupplyRepair.Apply(Log);
        }
        catch (Exception e)
        {
            Log.Error($"ai supply repair failed: {e}");
        }

        try
        {
            StockMissionSupply.Apply(Log);
        }
        catch (Exception e)
        {
            Log.Error($"stock supply failed: {e}");
        }
    }
}
