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
        new("part-contact-log", typeof(UnitPart), "TakeDamage",
            prefix: AccessTools.Method(typeof(PartContactLog), nameof(BeforeTakeDamage))),
    };

    static bool IsIcarus(UnitPart part) =>
        part.parentUnit is Aircraft aircraft && aircraft.definition != null && aircraft.definition.jsonKey == IcarusPlugin.JsonKey;

    static void BeforeCollision(AeroPart __instance, Collision collision)
    {
        if (IcarusPlugin.FeaturesOff.Contains("part-contact-log") || !IsIcarus(__instance)) return;
        UnitPart? other = collision.collider.GetComponentInParent<UnitPart>();
        bool self = other != null && other.parentUnit == __instance.parentUnit;
        string with = other != null ? other.name : collision.collider.name;
        // The g AeroPart.OnCollisionEnter weighs against impactDamage.threshold. Contacts that carry load get their own key, so
        // the stage log's per-key interval can't hide one behind the resting contacts the same pair logs every frame.
        float g = collision.impulse.magnitude / Time.fixedDeltaTime / (__instance.rb.mass * 9.81f);
        IcarusPlugin.Log.Stage($"contact {__instance.name}/{with}{(g >= 1f ? " loaded" : "")}",
            $"{(self ? "self " : "")}impulse {collision.impulse.magnitude:0.###} N s ({g:0.0} g), relative {collision.relativeVelocity.magnitude:0.0} m/s, part mass {__instance.rb.mass:0} kg");
    }

    static void BeforeTakeDamage(UnitPart __instance, float pierceDamage, float blastDamage, float fireDamage, float impactDamage)
    {
        if (IcarusPlugin.FeaturesOff.Contains("part-contact-log") || !IsIcarus(__instance)) return;
        var caller = new System.Diagnostics.StackTrace(2, false).GetFrame(0)?.GetMethod();
        IcarusPlugin.Log.Stage($"damage {__instance.name}",
            $"pierce {pierceDamage:0.0}, blast {blastDamage:0.0}, fire {fireDamage:0.0}, impact {impactDamage:0.0}, hp {__instance.hitPoints:0}, from {caller?.DeclaringType?.Name}.{caller?.Name}");
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
