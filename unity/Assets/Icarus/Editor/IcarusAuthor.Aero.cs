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
        private enum SurfaceKind { Roll, Yaw, Pitch, Flap, LeadingEdge }

        private static readonly (string Name, SurfaceKind Kind)[] Surfaces =
        {
            ("aileron_L", SurfaceKind.Roll), ("aileron_R", SurfaceKind.Roll), ("rudder", SurfaceKind.Yaw),
            ("stabilator_L", SurfaceKind.Pitch), ("stabilator_R", SurfaceKind.Pitch),
            ("flap_L", SurfaceKind.Flap), ("flap_R", SurfaceKind.Flap), ("lef_L", SurfaceKind.LeadingEdge), ("lef_R", SurfaceKind.LeadingEdge),
        };
        // Control ranges in degrees: the all-moving stabilator needs less throw than an elevator.
        private const float AileronRange = 20f, RudderRange = 25f, StabilatorRange = 15f;
        // Trailing-edge flaps as the Revoker's (R6): gear-independent, by speed, 25 degrees, no added area, their own lift
        // normal turning with them. Leading-edge flaps (R6 structure, R7 numbers): 20 degrees of droop and 1.25 m2 more
        // area a side below 100 m/s, gone above 160, on a lift normal that doesn't droop, so the device adds area as R7's
        // replica sized it.
        private const float FlapDroop = 25f, FlapSpeedDeployed = 90f, FlapSpeedRetracted = 150f;
        private const float LefDroop = 20f, LefSpeedDeployed = 100f, LefSpeedRetracted = 160f, LefAddedArea = 1.25f;

        // R7's areas: 18.2 m2 of main wing (both sides, surfaces included), 3.0 of horizontal tail, 2.0 of body; the fin and
        // rudder carry their drawn side areas.
        private const float WingArea = 18.2f, TailArea = 3.0f, BodyArea = 2.0f;
        // R7's 0.60 of aggregate clean dragArea, shared over the parts that meet the air.
        private static readonly Dictionary<string, float> DragAreas = new Dictionary<string, float>
        {
            { RootPart, 0.15f }, { "fuselage_forward", 0.12f }, { "canopy", 0.04f }, { "radome", 0.02f }, { "fuselage_aft", 0.10f },
            { "nozzle", 0.02f }, { "intake_duct_L", 0.03f }, { "intake_duct_R", 0.03f }, { "wing_spar_L", 0.025f }, { "wing_spar_R", 0.025f },
            { "fin_spar", 0.02f }, { "stabilator_L", 0.01f }, { "stabilator_R", 0.01f },
        };
        private const float DragAreaTotal = 0.60f;

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
                    var device = part.AddComponent(GameType("HighLiftDevice"));
                    EditorUtility.CopySerialized(b.Donor.DeviceTemplate, device);
                    var so = new SerializedObject(device);
                    Prop(so, "aeroPart").objectReferenceValue = part.GetComponent(GameType("AeroPart"));
                    Prop(so, "swingWingController").objectReferenceValue = null;
                    Prop(so, "speedDeployed").floatValue = flap ? FlapSpeedDeployed : LefSpeedDeployed;
                    Prop(so, "speedRetracted").floatValue = flap ? FlapSpeedRetracted : LefSpeedRetracted;
                    Prop(so, "alphaMin").floatValue = 0f;
                    Prop(so, "alphaFactor").floatValue = 0f; // R7's replica schedules by speed alone
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
                    entry.FindPropertyRelative("anglesDeployed").vector3Value = new Vector3(sign * (flap ? FlapDroop : LefDroop), 0, 0);
                    so.ApplyModifiedPropertiesWithoutUndo();
                    b.Report.Add($"surface {name}: HighLiftDevice {(flap ? FlapDroop : LefDroop) * sign:+0;-0} deg about {part.transform.right}, {(flap ? FlapSpeedDeployed : LefSpeedDeployed)} to {(flap ? FlapSpeedRetracted : LefSpeedRetracted)} m/s, +{(flap ? 0f : LefAddedArea)} m2");
                    continue;
                }

                var force = DeflectionForce(lift.rotation, hinge.right);
                var torque = Vector3.Cross(lift.position - cg, force);
                float pitch = 0, roll = 0, yaw = 0;
                if (kind == SurfaceKind.Roll)
                    roll = b.Donor.RollSense * Mathf.Sign(torque.z) * AileronRange;
                else if (kind == SurfaceKind.Yaw)
                    yaw = b.Donor.YawSense * Mathf.Sign(torque.y) * RudderRange;
                else
                    pitch = b.Donor.PitchSense * Mathf.Sign(torque.x) * StabilatorRange;
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
        // an opener whose +X is the hinge axis signed so a positive turn swings the panel out.
        private static void BuildSpeedBrakes(Build b)
        {
            var aft = b.Parts["fuselage_aft"].transform;
            var openers = new List<Object>();
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
            }
            var airbrake = b.Root.GetComponent(GameType("Airbrake"));
            var so = new SerializedObject(airbrake);
            SetList(Prop(so, "transforms"), openers);
            Prop(so, "part").objectReferenceValue = b.Part("fuselage_aft");
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"speed brakes: {openers.Count} panels open {Prop(so, "maxAngle").floatValue} deg outward on fuselage_aft, drag {Prop(so, "dragAmount").floatValue}");
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

        // Planform of a thin closed mesh: half its surface.
        private static float PlanformArea(Mesh mesh)
        {
            var v = mesh.vertices;
            var t = mesh.triangles;
            var area = 0f;
            for (var i = 0; i < t.Length; i += 3)
                area += Vector3.Cross(v[t[i + 1]] - v[t[i]], v[t[i + 2]] - v[t[i]]).magnitude / 2;
            return area / 2;
        }

        // Side area of a mesh seen along X: each triangle's projection on the YZ plane, both faces, halved.
        private static float SideArea(Mesh mesh, Transform t)
        {
            var v = mesh.vertices.Select(t.TransformVector).ToArray();
            var tris = mesh.triangles;
            var area = 0f;
            for (var i = 0; i < tris.Length; i += 3)
                area += Mathf.Abs(Vector3.Cross(v[tris[i + 1]] - v[tris[i]], v[tris[i + 2]] - v[tris[i]]).x) / 2;
            return area / 2;
        }

        private static void SetAero(Build b)
        {
            var aero = new Dictionary<string, (float Area, int Airfoil)>();
            foreach (var side in new[] { "L", "R" })
            {
                var surfaces = new[] { "aileron_", "flap_", "lef_" }.Select(s => s + side).ToArray();
                foreach (var s in surfaces)
                    aero[s] = (PlanformArea(b.Meshes[s + "_visible"].Render), WingAirfoil);
                var spar = WingArea / 2 - surfaces.Sum(s => aero[s].Area);
                if (spar <= 0)
                    throw new InvalidDataException($"wing {side}: its surfaces' {surfaces.Sum(s => aero[s].Area):F2} m2 leave nothing of R7's {WingArea / 2} m2 for the spar");
                aero["wing_spar_" + side] = (spar, WingAirfoil);
                aero["stabilator_" + side] = (TailArea / 2, TailAirfoil);
            }
            var finSkin = b.Parts["fin_skin"].transform;
            aero["fin_spar"] = (SideArea(b.Meshes["fin_skin"].Render, finSkin), TailAirfoil);
            aero["rudder"] = (SideArea(b.Meshes["rudder_visible"].Render, b.Visuals["rudder_visible"]), TailAirfoil);
            aero[RootPart] = (BodyArea, BodyAirfoil);
            if (Mathf.Abs(DragAreas.Values.Sum() - DragAreaTotal) > 1e-4f)
                throw new InvalidDataException($"dragArea shares add up to {DragAreas.Values.Sum()}, not R7's {DragAreaTotal}");

            foreach (var spec in b.Specs)
            {
                var part = b.Part(spec.Name);
                var so = new SerializedObject(part);
                var (area, airfoil) = aero.TryGetValue(spec.Name, out var a) ? a : (0f, BodyAirfoil);
                Prop(so, "wingArea").floatValue = area;
                Prop(so, "airfoil").intValue = airfoil;
                Prop(so, "dragArea").floatValue = DragAreas.TryGetValue(spec.Name, out var drag) ? drag : 0f;
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            // Lift frames for the lifting parts that aren't hinged (BuildSurfaces set those).
            foreach (var side in new[] { "L", "R" })
                SetWingLift(b, side);
            SetFinLift(b);
            var body = new GameObject(RootPart + "_liftNormal") { layer = b.Root.layer }.transform;
            body.SetParent(b.Root.transform, false);
            body.position = ((Transform)GetRef(b.Part(RootPart), "centerOfMass")).position;
            Set(b.Part(RootPart), "liftNormal", body);

            b.Report.Add("aero: " + string.Join(", ", aero.OrderBy(e => e.Key, StringComparer.Ordinal).Select(e => $"{e.Key} {e.Value.Area:F2} m2 ({Airfoils[e.Value.Airfoil].Name})"))
                + $"; main wing {aero.Where(e => e.Value.Airfoil == WingAirfoil).Sum(e => e.Value.Area):F2} m2 plus {2 * LefAddedArea} from the leading-edge flaps; dragArea {DragAreas.Values.Sum():F2}");
            ReportBalance(b);
        }

        // The spar carries the wing's lift. Its frame follows the wing skin's span (with the anhedral) at zero incidence; the
        // force acts at the quarter chord where the skin's area centroid sits, through centerOfLift, since the game applies
        // a part's lift at its own centre of mass.
        private static void SetWingLift(Build b, string side)
        {
            var spar = b.Parts["wing_spar_" + side].transform;
            var skin = b.Parts["wing_skin_" + side].transform;
            var skinPoints = WorldVertices(skin, b.Meshes["wing_skin_" + side].Render);
            var chordPoints = skinPoints
                .Concat(new[] { "flap_", "aileron_", "lef_" }.SelectMany(s => WorldVertices(b.Visuals[s + side + "_visible"], b.Meshes[s + side + "_visible"].Render))).ToArray();
            var centroid = AreaCentroid(skin, b.Meshes["wing_skin_" + side].Render);
            var slab = chordPoints.Where(p => Mathf.Abs(p.x - centroid.x) < 0.12f).ToArray();
            if (slab.Length < 4)
                throw new InvalidDataException($"wing_skin_{side}: no chord at its centroid x {centroid.x:F2}");
            var le = slab.Max(p => p.z);
            var te = slab.Min(p => p.z);
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
            var centerOfLift = Quaternion.Inverse(lift.rotation) * new Vector3(0, 0, quarter.z - com.z);
            Set(part, "centerOfLift", centerOfLift);
            b.Report.Add($"lift {spar.name}: quarter chord {quarter} (chord {le - te:F2} m at x {centroid.x:F2}), {quarter.z - com.z:+0.00;-0.00} m from the spar's centre of mass, dihedral {Mathf.Atan2(span.y, Mathf.Abs(span.x)) * Mathf.Rad2Deg:F1} deg");
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
            var tris = mesh.triangles;
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
                var slope = so.FindProperty("airfoil").intValue == BodyAirfoil ? 2.5f : so.FindProperty("airfoil").intValue == TailAirfoil ? 4.0f : 4.4f;
                var w = so.FindProperty("wingArea").floatValue * slope * lift.up.y * lift.up.y;
                sum += w * (com.position + lift.rotation * so.FindProperty("centerOfLift").vector3Value).z;
                weight += w;
            }
            var np = sum / weight;
            b.Report.Add($"balance: empty CG at {cg} (station {OriginStation(b) - cg.z:F2} m from the radome tip), neutral point estimate station {OriginStation(b) - np:F2} m, static margin {cg.z - np:F2} m");
        }

        // Prefab z of the radome tip, the generator's station 0.
        private static float OriginStation(Build b) => b.Meshes.Keys.Where(b.Parts.ContainsKey).Max(n => b.Parts[n].GetComponent<MeshRenderer>() is MeshRenderer r ? r.bounds.max.z : float.MinValue);
    }
}
