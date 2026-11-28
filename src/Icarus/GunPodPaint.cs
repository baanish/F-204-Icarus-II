using System;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Gun pods under a Bare Metal livery. The Icarus's own 25 mm pod body (IcarusAuthor.GunPod) takes the belly's metallic
/// map. The stock 20 mm pod has its own material and atlas, so it gets an even polished finish instead.
/// </summary>
static class GunPodPaint
{
    const string Feature = "gun-pod-paint", OwnPod = "baanish_icarus_gunpod_25mm", OwnBody = "gunpod_25mm_body", StockPod = "gunpod_20mm";
    static readonly int LiveryId = Shader.PropertyToID("_Livery");
    static readonly AccessTools.FieldRef<UnitPart, DamageMaterial> DamageMaterialOf = AccessTools.FieldRefAccess<UnitPart, DamageMaterial>("damageMaterial");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(Hardpoint), nameof(Hardpoint.SpawnMount), new[] { typeof(Aircraft), typeof(WeaponMount) },
            postfix: AccessTools.Method(typeof(GunPodPaint), nameof(AfterSpawnMount))),
    };

    static void AfterSpawnMount(Hardpoint __instance, Aircraft aircraft, WeaponMount weaponMount, GameObject __result)
    {
        if (IcarusPlugin.FeaturesOff.Contains(Feature) || __result == null || __instance.part == null || weaponMount == null
            || aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey
            || weaponMount.jsonKey != OwnPod && weaponMount.jsonKey != StockPod) return;
        UnitPart part = __instance.part;
        // The part's own skin: the renderers its livery paints, which BareMetalLivery gives the Bare Metal maps.
        Renderer? skin = DamageMaterialOf(part)?.renderers.FirstOrDefault(r => r != null && r.sharedMaterial != null && r.sharedMaterial.HasProperty(LiveryId));
        if (skin == null)
        {
            IcarusPlugin.Log.Warning($"{weaponMount.jsonKey}: no skin renderer on {part.name} to follow");
            return;
        }
        if (weaponMount.jsonKey == OwnPod)
        {
            var metallic = __result.AddComponent<MountMetallic>();
            metallic.Source = skin;
            metallic.Targets = __result.GetComponentsInChildren<Renderer>(true).Where(r => r.name == OwnBody).ToArray();
            return;
        }
        var plain = aircraft.transform.Find("Icarus_livery_materials")?.GetComponent<MeshRenderer>()?.sharedMaterials.FirstOrDefault();
        if (plain == null) return;
        var bare = __result.AddComponent<StockPodBareMetal>();
        bare.Skin = skin;
        bare.PlainMetallic = plain.GetTexture("_Metallic");
    }
}

/// <summary>
/// Turns the stock pod to polished metal (no paint, white base, full metallic and smoothness) while the part it hangs
/// from wears a Bare Metal livery's metallic map (BareMetalLivery), and puts its own maps back otherwise.
/// </summary>
sealed class StockPodBareMetal : MonoBehaviour
{
    const float RefreshS = 0.5f;
    static readonly int MetallicId = Shader.PropertyToID("_Metallic"), PaintId = Shader.PropertyToID("_Paint"),
        BaseColorId = Shader.PropertyToID("_BaseColor");

    internal Renderer? Skin;
    internal Texture? PlainMetallic;
    Renderer[] pod = Array.Empty<Renderer>();
    MaterialPropertyBlock? block;
    bool bare;
    float next;

    void Start()
    {
        pod = GetComponentsInChildren<Renderer>(true).Where(r => r.sharedMaterial != null && r.sharedMaterial.HasProperty(PaintId)).ToArray();
        block = new MaterialPropertyBlock();
    }

    void Update()
    {
        if (Time.time < next || Skin == null || block == null) return;
        next = Time.time + RefreshS;
        Material livery = Skin.sharedMaterial;
        if (livery == null || !livery.HasProperty(MetallicId)) return;
        bool now = livery.GetTexture(MetallicId) is Texture metallic && metallic != PlainMetallic;
        if (bare == now) return;
        bare = now;
        foreach (Renderer renderer in pod)
        {
            Material own = renderer.sharedMaterial;
            renderer.GetPropertyBlock(block);
            block.SetTexture(PaintId, now ? Texture2D.blackTexture : own.GetTexture(PaintId));
            block.SetTexture(BaseColorId, now ? Texture2D.whiteTexture : own.GetTexture(BaseColorId));
            block.SetTexture(MetallicId, now ? Texture2D.whiteTexture : own.GetTexture(MetallicId));
            renderer.SetPropertyBlock(block);
        }
    }
}
