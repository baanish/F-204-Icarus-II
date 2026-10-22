using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        private static string CheckStations(Build b, Object parameters, List<string> p)
        {
            var manager = new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager")));
            var sets = Prop(manager, "hardpointSets");
            var names = Enumerable.Range(0, sets.arraySize).Select(i => sets.GetArrayElementAtIndex(i).FindPropertyRelative("name").stringValue).ToArray();
            if (!names.SequenceEqual(SetNames)) p.Add("sets [" + string.Join(", ", names) + "]");
            var indices = new List<int>();
            var worst = 0f;
            for (var i = 0; i < sets.arraySize; i++)
            {
                var set = sets.GetArrayElementAtIndex(i);
                if (set.FindPropertyRelative("precludingHardpointSets").arraySize > 0) p.Add(names[i] + " precludes another set");
                var hardpoints = set.FindPropertyRelative("hardpoints");
                if (hardpoints.arraySize != 2) { p.Add($"{names[i]} has {hardpoints.arraySize} hardpoints"); continue; }
                for (var j = 0; j < 2; j++)
                {
                    var hp = hardpoints.GetArrayElementAtIndex(j);
                    var t = hp.FindPropertyRelative("transform").objectReferenceValue as Transform;
                    var part = hp.FindPropertyRelative("part").objectReferenceValue;
                    if (t == null || part == null || !Inside(b, part)) { p.Add($"{names[i]} hardpoint {j} has no transform or part"); continue; }
                    if (j == 0 ? t.position.x >= 0 : t.position.x <= 0) p.Add($"{names[i]} hardpoint {j} is on the wrong side ({t.position.x:F2})");
                    indices.Add(hp.FindPropertyRelative("HardpointIndex").intValue);
                    if (!MeasuredHardpoints.TryGetValue(t.name, out var measured)) { p.Add(t.name + " has no measured position"); continue; }
                    var miss = Vector3.Distance(t.position, measured.Position);
                    worst = Mathf.Max(worst, miss);
                    if (miss > MeasuredTolerance) p.Add($"{t.name} at {t.position.ToString("F4")} is {miss * 1000f:F1} mm from its measured {measured.Position.ToString("F3")}");
                    if (Mathf.Abs(Mathf.DeltaAngle(t.eulerAngles.z, measured.Roll)) > 0.1f) p.Add($"{t.name} rolls {t.eulerAngles.z:F1} deg, measured {measured.Roll}");
                }
            }
            if (!indices.OrderBy(i => i).SequenceEqual(Enumerable.Range(0, 2 * SetNames.Length))) p.Add("HardpointIndex values [" + string.Join(", ", indices) + $"], expected 0..{2 * SetNames.Length - 1} once each");
            var so = new SerializedObject(parameters);
            var lengths = new List<int>();
            var loadouts = Prop(so, "loadouts");
            for (var i = 0; i < loadouts.arraySize; i++)
                lengths.Add(loadouts.GetArrayElementAtIndex(i).FindPropertyRelative("weapons").arraySize);
            var standard = Prop(so, "StandardLoadouts");
            for (var i = 0; i < standard.arraySize; i++)
            {
                var weapons = standard.GetArrayElementAtIndex(i).FindPropertyRelative("loadout").FindPropertyRelative("weapons");
                lengths.Add(weapons.arraySize);
                if (GetList(weapons).Any(w => w != null && KeyOf(w).StartsWith("gun", StringComparison.Ordinal))) p.Add("a standard loadout carries a gun");
            }
            if (loadouts.arraySize < 2) p.Add("fewer than two ordinary loadouts (WeaponManager falls back to loadouts[1])");
            if (lengths.Any(l => l != SetNames.Length)) p.Add("loadout lengths [" + string.Join(", ", lengths) + "]");
            return $"sets [{string.Join(", ", names)}], hardpoints 0..{2 * SetNames.Length - 1} left before right, within {worst * 1000f:F1} mm of their measured positions, loadout lengths [{string.Join(", ", lengths)}]";
        }

        // A14: every offered mount, twins and the mod's own included, hung at each of its hardpoints, its colliders against
        // every airframe collider not on the hardpoint's own part (Physics.ComputePenetration). A mounted store's collider
        // joins its part's body, so one that sinks into a neighbouring part's collider fights it. Fails above StoreOverlap.
        private const float StoreOverlap = 0.005f;

        private static string CheckStoreColliders(Build b, List<string> p)
        {
            var unitPart = GameType("UnitPart");
            Physics.SyncTransforms();
            var airframe = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger && c.gameObject.layer != IgnoreCollisionsLayer && !(c is MeshCollider m && m.sharedMesh == null)).ToArray();
            var sets = Prop(new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager"))), "hardpointSets");
            var worst = (Depth: 0f, Where: "none");
            var hung = 0;
            for (var i = 0; i < sets.arraySize; i++)
            {
                var hardpoints = sets.GetArrayElementAtIndex(i).FindPropertyRelative("hardpoints");
                for (var j = 0; j < hardpoints.arraySize; j++)
                {
                    var hp = hardpoints.GetArrayElementAtIndex(j);
                    var point = (Transform)hp.FindPropertyRelative("transform").objectReferenceValue;
                    var part = hp.FindPropertyRelative("part").objectReferenceValue;
                    var others = airframe.Where(c => c.GetComponentInParent(unitPart) != part).ToArray();
                    foreach (var key in StationKeys[i])
                    {
                        var mount = AssetDatabase.LoadAssetAtPath<Object>(MountFolder + "/" + key + ".asset") ?? Load<Object>(MountPlaceholders + key + "_PLACEHOLDER.asset");
                        var store = (GameObject)Object.Instantiate((GameObject)GetRef(mount, "prefab"), point.position, point.rotation);
                        try
                        {
                            Physics.SyncTransforms();
                            hung++;
                            foreach (var s in store.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger))
                                foreach (var c in others.Where(c => c.bounds.Intersects(s.bounds)))
                                {
                                    if (!Physics.ComputePenetration(s, s.transform.position, s.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth))
                                        continue;
                                    var where = $"{key} {s.GetType().Name} on {point.name} into {PathOf(c.transform, b.Root.transform)}" +
                                                (c is MeshCollider mc ? " " + mc.sharedMesh.name : "");
                                    if (depth > worst.Depth)
                                        worst = (depth, where);
                                    if (depth > StoreOverlap)
                                        p.Add($"{where} by {depth:F3} m");
                                }
                        }
                        finally
                        {
                            Object.DestroyImmediate(store);
                        }
                    }
                }
            }
            return $"{hung} mounts hung on their hardpoints, deepest {worst.Depth:F3} m ({worst.Where}), limit {StoreOverlap} m";
        }
    }
}
