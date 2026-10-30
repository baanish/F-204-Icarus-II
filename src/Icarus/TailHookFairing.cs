using System;
using System.Linq;
using HarmonyLib;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus;

/// <summary>
/// The hooked ventral fin's collider hulls (art/blender/tail_hook.py fin_hulls, IcarusAuthor.TailHook.cs). The fairing
/// comes with the arrestor hook: the Tail Hook hardpoint swaps the two fins' renderers the stock way (Hardpoint.Plug and
/// pylonOptions), but the game has no way for a mount to give its part colliders. A mount's own colliders stay on the
/// mount's objects, and bullets and blasts damage only the object whose collider they hit (BulletSim, Explosion), so the
/// hulls ride in the mount disabled and this puts copies on the part itself while the hook is fitted: after
/// Hardpoint.SpawnMount hangs the hook, and off again before Hardpoint.RemoveMount takes it down. The part keeps them if
/// it breaks off, as it keeps the hook. The hook wears the airframe skin with its UVs on the fairing's paint
/// (art/blender/tail_hook.py paint), and <see cref="TailHookPaint"/> hands it the livery the hooked fin wears. Every
/// peer spawns the mounts of the loadout it is sent, so this sends nothing.
/// </summary>
public static class TailHookFairing
{
    /// <summary>The hook mount's WeaponMount.jsonKey (IcarusAuthor.TailHook).</summary>
    const string MountKey = "baanish_icarus_tail_hook";
    /// <summary>The mount prefab's child that holds the hulls as disabled convex MeshColliders, in the part's frame.</summary>
    public const string HullHolder = "fairing_hulls";
    /// <summary>Variant D's fin and fairing on the part, drawn while the hook is fitted (art/blender/tail_hook.py HOOKED_FIN).</summary>
    const string HookedFin = "ventral_fin_hooked";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("tail-hook-fairing", typeof(Hardpoint), nameof(Hardpoint.SpawnMount), new[] { typeof(Aircraft), typeof(WeaponMount) },
            postfix: AccessTools.Method(typeof(TailHookFairing), nameof(AfterSpawnMount))),
        new("tail-hook-fairing", typeof(Hardpoint), nameof(Hardpoint.RemoveMount), Type.EmptyTypes,
            prefix: AccessTools.Method(typeof(TailHookFairing), nameof(BeforeRemoveMount))),
    };

    static MeshCollider[] Hulls(WeaponMount? mount) =>
        mount == null || mount.jsonKey != MountKey || mount.prefab == null ? Array.Empty<MeshCollider>()
            : mount.prefab.transform.Find(HullHolder)?.GetComponents<MeshCollider>() ?? Array.Empty<MeshCollider>();

    static void AfterSpawnMount(Hardpoint __instance, Aircraft aircraft, WeaponMount weaponMount, GameObject __result)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tail-hook-fairing") || __result == null || __instance.part == null) return;
        MeshCollider[] hulls = Hulls(weaponMount);
        if (hulls.Length == 0) return;
        GameObject part = __instance.part.gameObject;
        __result.AddComponent<TailHookPaint>().Fin = part.GetComponentsInChildren<Renderer>(true).FirstOrDefault(r => r.name == HookedFin);
        foreach (MeshCollider hull in hulls)
        {
            MeshCollider added = part.AddComponent<MeshCollider>();
            added.convex = true;
            added.sharedMesh = hull.sharedMesh;
        }
        IcarusPlugin.Log.Stage("tail-hook-fairing", $"tail hook fitted on {aircraft.persistentID}: {hulls.Length} fairing hulls on {part.name}, " +
            $"{part.GetComponents<MeshCollider>().Length} colliders there", everyOccurrence: true);
    }

    static void BeforeRemoveMount(Hardpoint __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tail-hook-fairing") || __instance.part == null) return;
        var meshes = Hulls(__instance.GetMount()).Select(h => h.sharedMesh).ToHashSet();
        if (meshes.Count == 0) return;
        int removed = 0;
        foreach (MeshCollider collider in __instance.part.GetComponents<MeshCollider>())
        {
            if (!meshes.Contains(collider.sharedMesh)) continue;
            Object.Destroy(collider);
            removed++;
        }
        IcarusPlugin.Log.Stage("tail-hook-fairing", $"tail hook removed: {removed} fairing hulls off {__instance.part.name}", everyOccurrence: true);
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
