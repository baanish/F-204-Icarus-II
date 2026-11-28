using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Matches the arrestor hook's metallic map to the hooked fin after Hardpoint.SpawnMount fits it.
/// ColorableMount supplies the paint sampled by the hook's UVs (art/blender/tail_hook.py paint); MountMetallic the metallic map.
/// </summary>
public static class TailHookFairing
{
    /// <summary>The hook mount's WeaponMount.jsonKey (IcarusAuthor.TailHook).</summary>
    const string MountKey = "baanish_icarus_tail_hook";
    /// <summary>Variant D's fin and fairing on the part, drawn while the hook is fitted (art/blender/tail_hook.py HOOKED_FIN).</summary>
    const string HookedFin = "ventral_fin_hooked";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("tail-hook-fairing", typeof(Hardpoint), nameof(Hardpoint.SpawnMount), new[] { typeof(Aircraft), typeof(WeaponMount) },
            postfix: AccessTools.Method(typeof(TailHookFairing), nameof(AfterSpawnMount))),
    };

    static void AfterSpawnMount(Hardpoint __instance, WeaponMount weaponMount, GameObject __result)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tail-hook-fairing") || __result == null || __instance.part == null
            || weaponMount == null || weaponMount.jsonKey != MountKey) return;
        GameObject part = __instance.part.gameObject;
        __result.AddComponent<MountMetallic>().Source = part.GetComponentsInChildren<Renderer>(true).FirstOrDefault(r => r.name == HookedFin);
    }
}
