using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// A stage line, once a second while an Icarus runs complex physics, with how far each tail part has turned against the
/// root (fuselage_mid) since its joints were made: the peak over that second about any axis, and its roll about the
/// fuselage axis then, with the load factor. Each part is its own rigidbody on FixedJoints there, and the joint solver lets
/// a part flex as far as its joints' conditioning allows; tests/scenarios/tail_rigidity.scenario.jsonc reads the line.
/// fin_skin is the fin the player sees; fin_spar is the structure inside it. A "joint-load" line beside it gives the three
/// joints that came nearest their break limits over that second, each as its peak load over its limit (force or torque,
/// whichever is nearer; a joint breaks at 1), which the full_stick scenarios read. A "wing-crank-<side>" line gives how far
/// the outer wing box's body has carried its tip (where its wingtip station was made) in the inner box's frame from where
/// the joints made it, the physical seam the two boxes meet at, its peak over that second in mm, and the peak of the
/// outer box's joint against its limit. WingSkinFollow.cs draws the seam shut while the boxes are jointed.
/// </summary>
static class TailFlex
{
    internal static readonly string[] Parts = { "fin_skin", "fin_spar", "rudder", "stabilator" };

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("tail-flex", typeof(Aircraft), nameof(Aircraft.SetComplexPhysics),
            postfix: AccessTools.Method(typeof(TailFlex), nameof(AfterSetComplexPhysics))),
    };

    static void AfterSetComplexPhysics(Aircraft __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tail-flex")) return;
        if (__instance.definition == null || __instance.definition.jsonKey != IcarusPlugin.JsonKey) return;
        AeroPart[] all = IcarusSystems.Parts(__instance);
        AeroPart?[] tail = Parts.Select(n => all.FirstOrDefault(p => p.name == n)).ToArray();
        if (tail.Any(p => p == null))
        {
            IcarusPlugin.Log.Error("tail flex: missing " + string.Join(", ", Parts.Where((_, i) => tail[i] == null)));
            return;
        }

        if (!__instance.TryGetComponent(out TailFlexProbe probe))
        {
            probe = __instance.gameObject.AddComponent<TailFlexProbe>();
        }

        probe.Begin(__instance, tail!, all);
    }
}

sealed class TailFlexProbe : MonoBehaviour
{
    const float ReportIntervalS = 1f;

    Aircraft aircraft = null!;
    AeroPart[] parts = null!;
    // Each part's rotation in the root's frame as the joints were made, and its peak turn and roll since the last line.
    Quaternion[] rest = null!;
    float[] peak = null!, roll = null!;
    float gPeak, reportAt;
    // Every joint the aircraft's parts made, and each one's peak load over its break limit since the last line.
    (string Name, PartJoint Joint)[] joints = null!;
    float[] jointPeak = null!;
    // Each side's outer wing box, the inner box it hangs on, its tip in the outer box's frame and its rest point in the
    // inner box's frame, and the tip's peak movement since the last line, mm.
    (string Side, AeroPart Outer, AeroPart Inner, Vector3 Tip, Vector3 Home)[] cranks = null!;
    float[] crankPeak = null!;

    internal void Begin(Aircraft owner, AeroPart[] tail, AeroPart[] all)
    {
        var found = new System.Collections.Generic.List<(string, AeroPart, AeroPart, Vector3, Vector3)>();
        foreach (string side in new[] { "L", "R" })
        {
            AeroPart? outer = all.FirstOrDefault(p => p.name == "wing_spar_outer_" + side);
            AeroPart? inner = all.FirstOrDefault(p => p.name == "wing_spar_" + side);
            Transform? tip = outer == null ? null : outer.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == "hardpoint_wingtip_" + side);
            if (outer != null && inner != null && tip != null)
                found.Add((side, outer, inner, outer.transform.InverseTransformPoint(tip.position), inner.transform.InverseTransformPoint(tip.position)));
        }
        cranks = found.ToArray();
        crankPeak = new float[cranks.Length];
        aircraft = owner;
        parts = tail;
        rest = parts.Select(p => Quaternion.Inverse(aircraft.rb.rotation) * p.rb.rotation).ToArray();
        joints = IcarusSystems.Parts(aircraft).SelectMany(p => p.Joints.Where(j => j.joint != null)
            .Select(j => ($"{p.name}->{(j.connectedPart != null ? j.connectedPart.name : "?")}", j))).ToArray();
        jointPeak = new float[joints.Length];
        peak = new float[parts.Length];
        roll = new float[parts.Length];
        gPeak = 0f;
        reportAt = Time.time + ReportIntervalS;
    }

    void FixedUpdate()
    {
        // Simple physics merges every part back onto the root, which leaves nothing to flex. With stage logging off
        // nothing reads the samples, so none are taken.
        if (!IcarusPlugin.Log.StageEnabled || aircraft == null || parts == null || parts[0].rb == aircraft.rb) return;
        for (int i = 0; i < parts.Length; i++)
        {
            if (parts[i] == null || parts[i].IsDetached()) continue;
            (Quaternion.Inverse(aircraft.rb.rotation) * parts[i].rb.rotation * Quaternion.Inverse(rest[i])).ToAngleAxis(out float angle, out Vector3 axis);
            if (angle > 180f) angle -= 360f;
            if (Mathf.Abs(angle) > peak[i])
            {
                peak[i] = Mathf.Abs(angle);
                roll[i] = angle * Vector3.Dot(axis, Vector3.forward);
            }
        }

        for (int i = 0; i < joints.Length; i++)
        {
            Joint? joint = joints[i].Joint.joint;
            if (joint == null || joint.breakForce <= 0f || joint.breakTorque <= 0f) continue;
            jointPeak[i] = Mathf.Max(jointPeak[i], joint.currentForce.magnitude / joint.breakForce, joint.currentTorque.magnitude / joint.breakTorque);
        }

        for (int i = 0; i < cranks.Length; i++)
        {
            var c = cranks[i];
            if (c.Outer == null || c.Inner == null || c.Outer.IsDetached() || c.Inner.IsDetached()) continue;
            crankPeak[i] = Mathf.Max(crankPeak[i], (c.Inner.transform.InverseTransformPoint(c.Outer.transform.TransformPoint(c.Tip)) - c.Home).magnitude * 1000f);
        }

        gPeak = Mathf.Max(gPeak, Mathf.Abs(aircraft.gForce));
        if (Time.time < reportAt) return;
        reportAt = Time.time + ReportIntervalS;
        string line = string.Join(", ", parts.Select((p, i) => p == null || p.IsDetached()
            ? $"{TailFlex.Parts[i]} detached"
            : $"{TailFlex.Parts[i]} {peak[i]:0.00} deg (roll {roll[i]:+0.00;-0.00})"));
        IcarusPlugin.Log.Stage("tail-flex", $"{line}; peaks over 1 s, up to {gPeak:0.0} g");
        string worst = string.Join(", ", Enumerable.Range(0, joints.Length).OrderByDescending(i => jointPeak[i]).Take(3)
            .Select(i => $"{joints[i].Name} {jointPeak[i]:0.00}"));
        IcarusPlugin.Log.Stage("joint-load", $"nearest break: {worst}; peaks over 1 s, up to {gPeak:0.0} g");
        for (int i = 0; i < cranks.Length; i++)
        {
            int j = System.Array.FindIndex(joints, x => x.Joint == cranks[i].Outer.Joints.FirstOrDefault());
            IcarusPlugin.Log.Stage("wing-crank-" + cranks[i].Side,
                $"tip_mm={crankPeak[i]:0.00} joint={(j < 0 ? float.NaN : jointPeak[j]):0.00}; peaks over 1 s, up to {gPeak:0.0} g");
        }
        System.Array.Clear(crankPeak, 0, crankPeak.Length);
        System.Array.Clear(jointPeak, 0, jointPeak.Length);
        System.Array.Clear(peak, 0, peak.Length);
        System.Array.Clear(roll, 0, roll.Length);
        gPeak = 0f;
    }
}
