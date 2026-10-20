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
        // The generator's material slots (art/blender/build_icarus.py and internals.py), remapped by name on import.
        // Icarus_Body is the skin, the only slot that takes a livery; the internals keep their flat review colours so a
        // part torn away reads as tank, engine or structure.
        private const string SkinSlot = "Icarus_Body";
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
            ("Icarus_Int_Cockpit", new Color32(155, 157, 160, 255), 0.2f, 0.4f),
            ("Icarus_Int_Bay", new Color32(89, 89, 92, 255), 0f, 0.2f),
            ("Icarus_Frame", new Color32(124, 126, 129, 255), 0.6f, 0.5f),
            ("Icarus_Strut", new Color32(219, 220, 221, 255), 1f, 0.75f),
            ("Icarus_Tyre", new Color32(49, 49, 49, 255), 0f, 0.1f),
        };
        // The blockout finish (sRGB): bare steel, the generator's Icarus_Body, fully metallic at smoothness 0.68 (the metal
        // map holds metallic in R and smoothness in A).
        private static readonly Color32 GrayboxPaint = new Color32(196, 198, 201, 255);
        private static readonly Color32 SteelMetal = new Color32(255, 0, 0, 173);

        // The skin on the stock AircraftSkin shader with flat maps the mod owns, since the Revoker's maps follow its own UVs.
        private static Material AuthorSkin()
        {
            var flatNormal = new Color32(128, 128, 255, 255);
            var albedo = AuthorFlatTexture(LiveryFolder + "/icarus_graybox.png", GrayboxPaint, true, false);
            var skin = new Material(Load<Shader>(Stock + "Shader/Shader Graphs_AircraftSkin_PLACEHOLDER.shader")) { name = "Icarus_skin" };
            skin.SetTexture("_Basecolor", albedo);
            skin.SetTexture("_Livery", albedo);
            skin.SetTexture("_Metallic", AuthorFlatTexture(SkinFolder + "/icarus_graybox_m.png", SteelMetal, true, false));
            skin.SetTexture("_Normal", AuthorFlatTexture(SkinFolder + "/icarus_graybox_n.png", flatNormal, false, true));
            skin.SetTexture("_AO", AuthorFlatTexture(SkinFolder + "/icarus_graybox_ao.png", new Color32(255, 255, 255, 255), false, false));
            skin.SetTexture("_BasecolorDmg", AuthorFlatTexture(SkinFolder + "/icarus_graybox_dmg_b.png", new Color32(210, 208, 208, 165), true, false));
            skin.SetTexture("_NormalDmg", AuthorFlatTexture(SkinFolder + "/icarus_graybox_dmg_n.png", flatNormal, false, true));
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

        // A flat 64² texture the mod owns, imported with the colour space and type the stock skin maps use.
        private static Texture2D AuthorFlatTexture(string path, Color32 colour, bool sRgb, bool normalMap)
        {
            var texture = new Texture2D(64, 64, TextureFormat.RGBA32, false);
            texture.SetPixels32(Enumerable.Repeat(colour, 64 * 64).ToArray());
            var png = texture.EncodeToPNG();
            Object.DestroyImmediate(texture);
            if (!File.Exists(path) || !File.ReadAllBytes(path).SequenceEqual(png))
            {
                File.WriteAllBytes(path, png);
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            }
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            var type = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
            if (importer.textureType != type || importer.sRGBTexture != sRgb)
            {
                importer.textureType = type;
                importer.sRGBTexture = sRgb;
                importer.SaveAndReimport();
            }
            return Load<Texture2D>(path);
        }

        private sealed class LiveryEntry
        {
            public string Name;
            public Object Faction, Data;
        }

        // The Icarus flies for Primeva (PALA) only. The livery's texture is the blockout grey on the skin's own UVs, which
        // UnitPart.SetLivery sets as _Livery; LiveryData.Colors[0] is the paint the HUD and mounts read.
        private static List<LiveryEntry> AuthorLiveries(Texture2D skinLivery)
        {
            AssetDatabase.DeleteAsset(LiveryFolder + "/icarus_pala_blockout.asset"); // the grey blockout livery it replaced
            var data = ScriptableObject.CreateInstance(GameType("LiveryData"));
            data.name = "icarus_pala_steel";
            var so = new SerializedObject(data);
            Prop(so, "Texture").objectReferenceValue = skinLivery;
            Prop(so, "Glossiness").floatValue = 0f;
            var colors = Prop(so, "Colors");
            colors.arraySize = 1;
            colors.GetArrayElementAtIndex(0).FindPropertyRelative("Color").colorValue = GrayboxPaint;
            colors.GetArrayElementAtIndex(0).FindPropertyRelative("Count").intValue = 1;
            so.ApplyModifiedPropertiesWithoutUndo();
            return new List<LiveryEntry>
            {
                new LiveryEntry
                {
                    Name = "PALA Bare Steel",
                    Faction = Load<Object>(Stock + "MonoBehaviour/Primeva_PLACEHOLDER.asset"),
                    Data = SaveAsset(data, LiveryFolder + "/" + data.name + ".asset"),
                },
            };
        }

        // Every renderer wearing the skin goes in its part's damageMaterial.renderers, the only renderers UnitPart.SetLivery
        // paints and tints with damage.
        private static void ListLiveryRenderers(Build b)
        {
            var aeroType = GameType("AeroPart");
            var listed = 0;
            foreach (var renderer in b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.sharedMaterials.Contains(b.Skin)))
            {
                var owner = renderer.GetComponentInParent(aeroType, true);
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
