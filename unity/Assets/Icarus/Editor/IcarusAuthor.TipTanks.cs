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
        // The tip tank store (art/blender/tip_tanks.py): a mount for the Tip Tank set whose one round is the tank, released
        // like a dumb bomb through the game's networked store release. Built from copies of the stock PAB-250 (bomb_250_1:
        // its prefab, definition and weapon info) and its single mount, under the Icarus's own keys, as the MiG-29 mods
        // build their drop tanks (.internal research R2). The round has no steering and almost no warhead: it bursts on
        // impact with a puff of dust or spray, and zero effectiveness keeps the AI from choosing it as a weapon. Its fuel is
        // the plugin's (src/Icarus/TipTanks.cs): the store's mass is the full tank, which the plugin moves into the internal
        // cells as the jet burns, so a release sheds the shell and whatever fuel is left in it.
        private const string TipTank = "baanish_icarus_tip_tank";
        // The round's definition key, which src/Icarus/TipTanks.cs finds the tanks by.
        private const string TipTankRound = "baanish_icarus_tip_tank_round";
        // Per tank. Drag: the MiG-29 mod's PTB-1150 carries 0.08 on a 0.64 m body; scaled to this tank's 0.52 m frontal
        // area that is 0.053, and the fins bring it to 0.06, a little above a stock MMR-S3 on its rail (0.05). RCS scaled
        // the same way from the PTB-1150's 0.05. No empty mass, drag or RCS: the tip face stays clean when the tank goes.
        private const float TipTankDrag = 0.06f, TipTankRcs = 0.035f;
        // The release: the tank slides 0.3 m straight down at 3 m/s before the round spawns, clear of the tip face, then
        // falls outboard of every airframe part. It turns tangible 1 s after it spawns and arms at 1.5 s.
        private const float TipTankEjectLength = 0.3f, TipTankEjectSpeed = 3f;
        private const string TipTankDescription = "F-104-style wingtip fuel tanks, 170 US gal (500 kg of fuel) each. The jet burns their fuel " +
            "before its internal fuel. Select them and fire to drop the pair; the fuel left in them goes with them.";

        private static Dictionary<string, object> TipTankLayout() =>
            (Dictionary<string, object>)((Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(ExportFolder, "blockout.json"))))["tip_tank"];

        private static float TipTankMass(Dictionary<string, object> layout) =>
            Convert.ToSingle(layout["fuel_kg"]) + Convert.ToSingle(layout["dry_kg"]);

        // The tank's mesh from its pinned export, imported beside the mounts with the skin remapped onto its one slot.
        private static Mesh ImportTipTankMesh(Dictionary<string, object> layout)
        {
            var fbx = (string)layout["fbx"];
            var bytes = File.ReadAllBytes(Path.Combine(ExportFolder, fbx));
            if (Sha256(bytes) != (string)layout["sha256"])
                throw new InvalidDataException(fbx + " doesn't match blockout.json; rerun the export.");
            var target = MountFolder + "/" + fbx;
            if (!File.Exists(target) || !File.ReadAllBytes(target).SequenceEqual(bytes))
            {
                File.WriteAllBytes(target, bytes);
                AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
            }
            ConfigureModelImporter(target, new Dictionary<string, Material> { { SkinSlot, Load<Material>(SkinPath) } });
            var mesh = AssetDatabase.LoadAllAssetsAtPath(target).OfType<Mesh>().SingleOrDefault(m => m.name == "tip_tank")
                ?? throw new InvalidDataException(target + " has no tip_tank mesh");
            var bounds = (List<object>)layout["bounds_unity"];
            if ((mesh.bounds.min - Vec3(bounds[0])).magnitude > 0.02f || (mesh.bounds.max - Vec3(bounds[1])).magnitude > 0.02f)
                throw new InvalidDataException($"tip_tank: imported bounds {mesh.bounds.min}..{mesh.bounds.max} differ from the export's");
            return mesh;
        }

        // The tank on a store transform: its mesh on the skin, its capsule fitted inside the body where the tip face meets
        // it, and the two stock nav lenses on its bosses. The plugin shows each lens the wing lens's state and colour.
        private static void DressTipTank(Transform store, Mesh mesh, Dictionary<string, object> layout)
        {
            store.localPosition = Vector3.zero;
            store.localRotation = Quaternion.identity;
            store.localScale = Vector3.one;
            store.GetComponent<MeshFilter>().sharedMesh = mesh;
            store.GetComponent<MeshRenderer>().sharedMaterials = new[] { Load<Material>(SkinPath) };
            foreach (var filter in store.GetComponentsInChildren<MeshFilter>(true).Where(f => f.transform != store))
                filter.sharedMesh = null;
            var capsules = store.GetComponents<CapsuleCollider>();
            if (capsules.Length != 1)
                throw new InvalidDataException($"{store.name} has {capsules.Length} capsules, expected the stock bomb's one");
            capsules[0].direction = 2;
            capsules[0].radius = Convert.ToSingle(layout["capsule_radius"]);
            capsules[0].height = Convert.ToSingle(layout["length"]);
            capsules[0].center = Vec3(layout["centre_unity"]);
            var lensMesh = Load<Mesh>(Stock + "Mesh/fighter1_navLight_L_PLACEHOLDER.asset");
            var lensMaterial = Load<Material>(Stock + "Material/light_red_off_PLACEHOLDER.mat");
            var renderers = new List<Renderer> { store.GetComponent<MeshRenderer>() };
            foreach (var entry in ((Dictionary<string, object>)layout["lenses"]).OrderBy(e => e.Key, StringComparer.Ordinal))
            {
                var anchor = (Dictionary<string, object>)entry.Value;
                var lens = store.Find(TipTankLensPrefix + entry.Key);
                if (lens == null)
                    lens = new GameObject(TipTankLensPrefix + entry.Key) { layer = store.gameObject.layer }.transform;
                lens.SetParent(store, false);
                lens.localRotation = Quaternion.Euler(0f, 0f, Convert.ToSingle(anchor["roll_deg"]));
                lens.localScale = Vector3.one;
                // The anchor is the lens's bounds centre, as PlaceSystems places the wing lenses.
                lens.localPosition = Vec3(anchor["position"]) - lens.localRotation * lensMesh.bounds.center;
                // Unity's own null check: a missing component reads as a live object to ??.
                var filter = lens.GetComponent<MeshFilter>();
                if (filter == null)
                    filter = lens.gameObject.AddComponent<MeshFilter>();
                filter.sharedMesh = lensMesh;
                var renderer = lens.GetComponent<MeshRenderer>();
                if (renderer == null)
                    renderer = lens.gameObject.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = new[] { lensMaterial };
                renderers.Add(renderer);
            }
            var lod = store.GetComponent<LODGroup>();
            if (lod != null)
            {
                var levels = lod.GetLODs();
                levels[0].renderers = renderers.ToArray();
                lod.SetLODs(levels);
                lod.RecalculateBounds();
            }
        }

        // The lens objects' names; src/Icarus/TipTanks.cs finds them by this prefix.
        private const string TipTankLensPrefix = "tip_tank_lens_";

        private static Object AuthorTipTankMount()
        {
            BlueprinterAssets.EnsureFolder(MountFolder);
            var layout = TipTankLayout();
            if ((string)layout["key"] != TipTank)
                throw new InvalidDataException($"blockout.json's tip tank is {layout["key"]}, not {TipTank}");
            var mesh = ImportTipTankMesh(layout);
            var mass = TipTankMass(layout);
            var round = MountFolder + "/" + TipTank + "_round.prefab";
            var definition = MountFolder + "/" + TipTank + "_round.asset";
            var info = MountFolder + "/" + TipTank + "_info.asset";
            var mountPrefab = MountFolder + "/" + TipTank + ".prefab";
            var mountAsset = MountFolder + "/" + TipTank + ".asset";
            var copies = new[]
            {
                ("GameObject/bomb_250_1_PLACEHOLDER.prefab", round), ("MonoBehaviour/Bomb_250_1_PLACEHOLDER.asset", definition),
                ("MonoBehaviour/info_bomb_250_1_PLACEHOLDER.asset", info), ("GameObject/bomb_250_single_PLACEHOLDER.prefab", mountPrefab),
                ("MonoBehaviour/bomb_250_single_PLACEHOLDER.asset", mountAsset),
            };
            foreach (var (source, target) in copies)
            {
                File.Copy(Stock + source, target, true); // keeps the target's .meta, so its GUID survives
                AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
            }
            var remap = copies.ToDictionary(c => Load<Object>(Stock + c.Item1), c => Load<Object>(c.Item2));
            void Remap(Object target)
            {
                var so = new SerializedObject(target);
                var it = so.GetIterator();
                while (it.Next(true))
                    if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue != null && remap.TryGetValue(it.objectReferenceValue, out var mine))
                        it.objectReferenceValue = mine;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            void EditPrefab(string path, Action<GameObject> edit)
            {
                var root = PrefabUtility.LoadPrefabContents(path);
                try
                {
                    root.name = Path.GetFileNameWithoutExtension(path);
                    foreach (var component in root.GetComponentsInChildren<Component>(true).Where(c => c != null && !(c is Transform)))
                        Remap(component);
                    edit(root);
                    SavePrefab(root, path);
                }
                finally
                {
                    PrefabUtility.UnloadPrefabContents(root);
                }
            }
            SerializedObject Asset(string path)
            {
                var asset = Load<Object>(path);
                asset.name = Path.GetFileNameWithoutExtension(path);
                Remap(asset);
                EditorUtility.SetDirty(asset);
                return new SerializedObject(asset);
            }
            var effect = Load<GameObject>(Stock + "GameObject/cannonHit_50mm_dusty_PLACEHOLDER.prefab");
            var splash = Load<GameObject>(Stock + "GameObject/ShellSplash_10kg_PLACEHOLDER.prefab");

            EditPrefab(round, root =>
            {
                DressTipTank(root.transform, mesh, layout);
                var missile = new SerializedObject(root.GetComponent(GameType("Missile")));
                Num(missile, "mass", mass);
                Num(missile, "torque", 0f); // no steering: it falls where it is dropped
                Num(missile, "maxTurnRate", 0f);
                Num(missile, "blastYield", 1f); // a bursting tank, not a bomb
                Num(missile, "pierceDamage", 20f);
                Prop(missile, "impactFuse").boolValue = true;
                foreach (var (field, value) in new (string, GameObject)[] { ("airEffect", effect), ("armorEffect", effect), ("terrainEffect", effect), ("waterSurfaceEffect", splash), ("underwaterEffect", splash), ("fizzleEffect", null) })
                    Prop(missile, "warhead." + field).objectReferenceValue = value;
                missile.ApplyModifiedPropertiesWithoutUndo();
                var seeker = new SerializedObject(root.GetComponent(GameType("OpticalSeekerBomb")));
                Num(seeker, "searchRadius", 0f);
                Num(seeker, "tangibleDelay", 1f);
                Num(seeker, "armDelay", 1.5f);
                Num(seeker, "altitudeFuseHeight", 0f);
                seeker.ApplyModifiedPropertiesWithoutUndo();
                root.GetComponent<Rigidbody>().mass = mass;
            });

            var def = Asset(definition);
            Prop(def, "jsonKey").stringValue = TipTankRound;
            Prop(def, "unitName").stringValue = "Tip Tank";
            Prop(def, "code").stringValue = "TANK";
            Prop(def, "description").stringValue = TipTankDescription;
            Num(def, "length", Convert.ToSingle(layout["length"]));
            Num(def, "width", 2f * Convert.ToSingle(layout["radius"]));
            Num(def, "height", 2f * Convert.ToSingle(layout["radius"]));
            Num(def, "mass", mass);
            Num(def, "value", 0.01f);
            def.ApplyModifiedPropertiesWithoutUndo();

            var weapon = Asset(info);
            Prop(weapon, "weaponName").stringValue = "Tip Tank";
            Prop(weapon, "shortName").stringValue = "TANK";
            Prop(weapon, "description").stringValue = TipTankDescription;
            foreach (var role in new[] { "antiSurface", "antiAir", "antiMissile", "antiRadar" })
                Num(weapon, "effectiveness." + role, 0f);
            Num(weapon, "pierceDamage", 20f);
            Num(weapon, "blastDamage", 0f);
            Num(weapon, "costPerRound", 0.01f);
            Num(weapon, "massPerRound", mass);
            Num(weapon, "fireInterval", 0.15f);
            weapon.ApplyModifiedPropertiesWithoutUndo();

            EditPrefab(mountPrefab, root =>
            {
                // The PAB-250's rack stays, hidden and without colliders, as the tank's parent: the tank bears on the tip face.
                var rack = root.transform.Find("pylon") ?? throw new InvalidDataException("bomb_250_single has no pylon (its rack)");
                var store = rack.Find("bomb") ?? throw new InvalidDataException("bomb_250_single has no bomb");
                rack.localPosition = Vector3.zero;
                rack.localRotation = Quaternion.identity;
                rack.localScale = Vector3.one;
                rack.GetComponent<MeshRenderer>().enabled = false;
                foreach (var box in rack.GetComponents<Collider>())
                    Object.DestroyImmediate(box, true);
                var fairing = root.GetComponent<MeshRenderer>();
                if (fairing != null)
                    fairing.enabled = false;
                store.name = "tip_tank";
                DressTipTank(store, mesh, layout);
                var launcher = new SerializedObject(store.GetComponent(GameType("MountedMissile")));
                Prop(launcher, "railDirection").intValue = 1; // RailDirection.Down
                Num(launcher, "railLength", TipTankEjectLength);
                Num(launcher, "railSpeed", TipTankEjectSpeed);
                Num(launcher, "railDelay", 0f);
                launcher.ApplyModifiedPropertiesWithoutUndo();
            });

            var mount = Asset(mountAsset);
            Prop(mount, "jsonKey").stringValue = TipTank;
            Prop(mount, "mountName").stringValue = "Tip Tanks";
            Num(mount, "ammo", 1);
            Num(mount, "mass", mass);
            Num(mount, "emptyMass", 0f);
            Num(mount, "drag", TipTankDrag);
            Num(mount, "emptyDrag", 0f);
            Num(mount, "RCS", TipTankRcs);
            Num(mount, "emptyRCS", 0f);
            Prop(mount, "GearSafety").boolValue = true; // no release with the gear down or on the ground
            Prop(mount, "GroundSafety").boolValue = true;
            if (Prop(mount, "missileBay").intValue != 0)
                throw new InvalidDataException("bomb_250_single is a bay mount; the tip tank hangs outside");
            mount.ApplyModifiedPropertiesWithoutUndo();
            AssetDatabase.SaveAssets();
            Debug.Log($"[Icarus] stage: tip tank mount {TipTank}: {mass:0} kg full ({layout["fuel_kg"]} kg fuel), drag {TipTankDrag}, RCS {TipTankRcs}, " +
                $"{mesh.triangles.Length / 3} triangles, {layout["volume_l"]} L inside");
            return Load<Object>(mountAsset);
        }
    }
}
