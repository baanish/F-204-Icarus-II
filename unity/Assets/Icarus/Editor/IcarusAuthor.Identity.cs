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
        // The hardpoint set order is an API: loadouts and Blueprinter registrations address sets by position.
        // The tip tanks share the Wingtip set with its missiles: the tank mount seats its tank upright on the rolled
        // hardpoint (AuthorTipTankMount), so no set precludes another.
        private static readonly string[] SetNames = { "Wingtip", "Inner Wing", "Conformal" };

        // What each set carries: a starter jet, so a Starfighter's kind of load and little that is advanced. The wingtip
        // stations take the MMR-S3 and IRM-S2 on their own rails, or the tip tank; the wing pylons the missiles (the AAM-36 Scimitar is the interceptor's
        // one long-range shot), the AGM-68 against armour, the 500 kg and cluster bombs, the Genie, the GPO-N (1.5 kt and 250 kt) and the pods, one store
        // each, or a twin rack of MMR-S3, IRM-S2 or AAM-29; the semi-recessed conformal stations the MMR-S3, IRM-S2 and
        // AAM-29 on the Icarus's own low mounts (AuthorConformalMounts). No ARADs, AGM-99, Tusko-B, GBM-500LR or GPO-2P
        // Auger, and no other double or triple racks (a rocket pod is one store).
        private static readonly string[][] StationKeys =
        {
            new[] { "AAM1_single", "AAM3_single", TipTank },
            new[] { "AAM1_single", "AAM3_single", "AAM2_single", "AAM4_single", "AAM1_double", "AAM3_double", "AAM2_double",
                    "AGM_heavy_single", "bomb_500_single", "bomb_cluster1_single", "AIR-2_Genie_single", "nuclearBomb1_external", "nuclearBomb1_strategic_external", "Rocket2_4Pod",
                    "SpecialSmokePod", "SpecialFlarePod" },
            new[] { ConformalAAM1, ConformalAAM3, ConformalAAM2 },
        };
        // The conformal mounts' jsonKeys (art/blender/stations.py MOUNTS).
        private const string ConformalAAM1 = "baanish_icarus_AAM1_conformal", ConformalAAM3 = "baanish_icarus_AAM3_conformal",
            ConformalAAM2 = "baanish_icarus_AAM2_conformal";
        // Blueprinter's stand-ins for stock mounts the Revoker doesn't carry (the IRM-S2).
        private const string MountPlaceholders = "Assets/Blueprinter/_donotship/MonoBehaviour/";

        private sealed class Stations
        {
            public readonly List<Object>[] Options = new List<Object>[SetNames.Length];
            public readonly Dictionary<string, Object> ByKey = new Dictionary<string, Object>();
        }

        // Standard loadouts by mount jsonKey, one per set in SetNames order. loadouts[1], the default, is the first: the
        // Interceptor carries the tip tanks on its wingtips (the owner's call), the others their wingtip missiles.
        private static readonly (string Name, string[] Keys)[] StandardLoadouts =
        {
            ("Interceptor", new[] { TipTank, "AAM4_single", ConformalAAM2 }),
            ("Air Superiority", new[] { "AAM3_single", "AAM1_double", ConformalAAM2 }),
            ("Strike", new[] { "AAM3_single", "bomb_500_single", ConformalAAM1 }),
            ("Close Support", new[] { "AAM3_single", "Rocket2_4Pod", ConformalAAM1 }),
        };

        private static string KeyOf(Object mount) => new SerializedObject(mount).FindProperty("jsonKey")?.stringValue;

        private static Stations ReadDonorStations(GameObject donor)
        {
            var manager = donor.transform.Find("fuselage/cockpit").GetComponent(GameType("WeaponManager"));
            var sets = Prop(new SerializedObject(manager), "hardpointSets");
            var stations = new Stations();
            foreach (var own in AuthorConformalMounts())
                stations.ByKey[own.Key] = own.Value;
            stations.ByKey[TipTank] = AuthorTipTankMount();
            for (var i = 0; i < sets.arraySize; i++)
                foreach (var mount in GetList(sets.GetArrayElementAtIndex(i).FindPropertyRelative("weaponOptions")).Where(o => o != null))
                    stations.ByKey[KeyOf(mount)] = mount;
            Object Mount(string key) => stations.ByKey.TryGetValue(key, out var mount) ? mount
                : stations.ByKey[key] = AssetDatabase.LoadAssetAtPath<Object>(MountPlaceholders + key + "_PLACEHOLDER.asset")
                    ?? throw new InvalidDataException($"no stock mount {key}: not on the Revoker and no {MountPlaceholders}{key}_PLACEHOLDER.asset");
            for (var i = 0; i < SetNames.Length; i++)
            {
                stations.Options[i] = StationKeys[i].Select(Mount).ToList();
                Debug.Log($"[Icarus] stage: set {i} {SetNames[i]} offers {string.Join(", ", stations.Options[i].Select(KeyOf))}");
            }
            return stations;
        }

        private static Object[] LoadoutMounts(Stations stations, string name, string[] keys)
        {
            if (keys.Length != SetNames.Length)
                throw new InvalidDataException($"loadout {name} has {keys.Length} entries for {SetNames.Length} hardpoint sets");
            return keys.Select((key, set) =>
            {
                if (key == null)
                    return null;
                if (!stations.ByKey.TryGetValue(key, out var mount) || !stations.Options[set].Contains(mount))
                    throw new InvalidDataException($"loadout {name}: {key} isn't offered on set {set} {SetNames[set]}");
                return mount;
            }).ToArray();
        }

        // The sized curves (.internal research R7, re-sized by R14 to a 4.0/rad wing slope): keys as (alpha, value, in
        // tangent, out tangent).
        // The game's alpha is the airflow angle, negative for a nose-up body, so the wing's +0.12 camber lift sits at -0.12
        // on the curve at zero alpha.
        private static readonly float[][] WingLift =
        {
            new[] { -3.141593f, 0f, 0f, 0f }, new[] { -1.570796f, 0f, 0f, -1.399854f }, new[] { -0.785f, -1.1f, -1.399854f, 0.736842f },
            new[] { -0.31f, -0.75f, 0.736842f, -2.777778f }, new[] { -0.22f, -1.0f, -2.777778f, 4.0f }, new[] { 0f, -0.12f, 4.0f, 4.0f },
            new[] { 0.22f, 0.76f, 4.0f, -2.111111f }, new[] { 0.31f, 0.57f, -2.111111f, 1.115789f }, new[] { 0.785f, 1.1f, 1.115789f, -1.399854f },
            new[] { 1.570796f, 0f, -1.399854f, 0f }, new[] { 3.141593f, 0f, 0f, 0f },
        };
        private static readonly float[][] WingDrag =
        {
            new[] { -3.1416f, 0.02f, 0.400865f, 0.400865f }, new[] { -1.57f, 0.65f, 0.400865f, -0.063694f }, new[] { -0.785f, 0.6f, -0.063694f, -0.774737f },
            new[] { -0.31f, 0.232f, -0.774737f, -1.090909f }, new[] { -0.2f, 0.112f, -1.090909f, -0.875f }, new[] { -0.15f, 0.06825f, -0.875f, -0.625f },
            new[] { -0.1f, 0.037f, -0.625f, -0.375f }, new[] { -0.05f, 0.01825f, -0.375f, -0.125f }, new[] { 0f, 0.012f, -0.125f, 0.125f },
            new[] { 0.05f, 0.01825f, 0.125f, 0.375f }, new[] { 0.1f, 0.037f, 0.375f, 0.625f }, new[] { 0.15f, 0.06825f, 0.625f, 0.875f },
            new[] { 0.2f, 0.112f, 0.875f, 1.090909f }, new[] { 0.31f, 0.232f, 1.090909f, 0.774737f }, new[] { 0.785f, 0.6f, 0.774737f, 0.063694f },
            new[] { 1.57f, 0.65f, 0.063694f, -0.400865f }, new[] { 3.1416f, 0.02f, -0.400865f, -0.400865f },
        };
        private static readonly float[][] TailLift =
        {
            new[] { -3.141593f, 0f, 0f, 0f }, new[] { -1.570796f, 0f, 0f, -1.399854f }, new[] { -0.785f, -1.1f, -1.399854f, 0.735632f },
            new[] { -0.35f, -0.78f, 0.735632f, -2.888889f }, new[] { -0.26f, -1.04f, -2.888889f, 4f }, new[] { 0f, 0f, 4f, 4f },
            new[] { 0.26f, 1.04f, 4f, -2.888889f }, new[] { 0.35f, 0.78f, -2.888889f, 0.735632f }, new[] { 0.785f, 1.1f, 0.735632f, -1.399854f },
            new[] { 1.570796f, 0f, -1.399854f, 0f }, new[] { 3.141593f, 0f, 0f, 0f },
        };
        private static readonly float[][] BodyLift =
        {
            new[] { -3.141593f, 0f, 0f, 0f }, new[] { -1.570796f, 0f, 0f, -1.399854f }, new[] { -0.785f, -1.1f, -1.399854f, 1.408046f },
            new[] { -0.35f, -0.4875f, 1.408046f, -1.805556f }, new[] { -0.26f, -0.65f, -1.805556f, 2.5f }, new[] { 0f, 0f, 2.5f, 2.5f },
            new[] { 0.26f, 0.65f, 2.5f, -1.805556f }, new[] { 0.35f, 0.4875f, -1.805556f, 1.408046f }, new[] { 0.785f, 1.1f, 1.408046f, -1.399854f },
            new[] { 1.570796f, 0f, -1.399854f, 0f }, new[] { 3.141593f, 0f, 0f, 0f },
        };
        // The tail and body share one drag curve.
        private static readonly float[][] TailDrag =
        {
            new[] { -3.1416f, 0.02f, 0.400865f, 0.400865f }, new[] { -1.57f, 0.65f, 0.400865f, -0.063694f }, new[] { -0.785f, 0.6f, -0.063694f, -0.716667f },
            new[] { -0.35f, 0.28825f, -0.716667f, -1.2f }, new[] { -0.25f, 0.16825f, -1.2f, -1.125f }, new[] { -0.2f, 0.112f, -1.125f, -0.875f },
            new[] { -0.15f, 0.06825f, -0.875f, -0.625f }, new[] { -0.1f, 0.037f, -0.625f, -0.375f }, new[] { -0.05f, 0.01825f, -0.375f, -0.125f },
            new[] { 0f, 0.012f, -0.125f, 0.125f }, new[] { 0.05f, 0.01825f, 0.125f, 0.375f }, new[] { 0.1f, 0.037f, 0.375f, 0.625f },
            new[] { 0.15f, 0.06825f, 0.625f, 0.875f }, new[] { 0.2f, 0.112f, 0.875f, 1.125f }, new[] { 0.25f, 0.16825f, 1.125f, 1.2f },
            new[] { 0.35f, 0.28825f, 1.2f, 0.716667f }, new[] { 0.785f, 0.6f, 0.716667f, 0.063694f }, new[] { 1.57f, 0.65f, 0.063694f, -0.400865f },
            new[] { 3.1416f, 0.02f, -0.400865f, -0.400865f },
        };

        // Airfoil indices into AircraftParameters.airfoils; the Revoker's canard curve (its index 0) is gone, so every part
        // index is authored fresh rather than shifted.
        private const int WingAirfoil = 0, TailAirfoil = 1, BodyAirfoil = 2;
        private static readonly (string Name, float[][] Lift, float[][] Drag)[] Airfoils =
        {
            ("Icarus_wing", WingLift, WingDrag), ("Icarus_tail", TailLift, TailDrag), ("Icarus_body", BodyLift, TailDrag),
        };

        private static AnimationCurve Curve(float[][] keys) =>
            new AnimationCurve(keys.Select(k => new Keyframe(k[0], k[1], k[2], k[3])).ToArray()) { preWrapMode = WrapMode.ClampForever, postWrapMode = WrapMode.ClampForever };

        // AI numbers. The landing AI flies landingSpeed x sqrt(mass / maxWeight) (AIPilotLandingState.cs:96), so the
        // field is the speed at MaxWeight that gives R7's 75 m/s approach at 20% fuel (LowFuelLandingMass).
        private const float MaxWeight = EmptyMass + FuelMass + 2000f; // 2 t of stores
        private const float LowFuelLandingMass = EmptyMass + 0.2f * FuelMass;
        private const float ApproachAtLowFuel = 75f;
        private static float LandingSpeedField => ApproachAtLowFuel * Mathf.Sqrt(MaxWeight / LowFuelLandingMass);

        private static Object AuthorParameters(Stations stations, List<LiveryEntry> liveries, GameObject statusDisplay, GameObject hudExtras)
        {
            var parameters = Object.Instantiate(Load<Object>(DonorParameters));
            parameters.name = Path.GetFileNameWithoutExtension(ParametersPath);
            var so = new SerializedObject(parameters);
            Prop(so, "aircraftName").stringValue = JsonKey;

            var airfoils = Prop(so, "airfoils");
            airfoils.arraySize = Airfoils.Length;
            for (var i = 0; i < Airfoils.Length; i++)
            {
                var airfoil = airfoils.GetArrayElementAtIndex(i);
                airfoil.FindPropertyRelative("name").stringValue = Airfoils[i].Name;
                airfoil.FindPropertyRelative("liftCoef").animationCurveValue = Curve(Airfoils[i].Lift);
                airfoil.FindPropertyRelative("dragCoef").animationCurveValue = Curve(Airfoils[i].Drag);
            }

            var loadouts = Prop(so, "loadouts");
            loadouts.arraySize = 2;
            SetList(loadouts.GetArrayElementAtIndex(0).FindPropertyRelative("weapons"), new Object[SetNames.Length]);
            SetList(loadouts.GetArrayElementAtIndex(1).FindPropertyRelative("weapons"), LoadoutMounts(stations, StandardLoadouts[0].Name, StandardLoadouts[0].Keys));
            var standard = Prop(so, "StandardLoadouts");
            standard.arraySize = StandardLoadouts.Length;
            for (var i = 0; i < StandardLoadouts.Length; i++)
            {
                var entry = standard.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("disabled").boolValue = false;
                entry.FindPropertyRelative("Name").stringValue = StandardLoadouts[i].Name;
                entry.FindPropertyRelative("FuelRatio").floatValue = 1f;
                SetList(entry.FindPropertyRelative("loadout").FindPropertyRelative("weapons"), LoadoutMounts(stations, StandardLoadouts[i].Name, StandardLoadouts[i].Keys));
            }
            Num(so, "DefaultFuelLevel", 1f);
            // The Revoker's takeoff music is its own theme.
            Prop(so, "takeoffMusic").objectReferenceValue = null;

            var liveriesProp = Prop(so, "liveries");
            liveriesProp.arraySize = liveries.Count;
            for (var i = 0; i < liveries.Count; i++)
            {
                var entry = liveriesProp.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("name").stringValue = liveries[i].Name;
                entry.FindPropertyRelative("faction").objectReferenceValue = liveries[i].Faction;
                var reference = entry.FindPropertyRelative("assetReference");
                reference.FindPropertyRelative("m_AssetGUID").stringValue = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(liveries[i].Data));
                reference.FindPropertyRelative("m_SubObjectName").stringValue = string.Empty;
            }
            Prop(so, "StatusDisplay").objectReferenceValue = statusDisplay;
            // The Icarus's copy of the Revoker's HUD extras (IcarusAuthor.Hud.cs): its overspeed warning at the Icarus's speeds.
            Prop(so, "HUDExtras").objectReferenceValue = hudExtras;

            // First-cut AI numbers (R4/R7): an interceptor that bleeds energy in turns and lands fast.
            Num(so, "aircraftGLimit", 7.33f); // the F-104's limit
            Num(so, "maxSpeed", 800f);
            // The takeoff AI rotates at 0.7 of this and gains about 30 m/s in the rotation on afterburner: 75 lifts off at
            // 90 to 94 m/s, inside R7's band; below about 70 m/s the stabilator cannot raise the nose.
            Num(so, "takeoffSpeed", 75f);
            Num(so, "takeoffDistance", 1500f);
            Num(so, "turningRadius", 2500f);
            Num(so, "cornerSpeed", 250f);
            Num(so, "approachSpeed", 85f);
            Num(so, "landingSpeed", LandingSpeedField);
            Num(so, "shortLandingSpeed", ApproachAtLowFuel);
            // Full dry: throttleRemap ends at 0.88 and the afterburner starts at 0.9 (R7).
            Num(so, "cruiseThrottle", 0.85f);
            // Tier 2, the owner's call: unlocked a rank before the Revoker it is built on, beside the Brawler.
            Prop(so, "rankRequired").intValue = 2;
            so.ApplyModifiedPropertiesWithoutUndo();
            Debug.Log($"[Icarus] stage: parameters {Airfoils.Length} airfoils, {StandardLoadouts.Length} standard loadouts, landingSpeed {LandingSpeedField:F1} (75 m/s at {LowFuelLandingMass:0} kg of {MaxWeight:0})");
            return SaveAsset(parameters, ParametersPath);
        }

        private static Object AuthorDefinition(Object parameters)
        {
            var definition = Object.Instantiate(Load<Object>(DonorDefinition));
            definition.name = Path.GetFileNameWithoutExtension(DefinitionPath);
            var so = new SerializedObject(definition);
            Prop(so, "jsonKey").stringValue = JsonKey;
            Prop(so, "unitName").stringValue = "F-204 Icarus II";
            Prop(so, "code").stringValue = "F-204";
            Prop(so, "description").stringValue = "A modernized Starfighter: a single-turbojet interceptor on a cranked-arrow wing with leading-edge flaps and a vectoring iris nozzle. Fast and quick to climb, it bleeds energy in a turn. Six stations carry missiles and light strike stores.";
            Num(so, "roleIdentity.antiAir", 1f);
            Num(so, "roleIdentity.antiSurface", 0.3f);
            Num(so, "roleIdentity.antiRadar", 0.3f);
            // No internal bays and a conventional airframe: a larger return than the Revoker's 0.08.
            Num(so, "radarSize", 0.25f);
            Num(so, "value", 45f);
            Num(so, "mass", EmptyMass);
            Num(so, "manpower", 1);
            Prop(so, "aircraftParameters").objectReferenceValue = parameters;
            // The HUD markers (friendlyIcon, hostileIcon) stay the donor's hudIcon_aircraft, which every stock aircraft shares.
            Prop(so, "mapIcon").objectReferenceValue = MapIconSprite();
            var info = Prop(so, "aircraftInfo");
            Num(info.FindPropertyRelative("emptyWeight"), EmptyMass);
            Num(info.FindPropertyRelative("maxWeight"), MaxWeight);
            Num(info.FindPropertyRelative("maxSpeed"), 2750f); // km/h: R7's Mach 2.58 at 10 km
            Num(info.FindPropertyRelative("stallSpeed"), 230f); // km/h
            Num(info.FindPropertyRelative("maneuverability"), 6f);
            // length, width, height, spawnOffset and restRotation come from the authored prefab (SetRestPose).
            so.ApplyModifiedPropertiesWithoutUndo();
            return SaveAsset(definition, DefinitionPath);
        }

        // The map and plane select icon, drawn from the built aircraft by tools/map_icon.py. Imported as the game build holds
        // the Revoker's mapIcon_revoker: one sprite at 100 pixels per unit with a centre pivot, mipmapped, bilinear,
        // clamped, sRGB and block compressed with its alpha (DXT5).
        private const string MapIconPath = ModFolder + "/Icons/Icarus_mapIcon.png";

        private static Sprite MapIconSprite()
        {
            if (!(AssetImporter.GetAtPath(MapIconPath) is TextureImporter importer))
            {
                AssetDatabase.ImportAsset(MapIconPath, ImportAssetOptions.ForceSynchronousImport);
                importer = AssetImporter.GetAtPath(MapIconPath) as TextureImporter ?? throw new FileNotFoundException("Run tools/map_icon.py first.", MapIconPath);
            }
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            var settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            settings.spritePixelsPerUnit = 100f;
            settings.spriteAlignment = (int)SpriteAlignment.Center;
            settings.spriteMeshType = SpriteMeshType.Tight;
            importer.SetTextureSettings(settings);
            importer.mipmapEnabled = true;
            importer.filterMode = FilterMode.Bilinear;
            importer.anisoLevel = 1;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.sRGBTexture = true;
            importer.alphaSource = TextureImporterAlphaSource.FromInput;
            importer.alphaIsTransparency = true;
            importer.textureCompression = TextureImporterCompression.Compressed;
            importer.SaveAndReimport();
            return Load<Sprite>(MapIconPath);
        }

        // The hangars the Revoker uses, and every stock mount on the sets that offer it.
        private static readonly string[] HangarUnitKeys = { "hangar_med", "shelter1", "Helipad" };

        private static void AuthorOps(Stations stations)
        {
            var index = OpReferenceIndex.Load();
            if (index == null || !index.Aircraft.Exists(a => a.jsonKey == JsonKey))
                throw new InvalidDataException("OpReferenceIndex doesn't list " + JsonKey + " after Refresh.");
            var sets = index.Aircraft.Find(a => a.jsonKey == JsonKey).hardpointNames;
            if (!sets.SequenceEqual(SetNames))
                throw new InvalidDataException($"A5: {JsonKey} indexes hardpoint sets [{string.Join(", ", sets)}], expected [{string.Join(", ", SetNames)}].");

            var hangarOp = ScriptableObject.CreateInstance<OpAddAircraftToHangars>();
            hangarOp.name = "OpAddAircraftToHangars_icarus";
            hangarOp.aircraftJsonKey = JsonKey;
            foreach (var key in HangarUnitKeys)
            {
                var hangar = index.HangarUnits.Find(h => h.jsonKey == key) ?? throw new InvalidDataException("OpReferenceIndex has no hangar unit " + key + ".");
                hangarOp.hangars.Add(new OpAddAircraftToHangars.HangarTarget { hangarUnitJsonKey = hangar.jsonKey, hangarNames = new List<string>(hangar.hangarNames) });
            }
            SaveAsset(hangarOp, ModFolder + "/" + hangarOp.name + ".asset");

            var offered = new Dictionary<string, List<int>>();
            for (var set = 0; set < SetNames.Length; set++)
                foreach (var mount in stations.Options[set])
                {
                    var key = KeyOf(mount);
                    if (!offered.TryGetValue(key, out var list))
                        offered[key] = list = new List<int>();
                    list.Add(set);
                }
            // A stock mount the index doesn't know can't be registered; a standard loadout must not need one. The mod's own
            // mounts are registered by their own keys, as baanish-armory registers its Lance pod.
            var own = stations.Options.SelectMany(o => o).Where(m => AssetDatabase.GetAssetPath(m).StartsWith(ModFolder + "/", StringComparison.Ordinal))
                .Select(KeyOf).ToHashSet();
            var unknown = offered.Keys.Where(k => !index.Weapons.Contains(k) && !own.Contains(k)).OrderBy(k => k, StringComparer.Ordinal).ToArray();
            var needed = unknown.Where(k => StandardLoadouts.Any(l => l.Keys.Contains(k))).ToArray();
            if (needed.Length > 0)
                throw new InvalidDataException("A5: OpReferenceIndex has no weapon " + string.Join(", ", needed) + ", which a standard loadout carries.");
            foreach (var key in unknown)
                offered.Remove(key);
            if (unknown.Length > 0)
                Debug.Log("[Icarus] note: not registered, unknown to OpReferenceIndex: " + string.Join(", ", unknown));
            foreach (var path in Directory.GetFiles(ModFolder, "OpAddWeaponToHardpoint_*.asset"))
                if (!offered.ContainsKey(Path.GetFileNameWithoutExtension(path).Substring("OpAddWeaponToHardpoint_".Length)))
                    if (!AssetDatabase.DeleteAsset(path.Replace('\\', '/')))
                        throw new IOException("Could not remove retired hardpoint operation " + path);
            foreach (var entry in offered.OrderBy(e => e.Key, StringComparer.Ordinal))
            {
                if (entry.Value.Any(set => set < 0 || set >= sets.Count))
                    throw new InvalidDataException($"A5: {entry.Key} registers on sets [{string.Join(", ", entry.Value)}] outside 0..{sets.Count - 1}.");
                var op = ScriptableObject.CreateInstance<OpAddWeaponToHardpoint>();
                op.name = "OpAddWeaponToHardpoint_" + entry.Key;
                op.weaponJsonKey = entry.Key;
                op.aircraft.Add(new OpAddWeaponToHardpoint.AircraftTarget { aircraftJsonKey = JsonKey, hardpointIndices = new List<int>(entry.Value) });
                SaveAsset(op, ModFolder + "/" + op.name + ".asset");
            }
            Debug.Log($"[Icarus] check A5 registration PASS: sets [{string.Join(", ", sets)}]; hangars [{string.Join(", ", HangarUnitKeys)}]; {offered.Count} mounts ({own.Count} the mod's own): " +
                string.Join("; ", offered.OrderBy(e => e.Key, StringComparer.Ordinal).Select(e => e.Key + " on " + string.Join("/", e.Value))));
        }
    }
}
