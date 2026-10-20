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
        // The pilot's eye sits this far under the canopy's highest point, below it.
        private const float EyeBelowCanopyTop = 0.20f;
        // ...and this far behind the crown's middle. Under the crown itself the Revoker's instrument panel landed aft of
        // the windscreen frame, which then crossed the cockpit in front of the pilot; the F-104's eye sits about a metre
        // behind its windscreen bow.
        private const float EyeAftOfCrown = 0.50f;
        // TargetCam renders from 2 m out: its mounts sit 2.5 m clear of every mesh (Centurion's measured margin).
        private const float CameraClearance = 2.5f;

        private static void PlaceSystems(Build b)
        {
            var root = b.Root.transform;
            var renderers = b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.gameObject.layer != 3).ToArray();
            var noseTip = b.Parts["radome"].GetComponent<MeshRenderer>().bounds.max.z;
            var tailEnd = renderers.Min(r => r.bounds.min.z);
            var belly = new[] { RootPart, "skin_mid_L", "skin_mid_R", "fuselage_forward", "fuselage_aft" }.Min(n => b.Parts[n].GetComponent<MeshRenderer>().bounds.min.y);

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
                var skin = b.Parts[side < 0 ? "skin_aft_L" : "skin_aft_R"].GetComponent<MeshRenderer>().bounds;
                t.SetParent(b.Parts["fuselage_aft"].transform, true);
                t.SetPositionAndRotation(new Vector3(side < 0 ? skin.min.x : skin.max.x, skin.min.y + 0.15f, skin.center.z),
                    Quaternion.LookRotation(new Vector3(side * 0.8f, -0.55f, -0.25f), Vector3.up));
                point.FindPropertyRelative("part").objectReferenceValue = b.Part("fuselage_aft");
                b.Placed.Add(t);
            }
            ejector.ApplyModifiedPropertiesWithoutUndo();

            // The export's light empties on the Revoker's lights: the nav lamps on the wing skins' tips, which carry them
            // away when they go, the gear light as the landing light on the nose leg, and the Revoker's formation-light
            // switching on copies of the nav lamp. It has no anticollision beacon to give the two beacon empties.
            var navLights = new SerializedObject(b.Root.GetComponent(GameType("NavLights")));
            Vector3 Lamp(Transform lamp, string empty) => b.Blockout.Local(empty)
                - (lamp.GetComponent<MeshFilter>() is MeshFilter filter && filter.sharedMesh != null ? lamp.TransformVector(filter.sharedMesh.bounds.center) : Vector3.zero);
            var lights = new List<string>();
            foreach (var side in new[] { "L", "R" })
            {
                var skin = b.Parts["wing_skin_" + side].transform;
                var nav = root.Find("navlight_" + side);
                nav.SetParent(skin, true);
                nav.position = Lamp(nav, "light_nav_" + side);
                NavLightEntry(navLights, nav.GetComponent<Renderer>()).FindPropertyRelative("part").objectReferenceValue = b.Part("wing_skin_" + side);
                lights.Add($"{nav.name} at light_nav_{side}");

                var formation = Object.Instantiate(nav.gameObject, b.Parts["skin_mid_" + side].transform).transform;
                formation.name = "light_formation_" + side;
                foreach (var child in formation.Cast<Transform>().ToArray())
                    Object.DestroyImmediate(child.gameObject);
                formation.rotation = nav.rotation;
                formation.position = Lamp(formation, "light_formation_" + side);
                var entries = Prop(navLights, "navLights");
                entries.arraySize++;
                var entry = entries.GetArrayElementAtIndex(entries.arraySize - 1);
                entry.FindPropertyRelative("renderer").objectReferenceValue = formation.GetComponent<Renderer>();
                entry.FindPropertyRelative("objects").arraySize = 0;
                entry.FindPropertyRelative("litMaterial").objectReferenceValue = b.Donor.FormationLit;
                entry.FindPropertyRelative("part").objectReferenceValue = b.Part("skin_mid_" + side);
                entry.FindPropertyRelative("gear").objectReferenceValue = null;
                entry.FindPropertyRelative("controlState").intValue = b.Donor.FormationState;
                b.Placed.Add(formation);
                lights.Add($"{formation.name} on skin_mid_{side}");

                var tipVertices = WorldVertices(skin, b.Meshes["wing_skin_" + side].Render);
                var outer = tipVertices.Max(v => Mathf.Abs(v.x));
                var tip = tipVertices.Where(v => Mathf.Abs(v.x) > outer - 0.05f).ToArray();
                var tipCentre = tip.Aggregate(Vector3.zero, (s, v) => s + v) / tip.Length;
                var vortex = root.Find("wingtipvortex_" + side);
                vortex.SetParent(skin, true);
                vortex.position = new Vector3(Mathf.Sign(tipCentre.x) * outer, tipCentre.y, tip.Min(v => v.z));
                var vapour = root.Find("wingVapor_" + side);
                vapour.SetParent(b.Parts["wing_spar_" + side].transform, true);
                vapour.position = AreaCentroid(skin, b.Meshes["wing_skin_" + side].Render);
                b.Placed.UnionWith(new[] { nav, vortex, vapour });
            }
            var landingLight = root.Find("gearlight_F") ?? throw new MissingReferenceException("rescued gearlight_F");
            landingLight.SetParent(FindDeep(b.Root.transform, "gear_leg_N_hinge"), true);
            landingLight.SetPositionAndRotation(b.Blockout.Local("light_landing"), Quaternion.LookRotation(new Vector3(0f, -0.07f, 1f), Vector3.up));
            var gearLightEntry = Enumerable.Range(0, Prop(navLights, "navLights").arraySize).Select(Prop(navLights, "navLights").GetArrayElementAtIndex)
                .Single(e => e.FindPropertyRelative("gear").objectReferenceValue != null);
            gearLightEntry.FindPropertyRelative("part").objectReferenceValue = b.Part("gear_leg_N");
            b.Placed.Add(landingLight);
            lights.Add("gearlight_F at light_landing on the nose leg");
            navLights.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add("lights: " + string.Join("; ", lights) + "; light_beacon_top and light_beacon_belly unwired (no Revoker beacon)");

            // The transonic vapour cone where the wing root meets the body; the downwash under the nozzle on the Icarus
            // ground line; the scrape sparks on the belly.
            var wingRoot = WorldVertices(b.Parts["wing_skin_L"].transform, b.Meshes["wing_skin_L"].Render).OrderBy(v => Mathf.Abs(v.x)).Take(20).Max(v => v.z);
            var cone = b.Parts["fuselage_forward"].transform.Find("vaporCone") ?? throw new MissingReferenceException("vaporCone");
            cone.position = new Vector3(0f, b.Parts[RootPart].GetComponent<MeshRenderer>().bounds.center.y, wingRoot);
            var ground = Contacts(b).Min(l => l.Contact.y);
            var downwash = b.Find("downwash");
            downwash.position = new Vector3(0f, downwash.position.y + ground - b.Donor.GroundY, b.Visuals["nozzle_vector"].position.z);
            var sparks = b.Find("contactSparks");
            sparks.position = new Vector3(0f, belly, 0f);
            b.Placed.UnionWith(new[] { cone, downwash, sparks });
            b.Report.Add($"systems: radar bound to radar_tray; target cameras F {forward.position}, R {rear.position}, landing {landing.position}; flares, nav lights, vortices, vapour, downwash and sparks placed on the Icarus");
        }

        // Eight stations in R5's fixed order, each set [L, R] with HardpointIndex 0..7 left before right.
        private static void BuildStations(Build b)
        {
            Vector3 WingPoint(string side, float fraction)
            {
                var skin = WorldVertices(b.Parts["wing_skin_" + side].transform, b.Meshes["wing_skin_" + side].Render);
                var chord = skin.Concat(new[] { "flap_", "aileron_", "lef_" }.SelectMany(s => WorldVertices(b.Visuals[s + side + "_visible"], b.Meshes[s + side + "_visible"].Render))).ToArray();
                var inner = skin.Min(v => Mathf.Abs(v.x));
                var outer = skin.Max(v => Mathf.Abs(v.x));
                var sign = side == "L" ? -1f : 1f;
                if (fraction >= 1f)
                {
                    var tip = skin.Where(v => Mathf.Abs(v.x) > outer - 0.05f).ToArray();
                    return new Vector3(sign * outer, tip.Average(v => v.y), tip.Average(v => v.z));
                }
                var x = sign * (inner + fraction * (outer - inner));
                var slab = chord.Where(v => Mathf.Abs(v.x - x) < 0.15f).ToArray();
                var z = (slab.Max(v => v.z) + slab.Min(v => v.z)) / 2;
                var under = skin.Where(v => Mathf.Abs(v.x - x) < 0.15f && Mathf.Abs(v.z - z) < 0.4f).ToArray();
                return new Vector3(x, under.Min(v => v.y) - 0.02f, z);
            }
            Vector3 ConformalPoint(string side)
            {
                var x = (side == "L" ? -1f : 1f) * 0.55f;
                var z = b.Parts["fuel_forward_main"].transform.position.z - 0.6f;
                var hull = new[] { RootPart, "intake_duct_L", "intake_duct_R", "skin_mid_L", "skin_mid_R" }
                    .SelectMany(n => WorldVertices(b.Parts[n].transform, b.Meshes[n].Render)).Where(v => Mathf.Abs(v.x - x) < 0.12f && Mathf.Abs(v.z - z) < 0.3f).ToArray();
                return new Vector3(x, hull.Min(v => v.y) - 0.02f, z);
            }

            var sets = new (string Name, string Part, Func<string, Vector3> Where)[]
            {
                (SetNames[0], "wing_spar_", s => WingPoint(s, 1f)),
                (SetNames[1], "wing_spar_", s => WingPoint(s, 0.35f)),
                (SetNames[2], "wing_spar_", s => WingPoint(s, 0.70f)),
                (SetNames[3], RootPart, ConformalPoint),
            };
            var manager = b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager"));
            var so = new SerializedObject(manager);
            var list = Prop(so, "hardpointSets");
            list.arraySize = sets.Length;
            var lines = new List<string>();
            for (var i = 0; i < sets.Length; i++)
            {
                var set = list.GetArrayElementAtIndex(i);
                set.FindPropertyRelative("name").stringValue = sets[i].Name;
                set.FindPropertyRelative("precludingHardpointSets").arraySize = 0;
                set.FindPropertyRelative("SymmetryWithPrev").boolValue = false;
                set.FindPropertyRelative("SymmetryName").stringValue = string.Empty;
                var options = set.FindPropertyRelative("weaponOptions");
                options.arraySize = 1; // index 0 is "empty"; stock mounts arrive through OpAddWeaponToHardpoint
                options.GetArrayElementAtIndex(0).objectReferenceValue = null;
                set.FindPropertyRelative("weaponMount").objectReferenceValue = null;
                var hardpoints = set.FindPropertyRelative("hardpoints");
                hardpoints.arraySize = 2;
                foreach (var (side, j) in new[] { ("L", 0), ("R", 1) })
                {
                    var partName = sets[i].Part == RootPart ? RootPart : sets[i].Part + side;
                    var part = b.Parts[partName].transform;
                    var point = new GameObject("hardpoint_" + sets[i].Name.Replace(" ", "").ToLowerInvariant() + "_" + side) { layer = part.gameObject.layer }.transform;
                    point.SetParent(part, false);
                    point.SetPositionAndRotation(sets[i].Where(side), b.Root.transform.rotation);
                    var hp = hardpoints.GetArrayElementAtIndex(j);
                    hp.FindPropertyRelative("transform").objectReferenceValue = point;
                    hp.FindPropertyRelative("part").objectReferenceValue = b.Part(partName);
                    hp.FindPropertyRelative("bayDoors").arraySize = 0;
                    hp.FindPropertyRelative("doorOpenDuration").floatValue = 0f;
                    hp.FindPropertyRelative("pylonOptions").arraySize = 0;
                    hp.FindPropertyRelative("Pylon").objectReferenceValue = null;
                    hp.FindPropertyRelative("Plug").objectReferenceValue = null;
                    hp.FindPropertyRelative("BuiltInWeapons").arraySize = 0;
                    hp.FindPropertyRelative("BuiltInTurrets").arraySize = 0;
                    hp.FindPropertyRelative("HardpointIndex").intValue = 2 * i + j;
                    lines.Add($"{point.name} #{2 * i + j} on {partName} at {point.position}");
                }
            }
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add("stations: " + string.Join("; ", lines));
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
        // CG shared by lever arm between the nose and main legs, each shortened by its load over springRate. The nose sits
        // where the Revoker's did relative to the spawn point, so the hangars the Revoker uses fit it the same way.
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
            var donor = new SerializedObject(Load<Object>(DonorDefinition));
            var donorNose = Prop(donor, "spawnOffset").vector3Value.z + b.Donor.NoseZ;
            var def = new SerializedObject(definition);
            Prop(def, "spawnOffset").vector3Value = new Vector3(0, height, donorNose - bounds.max.z);
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
                var mesh = new GameObject(part.Name) { layer = b.Root.layer };
                mesh.transform.SetParent(parent, true);
                mesh.transform.SetPositionAndRotation(b.Blockout.Local(part.Name), b.Blockout.Rotation(part.Name));
                mesh.AddComponent<MeshFilter>().sharedMesh = b.Meshes[part.Name].Render;
                mesh.AddComponent<MeshRenderer>().sharedMaterials = b.Meshes[part.Name].Materials;
                b.Visuals[part.Name] = mesh.transform;
                b.Report.Add($"note: blockout mesh {part.Name} ({part.Number("mass_kg")} kg) is a visual under {parent.name}; its {part.ColliderCount} collider pieces are unused");
            }
        }

        // Each LOD1 hull on the part or visual it belongs to, at identity (the export puts it in that mesh's space).
        private static void AddLods(Build b)
        {
            foreach (var entry in b.Meshes.Where(m => m.Value.Lod1 != null).OrderBy(m => m.Key, StringComparer.Ordinal))
            {
                var owner = b.Parts.TryGetValue(entry.Key, out var part) && !b.Blockout.Parts[entry.Key].IsHinge ? part.transform
                    : b.Visuals.TryGetValue(entry.Key, out var visual) ? visual : throw new InvalidDataException(entry.Key + " has a LOD1 hull but no place in the prefab");
                var go = new GameObject(entry.Key + "_lod1") { layer = b.Root.layer };
                go.transform.SetParent(owner, false);
                go.AddComponent<MeshFilter>().sharedMesh = entry.Value.Lod1;
                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = entry.Value.Lod1Materials;
                b.Lod1.Add(renderer);
            }
        }

        // Two levels as stock: the full meshes, then the LOD1 hulls down to 0.1% of the screen.
        private static void FinishRoot(Build b)
        {
            b.Root.GetComponent<Rigidbody>().mass = EmptyMass;
            var lod = b.Root.GetComponent<LODGroup>();
            var renderers = b.Root.GetComponentsInChildren<Renderer>(true).Where(r => r.gameObject.layer != 3 && !(r is ParticleSystemRenderer)).ToArray();
            var hulls = b.Lod1.ToArray();
            var full = renderers.Except(hulls).ToArray();
            lod.SetLODs(new[] { new LOD(0.05f, full), new LOD(0.001f, hulls) });
            lod.RecalculateBounds();
            lod.size = Mathf.Max(b.Size.x, b.Size.z);
            b.Report.Add($"LODGroup: {full.Length} renderers to 5% of the screen, {hulls.Length} LOD1 hulls to 0.1%, size {lod.size:F2} m");
        }
    }
}
