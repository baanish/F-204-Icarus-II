using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Blueprinter;
using UnityEditor;
using UnityEngine;

namespace Icarus.Editor
{
    // Batch entry point for tools/Build-Icarus.ps1, which accepts a build only on exit 0, exactly one
    // "[Icarus] Build complete: " line, no captured error, and a .nobp newer than its own start.
    public static class IcarusBuild
    {
        private const string ModName = "icarus";
        private const string ModFolder = "Assets/Blueprinter/Mods/" + ModName;
        private const string BundleCache = "BlueprinterCache/Assetbundles";

        [Serializable]
        private sealed class ModInfo
        {
            public string displayName;
            public string version;
        }

        [MenuItem("Icarus/Build mod")]
        public static void Build()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling)
                throw new InvalidOperationException("Finish play mode or compilation before building.");

            var info = JsonUtility.FromJson<ModInfo>(File.ReadAllText(ModFolder + "/modinfo.json"));
            if (info.displayName != ModName || !ModBuilder.ValidateVersion(info.version, out var version))
                throw new InvalidDataException("Expected modinfo.json with displayName " + ModName + " and a valid version.");
            var output = Path.Combine(Directory.GetParent(Application.dataPath).Parent.FullName, "build", "unity-out");
            var bundle = Path.Combine(output, ModName + "_" + version + ".nobp");

            // Blueprinter's void APIs may log an error and return without throwing.
            var errors = new List<string>();
            Application.LogCallback capture = (message, stack, type) =>
            {
                if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert)
                    errors.Add(message + "\n" + stack);
            };
            Application.logMessageReceived += capture;
            try
            {
                InitializeGameTasks();
                IcarusAuthor.Author();
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                // Unity's incremental bundle build skips an unchanged bundle and the copy keeps the cached file's old
                // timestamp; removing the output, the cached bundle and its manifest forces a real rebuild.
                Directory.CreateDirectory(output);
                Directory.CreateDirectory(BundleCache);
                File.Delete(bundle);
                File.Delete(Path.Combine(BundleCache, ModName));
                File.Delete(Path.Combine(BundleCache, ModName + ".manifest"));
                BuildDependencyBundle(info.displayName, version, output);
                if (!File.Exists(bundle) || new FileInfo(bundle).Length == 0)
                    throw new FileNotFoundException("Blueprinter did not produce the bundle.", bundle);
            }
            finally
            {
                Application.logMessageReceived -= capture;
            }
            if (errors.Count > 0)
            {
                foreach (var error in errors)
                    Debug.LogError("[Icarus] Captured build error: " + error);
                throw new InvalidOperationException("Build logged " + errors.Count + " error(s).");
            }
            Debug.Log("[Icarus] Build complete: " + bundle);
        }

        // Bundles the mod plus only its recursive stock dependencies: Blueprinter's public build bundles every imported
        // game asset, including compiled compute shaders Unity cannot rebuild. The pinned revision (9a4a8e5094) keeps the
        // per-step methods private, so they are called by reflection.
        private static void BuildDependencyBundle(string displayName, string version, string outputFolder)
        {
            var assets = BlueprinterAssets.GetModAssetPaths(ModName);
            var included = InvokeModBuilder<HashSet<string>>("GetIncludedAssetPaths", (object)assets);
            if (included == null || !PrefabHashWriter.Write(assets))
                throw new InvalidDataException("Blueprinter could not prepare mod assets.");
            var manifest = InvokeModBuilder<PatchManifest>("BuildPatchManifest", displayName, version, assets, included);
            if (manifest == null)
                throw new InvalidDataException("Blueprinter could not resolve game references.");

            const string manifestPath = BlueprinterSettings.GeneratedFolder + "/patch_manifest.json";
            BlueprinterAssets.EnsureFolder(BlueprinterSettings.GeneratedFolder);
            File.WriteAllText(manifestPath, JsonUtility.ToJson(manifest, true), Encoding.UTF8);
            AssetDatabase.ImportAsset(manifestPath, ImportAssetOptions.ForceUpdate);
            var targetAssets = assets.Concat(new[] { manifestPath }).OrderBy(path => path, StringComparer.Ordinal).ToArray();
            var gameAssets = AssetDatabase.GetDependencies(targetAssets, true)
                .Where(BlueprinterAssets.IsGameAssetPath).OrderBy(path => path, StringComparer.Ordinal).ToArray();
            Debug.Log("[Icarus] Building " + targetAssets.Length + " mod assets and " + gameAssets.Length + " required game dependencies.");
            if (!InvokeModBuilder<bool>("BuildAssetBundles", BundleCache, ModName, targetAssets, gameAssets))
                throw new InvalidDataException("Blueprinter dependency bundle build failed.");
            InvokeModBuilder<object>("CopyBuiltMod", BundleCache, ModName, displayName, version, outputFolder);
        }

        private static T InvokeModBuilder<T>(string name, params object[] arguments)
        {
            var method = typeof(ModBuilder).GetMethod(name, BindingFlags.Static | BindingFlags.NonPublic,
                null, arguments.Select(argument => argument.GetType()).ToArray(), null);
            if (method == null)
                throw new MissingMethodException("Pinned Blueprinter build method is unavailable: " + name);
            return (T)method.Invoke(null, arguments);
        }

        // The imported game UniTask DLL lacks its editor bootstrap, and stock OnValidate callbacks schedule UniTask work
        // during import, so its runtime init must run first.
        internal static void InitializeGameTasks()
        {
            var helper = Type.GetType("Cysharp.Threading.Tasks.PlayerLoopHelper, UniTask", true);
            var init = helper.GetMethod("Init", BindingFlags.Static | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
            if (init == null)
                throw new MissingMethodException("The imported game UniTask initializer is unavailable.");
            init.Invoke(null, null);
        }
    }
}
