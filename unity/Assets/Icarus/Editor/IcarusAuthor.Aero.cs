using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Animations;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        private enum SurfaceKind { Roll, Yaw, Pitch, Flap, LeadingEdge }

        private static readonly (string Name, SurfaceKind Kind)[] Surfaces =
        {
            ("aileron_L", SurfaceKind.Roll), ("aileron_R", SurfaceKind.Roll), ("rudder", SurfaceKind.Yaw),
            ("stabilator", SurfaceKind.Pitch),
            ("flap_L", SurfaceKind.Flap), ("flap_R", SurfaceKind.Flap), ("lef_L", SurfaceKind.LeadingEdge), ("lef_R", SurfaceKind.LeadingEdge),
        };
        // Control ranges, flap and leading-edge flap droop and the speed brakes' opening come from the generator's surface
        // table (build_icarus.py PARAMS["surface_travel"]), the travel its surface sweep checks: each hinge's
        // deflection_deg in blockout.json.
        private static float Deflection(Build b, string name)
        {
            var deg = b.Blockout.Parts[name].Number("deflection_deg");
            return deg > 0f ? deg : throw new InvalidDataException($"{name} has no deflection_deg in blockout.json");
        }
        // Trailing-edge flaps as the Revoker's: gear-independent, by speed, no added area, their own lift normal
        // turning with them. Leading-edge flaps use stock devices, sized to add 1.25 m2 a side below 100 m/s, gone
        // above 160, on a lift normal that doesn't droop, as sized in an offline replica of the game's aero.
        private const float FlapSpeedDeployed = 90f, FlapSpeedRetracted = 150f;
        private const float LefSpeedDeployed = 100f, LefSpeedRetracted = 160f, LefAddedArea = 1.25f;

        // Geometry-sized areas: 20.8079 m2 of main wing, gross planform with the root chord carried to the centreline (both sides,
        // surfaces included), 3.0 of horizontal tail and 2.0 of body by design; the fin carries the
        // generator's pinned side area (parts.FIN_LIFT_AREA) and the rudder its drawn one.
        private const float WingArea = 20.8079f, TailArea = 3.0f, BodyArea = 2.0f;
        // Aggregate clean dragArea, shared over exposed parts in the offline model's proportions. It modelled 0.55; in
        // game that left the jet 4% short of Mach 2.46 at 10 km, and 0.47 holds the model's level speeds at 10 and 15 km.
        // The nozzle's share is fuselage_aft's and the intake ducts' the root's, the sections they fold into.
        private const float DragAreaR14 = 0.55f, DragAreaTotal = 0.47f;
        private static readonly Dictionary<string, float> DragAreas = new Dictionary<string, float>
        {
            { RootPart, 0.135f + 0.03f + 0.03f }, { "fuselage_forward", 0.11f }, { "canopy", 0.04f }, { "radome", 0.02f },
            { "fuselage_aft", 0.09f + 0.02f }, { "wing_spar_L", 0.02f }, { "wing_spar_R", 0.02f },
            { "fin_spar", 0.015f }, { "stabilator", 0.02f },
        }.ToDictionary(e => e.Key, e => e.Value * DragAreaTotal / DragAreaR14);
        // The wing's boxes on one side, root first: the inner box at the root and the outer box beyond the crank
        // (art/blender/parts.py), each carrying its own skin pieces' planform share of the spar's lift and drag.
        private static string[] WingBoxes(Build b, string side) =>
            new[] { "wing_spar_" + side, "wing_spar_outer_" + side }.Where(b.Parts.ContainsKey).ToArray();

        // The skin a box carries: the wing skin's pieces folded into it (art/blender/chunks.py).
        private static string[] BoxSkins(Build b, string box, string side) =>
            FamilyParts(b, "wing_skin_" + side).Where(n => b.Blockout.Parts[n].Text("folded_into") == box).ToArray();

        // Each spar's lift acts at station 7.835 m, 1.584 m ahead of the quarter chord this author measured, sized for a
        // 5% MAC static margin empty and 8.7% at 20% fuel (its neutral point 9.326 m, MAC 3.491 m).
        private const float SparForceStation = 7.83455f;
        private const float WingMac = 3.4911f;

        // Each hinged part: the part at its hinge (local X along the hinge), a hinge child at identity that turns, and the
        // _visible mesh under it. Ailerons, rudder and stabilators are ControlSurfaces on that hinge; flaps and leading-edge
        // flaps are HighLiftDevices turning it, so no two controllers write the same transform.
        private static void BuildSurfaces(Build b)
        {
            var cg = CenterOfMass(b.Root.transform);
            foreach (var (name, kind) in Surfaces)
            {
                var part = b.Parts[name];
                var hinge = new GameObject(name + "_hinge") { layer = part.layer }.transform;
                hinge.SetParent(part.transform, false);
                var visible = new GameObject(name + "_visible") { layer = part.layer };
                visible.transform.SetParent(hinge, false);
                visible.AddComponent<MeshFilter>().sharedMesh = b.Meshes[name + "_visible"].Render;
                var renderer = visible.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = b.Meshes[name + "_visible"].Materials;
                b.Visuals[name + "_visible"] = visible.transform;
                var partSo = new SerializedObject(part.GetComponent(GameType("AeroPart")));
                SetList(Prop(partSo, "damageMaterial").FindPropertyRelative("renderers"), new Object[] { renderer });
                partSo.ApplyModifiedPropertiesWithoutUndo();

                var lift = new GameObject(name + "_liftNormal") { layer = part.layer }.transform;
                lift.SetParent(kind == SurfaceKind.LeadingEdge ? part.transform : hinge, false);
                lift.position = renderer.bounds.center;
                lift.rotation = LiftFrame(part.transform.right, Vector3.forward);
                Set(part.GetComponent(GameType("AeroPart")), "liftNormal", lift);

                if (kind == SurfaceKind.Flap || kind == SurfaceKind.LeadingEdge)
                {
                    // Droop sign from the mesh: the direction that moves the surface's middle down.
                    var centre = hinge.InverseTransformPoint(renderer.bounds.center);
                    var sign = (hinge.TransformPoint(Quaternion.AngleAxis(1f, Vector3.right) * centre).y < renderer.bounds.center.y) ? 1f : -1f;
                    var flap = kind == SurfaceKind.Flap;
                    var droop = Deflection(b, name);
                    var device = part.AddComponent(GameType("HighLiftDevice"));
                    EditorUtility.CopySerialized(b.Donor.DeviceTemplate, device);
                    var so = new SerializedObject(device);
                    Prop(so, "aeroPart").objectReferenceValue = part.GetComponent(GameType("AeroPart"));
                    Prop(so, "swingWingController").objectReferenceValue = null;
                    Prop(so, "speedDeployed").floatValue = flap ? FlapSpeedDeployed : LefSpeedDeployed;
                    Prop(so, "speedRetracted").floatValue = flap ? FlapSpeedRetracted : LefSpeedRetracted;
                    Prop(so, "alphaMin").floatValue = 0f;
                    Prop(so, "alphaFactor").floatValue = 0f; // speed-only deployment by design
                    Prop(so, "deployedArea").floatValue = flap ? 0f : LefAddedArea;
                    var moving = Prop(so, "movingParts");
                    moving.arraySize = 1;
                    var entry = moving.GetArrayElementAtIndex(0);
                    entry.FindPropertyRelative("move").boolValue = false;
                    entry.FindPropertyRelative("rotate").boolValue = true;
                    entry.FindPropertyRelative("transform").objectReferenceValue = hinge;
                    entry.FindPropertyRelative("positionRetracted").vector3Value = Vector3.zero;
                    entry.FindPropertyRelative("positionDeployed").vector3Value = Vector3.zero;
                    entry.FindPropertyRelative("anglesRetracted").vector3Value = Vector3.zero;
                    entry.FindPropertyRelative("anglesDeployed").vector3Value = new Vector3(sign * droop, 0, 0);
                    so.ApplyModifiedPropertiesWithoutUndo();
                    b.Report.Add($"surface {name}: HighLiftDevice {droop * sign:+0;-0} deg about {part.transform.right}, {(flap ? FlapSpeedDeployed : LefSpeedDeployed)} to {(flap ? FlapSpeedRetracted : LefSpeedRetracted)} m/s, +{(flap ? 0f : LefAddedArea)} m2");
                    continue;
                }

                var force = DeflectionForce(lift.rotation, hinge.right);
                var torque = Vector3.Cross(lift.position - cg, force);
                float pitch = 0, roll = 0, yaw = 0;
                if (kind == SurfaceKind.Roll)
                    roll = b.Donor.RollSense * Mathf.Sign(torque.z) * Deflection(b, name);
                else if (kind == SurfaceKind.Yaw)
                    yaw = b.Donor.YawSense * Mathf.Sign(torque.y) * Deflection(b, name);
                else
                    pitch = b.Donor.PitchSense * Mathf.Sign(torque.x) * Deflection(b, name);
                var surface = part.AddComponent(GameType("ControlSurface"));
                EditorUtility.CopySerialized(b.Donor.SurfaceTemplate, surface);
                var cs = new SerializedObject(surface);
                Prop(cs, "pitchRange").floatValue = pitch;
                Prop(cs, "rollRange").floatValue = roll;
                Prop(cs, "yawRange").floatValue = yaw;
                Prop(cs, "brakeRange").floatValue = 0;
                Prop(cs, "attachedSurface").objectReferenceValue = part.GetComponent(GameType("AeroPart"));
                Prop(cs, "visibleMesh").objectReferenceValue = hinge.gameObject;
                Prop(cs, "flap").boolValue = false;
                Prop(cs, "splitDrag").floatValue = 0;
                Prop(cs, "maxSplit").floatValue = 0;
                Prop(cs, "yawSplitFactor").floatValue = 0;
                Prop(cs, "splitUpper").objectReferenceValue = null;
                Prop(cs, "splitLower").objectReferenceValue = null;
                cs.ApplyModifiedPropertiesWithoutUndo();
                b.Report.Add($"surface {name}: pitch {pitch}, roll {roll}, yaw {yaw}, servo {Prop(cs, "servoSpeed").floatValue} deg/s, hinge {part.transform.right} at {part.transform.position}");
            }
            BuildSpeedBrakes(b);
        }

        // The speed brakes open on the stock Airbrake, which turns each transform about its own +X: each panel hangs from
        // an opener whose +X is the hinge axis signed so a positive turn swings the panel out. Each actuator is two pieces
        // with their pivots at their eyes, the cylinder on the tail cone and the rod on the opener, each aimed at the
        // other's eye by an AimConstraint about the hinge axis; the Airbrake enables its constraints while the brakes are
        // open, as the stock VTOLTrainer1 aims its piston.
        private static void BuildSpeedBrakes(Build b)
        {
            var aft = b.Parts["fuselage_tail"].transform;  // the brakes run from the tail cone's break back
            var openers = new List<Object>();
            var constraints = new List<Object>();
            foreach (var name in new[] { "speed_brake_L", "speed_brake_R" })
            {
                var opener = new GameObject(name) { layer = aft.gameObject.layer }.transform;
                opener.SetParent(aft, false);
                opener.SetPositionAndRotation(b.Blockout.Local(name), b.Blockout.Rotation(name));
                var visible = new GameObject(name + "_visible") { layer = aft.gameObject.layer };
                visible.transform.SetParent(opener, false);
                visible.transform.SetPositionAndRotation(b.Blockout.Local(name + "_visible"), b.Blockout.Rotation(name + "_visible"));
                visible.AddComponent<MeshFilter>().sharedMesh = b.Meshes[name + "_visible"].Render;
                var renderer = visible.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = b.Meshes[name + "_visible"].Materials;
                var centre = renderer.bounds.center;
                var turned = opener.TransformPoint(Quaternion.AngleAxis(1f, Vector3.right) * opener.InverseTransformPoint(centre));
                if (Mathf.Abs(turned.x) < Mathf.Abs(centre.x))
                {
                    opener.Rotate(0f, 180f, 0f, Space.Self);
                    visible.transform.SetPositionAndRotation(b.Blockout.Local(name + "_visible"), b.Blockout.Rotation(name + "_visible"));
                }
                b.Visuals[name] = opener;
                b.Visuals[name + "_visible"] = visible.transform;
                openers.Add(opener);
                var cylinder = MeshVisual(b, name + "_cylinder", aft).transform;
                var rod = MeshVisual(b, name + "_rod", opener).transform;
                constraints.Add(AimAtEye(cylinder, rod, aft, opener.right));
                constraints.Add(AimAtEye(rod, cylinder, aft, opener.right));
            }
            var airbrake = b.Root.GetComponent(GameType("Airbrake"));
            var so = new SerializedObject(airbrake);
            SetList(Prop(so, "transforms"), openers);
            SetList(Prop(so, "constraints"), constraints);
            Prop(so, "part").objectReferenceValue = b.Part("fuselage_tail");
            if (Deflection(b, "speed_brake_L") != Deflection(b, "speed_brake_R"))
                throw new InvalidDataException("the speed brakes open by different angles; the one Airbrake turns both alike");
            Prop(so, "maxAngle").floatValue = Deflection(b, "speed_brake_L");
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"speed brakes: {openers.Count} panels open {Prop(so, "maxAngle").floatValue} deg outward on fuselage_tail, drag {Prop(so, "dragAmount").floatValue}; {constraints.Count} actuator pieces aimed");
        }

        // An actuator piece turning about its eye so it keeps pointing at the other piece's eye, its twist held about the
        // hinge axis (fixed in frame, the part both pieces ride). Built at rest, the constraint reproduces the export pose.
        private static AimConstraint AimAtEye(Transform piece, Transform other, Transform frame, Vector3 hingeAxis)
        {
            var aim = piece.gameObject.AddComponent<AimConstraint>();
            aim.AddSource(new ConstraintSource { sourceTransform = other, weight = 1f });
            aim.aimVector = Quaternion.Inverse(piece.rotation) * (other.position - piece.position).normalized;
            aim.upVector = Quaternion.Inverse(piece.rotation) * hingeAxis;
            aim.worldUpType = AimConstraint.WorldUpType.ObjectRotationUp;
            aim.worldUpObject = frame;
            aim.worldUpVector = Quaternion.Inverse(frame.rotation) * hingeAxis;
            aim.rotationAtRest = piece.localEulerAngles;
            aim.rotationOffset = Vector3.zero;
            aim.weight = 1f;
            aim.locked = true;
            aim.constraintActive = true;
            return aim;
        }

        // Streamwise lift frame: Z along the chord (leading edge ahead), Y the surface normal, up for a wing and to the
        // right for the fin. The game reads alpha in this frame.
        private static Quaternion LiftFrame(Vector3 span, Vector3 chord)
        {
            span = span.normalized;
            var along = (chord - span * Vector3.Dot(chord, span)).normalized;
            if (along.z < 0)
                along = -along;
            var normal = Vector3.Cross(along, span).normalized;
            if (Mathf.Abs(normal.y) >= 0.5f ? normal.y < 0 : normal.x < 0)
                normal = -normal;
            return Quaternion.LookRotation(along, normal);
        }

        // A mesh's triangles less the back-facing twins SkinFirst gives the skin, so a two-sided surface counts once: a
        // triangle is dropped when the same three points, wound the other way, came before it.
        private static int[] OneSided(Vector3[] v, int[] t)
        {
            var seen = new HashSet<(Vector3, Vector3, Vector3)>();
            var kept = new List<int>();
            for (var i = 0; i < t.Length; i += 3)
            {
                Vector3 a = v[t[i]], b = v[t[i + 1]], c = v[t[i + 2]];
                if (seen.Contains((a, c, b)) || seen.Contains((c, b, a)) || seen.Contains((b, a, c)))
                    continue;
                seen.Add((a, b, c));
                kept.AddRange(new[] { t[i], t[i + 1], t[i + 2] });
            }
            return kept.ToArray();
        }

        // Planform of a thin closed mesh: half its surface.
        private static float PlanformArea(Mesh mesh)
        {
            var v = mesh.vertices;
            var t = OneSided(v, mesh.triangles);
            var area = 0f;
            for (var i = 0; i < t.Length; i += 3)
                area += Vector3.Cross(v[t[i + 1]] - v[t[i]], v[t[i + 2]] - v[t[i]]).magnitude / 2;
            return area / 2;
        }

        // Side area of a mesh seen along X: each triangle's projection on the YZ plane, both faces, halved.
        private static float SideArea(Mesh mesh, Transform t)
        {
            var v = mesh.vertices.Select(t.TransformVector).ToArray();
            var tris = OneSided(mesh.vertices, mesh.triangles);
            var area = 0f;
            for (var i = 0; i < tris.Length; i += 3)
                area += Mathf.Abs(Vector3.Cross(v[tris[i + 1]] - v[tris[i]], v[tris[i + 2]] - v[tris[i]]).x) / 2;
            return area / 2;
        }

        private static void SetAero(Build b)
        {
            var aero = new Dictionary<string, (float Area, int Airfoil)>();
            // parts split off a DragAreas entry share its drag: each wing box by its skin's planform, the aft core and the
            // tail cone by their frontal areas
            var dragShare = new Dictionary<string, (string Of, float Share)>();
            float Frontal(string n) => b.Parts[n].GetComponent<MeshRenderer>().bounds.size.x * b.Parts[n].GetComponent<MeshRenderer>().bounds.size.y;
            foreach (var n in new[] { "fuselage_aft", "fuselage_tail" })
                dragShare[n] = ("fuselage_aft", Frontal(n) / (Frontal("fuselage_aft") + Frontal("fuselage_tail")));
            foreach (var side in new[] { "L", "R" })
            {
                var surfaces = new[] { "aileron_", "flap_", "lef_" }.Select(s => s + side).ToArray();
                foreach (var s in surfaces)
                    aero[s] = (PlanformArea(b.Meshes[s + "_visible"].Render), WingAirfoil);
                var spar = WingArea / 2 - surfaces.Sum(s => aero[s].Area);
                if (spar <= 0)
                    throw new InvalidDataException($"wing {side}: its surfaces' {surfaces.Sum(s => aero[s].Area):F2} m2 leave nothing of the sized {WingArea / 2} m2 for the spar");
                var planform = WingBoxes(b, side).ToDictionary(box => box, box => BoxSkins(b, box, side).Sum(n => PlanformArea(b.Meshes[n].Render)));
                foreach (var box in planform.Keys)
                {
                    dragShare[box] = ("wing_spar_" + side, planform[box] / planform.Values.Sum());
                    aero[box] = (spar * dragShare[box].Share, WingAirfoil);
                }
            }
            aero["stabilator"] = (TailArea, TailAirfoil);
            // the fin's lifting area, which the generator pins (parts.FIN_LIFT_AREA)
            var finArea = b.Blockout.Parts["fin_skin"].Number("side_area_m2");
            if (finArea <= 0)
                throw new InvalidDataException("fin_skin has no side_area_m2 in blockout.json");
            aero["fin_spar"] = (finArea, TailAirfoil);
            aero["rudder"] = (SideArea(b.Meshes["rudder_visible"].Render, b.Visuals["rudder_visible"]), TailAirfoil);
            aero[RootPart] = (BodyArea, BodyAirfoil);
            if (Mathf.Abs(DragAreas.Values.Sum() - DragAreaTotal) > 1e-4f)
                throw new InvalidDataException($"dragArea shares add up to {DragAreas.Values.Sum()}, not the tuned {DragAreaTotal}");

            foreach (var spec in b.Specs)
            {
                var part = b.Part(spec.Name);
                var so = new SerializedObject(part);
                var (area, airfoil) = aero.TryGetValue(spec.Name, out var a) ? a : (0f, BodyAirfoil);
                Prop(so, "wingArea").floatValue = area;
                Prop(so, "airfoil").intValue = airfoil;
                Prop(so, "dragArea").floatValue = dragShare.TryGetValue(spec.Name, out var split) ? DragAreas[split.Of] * split.Share
                    : DragAreas.TryGetValue(spec.Name, out var drag) ? drag : 0f;
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            // Lift frames for the lifting parts that aren't hinged (BuildSurfaces set those).
            foreach (var side in new[] { "L", "R" })
                foreach (var box in WingBoxes(b, side))
                    SetWingLift(b, box, side);
            SetFinLift(b);
            var body = new GameObject(RootPart + "_liftNormal") { layer = b.Root.layer }.transform;
            body.SetParent(b.Root.transform, false);
            body.position = ((Transform)GetRef(b.Part(RootPart), "centerOfMass")).position;
            Set(b.Part(RootPart), "liftNormal", body);

            b.Report.Add("aero: " + string.Join(", ", aero.OrderBy(e => e.Key, StringComparer.Ordinal).Select(e => $"{e.Key} {e.Value.Area:F2} m2 ({Airfoils[e.Value.Airfoil].Name})"))
                + $"; main wing {aero.Where(e => e.Value.Airfoil == WingAirfoil).Sum(e => e.Value.Area):F2} m2 plus {2 * LefAddedArea} from the leading-edge flaps; dragArea {DragAreas.Values.Sum():F2}");
            ReportBalance(b);
        }

        // Each wing box carries its share of the wing's lift. Its frame follows its skin pieces' span (with the anhedral)
        // at zero incidence; the force acts at the sized station, through centerOfLift, at the span of the box's own centre of
        // mass, since the game applies a part's lift there: the outer box's lift acts outboard of the inner's.
        private static void SetWingLift(Build b, string box, string side)
        {
            var spar = b.Parts[box].transform;
            var skins = BoxSkins(b, box, side);
            var skinPoints = skins.SelectMany(n => WorldVertices(Placed(b, n), b.Meshes[n].Render)).ToArray();
            var chordPoints = FamilyVertices(b, "wing_skin_" + side)
                .Concat(new[] { "flap_", "aileron_", "lef_" }.SelectMany(s => WorldVertices(b.Visuals[s + side + "_visible"], b.Meshes[s + side + "_visible"].Render))).ToArray();
            var centroid = AreaCentroid(b, skins);
            // The edges at the centroid's span, interpolated between the span stations either side of it: the
            // skin and its surfaces share their stations, so each station holds the leading and trailing edge.
            var stations = chordPoints.GroupBy(p => Mathf.Round(Mathf.Abs(p.x) * 1000f))
                .Select(g => (X: g.Key / 1000f, Le: g.Max(p => p.z), Te: g.Min(p => p.z))).OrderBy(s => s.X).ToArray();
            var atX = Mathf.Abs(centroid.x);
            var next = Array.FindIndex(stations, s => s.X >= atX);
            if (next < 1)
                throw new InvalidDataException($"{box}: no chord stations either side of its skin's centroid x {centroid.x:F2}");
            var (inboard, outboard) = (stations[next - 1], stations[next]);
            var along = (atX - inboard.X) / (outboard.X - inboard.X);
            var le = Mathf.Lerp(inboard.Le, outboard.Le, along);
            var te = Mathf.Lerp(inboard.Te, outboard.Te, along);
            var quarter = new Vector3(centroid.x, centroid.y, le - 0.25f * (le - te));
            var minX = skinPoints.Min(p => Mathf.Abs(p.x));
            var maxX = skinPoints.Max(p => Mathf.Abs(p.x));
            Vector3 Mean(Func<Vector3, bool> where) => skinPoints.Where(where).Aggregate(Vector3.zero, (s, p) => s + p) / skinPoints.Count(where);
            var span = Mean(p => Mathf.Abs(p.x) > maxX - 0.3f) - Mean(p => Mathf.Abs(p.x) < minX + 0.3f);

            var lift = new GameObject(spar.name + "_liftNormal") { layer = spar.gameObject.layer }.transform;
            lift.SetParent(spar, false);
            lift.SetPositionAndRotation(quarter, LiftFrame(span, Vector3.forward));
            var part = b.Part(spar.name);
            Set(part, "liftNormal", lift);
            var com = ((Transform)GetRef(part, "centerOfMass")).position;
            var force = GeneratorS0 - SparForceStation - b.Blockout.Origin.z;
            var centerOfLift = Quaternion.Inverse(lift.rotation) * new Vector3(0, 0, force - com.z);
            Set(part, "centerOfLift", centerOfLift);
            b.Report.Add($"lift {spar.name}: measured quarter chord station {Station(b, quarter.z):F3} m (chord {le - te:F2} m at x {centroid.x:F2}); force at sized station {SparForceStation} m, " +
                $"{Station(b, quarter.z) - SparForceStation:F3} m ahead of it and {force - com.z:+0.000;-0.000} m from the spar's centre of mass; dihedral {Mathf.Atan2(span.y, Mathf.Abs(span.x)) * Mathf.Rad2Deg:F1} deg");
        }

        // The fin spar carries the fin's side force, in a frame along the fin skin's span.
        private static void SetFinLift(Build b)
        {
            var spar = b.Parts["fin_spar"].transform;
            var skinPoints = WorldVertices(b.Parts["fin_skin"].transform, b.Meshes["fin_skin"].Render);
            var minY = skinPoints.Min(p => p.y);
            var maxY = skinPoints.Max(p => p.y);
            Vector3 Mean(Func<Vector3, bool> where) => skinPoints.Where(where).Aggregate(Vector3.zero, (s, p) => s + p) / skinPoints.Count(where);
            var span = Mean(p => p.y > maxY - 0.3f) - Mean(p => p.y < minY + 0.3f);
            var lift = new GameObject("fin_spar_liftNormal") { layer = spar.gameObject.layer }.transform;
            lift.SetParent(spar, false);
            lift.SetPositionAndRotation(AreaCentroid(b.Parts["fin_skin"].transform, b.Meshes["fin_skin"].Render), LiftFrame(span, Vector3.forward));
            Set(b.Part("fin_spar"), "liftNormal", lift);
        }

        // Area-weighted centroid of a mesh's triangles, in world space.
        private static Vector3 AreaCentroid(Transform t, Mesh mesh)
        {
            var v = WorldVertices(t, mesh);
            var tris = OneSided(mesh.vertices, mesh.triangles);
            var sum = Vector3.zero;
            var area = 0f;
            for (var i = 0; i < tris.Length; i += 3)
            {
                var a = Vector3.Cross(v[tris[i + 1]] - v[tris[i]], v[tris[i + 2]] - v[tris[i]]).magnitude / 2;
                sum += a * (v[tris[i]] + v[tris[i + 1]] + v[tris[i + 2]]) / 3;
                area += a;
            }
            return sum / area;
        }

        // Empty CG and a neutral point estimate: lift-slope-weighted lift stations of the horizontal lifting parts (a
        // part's lift acts at its centre of mass plus centerOfLift). No downwash or body terms.
        private static void ReportBalance(Build b)
        {
            var cg = CenterOfMass(b.Root.transform);
            float sum = 0, weight = 0;
            foreach (var part in b.Root.GetComponentsInChildren(GameType("AeroPart"), true))
            {
                var so = new SerializedObject(part);
                var lift = (Transform)so.FindProperty("liftNormal").objectReferenceValue ?? part.transform;
                var com = (Transform)so.FindProperty("centerOfMass").objectReferenceValue ?? part.transform;
                var slope = so.FindProperty("airfoil").intValue == BodyAirfoil ? 2.5f : 4.0f; // wing and tail sized at 4.0/rad
                var w = so.FindProperty("wingArea").floatValue * slope * lift.up.y * lift.up.y;
                sum += w * (com.position + lift.rotation * so.FindProperty("centerOfLift").vector3Value).z;
                weight += w;
            }
            var np = sum / weight;
            // Full internal fuel: each tank's fuel at its part's centre of mass, as UnitPart.ModifyMass adds it.
            var fuelMoment = Vector3.zero;
            var fuel = 0f;
            foreach (var tank in b.Tanks)
            {
                var kg = b.Blockout.Parts[tank].Number("fuel_kg");
                fuelMoment += kg * ((Transform)GetRef(b.Part(tank), "centerOfMass")).position;
                fuel += kg;
            }
            var full = (cg * EmptyMass + fuelMoment) / (EmptyMass + fuel);
            var low = (cg * EmptyMass + 0.2f * fuelMoment) / (EmptyMass + 0.2f * fuel);
            string Margin(Vector3 at) => $"{at.z - np:F3} m ({(at.z - np) / WingMac:P1} MAC)";
            b.Report.Add($"balance: CG station {Station(b, cg.z):F3} m empty, {Station(b, low.z):F3} m at 20% fuel, {Station(b, full.z):F3} m full ({fuel:0} kg); " +
                $"neutral point estimate station {Station(b, np):F3} m; static margin {Margin(cg)} empty, {Margin(low)} at 20% fuel, {Margin(full)} full");
        }

        // The generator's station (metres aft of the radome tip, art/blender/build_icarus.py) of a prefab z: its station 0
        // sits S0 = 8 m ahead of the Blender origin.
        private const float GeneratorS0 = 8f;
        private static float Station(Build b, float z) => GeneratorS0 - (z + b.Blockout.Origin.z);

    }
}
