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
        // The gear is the export's own: each leg a hinge (the gear_leg part) with its strut, a nested wheel hinge and its
        // tyre, plus hinged doors. The Revoker's LandingGear keeps its suspension, brakes, steering, audio and chocks and
        // drives the Icarus hinges. The bump stop sits GearStroke above the free wheel's centre, straight up.
        private const float GearStroke = 0.3f, GearMaxCompression = 0.5f, GearHingeBox = 0.15f;
        // The share of a leg's carrier mass that leaves with it when the wheel breaks off: LandingGear.BreakWheel takes
        // LandingGear.mass from the carrier's Rigidbody and gives it to the falling leg, so it must stay under the carrier's.
        private const float GearBreakShare = 0.5f;
        // Gear-down drag as LandingGear writes it onto the leg part: about the F-104's 0.02 rise in CD0 on 18.2 m2, or
        // 0.36 m2 of CdA, which the game counts as twice that in dragArea.
        private static readonly Dictionary<string, float> GearExtendedDrag = new Dictionary<string, float>
        {
            { "gear_leg_N", 0.18f }, { "gear_leg_L", 0.275f }, { "gear_leg_R", 0.275f },
        };
        private static readonly (string Leg, string Rig, string[] Leftovers, string Wheel, string[] Doors)[] Legs =
        {
            ("gear_leg_N", "gearHinge_F", new[] { "gear_F_armTarget" }, "gear_wheel_N", new[] { "gear_door_N_L", "gear_door_N_R" }),
            ("gear_leg_L", "gearMount_L", new[] { "gear_armtarget_L" }, "gear_wheel_L", new[] { "gear_door_main_L" }),
            ("gear_leg_R", "gearMount_R", new[] { "gear_armtarget_R" }, "gear_wheel_R", new[] { "gear_door_main_R" }),
        };
        // The F-104G's height to the stabilator top, which the stance should come out near.
        private const float F104Height = 4.12f;

        // An export hinge as the game drives one: the frame at the hinge's pose (local X along the hinge, the part itself
        // when the hinge is a part), a "<name>_hinge" child at identity that turns about local X, and the _visible mesh.
        // flip puts the hinge under a "<name>_axis" frame turned 180 degrees about Y, so it turns about the reversed axis.
        private static (Transform Frame, Transform Hinge, MeshRenderer Visible) HingeRig(Build b, string name, Transform parent, Transform frame = null, bool flip = false)
        {
            if (frame == null)
            {
                frame = new GameObject(name) { layer = parent.gameObject.layer }.transform;
                frame.SetParent(parent, false);
                frame.SetPositionAndRotation(b.Blockout.Local(name), b.Blockout.Rotation(name));
                b.Visuals[name] = frame;
            }
            var axis = frame;
            if (flip)
            {
                axis = new GameObject(name + "_axis") { layer = frame.gameObject.layer }.transform;
                axis.SetParent(frame, false);
                axis.localRotation = Quaternion.Euler(0f, 180f, 0f);
            }
            var hinge = new GameObject(name + "_hinge") { layer = frame.gameObject.layer }.transform;
            hinge.SetParent(axis, false);
            var visible = MeshVisual(b, name + "_visible", hinge);
            return (frame, hinge, visible);
        }

        // A blockout mesh as a plain renderer at its export pose under parent.
        private static MeshRenderer MeshVisual(Build b, string name, Transform parent)
        {
            var go = new GameObject(name) { layer = parent.gameObject.layer };
            go.transform.SetParent(parent, false);
            go.transform.SetPositionAndRotation(b.Blockout.Local(name), b.Blockout.Rotation(name));
            go.AddComponent<MeshFilter>().sharedMesh = b.Meshes[name].Render;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterials = b.Meshes[name].Materials;
            b.Visuals[name] = go.transform;
            return renderer;
        }

        // travel_deg turns the hinge from its built pose about its local X. Which way a positive turn goes is measured on the
        // mesh: the way that moves its middle further in the wanted direction (score). Returns the signed angle, and
        // whether it kept the export's sign.
        private static (float Angle, bool Kept) Travel(Build b, Transform frame, Vector3 centre, string name, Func<Vector3, float> score)
        {
            var travel = b.Blockout.Parts[name].Number("travel_deg");
            Vector3 Turned(float angle) => frame.position + Quaternion.AngleAxis(angle, frame.right) * (centre - frame.position);
            var kept = score(Turned(travel)) >= score(Turned(-travel));
            return (kept ? travel : -travel, kept);
        }

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
                var (fold, foldKept) = Travel(b, part, centre, leg, p => p.y); // stowed is up
                // LandingGear reads the hinge back through localEulerAngles.x and breaks the wheel above 10 degrees
                // (LandingGear.cs:620), so a negative fold, read as about 359 near full extension, would break a leg
                // touching down just before it locks: a leg that stows the other way turns about its reversed axis.
                var (_, hinge, strut) = HingeRig(b, leg, null, part, flip: fold < 0);
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

                // The Revoker's sprung leg, bump stop, unsprung, axle, wheels and chocks move onto the Icarus hinge; its strut,
                // tyre and arm meshes go.
                var travel = radius + GearStroke;
                gear.transform.SetParent(hinge, false);
                gear.transform.SetPositionAndRotation(part.position, Quaternion.identity);
                bump.SetParent(gear.transform, false);
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
                var wheelFrame = new GameObject(wheelName) { layer = part.gameObject.layer }.transform;
                wheelFrame.SetParent(unsprung, false);
                wheelFrame.SetPositionAndRotation(b.Blockout.Local(wheelName), b.Blockout.Rotation(wheelName));
                var wheelFold = new GameObject(wheelName + "_hinge") { layer = part.gameObject.layer }.transform;
                wheelFold.SetParent(wheelFrame, false);
                foreach (var wheel in wheels)
                {
                    wheel.SetParent(wheelFold, false);
                    wheel.SetPositionAndRotation(centre, AxleFrame(axle));
                }
                MeshVisual(b, tyreName, wheels[0]);
                b.Visuals[wheelName] = wheelFrame;
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
                    doomed.AddRange(t.Cast<Transform>().Where(c => !kept.Contains(c) && c != wheelFrame && !b.Visuals.ContainsValue(c)).Select(c => (Object)c.gameObject));
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
                    var (open, _) = Travel(b, frame, panel.bounds.center, door, p => -p.y); // open hangs down
                    doors.Add((doorHinge, open));
                }
                var wheelTravel = b.Blockout.Parts[wheelName].Number("travel_deg") * (foldKept ? 1f : -1f);

                so = new SerializedObject(gear);
                Prop(so, "attachedPart").objectReferenceValue = b.Part(leg);
                Prop(so, "gearHinge").objectReferenceValue = hinge;
                Prop(so, "hingeFoldMotion").vector3Value = Vector3.zero;
                Prop(so, "foldDegrees").floatValue = fold;
                Prop(so, "strutRotationTransform").objectReferenceValue = null;
                Prop(so, "strutRotation").floatValue = 0f;
                Prop(so, "joints").arraySize = 0;
                Prop(so, "suspensionTravel").floatValue = travel;
                Prop(so, "wheelRadius").floatValue = radius;
                Prop(so, "maxCompression").floatValue = GearMaxCompression;
                Prop(so, "extendedDrag").floatValue = GearExtendedDrag[leg];
                Prop(so, "mass").floatValue = GearBreakShare * b.Mass[leg];
                var moving = Prop(so, "movingParts");
                moving.arraySize = wheelTravel != 0 ? 1 : 0;
                if (wheelTravel != 0)
                {
                    var entry = moving.GetArrayElementAtIndex(0);
                    entry.FindPropertyRelative("transform").objectReferenceValue = wheelFold;
                    entry.FindPropertyRelative("target").objectReferenceValue = null;
                    entry.FindPropertyRelative("foldAngles").vector3Value = new Vector3(wheelTravel, 0, 0);
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
                lines.Add($"{leg}: tyre r {radius:F3} m at {centre}, axle {axle}, travel {travel:F2} m, fold {fold:+0.0;-0.0} deg about {(foldKept ? "the export's axis" : "the reversed axis")}, breaks off with {GearBreakShare * b.Mass[leg]:0} of its {b.Mass[leg]:0} kg, wheel fold {wheelTravel}, doors [{string.Join(", ", doors.Select(d => d.Hinge.name + " " + d.Open.ToString("+0;-0")))}], drag down {GearExtendedDrag[leg]}");
            }
            b.Report.Add("gear: the Icarus hinges on the Revoker's LandingGear; " + string.Join("; ", lines));
        }

        // The Revoker's cockpit, crew and ladder move as one so its pilot's eye lands under the Icarus canopy. The Revoker
        // canopy rig is gone; its Canopy opens the Icarus hood on its hinge and ejects the canopy part.
        private static void BuildCockpit(Build b)
        {
            var canopy = b.Parts["canopy"].transform;
            var (_, hood, glass) = HingeRig(b, "canopy", null, canopy);
            var cockpit = b.Parts["cockpit_cell"].transform;
            var windscreen = MeshVisual(b, "windscreen", cockpit);
            MeshVisual(b, "windscreen_frame", cockpit);
            var points = WorldVertices(glass.transform, b.Meshes["canopy_visible"].Render);
            var topY = points.Max(p => p.y);
            var crown = points.Where(p => p.y > topY - 0.01f).ToArray();
            var eye = new Vector3(0f, topY - EyeBelowCanopyTop, crown.Average(p => p.z));
            var helmet = (Transform)GetRef(b.Aircraft, "cockpitViewPoint");
            var delta = eye - helmet.position;
            foreach (var name in new[] { "cockpit_interior", "cockpit_interior_simple", "targetScreen", "pilot", "joystick", "throttle" })
            {
                var t = cockpit.Find(name) ?? throw new MissingReferenceException("cockpit_cell/" + name);
                t.position += delta;
                b.Placed.Add(t);
            }
            var ladder = b.Find("ladder");
            ladder.position += delta;
            b.Placed.Add(ladder);

            var (open, kept) = Travel(b, canopy, glass.bounds.center, "canopy", p => p.y); // the hood swings up
            var component = canopy.gameObject.AddComponent(GameType("Canopy"));
            EditorUtility.CopySerialized(b.Donor.CanopyTemplate, component);
            var so = new SerializedObject(component);
            Prop(so, "attachedPart").objectReferenceValue = b.Part("canopy");
            Prop(so, "ejectionTransform").objectReferenceValue = canopy;
            Prop(so, "ejectionCollider").objectReferenceValue = canopy.GetComponent<MeshCollider>();
            var hinges = Prop(so, "canopyHinges");
            hinges.arraySize = 1;
            hinges.GetArrayElementAtIndex(0).FindPropertyRelative("transform").objectReferenceValue = hood;
            hinges.GetArrayElementAtIndex(0).FindPropertyRelative("hingeAngle").floatValue = open;
            SetList(Prop(so, "glassRenderers"), new Object[] { glass, windscreen });
            // Canopy pushes along its part's own forward and up (Canopy.cs FixedUpdate); the hood's hinge frame has up
            // pointing down into the cockpit, so the Revoker's push is re-expressed in that frame to point up out of it.
            var push = Vector3.up * Prop(so, "ejectionForce").vector3Value.magnitude;
            Prop(so, "ejectionForce").vector3Value = new Vector3(0f, Vector3.Dot(push, canopy.up), Vector3.Dot(push, canopy.forward));
            so.ApplyModifiedPropertiesWithoutUndo();

            var aircraft = new SerializedObject(b.Aircraft);
            SetList(Prop(aircraft, "canopies"), new Object[] { component });
            // Hidden in cockpit view: the internal meshes round the pilot, which the Revoker interior stands inside.
            SetList(Prop(aircraft, "exteriorRenderers"), new[] { "cockpit_cell", "avionics_tray", "radar_tray" }
                .Select(n => (Object)b.Parts[n].GetComponent<MeshRenderer>()).Append(b.Visuals["gear_leg_N_visible"].GetComponent<MeshRenderer>()).ToArray());
            aircraft.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"cockpit: eye at {eye} ({EyeBelowCanopyTop} m under the canopy crown), Revoker interior, crew and ladder moved {delta}; " +
                $"hood opens {open:+0;-0} deg on its sill hinge ({(kept ? "export sign" : "export sign flipped")}) and ejects as its own part");
        }
    }
}
