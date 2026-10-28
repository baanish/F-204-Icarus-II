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
            // art/blender/lights.py: two forward lenses of 16 triangles, each in a 24 triangle rim; a fin strip of 8 in 20.
            var lensTriangles = new Dictionary<string, (int Lens, int All)> { ["light_formation_"] = (32, 80), ["light_fin_"] = (8, 28) };
            foreach (var side in new[] { "L", "R" })
            {
                var fairing = b.Parts[b.Blockout.Parts["light_nav_mount_" + side].BlenderParent].transform.Find("light_nav_mount_" + side);
                if (fairing == null || fairing.GetComponent<MeshRenderer>()?.sharedMaterial != b.Skin
                    || OneSidedCount(fairing) != 44)
                    p.Add("nav fairings must have 44 triangles per wing and share its livery material");
                foreach (var (name, owner) in FormationLenses(side).Concat(NavLenses(side).Select(l => (l.Name, b.Blockout.Parts[l.Anchor].BlenderParent))))
                {
                    var formation = !name.StartsWith("navlight_", StringComparison.Ordinal);
                    var parent = b.Parts[owner].transform;
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
                        var expected = lensTriangles[name.Substring(0, name.Length - side.Length)];
                        if (mesh != b.Meshes[name].Render || triangles != expected.All || mesh.subMeshCount != 2 || mesh.GetSubMesh(0).indexCount != 3 * expected.Lens)
                            p.Add($"{name} must use its generated lenses (submesh 0, {expected.Lens} triangles) and rims ({expected.All - expected.Lens} triangles)");
                        if (renderer.sharedMaterials.Length != 2 || renderer.sharedMaterials[1] != b.Meshes[name].Materials[1])
                            p.Add(name + " lost its rim material");
                        if (renderer.sharedMaterial != formationOff || entry.FindPropertyRelative("litMaterial").objectReferenceValue != b.Donor.FormationLit
                            || entry.FindPropertyRelative("controlState").intValue != b.Donor.FormationState)
                            p.Add(name + " lost the Revoker's formation materials or switching");
                        if (entry.FindPropertyRelative("gear").objectReferenceValue != null || entry.FindPropertyRelative("objects").arraySize != 0
                            || lamp.childCount != 0 || lamp.GetComponents<Collider>().Length != 0)
                            p.Add(name + " must be bare lenses without gear gating, effect objects or colliders");
                        if (Vector3.Distance(lamp.position, b.Blockout.Local(name)) > 0.001f)
                            p.Add(name + " moved off its generated skin position");
                    }
                    else
                    {
                        var stock = donor.GetComponentsInChildren<MeshFilter>(true).Single(f => f.name == "navlight_" + side);
                        var anchor = NavLenses(side).Single(l => l.Name == name).Anchor;
                        if (mesh != stock.sharedMesh || triangles != 14) p.Add(name + " must reference the stock 14 triangle lens");
                        if (Quaternion.Angle(lamp.rotation, b.Blockout.Rotation(anchor)) > 0.01f || Vector3.Distance(lamp.lossyScale, Vector3.one) > 0.0001f)
                            p.Add(name + " must keep its generated orientation and stock size");
                        if (Vector3.Distance(renderer.bounds.center, b.Blockout.Local(anchor)) > 0.001f)
                            p.Add(name + " moved off its tip anchor");
                        var stockEntry = NavLightEntry(new SerializedObject(donor.GetComponent(GameType("NavLights"))), stock.GetComponent<Renderer>());
                        if (renderer.sharedMaterial != stock.GetComponent<Renderer>().sharedMaterial
                            || entry.FindPropertyRelative("litMaterial").objectReferenceValue != stockEntry.FindPropertyRelative("litMaterial").objectReferenceValue
                            || entry.FindPropertyRelative("controlState").intValue != stockEntry.FindPropertyRelative("controlState").intValue
                            || entry.FindPropertyRelative("gear").objectReferenceValue != null)
                            p.Add(name + " lost the stock nav materials or switching");
                        var effectObjects = entry.FindPropertyRelative("objects");
                        if (effectObjects.arraySize != stockEntry.FindPropertyRelative("objects").arraySize
                            || Enumerable.Range(0, effectObjects.arraySize).Any(i =>
                                !(effectObjects.GetArrayElementAtIndex(i).objectReferenceValue is GameObject effect) || !effect.transform.IsChildOf(lamp)))
                            p.Add(name + " lost its own switched stock effects");
                        var wing = BoundsOf(FamilyVertices(b, "wing_skin_" + side));
                        if (Mathf.Max(Mathf.Abs(renderer.bounds.min.x), Mathf.Abs(renderer.bounds.max.x)) >= Mathf.Max(Mathf.Abs(wing.min.x), Mathf.Abs(wing.max.x)))
                            p.Add(name + " reaches the tip face");
                    }
                }
            }
            var stabilatorHinge = b.Parts["stabilator"].transform.Find("stabilator_hinge");
            var aft = stabilatorHinge.Find("navlight_aft");
            var aftRenderer = aft != null ? aft.GetComponent<MeshRenderer>() : null;
            var aftMesh = aft != null ? aft.GetComponent<MeshFilter>()?.sharedMesh : null;
            if (aftRenderer == null || aftMesh != b.Meshes["light_nav_aft"].Render || aftMesh.triangles.Length / 3 != 24)
                p.Add("rear nav light must use the generated 24 triangle dome on the stabilator's turning hinge");
            else
            {
                var entries = Enumerable.Range(0, navLights.arraySize).Select(navLights.GetArrayElementAtIndex)
                    .Where(e => e.FindPropertyRelative("renderer").objectReferenceValue == aftRenderer).ToArray();
                if (entries.Length != 1) p.Add("rear nav light must have exactly one switched entry");
                else
                {
                    var entry = entries[0];
                    var wing = NavLightEntry(new SerializedObject(b.Root.GetComponent(GameType("NavLights"))),
                        b.Parts[b.Blockout.Parts["light_nav_L"].BlenderParent].transform.Find("navlight_L").GetComponent<Renderer>());
                    if (entry.FindPropertyRelative("part").objectReferenceValue != b.Part("stabilator")
                        || entry.FindPropertyRelative("gear").objectReferenceValue != null
                        || entry.FindPropertyRelative("controlState").intValue != wing.FindPropertyRelative("controlState").intValue
                        || entry.FindPropertyRelative("litMaterial").objectReferenceValue != Load<Material>(Stock + "Material/gearLight_PLACEHOLDER.mat")
                        || aftRenderer.sharedMaterial != Load<Material>(Stock + "Material/Matte_black_PLACEHOLDER.mat"))
                        p.Add("rear nav light lost its stabilator binding, stock white material or wingtip switching");
                    var objects = entry.FindPropertyRelative("objects");
                    if (objects.arraySize != 1 || !(objects.GetArrayElementAtIndex(0).objectReferenceValue is GameObject effect)
                        || !effect.transform.IsChildOf(aft))
                        p.Add("rear nav light lost its own switched stock tail effect");
                }
                if (Vector3.Distance(aft.position, b.Blockout.Local("light_nav_aft")) > 0.001f
                    || Quaternion.Angle(aft.rotation, b.Blockout.Rotation("light_nav_aft")) > 0.01f)
                    p.Add("rear nav light moved off its generated trailing-edge position");
            }
            var tailFairing = stabilatorHinge.Find("light_tail_fairing");
            if (tailFairing == null || tailFairing.GetComponent<MeshRenderer>()?.sharedMaterial != b.Skin
                || OneSidedCount(tailFairing) != 32)
                p.Add("rear nav fairing must use 32 triangles and stabilator paint, on the stabilator's turning hinge");
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
            var effects = new[] { "vaporCone", "downwash", "contactSparks", "wingVapor_L", "wingVapor_R", "wingtipvortex_L", "wingtipvortex_R", "navlight_L", "navlight_R", "navlight_lower_L", "navlight_lower_R", "navlight_aft", "light_formation_L", "light_formation_R", "light_fin_L", "light_fin_R",
                "flareEjectorL", "flareEjectorR", "heat_haze", "afterburner_flame", "afterburner_nozzle_glow", "gearlight_F", "ladder" };
            foreach (var name in effects)
            {
                var found = b.Root.GetComponentsInChildren<Transform>(true).Where(t => t.name == name).ToArray();
                if (found.Length != 1) p.Add($"{found.Length} objects named {name}");
                else if (!b.Placed.Contains(found[0])) p.Add(name + " left at its Revoker offset");
            }
            var bayAudio = b.Root.GetComponentsInChildren<AudioSource>(true).Where(a => a.transform.name.StartsWith("weaponbay", StringComparison.Ordinal)).ToArray();
            if (bayAudio.Length > 0) p.Add("bay audio remains");
            return $"{navLights.arraySize} nav lights with parts, stock 14 triangle wing lenses, white rear dome and generated formation lenses with stock switching, {effects.Length} effects and markers placed, no beacons, separate antennas or bay audio";
        }
    }
}
