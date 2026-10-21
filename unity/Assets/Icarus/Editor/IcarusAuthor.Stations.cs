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
        // Where each hardpoint was measured to sit (root frame) and its roll about the forward axis, from the ground-strike
        // and tyre clearance run of tools/store_clearance.py. A5 holds every built hardpoint to it within
        // MeasuredTolerance: moving a station means a new clearance run and a new entry here.
        private static readonly Dictionary<string, (Vector3 Position, float Roll)> MeasuredHardpoints = new Dictionary<string, (Vector3, float)>
        {
            { "hardpoint_wingtip_L", (new Vector3(-3.395f, -0.562f, -2.595f), 270f) },
            { "hardpoint_wingtip_R", (new Vector3(3.395f, -0.562f, -2.595f), 90f) },
            { "hardpoint_innerwing_L", (new Vector3(-1.849f, -0.594f, -1.692f), 0f) },
            { "hardpoint_innerwing_R", (new Vector3(1.849f, -0.594f, -1.692f), 0f) },
            { "hardpoint_conformal_L", (new Vector3(-0.550f, -0.510f, 0.950f), 0f) },
            { "hardpoint_conformal_R", (new Vector3(0.550f, -0.510f, 0.950f), 0f) },
        };
        private const float MeasuredTolerance = 0.001f;

        // Six stations in SetNames order, each set [L, R] with HardpointIndex 0..5 left before right.
        private static void BuildStations(Build b)
        {
            // A wing station hangs from the foremost point of its pylon's flat lower edge, ahead of where stock blades put
            // theirs (0.45 of the blade back): the swept wing puts the blade well behind the main wheels, and a store
            // hung further aft reaches the runway before the tail in a nose-up rotation (art/blender/stations.py pylons).
            Vector3 PylonPoint(string pylon)
            {
                var probe = new GameObject("pylon_probe").transform;
                probe.SetPositionAndRotation(b.Blockout.Local(pylon), b.Blockout.Rotation(pylon));
                var points = WorldVertices(probe, b.Meshes[pylon].Render);
                Object.DestroyImmediate(probe.gameObject);
                var low = points.Min(v => v.y);
                var z = points.Where(v => v.y < low + 0.01f).Max(v => v.z);
                return new Vector3(points.Average(v => v.x), low, z);
            }
            // A wingtip station sits on the flat tip face, 0.005 m in from it at mid-thickness, 0.40 of the tip chord back
            // from the leading edge; its roll turns the mount's rail onto the face, so the store hangs beside the tip.
            Vector3 TipPoint(string side)
            {
                var vertices = WorldVertices(b.Parts["wing_skin_" + side].transform, b.Meshes["wing_skin_" + side].Render);
                var outer = vertices.Max(v => Mathf.Abs(v.x));
                var tip = vertices.Where(v => Mathf.Abs(v.x) > outer - 0.001f).ToArray();
                var leading = tip.Max(v => v.z);
                return new Vector3(Mathf.Sign(tip[0].x) * (outer - 0.005f), (tip.Max(v => v.y) + tip.Min(v => v.y)) / 2f,
                    leading - 0.40f * (leading - tip.Min(v => v.z)));
            }
            // Heights at which the vertical line through (x, z) crosses a part's mesh.
            IEnumerable<float> Crossings(string part, float x, float z)
            {
                var v = WorldVertices(b.Parts[part].transform, b.Meshes[part].Render);
                var triangles = b.Meshes[part].Render.triangles;
                for (var k = 0; k < triangles.Length; k += 3)
                {
                    Vector3 p = v[triangles[k]], q = v[triangles[k + 1]], r = v[triangles[k + 2]];
                    var d = (q.z - r.z) * (p.x - r.x) + (r.x - q.x) * (p.z - r.z);
                    if (Mathf.Abs(d) < 1e-9f)
                        continue;
                    var u = ((q.z - r.z) * (x - r.x) + (r.x - q.x) * (z - r.z)) / d;
                    var w = ((r.z - p.z) * (x - r.x) + (p.x - r.x) * (z - r.z)) / d;
                    if (u >= 0f && w >= 0f && u + w <= 1f)
                        yield return u * p.y + w * q.y + (1f - u - w) * r.y;
                }
            }
            // A conformal station sits 0.005 m inside the belly skin right above it: the IRM-S2's rail top stands only
            // 0.012 m above its hardpoint, so any deeper gap shows under it.
            Vector3 ConformalPoint(string side)
            {
                var x = (side == "L" ? -1f : 1f) * 0.55f;
                var z = b.Parts["fuel_forward_main"].transform.position.z - 0.6f;
                var skin = new[] { RootPart, "intake_duct_L", "intake_duct_R", "skin_mid_L", "skin_mid_R" }.SelectMany(n => Crossings(n, x, z)).ToArray();
                if (skin.Length == 0)
                    throw new InvalidDataException($"no belly skin above the conformal station at x {x}, z {z:F2}");
                return new Vector3(x, skin.Min() + 0.005f, z);
            }

            // Pylon names the blade and plug a wing station shows and hides by load. Roll is the left station's turn about
            // the forward axis; the right one turns the other way.
            var sets = new (string Name, string Part, string Pylon, Func<string, Vector3> Where, float Roll)[]
            {
                (SetNames[0], "wing_spar_", null, TipPoint, -90f),
                (SetNames[1], "wing_spar_", "pylon_inner_", s => PylonPoint("pylon_inner_" + s), 0f),
                (SetNames[2], RootPart, null, ConformalPoint, 0f),
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
                    point.SetPositionAndRotation(sets[i].Where(side), b.Root.transform.rotation * Quaternion.Euler(0f, 0f, side == "L" ? sets[i].Roll : -sets[i].Roll));
                    var hp = hardpoints.GetArrayElementAtIndex(j);
                    hp.FindPropertyRelative("transform").objectReferenceValue = point;
                    hp.FindPropertyRelative("part").objectReferenceValue = b.Part(partName);
                    hp.FindPropertyRelative("bayDoors").arraySize = 0;
                    hp.FindPropertyRelative("doorOpenDuration").floatValue = 0f;
                    // One option with no mount matches every mount, so the blade shows whenever the station is loaded
                    // and the plug whenever it is empty. Hardpoint.Pylon is left unset: the game never reads it.
                    var pylonOptions = hp.FindPropertyRelative("pylonOptions");
                    pylonOptions.arraySize = sets[i].Pylon == null ? 0 : 1;
                    if (sets[i].Pylon != null)
                    {
                        var option = pylonOptions.GetArrayElementAtIndex(0);
                        option.FindPropertyRelative("cargo").boolValue = false;
                        option.FindPropertyRelative("mount").objectReferenceValue = null;
                        option.FindPropertyRelative("renderer").objectReferenceValue = b.Visuals[sets[i].Pylon + side].GetComponent<MeshRenderer>();
                    }
                    hp.FindPropertyRelative("Pylon").objectReferenceValue = null;
                    hp.FindPropertyRelative("Plug").objectReferenceValue = sets[i].Pylon == null ? null : b.Visuals[sets[i].Pylon + "plug_" + side].GetComponent<MeshRenderer>();
                    hp.FindPropertyRelative("BuiltInWeapons").arraySize = 0;
                    hp.FindPropertyRelative("BuiltInTurrets").arraySize = 0;
                    hp.FindPropertyRelative("HardpointIndex").intValue = 2 * i + j;
                    lines.Add($"{point.name} #{2 * i + j} on {partName} at {point.position.ToString("F3")} roll {point.eulerAngles.z:F0}");
                }
            }
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add("stations: " + string.Join("; ", lines));
        }
    }
}
