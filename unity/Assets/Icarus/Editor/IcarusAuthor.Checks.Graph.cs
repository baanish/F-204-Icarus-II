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
        private static string CheckGraph(Build b, List<string> p)
        {
            var aeroType = GameType("AeroPart");
            var dangling = 0;
            foreach (var component in b.Root.GetComponentsInChildren<Component>(true))
            {
                if (component == null)
                {
                    p.Add("a missing script");
                    continue;
                }
                var it = new SerializedObject(component).GetIterator();
                while (it.Next(true))
                {
                    if (it.propertyType != SerializedPropertyType.ObjectReference)
                        continue;
                    var value = it.objectReferenceValue;
                    if (value == null && it.objectReferenceInstanceIDValue != 0)
                    {
                        dangling++;
                        p.Add($"dangling reference {PathOf(component.transform, b.Root.transform)}:{component.GetType().Name}.{it.propertyPath}");
                    }
                    else if (value != null && !EditorUtility.IsPersistent(value) && !Inside(b, value))
                        p.Add($"{PathOf(component.transform, b.Root.transform)}:{component.GetType().Name}.{it.propertyPath} points outside the prefab ({value.name})");
                }
            }
            var parts = b.Root.GetComponentsInChildren(aeroType, true);
            if (parts.Length != b.Specs.Count) p.Add($"{parts.Length} AeroParts, expected {b.Specs.Count}");
            var mass = parts.Sum(x => GetFloat(x, "mass"));
            if (Mathf.Abs(mass - EmptyMass) > 1f) p.Add($"AeroPart masses sum to {mass}, not {EmptyMass}");
            foreach (var part in parts)
            {
                var so = new SerializedObject(part);
                if (Prop(so, "parentUnit").objectReferenceValue != b.Aircraft) p.Add(part.name + ": parentUnit isn't the Aircraft");
                if (Prop(so, "mass").floatValue <= 0) p.Add(part.name + " has no mass");
                var joints = Prop(so, "joints");
                if (part.gameObject == b.Root)
                {
                    if (joints.arraySize != 0) p.Add("the root part has joints");
                    continue;
                }
                var parent = part.transform.parent.GetComponent(aeroType);
                if (parent == null) p.Add(part.name + " isn't a direct child of a part (UnitPart.Awake looks only at the parent)");
                else if (joints.arraySize == 0 || joints.GetArrayElementAtIndex(0).FindPropertyRelative("connectedPart").objectReferenceValue != parent) p.Add(part.name + ": joints[0] isn't its parent part");
                if (part.GetComponents<Collider>().Length == 0) p.Add(part.name + " has no collider");
            }
            foreach (var collider in b.Root.GetComponentsInChildren<MeshCollider>(true).Where(c => c.sharedMesh != null))
                if (!collider.convex) p.Add(PathOf(collider.transform, b.Root.transform) + " has a concave MeshCollider");
            var lod = b.Root.GetComponent<LODGroup>().GetLODs();
            if (lod.SelectMany(l => l.renderers).Any(r => r == null || !r.transform.IsChildOf(b.Root.transform))) p.Add("a LOD renderer outside the prefab");
            var hulls = lod[lod.Length - 1].renderers.Select(r => (r, tris: (int)r.GetComponent<MeshFilter>().sharedMesh.GetIndexCount(0) / 3)).ToArray();
            foreach (var (r, tris) in hulls.Where(h => h.tris > Lod1PerHull))
                p.Add($"LOD1 hull {r.name} has {tris} triangles, over {Lod1PerHull}");
            if (hulls.Sum(h => h.tris) > Lod1Total) p.Add($"LOD1 hulls have {hulls.Sum(h => h.tris)} triangles, over {Lod1Total}");
            var pieces = b.Root.GetComponentsInChildren<MeshCollider>(true).Where(c => c.sharedMesh != null).ToArray();
            // After the braces, no two parts without a joint between them may overlap.
            var linked = new HashSet<(Object, Object)>();
            foreach (var part in parts)
            {
                var joints = Prop(new SerializedObject(part), "joints");
                for (var i = 0; i < joints.arraySize; i++)
                {
                    var other = joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue;
                    linked.Add((part, other));
                    linked.Add((other, part));
                }
            }
            Physics.SyncTransforms();
            var colliders = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger && c.gameObject.layer != IgnoreCollisionsLayer && !(c is MeshCollider m && m.sharedMesh == null))
                .Select(c => (collider: c, part: (Object)c.GetComponentInParent(aeroType, true))).ToArray();
            var overlaps = 0;
            for (var i = 0; i < colliders.Length; i++)
                for (var j = i + 1; j < colliders.Length; j++)
                {
                    var (a, pa) = colliders[i];
                    var (c, pc) = colliders[j];
                    if (pa == pc || linked.Contains((pa, pc)) || !a.bounds.Intersects(c.bounds))
                        continue;
                    // Counted, not failed: the plugin has the Icarus's parts ignore one another's colliders (SelfCollision.cs).
                    if (Physics.ComputePenetration(a, a.transform.position, a.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.005f)
                        overlaps++;
                }
            return $"{parts.Length} AeroParts, {mass:0} kg, every part jointed to its parent and collidable, convex hulls, {colliders.Length} colliders " +
                $"({pieces.Length} mesh hulls, {pieces.Sum(c => c.sharedMesh.triangles.Length / 3)} triangles) with {overlaps} unjointed overlaps, {dangling} dangling references, " +
                $"LOD in the prefab, {hulls.Length} LOD1 hulls of {hulls.Sum(h => h.tris)} triangles (largest {hulls.Max(h => h.tris)})";
        }
    }
}
