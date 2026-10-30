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
        // The arrestor hook (art/blender/tail_hook.py): a mount for the Tail Hook set, built from copies of the stock
        // Compass's (TailHook_Trainer: its prefab and mount) under the Icarus's own key, as stock carrier jets carry
        // theirs. The game's TailHook on it does the rest: it deploys itself below 100 m/s between 30 and 120 m radar
        // altitude, and catches a wire its hinge-to-point linecast crosses. The landing AI reads the equipped mount's
        // tailHook flag (WeaponManager.HasTailHook), so every standard loadout carries it (StandardLoadouts).
        private const string TailHook = "baanish_icarus_tail_hook";
        // The set's place in SetNames: appended after the wing and conformal sets, so loadouts saved before it keep their
        // indices. One hardpoint, on the tail cone, HardpointIndex -1 as on the Compass and the Ifrit.
        private const int TailHookSet = 3;
        // The cost of the hook and the fairing that comes with it (art/blender/tail_hook.py HOOKED_FIN), the owner's call
        // since the stock hooks are much smaller: 100 kg and 5% of the clean airframe's dragArea (IcarusAuthor.Aero.cs
        // DragAreaTotal) together, all on the mount; the airframe without the hook carries neither. The Compass's own
        // 0.1 is a quarter of its airframe's. Hardpoint.SpawnMount puts only a mount's emptyMass on its part (WeaponMount
        // takes its label mass from the TailHook), and the stock hooks' is 0, so both carry the 100 kg; the drag adds to
        // the tail cone's dragArea (AeroPart.ModifyDrag). parts.py's radar weight holds the empty margin with it fitted.
        private const float TailHookMass = 100f, TailHookDrag = 0.05f * DragAreaTotal;
        // The stock Compass hook's castPoint, under its point (TailHook_Trainer).
        private const string TailHookCastPoint = "castPoint";
        private const float CastPointFromEnd = 1.731f;

        private static Dictionary<string, object> TailHookLayout() =>
            (Dictionary<string, object>)((Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(ExportFolder, "blockout.json"))))["tail_hook"];

        // The hook's mesh in its transform's frame (export_blockout.py).
        private static Mesh ImportTailHookMesh(Dictionary<string, object> layout)
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
            var mesh = AssetDatabase.LoadAllAssetsAtPath(target).OfType<Mesh>().SingleOrDefault(m => m.name == "tail_hook")
                ?? throw new InvalidDataException($"{target} has no tail_hook mesh");
            var box = (List<object>)layout["bounds_unity"];
            if ((mesh.bounds.min - Vec3(box[0])).magnitude > 0.02f || (mesh.bounds.max - Vec3(box[1])).magnitude > 0.02f)
                throw new InvalidDataException($"tail_hook: imported bounds {mesh.bounds.min}..{mesh.bounds.max} differ from the export's");
            return mesh;
        }

        // The airframe skin, its UVs on the fairing's paint (art/blender/tail_hook.py paint), as the tip tank wears the
        // wing's: the plugin hands the hook the livery the jet wears (src/Icarus/TailHookFairing.cs).
        private static Material TailHookMaterial() => Load<Material>(SkinPath);

        private static Object AuthorTailHookMount()
        {
            BlueprinterAssets.EnsureFolder(MountFolder);
            var layout = TailHookLayout();
            if ((string)layout["key"] != TailHook)
                throw new InvalidDataException($"blockout.json's tail hook is {layout["key"]}, not {TailHook}");
            var mesh = ImportTailHookMesh(layout);
            var prefabPath = MountFolder + "/" + TailHook + ".prefab";
            var assetPath = MountFolder + "/" + TailHook + ".asset";
            var copies = new[] { ("GameObject/TailHook_Trainer_PLACEHOLDER.prefab", prefabPath), ("MonoBehaviour/TailHook_Trainer_PLACEHOLDER.asset", assetPath) };
            foreach (var (source, target) in copies)
            {
                File.Copy(Stock + source, target, true); // keeps the target's .meta, so its GUID survives
                AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
            }
            var root = PrefabUtility.LoadPrefabContents(prefabPath);
            try
            {
                root.name = TailHook;
                var hook = new SerializedObject(root.GetComponent(GameType("TailHook")) ?? throw new InvalidDataException("TailHook_Trainer has no TailHook"));
                var hinge = (Transform)Prop(hook, "hinge").objectReferenceValue;
                var arm = (Transform)Prop(hook, "hook").objectReferenceValue;
                var end = (Transform)Prop(hook, "hookEnd").objectReferenceValue;
                if (hinge == null || arm == null || end == null || arm.parent != hinge || end.parent != arm)
                    throw new InvalidDataException("TailHook_Trainer's hinge, hook and hookEnd aren't the chain the game turns");
                // The hinge sits on the hardpoint, which BuildStations puts on the export's hinge, turned half a turn about
                // X as the Compass's is: the hook's local -Z then points aft, its point stowedAngle - 180 degrees up.
                hinge.localPosition = Vector3.zero;
                hinge.localRotation = Quaternion.Euler(180f, 0f, 0f);
                var stowed = Convert.ToSingle(layout["stowed_deg"]);
                arm.localPosition = Vector3.zero;
                arm.localRotation = Quaternion.Euler(stowed, 0f, 0f);
                arm.GetComponent<MeshFilter>().sharedMesh = mesh;
                arm.GetComponent<MeshRenderer>().sharedMaterials = new[] { TailHookMaterial() };
                end.localPosition = new Vector3(0f, 0f, -Convert.ToSingle(layout["length"]));
                // TailHook.ApplyForce reads the cable's pull against castPoint's axes: the Compass's, on the point, turned half
                // a turn about X and CastPointFromEnd back up the arm (the Icarus arm is the Compass's length).
                var cast = end.Find(TailHookCastPoint) ?? new GameObject(TailHookCastPoint).transform;
                cast.SetParent(end, false);
                cast.localPosition = new Vector3(0f, 0f, CastPointFromEnd);
                cast.localRotation = Quaternion.Euler(180f, 0f, 0f);
                // Every reference the game and A23 read, set here rather than left as the copied stock prefab imported them.
                Prop(hook, "hinge").objectReferenceValue = hinge;
                Prop(hook, "hook").objectReferenceValue = arm;
                Prop(hook, "hookEnd").objectReferenceValue = end;
                Prop(hook, "castPoint").objectReferenceValue = cast;
                Prop(hook, "unitPart").objectReferenceValue = null;
                Num(hook, "mass", TailHookMass);
                Num(hook, "stowedAngle", stowed);
                Num(hook, "deployedAngle", Convert.ToSingle(layout["deployed_deg"]));
                hook.ApplyModifiedPropertiesWithoutUndo();
                SavePrefab(root, prefabPath);
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
            var mount = Load<Object>(assetPath);
            mount.name = TailHook;
            var so = new SerializedObject(mount);
            Prop(so, "jsonKey").stringValue = TailHook;
            Prop(so, "prefab").objectReferenceValue = Load<GameObject>(prefabPath);
            Num(so, "mass", TailHookMass);
            Num(so, "emptyMass", TailHookMass);
            Num(so, "drag", TailHookDrag);
            Num(so, "emptyDrag", TailHookDrag);
            if (!Prop(so, "tailHook").boolValue)
                throw new InvalidDataException("TailHook_Trainer is no longer a tailHook mount");
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(mount);
            AssetDatabase.SaveAssets();
            Debug.Log($"[Icarus] stage: tail hook mount {TailHook}: {layout["length"]} m, local X {layout["stowed_deg"]} stowed / {layout["deployed_deg"]} deployed, " +
                      $"{mesh.triangles.Length / 3} triangles");
            return mount;
        }

        // The Tail Hook set: its one hardpoint on the tail cone at the export's hinge, square to the aircraft. The fins take
        // turns on it the stock way (Hardpoint.ShowPylon): the original ventral fin is its plug, drawn while it is empty,
        // and variant D's fin and fairing the pylon for the hook, drawn while that is fitted, as the Compass draws its
        // hook's. The prefab starts as an empty hardpoint shows.
        private static string BuildTailHookStation(Build b, SerializedProperty set)
        {
            var layout = TailHookLayout();
            var part = b.Parts[(string)layout["part"]].transform;
            var point = new GameObject("hardpoint_tailhook") { layer = part.gameObject.layer }.transform;
            point.SetParent(part, false);
            point.SetPositionAndRotation(Vec3(layout["hinge_unity"]) - b.Blockout.Origin, b.Root.transform.rotation);
            set.FindPropertyRelative("name").stringValue = SetNames[TailHookSet];
            set.FindPropertyRelative("precludingHardpointSets").arraySize = 0;
            set.FindPropertyRelative("SymmetryWithPrev").boolValue = false;
            set.FindPropertyRelative("SymmetryName").stringValue = string.Empty;
            var options = set.FindPropertyRelative("weaponOptions");
            options.arraySize = 1; // "none"; the hook arrives through its OpAddWeaponToHardpoint, as every mount does
            options.GetArrayElementAtIndex(0).objectReferenceValue = null;
            set.FindPropertyRelative("weaponMount").objectReferenceValue = null;
            var hardpoints = set.FindPropertyRelative("hardpoints");
            hardpoints.arraySize = 1;
            var hp = hardpoints.GetArrayElementAtIndex(0);
            hp.FindPropertyRelative("transform").objectReferenceValue = point;
            hp.FindPropertyRelative("part").objectReferenceValue = b.Part((string)layout["part"]);
            hp.FindPropertyRelative("bayDoors").arraySize = 0;
            hp.FindPropertyRelative("doorOpenDuration").floatValue = 0f;
            var fin = b.Visuals[(string)layout["fin"]].GetComponent<MeshRenderer>();
            var hooked = b.Visuals[(string)layout["hooked_fin"]].GetComponent<MeshRenderer>();
            var pylons = hp.FindPropertyRelative("pylonOptions");
            pylons.arraySize = 1;
            var pylon = pylons.GetArrayElementAtIndex(0);
            pylon.FindPropertyRelative("cargo").boolValue = false;
            pylon.FindPropertyRelative("mount").objectReferenceValue = Load<Object>(MountFolder + "/" + TailHook + ".asset");
            pylon.FindPropertyRelative("renderer").objectReferenceValue = hooked;
            hp.FindPropertyRelative("Pylon").objectReferenceValue = hooked;
            hp.FindPropertyRelative("Plug").objectReferenceValue = fin;
            fin.enabled = true;
            hooked.enabled = false;
            hp.FindPropertyRelative("BuiltInWeapons").arraySize = 0;
            hp.FindPropertyRelative("BuiltInTurrets").arraySize = 0;
            hp.FindPropertyRelative("HardpointIndex").intValue = -1;
            return $"{point.name} #-1 on {layout["part"]} at {point.position.ToString("F3")}, plug {fin.name}, pylon {hooked.name}";
        }

        // A23: the hook mount is the Icarus's own (key, prefab, mesh and material, no stock mesh left), its chain turns
        // as the game turns it and reaches the Compass's length, the set holds one hardpoint where the export put the
        // hinge on the tail cone, every standard loadout carries the hook. Both fits: without the hook the original
        // ventral fin shows and its hulls are the tail cone's; with it the hooked fin shows. Both fins come off with
        // the tail cone. The hook and fairing have no colliders. The game's catch linecast from
        // hinge to point meets no collider of the hooked jet stowed, deployed or between. The Hyperion's hangars are
        // checked with the registrations (AuthorOps), which are written after the prefab.
        private const int TailHookSweepSteps = 40;
        private const float TailHookTolerance = 0.001f;

        private static string CheckTailHook(Build b, Object parameters, List<string> p)
        {
            var layout = TailHookLayout();
            var mount = AssetDatabase.LoadAssetAtPath<Object>(MountFolder + "/" + TailHook + ".asset");
            if (mount == null) { p.Add("no " + TailHook + " mount asset"); return "no mount"; }
            var so = new SerializedObject(mount);
            if (Prop(so, "jsonKey").stringValue != TailHook) p.Add("mount key " + Prop(so, "jsonKey").stringValue);
            if (!Prop(so, "tailHook").boolValue) p.Add("mount isn't flagged tailHook, so the landing AI sees no hook");
            if (Prop(so, "emptyMass").floatValue != TailHookMass || Prop(so, "emptyDrag").floatValue != TailHookDrag)
                p.Add($"mount carries {Prop(so, "emptyMass").floatValue} kg and {Prop(so, "emptyDrag").floatValue} drag, not {TailHookMass} and {TailHookDrag}");
            var keys = AssetDatabase.FindAssets("t:ScriptableObject", new[] { ModFolder }).Select(AssetDatabase.GUIDToAssetPath)
                .Select(AssetDatabase.LoadMainAssetAtPath).Where(a => a != null && new SerializedObject(a).FindProperty("tailHook") != null)
                .Select(KeyOf).ToArray();
            if (keys.Count(k => k == TailHook) != 1 || keys.Any(k => k == "TailHook_Trainer" || k == "TailHook_Multirole1"))
                p.Add("mount keys in the mod [" + string.Join(", ", keys) + "]");
            var prefab = (GameObject)Prop(so, "prefab").objectReferenceValue;
            if (prefab == null || AssetDatabase.GetAssetPath(prefab) != MountFolder + "/" + TailHook + ".prefab") { p.Add("mount prefab " + AssetDatabase.GetAssetPath(prefab)); return "wrong prefab"; }
            foreach (var c in prefab.GetComponentsInChildren<Component>(true).Where(c => c != null))
            {
                var it = new SerializedObject(c).GetIterator();
                while (it.Next(true))
                    if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue != null
                        && AssetDatabase.GetAssetPath(it.objectReferenceValue).StartsWith(Stock + "Mesh/", StringComparison.Ordinal))
                        p.Add($"{c.name}.{it.propertyPath} still holds the stock {it.objectReferenceValue.name}");
            }
            var component = prefab.GetComponent(GameType("TailHook"));
            var hook = new SerializedObject(component);
            var hinge = (Transform)Prop(hook, "hinge").objectReferenceValue;
            var arm = (Transform)Prop(hook, "hook").objectReferenceValue;
            var end = (Transform)Prop(hook, "hookEnd").objectReferenceValue;
            var cast = (Transform)Prop(hook, "castPoint").objectReferenceValue;
            var outside = new[] { ("hinge", hinge), ("hook", arm), ("hookEnd", end), ("castPoint", cast) }
                .Where(r => r.Item2 == null || !r.Item2.IsChildOf(prefab.transform))
                .Select(r => r.Item2 == null ? r.Item1 + " none" : $"{r.Item1} {r.Item2.name} in {AssetDatabase.GetAssetPath(r.Item2)}").ToArray();
            if (outside.Length > 0) { p.Add("hook transforms not all in the mount: " + string.Join(", ", outside)); return "broken chain"; }
            if (cast.parent != end || Vector3.Distance(cast.localPosition, new Vector3(0f, 0f, CastPointFromEnd)) > TailHookTolerance
                || Quaternion.Angle(cast.localRotation, Quaternion.Euler(180f, 0f, 0f)) > 0.01f)
                p.Add("castPoint isn't the Compass's, on the point");
            if (arm.GetComponent<MeshFilter>().sharedMesh?.name != "tail_hook" || arm.GetComponent<MeshRenderer>().sharedMaterials.Single() != TailHookMaterial())
                p.Add("the arm doesn't draw the Icarus hook in the airframe skin");
            if (Prop(hook, "mass").floatValue != TailHookMass) p.Add($"TailHook mass {Prop(hook, "mass").floatValue}, not {TailHookMass}");
            var stowed = Prop(hook, "stowedAngle").floatValue;
            var deployed = Prop(hook, "deployedAngle").floatValue;
            if (Mathf.Abs(stowed - Convert.ToSingle(layout["stowed_deg"])) > 0.01f || Mathf.Abs(deployed - Convert.ToSingle(layout["deployed_deg"])) > 0.01f)
                p.Add($"angles {stowed:F2} / {deployed:F2}, export {layout["stowed_deg"]} / {layout["deployed_deg"]}");
            if (!(deployed < stowed && stowed > 180f && deployed < 180f)) p.Add($"angles {stowed:F2} / {deployed:F2} don't swing the point from above the hinge to below it");
            if (Quaternion.Angle(hinge.localRotation, Quaternion.Euler(180f, 0f, 0f)) > 0.01f || hinge.localPosition.magnitude > 1e-5f)
                p.Add("the hinge isn't half a turn about X on the hardpoint");
            if (prefab.GetComponentsInChildren<Collider>(true).Any(c => c.enabled))
                p.Add("the mount has an enabled collider");

            var sets = Prop(new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager"))), "hardpointSets");
            if (sets.arraySize != SetNames.Length || sets.GetArrayElementAtIndex(TailHookSet).FindPropertyRelative("name").stringValue != "Tail Hook")
            { p.Add("no Tail Hook set last"); return "no set"; }
            var hardpoints = sets.GetArrayElementAtIndex(TailHookSet).FindPropertyRelative("hardpoints");
            if (hardpoints.arraySize != 1) { p.Add($"Tail Hook has {hardpoints.arraySize} hardpoints"); return "wrong hardpoints"; }
            var hp = hardpoints.GetArrayElementAtIndex(0);
            var point = (Transform)hp.FindPropertyRelative("transform").objectReferenceValue;
            var partName = (string)layout["part"];
            if (hp.FindPropertyRelative("part").objectReferenceValue != b.Part(partName) || point == null || point.parent != b.Parts[partName].transform)
            { p.Add("the hook's hardpoint isn't on " + partName); return "wrong part"; }
            if (hp.FindPropertyRelative("HardpointIndex").intValue != -1) p.Add("Tail Hook HardpointIndex " + hp.FindPropertyRelative("HardpointIndex").intValue);
            var place = Vec3(layout["hinge_unity"]) - b.Blockout.Origin;
            if (Vector3.Distance(point.position, place) > TailHookTolerance) p.Add($"hinge {point.position.ToString("F4")}, export {place.ToString("F4")}");
            var fin = b.Visuals.TryGetValue((string)layout["fin"], out var finAt) ? finAt.GetComponent<MeshRenderer>() : null;
            var hooked = b.Visuals.TryGetValue((string)layout["hooked_fin"], out var hookedAt) ? hookedAt.GetComponent<MeshRenderer>() : null;
            var pylons = hp.FindPropertyRelative("pylonOptions");
            if (fin == null || hooked == null) { p.Add("no ventral fin or hooked fin renderer"); return "no fins"; }
            if (hp.FindPropertyRelative("Plug").objectReferenceValue != fin) p.Add("the Tail Hook plug isn't the ventral fin");
            if (pylons.arraySize != 1 || pylons.GetArrayElementAtIndex(0).FindPropertyRelative("renderer").objectReferenceValue != hooked
                || pylons.GetArrayElementAtIndex(0).FindPropertyRelative("mount").objectReferenceValue != mount
                || pylons.GetArrayElementAtIndex(0).FindPropertyRelative("cargo").boolValue)
                p.Add("the Tail Hook pylon isn't the hooked fin, for the hook mount alone");
            if (!fin.enabled || hooked.enabled) p.Add("the prefab doesn't start as an empty hardpoint shows: the ventral fin drawn, the hooked fin not");
            foreach (var renderer in new[] { fin, hooked })
                if (renderer.GetComponentInParent(GameType("UnitPart")) != b.Part(partName)) p.Add($"{renderer.name} doesn't ride {partName}, so it wouldn't come off with it");

            var std = Prop(new SerializedObject(parameters), "StandardLoadouts");
            var bare = new List<string>();
            for (var i = 0; i < std.arraySize; i++)
            {
                var weapons = GetList(std.GetArrayElementAtIndex(i).FindPropertyRelative("loadout").FindPropertyRelative("weapons"));
                if (weapons.Length != SetNames.Length || weapons[TailHookSet] != mount)
                    bare.Add(std.GetArrayElementAtIndex(i).FindPropertyRelative("Name").stringValue);
            }
            var fallback = GetList(Prop(new SerializedObject(parameters), "loadouts").GetArrayElementAtIndex(1).FindPropertyRelative("weapons"));
            if (fallback.Length != SetNames.Length || fallback[TailHookSet] != mount) bare.Add("loadouts[1]");
            if (bare.Count > 0) p.Add("no hook on " + string.Join(", ", bare));

            // Hung on its hardpoint in the built jet, as Hardpoint.SpawnMount hangs it: its part, length and catch line.
            var hung = (GameObject)Object.Instantiate(prefab, point, false);
            float length = 0, least = float.MaxValue;
            var tipStowed = Vector3.zero;
            var tipDeployed = Vector3.zero;
            var crossings = new List<string>();
            try
            {
                var live = hung.GetComponent(GameType("TailHook"));
                var liveSo = new SerializedObject(live);
                var liveHinge = (Transform)Prop(liveSo, "hinge").objectReferenceValue;
                var liveArm = (Transform)Prop(liveSo, "hook").objectReferenceValue;
                var liveEnd = (Transform)Prop(liveSo, "hookEnd").objectReferenceValue;
                if (hung.GetComponentInParent(GameType("UnitPart")) != b.Part(partName)) p.Add("the hung hook finds a part other than " + partName);
                length = Vector3.Distance(liveArm.position, liveEnd.position);
                if (Mathf.Abs(length - Convert.ToSingle(layout["length"])) > TailHookTolerance) p.Add($"hook length {length:F4} m, export {layout["length"]}");
                var airframe = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger
                    && !(c is MeshCollider m && m.sharedMesh == null) && !c.transform.IsChildOf(hung.transform)).ToHashSet();
                for (var k = 0; k <= TailHookSweepSteps; k++)
                {
                    liveArm.localEulerAngles = new Vector3(Mathf.Lerp(stowed, deployed, k / (float)TailHookSweepSteps), 0f, 0f);
                    Physics.SyncTransforms();
                    if (k == 0) tipStowed = liveEnd.position - liveHinge.position;
                    if (k == TailHookSweepSteps) tipDeployed = liveEnd.position - liveHinge.position;
                    var from = liveHinge.position;
                    var to = liveEnd.position;
                    foreach (var hit in Physics.RaycastAll(from, to - from, (to - from).magnitude).Where(h => airframe.Contains(h.collider)))
                        crossings.Add($"{k}: {PathOf(hit.collider.transform, b.Root.transform)}");
                    foreach (var c in airframe.Where(c => c.bounds.SqrDistance(from) < 1f || c.bounds.SqrDistance(to) < 1f))
                        for (var i = 0; i <= 20; i++)
                        {
                            var q = Vector3.Lerp(from, to, i / 20f);
                            least = Mathf.Min(least, Vector3.Distance(q, c.ClosestPoint(q)));
                        }
                }
            }
            finally
            {
                Object.DestroyImmediate(hung);
            }
            if (crossings.Count > 0) p.Add("the catch linecast meets the jet's own colliders at " + string.Join("; ", crossings.Take(5)));
            if (!(tipStowed.z < 0f && tipStowed.y > 0f && tipDeployed.z < 0f && tipDeployed.y < 0f)) p.Add($"point stowed {tipStowed.ToString("F3")}, deployed {tipDeployed.ToString("F3")} from the hinge, expected aft and up, then aft and down");

            return $"{TailHook} on {partName} at {point.position.ToString("F3")}, {length:F3} m, local X {stowed:F2} / {deployed:F2}, " +
                   $"point {tipStowed.ToString("F2")} stowed and {tipDeployed.ToString("F2")} deployed from the hinge; on all {std.arraySize} standard loadouts; " +
                   $"catch line {least:F3} m from the jet's colliders over {TailHookSweepSteps + 1} poses; " +
                   $"plug {fin.name}, pylon {hooked.name}";
        }
    }
}
