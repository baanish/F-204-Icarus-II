using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// FloatingOrigin.OriginShift runs in the camera's LateUpdate: it moves every scene root's transform by the shift and calls
/// Physics.SyncTransforms, which writes each transform back into its rigidbody. An interpolated rigidbody's transform holds
/// its render pose then, up to one physics step behind its physics pose, so every body is teleported back by part of a
/// step, each by its own interpolation, and the Icarus's bodies come out of the shift up to a step apart: in a 160 deg/s
/// roll the wing boxes landed 80 mm off the root, the joints snapped them back next step, and a wing box struck
/// fuselage_aft. After the shift, each interpolated Icarus body is put back on the physics pose it had, moved by the shift.
/// Bodies without interpolation (a remote copy, which Aircraft.SetLocalSim turns off and the network transform moves) are
/// left alone, since their transform is their pose.
/// </summary>
static class OriginShiftPoses
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("origin-shift-poses", typeof(FloatingOrigin), nameof(FloatingOrigin.OriginShift),
            prefix: AccessTools.Method(typeof(OriginShiftPoses), nameof(BeforeOriginShift)),
            postfix: AccessTools.Method(typeof(OriginShiftPoses), nameof(AfterOriginShift))),
    };

    static readonly List<(Rigidbody Body, Vector3 Position, Quaternion Rotation)> held = new List<(Rigidbody, Vector3, Quaternion)>();
    static Vector3 originBefore;

    static void BeforeOriginShift()
    {
        held.Clear();
        if (IcarusPlugin.FeaturesOff.Contains("origin-shift-poses") || Datum.origin == null) return;
        foreach (Aircraft aircraft in Object.FindObjectsOfType<Aircraft>())
        {
            if (aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey) continue;
            foreach (Rigidbody body in IcarusSystems.Parts(aircraft).Select(p => p.rb).Append(aircraft.rb)
                         .Where(b => b != null && b.interpolation != RigidbodyInterpolation.None).Distinct())
                held.Add((body, body.position, body.rotation));
        }
        originBefore = Datum.origin.position;
    }

    static void AfterOriginShift()
    {
        if (held.Count == 0 || Datum.origin == null) return;
        Vector3 shift = Datum.origin.position - originBefore;
        if (shift != Vector3.zero)
        {
            foreach (var (body, position, rotation) in held)
            {
                if (body == null) continue;
                body.position = position + shift;
                body.rotation = rotation;
            }
            IcarusPlugin.Log.Stage("origin-shift-poses", $"shift {shift.magnitude:0} m: {held.Count} interpolated bodies put back on their physics poses",
                everyOccurrence: true);
        }
        held.Clear();
    }
}
