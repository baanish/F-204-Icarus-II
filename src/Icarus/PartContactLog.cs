using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Stage lines for what tears an Icarus apart: each collision an Icarus part takes (with the other collider's part, and
/// "self" when that part is on the same aircraft) and each joint that breaks, with every joint's limits and load on that
/// part. A part tree this deep only holds together while its parts don't collide with one another and its joints carry
/// what the airframe does, so these name the pair or the joint when it doesn't.
/// </summary>
static class PartContactLog
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("part-contact-log", typeof(AeroPart), "OnCollisionEnter",
            prefix: AccessTools.Method(typeof(PartContactLog), nameof(BeforeCollision))),
        new("part-contact-log", typeof(UnitPart), "OnJointBreak",
            prefix: AccessTools.Method(typeof(PartContactLog), nameof(BeforeJointBreak))),
    };

    static bool IsIcarus(UnitPart part) =>
        part.parentUnit is Aircraft aircraft && aircraft.definition != null && aircraft.definition.jsonKey == IcarusPlugin.JsonKey;

    static void BeforeCollision(AeroPart __instance, Collision collision)
    {
        if (IcarusPlugin.FeaturesOff.Contains("part-contact-log") || !IsIcarus(__instance)) return;
        UnitPart? other = collision.collider.GetComponentInParent<UnitPart>();
        bool self = other != null && other.parentUnit == __instance.parentUnit;
        string with = other != null ? other.name : collision.collider.name;
        IcarusPlugin.Log.Stage($"contact {__instance.name}/{with}",
            $"{(self ? "self " : "")}impulse {collision.impulse.magnitude:0} N s, relative {collision.relativeVelocity.magnitude:0.0} m/s, part mass {__instance.rb.mass:0} kg");
    }

    static void BeforeJointBreak(UnitPart __instance, float breakForce)
    {
        if (IcarusPlugin.FeaturesOff.Contains("part-contact-log") || !IsIcarus(__instance)) return;
        var joints = new System.Text.StringBuilder();
        if (__instance is AeroPart aero)
        {
            foreach (PartJoint joint in aero.Joints)
            {
                if (joint.joint == null) continue;
                joints.Append($"; to {(joint.connectedPart != null ? joint.connectedPart.name : "?")}: limits {joint.joint.breakForce:0} N, {joint.joint.breakTorque:0} N m, " +
                    $"load {joint.joint.currentForce.magnitude:0} N, {joint.joint.currentTorque.magnitude:0} N m");
            }
        }
        IcarusPlugin.Log.Stage($"joint-break {__instance.name}", $"joint broke at {breakForce:0}, part hp {__instance.hitPoints:0}, rb {__instance.rb.mass:0} kg{joints}");
    }
}
