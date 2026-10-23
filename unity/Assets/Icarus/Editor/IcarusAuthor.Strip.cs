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
        // What the Icarus takes from Revoker parts the strip deletes: their armour classes, component templates, the
        // control sense of their surfaces and where the pilot's eye was.
        private sealed class DonorCapture
        {
            public readonly Dictionary<string, Dictionary<string, float>> Armour = new Dictionary<string, Dictionary<string, float>>();
            public Component AeroTemplate, TankTemplate, SurfaceTemplate, DeviceTemplate, CanopyTemplate;
            public float PitchSense, RollSense, YawSense;
            public Vector3 Eye;
            public float GroundY; // the Revoker's ground line under its root, from its definition's spawnOffset
            public Material FormationLit; // the Revoker's formation strips' lit material and switching
            public int FormationState;
        }

        // Revoker parts the Icarus parts take their armour from (R13: "use Revoker armor classes").
        private static readonly string[] ArmourSources =
        {
            "", "fuselage", "tail", "fuselage/cockpit", "fuselage/cockpit/nose", "fuselage/cockpit/cheek_L", "fuselage/intake_L",
            "fuselage/wing1a_L", "fuselage/wing1a_L/wing2_L", "fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L", "fuselage/wing1a_L/wing2_L/flap_L",
            "wing1b_L", "vstab1", "vstab1/vstab2", "vstab1/vstab2/rudder",
        };

        private static DonorCapture CaptureDonor(Build b, List<GameObject> templates)
        {
            var capture = new DonorCapture();
            var aeroType = GameType("AeroPart");
            foreach (var path in ArmourSources)
            {
                var part = (path == "" ? b.Root.transform : b.Find(path)).GetComponent(aeroType);
                var so = new SerializedObject(part);
                var values = new Dictionary<string, float>
                {
                    ["structuralThreshold"] = Prop(so, "structuralThreshold").floatValue,
                    ["integrityThreshold"] = Prop(so, "integrityThreshold").floatValue,
                };
                var armour = Prop(so, "armorProperties");
                var end = armour.GetEndProperty();
                for (var it = armour.Copy(); it.NextVisible(true) && !SerializedProperty.EqualContents(it, end);)
                    if (it.propertyType == SerializedPropertyType.Float)
                        values[it.propertyPath] = it.floatValue;
                capture.Armour[path] = values;
            }

            Component Template(Component source, string name)
            {
                var go = new GameObject(name);
                templates.Add(go);
                var copy = go.AddComponent(source.GetType());
                EditorUtility.CopySerialized(source, copy);
                return copy;
            }
            capture.AeroTemplate = Template(b.Find("fuselage/wing1a_L").GetComponent(aeroType), "aeropart_template");
            capture.TankTemplate = Template(b.Root.GetComponent(GameType("FuelTank")), "tank_template");
            capture.SurfaceTemplate = Template(b.Find("fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L").GetComponent(GameType("ControlSurface")), "surface_template");
            capture.DeviceTemplate = Template(b.Find("fuselage/wing1a_L/wing2_L/flap_L").GetComponent(GameType("HighLiftDevice")), "device_template");
            capture.CanopyTemplate = Template(b.Find("fuselage/cockpit/canopyHingea/canopyHingeb/canopyFrame").GetComponent(GameType("Canopy")), "canopy_template");

            var navLights = Prop(new SerializedObject(b.Root.GetComponent(GameType("NavLights"))), "navLights");
            var strip = Enumerable.Range(0, navLights.arraySize).Select(navLights.GetArrayElementAtIndex)
                .First(e => e.FindPropertyRelative("renderer").objectReferenceValue is Component r && r.name.StartsWith("slimelights", StringComparison.Ordinal));
            capture.FormationLit = (Material)strip.FindPropertyRelative("litMaterial").objectReferenceValue;
            capture.FormationState = strip.FindPropertyRelative("controlState").intValue;
            CalibrateSurfaceSigns(b, capture);
            capture.Eye = ((Transform)GetRef(b.Aircraft, "cockpitViewPoint")).position;
            capture.GroundY = -Prop(new SerializedObject(Load<Object>(DonorDefinition)), "spawnOffset").vector3Value.y;
            return capture;
        }

        // Change in the game's lift force (AeroJob_Math.Execute, odd lift curve, unit airflow from ahead) when a surface's
        // lift transform turns +1 degree about its hinge (ControlSurface rotates visibleMesh about local X).
        private static Vector3 DeflectionForce(Quaternion lift, Vector3 hingeAxis)
        {
            Vector3 Force(Quaternion r)
            {
                var v = Vector3.forward;
                var local = Quaternion.Inverse(r) * v;
                var n = Vector3.Cross(v, r * Vector3.right).normalized;
                return -n * Mathf.Atan2(local.y, local.z);
            }
            return Force(Quaternion.AngleAxis(1f, hingeAxis) * lift) - Force(lift);
        }

        private static Vector3 CenterOfMass(Transform root)
        {
            var sum = Vector3.zero;
            var mass = 0f;
            foreach (var part in root.GetComponentsInChildren(GameType("AeroPart"), true))
            {
                var so = new SerializedObject(part);
                var m = so.FindProperty("mass").floatValue;
                var com = (Transform)so.FindProperty("centerOfMass").objectReferenceValue;
                sum += m * (com != null ? com.position : part.transform.position);
                mass += m;
            }
            return sum / mass;
        }

        // Which way a positive range moves the aircraft, read from the Revoker's own surfaces, so the Icarus ranges get the
        // same sense whatever their hinge orientation: its canards are its only pitch surfaces.
        private static void CalibrateSurfaceSigns(Build b, DonorCapture capture)
        {
            var cg = CenterOfMass(b.Root.transform);
            float Sense(string path, string range, int axis)
            {
                var surface = b.Find(path).GetComponent(GameType("ControlSurface"));
                var so = new SerializedObject(surface);
                var visible = ((GameObject)Prop(so, "visibleMesh").objectReferenceValue).transform;
                var part = Prop(so, "attachedSurface").objectReferenceValue;
                var lift = (Transform)new SerializedObject(part).FindProperty("liftNormal").objectReferenceValue ?? ((Component)part).transform;
                if (!lift.IsChildOf(visible))
                    throw new InvalidDataException(path + ": the lift transform doesn't turn with the surface; can't calibrate.");
                var torque = Vector3.Cross(lift.position - cg, DeflectionForce(lift.rotation, visible.rotation * Vector3.right));
                return Mathf.Sign(Prop(so, range).floatValue * torque[axis]);
            }
            capture.PitchSense = Sense("fuselage/cockpit/cheek_L/canard_L", "pitchRange", 0);
            capture.RollSense = Sense("fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L", "rollRange", 2);
            capture.YawSense = Sense("vstab1/vstab2/rudder", "yawRange", 1);
            if (capture.PitchSense != Sense("fuselage/cockpit/cheek_R/canard_R", "pitchRange", 0)
                || capture.RollSense != Sense("fuselage/wing1a_R/wing2_R/wingtip_R/aileron_R", "rollRange", 2))
                throw new InvalidDataException("The Revoker's left and right surfaces disagree on control sense.");
            b.Report.Add($"control sense from the Revoker: pitch {capture.PitchSense:+0;-0}, roll {capture.RollSense:+0;-0}, yaw {capture.YawSense:+0;-0} (torque sign about X, Z, Y per +1 input)");
        }

        // R5's strip: keeps the Revoker's systems and deletes its airframe, canards, cannon, internal bays and doors,
        // canopy rig and gear doors, rescuing what the Icarus keeps from inside them first. Reused GameObjects (the root,
        // fuselage, cockpit, nose and tail, which carry the systems) become Icarus parts in BuildParts.
        private static void StripDonor(Build b)
        {
            var root = b.Root.transform;
            foreach (var path in new[]
                     {
                         "fuselage/cockpit/gearHinge_F", "fuselage/cockpit/gear_F_armTarget", "fuselage/cockpit/geardoorHinge_FF/geardoor_FF/gearlight_F",
                         "fuselage/wing1a_L/gearMount_L", "fuselage/wing1a_L/gear_armtarget_L", "fuselage/wing1a_R/gearMount_R", "fuselage/wing1a_R/gear_armtarget_R",
                         "fuselage/wing1a_L/wing2_L/wingtip_L/navlight_L", "fuselage/wing1a_R/wing2_R/wingtip_R/navlight_R",
                         "fuselage/wing1a_L/wing2_L/wingtip_L/wingtipvortex_L", "fuselage/wing1a_R/wing2_R/wingtip_R/wingtipvortex_R",
                         "fuselage/wing1a_L/wingVapor_L", "fuselage/wing1a_R/wingVapor_R",
                     })
                b.Find(path).SetParent(root, true);
            // The wingtip lights' NavLights entries name the doomed wingtips as their part, and DestroyWithReferences would
            // drop the whole entry, leaving the light lit for good; they lose only the part, which PlaceSystems gives back.
            var navLights = new SerializedObject(b.Root.GetComponent(GameType("NavLights")));
            foreach (var light in new[] { "navlight_L", "navlight_R" })
                NavLightEntry(navLights, root.Find(light).GetComponent<Renderer>()).FindPropertyRelative("part").objectReferenceValue = null;
            navLights.ApplyModifiedPropertiesWithoutUndo();

            var doomed = new List<Object>();
            foreach (var path in new[]
                     {
                         // A3: the cannon, both canards (under the cheeks), both weapon bays with their four BayDoors.
                         "fuselage/cannon", "fuselage/cockpit/cheek_L", "fuselage/cockpit/cheek_R", "weaponbay_L", "weaponbay_R",
                         // The rest of the Revoker airframe the Icarus replaces.
                         "fuselage/wing1a_L", "fuselage/wing1a_R", "fuselage/intake_L", "fuselage/intake_R", "wing1b_L", "wing1b_R", "vstab1",
                         "airbrake_L", "airbrake_R", "engine_lod1", "tail/tail_lod1", "fuselage/fuselage_lod1", "fuselage/cockpit/cockpit_lod1",
                         "fuselage/cockpit/nose/nose_lod1", "fuselage/cockpit/nose/nose_liftNormal", "fuselage/cockpit/slimelights_cockpit",
                         // The canopy rig (its Canopy is rebuilt on the Icarus canopy part) and the Revoker-shaped gear doors.
                         "fuselage/cockpit/canopyHingea", "fuselage/cockpit/geardoor_FL", "fuselage/cockpit/geardoor_FR", "fuselage/cockpit/geardoorHinge_FF",
                     })
                doomed.Add(b.Find(path).gameObject);
            // Fuel moves to the five bladder parts; the tanks' templates were copied in CaptureDonor.
            doomed.AddRange(b.Root.GetComponentsInChildren(GameType("FuelTank"), true));
            DestroyWithReferences(b, doomed);

            // The reused parts lose the Revoker's meshes, and every list naming them its entry; BuildParts gives them the
            // Icarus ones.
            var meshes = new List<Object>();
            foreach (var path in new[] { "", "fuselage", "tail", "fuselage/cockpit", "fuselage/cockpit/nose", "tail/nozzle" })
            {
                var go = (path == "" ? root : b.Find(path)).gameObject;
                meshes.AddRange(go.GetComponents<MeshCollider>());
                meshes.AddRange(go.GetComponents<MeshRenderer>());
                meshes.AddRange(go.GetComponents<MeshFilter>());
            }
            DestroyWithReferences(b, meshes);
            // The JetNozzle's GameObject becomes the thrust vector pivot; "nozzle" is now the Icarus part it sits in.
            b.Find("tail/nozzle").name = "thrust_vector";
            b.Report.Add($"strip: {doomed.Count} Revoker objects and components removed with their references");
        }

        // The NavLights entry that switches a light, found by its renderer.
        private static SerializedProperty NavLightEntry(SerializedObject navLights, Renderer light)
        {
            var lights = Prop(navLights, "navLights");
            return Enumerable.Range(0, lights.arraySize).Select(lights.GetArrayElementAtIndex)
                .Single(e => e.FindPropertyRelative("renderer").objectReferenceValue == light);
        }
    }
}
