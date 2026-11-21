// A livery builder for the F-204 Icarus II, for the game developer's livery project (Nuclear-Option-Mods).
// Put this file in that project's Assets/Scripts/Editor folder. It adds two things:
// - Nuclear Option > Create Icarus Livery Builder: a builder that works like the project's own, except that the
//   livery it builds is for the Icarus. The project's own builder can only name the game's own aircraft, so its
//   meta.json never matches the Icarus; this one writes AircraftKey "baanish_icarus", which the game matches against
//   the aircraft's key (LiveryMetaData.CheckAircraft).
// - IcarusLiveryBuilder.BuildFromCommandLine, the same build without opening the editor:
//   Unity.exe -batchmode -quit -projectPath <project> -executeMethod IcarusLiveryBuilder.BuildFromCommandLine
//     -icarusTexture <png> -icarusBundle <folder name> -icarusName <name in the game's list> [-icarusFaction Primeva|Boscali]
//     [-icarusGloss 0] [-icarusNoCopy]
using System;
using System.IO;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEngine;

public class IcarusLiveryBuilder : LiveryBuilder
{
    public const string IcarusKey = "baanish_icarus";
    // The Icarus atlas is 4096 square; Unity's default import would halve it.
    public const int AtlasSize = 4096;

    public override LiveryMetaData CreateMeta()
    {
        // The base looks Aircraft up in a dictionary, which throws on null: a builder made in code has no serialized "".
        Aircraft ??= "";
        var meta = base.CreateMeta();
        meta.Aircraft = "";
        meta.AircraftKey = IcarusKey;
        return meta;
    }

    public override void AddToBuilder(BundleBuilder builder)
    {
        base.AddToBuilder(builder);
        // The developer's BundleBuilder points the bundle at the Skins folder but leaves the remote catalog's paths as the
        // Addressables settings have them, which is empty when the project made those settings itself: then the build
        // writes no catalog_1.json and the game cannot load the livery. Use the same profile paths as the bundle.
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        settings.RemoteCatalogBuildPath.SetVariableByName(settings, "Remote.BuildPath");
        settings.RemoteCatalogLoadPath.SetVariableByName(settings, "Remote.LoadPath");
    }

    [MenuItem("Nuclear Option/Create Icarus Livery Builder")]
    private static void CreateBuilder()
    {
        var builder = ScriptableObjectUtility.CreateAsset<IcarusLiveryBuilder>("Icarus Livery Builder", "Assets", true, true);
        Selection.activeObject = builder;
    }

    // Import settings the Icarus's own liveries ship with: sRGB colour, mipmaps, full 4096 size, compressed.
    public static void ImportForIcarus(string assetPath)
    {
        var importer = (TextureImporter)AssetImporter.GetAtPath(assetPath);
        importer.textureType = TextureImporterType.Default;
        importer.sRGBTexture = true;
        importer.mipmapEnabled = true;
        importer.maxTextureSize = AtlasSize;
        importer.textureCompression = TextureImporterCompression.Compressed;
        importer.SaveAndReimport();
    }

    public static void BuildFromCommandLine()
    {
        string texture = Argument("-icarusTexture"), bundle = Argument("-icarusBundle"), name = Argument("-icarusName");
        if (texture == null || bundle == null || name == null)
            throw new ArgumentException("needs -icarusTexture <png> -icarusBundle <folder name> -icarusName <name>");
        string faction = Argument("-icarusFaction") ?? "";
        if (faction != "" && faction != "Primeva" && faction != "Boscali")
            throw new ArgumentException("-icarusFaction is Primeva or Boscali, or leave it out for both sides");

        const string folder = "Assets/IcarusLivery";
        Directory.CreateDirectory(folder);
        string assetPath = folder + "/" + bundle + ".png";
        File.Copy(texture, assetPath, true);
        AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
        ImportForIcarus(assetPath);

        var builder = CreateInstance<IcarusLiveryBuilder>();
        builder.BundleName = bundle;
        builder.CopyToAppData = Array.IndexOf(Environment.GetCommandLineArgs(), "-icarusNoCopy") < 0;
        builder.Texture = AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
        builder.Glossiness = float.Parse(Argument("-icarusGloss") ?? "0", System.Globalization.CultureInfo.InvariantCulture);
        builder.DisplayName = name;
        builder.Faction = faction;
        var bundleBuilder = new BundleBuilder(bundle);
        builder.AddToBuilder(bundleBuilder);
        bundleBuilder.Build(builder.CopyToAppData);
        Debug.Log("ICARUS LIVERY BUILT: " + bundle);
    }

    private static string Argument(string flag)
    {
        var args = Environment.GetCommandLineArgs();
        int i = Array.IndexOf(args, flag);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
