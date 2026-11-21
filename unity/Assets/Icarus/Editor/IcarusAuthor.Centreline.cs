using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The Centreline set's place in SetNames, appended after the Tail Hook set so loadouts saved before it keep their
        // indices, and the Conformal set's, which it shares the belly with.
        private const int ConformalSet = 2, CentrelineSet = 4;
        // The station, in metres forward of the root origin: between the main wheels' doors and the nose wheel
        // (tools/store_clearance.py; at 0.4 the 500 kg bomb is 0.10 m from a main door, at 1.2 a 3 m store meets the nose wheel).
        private const float CentrelineStation = 0.8f;

        // The Centreline set: one hardpoint on the belly's centreline, square to the aircraft, HardpointIndex -1 as the
        // Tail Hook's. A store hangs there on its own mount's pylon, so the airframe draws nothing for it. It lies between
        // the conformal troughs, so the two sets preclude each other, as the stock Brawler's centre pylon and inner fuselage
        // pylons do: the loadout menu empties and greys the one while the other is loaded (HardpointSet.BlockedByOtherHardpoint).
        private static string BuildCentrelineStation(Build b, SerializedProperty set, SerializedProperty conformal, Vector3 where)
        {
            var part = b.Parts[RootPart].transform;
            var point = new GameObject("hardpoint_centreline") { layer = part.gameObject.layer }.transform;
            point.SetParent(part, false);
            point.SetPositionAndRotation(where, b.Root.transform.rotation);
            set.FindPropertyRelative("name").stringValue = SetNames[CentrelineSet];
            foreach (var (blocked, by) in new[] { (set, ConformalSet), (conformal, CentrelineSet) })
            {
                var precludes = blocked.FindPropertyRelative("precludingHardpointSets");
                precludes.arraySize = 1;
                precludes.GetArrayElementAtIndex(0).intValue = by;
            }
            set.FindPropertyRelative("SymmetryWithPrev").boolValue = false;
            set.FindPropertyRelative("SymmetryName").stringValue = string.Empty;
            var options = set.FindPropertyRelative("weaponOptions");
            options.arraySize = 1; // "none"; the bombs arrive through OpAddWeaponToHardpoint, as every mount does
            options.GetArrayElementAtIndex(0).objectReferenceValue = null;
            set.FindPropertyRelative("weaponMount").objectReferenceValue = null;
            var hardpoints = set.FindPropertyRelative("hardpoints");
            hardpoints.arraySize = 1;
            var hp = hardpoints.GetArrayElementAtIndex(0);
            hp.FindPropertyRelative("transform").objectReferenceValue = point;
            hp.FindPropertyRelative("part").objectReferenceValue = b.Part(RootPart);
            hp.FindPropertyRelative("bayDoors").arraySize = 0;
            hp.FindPropertyRelative("doorOpenDuration").floatValue = 0f;
            hp.FindPropertyRelative("pylonOptions").arraySize = 0;
            hp.FindPropertyRelative("Pylon").objectReferenceValue = null;
            hp.FindPropertyRelative("Plug").objectReferenceValue = null;
            hp.FindPropertyRelative("BuiltInWeapons").arraySize = 0;
            hp.FindPropertyRelative("BuiltInTurrets").arraySize = 0;
            hp.FindPropertyRelative("HardpointIndex").intValue = -1;
            return $"{point.name} #-1 on {RootPart} at {point.position.ToString("F4")}";
        }

        private static void CheckCentrelineStation(Build b, SerializedProperty set, List<string> p)
        {
            var hardpoints = set.FindPropertyRelative("hardpoints");
            if (hardpoints.arraySize != 1) { p.Add($"Centreline has {hardpoints.arraySize} hardpoints"); return; }
            var hp = hardpoints.GetArrayElementAtIndex(0);
            var t = hp.FindPropertyRelative("transform").objectReferenceValue as Transform;
            var part = hp.FindPropertyRelative("part").objectReferenceValue;
            if (t == null || part == null || !Inside(b, part)) { p.Add("the Centreline hardpoint has no transform or part"); return; }
            if (hp.FindPropertyRelative("HardpointIndex").intValue != -1) p.Add("the Centreline hardpoint's HardpointIndex is not -1");
            var measured = MeasuredHardpoints[t.name];
            var miss = Vector3.Distance(t.position, measured.Position);
            if (miss > MeasuredTolerance) p.Add($"{t.name} at {t.position.ToString("F4")} is {miss * 1000f:F1} mm from its measured {measured.Position.ToString("F3")}");
            if (Mathf.Abs(Mathf.DeltaAngle(t.eulerAngles.z, measured.Roll)) > 0.1f) p.Add($"{t.name} rolls {t.eulerAngles.z:F1} deg, measured {measured.Roll}");
        }
    }
}
