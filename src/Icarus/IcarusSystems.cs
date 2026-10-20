using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// First sight of an Icarus. The game calls Aircraft.SetLocalSim(bool) on every peer from OnStartClient, after every
/// component's Awake and before the loadout spawns, and again on an authority change, so the attach is idempotent.
/// </summary>
static class IcarusSystems
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("systems", typeof(Aircraft), nameof(Aircraft.SetLocalSim), new[] { typeof(bool) },
            postfix: AccessTools.Method(typeof(IcarusSystems), nameof(AfterSetLocalSim))),
    };

    static void AfterSetLocalSim(Aircraft __instance, bool localSim)
    {
        if (IcarusPlugin.FeaturesOff.Contains("systems")) return;
        if (__instance.definition == null || __instance.definition.jsonKey != IcarusPlugin.JsonKey)
        {
            return;
        }

        if (!__instance.TryGetComponent<NozzleDriver>(out _))
        {
            __instance.gameObject.AddComponent<NozzleDriver>();
        }

        IcarusPlugin.Log.Stage("spawn", $"Icarus {__instance.persistentID} seen, local sim {localSim}");
        Tuning.Track(__instance);
    }
}
