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
        // R5's ordered strip checklist, A1 to A15, run on the finished prefab before it is saved. Each item logs one line;
        // any failure throws with every problem found, so the build fails and nothing is saved.
        private static void RunChecks(Build b, Object definition, Object parameters)
        {
            var failures = new List<string>();
            void Item(string id, string what, Func<List<string>, string> check)
            {
                var problems = new List<string>();
                string summary;
                try
                {
                    summary = check(problems);
                }
                catch (Exception e)
                {
                    problems.Add(e.GetType().Name + ": " + e.Message);
                    summary = "threw";
                }
                if (problems.Count == 0)
                    Debug.Log($"[Icarus] check {id} PASS: {what}; {summary}");
                else
                {
                    Debug.Log($"[Icarus] check {id} FAIL: {what}; {string.Join("; ", problems)}");
                    failures.AddRange(problems.Select(p => id + ": " + p));
                }
            }
            Item("A1", "identity", p => CheckIdentity(b, definition, parameters, p));
            Item("A2", "engine, nozzle and vectoring", p => CheckEngine(b, p));
            Item("A3", "canards, cannon, bays and doors gone", p => CheckStripped(b, p));
            Item("A4", "airfoils, structure and controls", p => CheckAero(b, parameters, p));
            Item("A5", "station schema and loadouts", p => CheckStations(b, parameters, p));
            Item("A6", "tanks", p => CheckTanks(b, p));
            Item("A7", "cockpit, cameras, HUD and damage diagram", p => CheckCockpit(b, parameters, p));
            Item("A8", "gear", p => CheckGear(b, p));
            Item("A9", "seat escape and canopy", p => CheckEscape(b, p));
            Item("A10", "sensors, ECM, flares and power", p => CheckSensors(b, p));
            Item("A11", "effects, lights and audio", p => CheckEffects(b, p));
            Item("A12", "prefab graph, LOD and physics structure", p => CheckGraph(b, p));
            Item("A13", "skin slot 0 and livery coverage", p => CheckSkin(b, p));
            Item("A14", "mounted store colliders", p => CheckStoreColliders(b, p));
            Item("A15", "cockpit renderers", p => CheckCockpitRenderers(b, p));
            if (failures.Count > 0)
                throw new InvalidDataException("Icarus authoring checks failed:\n  " + string.Join("\n  ", failures));
        }

        private static Component[] All(Build b, string type)
        {
            var t = Type.GetType(type + ", Assembly-CSharp");
            return t == null ? new Component[0] : b.Root.GetComponentsInChildren(t, true);
        }

        private static bool Inside(Build b, Object o) => o is Component c ? c.transform.IsChildOf(b.Root.transform) : o is GameObject g && g.transform.IsChildOf(b.Root.transform);

        private static string CheckIdentity(Build b, Object definition, Object parameters, List<string> p)
        {
            if (All(b, "Aircraft").Length != 1) p.Add($"{All(b, "Aircraft").Length} Aircraft components");
            var identities = b.Root.GetComponentsInChildren<Component>(true).Count(c => c != null && c.GetType().Name == "NetworkIdentity");
            if (identities != 1) p.Add($"{identities} NetworkIdentity components");
            if (GetRef(b.Aircraft, "definition") != definition) p.Add("Aircraft.definition isn't the Icarus definition");
            var def = new SerializedObject(definition);
            if (Prop(def, "jsonKey").stringValue != JsonKey) p.Add("definition jsonKey " + Prop(def, "jsonKey").stringValue);
            if (Prop(def, "aircraftParameters").objectReferenceValue != parameters) p.Add("definition.aircraftParameters isn't the Icarus parameters");
            if (!AssetDatabase.GetAssetPath(parameters).StartsWith(ModFolder, StringComparison.Ordinal)) p.Add("parameters outside the mod");
            return $"one Aircraft and NetworkIdentity, {JsonKey} -> {Path.GetFileName(AssetDatabase.GetAssetPath(parameters))}";
        }

        private static string CheckEngine(Build b, List<string> p)
        {
            var engines = All(b, "Turbojet");
            var nozzles = All(b, "JetNozzle");
            if (engines.Length != 1 || nozzles.Length != 1)
                p.Add($"{engines.Length} Turbojets and {nozzles.Length} JetNozzles, expected one each");
            if (engines.Length == 0 || nozzles.Length == 0)
                return "no engine";
            var te = new SerializedObject(engines[0]);
            if (Prop(te, "thrustVectoring").vector3Value != ThrustVectoring) p.Add("thrustVectoring " + Prop(te, "thrustVectoring").vector3Value);
            if (Prop(te, "thrustVectoringGain").vector3Value.z != 0) p.Add("roll gain isn't zero");
            if (Prop(te, "thrustVectoringMaxAirspeed").floatValue != VectoringMaxAirspeed) p.Add("vectoring cutoff " + Prop(te, "thrustVectoringMaxAirspeed").floatValue);
            var vectoring = GetList(Prop(te, "vectoringTransforms"));
            var thrust = b.Parts["nozzle"].transform.Find("thrust_vector");
            if (vectoring.Length != 1 || vectoring[0] != thrust) p.Add("vectoringTransforms isn't [thrust_vector]");
            if (thrust != null && Quaternion.Angle(thrust.localRotation, Quaternion.identity) > 0.01f) p.Add("thrust_vector isn't at rest (the Turbojet writes absolute angles)");
            if (thrust != null && thrust.GetComponent(GameType("JetNozzle")) != nozzles[0]) p.Add("the JetNozzle isn't on thrust_vector");
            var critical = GetList(Prop(te, "criticalParts"));
            if (critical.Length != 2 || critical[0] != b.Part("engine_core") || critical[1] != b.Part("nozzle")) p.Add("criticalParts isn't [engine_core, nozzle]");
            if (Prop(te, "damageThreshold").floatValue != EngineDamageThreshold) p.Add("damageThreshold " + Prop(te, "damageThreshold").floatValue);
            if (GetList(Prop(te, "nozzles")).SingleOrDefault() != nozzles[0]) p.Add("Turbojet.nozzles isn't the JetNozzle");
            if (Prop(te, "maxThrust").floatValue != MaxThrust || Prop(te, "maxSpeed").floatValue != EngineMaxSpeed) p.Add("core thrust or maxSpeed off R7");
            var jet = new SerializedObject(nozzles[0]);
            if (Prop(jet, "vectorTransforms").arraySize != 0) p.Add("JetNozzle.vectorTransforms isn't empty");
            if (Prop(jet, "part").objectReferenceValue != b.Part("nozzle")) p.Add("JetNozzle.part isn't the nozzle part");
            var axis = (Transform)Prop(jet, "thrustTransform").objectReferenceValue;
            if (axis == null || !axis.IsChildOf(thrust) || Vector3.Angle(axis.forward, Vector3.forward) > 2f) p.Add("the thrust axis doesn't ride on thrust_vector pointing forward");
            var afterburners = Prop(jet, "afterburners");
            if (afterburners.arraySize != 1) p.Add(afterburners.arraySize + " afterburners");
            else
            {
                var ab = afterburners.GetArrayElementAtIndex(0);
                foreach (var field in new[] { "flameRenderer", "nozzleGlowRenderer", "source" })
                    if (ab.FindPropertyRelative(field).objectReferenceValue == null) p.Add("afterburner " + field + " is null");
                if (ab.FindPropertyRelative("thrust").floatValue != AfterburnerThrust) p.Add("afterburner thrust off R7");
            }
            var petals = b.Visuals["nozzle_vector"].Cast<Transform>().Count(t => t.name.StartsWith("nozzle_petal_", StringComparison.Ordinal) || t.name.StartsWith("nozzle_seal_", StringComparison.Ordinal));
            if (petals == 0) p.Add("no petals under nozzle_vector for NozzleDriver");
            return $"one Turbojet ({MaxThrust / 1000:0} kN, maxSpeed {EngineMaxSpeed}), vectoring {ThrustVectoring} below {VectoringMaxAirspeed} m/s on thrust_vector, criticalParts engine_core and nozzle at {EngineDamageThreshold}, one afterburner, {petals} petals";
        }

        private static string CheckStripped(Build b, List<string> p)
        {
            var banned = new[] { "canard_L", "canard_R", "cannon", "weaponbay_L", "weaponbay_R", "weapondoor_L", "weapondoor_LL", "weapondoor_R", "weapondoor_RR", "cheek_L", "cheek_R", "canopyHingea" };
            foreach (var t in b.Root.GetComponentsInChildren<Transform>(true).Where(t => banned.Contains(t.name)))
                p.Add("Revoker object remains: " + PathOf(t, b.Root.transform));
            if (All(b, "BayDoor").Length > 0) p.Add(All(b, "BayDoor").Length + " BayDoors remain");
            var manager = new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager")));
            var sets = Prop(manager, "hardpointSets");
            for (var i = 0; i < sets.arraySize; i++)
            {
                var hardpoints = sets.GetArrayElementAtIndex(i).FindPropertyRelative("hardpoints");
                for (var j = 0; j < hardpoints.arraySize; j++)
                    if (hardpoints.GetArrayElementAtIndex(j).FindPropertyRelative("bayDoors").arraySize > 0) p.Add($"set {i} hardpoint {j} has bay doors");
            }
            foreach (var part in All(b, "AeroPart"))
            {
                var joints = Prop(new SerializedObject(part), "joints");
                for (var i = 0; i < joints.arraySize; i++)
                {
                    var other = joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue;
                    if (other == null || !Inside(b, other)) p.Add($"{part.name} joint {i} points at a removed part");
                }
            }
            return "no canards, cannon, bays, BayDoors or Revoker canopy rig; every joint on a live part";
        }

        private static string CheckAero(Build b, Object parameters, List<string> p)
        {
            var airfoils = Prop(new SerializedObject(parameters), "airfoils");
            var names = Enumerable.Range(0, airfoils.arraySize).Select(i => airfoils.GetArrayElementAtIndex(i).FindPropertyRelative("name").stringValue).ToArray();
            if (!names.SequenceEqual(Airfoils.Select(a => a.Name))) p.Add("airfoils [" + string.Join(", ", names) + "]");
            if (names.Any(n => n.IndexOf("canard", StringComparison.OrdinalIgnoreCase) >= 0)) p.Add("a canard curve remains");
            foreach (var part in All(b, "AeroPart"))
            {
                var index = Prop(new SerializedObject(part), "airfoil").intValue;
                if (index < 0 || index >= airfoils.arraySize) p.Add($"{part.name} airfoil {index} out of range");
            }
            var surfaces = All(b, "ControlSurface");
            float Sum(string range) => surfaces.Sum(s => Mathf.Abs(Prop(new SerializedObject(s), range).floatValue));
            if (Sum("pitchRange") == 0 || Sum("rollRange") == 0 || Sum("yawRange") == 0) p.Add("missing pitch, roll or yaw authority");
            foreach (var s in surfaces)
            {
                var so = new SerializedObject(s);
                var part = Prop(so, "attachedSurface").objectReferenceValue as Component;
                var visible = Prop(so, "visibleMesh").objectReferenceValue as GameObject;
                if (part == null || part.gameObject != s.gameObject || visible == null || !visible.transform.IsChildOf(s.transform)) p.Add(s.name + ": ControlSurface without its own part or hinge");
                var lift = GetRef(part, "liftNormal") as Transform;
                if (lift == null || visible == null || !lift.IsChildOf(visible.transform)) p.Add(s.name + ": lift normal doesn't turn with the surface");
            }
            var devices = All(b, "HighLiftDevice");
            if (devices.Length != 4) p.Add(devices.Length + " HighLiftDevices, expected the two flaps and two leading-edge flaps");
            foreach (var d in devices)
            {
                var so = new SerializedObject(d);
                var part = Prop(so, "aeroPart").objectReferenceValue as Component;
                if (part == null || part.gameObject != d.gameObject) p.Add(d.name + ": HighLiftDevice not on its own part");
                var moving = Prop(so, "movingParts");
                if (moving.arraySize == 0 || Enumerable.Range(0, moving.arraySize).Any(i => moving.GetArrayElementAtIndex(i).FindPropertyRelative("transform").objectReferenceValue == null)) p.Add(d.name + ": no moving transform");
                var expected = d.name.StartsWith("lef_", StringComparison.Ordinal) ? LefAddedArea : 0f;
                if (Mathf.Abs(Prop(so, "deployedArea").floatValue - expected) > 1e-4f) p.Add($"{d.name}: deployedArea {Prop(so, "deployedArea").floatValue}, expected {expected}");
                if (surfaces.Any(s => s.gameObject == d.gameObject)) p.Add(d.name + ": a ControlSurface and a HighLiftDevice share the part");
            }
            var airbrake = new SerializedObject(b.Root.GetComponent(GameType("Airbrake")));
            var openers = GetList(Prop(airbrake, "transforms"));
            if (openers.Length != 2 || openers.Any(o => o == null || !Inside(b, o))) p.Add("Airbrake transforms aren't the two speed brakes");
            if (Prop(airbrake, "part").objectReferenceValue != b.Part("fuselage_aft")) p.Add("Airbrake part isn't fuselage_aft");
            var wing = new[] { "wing_spar_L", "wing_spar_R", "aileron_L", "aileron_R", "flap_L", "flap_R", "lef_L", "lef_R" }.Sum(n => GetFloat(b.Part(n), "wingArea"));
            if (Mathf.Abs(wing - WingArea) > 0.01f) p.Add($"main wing {wing:F2} m2, not R7's {WingArea}");
            foreach (var skin in Tree.Where(s => s.Name.Contains("skin") || s.Name == "dorsal_cover"))
                if (GetFloat(b.Part(skin.Name), "wingArea") != 0) p.Add(skin.Name + " has lift; skins carry none (R13)");
            var drag = All(b, "AeroPart").Sum(a => GetFloat(a, "dragArea"));
            if (Mathf.Abs(drag - DragAreaTotal) > 1e-3f) p.Add($"dragArea {drag:F3}, not R7's {DragAreaTotal}");
            return $"airfoils [{string.Join(", ", names)}]; {surfaces.Length} ControlSurfaces (pitch {Sum("pitchRange")}, roll {Sum("rollRange")}, yaw {Sum("yawRange")}), {devices.Length} HighLiftDevices, two speed brakes; wing {wing:F2} m2, dragArea {drag:F2}";
        }

        private static string CheckTanks(Build b, List<string> p)
        {
            var tanks = All(b, "FuelTank");
            if (tanks.Length != b.Tanks.Count) p.Add($"{tanks.Length} FuelTanks, expected {b.Tanks.Count}");
            var total = 0f;
            foreach (var tank in tanks)
            {
                var so = new SerializedObject(tank);
                var part = Prop(so, "part").objectReferenceValue as Component;
                if (!b.Tanks.Contains(tank.name)) p.Add("a FuelTank on " + tank.name);
                if (part == null || part.gameObject != tank.gameObject || part.GetType().Name != "AeroPart") p.Add(tank.name + ": tank.part isn't its own AeroPart");
                if (GetList(Prop(so, "connectedTanks")).Any(c => c == null || !Inside(b, c))) p.Add(tank.name + ": a dead connected tank");
                total += Prop(so, "fuelCapacity").floatValue;
            }
            if (Mathf.Abs(total - FuelMass) > 1f) p.Add($"capacity {total} kg, not R7's {FuelMass}");
            return $"{tanks.Length} bladder tanks on their own parts, {total:0} kg";
        }

        private static string CheckSensors(Build b, List<string> p)
        {
            var radar = new SerializedObject(b.Parts["radome"].GetComponent(GameType("Radar")));
            if (Prop(radar, "attachedUnit").objectReferenceValue != b.Aircraft || Prop(radar, "part").objectReferenceValue != b.Part("radar_tray")) p.Add("the radar isn't bound to the aircraft and radar_tray");
            // Exact types: the Radar is itself a TargetDetector.
            foreach (var type in new[] { "TargetDetector", "RadarLocator", "LaserDesignator", "RadarJammer", "FlareEjector", "PowerSupply", "Radar" })
            {
                var count = All(b, type).Count(c => c.GetType().Name == type);
                if (count != 1) p.Add($"{count} {type}");
            }
            var power = new SerializedObject(b.Root.GetComponent(GameType("PowerSupply")));
            var sources = GetList(Prop(power, "powerSources"));
            if (sources.Length == 0 || sources.Any(s => s == null || !Inside(b, s))) p.Add("PowerSupply.powerSources don't resolve");
            var flares = Prop(new SerializedObject(b.Root.GetComponent(GameType("FlareEjector"))), "ejectionPoints");
            for (var i = 0; i < flares.arraySize; i++)
            {
                var t = flares.GetArrayElementAtIndex(i).FindPropertyRelative("transform").objectReferenceValue as Transform;
                var part = flares.GetArrayElementAtIndex(i).FindPropertyRelative("part").objectReferenceValue as Component;
                if (t == null || part == null || !t.IsChildOf(part.transform)) p.Add($"flare point {i} doesn't sit on its part");
            }
            if (flares.arraySize == 0) p.Add("no flare points");
            return $"radar on radar_tray, detector, locator, laser, jammer, {flares.arraySize} flare points, {sources.Length} power sources";
        }
    }
}
