using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The Icarus's colliders make contacts only within 2 mm, not Unity's default 10 mm, so two parts' contacts start
/// across 4 mm rather than 20. Parts with no joint between them stand at least that far apart plus their flex
/// (art/blender/clearance.py), so they never touch while attached; jointed parts don't collide while their joint
/// stands (the game's joints switch collision off between the bodies they join), and a part that breaks free collides
/// with the rest of the jet as a stock part does. Unity serializes no contact offset on a collider, so it is set here,
/// from SetLocalSim on every peer, before the loadout spawns: stores keep the default.
/// </summary>
static class ContactOffset
{
    /// <summary>clearance.CONTACT_OFFSET: the clearance check sizes every gap from it.</summary>
    const float Offset = 0.002f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("contact-offset", typeof(Aircraft), nameof(Aircraft.SetLocalSim), new[] { typeof(bool) },
            postfix: AccessTools.Method(typeof(ContactOffset), nameof(AfterSetLocalSim))),
    };

    static void AfterSetLocalSim(Aircraft __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("contact-offset")) return;
        if (__instance.definition == null || __instance.definition.jsonKey != IcarusPlugin.JsonKey) return;
        int count = 0;
        foreach (AeroPart part in IcarusSystems.Parts(__instance))
        {
            // the hulls only: the gear's ground colliders keep the default
            foreach (MeshCollider collider in part.GetComponentsInChildren<MeshCollider>(true))
            {
                if (collider.isTrigger) continue;
                collider.contactOffset = Offset;
                count++;
            }
        }
        IcarusPlugin.Log.Stage("contact-offset", $"Icarus {__instance.persistentID}: {count} colliders at {Offset * 1000:0} mm contact offset");
    }
}
