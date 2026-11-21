using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The livery list by index, pinned here rather than read from the specifications the author sorts too: a mission
        // saves a jet's livery as its index (SavedAircraft.livery), so 0 to 3 stay the four 0.3.0 shipped, and the three
        // BDF liveries follow.
        private static readonly (string Name, string Faction, string Texture)[] ReleasedLiveries =
        {
            ("PALA Navy", "PALA", "Icarus_livery_1"), ("PALA Black", "PALA", "Icarus_livery_2"), ("PALA Desert", "PALA", "Icarus_livery_3"),
            ("PALA Bare Metal", "PALA", "Icarus_livery_4"), ("BDF Matte Gray", "BDF", "Icarus_livery_5"),
            ("BDF Gray Camo", "BDF", "Icarus_livery_6"), ("BDF Bare Metal", "BDF", "Icarus_livery_7"),
        };

        private static string CheckSkin(Build b, List<string> p)
        {
            var renderers = b.Root.GetComponentsInChildren<MeshRenderer>(true);
            var skinRenderers = renderers.Where(r => r.GetComponent<MeshFilter>() != null && r.sharedMaterials.Contains(b.Skin)).ToArray();
            var carrier = b.Root.transform.Find("Icarus_livery_materials");
            var maps = carrier == null ? null : carrier.GetComponent<MeshRenderer>();
            if (carrier == null || carrier.gameObject.activeSelf || carrier.gameObject.layer != 3 || maps == null || maps.enabled || carrier.GetComponent<MeshFilter>() != null)
                p.Add("bare metal texture carrier must be inactive, disabled, layer 3 and mesh-free");
            else
            {
                var held = maps.sharedMaterials;
                var bareIds = BareMetalLiveryIds();
                if (held.Length != 1 + bareIds.Length || held[0] != b.Skin || held.Skip(1).Any(m => m == null))
                    p.Add("bare metal carrier must hold the shared skin and one material per Bare Metal livery (" + string.Join(", ", bareIds) + ")");
                else
                    for (var k = 0; k < bareIds.Length; k++)
                    {
                        var metal = held[k + 1].GetTexture("_Metallic") as Texture2D;
                        var livery = held[k + 1].GetTexture("_Livery");
                        if (metal == null || metal.width != SkinSize || metal.height != SkinSize || metal.format != TextureFormat.DXT5)
                            p.Add($"bare metal map {bareIds[k]} must be {SkinSize} square DXT5");
                        else
                        {
                            var importer = (TextureImporter)AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(metal));
                            if (importer.sRGBTexture || importer.alphaSource != TextureImporterAlphaSource.FromInput)
                                p.Add($"bare metal map {bareIds[k]} must retain linear smoothness alpha");
                        }
                        if (livery != Load<Texture2D>(LiveryFolder + "/Icarus_livery_" + bareIds[k] + ".png") || metal == b.Skin.GetTexture("_Metallic")
                            || held.Skip(1).Count(m => m.GetTexture("_Metallic") == metal) != 1)
                            p.Add($"bare metal carrier slot {k + 1} must identify livery {bareIds[k]} and its own metallic map");
                    }
            }
            if (skinRenderers.Length == 0) p.Add("no skin renderers");
            var singles = b.Blockout.Parts.Values.Where(x => x.Flag("single_sided_skin")).Select(x => x.Name).ToArray();
            if (singles.Length != SingleSidedCount || singles.Any(n => !SingleSidedNames.IsMatch(n)))
                p.Add($"single-sided skin on [{string.Join(", ", singles)}], expected the {SingleSidedCount} doors, speed brakes, nozzle, petals, seals, canopy frame and pylons");
            var drawn = 0;
            foreach (var renderer in renderers.Where(r => r.name.Contains("_detail_")))
                p.Add("unmerged detail renderer: " + renderer.name);
            foreach (var renderer in skinRenderers)
            {
                var slots = renderer.sharedMaterials;
                if (slots[0] != b.Skin || slots.Count(m => m == b.Skin) != 1)
                    p.Add(renderer.name + " skin must occur only at slot 0");
                var owner = renderer.GetComponentInParent(GameType("AeroPart"), true);
                if (owner == null)
                    p.Add(renderer.name + " has no part owner");
                else
                {
                    var damage = Prop(new SerializedObject(owner), "damageMaterial");
                    if (!GetList(damage.FindPropertyRelative("renderers")).Contains(renderer))
                        p.Add(renderer.name + " is not listed in its part's damage renderers");
                }
                var mesh = renderer.GetComponent<MeshFilter>()?.sharedMesh;
                if (mesh == null || mesh.uv.Length != mesh.vertexCount || mesh.subMeshCount == 0)
                {
                    p.Add(renderer.name + " has no complete skin UVs");
                    continue;
                }
                var uv = mesh.uv;
                var skinSlot = System.Array.IndexOf(slots, b.Skin);
                if (skinSlot < 0 || skinSlot >= mesh.subMeshCount)
                {
                    p.Add(renderer.name + " has no skin submesh");
                    continue;
                }
                foreach (var index in mesh.GetIndices(skinSlot).Distinct())
                    if (float.IsNaN(uv[index].x) || float.IsNaN(uv[index].y) || uv[index].x < 0 || uv[index].x > 1 || uv[index].y < 0 || uv[index].y > 1)
                    {
                        p.Add(renderer.name + " skin UV outside [0,1]");
                        break;
                    }
                // SkinFirst twins every skin triangle so a hole or a break shows the inside of the skin, not the sky, but on a
                // piece marked single_sided_skin, which an inner face covers; a joined mesh holds its pieces' skins as each
                // came (JoinPartMeshes). LOD1 hulls are closed and never holed.
                var skin = mesh.GetIndices(skinSlot);
                if (!b.Lod1.Contains(renderer))
                {
                    var single = SingleSidedSkin(b, renderer);
                    if (2 * OneSided(mesh.vertices, skin).Length - skin.Length != 3 * single)
                        p.Add($"{renderer.name}: {OneSided(mesh.vertices, skin).Length / 3} of {skin.Length / 3} skin triangles lack a back-facing twin, {single} single-sided by design");
                    drawn += skin.Length / 3;
                }
            }
            foreach (var property in new[] { "_Basecolor", "_Livery", "_Normal", "_AO", "_Metallic", "_BasecolorDmg", "_NormalDmg" })
            {
                var texture = b.Skin.GetTexture(property) as Texture2D;
                if (texture == null || texture.width != SkinSize || texture.height != SkinSize)
                {
                    p.Add(property + " must be " + SkinSize + " square");
                    continue;
                }
                var importer = (TextureImporter)AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(texture));
                var normal = property == "_Normal" || property == "_NormalDmg";
                var linear = normal || property == "_AO" || property == "_Metallic";
                if (importer.sRGBTexture == linear || (importer.textureType == TextureImporterType.NormalMap) != normal)
                    p.Add(property + " has incorrect colour space or texture type");
                if (property == "_Metallic" && texture.format != TextureFormat.DXT5)
                    p.Add("metallic map must preserve smoothness alpha in DXT5");
            }
            var liveries = Prop(new SerializedObject(b.Parameters), "liveries");
            var specs = LiverySpecs();
            if (liveries.arraySize != specs.Count) p.Add($"expected {specs.Count} liveries, got {liveries.arraySize}");
            if (liveries.arraySize != ReleasedLiveries.Length) p.Add($"{liveries.arraySize} liveries, the pinned list has {ReleasedLiveries.Length}");
            var textures = new HashSet<Object>();
            var factions = new HashSet<Object>();
            // The plugin's first pick (src/Icarus/BareMetalFirstPick.cs) finds each side's Bare Metal by its index here.
            var plugin = System.AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a => a.GetName().Name == "Icarus");
            int PluginIndex(string name) => (int)(plugin?.GetType("Icarus.BareMetalFirstPick", true)
                .GetField(name, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)?.GetRawConstantValue() ?? -1);
            var bareMetal = plugin == null ? new Dictionary<string, int>()
                : new Dictionary<string, int> { ["PALA"] = PluginIndex("PalaBareMetal"), ["BDF"] = PluginIndex("BdfBareMetal") };
            if (plugin == null) p.Add("Icarus.dll isn't loaded in the editor, so the first pick's Bare Metal indices go unchecked");
            foreach (var side in bareMetal)
                if (side.Value < 0 || side.Value >= specs.Count || (string)specs[side.Value]["faction"] != side.Key || (string)specs[side.Value]["pattern"] != "bands")
                    p.Add($"the plugin's {side.Key} Bare Metal index {side.Value} is not {side.Key}'s Bare Metal in the livery list");
            for (var i = 0; i < Mathf.Min(liveries.arraySize, specs.Count); i++)
            {
                var entry = liveries.GetArrayElementAtIndex(i);
                var spec = specs[i];
                var faction = entry.FindPropertyRelative("faction").objectReferenceValue;
                if (faction == null || faction != FactionAsset((string)spec["faction"]))
                    p.Add($"livery {i} ({spec["name"]}) must belong to {(spec["faction"] as string == "PALA" ? "Primeva" : "Boscali")}");
                else
                    factions.Add(faction);
                // A mission saves the index (SavedAircraft.livery): livery id n stays at n - 1, as 0.3.0 shipped ids 1 to 4.
                if (System.Convert.ToInt32(spec["id"]) != i + 1)
                    p.Add($"livery {i} ({spec["name"]}) is id {spec["id"]}, but a saved mission's livery {i} means id {i + 1}");
                if (entry.FindPropertyRelative("name").stringValue != (string)spec["name"])
                    p.Add($"livery {i} is named {entry.FindPropertyRelative("name").stringValue}, expected {spec["name"]}");
                var guid = entry.FindPropertyRelative("assetReference").FindPropertyRelative("m_AssetGUID").stringValue;
                var data = AssetDatabase.LoadAssetAtPath<Object>(AssetDatabase.GUIDToAssetPath(guid));
                if (data == null)
                {
                    p.Add("livery " + i + " has no LiveryData");
                    continue;
                }
                var so = new SerializedObject(data);
                var texture = Prop(so, "Texture").objectReferenceValue as Texture2D;
                if (texture == null || texture.width != SkinSize || texture.height != SkinSize || texture.format != TextureFormat.DXT1)
                    p.Add("livery " + i + " must be " + SkinSize + " square DXT1");
                if (texture != null && !textures.Add(texture)) p.Add("liveries share a texture");
                if (i < ReleasedLiveries.Length)
                {
                    var pinned = ReleasedLiveries[i];
                    if (entry.FindPropertyRelative("name").stringValue != pinned.Name || faction != FactionAsset(pinned.Faction) || texture == null || texture.name != pinned.Texture)
                        p.Add($"livery {i} is {entry.FindPropertyRelative("name").stringValue} ({(texture != null ? texture.name : "no texture")}), " +
                              $"pinned as {pinned.Name} of {pinned.Faction} wearing {pinned.Texture}");
                }
                if (Prop(so, "Colors").arraySize == 0) p.Add("livery " + i + " has no dominant paint");
            }
            if (factions.Count != 2) p.Add("the liveries must cover Primeva and Boscali");
            var count = b.Root.GetComponentsInChildren<LODGroup>(true).Sum(g => g.GetLODs().Length == 0 ? 0 : g.GetLODs()[0].renderers.Length);
            // LOD1 hulls wear their part's paint (art/blender/hulls.py paint_lods), so the livery and the Bare Metal swap
            // reach them; on stock's flat grey LOD material every livery fell off at range. The skin renderer checks above
            // cover slot 0, the damage list and the UV range; this adds that a hull wears what its part wears, on UVs
            // that span the atlas rather than collapsing to one texel.
            var skinHulls = 0;
            foreach (var hull in b.Lod1)
            {
                var own = b.Meshes[hull.name.Substring(0, hull.name.Length - "_lod1".Length)].Materials;
                var worn = hull.sharedMaterials;
                if (worn.Length == 0 || worn.Any(m => m == null || !own.Contains(m)))
                    p.Add($"{hull.name} wears [{string.Join(", ", worn.Select(m => m == null ? "none" : m.name))}], not its part's paint");
                else if (own.Contains(b.Skin) && !worn.Contains(b.Skin))
                    p.Add(hull.name + " lacks the skin its part wears");
                if (!worn.Contains(b.Skin))
                    continue;
                skinHulls++;
                var mesh = hull.GetComponent<MeshFilter>().sharedMesh;
                var uv = mesh.uv;
                var tris = mesh.GetIndices(System.Array.IndexOf(worn, b.Skin));
                var spread = 0;
                for (var i = 0; i < tris.Length && uv.Length == mesh.vertexCount; i += 3)
                    if (Mathf.Abs((uv[tris[i + 1]].x - uv[tris[i]].x) * (uv[tris[i + 2]].y - uv[tris[i]].y) - (uv[tris[i + 2]].x - uv[tris[i]].x) * (uv[tris[i + 1]].y - uv[tris[i]].y)) > 2e-8f)
                        spread++;
                // hulls.py fits a face's UVs inside its island, which leaves a few on one texel (at most 5 of 24 today)
                if (3 * spread < 2 * (tris.Length / 3))
                    p.Add($"{hull.name}: {spread} of {tris.Length / 3} skin triangles span the atlas; the rest sample a point");
            }
            return $"{skinRenderers.Length} registered skin renderers, {drawn} skin triangles drawn from both sides, seven liveries by id (four Primeva at their 0.3.0 indices, three Boscali; Bare Metal at {string.Join(" and ", bareMetal.Values)} for the first pick), exterior LOD0 {count} renderers, " +
                $"{b.Lod1.Count} LOD1 hulls on their parts' paint ({skinHulls} on the skin)";
        }

        // The skin drawn from one side only (art/blender/skeleton.py SINGLE_SIDED): the doors, speed brakes, nozzle, its
        // petals and seals, the canopy frame and the pylons, 50 meshes.
        private static readonly System.Text.RegularExpressions.Regex SingleSidedNames = new System.Text.RegularExpressions.Regex(
            @"^(gear_door_\w+_visible|speed_brake_[LR]_visible|nozzle|nozzle_(petal|seal)_\d\d_visible|canopy_visible|pylon_inner_\w+)$");
        private const int SingleSidedCount = 50;

        // A renderer's skin triangles from single-sided pieces: its own mesh's, or a joined mesh's pieces'.
        private static int SingleSidedSkin(Build b, Renderer renderer)
        {
            var names = b.DrawnFrom.TryGetValue(renderer, out var from) ? from : new[] { renderer.name };
            return names.Where(n => b.Blockout.Has(n) && b.Blockout.Parts[n].Flag("single_sided_skin") && b.Meshes.ContainsKey(n))
                .Sum(n => b.Meshes[n].Materials.Length > 0 && b.Meshes[n].Materials[0] == b.Skin ? (int)b.Meshes[n].Render.GetSubMesh(0).indexCount / 3 : 0);
        }

        // Triangles of a renderer's mesh with a two-sided skin counted once (OneSided); -1 without a mesh.
        private static int OneSidedCount(Component c)
        {
            var mesh = c.GetComponent<MeshFilter>()?.sharedMesh;
            return mesh == null ? -1 : OneSided(mesh.vertices, mesh.triangles).Length / 3;
        }
    }
}
