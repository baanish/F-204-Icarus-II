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
        // The generator's material slots (art/blender/materials.py), remapped by name on import. Icarus_Body is the skin,
        // the only slot that takes a livery; the internals keep their stock trim materials.
        private const string SkinSlot = "Icarus_Body";
        // art/blender/uvs.py ATLAS_SIZE: every skin, livery and damage map is this square.
        private const int SkinSize = 4096;
        private const string GlassSlot = "Icarus_Glass";
        private const string LodSlot = "LOD";
        private const string SkinPath = SkinFolder + "/Icarus_skin.mat";
        private static readonly (string Slot, Color32 Colour, float Metallic, float Smoothness)[] FlatSlots =
        {
            ("Icarus_Duct", new Color32(13, 13, 13, 255), 0f, 0.2f),
            ("Icarus_Nozzle", new Color32(137, 128, 123, 255), 0.9f, 0.65f),
            ("Icarus_Petal", new Color32(180, 175, 170, 255), 0.85f, 0.7f),
            ("Icarus_Seal", new Color32(143, 140, 137, 255), 0.85f, 0.6f),
            ("Icarus_Int_Fuel", new Color32(238, 196, 97, 255), 0f, 0.4f),
            ("Icarus_Int_Engine", new Color32(149, 145, 140, 255), 0.9f, 0.6f),
            ("Icarus_Int_Structure", new Color32(219, 221, 224, 255), 0.6f, 0.5f),
            ("Icarus_Int_Avionics", new Color32(124, 180, 149, 255), 0.1f, 0.4f),
            ("Icarus_Int_Bay", new Color32(89, 89, 92, 255), 0f, 0.2f),
            ("Icarus_Frame", new Color32(50, 52, 55, 255), 0.6f, 0.5f),
            ("Icarus_Strut", new Color32(219, 220, 221, 255), 1f, 0.75f),
            ("Icarus_Tyre", new Color32(49, 49, 49, 255), 0f, 0.1f),
        };
        // The stock slots (materials.py STOCK), each the game material Blueprinter patches in for its placeholder.
        private static readonly string[] StockSlots =
        {
            "jet_mechanical", "aircraft_structure", "Matte_black", "Mirror", "Aircraft_wheels", "Fighter1_gear", "fighter1_canopy",
            "fighter1_canopy_int", "tacScreenDisplay", "CockpitWarningLight", "hotas", "Seats", "LOD", "light_red_off", "light_green_off",
            "slimelight_on",
        };
        private static Material AuthorSkin()
        {
            var albedo = ImportSkinTexture("Icarus_livery_1.png", true, false, TextureImporterFormat.DXT1);
            var skin = new Material(Load<Shader>(Stock + "Shader/Shader Graphs_AircraftSkin_PLACEHOLDER.shader")) { name = "Icarus_skin" };
            skin.SetTexture("_Basecolor", albedo);
            skin.SetTexture("_Livery", albedo);
            skin.SetTexture("_Metallic", ImportSkinTexture("Icarus_skin_m.png", false, false, TextureImporterFormat.DXT5));
            skin.SetTexture("_Normal", ImportSkinTexture("Icarus_skin_n.png", false, true, TextureImporterFormat.DXT5));
            skin.SetTexture("_AO", ImportSkinTexture("Icarus_skin_ao.png", false, false, TextureImporterFormat.DXT1));
            skin.SetTexture("_BasecolorDmg", ImportSkinTexture("Icarus_skin_dmg_b.png", true, false, TextureImporterFormat.DXT5));
            skin.SetTexture("_NormalDmg", ImportSkinTexture("Icarus_skin_dmg_n.png", false, true, TextureImporterFormat.DXT5));
            skin.SetFloat("_HitPoints", 100f);
            skin.SetFloat("_Glossiness", 0f);
            return SaveAsset(skin, SkinPath);
        }

        // Slot name -> material. The canopy wears the Revoker canopy's own glass, so the stock Canopy can crack it.
        private static Dictionary<string, Material> SlotMaterialMap(Material skin, GameObject donor)
        {
            var glass = donor.transform.Find("fuselage/cockpit/canopyHingea/canopyHingeb/canopyFrame/canopyGlass_exterior")?.GetComponent<MeshRenderer>()?.sharedMaterial
                ?? throw new MissingReferenceException("The Revoker's canopyGlass_exterior has no material");
            var map = new Dictionary<string, Material> { { SkinSlot, skin }, { GlassSlot, glass }, { LodSlot, Load<Material>(Stock + "Material/LOD_PLACEHOLDER.mat") } };
            foreach (var (slot, colour, metallic, smoothness) in FlatSlots)
                map[slot] = AuthorFlat(slot, colour, metallic, smoothness);
            foreach (var slot in StockSlots)
                map[slot] = Load<Material>(Stock + "Material/" + slot + "_PLACEHOLDER.mat");
            AuthorCockpitMaterial(map);
            return map;
        }

        // A copy of the stock Lit material, opaque, untextured, in one colour.
        private static Material AuthorFlat(string name, Color32 colour, float metallic, float smoothness)
        {
            var m = new Material(Load<Material>(Stock + "Material/jet_mechanical_PLACEHOLDER.mat")) { name = name };
            m.SetFloat("_AlphaClip", 0f);
            m.SetFloat("_AlphaToMask", 0f);
            m.DisableKeyword("_ALPHATEST_ON");
            m.SetOverrideTag("RenderType", "Opaque");
            m.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Geometry;
            foreach (var map in new[] { "_BaseMap", "_MainTex", "_MetallicGlossMap", "_BumpMap", "_OcclusionMap" })
                if (m.HasProperty(map))
                    m.SetTexture(map, null);
            foreach (var keyword in new[] { "_METALLICSPECGLOSSMAP", "_NORMALMAP", "_OCCLUSIONMAP" })
                m.DisableKeyword(keyword);
            m.SetColor("_BaseColor", colour);
            m.SetColor("_Color", colour);
            m.SetFloat("_Metallic", metallic);
            m.SetFloat("_Smoothness", smoothness);
            return SaveAsset(m, SkinFolder + "/" + name + ".mat");
        }

        private static Texture2D ImportSkinTexture(string name, bool sRgb, bool normalMap, TextureImporterFormat format)
        {
            var source = Path.Combine(ExportFolder, "textures", name);
            var gate = (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(RepoRoot, "art/textures/gate.json")));
            var hashes = (Dictionary<string, object>)gate["outputs"];
            var bytes = File.ReadAllBytes(source);
            if (!hashes.TryGetValue(name, out var expected) || Sha256(bytes) != (string)expected)
                throw new InvalidDataException("skin texture differs from gate.json: " + name);
            var path = (name.StartsWith("Icarus_livery_") ? LiveryFolder : SkinFolder) + "/" + name;
            if (!File.Exists(path) || Sha256(File.ReadAllBytes(path)) != (string)expected)
            {
                File.WriteAllBytes(path, bytes);
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            }
            if (Sha256(File.ReadAllBytes(path)) != (string)expected)
                throw new InvalidDataException("skin texture copy SHA mismatch: " + name);
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            importer.textureType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
            importer.sRGBTexture = sRgb;
            importer.maxTextureSize = SkinSize;
            importer.mipmapEnabled = true;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.alphaSource = format == TextureImporterFormat.DXT1 ? TextureImporterAlphaSource.None : TextureImporterAlphaSource.FromInput;
            importer.textureCompression = TextureImporterCompression.Compressed;
            // The default platform takes only Automatic; the explicit DXT format goes on the Standalone override.
            var platform = importer.GetDefaultPlatformTextureSettings();
            platform.maxTextureSize = SkinSize;
            platform.format = TextureImporterFormat.Automatic;
            importer.SetPlatformTextureSettings(platform);
            var standalone = importer.GetPlatformTextureSettings("Standalone");
            standalone.overridden = true;
            standalone.maxTextureSize = SkinSize;
            standalone.format = format;
            importer.SetPlatformTextureSettings(standalone);
            importer.SaveAndReimport();
            var texture = Load<Texture2D>(path);
            if (texture.width != SkinSize || texture.height != SkinSize)
                throw new InvalidDataException("skin texture must be " + SkinSize + " square: " + name);
            return texture;
        }

        private sealed class LiveryEntry
        {
            public string Name;
            public Object Faction, Data;
        }

        private static List<LiveryEntry> AuthorLiveries(Texture2D skinLivery)
        {
            var result = new List<LiveryEntry>();
            foreach (var old in new[] { "icarus_pala_blockout", "icarus_pala_steel" })
                AssetDatabase.DeleteAsset(LiveryFolder + "/" + old + ".asset");
            var files = Directory.GetFiles(Path.Combine(RepoRoot, "art/textures/liveries"), "*.json").OrderBy(f => f).ToArray();
            if (files.Length != 4) throw new InvalidDataException("expected four PALA livery specifications");
            foreach (var file in files)
            {
                var spec = (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(file));
                var id = System.Convert.ToInt32(spec["id"]);
                var data = ScriptableObject.CreateInstance(GameType("LiveryData"));
                data.name = "icarus_pala_" + id;
                var so = new SerializedObject(data);
                Prop(so, "Texture").objectReferenceValue = id == 1 ? skinLivery : ImportSkinTexture("Icarus_livery_" + id + ".png", true, false, TextureImporterFormat.DXT1);
                Prop(so, "Glossiness").floatValue = System.Convert.ToSingle(spec["glossiness"]);
                var dominant = (List<object>)spec["dominant"];
                var colors = Prop(so, "Colors");
                colors.arraySize = 1;
                colors.GetArrayElementAtIndex(0).FindPropertyRelative("Color").colorValue = new Color32(System.Convert.ToByte(dominant[0]), System.Convert.ToByte(dominant[1]), System.Convert.ToByte(dominant[2]), 255);
                colors.GetArrayElementAtIndex(0).FindPropertyRelative("Count").intValue = 1;
                so.ApplyModifiedPropertiesWithoutUndo();
                result.Add(new LiveryEntry
                {
                    Name = (string)spec["name"],
                    Faction = Load<Object>(Stock + "MonoBehaviour/Primeva_PLACEHOLDER.asset"),
                    Data = SaveAsset(data, LiveryFolder + "/" + data.name + ".asset"),
                });
            }
            return result;
        }

        private static void AuthorLiveryMaterialCarrier(Build b)
        {
            var bare = new Material(b.Skin) { name = "Icarus_bare_metal" };
            bare.SetTexture("_Livery", Load<Texture2D>(LiveryFolder + "/Icarus_livery_4.png"));
            bare.SetTexture("_Metallic", ImportSkinTexture("Icarus_livery_4_m.png", false, false, TextureImporterFormat.DXT5));
            bare = SaveAsset(bare, SkinFolder + "/Icarus_bare_metal.mat");
            // BareMetalLivery reads slots 0/1 as the untouched skin and the Bare Metal livery/map pair.
            var carrier = new GameObject("Icarus_livery_materials") { layer = 3 };
            carrier.SetActive(false);
            carrier.transform.SetParent(b.Root.transform, false);
            var renderer = carrier.AddComponent<MeshRenderer>();
            renderer.enabled = false;
            renderer.sharedMaterials = new[] { b.Skin, bare };
        }

        // Every mesh renderer wearing the skin goes in its part's damageMaterial.renderers, the only renderers UnitPart.SetLivery
        // paints and tints with damage.
        private static void ListLiveryRenderers(Build b)
        {
            AuthorLiveryMaterialCarrier(b);
            var aeroType = GameType("AeroPart");
            var listed = 0;
            foreach (var renderer in b.Root.GetComponentsInChildren<MeshRenderer>(true)
                .Where(r => r.TryGetComponent<MeshFilter>(out var filter) && filter.sharedMesh != null && r.sharedMaterials.Contains(b.Skin)))
            {
                var owner = renderer.GetComponentInParent(aeroType, true);
                if (owner == null) throw new InvalidDataException("skin renderer has no part owner: " + renderer.name);
                var so = new SerializedObject(owner);
                var list = so.FindProperty("damageMaterial").FindPropertyRelative("renderers");
                if (GetList(list).Contains(renderer))
                    continue;
                list.arraySize++;
                list.GetArrayElementAtIndex(list.arraySize - 1).objectReferenceValue = renderer;
                so.ApplyModifiedPropertiesWithoutUndo();
                listed++;
            }
            b.Report.Add($"livery: {listed} skin renderers listed on their parts' damageMaterial");
        }
    }
}
