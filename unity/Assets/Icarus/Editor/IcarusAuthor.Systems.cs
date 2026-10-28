using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The FS-12 Revoker's body width with its intakes, which its vapour cone is sized to (estimated from its art).
        private const float RevokerBodyWidth = 2.5f;
        // TargetCam renders from 2 m out: its mounts sit 2.5 m clear of every mesh (Centurion's measured margin).
        private const float CameraClearance = 2.5f;

        // art/blender/lights.py: one side's generated formation lenses and the skin part each rides on.
        private static (string Name, string Owner)[] FormationLenses(string side) =>
            new[] { ("light_formation_" + side, "skin_forward_" + side), ("light_fin_" + side, "fin_skin") };

        private static (string Name, string Anchor)[] NavLenses(string side) =>
            new[] { ("navlight_" + side, "light_nav_" + side), ("navlight_lower_" + side, "light_nav_lower_" + side) };

        private static void PlaceSystems(Build b)
        {
            var root = b.Root.transform;
            var renderers = b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.gameObject.layer != 3).ToArray();
            var noseTip = b.Parts["radome"].GetComponent<MeshRenderer>().bounds.max.z;
            var tailEnd = renderers.Min(r => r.bounds.min.z);
            var belly = new[] { RootPart, "fuselage_forward", "fuselage_aft" }.Concat(FamilyParts(b, "skin_mid_L")).Concat(FamilyParts(b, "skin_mid_R"))
                .Min(n => b.Parts[n].GetComponent<MeshRenderer>().bounds.min.y);

            // Radar on the radome's Revoker nose, bound to the radar tray, whose loss is the radar's (R13).
            var radar = b.Parts["radome"].GetComponent(GameType("Radar"));
            Set(radar, "part", b.Part("radar_tray"));

            var targetCam = new SerializedObject(b.Parts["radome"].GetComponent(GameType("TargetCam")));
            var forward = (Transform)Prop(targetCam, "camMountForward").objectReferenceValue;
            var rear = (Transform)Prop(targetCam, "camMountRear").objectReferenceValue;
            var landing = (Transform)Prop(targetCam, "camMountLanding").objectReferenceValue;
            forward.position = new Vector3(0f, b.Parts["radome"].transform.position.y - 0.3f, noseTip + CameraClearance);
            rear.position = new Vector3(0f, b.Visuals["nozzle_vector"].position.y, tailEnd - CameraClearance);
            landing.position = new Vector3(0f, belly - 0.3f, b.Parts["gear_leg_L"].transform.position.z - 2.5f);
            b.Placed.UnionWith(new[] { forward, rear, landing });

            // Flare dispensers on the aft fuselage's lower sides, throwing outboard, down and aft.
            var ejector = new SerializedObject(b.Root.GetComponent(GameType("FlareEjector")));
            var points = Prop(ejector, "ejectionPoints");
            for (var i = 0; i < points.arraySize; i++)
            {
                var point = points.GetArrayElementAtIndex(i);
                var t = (Transform)point.FindPropertyRelative("transform").objectReferenceValue;
                var side = t.name.EndsWith("L", StringComparison.Ordinal) ? -1f : 1f;
                var skin = BoundsOf(FamilyVertices(b, side < 0 ? "skin_aft_L" : "skin_aft_R"));
                t.SetParent(b.Parts["fuselage_aft"].transform, true);
                t.SetPositionAndRotation(new Vector3(side < 0 ? skin.min.x : skin.max.x, skin.min.y + 0.15f, skin.center.z),
                    Quaternion.LookRotation(new Vector3(side * 0.8f, -0.55f, -0.25f), Vector3.up));
                point.FindPropertyRelative("part").objectReferenceValue = b.Part("fuselage_aft");
                b.Placed.Add(t);
            }
            ejector.ApplyModifiedPropertiesWithoutUndo();

            // Keep the stock nav lenses by reference. Formation lenses and fin strips use our surface-following mesh,
            // the Revoker's off material and switching on the lens (slot 0, the one NavLights swaps) and the rim's own
            // slot, so the wing, skin and fin parts carry their own lights away.
            var navLights = new SerializedObject(b.Root.GetComponent(GameType("NavLights")));
            var formationOff = Load<GameObject>(DonorPrefab).GetComponentsInChildren<MeshRenderer>(true)
                .First(r => r.name.StartsWith("slimelights", StringComparison.Ordinal)).sharedMaterial;
            Vector3 Lamp(Transform lamp, string empty) => b.Blockout.Local(empty)
                - (lamp.GetComponent<MeshFilter>() is MeshFilter filter && filter.sharedMesh != null ? lamp.TransformVector(filter.sharedMesh.bounds.center) : Vector3.zero);
            var lights = new List<string>();
            foreach (var side in new[] { "L", "R" })
            {
                // The wing skin part each lens's anchor hangs on in the export: the skin, or the outer piece under it.
                var upperSkin = b.Blockout.Parts["light_nav_" + side].BlenderParent;
                var lowerSkin = b.Blockout.Parts["light_nav_lower_" + side].BlenderParent;
                var skin = b.Parts[upperSkin].transform;
                var nav = root.Find("navlight_" + side);
                nav.SetParent(skin, true);
                nav.rotation = b.Blockout.Rotation("light_nav_" + side);
                nav.localScale = Vector3.one;
                nav.position = Lamp(nav, "light_nav_" + side);
                NavLightEntry(navLights, nav.GetComponent<Renderer>()).FindPropertyRelative("part").objectReferenceValue = b.Part(upperSkin);
                lights.Add($"{nav.name} at light_nav_{side}");

                var lower = Object.Instantiate(nav.gameObject, b.Parts[lowerSkin].transform).transform;
                lower.name = "navlight_lower_" + side;
                lower.rotation = b.Blockout.Rotation("light_nav_lower_" + side);
                lower.position = Lamp(lower, "light_nav_lower_" + side);
                var navEntries = Prop(navLights, "navLights");
                var sourceIndex = Enumerable.Range(0, navEntries.arraySize).Single(i =>
                    navEntries.GetArrayElementAtIndex(i).FindPropertyRelative("renderer").objectReferenceValue == nav.GetComponent<Renderer>());
                navEntries.InsertArrayElementAtIndex(sourceIndex);
                var lowerEntry = navEntries.GetArrayElementAtIndex(sourceIndex);
                var sourceEntry = navEntries.GetArrayElementAtIndex(sourceIndex + 1);
                lowerEntry.FindPropertyRelative("renderer").objectReferenceValue = lower.GetComponent<Renderer>();
                lowerEntry.FindPropertyRelative("part").objectReferenceValue = b.Part(lowerSkin);
                lowerEntry.FindPropertyRelative("litMaterial").objectReferenceValue = sourceEntry.FindPropertyRelative("litMaterial").objectReferenceValue;
                lowerEntry.FindPropertyRelative("controlState").intValue = sourceEntry.FindPropertyRelative("controlState").intValue;
                lowerEntry.FindPropertyRelative("gear").objectReferenceValue = null;
                var lowerObjects = lowerEntry.FindPropertyRelative("objects");
                var sourceObjects = sourceEntry.FindPropertyRelative("objects");
                lowerObjects.arraySize = sourceObjects.arraySize;
                for (var i = 0; i < lowerObjects.arraySize; i++)
                {
                    var effect = (GameObject)sourceObjects.GetArrayElementAtIndex(i).objectReferenceValue;
                    lowerObjects.GetArrayElementAtIndex(i).objectReferenceValue = lower.Find(AnimationUtility.CalculateTransformPath(effect.transform, nav)).gameObject;
                }
                b.Placed.Add(lower);
                lights.Add($"{lower.name} at light_nav_lower_{side}");

                foreach (var (formationName, owner) in FormationLenses(side))
                {
                    var formation = new GameObject(formationName) { layer = b.Root.layer }.transform;
                    formation.SetParent(b.Parts[owner].transform, true);
                    formation.SetPositionAndRotation(b.Blockout.Local(formationName), b.Blockout.Rotation(formationName));
                    formation.gameObject.AddComponent<MeshFilter>().sharedMesh = b.Meshes[formationName].Render;
                    var formationRenderer = formation.gameObject.AddComponent<MeshRenderer>();
                    var formationMaterials = (Material[])b.Meshes[formationName].Materials.Clone();
                    formationMaterials[0] = formationOff;
                    formationRenderer.sharedMaterials = formationMaterials;
                    b.Visuals[formationName] = formation;
                    var entries = Prop(navLights, "navLights");
                    entries.arraySize++;
                    var entry = entries.GetArrayElementAtIndex(entries.arraySize - 1);
                    entry.FindPropertyRelative("renderer").objectReferenceValue = formationRenderer;
                    entry.FindPropertyRelative("objects").arraySize = 0;
                    entry.FindPropertyRelative("litMaterial").objectReferenceValue = b.Donor.FormationLit;
                    entry.FindPropertyRelative("part").objectReferenceValue = b.Part(owner);
                    entry.FindPropertyRelative("gear").objectReferenceValue = null;
                    entry.FindPropertyRelative("controlState").intValue = b.Donor.FormationState;
                    b.Placed.Add(formation);
                    lights.Add($"{formation.name} on {owner}");
                }

                var tipVertices = FamilyVertices(b, "wing_skin_" + side);
                var outer = tipVertices.Max(v => Mathf.Abs(v.x));
                var tip = tipVertices.Where(v => Mathf.Abs(v.x) > outer - 0.05f).ToArray();
                var tipCentre = tip.Aggregate(Vector3.zero, (s, v) => s + v) / tip.Length;
                var vortex = root.Find("wingtipvortex_" + side);
                vortex.SetParent(skin, true);
                vortex.position = new Vector3(Mathf.Sign(tipCentre.x) * outer, tipCentre.y, tip.Min(v => v.z));
                var vapour = root.Find("wingVapor_" + side);
                vapour.SetParent(b.Parts["wing_spar_" + side].transform, true);
                vapour.position = AreaCentroid(b, FamilyParts(b, "wing_skin_" + side));
                b.Placed.UnionWith(new[] { nav, vortex, vapour });
            }
            var tailReference = Load<GameObject>(Stock + "GameObject/AttackHelo1_PLACEHOLDER.prefab");
            var stockTail = tailReference.GetComponentsInChildren<MeshRenderer>(true).Single(r => r.name == "taillight");
            var stockTailEntry = NavLightEntry(new SerializedObject(tailReference.GetComponent(GameType("NavLights"))), stockTail);
            // The ControlSurface turns stabilator_hinge, not the part, so the lamp rides the hinge (its fairing does too,
            // through AttachLeftovers).
            var aft = new GameObject("navlight_aft") { layer = b.Root.layer }.transform;
            aft.SetParent(b.Parts["stabilator"].transform.Find("stabilator_hinge"), true);
            aft.SetPositionAndRotation(b.Blockout.Local("light_nav_aft"), b.Blockout.Rotation("light_nav_aft"));
            aft.gameObject.AddComponent<MeshFilter>().sharedMesh = b.Meshes["light_nav_aft"].Render;
            var aftRenderer = aft.gameObject.AddComponent<MeshRenderer>();
            aftRenderer.sharedMaterial = Load<Material>(Stock + "Material/Matte_black_PLACEHOLDER.mat");
            var aftEntries = Prop(navLights, "navLights");
            aftEntries.arraySize++;
            var aftEntry = aftEntries.GetArrayElementAtIndex(aftEntries.arraySize - 1);
            aftEntry.FindPropertyRelative("renderer").objectReferenceValue = aftRenderer;
            aftEntry.FindPropertyRelative("part").objectReferenceValue = b.Part("stabilator");
            aftEntry.FindPropertyRelative("gear").objectReferenceValue = null;
            aftEntry.FindPropertyRelative("litMaterial").objectReferenceValue = stockTailEntry.FindPropertyRelative("litMaterial").objectReferenceValue;
            aftEntry.FindPropertyRelative("controlState").intValue = NavLightEntry(navLights, b.Parts[b.Blockout.Parts["light_nav_L"].BlenderParent].transform.Find("navlight_L").GetComponent<Renderer>())
                .FindPropertyRelative("controlState").intValue;
            var stockTailObjects = stockTailEntry.FindPropertyRelative("objects");
            var aftObjects = aftEntry.FindPropertyRelative("objects");
            aftObjects.arraySize = stockTailObjects.arraySize;
            for (var i = 0; i < aftObjects.arraySize; i++)
            {
                var effect = Object.Instantiate((GameObject)stockTailObjects.GetArrayElementAtIndex(i).objectReferenceValue, aft);
                effect.transform.localPosition = new Vector3(0f, 0f, -0.04f);
                effect.transform.localRotation = Quaternion.identity;
                aftObjects.GetArrayElementAtIndex(i).objectReferenceValue = effect;
            }
            b.Visuals["light_nav_aft"] = aft;
            b.Placed.Add(aft);
            lights.Add("navlight_aft on stabilator with stock white tail-lamp switching");
            var landingLight = root.Find("gearlight_F") ?? throw new MissingReferenceException("rescued gearlight_F");
            landingLight.SetParent(FindDeep(b.Root.transform, "gear_leg_N_hinge"), true);
            landingLight.SetPositionAndRotation(b.Blockout.Local("light_landing"), Quaternion.LookRotation(new Vector3(0f, -0.07f, 1f), Vector3.up));
            var gearLightEntry = Enumerable.Range(0, Prop(navLights, "navLights").arraySize).Select(Prop(navLights, "navLights").GetArrayElementAtIndex)
                .Single(e => e.FindPropertyRelative("gear").objectReferenceValue != null);
            gearLightEntry.FindPropertyRelative("part").objectReferenceValue = b.Part("gear_leg_N");
            b.Placed.Add(landingLight);
            lights.Add("gearlight_F at light_landing on the nose leg");
            navLights.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add("lights: " + string.Join("; ", lights));

            // The transonic vapour cone where the wing root meets the body; the downwash under the nozzle on the Icarus
            // ground line; the scrape sparks on the belly.
            var wingRoot = FamilyVertices(b, "wing_skin_L").OrderBy(v => Mathf.Abs(v.x)).Take(20).Max(v => v.z);
            var cone = b.Parts["fuselage_forward"].transform.Find("vaporCone") ?? throw new MissingReferenceException("vaporCone");
            cone.position = new Vector3(0f, b.Parts[RootPart].GetComponent<MeshRenderer>().bounds.center.y, wingRoot);
            // Its 7-8 m particles were sized for the Revoker's broad body; the system scales locally, so the transform
            // scales them to the Icarus's width there.
            var width = FamilyVertices(b, "skin_mid_L").Concat(FamilyVertices(b, "skin_mid_R")).Select(v => v.x).ToArray();
            cone.localScale = Vector3.one * ((width.Max() - width.Min()) / RevokerBodyWidth);
            var ground = Contacts(b).Min(l => l.Contact.y);
            var downwash = b.Find("downwash");
            downwash.position = new Vector3(0f, downwash.position.y + ground - b.Donor.GroundY, b.Visuals["nozzle_vector"].position.z);
            var sparks = b.Find("contactSparks");
            sparks.position = new Vector3(0f, belly, 0f);
            b.Placed.UnionWith(new[] { cone, downwash, sparks });
            b.Report.Add($"systems: radar bound to radar_tray; target cameras F {forward.position}, R {rear.position}, landing {landing.position}; flares, nav lights, vortices, vapour (cone scaled {cone.localScale.x:F2}), downwash and sparks placed on the Icarus");
        }

        private sealed class Leg
        {
            public string Name;
            public Vector3 Contact; // the wheel's bottom with the spring free, in prefab space
            public float Travel, Spring;
        }

        private static Leg[] Contacts(Build b) => b.Root.GetComponentsInChildren(GameType("LandingGear"), true).Select(g =>
        {
            var so = new SerializedObject(g);
            var cast = Prop(so, "castPoint").objectReferenceValue as Transform;
            if (cast == null)
                cast = ((GameObject)Prop(so, "bumpStop").objectReferenceValue).transform;
            var travel = Prop(so, "suspensionTravel").floatValue;
            return new Leg { Name = g.name, Contact = cast.position - cast.up * travel, Travel = travel, Spring = Prop(so, "springRate").floatValue };
        }).ToArray();

        // Spawns the aircraft already sitting on its springs, as every geared stock definition does: the empty mass at the
        // CG shared by lever arm between the nose and main legs, each shortened by its load over springRate. The airframe's
        // length is centred on the spawn point, as the Revoker's is to within 0.15 m: a shelter1's spawn point sits midway
        // between its doors, 19.5 m apart, and with the nose where the Revoker's sat the 2 m longer Icarus put its
        // stabilator into the shut rear door.
        private static void SetRestPose(Build b, Object definition)
        {
            var legs = Contacts(b);
            var frontZ = legs.Max(l => l.Contact.z);
            var nose = legs.Where(l => l.Contact.z > frontZ - 0.5f).ToArray();
            var mains = legs.Except(nose).ToArray();
            if (nose.Length != 1 || mains.Length != 2)
                throw new InvalidDataException($"A8: expected one nose leg ahead of two mains; found {legs.Length} legs");
            var noseZ = nose.Average(l => l.Contact.z);
            var mainZ = mains.Average(l => l.Contact.z);
            var cg = CenterOfMass(b.Root.transform);
            var noseShare = (cg.z - mainZ) / (noseZ - mainZ);
            if (noseShare <= 0.02f || noseShare >= 0.5f)
                throw new InvalidDataException($"A8: {noseShare:P1} of the empty weight on the nose leg; the CG at z {cg.z:F2} must sit just ahead of the mains at {mainZ:F2}");
            var weight = EmptyMass * 9.81f;
            var lines = new List<string>();
            float RestY(Leg[] group, float load) => group.Average(l =>
            {
                var compression = load / group.Length / l.Spring;
                if (compression >= l.Travel)
                    throw new InvalidDataException($"A8: {l.Name} would bottom out at rest ({compression:F2} m of {l.Travel} m travel)");
                lines.Add($"{l.Name} {load / group.Length / 1000:0.0} kN, {compression:F3} m");
                return l.Contact.y + compression;
            });
            var noseY = RestY(nose, noseShare * weight);
            var mainY = RestY(mains, (1 - noseShare) * weight);
            var slope = (noseY - mainY) / (noseZ - mainZ);
            var height = slope * mainZ - mainY;
            var noseUp = Mathf.Atan(-slope) * Mathf.Rad2Deg;

            // Measured on the Icarus meshes alone: the Revoker's afterburner flame and lamps reach well past the airframe.
            var icarus = new HashSet<Mesh>(b.Meshes.Values.Select(m => m.Render));
            var renderers = b.Root.GetComponentsInChildren<MeshRenderer>(true)
                .Where(r => r.TryGetComponent<MeshFilter>(out var f) && icarus.Contains(f.sharedMesh)).ToArray();
            var bounds = renderers.Select(r => r.bounds).Aggregate((x, y) => { x.Encapsulate(y); return x; });
            b.Size = new Vector3(bounds.size.x, bounds.max.y + height, bounds.size.z);
            var def = new SerializedObject(definition);
            Prop(def, "spawnOffset").vector3Value = new Vector3(0, height, -bounds.center.z);
            Prop(def, "restRotation").vector3Value = new Vector3(-noseUp, 0, 0);
            Num(def, "length", bounds.size.z);
            Num(def, "width", bounds.size.x);
            Num(def, "height", bounds.max.y + height);
            def.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"rest pose: spawnOffset {Prop(def, "spawnOffset").vector3Value}, restRotation.x {-noseUp:F2} deg; {noseShare:P1} on the nose; {string.Join("; ", lines)}; " +
                $"length {bounds.size.z:F2} m, span {bounds.size.x:F2} m, height {bounds.max.y + height:F2} m (F-104G 16.69 x 6.68 x 4.12)");
        }

        // Blockout meshes no table gives a role (the ventral fin) ride along as plain meshes under their nearest placed
        // Blender ancestor, without colliders.
        private static void AttachLeftovers(Build b)
        {
            foreach (var part in b.Blockout.Parts.Values.Where(p => p.Fbx != null).OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                if (b.Parts.ContainsKey(part.Name) || b.Visuals.ContainsKey(part.Name))
                    continue;
                Transform parent = null;
                for (var name = part.BlenderParent; name != null && parent == null; name = b.Blockout.Has(name) ? b.Blockout.Parts[name].BlenderParent : null)
                    parent = b.Parts.TryGetValue(name, out var go) ? go.transform : b.Visuals.TryGetValue(name, out var visual) ? visual : null;
                parent = parent != null ? parent : b.Root.transform;
                // A hinged surface turns its <name>_hinge child, not the part, so its details ride the hinge.
                parent = parent.Find(parent.name + "_hinge") ?? parent;
                var mesh = new GameObject(part.Name) { layer = b.Root.layer };
                mesh.transform.SetParent(parent, true);
                mesh.transform.SetPositionAndRotation(b.Blockout.Local(part.Name), b.Blockout.Rotation(part.Name));
                mesh.AddComponent<MeshFilter>().sharedMesh = b.Meshes[part.Name].Render;
                mesh.AddComponent<MeshRenderer>().sharedMaterials = b.Meshes[part.Name].Materials;
                b.Visuals[part.Name] = mesh.transform;
                b.Report.Add($"note: blockout mesh {part.Name} ({part.Number("mass_kg")} kg) is a visual under {parent.name}; its {part.ColliderCount} collider pieces are unused");
            }
        }
    }
}
