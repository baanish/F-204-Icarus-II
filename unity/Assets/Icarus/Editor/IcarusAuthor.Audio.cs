using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditorInternal;
using UnityEngine;
using Object = UnityEngine.Object;

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

        // The owner's aircraft sounds (audio research, aircraft pass): new gear travel, gear lock and belly scrape,
        // Earshot v0.4.0 renders of CC0 recordings (Audio/CREDITS.md). By the owner's choice, flare release, tyre roll
        // and skid, speed-brake airflow and canopy jettison keep the Revoker's stock clips (StockAircraftClips).
        private const string GearTravelClipPath = AudioFolder + "/gear_fold_icarus.wav";
        private const string GearLockClipPath = AudioFolder + "/gear_latch_icarus.wav";
        private const string ScrapeClipPath = AudioFolder + "/runway_scrape_icarus.wav";
        private static readonly string[] DonorAircraftClips = { "gearfold", "latch1", "runway scrape" };
        // LandingGear plays fold and latch at these volumes (stock 0.3 each). The travel file matches the donor
        // gearfold's loudness, so 0.379 sits 2.0 dB over the donor in game, as the owner asked. The lock file is
        // 1.88 LU under the donor latch1 with its peak already at -1 dBTP, so 0.373 brings it level. Aircraft drives the
        // scrape source's volume to 1 in code, so the scrape file carries the donor's loudness itself.
        private const float GearTravelVolume = 0.379f, GearLockVolume = 0.373f;
        // A leg opens its doors for 1 s before extending and closes them for 1 s after retracting, then latches, which
        // stops the travel clip (LandingGear.cs:369-446). The clip must last the slowest leg's cycle, 1 s +
        // foldDegrees / foldSpeed (the nose: 1 + 90 / 30 = 4 s), or the leg goes quiet before its lock.
        private const float GearDoorSeconds = 1f;
        // The kept stock clips, by component and field: the owner heard the new ones and chose these.
        private static readonly (string type, string field, string clip)[] StockAircraftClips =
        {
            ("LandingGear", "tireNoiseSound", "wheelRollingRoad"), ("LandingGear", "tireSkidSound", "wheelSlidingRoad"),
            ("Airbrake", "airbrakeSound", "airbrake"), ("Canopy", "ejectSound", "canopyJettison"), ("FlareEjector", "ejectionSound", "flare1"),
        };

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

        private static void BuildAircraftSounds(Build b)
        {
            var travel = ImportEngineClip(GearTravelClipPath);
            var lockClip = ImportEngineClip(GearLockClipPath);
            foreach (var gear in b.Root.GetComponentsInChildren(GameType("LandingGear"), true))
            {
                Set(gear, "foldSound", travel);
                Set(gear, "foldVolume", GearTravelVolume);
                Set(gear, "latchSound", lockClip);
                Set(gear, "latchVolume", GearLockVolume);
            }
            Set(b.Aircraft, "scrapeSound", ImportEngineClip(ScrapeClipPath));
            b.Report.Add($"aircraft sounds: {Path.GetFileName(GearTravelClipPath)} at {GearTravelVolume}, {Path.GetFileName(GearLockClipPath)} at {GearLockVolume}, {Path.GetFileName(ScrapeClipPath)}");
        }

        // PCM, decompressed on load: the loops are seamless and the reheat sits at its clean -1.2 dBTP ceiling, so no
        // lossy re-encode. The aircraft sounds load the same way.
        private static AudioClip ImportEngineClip(string path)
        {
            if (!(AssetImporter.GetAtPath(path) is AudioImporter importer))
            {
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
                importer = AssetImporter.GetAtPath(path) as AudioImporter ?? throw new FileNotFoundException("Icarus clip missing; see Audio/CREDITS.md", path);
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

        private static string CheckAircraftSounds(Build b, List<string> p)
        {
            static string ClipName(Object o) => o == null ? "nothing" : o.name;
            static bool IsStock(Object o, string stock) => o != null && o.name.StartsWith(stock + "_PLACEHOLDER", StringComparison.Ordinal);
            var donor = b.Root.GetComponentsInChildren<Component>(true).Where(c => c != null && !(c is Transform))
                .SelectMany(c => { var it = new SerializedObject(c).GetIterator(); var refs = new List<string>();
                    while (it.Next(true)) if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue is AudioClip clip
                        && DonorAircraftClips.Any(n => IsStock(clip, n))) refs.Add($"{c.name}.{it.propertyPath} = {clip.name}");
                    return refs; }).ToArray();
            p.AddRange(donor.Select(d => "donor aircraft clip: " + d));

            var travel = Load<AudioClip>(GearTravelClipPath);
            var gears = b.Root.GetComponentsInChildren(GameType("LandingGear"), true);
            if (gears.Length != 3) p.Add($"{gears.Length} LandingGear, expected 3");
            var slowest = 0f;
            foreach (var gear in gears)
            {
                if (AssetDatabase.GetAssetPath(GetRef(gear, "foldSound")) != GearTravelClipPath) p.Add($"{gear.name} foldSound is {ClipName(GetRef(gear, "foldSound"))}");
                if (AssetDatabase.GetAssetPath(GetRef(gear, "latchSound")) != GearLockClipPath) p.Add($"{gear.name} latchSound is {ClipName(GetRef(gear, "latchSound"))}");
                if (GetFloat(gear, "foldVolume") != GearTravelVolume || GetFloat(gear, "latchVolume") != GearLockVolume)
                    p.Add($"{gear.name} fold/latch volume {GetFloat(gear, "foldVolume")}/{GetFloat(gear, "latchVolume")}, expected {GearTravelVolume}/{GearLockVolume}");
                slowest = Mathf.Max(slowest, GearDoorSeconds + Mathf.Abs(GetFloat(gear, "foldDegrees")) / GetFloat(gear, "foldSpeed"));
            }
            if (travel.length <= slowest) p.Add($"gear travel clip {travel.length:F2} s ends before the slowest leg's {slowest:F2} s cycle");
            if (AssetDatabase.GetAssetPath(GetRef(b.Aircraft, "scrapeSound")) != ScrapeClipPath) p.Add("scrapeSound is " + ClipName(GetRef(b.Aircraft, "scrapeSound")));

            var kept = 0;
            foreach (var (type, field, stock) in StockAircraftClips)
            {
                var holders = b.Root.GetComponentsInChildren(GameType(type), true);
                if (holders.Length == 0) p.Add($"no {type} left to keep the stock {stock}");
                foreach (var c in holders)
                {
                    var r = GetRef(c, field);
                    var clip = r is AudioSource source ? source.clip : r;
                    if (!IsStock(clip, stock)) p.Add($"{type}.{field} on {c.name} plays {ClipName(clip)}, not the kept stock {stock}");
                    else kept++;
                }
            }
            foreach (var path in new[] { GearTravelClipPath, GearLockClipPath, ScrapeClipPath })
            {
                var s = ((AudioImporter)AssetImporter.GetAtPath(path)).defaultSampleSettings;
                if (s.compressionFormat != AudioCompressionFormat.PCM || s.loadType != AudioClipLoadType.DecompressOnLoad) p.Add(Path.GetFileName(path) + " isn't PCM decompressed on load");
            }
            return $"{gears.Length} legs play the Icarus travel ({travel.length:F2} s, slowest cycle {slowest:F2} s) at {GearTravelVolume} and lock at {GearLockVolume}, Icarus scrape, {kept} kept stock slots, no donor gearfold, latch1 or runway scrape";
        }
    }
}
