using System.Linq;
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

        if (!__instance.TryGetComponent<EjectLog>(out _))
        {
            __instance.gameObject.AddComponent<EjectLog>();
        }

        Turbojet? engine = Engine(__instance);
        JetNozzle? nozzle = engine == null ? null : Nozzle(engine);
        Transform? reheat = nozzle == null ? null : nozzle.transform.Find("afterburner_audio");
        if (reheat == null)
        {
            IcarusPlugin.Log.Error("reheat gain: no thrust_vector/afterburner_audio; reheat plays 9.5 dB under its mix");
        }
        else if (!reheat.TryGetComponent<ReheatGain>(out _))
        {
            reheat.gameObject.AddComponent<ReheatGain>();
        }

        IcarusPlugin.Log.Stage("spawn", $"Icarus {__instance.persistentID} seen, local sim {localSim}");
        Tuning.Track(__instance);
    }

    // Complex physics (the local player's and the host's AI aircraft) unparents every part but the root when SetLocalSim
    // runs (Aircraft.SetComplexPhysics, AeroPart.CreateRB), so the root's descendants no longer hold the airframe:
    // parts come from the aircraft's part list and the engine's own references.
    internal static AeroPart[] Parts(Aircraft aircraft) => aircraft.GetAllParts().OfType<AeroPart>().ToArray();

    internal static Turbojet? Engine(Aircraft aircraft) =>
        aircraft.GetComponent<Turbojet>() ?? Parts(aircraft).Select(p => p.GetComponent<Turbojet>()).FirstOrDefault(t => t != null);

    internal static JetNozzle? Nozzle(Turbojet engine) =>
        ((JetNozzle[])AccessTools.Field(typeof(Turbojet), "nozzles").GetValue(engine)).FirstOrDefault(n => n != null);
}
