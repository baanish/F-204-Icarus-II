using HarmonyLib;
using UnityEngine;

namespace Icarus;

static class BareMetalLivery
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("bare-metal-livery", typeof(UnitPart), "SetLivery",
            new[] { typeof(LiveryData), typeof(MaterialCleanup) },
            postfix: AccessTools.Method(typeof(BareMetalLivery), nameof(AfterSetLivery))),
    };

    static void AfterSetLivery(UnitPart __instance, LiveryData livery, DamageMaterial ___damageMaterial)
    {
        if (IcarusPlugin.FeaturesOff.Contains("bare-metal-livery") ||
            __instance.parentUnit is not Aircraft aircraft || aircraft.definition == null ||
            aircraft.definition.jsonKey != IcarusPlugin.JsonKey) return;

        // The inactive root carrier keeps both bundled maps alive even after physics unparents the parts.
        var carrier = aircraft.transform.Find("Icarus_livery_materials")?.GetComponent<MeshRenderer>();
        if (carrier == null) return;
        Material[] sources = carrier.sharedMaterials;
        if (sources.Length != 2 || sources[0] == null || sources[1] == null) return;
        Material skin = sources[0], bare = sources[1];
        Texture bareLivery = bare.GetTexture("_Livery");
        Texture metallic = (bareLivery != null && livery.Texture == bareLivery ? bare : skin).GetTexture("_Metallic");
        if (metallic == null) return;

        foreach (Renderer renderer in ___damageMaterial.renderers)
        {
            // SetLivery already instanced slot 0 and registered it with MaterialCleanup. Never touch the source assets.
            Material material = renderer.sharedMaterial;
            if (material != null && material != skin && material != bare && material.shader == skin.shader &&
                material.GetTexture("_Basecolor") == skin.GetTexture("_Basecolor"))
                material.SetTexture("_Metallic", metallic);
        }
    }
}
