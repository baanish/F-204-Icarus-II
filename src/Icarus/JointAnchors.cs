using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// AeroPart.CreateJoints sets each FixedJoint's anchor to the world offset anchor.position - rb.position, but
/// Joint.anchor is in the body's local space, so on a part rotated in the aircraft, or an aircraft created at any heading,
/// the anchor lands somewhere else and the joint's break forces are measured about the wrong point. After the game
/// creates an Icarus part's joints, each anchor is set to its marker in the part's own space.
/// </summary>
static class JointAnchors
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("joint-anchors", typeof(AeroPart), nameof(AeroPart.CreateJoints),
            postfix: AccessTools.Method(typeof(JointAnchors), nameof(AfterCreateJoints))),
    };

    static void AfterCreateJoints(AeroPart __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("joint-anchors")) return;
        if (!(__instance.parentUnit is Aircraft aircraft) || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey)
        {
            return;
        }

        foreach (PartJoint joint in __instance.Joints)
        {
            if (joint.anchor != null && joint.joint != null)
            {
                joint.joint.anchor = __instance.transform.InverseTransformPoint(joint.anchor.position);
            }
        }
    }
}
