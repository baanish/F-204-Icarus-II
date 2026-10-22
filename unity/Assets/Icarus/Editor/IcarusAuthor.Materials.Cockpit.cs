using System.Collections.Generic;
using System.IO;
using Blueprinter;
using UnityEditor;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The cockpit's slots: Icarus_Int_Cockpit, the cockpit cell's old flat review colour, and Icarus_Cockpit, the slot of
        // the cockpit atlas (art/blender/cockpit_atlas.py) the interior and inner frames wear.
        private const string CockpitSlot = "Icarus_Cockpit";
        private const string CockpitFolder = ModFolder + "/Cockpit";
        // The atlas's four maps in art/export/textures, as Cockpit rule 9 has them: albedo, tangent normal, metallic (R) and
        // smoothness (A), AO; only the albedo is sRGB.
        private static readonly (string Key, bool Srgb, bool Normal)[] CockpitMaps = { ("b", true, false), ("n", false, true), ("m", false, false), ("ao", false, false) };

        private static void AuthorCockpitMaterial(Dictionary<string, Material> map)
        {
            map["Icarus_Int_Cockpit"] = AuthorFlat("Icarus_Int_Cockpit", new Color32(155, 157, 160, 255), 0.2f, 0.4f);
            BlueprinterAssets.EnsureFolder(CockpitFolder);
            var maps = new Dictionary<string, Texture2D>();
            foreach (var (key, srgb, normal) in CockpitMaps)
            {
                var name = $"{CockpitSlot}_{key}.png";
                var source = Path.Combine(ExportFolder, "textures", name);
                if (!File.Exists(source))
                    throw new FileNotFoundException("Run tools/export_blockout.py: the cockpit atlas is missing", source);
                var bytes = File.ReadAllBytes(source);
                var target = CockpitFolder + "/" + name;
                if (!File.Exists(target) || Sha256(File.ReadAllBytes(target)) != Sha256(bytes))
                {
                    File.WriteAllBytes(target, bytes);
                    AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
                }
                if (Sha256(File.ReadAllBytes(target)) != Sha256(bytes))
                    throw new InvalidDataException(target + " doesn't match " + source);
                var importer = (TextureImporter)AssetImporter.GetAtPath(target);
                var type = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
                if (importer.textureType != type || importer.sRGBTexture != srgb || importer.maxTextureSize != 2048)
                {
                    importer.textureType = type;
                    importer.sRGBTexture = srgb;
                    importer.maxTextureSize = 2048;
                    importer.SaveAndReimport();
                }
                maps[key] = Load<Texture2D>(target);
            }
            // The stock Lit, opaque, the four maps on it and no emission: no stock cockpit glows but its tac screen.
            var m = new Material(Load<Material>(Stock + "Material/jet_mechanical_PLACEHOLDER.mat")) { name = CockpitSlot };
            m.SetFloat("_AlphaClip", 0f);
            m.DisableKeyword("_ALPHATEST_ON");
            m.SetOverrideTag("RenderType", "Opaque");
            m.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Geometry;
            m.SetTexture("_BaseMap", maps["b"]);
            m.SetTexture("_MainTex", maps["b"]);
            m.SetTexture("_BumpMap", maps["n"]);
            m.SetTexture("_MetallicGlossMap", maps["m"]);
            m.SetTexture("_OcclusionMap", maps["ao"]);
            foreach (var keyword in new[] { "_NORMALMAP", "_METALLICSPECGLOSSMAP", "_OCCLUSIONMAP" })
                m.EnableKeyword(keyword);
            m.SetColor("_BaseColor", Color.white);
            m.SetColor("_Color", Color.white);
            m.SetFloat("_Metallic", 1f);
            m.SetFloat("_Smoothness", 1f); // a multiplier on the map's alpha once the map is set
            m.SetFloat("_BumpScale", 1f);
            m.SetFloat("_OcclusionStrength", 1f);
            m.SetColor("_EmissionColor", Color.black);
            m.DisableKeyword("_EMISSION");
            m.globalIlluminationFlags = MaterialGlobalIlluminationFlags.EmissiveIsBlack;
            map[CockpitSlot] = SaveAsset(m, CockpitFolder + "/" + CockpitSlot + ".mat");
        }
    }
}
