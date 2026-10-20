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
        // The stock seat's rail (EjectionSeat, the PilotDismounted nozzle's up in the cockpit frame), the last step where its
        // colliders turn on and its end, and the pilot capsule swept along it (radius, ends below and above the Pilot).
        private static readonly Vector3 SeatRail = new Vector3(-0.024f, 0.973f, 0.230f);
        private const float RailCollidable = 1.44f, RailEnd = 1.50f, CapsuleRadius = 0.25f, CapsuleBelow = 0.40f, CapsuleAbove = 0.90f;

        // R5's ordered strip checklist, A1 to A12, run on the finished prefab before it is saved. Each item logs one line;
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

        private static string CheckStations(Build b, Object parameters, List<string> p)
        {
            var manager = new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager")));
            var sets = Prop(manager, "hardpointSets");
            var names = Enumerable.Range(0, sets.arraySize).Select(i => sets.GetArrayElementAtIndex(i).FindPropertyRelative("name").stringValue).ToArray();
            if (!names.SequenceEqual(SetNames)) p.Add("sets [" + string.Join(", ", names) + "]");
            var indices = new List<int>();
            for (var i = 0; i < sets.arraySize; i++)
            {
                var set = sets.GetArrayElementAtIndex(i);
                if (set.FindPropertyRelative("precludingHardpointSets").arraySize > 0) p.Add(names[i] + " precludes another set");
                var hardpoints = set.FindPropertyRelative("hardpoints");
                if (hardpoints.arraySize != 2) { p.Add($"{names[i]} has {hardpoints.arraySize} hardpoints"); continue; }
                for (var j = 0; j < 2; j++)
                {
                    var hp = hardpoints.GetArrayElementAtIndex(j);
                    var t = hp.FindPropertyRelative("transform").objectReferenceValue as Transform;
                    var part = hp.FindPropertyRelative("part").objectReferenceValue;
                    if (t == null || part == null || !Inside(b, part)) { p.Add($"{names[i]} hardpoint {j} has no transform or part"); continue; }
                    if (j == 0 ? t.position.x >= 0 : t.position.x <= 0) p.Add($"{names[i]} hardpoint {j} is on the wrong side ({t.position.x:F2})");
                    indices.Add(hp.FindPropertyRelative("HardpointIndex").intValue);
                }
            }
            if (!indices.OrderBy(i => i).SequenceEqual(Enumerable.Range(0, 8))) p.Add("HardpointIndex values [" + string.Join(", ", indices) + "], expected 0..7 once each");
            var so = new SerializedObject(parameters);
            var lengths = new List<int>();
            var loadouts = Prop(so, "loadouts");
            for (var i = 0; i < loadouts.arraySize; i++)
                lengths.Add(loadouts.GetArrayElementAtIndex(i).FindPropertyRelative("weapons").arraySize);
            var standard = Prop(so, "StandardLoadouts");
            for (var i = 0; i < standard.arraySize; i++)
            {
                var weapons = standard.GetArrayElementAtIndex(i).FindPropertyRelative("loadout").FindPropertyRelative("weapons");
                lengths.Add(weapons.arraySize);
                if (GetList(weapons).Any(w => w != null && KeyOf(w).StartsWith("gun", StringComparison.Ordinal))) p.Add("a standard loadout carries a gun");
            }
            if (loadouts.arraySize < 2) p.Add("fewer than two ordinary loadouts (WeaponManager falls back to loadouts[1])");
            if (lengths.Any(l => l != SetNames.Length)) p.Add("loadout lengths [" + string.Join(", ", lengths) + "]");
            return $"sets [{string.Join(", ", names)}], hardpoints 0..7 left before right, loadout lengths [{string.Join(", ", lengths)}]";
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

        private static string CheckCockpit(Build b, Object parameters, List<string> p)
        {
            var aircraft = new SerializedObject(b.Aircraft);
            foreach (var field in new[] { "cockpit", "controlsFilter", "weaponManager", "targetCam", "radar", "EOTS", "powerSupply", "cockpitViewPoint", "definition" })
                if (Prop(aircraft, field).objectReferenceValue == null) p.Add("Aircraft." + field + " is null");
            if (GetList(Prop(aircraft, "pilots")).Any(o => o == null)) p.Add("a null pilot");
            if (GetList(Prop(aircraft, "groundEquipment")).Any(o => o == null)) p.Add("dead ground equipment");
            if (GetList(Prop(aircraft, "exteriorRenderers")).Any(o => o == null)) p.Add("a null exterior renderer");
            // The tac screen: one pylon set per HardpointIndex (PylonIndicator indexes them directly), and every engine
            // gauge named for a damageable that carries the engine.
            var cockpitUi = b.Parts["cockpit_cell"].GetComponentsInChildren(GameType("Cockpit"), true).Single();
            var screen = GetRef(cockpitUi, "tacScreenUIPrefab") as GameObject;
            var manager = new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager")));
            var stationSets = Prop(manager, "hardpointSets");
            var stations = Enumerable.Range(0, stationSets.arraySize).SelectMany(i =>
            {
                var hardpoints = stationSets.GetArrayElementAtIndex(i).FindPropertyRelative("hardpoints");
                return Enumerable.Range(0, hardpoints.arraySize).Select(j => hardpoints.GetArrayElementAtIndex(j).FindPropertyRelative("HardpointIndex").intValue);
            }).ToArray();
            var pylonSets = 0;
            if (screen == null || !AssetDatabase.GetAssetPath(screen).StartsWith(ModFolder, StringComparison.Ordinal))
                p.Add("the cockpit's tac screen isn't the Icarus copy");
            else
            {
                var pylons = Prop(new SerializedObject(screen.GetComponentsInChildren(GameType("PylonIndicator"), true).Single()), "pylonElementSets");
                pylonSets = pylons.arraySize;
                if (pylonSets <= stations.Max()) p.Add($"the tac screen has {pylonSets} pylon sets for HardpointIndex up to {stations.Max()}");
                foreach (var telemetry in screen.GetComponentsInChildren(GameType("EngineTelemetry"), true))
                {
                    var engineName = Prop(new SerializedObject(telemetry), "engineName").stringValue;
                    var carriers = b.Root.GetComponentsInChildren(GameType("Turbojet"), true).Where(t => t.gameObject.name == engineName && t.GetComponent(GameType("AeroPart")) != null).ToArray();
                    if (carriers.Length != 1) p.Add($"tac screen engine gauge names {engineName}, which {carriers.Length} engine parts carry");
                }
            }
            var so = new SerializedObject(parameters);
            if (Prop(so, "HUDExtras").objectReferenceValue != Load<GameObject>(DonorHudExtras)) p.Add("HUDExtras isn't the afterburner-and-airbrake HUD");
            var display = (GameObject)Prop(so, "StatusDisplay").objectReferenceValue;
            var images = display == null ? new string[0] : Enumerable.Range(0, Prop(new SerializedObject(display.GetComponent(GameType("StatusDisplay"))), "statusDisplays").arraySize)
                .Select(i => ((Component)Prop(new SerializedObject(display.GetComponent(GameType("StatusDisplay"))), "statusDisplays").GetArrayElementAtIndex(i).FindPropertyRelative("partImage").objectReferenceValue).gameObject.name).ToArray();
            var partNames = All(b, "AeroPart").Select(a => a.gameObject.name).ToArray();
            foreach (var image in images)
                if (partNames.Count(n => n == image) != 1) p.Add($"damage diagram image {image} matches {partNames.Count(n => n == image)} parts");
            if (images.Length == 0) p.Add("no damage diagram images");
            var cameras = new[] { "camMountForward", "camMountRear" }.Select(f => (Transform)Prop(new SerializedObject(b.Parts["radome"].GetComponent(GameType("TargetCam"))), f).objectReferenceValue).ToArray();
            var minimum = float.PositiveInfinity;
            foreach (var r in b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.gameObject.layer != 3))
                foreach (var camera in cameras)
                    minimum = Mathf.Min(minimum, Vector3.Distance(camera.position, r.bounds.ClosestPoint(camera.position)));
            if (minimum < CameraClearance - 0.01f) p.Add($"a target camera is {minimum:F2} m from the airframe, under {CameraClearance}");
            return $"aircraft links set, tac screen with {pylonSets} pylon sets for {stations.Length} stations and its engine gauges on the engine, HUD extras with afterburner and airbrake, {images.Length} diagram images on unique parts, target cameras {minimum:F2} m clear";
        }

        private static string CheckGear(Build b, List<string> p)
        {
            var gears = All(b, "LandingGear");
            if (gears.Length != 3) p.Add(gears.Length + " LandingGears");
            foreach (var g in gears)
            {
                var so = new SerializedObject(g);
                var part = Prop(so, "attachedPart").objectReferenceValue as Component;
                if (part == null || !part.name.StartsWith("gear_leg_", StringComparison.Ordinal) || !g.transform.IsChildOf(part.transform)) p.Add(g.name + " isn't carried by a gear_leg part");
                foreach (var field in new[] { "bumpStop", "unsprung", "axle", "gearCollider", "gearHinge", "tireNoiseSound", "tireSkidSound" })
                    if (Prop(so, field).objectReferenceValue == null) p.Add($"{g.name}.{field} is null");
                var wheels = GetList(Prop(so, "wheels")).Cast<Transform>().ToArray();
                if (wheels.Length == 0 || wheels.Any(w => w == null)) p.Add(g.name + " has no wheel or a null one");
                var hinge = Prop(so, "gearHinge").objectReferenceValue as Transform;
                if (part == null || hinge == null || wheels.Length == 0 || wheels[0] == null)
                    continue;
                var leg = Legs.FirstOrDefault(l => l.Leg == part.name);
                if (!hinge.IsChildOf(part.transform) || Quaternion.Angle(hinge.localRotation, Quaternion.identity) > 0.01f)
                    p.Add(g.name + "'s gear hinge isn't at rest on its gear_leg part");
                // A negative fold reads back near 360 through localEulerAngles.x as the leg locks down, which LandingGear
                // takes for a broken wheel above 10 degrees.
                if (Prop(so, "foldDegrees").floatValue <= 0f) p.Add($"{g.name} folds {Prop(so, "foldDegrees").floatValue} deg; stowing must be a positive turn");
                // BreakWheel takes the leg's mass from its carrier's Rigidbody.
                var carrier = GetFloat(part, "mass");
                if (Prop(so, "mass").floatValue <= 0f || Prop(so, "mass").floatValue >= carrier)
                    p.Add($"{g.name} breaks off with {Prop(so, "mass").floatValue} kg of its {carrier} kg carrier");
                if (leg.Doors == null || Prop(so, "gearDoors").arraySize != leg.Doors.Length) p.Add($"{g.name} lists {Prop(so, "gearDoors").arraySize} doors");
                // Stowing must carry the wheel up into the airframe.
                var down = wheels[0].position;
                hinge.localRotation = Quaternion.Euler(Prop(so, "foldDegrees").floatValue, 0, 0);
                var up = wheels[0].position;
                hinge.localRotation = Quaternion.identity;
                if (up.y - down.y < 0.2f) p.Add($"{g.name} stows its wheel {up.y - down.y:F2} m higher, not up into the airframe");
            }
            // Each leg's ground cast, castPoint down suspensionTravel, must meet no collider of the aircraft.
            Physics.SyncTransforms();
            var airframe = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger && !(c is MeshCollider m && m.sharedMesh == null)).ToArray();
            foreach (var g in gears)
            {
                var so = new SerializedObject(g);
                var cast = Prop(so, "castPoint").objectReferenceValue as Transform ?? ((GameObject)Prop(so, "bumpStop").objectReferenceValue).transform;
                var travel = Prop(so, "suspensionTravel").floatValue;
                foreach (var c in airframe)
                    if (c.Raycast(new Ray(cast.position, -cast.up), out var hit, travel))
                        p.Add($"{g.name}'s ground cast meets {PathOf(c.transform, b.Root.transform)} {hit.distance:F2} m down");
            }
            if (Mathf.Abs(b.Size.y - F104Height) > 0.5f) p.Add($"stance {b.Size.y:F2} m tall on its gear, not near the F-104G's {F104Height}");
            var filter = b.Parts["cockpit_cell"].GetComponent(GameType("ControlsFilter"));
            var noseGear = gears.OrderByDescending(g => g.transform.position.z).FirstOrDefault();
            var links = new List<Object>();
            var it = new SerializedObject(filter).GetIterator();
            while (it.Next(true))
                if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue != null && it.objectReferenceValue.GetType().Name == "LandingGear")
                    links.Add(it.objectReferenceValue);
            if (links.Count == 0 || links.Any(l => l != noseGear)) p.Add("ControlsFilter's nose gear link isn't the nose LandingGear");
            var contacts = Contacts(b);
            return $"{gears.Length} Revoker LandingGears driving the Icarus gear_leg hinges, wheels stow upward, doors listed, nose steering linked, {b.Size.y:F2} m tall at rest; free contacts {string.Join(", ", contacts.Select(c => c.Name + " " + c.Contact.ToString("F2")))}";
        }

        private static string CheckEscape(Build b, List<string> p)
        {
            var pilots = All(b, "Pilot");
            var listed = GetList(Prop(new SerializedObject(b.Aircraft), "pilots"));
            if (pilots.Length != 1 || listed.Length != 1 || listed[0] != pilots[0]) p.Add($"{pilots.Length} Pilots, Aircraft.pilots [{string.Join(", ", listed.Select(o => o == null ? "null" : o.name))}]");
            if (pilots.Length > 0 && !Prop(new SerializedObject(pilots[0]), "ejectionSeat").boolValue) p.Add("the pilot has no ejection seat");
            if (pilots.Length > 0 && Prop(new SerializedObject(pilots[0]), "unitPart").objectReferenceValue != b.Part("cockpit_cell")) p.Add("the pilot isn't on cockpit_cell");
            if (All(b, "EscapeCapsule").Length > 0) p.Add("an EscapeCapsule remains");
            var canopies = GetList(Prop(new SerializedObject(b.Aircraft), "canopies"));
            var canopy = b.Parts["canopy"].GetComponent(GameType("Canopy"));
            if (canopies.Length != 1 || canopies[0] != canopy) p.Add("Aircraft.canopies isn't the canopy part's Canopy");
            if (canopy != null)
            {
                var so = new SerializedObject(canopy);
                if (Prop(so, "attachedPart").objectReferenceValue != b.Part("canopy") || Prop(so, "ejectionTransform").objectReferenceValue != b.Parts["canopy"].transform) p.Add("the Canopy doesn't eject the canopy part");
                if (GetList(Prop(so, "glassRenderers")).Any(r => r == null)) p.Add("a null canopy glass renderer");
                var hinges = Prop(so, "canopyHinges");
                var hood = hinges.arraySize == 1 ? hinges.GetArrayElementAtIndex(0).FindPropertyRelative("transform").objectReferenceValue as Transform : null;
                if (hood == null || hood.parent != b.Parts["canopy"].transform || hinges.GetArrayElementAtIndex(0).FindPropertyRelative("hingeAngle").floatValue == 0)
                    p.Add("the canopy doesn't open its hood on the canopy hinge");
                // Canopy pushes along its part's forward x ejectionForce.z plus up x ejectionForce.y.
                var force = Prop(so, "ejectionForce").vector3Value;
                var push = b.Parts["canopy"].transform.forward * force.z + b.Parts["canopy"].transform.up * force.y;
                if (push.sqrMagnitude < 1f || Vector3.Dot(push.normalized, Vector3.up) < 0.9f)
                    p.Add($"the canopy ejects along {push.normalized}, not up out of the aircraft");
            }
            if (pilots.Length == 0)
                return "no pilot";
            // The seat rides its rail out after the canopy goes; the capsule must clear every other airframe collider.
            var crew = new HashSet<Collider>(pilots.SelectMany(x => x.GetComponentsInChildren<Collider>(true)));
            var airframe = b.Root.GetComponentsInChildren<Collider>(true)
                .Where(c => c.enabled && !c.isTrigger && !crew.Contains(c) && !c.transform.IsChildOf(b.Parts["canopy"].transform) && !(c is MeshCollider m && m.sharedMesh == null)).ToArray();
            var probe = new GameObject("escape_probe").AddComponent<CapsuleCollider>();
            try
            {
                probe.radius = CapsuleRadius;
                probe.height = CapsuleBelow + CapsuleAbove;
                probe.center = new Vector3(0, (CapsuleAbove - CapsuleBelow) / 2, 0);
                foreach (var rail in new[] { RailCollidable, RailEnd })
                {
                    probe.transform.position = pilots[0].transform.position + b.Parts["cockpit_cell"].transform.TransformDirection(SeatRail) * rail;
                    Physics.SyncTransforms();
                    foreach (var c in airframe)
                        if (Physics.ComputePenetration(probe, probe.transform.position, probe.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.001f)
                            p.Add($"the seat at {rail} m up its rail overlaps {PathOf(c.transform, b.Root.transform)} by {depth:F3} m");
                }
            }
            finally
            {
                Object.DestroyImmediate(probe.gameObject);
            }
            return $"one pilot with an ejection seat, no capsule, the canopy part ejects, the seat clears {airframe.Length} colliders at {RailCollidable} and {RailEnd} m";
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

        private static string CheckGraph(Build b, List<string> p)
        {
            var aeroType = GameType("AeroPart");
            var dangling = 0;
            foreach (var component in b.Root.GetComponentsInChildren<Component>(true))
            {
                if (component == null)
                {
                    p.Add("a missing script");
                    continue;
                }
                var it = new SerializedObject(component).GetIterator();
                while (it.Next(true))
                {
                    if (it.propertyType != SerializedPropertyType.ObjectReference)
                        continue;
                    var value = it.objectReferenceValue;
                    if (value == null && it.objectReferenceInstanceIDValue != 0)
                    {
                        dangling++;
                        p.Add($"dangling reference {PathOf(component.transform, b.Root.transform)}:{component.GetType().Name}.{it.propertyPath}");
                    }
                    else if (value != null && !EditorUtility.IsPersistent(value) && !Inside(b, value))
                        p.Add($"{PathOf(component.transform, b.Root.transform)}:{component.GetType().Name}.{it.propertyPath} points outside the prefab ({value.name})");
                }
            }
            var parts = b.Root.GetComponentsInChildren(aeroType, true);
            if (parts.Length != b.Specs.Count) p.Add($"{parts.Length} AeroParts, expected {b.Specs.Count}");
            var mass = parts.Sum(x => GetFloat(x, "mass"));
            if (Mathf.Abs(mass - EmptyMass) > 1f) p.Add($"AeroPart masses sum to {mass}, not {EmptyMass}");
            foreach (var part in parts)
            {
                var so = new SerializedObject(part);
                if (Prop(so, "parentUnit").objectReferenceValue != b.Aircraft) p.Add(part.name + ": parentUnit isn't the Aircraft");
                if (Prop(so, "mass").floatValue <= 0) p.Add(part.name + " has no mass");
                var joints = Prop(so, "joints");
                if (part.gameObject == b.Root)
                {
                    if (joints.arraySize != 0) p.Add("the root part has joints");
                    continue;
                }
                var parent = part.transform.parent.GetComponent(aeroType);
                if (parent == null) p.Add(part.name + " isn't a direct child of a part (UnitPart.Awake looks only at the parent)");
                else if (joints.arraySize == 0 || joints.GetArrayElementAtIndex(0).FindPropertyRelative("connectedPart").objectReferenceValue != parent) p.Add(part.name + ": joints[0] isn't its parent part");
                if (part.GetComponents<Collider>().Length == 0) p.Add(part.name + " has no collider");
            }
            foreach (var collider in b.Root.GetComponentsInChildren<MeshCollider>(true).Where(c => c.sharedMesh != null))
                if (!collider.convex) p.Add(PathOf(collider.transform, b.Root.transform) + " has a concave MeshCollider");
            var lod = b.Root.GetComponent<LODGroup>().GetLODs();
            if (lod.SelectMany(l => l.renderers).Any(r => r == null || !r.transform.IsChildOf(b.Root.transform))) p.Add("a LOD renderer outside the prefab");
            // After the braces, no two parts without a joint between them may overlap.
            var linked = new HashSet<(Object, Object)>();
            foreach (var part in parts)
            {
                var joints = Prop(new SerializedObject(part), "joints");
                for (var i = 0; i < joints.arraySize; i++)
                {
                    var other = joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue;
                    linked.Add((part, other));
                    linked.Add((other, part));
                }
            }
            Physics.SyncTransforms();
            var colliders = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger && !(c is MeshCollider m && m.sharedMesh == null))
                .Select(c => (collider: c, part: (Object)c.GetComponentInParent(aeroType, true))).ToArray();
            var overlaps = 0;
            for (var i = 0; i < colliders.Length; i++)
                for (var j = i + 1; j < colliders.Length; j++)
                {
                    var (a, pa) = colliders[i];
                    var (c, pc) = colliders[j];
                    if (pa == pc || linked.Contains((pa, pc)) || !a.bounds.Intersects(c.bounds))
                        continue;
                    if (Physics.ComputePenetration(a, a.transform.position, a.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.005f)
                    {
                        overlaps++;
                        p.Add($"unjointed overlap {depth:F3} m: {PathOf(a.transform, b.Root.transform)} and {PathOf(c.transform, b.Root.transform)}");
                    }
                }
            return $"{parts.Length} AeroParts, {mass:0} kg, every part jointed to its parent and collidable, convex hulls, {colliders.Length} colliders with {overlaps} unjointed overlaps, {dangling} dangling references, LOD in the prefab";
        }
    }
}
