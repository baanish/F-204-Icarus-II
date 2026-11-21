using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // A blast traces one frag at each collider in its reach, aimed at the collider's transform, and harms that collider
        // only where the trace meets it (DamageEffects.BlastFrag and FragTrace): a part whose origin lies inside one of its
        // own colliders is met from every side. These parts' origins stand outside: the canopy's is the sill hinge its hood
        // turns about (art/blender/hulls.py AIM_OUTSIDE). A part listed here whose origin comes inside fails, so the list
        // stays the parts it names. A part whose colliders are all triggers (the gear legs) is not judged: its trigger is
        // at its hinge, and no blast damage was designed through it.
        private static readonly string[] AimOutside = { "canopy" };
        // One hull each, so "inside one of its colliders" means inside the part: the root and the intakes, the outside chunks
        // cut from its fairing (art/blender/parts.py split_intakes), are single hulls by design.
        private static readonly string[] SingleHull = { RootPart, "intake_duct_L", "intake_duct_R" };
        private const float AimSlack = 0.001f;
        // A tank's fire spawns at its transform (FuelTank.IgnitionEffects, localPosition zero), so every tank keeps this far
        // from the pilot's eye and out of the cockpit (art/blender/parts.py FIRE_EYE_CLEAR).
        private const float FireEyeClear = 1.5f;

        // A collider a blast can meet: enabled, solid, and with a mesh if it is a MeshCollider.
        private static bool Usable(Collider c) => c.enabled && !c.isTrigger && !(c is MeshCollider m && m.sharedMesh == null);

        private static string CheckAimAndFires(Build b, List<string> p)
        {
            Physics.SyncTransforms();
            var judged = 0;
            var several = new List<string>();
            foreach (var part in All(b, "AeroPart").OrderBy(a => a.gameObject.name, System.StringComparer.Ordinal))
            {
                var cols = part.GetComponents<Collider>().Where(Usable).ToArray();
                if (cols.Length == 0)
                    continue;
                var at = part.transform.position;
                var inside = cols.Any(c => (c.ClosestPoint(at) - at).magnitude <= AimSlack);
                var listed = AimOutside.Contains(part.gameObject.name);
                if (inside == listed)
                    p.Add($"{part.gameObject.name}'s origin is {(inside ? "inside one of its colliders, off the exception list now" : "outside all its colliders")}");
                judged++;
                if (cols.Length > 1)
                    several.Add($"{part.gameObject.name} {cols.Length} colliders");
            }
            foreach (var name in SingleHull)
            {
                var count = b.Parts.TryGetValue(name, out var go) ? go.GetComponents<Collider>().Count(Usable) : 0;
                if (count != 1) p.Add($"{name} has {count} usable colliders (enabled, not a trigger, with a mesh), one by design");
            }
            var eye = ((Transform)GetRef(b.Aircraft, "cockpitViewPoint")).position;
            var room = b.Visuals.TryGetValue("cockpit_interior", out var interior) ? interior.GetComponent<MeshRenderer>().bounds : default;
            var tanks = new List<string>();
            foreach (var tank in All(b, "FuelTank"))
            {
                var at = tank.transform.position;
                var d = Vector3.Distance(at, eye);
                tanks.Add($"{tank.gameObject.name} {d:F2} m");
                if (d < FireEyeClear) p.Add($"{tank.gameObject.name}'s tank is {d:F2} m from the pilot's eye, under {FireEyeClear}");
                if (room.size != Vector3.zero && room.Contains(at)) p.Add($"{tank.gameObject.name}'s tank is inside the cockpit");
            }
            if (room.size == Vector3.zero) p.Add("no cockpit_interior to judge the tanks against");
            return $"{judged} parts' origins inside one of their own colliders but {string.Join(", ", AimOutside)} ({string.Join(", ", several)}); one hull each for {string.Join(", ", SingleHull)}; " +
                   $"tank fires from the pilot's eye: {string.Join(", ", tanks)}";
        }
    }
}
