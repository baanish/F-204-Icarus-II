using System;
using System.Collections.Generic;
using System.Reflection.Emit;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

static class BulletHitLog
{
    static ConfigEntry<bool> enabled = null!;

    internal static void Install(ConfigFile config) => enabled = config.Bind("Diagnostics", "BulletHits", false,
        "Log every BulletSim linecast hit on an Icarus, including visual-only bullets; requires StageLogging. Disable after the gun test.");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("bullet-hit-log", typeof(BulletSim.Bullet), nameof(BulletSim.Bullet.TrajectoryTrace),
            transpiler: AccessTools.Method(typeof(BulletHitLog), nameof(TraceHits))),
    };

    static IEnumerable<CodeInstruction> TraceHits(IEnumerable<CodeInstruction> instructions)
    {
        var linecast = AccessTools.Method(typeof(Physics), nameof(Physics.Linecast),
            new[] { typeof(Vector3), typeof(Vector3), typeof(RaycastHit).MakeByRefType(), typeof(int) });
        int count = 0;
        foreach (var instruction in instructions)
        {
            if (instruction.Calls(linecast))
            {
                instruction.opcode = OpCodes.Call;
                instruction.operand = AccessTools.Method(typeof(BulletHitLog), nameof(Linecast));
                count++;
            }
            yield return instruction;
        }
        if (count != 2) throw new InvalidOperationException($"BulletSim has {count} linecasts, expected 2; hit logging not installed");
    }

    // Observe the actual query result, retaining the game's mask, trigger policy and hit ordering.
    static bool Linecast(Vector3 start, Vector3 end, out RaycastHit hit, int mask)
    {
        bool found = Physics.Linecast(start, end, out hit, mask);
        if (!found || !enabled.Value || !IcarusPlugin.Log.StageEnabled) return found;
        Collider collider = hit.collider;
        UnitPart part = collider.GetComponentInParent<UnitPart>();
        if (part == null || part.GetUnit() is not Aircraft aircraft || aircraft.definition == null
            || aircraft.definition.jsonKey != IcarusPlugin.JsonKey) return found;
        IDamageable damageable = collider.GetComponent<IDamageable>();
        IcarusPlugin.Log.Stage("bullet-hit",
            $"aircraft={aircraft.UniqueName} part={part.name} collider={collider.name}/{collider.GetType().Name}#{collider.GetInstanceID()} layer={collider.gameObject.layer} damageable={(damageable != null ? "true" : "false")} receiver={damageable?.GetType().Name ?? "none"} trigger={collider.isTrigger} distance={hit.distance:F3}", true);
        return found;
    }
}
