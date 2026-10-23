using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // BulletSim linecasts every layer but 13 (ExclusionZones), triggers included (the game ships queriesHitTriggers on),
        // and takes the damage receiver from the hit collider's own object, so an enabled collider without one stops a round
        // that would have hit the hull. Layer 13 is no way out: Autopilot's terrain checks hit it. LandingGear enables its
        // gear colliders only when a wheel breaks off.
        private static string CheckBulletColliders(Build b, List<string> problems)
        {
            var gear = new HashSet<Collider>(All(b, "LandingGear").Select(c => GetRef(c, "gearCollider")).OfType<Collider>());
            var hulls = 0;
            foreach (var collider in b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled))
            {
                if (collider.GetComponent(GameType("IDamageable")) != null)
                    hulls++;
                else if (!gear.Contains(collider))
                    problems.Add($"{PathOf(collider.transform, b.Root.transform)} {collider.GetType().Name} layer {collider.gameObject.layer} trigger {collider.isTrigger}: no same-object IDamageable");
            }
            return $"{hulls} enabled colliders, each with a damage receiver, and {gear.Count} gear colliders";
        }
    }
}
