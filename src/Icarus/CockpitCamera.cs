using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// After an Icarus breakup, keep external views on the cockpit even if the camera missed its detach event.
/// The root remains fuselage_mid. Stock orbit caches a rigidbody and chase parents its pivot to the root until
/// onParentDetached arrives; a disabled aircraft can already have physically separated before that notification.
/// </summary>
static class CockpitCamera
{
    const string Feature = "cockpit-camera";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(CameraOrbitState), "CameraMotion",
            prefix: AccessTools.Method(typeof(CockpitCamera), nameof(BeforeOrbitMotion))),
        new(Feature, typeof(CameraChaseState), nameof(CameraChaseState.UpdateState),
            prefix: AccessTools.Method(typeof(CockpitCamera), nameof(BeforeChaseUpdate))),
        new(Feature, typeof(CameraTVState), nameof(CameraTVState.UpdateState),
            prefix: AccessTools.Method(typeof(CockpitCamera), nameof(BeforeTVUpdate))),
    };

    static bool FollowingBrokenCockpit(CameraStateManager cam, out Aircraft aircraft)
    {
        aircraft = (cam.followingUnit as Aircraft)!;
        return !IcarusPlugin.FeaturesOff.Contains(Feature) && aircraft != null
            && aircraft.definition != null && aircraft.definition.jsonKey == IcarusPlugin.JsonKey
            && !aircraft.HasEjected() && aircraft.cockpit != null && aircraft.CockpitRB() != null
            && (aircraft.disabled || aircraft.cockpit.IsDetached());
    }

    static void BeforeOrbitMotion(CameraStateManager cam, ref Rigidbody ___follow1,
        ref Rigidbody ___follow2, ref float ___followLerp)
    {
        if (!FollowingBrokenCockpit(cam, out Aircraft aircraft)) return;
        ___follow1 = aircraft.CockpitRB();
        ___follow2 = null!;
        ___followLerp = 0f;
        cam.followingRB = ___follow1;
        cam.cameraPivot.SetParent(aircraft.cockpit.transform, true);
    }

    static void BeforeChaseUpdate(CameraStateManager cam, ref float ___transitionTimer)
    {
        if (!FollowingBrokenCockpit(cam, out Aircraft aircraft)) return;
        ___transitionTimer = 0f;
        cam.followingRB = aircraft.CockpitRB();
        cam.cameraPivot.SetParent(aircraft.cockpit.transform, true);
    }

    static void BeforeTVUpdate(CameraStateManager cam, ref float ___transitionTimer)
    {
        if (!FollowingBrokenCockpit(cam, out Aircraft aircraft)) return;
        ___transitionTimer = 0f;
        cam.followingRB = aircraft.CockpitRB();
    }
}
