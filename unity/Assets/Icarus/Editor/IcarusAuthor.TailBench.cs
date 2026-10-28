using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The game's physics, read from its globalgamemanagers (Unity 2022.3.62f2, the editor's own PhysX): a 1/60 s step,
        // PGS with 6 position and 1 velocity iterations, angular speed capped at 14 rad/s.
        private const float BenchStep = 1f / 60f;
        private const int BenchPositionIterations = 6, BenchVelocityIterations = 1;
        private const float BenchMaxAngularSpeed = 14f;

        private sealed class BenchCase
        {
            public string Name;
            public float G;          // the load factor the lifting surfaces carry, trimmed in pitch by the trim parts
            public float FinSide;    // N on the vertical surfaces, by area, along the aircraft's right
            public float Roll;       // N up on the left wing and down on the right (an aileron roll), applied for RollTime
            public float RollTime;
            public float Seconds;    // loads ramp in over the first half second; the last second is measured
            public float Thrust;     // N at the JetNozzle's thrust transform (thrust_vector) along its forward,
            public float VectorDeg;  // turned this far nose-down about its right, as full vectoring does
        }

        private static readonly BenchCase[] BenchCases =
        {
            new BenchCase { Name = "9 g pull", G = 9f, Seconds = 3f },
            new BenchCase { Name = "9 g pull, 5 kN fin side load", G = 9f, FinSide = 5000f, Seconds = 3f },
            new BenchCase { Name = "1 g, 5 kN fin side load", G = 1f, FinSide = 5000f, Seconds = 3f },
            new BenchCase { Name = "5 g pull, 20 kN aileron roll for 0.5 s", G = 5f, Roll = 20000f, RollTime = 0.5f, Seconds = 2f },
        };

        private sealed class BenchPart
        {
            public string Name;
            public Component Part;
            public Rigidbody Rb;
            public float WingArea;
            public Vector3 LiftUp;     // the lift normal's up, in the root's frame
            public Vector3 LiftOffset; // centerOfLift turned by the lift normal, in the part's frame: the game's lift acts there
        }

        // Rebuilds an aircraft prefab's complex physics the way Aircraft.SetComplexPhysics does (AeroPart.CreateRB, then
        // CreateJoints, with each anchor in body space as src/Icarus/JointAnchors.cs sets it when icarusAnchors) on a copy
        // in a preview scene of its own (its own physics scene, stepped here, so the project's simulation mode is left
        // alone), loads it as each case says and reports each watched part's turn against the root over the last second:
        // its mean roll about the fuselage axis, its largest turn about any axis (into worst, by "case part") and its
        // roll's peak-to-peak (wobble), with each joint's mean load there against its in-game break force.
        // stores: kg a part carries at its centre-of-mass marker besides its fuel (UnitPart.ModifyMass, as a mounted store's
        // mass is). seams: each outer part's point (a transform under it) whose movement in the inner part's frame, mm from
        // its rest, goes into worst by "case |seam| outer", with the outer part's joint load against its break force by
        // "case |load| outer" where the two are jointed, and its largest turn in the inner part's frame by "case |turn| outer
        // vs inner". loadOwners: parts whose every joint's load against its break force goes into worst by "case |joint|
        // owner -> part". cases: the bench cases to run, BenchCases by default.
        private static string RunTailBench(GameObject prefab, string[] watched, string[] trimParts, bool icarusAnchors, float fuelFraction, Dictionary<string, float> worst,
            Dictionary<string, float> stores = null, (string Outer, string Inner, string Point)[] seams = null, string[] loadOwners = null, BenchCase[] cases = null)
        {
            var report = new StringBuilder();
            foreach (var bench in cases ?? BenchCases)
            {
                var scene = EditorSceneManager.NewPreviewScene();
                try
                {
                    var copy = (GameObject)Object.Instantiate(prefab, Vector3.zero, Quaternion.identity);
                    SceneManager.MoveGameObjectToScene(copy, scene);
                    report.Append(BenchRun(copy, scene.GetPhysicsScene(), bench, watched, trimParts, icarusAnchors, fuelFraction, worst,
                        stores ?? new Dictionary<string, float>(), seams ?? new (string, string, string)[0], loadOwners ?? new string[0]));
                }
                finally
                {
                    EditorSceneManager.ClosePreviewScene(scene);
                }
            }
            return report.ToString();
        }

        private static string BenchRun(GameObject root, PhysicsScene physics, BenchCase bench, string[] watched, string[] trimParts, bool icarusAnchors,
            float fuelFraction, Dictionary<string, float> worst, Dictionary<string, float> stores, (string Outer, string Inner, string Point)[] seams,
            string[] loadOwners)
        {
            var parts = root.GetComponentsInChildren(GameType("AeroPart"), true)
                .ToDictionary(c => c.gameObject == root ? "root" : c.gameObject.name, c => new BenchPart { Name = c.gameObject.name, Part = c });
            if (!parts.ContainsKey("root"))
                throw new InvalidOperationException(root.name + ": no AeroPart on the root; are the game's scripts loaded?");
            foreach (var wheel in root.GetComponentsInChildren<WheelCollider>(true))
                Object.DestroyImmediate(wheel);
            foreach (var extra in root.GetComponentsInChildren<Rigidbody>(true).Where(r => r.gameObject != root))
                Object.DestroyImmediate(extra);
            var fuel = new Dictionary<Component, float>();
            foreach (var tank in root.GetComponentsInChildren(GameType("FuelTank"), true))
            {
                var so = new SerializedObject(tank);
                var host = (Component)Prop(so, "part").objectReferenceValue;
                if (host != null)
                    fuel[host] = (fuel.TryGetValue(host, out var f) ? f : 0) + Prop(so, "fuelCapacity").floatValue * fuelFraction;
            }
            foreach (var p in parts.Values)
            {
                var so = new SerializedObject(p.Part);
                var lift = (Transform)Prop(so, "liftNormal").objectReferenceValue;
                if (lift == null)
                    lift = p.Part.transform;
                p.WingArea = Prop(so, "wingArea").floatValue;
                p.LiftUp = root.transform.InverseTransformDirection(lift.up);
                p.LiftOffset = p.Part.transform.InverseTransformVector(lift.rotation * Prop(so, "centerOfLift").vector3Value);
            }
            // CreateRB: every part but the root leaves the hierarchy on a body of its own.
            foreach (var p in parts.Values.Where(p => p.Part.gameObject != root))
                p.Part.transform.SetParent(null, true);
            foreach (var p in parts.Values)
            {
                var so = new SerializedObject(p.Part);
                var rb = p.Part.GetComponent<Rigidbody>();
                if (rb == null)
                    rb = p.Part.gameObject.AddComponent<Rigidbody>();
                rb.isKinematic = false;
                rb.useGravity = false;
                rb.mass = Prop(so, "mass").floatValue + (fuel.TryGetValue(p.Part, out var kg) ? kg : 0) + (stores.TryGetValue(p.Name, out var store) ? store : 0);
                rb.drag = 0;
                rb.angularDrag = 0;
                rb.sleepThreshold = 0;
                rb.maxAngularVelocity = BenchMaxAngularSpeed;
                rb.solverIterations = BenchPositionIterations;
                rb.solverVelocityIterations = BenchVelocityIterations;
                rb.ResetCenterOfMass();
                rb.ResetInertiaTensor();
                // UnitPart.ModifyMass, from a tank's fuel.
                var com = (Transform)Prop(so, "centerOfMass").objectReferenceValue;
                var fuelled = (fuel.ContainsKey(p.Part) || stores.ContainsKey(p.Name)) && com != null;
                if (fuelled)
                    rb.centerOfMass = com.localPosition;
                SectionInertia.Pin(rb, SectionInertia.BoxesUnder(new[] { p.Part }), automaticCenter: !fuelled);
                p.Rb = rb;
            }
            // The Icarus's parts ignore one another (src/Icarus/SelfCollision.cs); stock parts sit apart.
            var colliders = parts.Values.Select(p => p.Part.GetComponentsInChildren<Collider>(true).Where(c => !c.isTrigger).ToArray()).ToArray();
            for (var i = 0; i < colliders.Length; i++)
                for (var j = i + 1; j < colliders.Length; j++)
                    foreach (var a in colliders[i])
                        foreach (var c in colliders[j])
                            Physics.IgnoreCollision(a, c);
            // CreateJoints, unbreakable here: the bench measures deflection and reports the load against the break force.
            var joints = new List<(string Owner, string To, FixedJoint Joint, float Break)>();
            var rbOf = parts.Values.ToDictionary(p => (Object)p.Part, p => p.Rb);
            foreach (var p in parts.Values)
            {
                var list = Prop(new SerializedObject(p.Part), "joints");
                for (var i = 0; i < list.arraySize; i++)
                {
                    var pj = list.GetArrayElementAtIndex(i);
                    var to = pj.FindPropertyRelative("connectedPart").objectReferenceValue;
                    if (to == null || !rbOf.ContainsKey(to))
                        continue;
                    var joint = p.Part.gameObject.AddComponent<FixedJoint>();
                    var anchor = (Transform)pj.FindPropertyRelative("anchor").objectReferenceValue;
                    if (anchor != null)
                        joint.anchor = icarusAnchors ? p.Part.transform.InverseTransformPoint(anchor.position) : anchor.position - p.Rb.position;
                    joint.connectedBody = rbOf[to];
                    joint.enableCollision = false;
                    var iterations = pj.FindPropertyRelative("solverIterations").intValue;
                    if (iterations != 6)
                        p.Rb.solverIterations = iterations;
                    joints.Add((p.Name, ((Component)to).gameObject.name, joint, pj.FindPropertyRelative("breakForce").floatValue * 10f));
                }
            }

            // Lift on the horizontal surfaces by area, and on the trim parts what zeroes the pitching moment about the centre
            // of mass: the load a trimmed pull puts on the airframe. Each acts where the game's does (centerOfLift).
            var rootRb = parts["root"].Rb;
            var bodies = parts.Values.ToArray();
            var mass = bodies.Sum(p => p.Rb.mass);
            var lifting = bodies.Where(p => p.WingArea > 0 && Mathf.Abs(p.LiftUp.y) > 0.7f && !trimParts.Contains(p.Name)).ToArray();
            var trim = bodies.Where(p => trimParts.Contains(p.Name)).ToArray();
            var fins = bodies.Where(p => p.WingArea > 0 && Mathf.Abs(p.LiftUp.x) > 0.7f).ToArray();
            Vector3 LiftPoint(BenchPart p) => p.Rb.worldCenterOfMass + p.Part.transform.TransformVector(p.LiftOffset);
            float Station(Vector3 world) => root.transform.InverseTransformPoint(world).z;
            var cg = bodies.Sum(p => Station(p.Rb.worldCenterOfMass) * p.Rb.mass) / mass;
            var area = lifting.Sum(p => p.WingArea);
            var liftArm = lifting.Sum(p => p.WingArea / area * (Station(LiftPoint(p)) - cg));
            var trimArm = trim.Average(p => Station(LiftPoint(p)) - cg);
            var total = bench.G * 9.81f * mass;
            var trimLift = -total * liftArm / (trimArm - liftArm); // wing + trim = total, wing * liftArm + trim * trimArm = 0
            var wingLift = total - trimLift;
            var finArea = fins.Sum(p => p.WingArea);

            Quaternion Relative(Rigidbody rb) => Quaternion.Inverse(rootRb.rotation) * rb.rotation;
            var watch = watched.Where(parts.ContainsKey).ToArray();
            var rest = watch.ToDictionary(n => n, n => Relative(parts[n].Rb));
            var turns = watch.ToDictionary(n => n, n => new List<(float Angle, float Roll)>());
            var seamPoints = seams.Where(s => parts.ContainsKey(s.Outer) && parts.ContainsKey(s.Inner))
                .Select(s => (s.Outer, s.Inner, Point: FindDeep(parts[s.Outer].Part.transform, s.Point))).Where(s => s.Point != null).ToArray();
            Vector3 InInner((string Outer, string Inner, Transform Point) s) => parts[s.Inner].Part.transform.InverseTransformPoint(s.Point.position);
            Quaternion TurnIn((string Outer, string Inner, Transform Point) s) => Quaternion.Inverse(parts[s.Inner].Rb.rotation) * parts[s.Outer].Rb.rotation;
            var seamRest = seamPoints.ToDictionary(s => s, InInner);
            var seamTurnRest = seamPoints.ToDictionary(s => s, TurnIn);
            var seamMoved = seamPoints.ToDictionary(s => s, s => 0f);
            var seamTurned = seamPoints.ToDictionary(s => s, s => 0f);
            // the JetNozzle's thrust transform, under the nozzle part, with each part now a body of its own
            var thrustAt = bench.Thrust > 0 ? parts.Values.Select(p => p.Part.transform.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == "thrust_vector"))
                .FirstOrDefault(t => t != null) ?? throw new InvalidOperationException(root.name + ": no thrust_vector to push") : null;
            var thrustBody = thrustAt == null ? null : thrustAt.GetComponentInParent<Rigidbody>();
            var load = joints.ToDictionary(j => j.Joint, j => (Force: 0f, Torque: 0f, Samples: 0));
            var steps = Mathf.RoundToInt(bench.Seconds / BenchStep);
            for (var step = 0; step < steps; step++)
            {
                var t = step * BenchStep;
                var ramp = Mathf.Clamp01(t / 0.5f);
                var up = rootRb.rotation * Vector3.up * ramp;
                var right = rootRb.rotation * Vector3.right * ramp;
                foreach (var p in lifting)
                    p.Rb.AddForceAtPosition(up * wingLift * p.WingArea / area, LiftPoint(p));
                foreach (var p in trim)
                    p.Rb.AddForceAtPosition(up * trimLift / trim.Length, LiftPoint(p));
                foreach (var p in fins)
                    p.Rb.AddForceAtPosition(right * bench.FinSide * p.WingArea / finArea, LiftPoint(p));
                if (thrustAt != null)
                    thrustBody.AddForceAtPosition(Quaternion.AngleAxis(bench.VectorDeg, thrustAt.right) * thrustAt.forward * bench.Thrust * ramp, thrustAt.position);
                if (t >= 0.5f && t < 0.5f + bench.RollTime)
                    foreach (var p in lifting.Where(p => p.WingArea > 1f))
                        p.Rb.AddForce(up * bench.Roll * -Mathf.Sign(root.transform.InverseTransformPoint(p.Rb.worldCenterOfMass).x) / 2f);
                physics.Simulate(BenchStep);
                if (t < bench.Seconds - 1f)
                    continue;
                foreach (var j in joints)
                {
                    var l = load[j.Joint];
                    load[j.Joint] = (l.Force + j.Joint.currentForce.magnitude, l.Torque + j.Joint.currentTorque.magnitude, l.Samples + 1);
                }
                foreach (var s in seamPoints)
                {
                    seamMoved[s] = Mathf.Max(seamMoved[s], (InInner(s) - seamRest[s]).magnitude * 1000f);
                    seamTurned[s] = Mathf.Max(seamTurned[s], TurnAngle(seamTurnRest[s], TurnIn(s)));
                }
                foreach (var n in watch)
                {
                    (Relative(parts[n].Rb) * Quaternion.Inverse(rest[n])).ToAngleAxis(out var angle, out var axis);
                    if (angle > 180f) angle -= 360f;
                    turns[n].Add((Mathf.Abs(angle), angle * Vector3.Dot(axis, Vector3.forward)));
                }
            }

            var line = new StringBuilder($"  {bench.Name} ({mass:0} kg, wing {wingLift / 1000:0.0} kN, trim {trimLift / 1000:0.0} kN):");
            foreach (var n in watch)
            {
                var s = turns[n];
                worst[bench.Name + " " + n] = s.Max(x => x.Angle);
                line.Append($" {n} roll {s.Average(x => x.Roll):+0.00;-0.00} deg, max {s.Max(x => x.Angle):0.00}, wobble {s.Max(x => x.Roll) - s.Min(x => x.Roll):0.00};");
            }
            float Share((string Owner, string To, FixedJoint Joint, float Break) j) =>
                Mathf.Max(load[j.Joint].Force, load[j.Joint].Torque) / load[j.Joint].Samples / j.Break;
            foreach (var s in seamPoints)
            {
                worst[bench.Name + " |seam| " + s.Outer + " vs " + s.Inner] = seamMoved[s];
                worst[bench.Name + " |turn| " + s.Outer + " vs " + s.Inner] = seamTurned[s];
                line.Append($" {s.Outer} {s.Point.name} {seamMoved[s]:0.00} mm and {seamTurned[s]:0.0000} deg off {s.Inner}");
                var j = joints.FirstOrDefault(x => x.Owner == s.Outer && x.To == s.Inner);
                if (j.Joint != null)
                {
                    worst[bench.Name + " |load| " + s.Outer] = Share(j);
                    line.Append($", joint at {Share(j):0.00} of its break");
                }
                line.Append(";");
            }
            foreach (var j in joints.Where(j => loadOwners.Contains(j.Owner)))
                worst[$"{bench.Name} |joint| {j.Owner} -> {j.To}"] = Share(j);
            line.AppendLine();
            foreach (var j in joints.Where(j => watch.Contains(j.Owner) || watch.Contains(j.To) || seamPoints.Any(s => s.Outer == j.Owner) || loadOwners.Contains(j.Owner)))
                line.AppendLine($"    joint {j.Owner} -> {j.To}: {load[j.Joint].Force / load[j.Joint].Samples / 1000:0.0} kN, {load[j.Joint].Torque / load[j.Joint].Samples / 1000:0.0} kN m (breaks at {j.Break / 1000:0} in game)");
            return line.ToString();
        }

        // The most an Icarus tail part may turn against the root on the bench (check A18). Stock tails stay under half a
        // degree (the Revoker's fin 0.34, the Vagrant's elevator 0.19); with the fin skin, rudder and stabilator on fin_spar
        // alone they sat 8 deg rolled off the root in a 9 g pull and reached 21.
        private const float TailFlexLimitDeg = 1f;
        private static readonly string[] TailParts = { "fin_spar", "fin_skin", "rudder", "stabilator" };

        private static string CheckTailStiffness(Build b, List<string> p)
        {
            var worst = new Dictionary<string, float>();
            RunTailBench(b.Root, TailParts, new[] { "stabilator" }, true, 0.5f, worst, null, null, new[] { "fin_spar", "fuselage_tail", "engine_core" });
            var loads = worst.Where(w => w.Key.Contains(" |joint| ")).ToArray();
            foreach (var w in worst.Except(loads).Where(w => w.Value > TailFlexLimitDeg))
                p.Add($"{w.Key}: turns {w.Value:0.00} deg against the root, over {TailFlexLimitDeg}");
            foreach (var w in loads.Where(w => w.Value > NozzleLoadLimit))
                p.Add($"{w.Key} {w.Value:0.00} of its break, over {NozzleLoadLimit}");
            var top = worst.Except(loads).OrderByDescending(w => w.Value).First();
            return $"{string.Join(", ", TailParts)} within {TailFlexLimitDeg} deg of the root in {BenchCases.Length} bench cases at half fuel; worst {top.Key} {top.Value:0.00} deg"
                + "; " + CheckCrankSeam(b, p) + "; " + CheckNozzleBench(b, p);
        }

        // The outer wing box hangs on the inner at the crank, and the wingtip station's store rides it (a full tip tank is
        // 570 kg, an empty one 70; art/blender/tip_tanks.py): its joint may carry at most half its break force on any bench
        // case, empty and full. Its tip's movement against the inner box, the physical seam where the two meet, is reported:
        // no solver setting or second brace brought it under 5 mm with a full tank (4.3 mm empty and 6.3 full at 48
        // position and 16 velocity iterations, 5.3 and 8.1 as the game runs them), so src/Icarus/WingSkinFollow.cs draws
        // the outer box on the inner while they are jointed and the seam never shows.
        private const float CrankLoadLimit = 0.5f;
        private static readonly float[] TipStores = { 70f, 570f };

        // The nozzle hangs on the afterburner, which hangs on the engine core, and the nozzle carries the thrust (JetNozzle on
        // its part): under full afterburner (65 kN core and 45 afterburner), vectored to its 4 degree limit, in a 9 g pull,
        // the core's, afterburner's, nozzle's and tail cone's joints, and the root braces of the core, tail cone and fin,
        // carry at most NozzleLoadLimit of their break forces. Reported: the thrust line's turn (the nozzle against the
        // root), and the physical seams of the fixed shroud (the nozzle part's own mesh) against each aft rear skin panel it
        // ends in and of the tail cone against the aft core. No brace held the shroud within 3 mm of the tail cone's skin
        // (17 mm with the root braces, 8 before the tail cone split off), so src/Icarus/WingSkinFollow.cs draws the tail cone
        // on the aft core, and the afterburner and nozzle on the tail cone, while they are jointed.
        private const float NozzleLoadLimit = 0.7f;
        private static readonly BenchCase[] NozzleCases =
        {
            new BenchCase { Name = "9 g pull, full afterburner vectored 4 deg", G = 9f, Thrust = 110000f, VectorDeg = 4f, Seconds = 3f },
            new BenchCase { Name = "1 g, full afterburner vectored 4 deg", G = 1f, Thrust = 110000f, VectorDeg = 4f, Seconds = 3f },
        };

        // The angle between two rotations, in degrees, exact for small turns (Quaternion.Angle reads 0 below about 0.16).
        private static float TurnAngle(Quaternion a, Quaternion b)
        {
            var d = Quaternion.Inverse(a) * b;
            return 2f * Mathf.Atan2(new Vector3(d.x, d.y, d.z).magnitude, Mathf.Abs(d.w)) * Mathf.Rad2Deg;
        }

        private static string CheckNozzleBench(Build b, List<string> p)
        {
            var worst = new Dictionary<string, float>();
            var seams = new[] { ("nozzle", "skin_aft_rear_L", "nozzle"), ("nozzle", "skin_aft_rear_R", "nozzle"), ("fuselage_tail", "fuselage_aft", "fuselage_tail"),
                ("nozzle", "root", "thrust_vector") };
            Debug.Log("[Icarus] nozzle bench:\n" + RunTailBench(b.Root, new string[0], new[] { "stabilator" }, true, 0.5f, worst, null, seams,
                new[] { "engine_core", "engine_afterburner", "nozzle", "fuselage_tail", "fin_spar" }, NozzleCases));
            KeyValuePair<string, float> Worst(string kind, string pair) =>
                worst.Where(w => w.Key.Contains($" |{kind}| ") && w.Key.EndsWith(pair)).OrderByDescending(w => w.Value).First();
            var shroud = Worst("seam", "vs skin_aft_rear_L").Value > Worst("seam", "vs skin_aft_rear_R").Value ? Worst("seam", "vs skin_aft_rear_L") : Worst("seam", "vs skin_aft_rear_R");
            var cone = Worst("seam", "fuselage_tail vs fuselage_aft");
            var coneTurn = Worst("turn", "fuselage_tail vs fuselage_aft");
            var thrust = Worst("turn", "nozzle vs root");
            var load = worst.Where(w => w.Key.Contains(" |joint| ")).OrderByDescending(w => w.Value).First();
            if (load.Value > NozzleLoadLimit) p.Add($"{load.Key} {load.Value:0.00} of its break, over {NozzleLoadLimit}");
            return $"thrust line turns {thrust.Value:0.00} deg ({thrust.Key}); physical seams: shroud {shroud.Value:0.00} mm ({shroud.Key}), tail cone {cone.Value:0.00} mm and " +
                $"{coneTurn.Value:0.00} deg ({cone.Key}); {load.Key} {load.Value:0.00}";
        }

        private static string CheckCrankSeam(Build b, List<string> p)
        {
            var seams = new[] { "L", "R" }.Select(s => ("wing_spar_outer_" + s, "wing_spar_" + s, "hardpoint_wingtip_" + s)).ToArray();
            var lines = new List<string>();
            foreach (var kg in TipStores)
            {
                var worst = new Dictionary<string, float>();
                var stores = seams.ToDictionary(s => s.Item1, s => kg);
                Debug.Log($"[Icarus] crank bench, tip stores {kg} kg:\n" + RunTailBench(b.Root, new string[0], new[] { "stabilator" }, true, 0.5f, worst, stores, seams));
                var seam = worst.Where(w => w.Key.Contains(" |seam| ")).OrderByDescending(w => w.Value).First();
                var load = worst.Where(w => w.Key.Contains(" |load| ")).OrderByDescending(w => w.Value).First();
                if (load.Value > CrankLoadLimit) p.Add($"tip stores {kg} kg: {load.Key} {load.Value:0.00} of its break, over {CrankLoadLimit}");
                lines.Add($"tip stores {kg} kg: physical seam {seam.Value:0.00} mm ({seam.Key}), {load.Key} {load.Value:0.00}");
            }
            return "wing crank " + string.Join("; ", lines);
        }

        // Batch entry, which authors nothing: pwsh tools/Build-Icarus.ps1 -ExecuteMethod Icarus.Editor.IcarusAuthor.TailBenchFromBatch
        // (B0's verdict then reads FAIL for the missing checks; the bench is the "[Icarus] tail bench" block in the Unity log).
        // Benches the saved Icarus prefab, any older Icarus prefab copied into Assets/IcarusBench (git show
        // <commit>:unity/Assets/Blueprinter/Mods/icarus/Icarus.prefab), and the stock Revoker and Vagrant, at half fuel.
        public static void TailBenchFromBatch()
        {
            IcarusBuild.InitializeGameTasks();
            var worst = new Dictionary<string, float>();
            var watched = TailParts.Append("fuselage_aft").ToArray();
            var log = new StringBuilder("[Icarus] tail bench\n");
            log.Append("Icarus:\n").Append(RunTailBench(Load<GameObject>(PrefabPath), watched, new[] { "stabilator" }, true, 0.5f, worst));
            foreach (var guid in AssetDatabase.IsValidFolder("Assets/IcarusBench") ? AssetDatabase.FindAssets("t:Prefab", new[] { "Assets/IcarusBench" }) : new string[0])
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                log.Append(path + ":\n").Append(RunTailBench(Load<GameObject>(path), watched, new[] { "stabilator" }, true, 0.5f, worst));
            }
            log.Append("Revoker FS-12:\n").Append(RunTailBench(Load<GameObject>(DonorPrefab), new[] { "vstab1", "vstab2", "rudder", "tail" }, new[] { "canard_L", "canard_R" }, false, 0.5f, worst));
            log.Append("Vagrant VT-7:\n").Append(RunTailBench(Load<GameObject>(Stock + "GameObject/VTOLTrainer1_PLACEHOLDER.prefab"), new[] { "vstab1", "vstab2", "elevator_L", "tail" }, new[] { "elevator_L", "elevator_R" }, false, 0.5f, worst));
            Debug.Log(log.ToString());
        }
    }
}
