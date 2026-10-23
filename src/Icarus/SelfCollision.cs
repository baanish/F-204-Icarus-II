using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// An Icarus's parts never collide with one another. Its skin panels, cores and tanks nest within millimetres of each other
/// on separate rigidbodies, and their joints flex more than any practical gap when the aircraft settles at spawn, so
/// neighbouring panels met at 23 to 30 g and took impact damage on the runway. Stock airframes have fewer, blockier parts
/// and rely on gaps; Unity's joints only disable collision between the two bodies each one joins. The pairs are ignored
/// once, from SetLocalSim on every peer, before the loadout spawns, so stores still collide with the airframe.
/// </summary>
static class SelfCollision
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("self-collision", typeof(Aircraft), nameof(Aircraft.SetLocalSim), new[] { typeof(bool) },
            postfix: AccessTools.Method(typeof(SelfCollision), nameof(AfterSetLocalSim))),
    };

    static void AfterSetLocalSim(Aircraft __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("self-collision")) return;
        if (__instance.definition == null || __instance.definition.jsonKey != IcarusPlugin.JsonKey)
        {
            return;
        }

        var parts = IcarusSystems.Parts(__instance)
            .Select(p => p.GetComponentsInChildren<Collider>(true).Where(c => !c.isTrigger).ToArray())
            .ToArray();
        int pairs = 0;
        for (int i = 0; i < parts.Length; i++)
        {
            for (int j = i + 1; j < parts.Length; j++)
            {
                foreach (Collider a in parts[i])
                {
                    foreach (Collider b in parts[j])
                    {
                        Physics.IgnoreCollision(a, b);
                        pairs++;
                    }
                }
            }
        }

        IcarusPlugin.Log.Stage("self-collision", $"Icarus {__instance.persistentID}: {parts.Sum(p => p.Length)} colliders on {parts.Length} parts, {pairs} pairs ignored");
    }
}
