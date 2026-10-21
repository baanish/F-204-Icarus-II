using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        private static string CheckEffects(Build b, List<string> p)
        {
            var navLights = Prop(new SerializedObject(b.Root.GetComponent(GameType("NavLights"))), "navLights");
            for (var i = 0; i < navLights.arraySize; i++)
            {
                var entry = navLights.GetArrayElementAtIndex(i);
                var renderer = entry.FindPropertyRelative("renderer").objectReferenceValue as Component;
                if (renderer == null) p.Add($"nav light {i} has no renderer");
                if (entry.FindPropertyRelative("part").objectReferenceValue == null) p.Add($"nav light {i} ({(renderer != null ? renderer.name : "?")}) has no part");
            }
            foreach (var global in All(b, "SetGlobalParticles"))
                if (GetList(Prop(new SerializedObject(global), "systems")).Any(s => s == null)) p.Add(global.name + ": a null particle system");
            foreach (var vapour in All(b, "VaporEffect"))
            {
                var emitters = Prop(new SerializedObject(vapour), "emitters");
                var it = emitters.Copy();
                var end = emitters.GetEndProperty();
                while (it.Next(true) && !SerializedProperty.EqualContents(it, end))
                    if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue == null && it.objectReferenceInstanceIDValue != 0) p.Add("a dead vapour emitter");
            }
            var effects = new[] { "vaporCone", "downwash", "contactSparks", "wingVapor_L", "wingVapor_R", "wingtipvortex_L", "wingtipvortex_R", "navlight_L", "navlight_R", "light_formation_L", "light_formation_R",
                "flareEjectorL", "flareEjectorR", "heat_haze", "afterburner_flame", "afterburner_nozzle_glow", "gearlight_F", "ladder" };
            foreach (var name in effects)
            {
                var found = b.Root.GetComponentsInChildren<Transform>(true).Where(t => t.name == name).ToArray();
                if (found.Length != 1) p.Add($"{found.Length} objects named {name}");
                else if (!b.Placed.Contains(found[0])) p.Add(name + " left at its Revoker offset");
            }
            var bayAudio = b.Root.GetComponentsInChildren<AudioSource>(true).Where(a => a.transform.name.StartsWith("weaponbay", StringComparison.Ordinal)).ToArray();
            if (bayAudio.Length > 0) p.Add("bay audio remains");
            return $"{navLights.arraySize} nav lights with parts, {effects.Length} effects and markers placed on the Icarus, no bay audio";
        }
    }
}
