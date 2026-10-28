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
/// outer box's joint against its limit. WingSkinFollow.cs draws the seam shut while the boxes are jointed. A "thrust-line"
/// line gives the nozzle's body's peak turn against the root over that second, exact for small turns: the JetNozzle rides
/// that body, so this is how far the thrust line has turned off its authored axis before vectoring. A "panel-drift" line
/// gives each fuselage skin piece's peak movement over that second against the part it hangs on, from where the joints
/// made it: the most any corner of its mesh's bounds moved in that part's frame, in mm, with ulp_mm, the float32 spacing
/// of world positions where the jet is, below which no movement between two bodies can be measured (or drawn). A light
/// panel on a heavy core is the case the joint solver holds worst, and a drifted panel opens a gap at its seams.
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
    AeroPart? nozzle;
    Quaternion nozzleRest;
    float nozzlePeak;
    // Each fuselage skin piece, the part it hangs on, its mesh's bounds corners in its own frame and their rest points in
    // that part's frame, and its peak movement since the last line, mm.
    (AeroPart Piece, AeroPart On, Vector3[] Corners, Vector3[] Home)[] panels = null!;
    float[] panelPeak = null!;

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
        nozzle = all.FirstOrDefault(p => p.name == "nozzle");
        if (nozzle != null) nozzleRest = Quaternion.Inverse(aircraft.rb.rotation) * nozzle.rb.rotation;
        nozzlePeak = 0f;
        panels = all.Where(p => (p.name.StartsWith("skin_") || p.name.StartsWith("dorsal_cover")) && p.Joints.Length > 0 &&
                                p.Joints[0].connectedPart is AeroPart && p.GetComponent<MeshFilter>() != null)
            .Select(p =>
            {
                var on = (AeroPart)p.Joints[0].connectedPart;
                Bounds b = p.GetComponent<MeshFilter>().sharedMesh.bounds;
                Vector3[] corners = Enumerable.Range(0, 8).Select(i => b.center + Vector3.Scale(b.extents,
                    new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1))).ToArray();
                return (p, on, corners, corners.Select(c => on.transform.InverseTransformPoint(p.transform.TransformPoint(c))).ToArray());
            }).ToArray();
        panelPeak = new float[panels.Length];
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

        if (nozzle != null && !nozzle.IsDetached())
        {
            Quaternion d = Quaternion.Inverse(nozzleRest) * Quaternion.Inverse(aircraft.rb.rotation) * nozzle.rb.rotation;
            nozzlePeak = Mathf.Max(nozzlePeak, 2f * Mathf.Atan2(new Vector3(d.x, d.y, d.z).magnitude, Mathf.Abs(d.w)) * Mathf.Rad2Deg);
        }

        for (int i = 0; i < panels.Length; i++)
        {
            var (piece, on, corners, home) = panels[i];
            if (piece == null || on == null || piece.IsDetached() || on.IsDetached()) continue;
            for (int k = 0; k < corners.Length; k++)
                panelPeak[i] = Mathf.Max(panelPeak[i], (on.transform.InverseTransformPoint(piece.transform.TransformPoint(corners[k])) - home[k]).magnitude * 1000f);
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
        if (nozzle != null)
            IcarusPlugin.Log.Stage("thrust-line", nozzle.IsDetached() ? "nozzle detached" : $"turn_deg={nozzlePeak:0.000}; peaks over 1 s, up to {gPeak:0.0} g");
        nozzlePeak = 0f;
        if (panels.Length > 0)
        {
            int worstPanel = System.Array.IndexOf(panelPeak, panelPeak.Max());
            Vector3 at = aircraft.rb.position;
            float far = Mathf.Max(Mathf.Abs(at.x), Mathf.Abs(at.y), Mathf.Abs(at.z));
            float ulp = (System.BitConverter.Int32BitsToSingle(System.BitConverter.SingleToInt32Bits(far) + 1) - far) * 1000f;
            IcarusPlugin.Log.Stage("panel-drift", $"worst {panels[worstPanel].Piece.name} {panelPeak[worstPanel]:0.00} mm ulp_mm={ulp:0.0000}; " +
                string.Join(", ", panels.Select((x, i) => $"{x.Piece.name} {panelPeak[i]:0.00}")) + $"; peaks over 1 s, up to {gPeak:0.0} g");
        }
        System.Array.Clear(panelPeak, 0, panelPeak.Length);
        System.Array.Clear(jointPeak, 0, jointPeak.Length);
        System.Array.Clear(peak, 0, peak.Length);
        System.Array.Clear(roll, 0, roll.Length);
        gPeak = 0f;
    }
}
