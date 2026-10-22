using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.Networking;
using NuclearOption.SavedMission;

namespace Icarus;

/// <summary>
/// Puts the Icarus into Primeva's AI supply in the stock operations and has one Primeva Revoker factory in each build
/// Icarus instead, behind Missions.StockMissionSupply, default on (owner, 2026-10-20; .internal research R3). The host's
/// setting decides, read at each mission load. Only the built-in missions in <see cref="Factories"/> change: the
/// numbered scenarios, Altercation and Carrier Duel keep their stock supply, and the mission editor is left alone, since
/// it saves a factory's live production type back into the mission (Building.CreateBuiltInSavedUnit).
/// The reserve goes in from the delayed server pass after <see cref="AiSupplyRepair"/>, once FactionHQ.OnMissionLoad has
/// reset the inventory and the Icarus is surely in Encyclopedia.Lookup. The factory is repointed in a prefix on its
/// first SetFactory, because a second call starts another production timer instead of replacing the first.
/// </summary>
static class StockMissionSupply
{
    public const string Faction = "Primeva";

    /// <summary>Icarus added to Primeva's starting supply: as many as stock Domination gives it Revokers.</summary>
    public const int StartingReserve = 4;

    const string Revoker = "Fighter1";

    /// <summary>
    /// Built-in mission name (MissionKey.Name) to the UniqueName of the Primeva factory whose Revoker production becomes
    /// the Icarus's, at the factory's own interval. Co-op variants carry the same buildings. Domination and Confrontation
    /// have no other Revoker factory; Breakout, Escalation and Terminal Control keep one.
    /// </summary>
    internal static readonly Dictionary<string, string> Factories = new()
    {
        ["Breakout"] = "factory_large_4",
        ["Confrontation"] = "DsrtFac",
        ["Confrontation Co-op as PALA"] = "DsrtFac",
        ["Confrontation Co-op as BDF"] = "DsrtFac",
        ["Domination"] = "IslandFac1",
        ["Domination Co-op as PALA"] = "IslandFac1",
        ["Domination Co-op as BDF"] = "IslandFac1",
        ["Escalation"] = "RearFac1",
        ["Escalation Co-op as PALA"] = "RearFac1",
        ["Escalation Co-op as BDF"] = "RearFac1",
        ["Terminal Control"] = "PALA_northFac4",
        ["Terminal Control Co-op as PALA"] = "PALA_northFac4",
        ["Terminal Control Co-op as BDF"] = "PALA_northFac4",
    };

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("stock-supply", typeof(Factory), nameof(Factory.SetFactory), new[] { typeof(string), typeof(float) },
            prefix: AccessTools.Method(typeof(StockMissionSupply), nameof(BeforeSetFactory))),
    };

    static ConfigEntry<bool> enabled = null!;

    internal static void Install(ConfigFile config, IcarusLog log)
    {
        enabled = config.Bind("Missions", "StockMissionSupply", true,
            $"In the stock operations (Breakout, Confrontation, Domination, Escalation, Terminal Control and their co-op variants), add {StartingReserve} Icarus to {Faction}'s AI supply and have one {Faction} Revoker factory build the Icarus instead. The host's setting applies, from the next mission load");
        log.Info($"Missions.StockMissionSupply={enabled.Value}");
    }

    /// <summary>The covered mission's Icarus factory, or null when this mission keeps its stock supply.</summary>
    static string? CoveredFactory(Mission? mission) =>
        enabled.Value && GameManager.gameState != GameState.Editor && mission?.LoadKey is { } key
        && key.Group == MissionGroup.BuiltIn && Factories.TryGetValue(key.Name, out string factory) ? factory : null;

    public static void Apply(IcarusLog log)
    {
        Mission? mission = MissionManager.CurrentMission;
        if (IcarusPlugin.FeaturesOff.Contains("stock-supply") || !NetworkManagerNuclearOption.i.Server.Active || CoveredFactory(mission) == null)
        {
            return;
        }

        if (!Encyclopedia.Lookup.TryGetValue(IcarusPlugin.JsonKey, out UnitDefinition definition) || definition is not AircraftDefinition icarus)
        {
            log.Warning($"stock supply: {IcarusPlugin.JsonKey} is not in the encyclopedia, so {mission!.Name} keeps its stock supply");
            return;
        }

        foreach (FactionHQ hq in FactionRegistry.GetAllHQs())
        {
            if (hq.faction?.factionName != Faction)
            {
                continue;
            }

            // Already there means the mission lists it or this pass ran for this load: leave the count alone.
            if (hq.AircraftSupply.ContainsKey(icarus))
            {
                log.Info($"stock supply: {Faction} already holds {hq.AircraftSupply[icarus].Count} {IcarusPlugin.JsonKey} in {mission!.Name}, left alone");
                continue;
            }

            hq.ModifyUnitSupply(icarus, StartingReserve);
            log.Info($"stock supply: added {StartingReserve} {IcarusPlugin.JsonKey} to {Faction} in {mission!.Name}");
        }
    }

    static void BeforeSetFactory(Factory __instance, ref string productionType)
    {
        if (IcarusPlugin.FeaturesOff.Contains("stock-supply") || productionType != Revoker)
        {
            return;
        }

        Mission? mission = MissionManager.CurrentMission;
        string? factory = CoveredFactory(mission);
        if (factory == null || __instance.attachedUnit == null || __instance.attachedUnit.UniqueName != factory)
        {
            return;
        }

        // An unknown key would leave the factory building nothing (SetFactory skips it), so it keeps the Revoker.
        if (!Encyclopedia.Lookup.ContainsKey(IcarusPlugin.JsonKey))
        {
            IcarusPlugin.Log.Warning($"stock supply: {IcarusPlugin.JsonKey} is not in the encyclopedia yet, so {factory} in {mission!.Name} keeps building {Revoker}");
            return;
        }

        productionType = IcarusPlugin.JsonKey;
        IcarusPlugin.Log.Info($"stock supply: {factory} in {mission!.Name} builds {IcarusPlugin.JsonKey} instead of {Revoker}");
    }
}
