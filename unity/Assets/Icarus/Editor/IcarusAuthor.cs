using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Blueprinter;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    // Authors the F-240 Icarus II blockout into the mod folder from two inputs: the FS-12 Revoker (Fighter1), whose
    // systems are kept, and the export of tools/export_blockout.py (art/export), which replaces its airframe, aero tree,
    // damage structure, engine rig and stations. Rerunnable: every asset is rewritten in place at a fixed path, so GUIDs
    // survive a rerun. Game types live in the imported Assembly-CSharp, which an asmdef can't reference, so their fields
    // are set through SerializedObject by name; a renamed field throws.
    public static partial class IcarusAuthor
    {
        private const string ModFolder = "Assets/Blueprinter/Mods/icarus";
        private const string BlockoutFolder = ModFolder + "/Blockout";
        private const string MeshFolder = ModFolder + "/Meshes";
        private const string SkinFolder = ModFolder + "/Skin";
        private const string LiveryFolder = ModFolder + "/Liveries";
        private const string PrefabName = "Icarus";
        private const string PrefabPath = ModFolder + "/" + PrefabName + ".prefab";
        private const string DefinitionPath = ModFolder + "/Icarus.asset";
        private const string ParametersPath = ModFolder + "/Icarus_Parameters.asset";
        private const string StatusDisplayPath = ModFolder + "/Icarus_StatusDisplay.prefab";
        private const string Stock = "Assets/Blueprinter/_donotship/";
        private const string DonorPrefab = Stock + "GameObject/Fighter1_PLACEHOLDER.prefab";
        private const string DonorDefinition = Stock + "MonoBehaviour/FS-12_PLACEHOLDER.asset";
        private const string DonorParameters = Stock + "MonoBehaviour/Fighter1Parameters_PLACEHOLDER.asset";
        private const string DonorStatusDisplay = Stock + "GameObject/StatusDisplay_Fighter1_PLACEHOLDER.prefab";
        private const string DonorHudExtras = Stock + "GameObject/Fighter1_HUDExtras_PLACEHOLDER.prefab";

        public const string JsonKey = "baanish_icarus";
        private const string RootPart = "fuselage_mid";
        // .internal research R7: the first-cut empty and internal fuel masses, which the export's mass_kg and fuel_kg
        // props must add up to.
        private const float EmptyMass = 5800f, FuelMass = 2400f;

        private static string RepoRoot => Directory.GetParent(Application.dataPath).Parent.FullName;
        private static string ExportFolder => Path.Combine(RepoRoot, "art", "export");

        [MenuItem("Icarus/Author aircraft")]
        private static void AuthorFromMenu()
        {
            IcarusBuild.InitializeGameTasks();
            Author();
        }

        public static void Author()
        {
            var blockout = Blockout.Load(ExportFolder);
            Debug.Log($"[Icarus] stage: blockout {blockout.Parts.Count} entries from {blockout.Source}");
            foreach (var folder in new[] { BlockoutFolder, MeshFolder, SkinFolder, LiveryFolder })
                BlueprinterAssets.EnsureFolder(folder);
            SavedMeshes.Clear();
            var donor = Load<GameObject>(DonorPrefab);
            var skin = AuthorSkin();
            var meshes = ImportBlockout(blockout, SlotMaterialMap(skin, donor));
            var stations = ReadDonorStations(donor);
            var liveries = AuthorLiveries((Texture2D)skin.GetTexture("_Livery"));
            var statusDisplay = AuthorStatusDisplay();
            var parameters = AuthorParameters(stations, liveries, statusDisplay);
            var definition = AuthorDefinition(parameters);
            var prefab = AuthorPrefab(blockout, meshes, definition, parameters);
            Set(definition, "unitPrefab", prefab);
            foreach (var guid in AssetDatabase.FindAssets("t:Mesh", new[] { MeshFolder }))
                if (!SavedMeshes.Contains(AssetDatabase.GUIDToAssetPath(guid)))
                    AssetDatabase.DeleteAsset(AssetDatabase.GUIDToAssetPath(guid));
            AssetDatabase.SaveAssets();

            OpReferenceIndex.Refresh();
            AuthorOps(stations);
            AssetDatabase.SaveAssets();
            Debug.Log("[Icarus] Authored " + PrefabPath + " from " + blockout.Source);
        }

        // ---------- blockout ----------

        private sealed class BlockoutPart
        {
            public string Name, Fbx, Sha256, BlenderParent;
            public Vector3 Pivot, Min, Max;
            public Quaternion Rotation;
            public string[] Materials = Array.Empty<string>();
            public int[] MaterialTris = Array.Empty<int>();
            public int ColliderCount;
            public bool HasLod1, IsHinge;
            public Dictionary<string, object> Props;

            public float Number(string key) => Props.TryGetValue(key, out var v) ? Convert.ToSingle(v) : 0f;
            public string Text(string key) => Props.TryGetValue(key, out var v) ? v as string : null;
        }

        private sealed class Blockout
        {
            public string Source;
            public readonly Dictionary<string, BlockoutPart> Parts = new Dictionary<string, BlockoutPart>();
            public Vector3 Origin;

            public bool Has(string name) => Parts.ContainsKey(name);
            public bool HasMesh(string name) => Parts.TryGetValue(name, out var p) && p.Fbx != null;

            // Prefab space: the root is the fuselage_mid pivot, so a blockout position u lands at u - Origin.
            public Vector3 Local(string name) => Parts[name].Pivot - Origin;
            public Quaternion Rotation(string name) => Parts[name].Rotation;

            public static Blockout Load(string folder)
            {
                var path = Path.Combine(folder, "blockout.json");
                if (!File.Exists(path))
                    throw new FileNotFoundException("Run tools/export_blockout.py first.", path);
                var json = (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(path));
                var result = new Blockout { Source = (string)json["source_generator"] + " " + ((string)json["source_sha256"]).Substring(0, 12) };
                foreach (var entry in (Dictionary<string, object>)json["parts"])
                {
                    var part = (Dictionary<string, object>)entry.Value;
                    var bounds = part["bounds_unity"] as List<object>;
                    var axes = (Dictionary<string, object>)part["axes_unity"];
                    var slots = part.TryGetValue("materials", out var m) ? ((List<object>)m).Cast<List<object>>().ToArray() : new List<object>[0];
                    var props = (Dictionary<string, object>)part["props"];
                    result.Parts[entry.Key] = new BlockoutPart
                    {
                        Name = entry.Key, Fbx = part["fbx"] as string, Sha256 = part.TryGetValue("sha256", out var sha) ? (string)sha : null,
                        Pivot = Vec(part["pivot_unity"]), Min = bounds != null ? Vec(bounds[0]) : Vector3.zero, Max = bounds != null ? Vec(bounds[1]) : Vector3.zero,
                        Rotation = Quaternion.LookRotation(Vec(axes["forward"]), Vec(axes["up"])),
                        BlenderParent = part["blender_parent"] as string,
                        Materials = slots.Select(s => (string)s[0]).ToArray(),
                        MaterialTris = slots.Select(s => Convert.ToInt32(s[1])).ToArray(),
                        ColliderCount = part.TryGetValue("colliders", out var c) && c is List<object> list ? list.Count : 0,
                        HasLod1 = part.TryGetValue("lod1", out var l) && l is Dictionary<string, object>,
                        IsHinge = props.ContainsKey("hinge_axis"),
                        Props = props,
                    };
                }
                if (!result.Parts.ContainsKey(RootPart))
                    throw new InvalidDataException($"The blockout has no {RootPart}, the root part; the export isn't on the R13 part tree yet.");
                result.Origin = result.Parts[RootPart].Pivot;
                return result;
            }

            private static Vector3 Vec(object value)
            {
                var list = (List<object>)value;
                return new Vector3(Convert.ToSingle(list[0]), Convert.ToSingle(list[1]), Convert.ToSingle(list[2]));
            }
        }

        private sealed class PartMeshes
        {
            public Mesh Render, Lod1;
            public Mesh[] Colliders;
            public Material[] Materials, Lod1Materials; // one per submesh, as the importer remapped them
        }

        private static Dictionary<string, PartMeshes> ImportBlockout(Blockout blockout, Dictionary<string, Material> slots)
        {
            var slotOf = slots.GroupBy(s => s.Value).ToDictionary(g => g.Key, g => g.Select(s => s.Key).ToArray());
            var meshParts = blockout.Parts.Values.Where(p => p.Fbx != null).ToArray();
            var wanted = new HashSet<string>(meshParts.Select(p => BlockoutFolder + "/" + p.Fbx));
            foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { BlockoutFolder }))
            {
                var stale = AssetDatabase.GUIDToAssetPath(guid);
                if (!wanted.Contains(stale))
                    AssetDatabase.DeleteAsset(stale);
            }

            var result = new Dictionary<string, PartMeshes>();
            foreach (var part in meshParts.OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                var source = Path.Combine(ExportFolder, part.Fbx);
                var target = BlockoutFolder + "/" + part.Fbx;
                var bytes = File.ReadAllBytes(source);
                if (Sha256(bytes) != part.Sha256)
                    throw new InvalidDataException(part.Fbx + " doesn't match blockout.json; rerun the export.");
                if (!File.Exists(target) || !File.ReadAllBytes(target).SequenceEqual(bytes))
                {
                    File.WriteAllBytes(target, bytes);
                    AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
                }
                ConfigureModelImporter(target, slots);

                var assets = AssetDatabase.LoadAllAssetsAtPath(target).OfType<Mesh>().ToArray();
                // Blender suffixes a node whose name is taken in its scene (".001"); the FBX is still that node.
                Mesh Named(string name) => assets.SingleOrDefault(m => Regex.Replace(m.name, @"\.\d{3}$", "") == name);
                var meshes = new PartMeshes
                {
                    Render = Named(part.Name),
                    Colliders = Enumerable.Range(0, part.ColliderCount).Select(i => Named(part.Name + "_colmesh" + i)).ToArray(),
                    Lod1 = part.HasLod1 ? Named(part.Name + "_lod1") : null,
                };
                if (meshes.Render == null || meshes.Colliders.Contains(null) || part.HasLod1 && meshes.Lod1 == null)
                    throw new InvalidDataException($"{target} lacks the {part.Name} mesh, one of its {part.ColliderCount} collider pieces or its LOD1 hull; it holds [{string.Join(", ", assets.Select(a => a.name))}].");
                // Catches an axis or scale slip in the FBX round trip before it reaches the prefab.
                var bounds = meshes.Render.bounds;
                if ((bounds.min - part.Min).magnitude > 0.02f || (bounds.max - part.Max).magnitude > 0.02f)
                    throw new InvalidDataException($"{part.Name}: imported bounds {bounds.min}..{bounds.max} differ from the export's {part.Min}..{part.Max}.");
                var renderers = AssetDatabase.LoadAssetAtPath<GameObject>(target).GetComponentsInChildren<MeshRenderer>(true);
                Material[] MaterialsOf(Mesh mesh) => renderers.Single(r => r.GetComponent<MeshFilter>().sharedMesh == mesh).sharedMaterials;
                meshes.Materials = MaterialsOf(meshes.Render);
                meshes.Lod1Materials = meshes.Lod1 != null ? MaterialsOf(meshes.Lod1) : null;
                // The importer orders submeshes its own way and remaps each slot to its material by name; every submesh
                // must be one of the export's slots with its triangles, less the few degenerate ones the importer drops.
                var submeshes = Enumerable.Range(0, meshes.Render.subMeshCount).Select(i =>
                    (slots: i < meshes.Materials.Length && meshes.Materials[i] != null && slotOf.TryGetValue(meshes.Materials[i], out var s) ? s : new string[0],
                     tris: (int)meshes.Render.GetSubMesh(i).indexCount / 3)).ToArray();
                bool Matches((string[] slots, int tris) sub) => part.Materials.Select((name, i) => (name, i))
                    .Any(e => sub.slots.Contains(e.name) && sub.tris <= part.MaterialTris[e.i] && sub.tris >= 0.97f * part.MaterialTris[e.i]);
                bool matched;
                if (part.Materials.Contains(""))
                {
                    // An unnamed export slot (a Blender slot with no material) comes in as whatever the FBX brought, merged
                    // into a named slot's submesh or on its own: every named slot must arrive, every submesh on a known
                    // material, and the triangles add up.
                    var exported = part.MaterialTris.Sum();
                    var imported = submeshes.Sum(m => m.tris);
                    matched = submeshes.All(m => m.slots.Length > 0) && part.Materials.Where(n => n != "").All(n => submeshes.Any(m => m.slots.Contains(n)))
                        && imported <= exported && imported >= 0.97f * exported;
                    Debug.Log($"[Icarus] note: {part.Name} has an unnamed material slot in blockout.json; it wears {string.Join(", ", meshes.Materials.Select(m => m == null ? "none" : m.name))}");
                }
                else
                    matched = submeshes.Length == part.Materials.Length && submeshes.All(Matches);
                if (!matched)
                    throw new InvalidDataException($"{part.Name}: imported submeshes [{string.Join(", ", submeshes.Select(m => string.Join("/", m.slots) + " " + m.tris))}] " +
                        $"don't match its slots [{string.Join(", ", part.Materials.Zip(part.MaterialTris, (s, n) => s + " " + n))}], or a slot has no material.");
                var dropped = part.MaterialTris.Sum() - submeshes.Sum(m => m.tris);
                if (dropped > 0)
                    Debug.Log($"[Icarus] note: {part.Name} imported {dropped} fewer triangles than exported (degenerate)");
                foreach (var collider in meshes.Colliders)
                {
                    // Flat shading splits vertices per face; the hull limit counts distinct points.
                    var points = collider.vertices.Distinct().Count();
                    if (points > 255 || collider.triangles.Length / 3 > 255)
                        throw new InvalidDataException($"{collider.name} has {points} points and {collider.triangles.Length / 3} triangles; the limit is 255.");
                }
                (meshes.Render, meshes.Materials) = SkinFirst(meshes.Render, meshes.Materials, slots[SkinSlot]);
                result[part.Name] = meshes;
            }
            Debug.Log($"[Icarus] stage: imported {result.Count} meshes, {result.Values.Sum(m => m.Colliders.Length)} collider pieces, {result.Values.Count(m => m.Lod1 != null)} LOD1 hulls");
            return result;
        }

        // The mesh with the skin's submesh first (a copy in MeshFolder), or the mesh itself when it already is. The game
        // sets a livery on material slot 0 only (UnitPart.SetLivery).
        private static (Mesh Mesh, Material[] Materials) SkinFirst(Mesh mesh, Material[] materials, Material skin)
        {
            var first = Array.IndexOf(materials, skin);
            if (first <= 0)
                return (mesh, materials);
            var order = new[] { first }.Concat(Enumerable.Range(0, materials.Length).Where(i => i != first)).ToArray();
            var copy = Object.Instantiate(mesh);
            copy.name = mesh.name + "_skinfirst";
            for (var i = 0; i < order.Length; i++)
                copy.SetTriangles(mesh.GetTriangles(order[i]), i, false);
            return (SaveMesh(copy), order.Select(i => materials[i]).ToArray());
        }

        private static void ConfigureModelImporter(string path, Dictionary<string, Material> slots)
        {
            var importer = (ModelImporter)AssetImporter.GetAtPath(path);
            var changed = false;
            void Apply<T>(T current, T wanted, Action<T> set)
            {
                if (EqualityComparer<T>.Default.Equals(current, wanted))
                    return;
                set(wanted);
                changed = true;
            }
            Apply(importer.globalScale, 1f, v => importer.globalScale = v);
            Apply(importer.useFileScale, true, v => importer.useFileScale = v);
            Apply(importer.bakeAxisConversion, false, v => importer.bakeAxisConversion = v);
            Apply(importer.isReadable, true, v => importer.isReadable = v);
            Apply(importer.meshCompression, ModelImporterMeshCompression.Off, v => importer.meshCompression = v);
            Apply(importer.materialImportMode, ModelImporterMaterialImportMode.ImportStandard, v => importer.materialImportMode = v);
            Apply(importer.materialLocation, ModelImporterMaterialLocation.InPrefab, v => importer.materialLocation = v);
            var remaps = importer.GetExternalObjectMap();
            foreach (var slot in slots)
            {
                var id = new AssetImporter.SourceAssetIdentifier(typeof(Material), slot.Key);
                if (!remaps.TryGetValue(id, out var current) || current != slot.Value)
                {
                    importer.AddRemap(id, slot.Value);
                    changed = true;
                }
            }
            Apply(importer.importAnimation, false, v => importer.importAnimation = v);
            Apply(importer.animationType, ModelImporterAnimationType.None, v => importer.animationType = v);
            Apply(importer.importCameras, false, v => importer.importCameras = v);
            Apply(importer.importLights, false, v => importer.importLights = v);
            Apply(importer.importBlendShapes, false, v => importer.importBlendShapes = v);
            Apply(importer.importNormals, ModelImporterNormals.Import, v => importer.importNormals = v);
            Apply(importer.addCollider, false, v => importer.addCollider = v);
            if (changed)
                importer.SaveAndReimport();
        }

        // ---------- prefab ----------

        private sealed class Build
        {
            public GameObject Root;
            public Blockout Blockout;
            public Dictionary<string, PartMeshes> Meshes;
            public Material Skin;
            public Component Aircraft;
            public Object Parameters;
            public readonly Dictionary<string, GameObject> Parts = new Dictionary<string, GameObject>();
            public readonly Dictionary<string, Transform> Visuals = new Dictionary<string, Transform>();
            public readonly Dictionary<string, List<string>> Joints = new Dictionary<string, List<string>>(); // part -> parent, then braces
            public readonly List<Renderer> Lod1 = new List<Renderer>();
            public readonly HashSet<Transform> Placed = new HashSet<Transform>(); // effects and markers moved off donor offsets
            public readonly List<string> Report = new List<string>();
            public DonorCapture Donor;
            public Vector3 Size; // span, height on the gear at rest, length of the Icarus meshes
            public readonly List<PartSpec> Specs = new List<PartSpec>(); // R13's tree, then any extra fuel cells
            public readonly Dictionary<string, float> Mass = new Dictionary<string, float>(); // dry kg per part
            public readonly List<string> Tanks = new List<string>();

            public Transform Find(string path) => Root.transform.Find(path) ?? throw new MissingReferenceException("The Revoker has no " + path);
            public Component Part(string name) => Parts[name].GetComponent(GameType("AeroPart"));
        }

        private static GameObject AuthorPrefab(Blockout blockout, Dictionary<string, PartMeshes> meshes, Object definition, Object parameters)
        {
            var root = (GameObject)Object.Instantiate(Load<GameObject>(DonorPrefab), Vector3.zero, Quaternion.identity);
            var templates = new List<GameObject>();
            try
            {
                root.name = Path.GetFileNameWithoutExtension(PrefabPath);
                var b = new Build { Root = root, Blockout = blockout, Meshes = meshes, Parameters = parameters };
                b.Aircraft = root.GetComponent(GameType("Aircraft"));
                b.Skin = Load<Material>(SkinPath);
                Set(b.Aircraft, "definition", definition);

                b.Donor = CaptureDonor(b, templates);
                StripDonor(b);
                BuildParts(b);
                BuildSurfaces(b);
                SetAero(b);
                BuildEngine(b);
                AuthorDamage(b);
                BuildGear(b);
                BuildCockpit(b);
                PlaceSystems(b);
                BuildStations(b);
                AttachLeftovers(b);
                SetRestPose(b, definition);
                AddLods(b);
                ListLiveryRenderers(b);
                FinishRoot(b);
                BraceTouchingParts(b);
                WriteJoints(b);
                RunChecks(b, definition, parameters);
                foreach (var line in b.Report)
                    Debug.Log("[Icarus] " + line);
                return SavePrefab(root, PrefabPath);
            }
            finally
            {
                Object.DestroyImmediate(root);
                foreach (var template in templates.Where(t => t != null))
                    Object.DestroyImmediate(template);
            }
        }

        // Deletes objects after removing every reference to them from the remaining components: a list entry that
        // holds one is removed (a nav light, a gear door), a plain field is cleared and reported.
        private static void DestroyWithReferences(Build b, List<Object> doomedRoots)
        {
            var doomed = new HashSet<Object>();
            foreach (var target in doomedRoots.Where(t => t != null))
            {
                if (target is GameObject go)
                    foreach (var t in go.GetComponentsInChildren<Transform>(true))
                    {
                        doomed.Add(t.gameObject);
                        foreach (var c in t.GetComponents<Component>())
                            doomed.Add(c);
                    }
                else
                    doomed.Add(target);
            }
            foreach (var component in b.Root.GetComponentsInChildren<Component>(true))
            {
                if (component == null || doomed.Contains(component))
                    continue;
                var so = new SerializedObject(component);
                var elements = new List<(string array, int index)>();
                var fields = new List<string>();
                var it = so.GetIterator();
                while (it.Next(true))
                {
                    if (it.propertyType != SerializedPropertyType.ObjectReference || it.objectReferenceValue == null || !doomed.Contains(it.objectReferenceValue))
                        continue;
                    var match = Regex.Match(it.propertyPath, @"^(.*)\.Array\.data\[(\d+)\][^\[\]]*$");
                    if (match.Success)
                        elements.Add((match.Groups[1].Value, int.Parse(match.Groups[2].Value)));
                    else
                        fields.Add(it.propertyPath);
                }
                foreach (var path in fields)
                {
                    so.FindProperty(path).objectReferenceValue = null;
                    b.Report.Add($"strip: cleared {PathOf(component.transform, b.Root.transform)}:{component.GetType().Name}.{path}");
                }
                foreach (var (array, index) in elements.Distinct().OrderByDescending(e => e.array.Length).ThenByDescending(e => e.index))
                {
                    var list = so.FindProperty(array);
                    if (index >= list.arraySize)
                        continue; // two dead references in one entry
                    var element = list.GetArrayElementAtIndex(index);
                    if (element.propertyType == SerializedPropertyType.ObjectReference)
                        element.objectReferenceValue = null;
                    list.DeleteArrayElementAtIndex(index);
                }
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            foreach (var target in doomedRoots.Where(t => t != null && !(t is GameObject)))
                Object.DestroyImmediate(target);
            foreach (var target in doomedRoots.OfType<GameObject>().Where(t => t != null))
                Object.DestroyImmediate(target);
        }

        // ---------- helpers ----------

        private static T Ensure<T>(GameObject go) where T : Component => go.TryGetComponent<T>(out var c) ? c : go.AddComponent<T>();

        private static Transform FindDeep(Transform root, string name) =>
            root.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == name) ?? throw new MissingReferenceException("No " + name + " under " + root.name);

        private static string PathOf(Transform t, Transform root)
        {
            var parts = new List<string>();
            for (var x = t; x != null && x != root; x = x.parent)
                parts.Add(x.name);
            parts.Reverse();
            return parts.Count == 0 ? root.name : string.Join("/", parts);
        }

        private static IEnumerable<Vector3> Corners(Bounds bounds)
        {
            for (var i = 0; i < 8; i++)
                yield return bounds.center + Vector3.Scale(bounds.extents, new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1));
        }

        // A mesh's vertices in world space through the transform that draws it.
        private static Vector3[] WorldVertices(Transform t, Mesh mesh) => mesh.vertices.Select(t.TransformPoint).ToArray();

        private static Bounds BoundsOf(IEnumerable<Vector3> points)
        {
            var all = points.ToArray();
            var bounds = new Bounds(all[0], Vector3.zero);
            foreach (var p in all)
                bounds.Encapsulate(p);
            return bounds;
        }

        // Generated meshes written this run; Author deletes the rest of MeshFolder.
        private static readonly HashSet<string> SavedMeshes = new HashSet<string>();

        private static Mesh SaveMesh(Mesh mesh)
        {
            var path = MeshFolder + "/" + mesh.name + ".asset";
            SavedMeshes.Add(path);
            return SaveAsset(mesh, path);
        }

        // Writes into an existing asset when there is one, so its GUID (and every reference to it) survives.
        private static T SaveAsset<T>(T fresh, string path) where T : Object
        {
            var existing = AssetDatabase.LoadMainAssetAtPath(path);
            if (existing == null)
            {
                AssetDatabase.CreateAsset(fresh, path);
                return fresh;
            }
            if (existing.GetType() != fresh.GetType())
                throw new InvalidDataException(path + " holds a " + existing.GetType().Name + ", not a " + fresh.GetType().Name);
            var name = fresh.name;
            EditorUtility.CopySerialized(fresh, existing);
            existing.name = name;
            EditorUtility.SetDirty(existing);
            Object.DestroyImmediate(fresh);
            return (T)existing;
        }

        // Blueprinter re-links each reference to a stock asset by hierarchy path through Transform.Find, which reaches only
        // the first of same-named siblings: a duplicate's stock references would load null.
        private static GameObject SavePrefab(GameObject instance, string path)
        {
            var duplicate = instance.GetComponentsInChildren<Transform>(true)
                .GroupBy(t => AnimationUtility.CalculateTransformPath(t, instance.transform)).FirstOrDefault(g => g.Count() > 1);
            if (duplicate != null)
                throw new InvalidDataException(path + " has two transforms at '" + duplicate.Key + "'; Blueprinter would leave the second's stock references null");
            var prefab = PrefabUtility.SaveAsPrefabAsset(instance, path, out var success);
            if (!success)
                throw new InvalidOperationException("Could not save " + path);
            return prefab;
        }

        private static T Load<T>(string path) where T : Object =>
            AssetDatabase.LoadAssetAtPath<T>(path) ?? throw new FileNotFoundException("Missing asset", path);

        private static Type GameType(string name) =>
            Type.GetType(name + ", Assembly-CSharp") ?? throw new TypeLoadException("Game type " + name + " isn't loaded");

        private static SerializedProperty Prop(SerializedObject so, string path) =>
            so.FindProperty(path) ?? throw new MissingFieldException(so.targetObject.GetType().Name, path);

        private static void Set(Object target, string path, Object value)
        {
            var so = new SerializedObject(target);
            Prop(so, path).objectReferenceValue = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void Set(Object target, string path, float value)
        {
            var so = new SerializedObject(target);
            Num(Prop(so, path), value);
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void Set(Object target, string path, Vector3 value)
        {
            var so = new SerializedObject(target);
            Prop(so, path).vector3Value = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static float GetFloat(Object target, string path) => Prop(new SerializedObject(target), path).floatValue;

        private static Object GetRef(Object target, string path) => Prop(new SerializedObject(target), path).objectReferenceValue;

        private static void Num(SerializedObject so, string path, double value) => Num(Prop(so, path), value);

        // Sets a number whether the game declares the field int or float.
        private static void Num(SerializedProperty property, double value)
        {
            if (property.propertyType == SerializedPropertyType.Integer)
                property.intValue = (int)Math.Round(value);
            else if (property.propertyType == SerializedPropertyType.Float)
                property.floatValue = (float)value;
            else
                throw new InvalidDataException(property.propertyPath + " is " + property.propertyType + ", not a number");
        }

        private static void SetList(SerializedProperty list, IList<Object> values)
        {
            list.arraySize = values.Count;
            for (var i = 0; i < values.Count; i++)
                list.GetArrayElementAtIndex(i).objectReferenceValue = values[i];
        }

        private static Object[] GetList(SerializedProperty list) =>
            Enumerable.Range(0, list.arraySize).Select(i => list.GetArrayElementAtIndex(i).objectReferenceValue).ToArray();

        private static string Sha256(byte[] bytes)
        {
            using (var sha = System.Security.Cryptography.SHA256.Create())
                return string.Concat(sha.ComputeHash(bytes).Select(x => x.ToString("x2")));
        }

        // Just enough JSON for blockout.json: objects as dictionaries, arrays as lists, numbers as doubles.
        private static class MiniJson
        {
            public static object Parse(string text)
            {
                var i = 0;
                var value = Value(text, ref i);
                Skip(text, ref i);
                if (i != text.Length)
                    throw new InvalidDataException("Trailing data in JSON at " + i);
                return value;
            }

            private static void Skip(string s, ref int i)
            {
                while (i < s.Length && char.IsWhiteSpace(s[i]))
                    i++;
            }

            private static object Value(string s, ref int i)
            {
                Skip(s, ref i);
                switch (s[i])
                {
                    case '{':
                        var obj = new Dictionary<string, object>();
                        i++;
                        Skip(s, ref i);
                        if (s[i] == '}') { i++; return obj; }
                        while (true)
                        {
                            Skip(s, ref i);
                            var key = (string)Value(s, ref i);
                            Skip(s, ref i);
                            Expect(s, ref i, ':');
                            obj[key] = Value(s, ref i);
                            Skip(s, ref i);
                            if (s[i] == '}') { i++; return obj; }
                            Expect(s, ref i, ',');
                        }
                    case '[':
                        var list = new List<object>();
                        i++;
                        Skip(s, ref i);
                        if (s[i] == ']') { i++; return list; }
                        while (true)
                        {
                            list.Add(Value(s, ref i));
                            Skip(s, ref i);
                            if (s[i] == ']') { i++; return list; }
                            Expect(s, ref i, ',');
                        }
                    case '"':
                        var sb = new StringBuilder();
                        i++;
                        while (s[i] != '"')
                        {
                            if (s[i] == '\\')
                            {
                                i++;
                                var c = s[i];
                                if (c == 'u') { sb.Append((char)Convert.ToInt32(s.Substring(i + 1, 4), 16)); i += 4; }
                                else sb.Append(c == 'n' ? '\n' : c == 't' ? '\t' : c == 'r' ? '\r' : c == 'b' ? '\b' : c == 'f' ? '\f' : c);
                            }
                            else
                            {
                                sb.Append(s[i]);
                            }
                            i++;
                        }
                        i++;
                        return sb.ToString();
                    default:
                        if (string.CompareOrdinal(s, i, "true", 0, 4) == 0) { i += 4; return true; }
                        if (string.CompareOrdinal(s, i, "false", 0, 5) == 0) { i += 5; return false; }
                        if (string.CompareOrdinal(s, i, "null", 0, 4) == 0) { i += 4; return null; }
                        var start = i;
                        while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0)
                            i++;
                        if (start == i)
                            throw new InvalidDataException("Unexpected '" + s[i] + "' in JSON at " + i);
                        return double.Parse(s.Substring(start, i - start), System.Globalization.CultureInfo.InvariantCulture);
                }
            }

            private static void Expect(string s, ref int i, char c)
            {
                if (s[i] != c)
                    throw new InvalidDataException("Expected '" + c + "' in JSON at " + i);
                i++;
            }
        }
    }
}
