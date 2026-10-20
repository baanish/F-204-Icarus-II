using BepInEx.Bootstrap;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Icarus;

/// <summary>
/// Every automatic start (-autoHost, -autoConnect, a dedicated server's mission, a Steam lobby join) waits on
/// MainMenu.WaitForLoaded, State == Loaded, which the game sets when its own loads finish. Blueprinter adds the Icarus to
/// the encyclopedia from a frame to several seconds later, so a host started that way spawns none of the mission's Icarus
/// and a client registers no Icarus prefab with Mirage. The state reads Loading until the Icarus is in Encyclopedia.Lookup
/// and Blueprinter's ops after it have had <see cref="SettleS"/>, for at most <see cref="MaxHoldS"/>, and only while
/// Blueprinter is loaded. A start from the menu does not wait on it.
/// </summary>
static class StartupHold
{
    const string BlueprinterGuid = "com.nikkorap.blueprinter";
    const float SettleS = 1f, MaxHoldS = 30f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("startup-hold", typeof(MainMenu), "get_State", postfix: AccessTools.Method(typeof(StartupHold), nameof(AfterState))),
    };

    static float heldSince = float.NaN, registeredAt = float.NaN;
    static bool released;

    static void AfterState(ref MainMenu.LoadingState __result)
    {
        if (IcarusPlugin.FeaturesOff.Contains("startup-hold")) return;
        if (__result == MainMenu.LoadingState.Loaded && !released && Holding())
        {
            __result = MainMenu.LoadingState.Loading;
        }
    }

    static bool Holding()
    {
        if (!Chainloader.PluginInfos.ContainsKey(BlueprinterGuid))
        {
            released = true;
            IcarusPlugin.Log.Warning("startup hold: Blueprinter is not loaded, so the Icarus content is not either");
            return false;
        }

        float now = Time.realtimeSinceStartup;
        if (float.IsNaN(heldSince))
        {
            heldSince = now;
            IcarusPlugin.Log.Info("startup hold: holding automatic starts until the Icarus is registered");
        }

        if (float.IsNaN(registeredAt) && Encyclopedia.Lookup != null && Encyclopedia.Lookup.ContainsKey(IcarusPlugin.JsonKey))
        {
            registeredAt = now;
        }

        bool settled = !float.IsNaN(registeredAt) && now - registeredAt >= SettleS;
        if (!settled && now - heldSince < MaxHoldS)
        {
            return true;
        }

        released = true;
        IcarusPlugin.Log.Info(Invariant($"startup hold: released {now - heldSince:0.0} s after the game's menu loaded, {(settled ? "the Icarus registered" : $"no Icarus in the encyclopedia after {MaxHoldS} s")}"));
        return false;
    }
}
