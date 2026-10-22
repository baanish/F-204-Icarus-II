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
            var donor = Load<GameObject>(DonorPrefab);
            var formationOff = donor.GetComponentsInChildren<MeshRenderer>(true)
                .First(r => r.name.StartsWith("slimelights", StringComparison.Ordinal)).sharedMaterial;
            foreach (var side in new[] { "L", "R" })
            {
                foreach (var formation in new[] { false, true })
                {
                    var name = formation ? "light_formation_" + side : "navlight_" + side;
                    var parent = b.Parts[(formation ? "skin_mid_" : "wing_skin_") + side].transform;
                    var lamp = parent.Find(name);
                    if (lamp == null) { p.Add(name + " is not on its skin part"); continue; }
                    var renderer = lamp.GetComponent<MeshRenderer>();
                    var mesh = lamp.GetComponent<MeshFilter>()?.sharedMesh;
                    if (renderer == null || mesh == null) { p.Add(name + " has no mesh renderer"); continue; }
                    var entries = Enumerable.Range(0, navLights.arraySize).Select(navLights.GetArrayElementAtIndex)
                        .Where(e => e.FindPropertyRelative("renderer").objectReferenceValue == renderer).ToArray();
                    if (entries.Length != 1) { p.Add($"{name} has {entries.Length} nav entries"); continue; }
                    var entry = entries[0];
                    if (entry.FindPropertyRelative("part").objectReferenceValue != b.Part(parent.name))
                        p.Add(name + " is bound to the wrong part");
                    var triangles = mesh.triangles.Length / 3;
                    if (formation)
                    {
                        if (mesh != b.Meshes[name].Render || triangles < 2 || triangles > 8)
                            p.Add(name + " must use its generated 2 to 8 triangle strip");
                        if (renderer.sharedMaterial != formationOff || entry.FindPropertyRelative("litMaterial").objectReferenceValue != b.Donor.FormationLit
                            || entry.FindPropertyRelative("controlState").intValue != b.Donor.FormationState)
                            p.Add(name + " lost the Revoker's formation materials or switching");
                        if (entry.FindPropertyRelative("gear").objectReferenceValue != null || entry.FindPropertyRelative("objects").arraySize != 0
                            || lamp.childCount != 0 || lamp.GetComponents<Collider>().Length != 0)
                            p.Add(name + " must be a bare strip without gear gating, effect objects or colliders");
                        if (Vector3.Distance(lamp.position, b.Blockout.Local(name)) > 0.001f)
                            p.Add(name + " moved off its generated skin position");
                    }
                    else
                    {
                        var stock = donor.GetComponentsInChildren<MeshFilter>(true).Single(f => f.name == name);
                        if (mesh != stock.sharedMesh || triangles != 14) p.Add(name + " must reference the stock 14 triangle lens");
                        if (Quaternion.Angle(lamp.rotation, Quaternion.identity) > 0.01f || Vector3.Distance(lamp.lossyScale, Vector3.one) > 0.0001f)
                            p.Add(name + " must keep the stock lens orientation and size");
                        if (Vector3.Distance(renderer.bounds.center, b.Blockout.Local("light_nav_" + side)) > 0.001f)
                            p.Add(name + " moved off its upper-tip anchor");
                        var wing = b.Parts["wing_skin_" + side].GetComponent<MeshRenderer>().bounds;
                        if (Mathf.Max(Mathf.Abs(renderer.bounds.min.x), Mathf.Abs(renderer.bounds.max.x)) >= Mathf.Max(Mathf.Abs(wing.min.x), Mathf.Abs(wing.max.x)))
                            p.Add(name + " reaches the tip face");
                    }
                }
            }
            if (b.Root.GetComponentsInChildren<Transform>(true).Any(t => t.name.StartsWith("light_beacon_", StringComparison.Ordinal)
                || t.name.StartsWith("antenna_", StringComparison.Ordinal))) p.Add("beacon or separate antenna remains");
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
            return $"{navLights.arraySize} nav lights with parts, stock 14 triangle lenses, generated formation strips with stock switching, {effects.Length} effects and markers placed, no beacons, separate antennas or bay audio";
        }
    }
}
