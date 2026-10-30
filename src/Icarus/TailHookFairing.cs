using System;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Gives the arrestor hook the hooked fin's livery after Hardpoint.SpawnMount fits it.
/// The hook's UVs sample the fairing's paint (art/blender/tail_hook.py paint), and <see cref="TailHookPaint"/>
/// follows the fin's livery changes on each peer without sending network messages.
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
        __result.AddComponent<TailHookPaint>().Fin = part.GetComponentsInChildren<Renderer>(true).FirstOrDefault(r => r.name == HookedFin);
    }
}

/// <summary>
/// The hook's paint: every half second, the livery the hooked fin wears (UnitPart.SetLivery sets _Livery and _Glossiness,
/// BareMetalLivery the _Metallic map), as TipTanks dresses its stores from the wing.
/// </summary>
sealed class TailHookPaint : MonoBehaviour
{
    const float RefreshS = 0.5f;
    static readonly int LiveryId = Shader.PropertyToID("_Livery"), GlossId = Shader.PropertyToID("_Glossiness"), MetallicId = Shader.PropertyToID("_Metallic");

    internal Renderer? Fin;
    Renderer[] hook = Array.Empty<Renderer>();
    MaterialPropertyBlock? block;
    float next;

    void Start()
    {
        hook = GetComponentsInChildren<Renderer>(true);
        block = new MaterialPropertyBlock();
    }

    void Update()
    {
        if (Time.time < next || Fin == null || block == null) return;
        next = Time.time + RefreshS;
        Material livery = Fin.sharedMaterial;
        if (livery == null) return;
        foreach (Renderer renderer in hook)
        {
            renderer.GetPropertyBlock(block);
            if (livery.HasProperty(LiveryId) && livery.GetTexture(LiveryId) is Texture paint) block.SetTexture(LiveryId, paint);
            if (livery.HasProperty(MetallicId) && livery.GetTexture(MetallicId) is Texture metallic) block.SetTexture(MetallicId, metallic);
            if (livery.HasProperty(GlossId)) block.SetFloat(GlossId, livery.GetFloat(GlossId));
            renderer.SetPropertyBlock(block);
        }
    }
}
