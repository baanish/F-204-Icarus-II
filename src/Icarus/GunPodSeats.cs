using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Seats the stock 20 mm gun pods against the Icarus's belly on the conformal stations as they spawn, on every peer. The
/// trough is narrower than the pod, so each pod is tucked into it as far as it goes, rolled on its side toward the
/// centreline, which leaves the least of it in the airflow below the fuselage; its capsule reaches into fuselage_mid,
/// the hull the hardpoint is on. The pod's pieces move by an offset from their prefab place and turn about the pod's own
/// origin; the seat is given for the right hardpoint and mirrored on the left. tools/stores/geometry.py GUN_POD_SEATS
/// repeats it for tools/store_clearance.py. The centreline's 25 mm pod is the Icarus's own mount (IcarusAuthor.GunPod.cs).
/// </summary>
static class GunPodSeats
{
    const string Feature = "gun-pod-seat", Pod = "gunpod";

    static readonly Dictionary<(string Station, string Mount), (Vector3 Offset, Vector3 Euler)> Seats = new()
    {
        [("hardpoint_conformal", "gunpod_20mm")] = (new Vector3(-0.086f, -0.2166f, 0.672f), new Vector3(0f, 0f, 84.4f)),
    };

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(Hardpoint), nameof(Hardpoint.SpawnMount), new[] { typeof(Aircraft), typeof(WeaponMount) },
            postfix: AccessTools.Method(typeof(GunPodSeats), nameof(AfterSpawnMount))),
    };

    static void AfterSpawnMount(Hardpoint __instance, Aircraft aircraft, WeaponMount weaponMount, GameObject __result)
    {
        if (IcarusPlugin.FeaturesOff.Contains(Feature) || __result == null || weaponMount == null || aircraft == null
            || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey || __instance.transform == null) return;
        var hardpoint = __instance.transform.name;
        var station = hardpoint.StartsWith("hardpoint_conformal") ? "hardpoint_conformal" : hardpoint;
        if (!Seats.TryGetValue((station, weaponMount.jsonKey), out var seat)) return;
        var pod = __result.transform.Find(Pod);
        if (pod == null)
        {
            IcarusPlugin.Log.Warning($"{weaponMount.jsonKey} has no {Pod} child to seat on {hardpoint}");
            return;
        }
        var (offset, euler) = seat;
        if (aircraft.transform.InverseTransformPoint(__instance.transform.position).x < 0f)
        {
            offset.x = -offset.x;
            euler = new Vector3(euler.x, -euler.y, -euler.z);
        }
        var turn = Quaternion.Euler(euler);
        var origin = pod.localPosition;
        pod.localPosition = origin + offset;
        pod.localRotation = turn * pod.localRotation;
        // The capsule sits on the mount's root, not on the pod: it moves with it. The seats only roll the pod about its
        // length, so the capsule keeps its direction.
        if (__result.GetComponent<CapsuleCollider>() is CapsuleCollider capsule)
            capsule.center = origin + offset + turn * (capsule.center - origin);
        if (IcarusPlugin.Log.StageEnabled)
            IcarusPlugin.Log.Stage(Feature, $"{weaponMount.jsonKey} seated on {hardpoint}: moved {offset.ToString("F3")}, turned {euler.ToString("F2")}", everyOccurrence: true);
    }
}
