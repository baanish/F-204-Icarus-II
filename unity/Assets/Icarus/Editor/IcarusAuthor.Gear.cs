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
        // The gear is the export's own: each leg a hinge (the gear_leg part) with its sprung mesh, a second fold under it
        // (gear_wheel: the main gear's knee, the nose gear's twist) that LandingGear turns through movingParts, and hinged
        // doors. What rides the second fold: the main gear's oleo (gear_arm), the bump stop, the unsprung transform with
        // the piston, axle and fork (gear_unsprung) and the wheel. The Revoker's LandingGear keeps its suspension, brakes,
        // steering, audio and chocks and drives the Icarus hinges. The bump stop sits GearStroke above the free wheel's
        // centre, straight up.
        private const float GearStroke = 0.3f, GearMaxCompression = 0.5f, GearHingeBox = 0.15f;
        // The share of a leg's carrier mass that leaves with it when the wheel breaks off: LandingGear.BreakWheel takes
        // LandingGear.mass from the carrier's Rigidbody and gives it to the falling leg, so it must stay under the carrier's.
        private const float GearBreakShare = 0.5f;
        // Each leg's gear-down drag, which LandingGear adds through its host part: about the F-104's 0.02 rise in CD0 on 18.2 m2, or
        // 0.36 m2 of CdA, which the game counts as twice that in dragArea.
        private static readonly Dictionary<string, float> GearExtendedDrag = new Dictionary<string, float>
        {
            { "gear_leg_N", 0.18f }, { "gear_leg_L", 0.275f }, { "gear_leg_R", 0.275f },
        };
        private static readonly (string Leg, string Rig, string[] Leftovers, string Wheel, string[] Doors)[] Legs =
        {
            ("gear_leg_N", "gearHinge_F", new[] { "gear_F_armTarget" }, "gear_wheel_N", new[] { "gear_door_N_L", "gear_door_N_R", "gear_door_N2_L", "gear_door_N2_R" }),
            ("gear_leg_L", "gearMount_L", new[] { "gear_armtarget_L" }, "gear_wheel_L", new[] { "gear_door_main_L", "gear_door_flap_L" }),
            ("gear_leg_R", "gearMount_R", new[] { "gear_armtarget_R" }, "gear_wheel_R", new[] { "gear_door_main_R", "gear_door_flap_R" }),
        };
        // The F-104G's height to the stabilator top, which the stance should come out near.
        private const float F104Height = 4.12f;

        // A tyre's centre, axle (its mesh's least-spread direction, pointing right) and radius, in world space.
        private static (Vector3 Centre, Vector3 Axle, float Radius) WheelOf(Transform t, Mesh mesh)
        {
            var points = WorldVertices(t, mesh);
            var centre = BoundsOf(points).center;
            var a = new double[3, 3];
            foreach (var p in points)
            {
                var d = p - centre;
                for (var i = 0; i < 3; i++)
                    for (var j = 0; j < 3; j++)
                        a[i, j] += d[i] * d[j];
            }
            // Jacobi sweeps: the eigenvector of the smallest eigenvalue is the axle.
            var v = new double[3, 3] { { 1, 0, 0 }, { 0, 1, 0 }, { 0, 0, 1 } };
            for (var sweep = 0; sweep < 50; sweep++)
                for (var p = 0; p < 2; p++)
                    for (var q = p + 1; q < 3; q++)
                    {
                        if (Math.Abs(a[p, q]) < 1e-12)
                            continue;
                        var theta = (a[q, q] - a[p, p]) / (2 * a[p, q]);
                        var tan = (theta >= 0 ? 1 : -1) / (Math.Abs(theta) + Math.Sqrt(theta * theta + 1));
                        var c = 1 / Math.Sqrt(tan * tan + 1);
                        var s = tan * c;
                        for (var k = 0; k < 3; k++)
                        {
                            double kp = a[k, p], kq = a[k, q];
                            a[k, p] = c * kp - s * kq;
                            a[k, q] = s * kp + c * kq;
                        }
                        for (var k = 0; k < 3; k++)
                        {
                            double pk = a[p, k], qk = a[q, k];
                            a[p, k] = c * pk - s * qk;
                            a[q, k] = s * pk + c * qk;
                        }
                        for (var k = 0; k < 3; k++)
                        {
                            double kp = v[k, p], kq = v[k, q];
                            v[k, p] = c * kp - s * kq;
                            v[k, q] = s * kp + c * kq;
                        }
                    }
            var m = Enumerable.Range(0, 3).OrderBy(i => a[i, i]).First();
            var axle = new Vector3((float)v[0, m], (float)v[1, m], (float)v[2, m]).normalized;
            if (axle.x < 0)
                axle = -axle;
            var radius = points.Max(p => Vector3.ProjectOnPlane(p - centre, axle).magnitude);
            return (centre, axle, radius);
        }

        // A frame with local X along axle and Y as near up as the axle allows.
        private static Quaternion AxleFrame(Vector3 axle)
        {
            var up = Vector3.ProjectOnPlane(Vector3.up, axle).normalized;
            return Quaternion.LookRotation(Vector3.Cross(axle, up), up);
        }

        private const string Unsprung = "gear_unsprung_", Arm = "gear_arm_";

        // The export gives each fold's travel_deg and where the wheel lies stowed (gear_wheel's stowed_wheel, Blender
        // world space); which way each turn goes in Unity's frames is taken from that: the senses of the leg's fold and
        // the second fold that put the wheel nearest it. Returns the signed fold about the leg hinge's X and the second
        // fold's turn about its own X.
        private static (float Fold, float Second) FoldSenses(Build b, Transform legFrame, string leg, string wheelName, Vector3 centre)
        {
            var stowed = (List<object>)b.Blockout.Parts[wheelName].Props["stowed_wheel"];
            var target = new Vector3(-Convert.ToSingle(stowed[0]), Convert.ToSingle(stowed[2]), -Convert.ToSingle(stowed[1])) - b.Blockout.Origin;
            var fold = b.Blockout.Parts[leg].Number("travel_deg");
            var second = b.Blockout.Parts[wheelName].Number("travel_deg");
            var pivot = b.Blockout.Local(wheelName);
            var secondAxis = b.Blockout.Rotation(wheelName) * Vector3.right;
            var best = (Miss: float.MaxValue, Fold: 0f, Second: 0f);
            foreach (var s1 in new[] { 1f, -1f })
                foreach (var s2 in new[] { 1f, -1f })
                {
                    var p = pivot + Quaternion.AngleAxis(s2 * second, secondAxis) * (centre - pivot);
                    p = legFrame.position + Quaternion.AngleAxis(s1 * fold, legFrame.right) * (p - legFrame.position);
                    if ((p - target).magnitude < best.Miss)
                        best = ((p - target).magnitude, s1 * fold, s2 * second);
                }
            if (best.Miss > 0.01f)
                throw new InvalidDataException($"{leg}: no sense of its two folds stows the wheel where the export does ({best.Miss:F3} m off)");
            return (best.Fold, best.Second);
        }

        private static void BuildGear(Build b)
        {
            var lines = new List<string>();
            var gearType = GameType("LandingGear");
            foreach (var (leg, rigName, leftovers, wheelName, doorNames) in Legs)
            {
                var part = b.Parts[leg].transform;
                var tyreName = wheelName + "_visible";
                var probe = new GameObject("wheel_probe").transform;
                probe.SetPositionAndRotation(b.Blockout.Local(tyreName), b.Blockout.Rotation(tyreName));
                var (centre, axle, radius) = WheelOf(probe, b.Meshes[tyreName].Render);
                Object.DestroyImmediate(probe.gameObject);
                var (fold, knee) = FoldSenses(b, part, leg, wheelName, centre);
                // LandingGear reads the hinge back through localEulerAngles.x and breaks the wheel above 10 degrees
                // (LandingGear.cs:620), so a negative fold, read as about 359 near full extension, would break a leg
                // touching down just before it locks: a leg that stows the other way turns about its reversed axis.
                // The rig (hinge, bump stop, ground cast, wheel) rides the part the suspension pushes on, as the Centurion's
                // and the Revoker's do. Under the leg part, a body of its own on a joint, the cast swung with the leg while
                // the force went to the host, and the jet reared up as soon as it rolled.
                var carrier = b.Specs.First(s => s.Name == leg).Parent;
                var mount = new GameObject(leg + "_mount") { layer = part.gameObject.layer }.transform;
                mount.SetParent(b.Parts[carrier].transform, false);
                mount.SetPositionAndRotation(part.position, part.rotation);
                var (_, hinge, strut) = HingeRig(b, leg, null, mount, flip: fold < 0);
                fold = Mathf.Abs(fold);
                // LandingGear finds the ground with a linecast that also sees the aircraft's own colliders (layer 14), so
                // a strut collider over the wheel would read as full compression and lock the leg. The part keeps a small
                // box at its hinge in the well; the strut's export pieces go unused.
                foreach (var piece in part.GetComponents<MeshCollider>())
                    Object.DestroyImmediate(piece);
                part.gameObject.AddComponent<BoxCollider>().size = Vector3.one * GearHingeBox;

                var rig = b.Root.transform.Find(rigName) ?? throw new MissingReferenceException("rescued gear rig " + rigName);
                var gear = rig.GetComponentInChildren(gearType, true);
                var so = new SerializedObject(gear);
                var bump = ((GameObject)Prop(so, "bumpStop").objectReferenceValue).transform;
                var unsprung = ((GameObject)Prop(so, "unsprung").objectReferenceValue).transform;
                var cast = (Transform)Prop(so, "castPoint").objectReferenceValue;
                var axleT = (Transform)Prop(so, "axle").objectReferenceValue;
                var wheels = GetList(Prop(so, "wheels")).Cast<Transform>().ToArray();
                var chocks = FindDeep(rig, "chocks");
                var effects = new[] { "dust", "tireNoiseSound", "tireSkidSound" }.Select(f => Prop(so, f).objectReferenceValue as Component)
                    .Where(c => c != null).Select(c => c.transform).ToArray();

                // The Revoker's sprung leg moves onto the Icarus hinge, and its bump stop, unsprung, axle, wheels and chocks
                // onto the second fold under it; its strut, tyre and arm meshes go.
                var travel = radius + GearStroke;
                gear.transform.SetParent(hinge, false);
                gear.transform.SetPositionAndRotation(part.position, Quaternion.identity);
                var foldFrame = new GameObject(wheelName) { layer = part.gameObject.layer }.transform;
                foldFrame.SetParent(gear.transform, false);
                foldFrame.SetPositionAndRotation(b.Blockout.Local(wheelName), b.Blockout.Rotation(wheelName));
                b.Visuals[wheelName] = foldFrame;
                var secondFold = new GameObject(wheelName + "_hinge") { layer = part.gameObject.layer }.transform;
                secondFold.SetParent(foldFrame, false);
                var arm = Arm + leg.Substring(leg.Length - 1);
                if (b.Blockout.HasMesh(arm))
                    MeshVisual(b, arm, secondFold);
                bump.SetParent(secondFold, false);
                bump.SetPositionAndRotation(centre + Vector3.up * (travel - radius), Quaternion.identity);
                if (cast != null)
                {
                    cast.SetParent(bump, false);
                    cast.localPosition = Vector3.zero;
                    cast.localRotation = Quaternion.identity;
                }
                unsprung.SetParent(bump, false);
                unsprung.localRotation = Quaternion.identity;
                unsprung.position = centre;
                axleT.SetParent(unsprung, false);
                axleT.SetPositionAndRotation(centre, AxleFrame(axle));
                // The piston, axle and fork slide with the suspension (LandingGear moves unsprung up its bump stop).
                MeshVisual(b, Unsprung + leg.Substring(leg.Length - 1), unsprung);
                foreach (var wheel in wheels)
                {
                    wheel.SetParent(unsprung, false);
                    wheel.SetPositionAndRotation(centre, AxleFrame(axle));
                }
                MeshVisual(b, tyreName, wheels[0]);
                foreach (var effect in effects.Where(e => !wheels.Contains(e) && e != unsprung && e != axleT && e != bump))
                {
                    effect.SetParent(unsprung, false);
                    effect.position = centre - Vector3.up * radius;
                }
                chocks.SetParent(unsprung, false);
                chocks.SetPositionAndRotation(centre - Vector3.up * radius, Quaternion.identity);
                b.Placed.Add(chocks);

                var kept = new HashSet<Transform>(new[] { gear.transform, bump, unsprung, axleT, chocks }.Concat(wheels).Concat(effects).Where(t => t != null));
                if (cast != null)
                    kept.Add(cast);
                var doomed = new List<Object> { rig.gameObject };
                doomed.AddRange(leftovers.Select(n => (Object)(b.Root.transform.Find(n) ?? throw new MissingReferenceException("rescued " + n)).gameObject));
                foreach (var t in kept.Where(t => t != chocks))
                {
                    doomed.AddRange(t.GetComponents<MeshRenderer>());
                    doomed.AddRange(t.GetComponents<MeshFilter>());
                    // Revoker children of the kept transforms (arms, struts) that nothing above keeps.
                    doomed.AddRange(t.Cast<Transform>().Where(c => !kept.Contains(c) && !b.Visuals.ContainsValue(c)).Select(c => (Object)c.gameObject));
                }
                DestroyWithReferences(b, doomed);

                // The gear collider (used once a leg breaks off) round the strut and tyre.
                var box = gear.GetComponent<BoxCollider>();
                if (box != null)
                {
                    var hull = strut.bounds;
                    hull.Encapsulate(new Bounds(centre, Vector3.one * 2 * radius));
                    box.center = hull.center - gear.transform.position;
                    box.size = hull.size;
                }

                var doors = new List<(Transform Hinge, float Open)>();
                foreach (var door in doorNames)
                {
                    var host = b.Parts[b.Blockout.Parts[door].BlenderParent].transform;
                    var (frame, doorHinge, panel) = HingeRig(b, door, host);
                    // The export opens each door to open_centre (Blender world space): a main door and the nose doors
                    // hang down, a main flap folds up against the lobe.
                    var opened = (List<object>)b.Blockout.Parts[door].Props["open_centre"];
                    var target = new Vector3(-Convert.ToSingle(opened[0]), Convert.ToSingle(opened[2]), -Convert.ToSingle(opened[1])) - b.Blockout.Origin;
                    var (open, _) = Travel(b, frame, panel.bounds.center, door, p => -(p - target).magnitude);
                    doors.Add((doorHinge, open));
                }

                // LandingGear pushes its suspension on attachedPart alone, so as on the Revoker (mains on a 300 kg wing root,
                // nose on the 350 kg cockpit) that is the heavy part the leg hangs on, not the light leg part: on the leg,
                // the Revoker's dampers flung it on its joint until the joint broke. The leg part stays a damageable part.
                so = new SerializedObject(gear);
                Prop(so, "attachedPart").objectReferenceValue = b.Part(carrier);
                Prop(so, "gearHinge").objectReferenceValue = hinge;
                Prop(so, "hingeFoldMotion").vector3Value = Vector3.zero;
                Prop(so, "foldDegrees").floatValue = fold;
                Prop(so, "strutRotationTransform").objectReferenceValue = null;
                Prop(so, "strutRotation").floatValue = 0f;
                Prop(so, "joints").arraySize = 0;
                Prop(so, "suspensionTravel").floatValue = travel;
                Prop(so, "wheelRadius").floatValue = radius;
                Prop(so, "maxCompression").floatValue = GearMaxCompression;
                // LandingGear writes extendedDrag over the host's whole dragArea, so it carries the host's own share and the
                // drag of every leg on that host (both mains write the same value onto the root).
                var extendedDrag = (DragAreas.TryGetValue(carrier, out var carrierDrag) ? carrierDrag : 0f)
                    + Legs.Where(l => b.Specs.First(s => s.Name == l.Leg).Parent == carrier).Sum(l => GearExtendedDrag[l.Leg]);
                Prop(so, "extendedDrag").floatValue = extendedDrag;
                Prop(so, "mass").floatValue = GearBreakShare * b.Mass[leg];
                var moving = Prop(so, "movingParts");
                moving.arraySize = 1;
                {
                    var entry = moving.GetArrayElementAtIndex(0);
                    entry.FindPropertyRelative("transform").objectReferenceValue = secondFold;
                    entry.FindPropertyRelative("target").objectReferenceValue = null;
                    entry.FindPropertyRelative("foldAngles").vector3Value = new Vector3(knee, 0, 0);
                }
                var gearDoors = Prop(so, "gearDoors");
                gearDoors.arraySize = doors.Count;
                for (var i = 0; i < doors.Count; i++)
                {
                    var entry = gearDoors.GetArrayElementAtIndex(i);
                    entry.FindPropertyRelative("transform").objectReferenceValue = doors[i].Hinge;
                    entry.FindPropertyRelative("closedAngle").vector3Value = Vector3.zero;
                    entry.FindPropertyRelative("openAngle").vector3Value = new Vector3(doors[i].Open, 0, 0);
                }
                so.ApplyModifiedPropertiesWithoutUndo();
                lines.Add($"{leg}: tyre r {radius:F3} m at {centre}, axle {axle}, travel {travel:F2} m, fold {fold:+0.0;-0.0} deg, second fold {knee:+0.0;-0.0} deg, breaks off with {GearBreakShare * b.Mass[leg]:0} of its {b.Mass[leg]:0} kg, doors [{string.Join(", ", doors.Select(d => d.Hinge.name + " " + d.Open.ToString("+0;-0")))}], pushes on {carrier}, its drag down {extendedDrag}");
            }
            b.Report.Add("gear: the Icarus hinges on the Revoker's LandingGear; " + string.Join("; ", lines));
        }
    }
}
