using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Blueprinter;
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
            { "hardpoint_wingtip_L", (new Vector3(-3.395f, -0.562f, -2.7835f), 270f) },
            { "hardpoint_wingtip_R", (new Vector3(3.395f, -0.562f, -2.7835f), 90f) },
            { "hardpoint_innerwing_L", (new Vector3(-1.849f, -0.4135f, -1.8800f), 0f) },
            { "hardpoint_innerwing_R", (new Vector3(1.849f, -0.4135f, -1.8800f), 0f) },
            // Raised 0.055 m onto the trough floor for the Icarus's own conformal mounts (art/blender/stations.py).
            { "hardpoint_conformal_L", (new Vector3(-0.550f, -0.455f, 0.950f), 0f) },
            { "hardpoint_conformal_R", (new Vector3(0.550f, -0.455f, 0.950f), 0f) },
        };
        private const float MeasuredTolerance = 0.001f;
        private const string MountFolder = ModFolder + "/Mounts";

        // The conformal section of blockout.json (art/blender/stations.py export): the left hardpoint, world, and the
        // Icarus's own mounts by the stock mount each replaces.
        private static Dictionary<string, object> ConformalLayout() =>
            (Dictionary<string, object>)((Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(ExportFolder, "blockout.json"))))["conformal"];

        private static Vector3 Vec3(object value)
        {
            var list = (List<object>)value;
            return new Vector3(Convert.ToSingle(list[0]), Convert.ToSingle(list[1]), Convert.ToSingle(list[2]));
        }

        // The conformal mounts: each a copy of the stock external single (its missile, WeaponInfo, mass, drag and RCS,
        // and missileBay 0, so it flies as an exposed store) under a new jsonKey, with the stock launch rail swapped for
        // a low shoe, the missile hung at the trough's depth and pitch, and its capsule fitted to the body so it clears
        // the trough. The AAM-29's rail box collider goes with its rail. Rebuilt in place on every run, GUIDs kept.
        private static Dictionary<string, Object> AuthorConformalMounts()
        {
            BlueprinterAssets.EnsureFolder(MountFolder);
            var shoeMaterial = Load<Material>(Stock + "Material/jet_mechanical_PLACEHOLDER.mat");
            var authored = new Dictionary<string, Object>();
            foreach (var entry in ((Dictionary<string, object>)ConformalLayout()["mounts"]).OrderBy(e => e.Key, StringComparer.Ordinal))
            {
                var m = (Dictionary<string, object>)entry.Value;
                var key = (string)m["key"];
                var prefabPath = MountFolder + "/" + key + ".prefab";
                var assetPath = MountFolder + "/" + key + ".asset";
                foreach (var (source, target) in new[] { ("GameObject/" + entry.Key + "_PLACEHOLDER.prefab", prefabPath), ("MonoBehaviour/" + entry.Key + "_PLACEHOLDER.asset", assetPath) })
                {
                    File.Copy(Stock + source, target, true); // keeps the target's .meta, so its GUID survives
                    AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
                }
                var shoe = SaveAsset(ShoeMesh(key + "_shoe", ((List<object>)m["shoe"]).Select(Vec3).ToArray()), MountFolder + "/" + key + "_shoe.asset");
                var root = PrefabUtility.LoadPrefabContents(prefabPath);
                try
                {
                    root.name = key;
                    var rail = root.transform.Find("pylon") ?? throw new InvalidDataException(entry.Key + " has no pylon (its launch rail)");
                    var missile = rail.Find((string)m["missile"]) ?? throw new InvalidDataException(entry.Key + " has no " + m["missile"]);
                    rail.localPosition = Vector3.zero;
                    rail.localRotation = Quaternion.identity;
                    rail.localScale = Vector3.one;
                    rail.GetComponent<MeshFilter>().sharedMesh = shoe;
                    rail.GetComponent<MeshRenderer>().sharedMaterials = new[] { shoeMaterial };
                    foreach (var box in rail.GetComponents<BoxCollider>())
                        Object.DestroyImmediate(box, true);
                    missile.localPosition = Vec3(m["position"]);
                    missile.localRotation = Quaternion.Euler(Convert.ToSingle(m["pitch"]), 0f, 0f); // +x turns the nose down
                    missile.localScale = Vector3.one;
                    var capsule = missile.GetComponent<CapsuleCollider>() ?? throw new InvalidDataException(entry.Key + "'s missile has no capsule");
                    capsule.radius = Convert.ToSingle(m["capsule_radius"]);
                    PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
                }
                finally
                {
                    PrefabUtility.UnloadPrefabContents(root);
                }
                var mount = Load<Object>(assetPath);
                mount.name = key;
                var so = new SerializedObject(mount);
                Prop(so, "jsonKey").stringValue = key;
                Prop(so, "prefab").objectReferenceValue = Load<GameObject>(prefabPath);
                if (Prop(so, "missileBay").intValue != 0)
                    throw new InvalidDataException(entry.Key + " is a bay mount; the conformal stations are exposed");
                so.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(mount);
                authored[key] = mount;
            }
            AssetDatabase.SaveAssets();
            Debug.Log("[Icarus] stage: conformal mounts " + string.Join(", ", authored.Keys));
            return authored;
        }

        // A box from its eight corners (bottom four then top four, each -x then +x, at the back then the front), flat
        // shaded, every face turned out from the centre.
        private static Mesh ShoeMesh(string name, Vector3[] c)
        {
            var quads = new[] { new[] { 0, 1, 3, 2 }, new[] { 4, 6, 7, 5 }, new[] { 2, 3, 7, 6 }, new[] { 0, 4, 5, 1 }, new[] { 0, 2, 6, 4 }, new[] { 1, 5, 7, 3 } };
            var centre = c.Aggregate(Vector3.zero, (a, v) => a + v) / c.Length;
            var vertices = new List<Vector3>();
            var triangles = new List<int>();
            foreach (var q in quads)
            {
                var face = q.Select(i => c[i]).ToArray();
                var normal = Vector3.Cross(face[1] - face[0], face[2] - face[0]);
                var mid = face.Aggregate(Vector3.zero, (a, v) => a + v) / 4f;
                if (Vector3.Dot(normal, mid - centre) > 0f) // Unity's front faces wind clockwise seen from outside
                    Array.Reverse(face);
                var start = vertices.Count;
                vertices.AddRange(face);
                triangles.AddRange(new[] { start, start + 1, start + 2, start, start + 2, start + 3 });
            }
            var mesh = new Mesh { name = name };
            mesh.SetVertices(vertices);
            mesh.SetTriangles(triangles, 0);
            mesh.SetUVs(0, vertices.Select(v => new Vector2(v.z, v.y + v.x)).ToList());
            mesh.RecalculateNormals();
            mesh.RecalculateTangents();
            mesh.RecalculateBounds();
            return mesh;
        }

        // Six stations in SetNames order, each set [L, R] with HardpointIndex 0..5 left before right.
        private static void BuildStations(Build b)
        {
            // A wing station hangs under the middle of its pylon's flat lower edge, as stock blades put theirs, so every
            // mount's hooks and twin rack bear on the blade (art/blender/stations.py PYLONS).
            Vector3 PylonPoint(string pylon)
            {
                var probe = new GameObject("pylon_probe").transform;
                probe.SetPositionAndRotation(b.Blockout.Local(pylon), b.Blockout.Rotation(pylon));
                var points = WorldVertices(probe, b.Meshes[pylon].Render);
                Object.DestroyImmediate(probe.gameObject);
                var low = points.Min(v => v.y);
                var edge = points.Where(v => v.y < low + 0.01f).ToArray();
                return new Vector3(points.Average(v => v.x), low, (edge.Max(v => v.z) + edge.Min(v => v.z)) / 2f);
            }
            // A wingtip station sits on the flat tip face, 0.005 m in from it at mid-thickness, 0.545 of the tip chord back
            // from the leading edge, where both hooks of every wingtip mount's rail bear on the face (Stores rule 5 as the
            // owner redefined it); its roll turns the mount's rail onto the face, so the store hangs beside the tip.
            Vector3 TipPoint(string side)
            {
                var vertices = WorldVertices(b.Parts["wing_skin_" + side].transform, b.Meshes["wing_skin_" + side].Render);
                var outer = vertices.Max(v => Mathf.Abs(v.x));
                var tip = vertices.Where(v => Mathf.Abs(v.x) > outer - 0.001f).ToArray();
                var leading = tip.Max(v => v.z);
                return new Vector3(Mathf.Sign(tip[0].x) * (outer - 0.005f), (tip.Max(v => v.y) + tip.Min(v => v.y)) / 2f,
                    leading - 0.545f * (leading - tip.Min(v => v.z)));
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
            // A conformal station sits 0.005 m inside the trough floor right above it (Stores rule 9), where its mount's
            // shoe bears; x and z are the station's own (art/blender/stations.py CONFORMAL).
            var conformal = Vec3(ConformalLayout()["hardpoint_unity"]) - b.Blockout.Origin;
            Vector3 ConformalPoint(string side)
            {
                var x = (side == "L" ? 1f : -1f) * conformal.x;
                var z = conformal.z;
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
