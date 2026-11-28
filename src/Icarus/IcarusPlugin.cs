using System;
using System.Collections.Generic;
using System.Linq;
using BepInEx;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The F-204 Icarus II plugin: config (BepInEx/config/baanish.icarus.cfg), the "[Icarus]" logger, the Harmony install,
/// the startup hold, AI supply repair and stock-mission supply, the iris nozzle driver, the cockpit's live instruments, the tip tanks' fuel, the live tuning knobs and its liveries' Workshop tag.
/// </summary>
[BepInPlugin(Guid, "F-204 Icarus II", Version)]
public sealed class IcarusPlugin : BaseUnityPlugin
{
    public const string Guid = "baanish.icarus";
    public const string Version = "0.4.1";

    /// <summary>AircraftDefinition.jsonKey of the Icarus (IcarusAuthor.JsonKey).</summary>
    public const string JsonKey = "baanish_icarus";

    /// <summary>Seconds between a mission starting and the supply repair and stock-mission supply, so the HQs have loaded.</summary>
    const float SupplyRepairDelayS = 3f;

    static readonly PatchTarget[] PatchTargets = StartupHold.PatchTargets.Concat(IcarusSystems.PatchTargets).Concat(JointAnchors.PatchTargets).Concat(PartContactLog.PatchTargets).Concat(TankFireLog.PatchTargets).Concat(ContactOffset.PatchTargets).Concat(TailFlex.PatchTargets).Concat(StockMissionSupply.PatchTargets).Concat(CockpitCamera.PatchTargets).Concat(BareMetalLivery.PatchTargets).Concat(GroundSteering.PatchTargets).Concat(AiTaxiSpeed.PatchTargets).Concat(TipTanks.PatchTargets).Concat(TailHookFairing.PatchTargets).Concat(BareMetalFirstPick.PatchTargets).Concat(HelipadLaunch.PatchTargets).Concat(LeadingEdgeFlaps.PatchTargets).Concat(DamageRegistrations.PatchTargets).Concat(OriginShiftPoses.PatchTargets).Concat(AiApproachSpeed.PatchTargets).Concat(PackMountFit.PatchTargets).Concat(GunPodSeats.PatchTargets).Concat(GunPodPaint.PatchTargets).Concat(FourSetLoadouts.PatchTargets).ToArray();

    internal static IcarusLog Log = null!;

    /// <summary>Features whose patch target was missing or failed; their code stands down.</summary>
    internal static HashSet<string> FeaturesOff = new();

    Harmony harmony = null!;
    bool missionRunning;
    float supplyRepairAt = float.PositiveInfinity;

    void Awake()
    {
        Log = new IcarusLog(Logger);
#if ICARUS_DEV
        var stageLogging = Config.Bind("Diagnostics", "StageLogging", false,
            "Log diagnostic stages, at most one line per key per second. Restart the game after changing this to install or remove diagnostic patches.");
        Log.StageEnabled = stageLogging.Value;
        stageLogging.SettingChanged += (_, _) => Log.StageEnabled = stageLogging.Value;
        Log.Info($"F-204 Icarus II {Version} ({Guid}); dev build; Diagnostics.StageLogging={stageLogging.Value}");
#else
        Log.Info($"F-204 Icarus II {Version} ({Guid}); release build; stage logging off");
#endif
        Tuning.Install(Config, Log);
        StockMissionSupply.Install(Config, Log);
        HelipadLaunch.Install(Config);
#if ICARUS_DEV
        DamageRegistrations.Install(Config);
        AircraftMenuProbe.Install(Config, this);
#endif
        harmony = new Harmony(Guid);
        FeaturesOff = PatchTarget.InstallAll(harmony, PatchTargets, Log);
    }

    void OnDestroy() => harmony?.UnpatchSelf();

    /// <summary>
    /// For scenario checks: the active loadout, including empty hardpoint sets; the liveries the aircraft menu offers the
    /// player's faction (the game's own LoadoutSelector.GetLiveryOptions); the faction's first livery, which a jet wears
    /// until its own loads (AircraftParameters.GetFirstLiveryForFaction); and the livery it wears.
    /// </summary>
    public object? AgenticState()
    {
        if (!GameManager.GetLocalAircraft(out var aircraft) || aircraft.definition.jsonKey != JsonKey ||
            aircraft.Networkloadout == null) return null;
        var parameters = aircraft.definition.aircraftParameters;
        var faction = aircraft.NetworkHQ != null ? aircraft.NetworkHQ.faction : null;
        var options = new List<(LiveryKey key, string label)>();
        LoadoutSelector.GetLiveryOptions(options, aircraft.definition, faction != null ? faction.factionName : null, true);
        var key = aircraft.NetworkLiveryKey;
        return new
        {
            loadout = string.Join("|", aircraft.Networkloadout.weapons.Select(m => m != null ? m.jsonKey : "")),
            liveries = string.Join("|", options.Select(o => o.label)),
            first_livery = parameters.liveries[parameters.GetFirstLiveryForFaction(faction)].name,
            livery = key.Type == LiveryKey.KeyType.Builtin && key.Index < parameters.liveries.Count ? parameters.liveries[key.Index].name : "",
        };
    }

    void Update()
    {
        LiveryWorkshopTag.Update(Log);
        Tuning.Update();

        bool running = MissionManager.IsRunning;
        if (running && !missionRunning)
        {
            supplyRepairAt = Time.unscaledTime + SupplyRepairDelayS;
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
