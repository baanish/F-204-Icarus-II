using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditorInternal;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The owner's engine (audio research round 7, take A): round 6's steady turbine A, round 7's clean dark F110 dry
        // roar A and round 6's moderately violent reheat, public-domain derived (Audio/CREDITS.md). They replace the
        // Revoker's revoker_turbine, jet_thrust and afterburner on the same sources, so the stock pitch and gain laws the
        // research mixed against still drive them: turbine pitch RPM/3000 x 1.5 at gain 0.4, dry gain from thrust ratio
        // x 1.5, reheat gain from the afterburner amount, both times the 0.5 (front) to 2 (rear) facing multiplier.
        private const string AudioFolder = ModFolder + "/Audio";
        private const string TurbineClipPath = AudioFolder + "/turbine_a_f110_r6.wav";
        private const string DryClipPath = AudioFolder + "/dry_a_f110_r7.wav";
        private const string ReheatClipPath = AudioFolder + "/afterburner_m_f110_r6.wav";
        private static readonly string[] DonorEngineClips = { "revoker_turbine", "jet_thrust", "afterburner" };
        private const float TurbineVolume = 0.4f, TurbineMaxPitch = 1.5f, ThrustMaxVolume = 1.5f;
        // ReheatGain (src/Icarus) scales this GameObject's samples, so the reheat source lives alone on it: the dry
        // roar's source shares thrust_vector with the JetNozzle.
        private const string ReheatAudioName = "afterburner_audio";

        private static void BuildEngineAudio(Build b)
        {
            var engine = b.Root.GetComponent(GameType("Turbojet"));
            var turbine = (AudioSource)GetRef(engine, "turbineAudio");
            turbine.clip = ImportEngineClip(TurbineClipPath);

            var thrust = b.Parts["nozzle"].transform.Find("thrust_vector");
            var jet = thrust.GetComponent(GameType("JetNozzle"));
            var dry = (AudioSource)GetRef(jet, "thrustAudio");
            dry.clip = ImportEngineClip(DryClipPath);

            var so = new SerializedObject(jet);
            var source = Prop(so, "afterburners").GetArrayElementAtIndex(0).FindPropertyRelative("source");
            var donorReheat = (AudioSource)source.objectReferenceValue;
            var holder = new GameObject(ReheatAudioName) { layer = thrust.gameObject.layer };
            holder.transform.SetParent(thrust, false);
            var reheat = holder.AddComponent<AudioSource>();
            if (!ComponentUtility.CopyComponent(donorReheat) || !ComponentUtility.PasteComponentValues(reheat))
                throw new InvalidOperationException("A17: couldn't copy the Revoker's afterburner AudioSource");
            reheat.clip = ImportEngineClip(ReheatClipPath);
            source.objectReferenceValue = reheat;
            so.ApplyModifiedPropertiesWithoutUndo();
            UnityEngine.Object.DestroyImmediate(donorReheat);
            b.Placed.Add(holder.transform);
            b.Report.Add($"engine audio: {Path.GetFileName(TurbineClipPath)}, {Path.GetFileName(DryClipPath)}, {Path.GetFileName(ReheatClipPath)} on thrust_vector/{ReheatAudioName}");
        }

        // PCM, decompressed on load: the loops are seamless and the reheat sits at its clean -1.2 dBTP ceiling, so no
        // lossy re-encode.
        private static AudioClip ImportEngineClip(string path)
        {
            if (!(AssetImporter.GetAtPath(path) is AudioImporter importer))
            {
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
                importer = AssetImporter.GetAtPath(path) as AudioImporter ?? throw new FileNotFoundException("Engine loop missing; see Audio/CREDITS.md", path);
            }
            var settings = importer.defaultSampleSettings;
            if (settings.loadType != AudioClipLoadType.DecompressOnLoad || settings.compressionFormat != AudioCompressionFormat.PCM
                || settings.sampleRateSetting != AudioSampleRateSetting.PreserveSampleRate)
            {
                settings.loadType = AudioClipLoadType.DecompressOnLoad;
                settings.compressionFormat = AudioCompressionFormat.PCM;
                settings.sampleRateSetting = AudioSampleRateSetting.PreserveSampleRate;
                importer.defaultSampleSettings = settings;
                importer.SaveAndReimport();
            }
            return Load<AudioClip>(path);
        }

        private static string CheckEngineAudio(Build b, List<string> p)
        {
            var donorClips = b.Root.GetComponentsInChildren<AudioSource>(true)
                .Where(a => a.clip != null && DonorEngineClips.Any(n => a.clip.name.StartsWith(n + "_PLACEHOLDER", StringComparison.Ordinal)))
                .Select(a => $"{a.name} plays {a.clip.name}").ToArray();
            p.AddRange(donorClips.Select(d => "donor engine clip: " + d));

            var engine = b.Root.GetComponent(GameType("Turbojet"));
            var turbine = (AudioSource)GetRef(engine, "turbineAudio");
            if (turbine == null || AssetDatabase.GetAssetPath(turbine.clip) != TurbineClipPath) p.Add("turbineAudio doesn't play " + TurbineClipPath);
            else if (turbine.volume != TurbineVolume || !turbine.loop) p.Add($"turbine source volume {turbine.volume}, loop {turbine.loop}");
            if (GetFloat(engine, "turbineMaxPitch") != TurbineMaxPitch || GetFloat(engine, "maxRPM") != MaxRpm) p.Add("turbine pitch law off the researched RPM/3000 x 1.5");

            var jet = b.Root.GetComponentsInChildren(GameType("JetNozzle"), true).SingleOrDefault();
            if (jet == null) return "no JetNozzle";
            var dry = (AudioSource)GetRef(jet, "thrustAudio");
            if (dry == null || AssetDatabase.GetAssetPath(dry.clip) != DryClipPath || !dry.loop) p.Add("thrustAudio doesn't loop " + DryClipPath);
            if (GetFloat(jet, "thrustMaxVolume") != ThrustMaxVolume) p.Add("thrustMaxVolume " + GetFloat(jet, "thrustMaxVolume"));
            var reheat = Prop(new SerializedObject(jet), "afterburners").GetArrayElementAtIndex(0).FindPropertyRelative("source").objectReferenceValue as AudioSource;
            if (reheat == null || AssetDatabase.GetAssetPath(reheat.clip) != ReheatClipPath || !reheat.loop) p.Add("the afterburner source doesn't loop " + ReheatClipPath);
            else if (reheat.name != ReheatAudioName || reheat.GetComponents<AudioSource>().Length != 1) p.Add($"the reheat source isn't alone on {ReheatAudioName}, so ReheatGain would raise more than the reheat");

            foreach (var path in new[] { TurbineClipPath, DryClipPath, ReheatClipPath })
            {
                var s = ((AudioImporter)AssetImporter.GetAtPath(path)).defaultSampleSettings;
                if (s.compressionFormat != AudioCompressionFormat.PCM || s.loadType != AudioClipLoadType.DecompressOnLoad) p.Add(Path.GetFileName(path) + " isn't PCM decompressed on load");
            }
            return "turbine, dry roar and reheat play the round 7 take A loops at the stock gain laws, no donor engine clip, reheat alone on " + ReheatAudioName;
        }
    }
}
