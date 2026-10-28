using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The ceilings for the LOD1 hulls (A12): exterior rule 27's per hull, and in all its 760 raised to the 780 the
        // split wing skins measure (art/blender/hulls.py LOD1_TOTAL).
        private const int Lod1PerHull = 56, Lod1Total = 780;

        // Each LOD1 hull on the part or visual it belongs to, at identity (the export puts it in that mesh's space).
        private static void AddLods(Build b)
        {
            foreach (var entry in b.Meshes.Where(m => m.Value.Lod1 != null).OrderBy(m => m.Key, StringComparer.Ordinal))
            {
                var owner = b.Parts.TryGetValue(entry.Key, out var part) && !b.Blockout.Parts[entry.Key].IsHinge ? part.transform
                    : b.Visuals.TryGetValue(entry.Key, out var visual) ? visual : throw new InvalidDataException(entry.Key + " has a LOD1 hull but no place in the prefab");
                var go = new GameObject(entry.Key + "_lod1") { layer = b.Root.layer };
                go.transform.SetParent(owner, false);
                go.AddComponent<MeshFilter>().sharedMesh = entry.Value.Lod1;
                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = entry.Value.Lod1Materials;
                b.Lod1.Add(renderer);
            }
        }

        // Two levels as stock, in one LODGroup per part where stock has one on the root. Physics unparents every part
        // (AeroPart.CreateRB), and the game never touches a LODGroup, so a part that breaks off stays in the group that
        // lists it: in the root's, debris beside the camera turned to its hull, or vanished, by the distance of the
        // fuselage it left. Every group is sized to the whole aircraft, so the intact aircraft changes level at once.
        private static void FinishRoot(Build b)
        {
            b.Root.GetComponent<Rigidbody>().mass = EmptyMass;
            var aeroType = GameType("AeroPart");
            var hulls = new HashSet<Renderer>(b.Lod1);
            var size = Mathf.Max(b.Size.x, b.Size.z);
            var groups = b.Root.GetComponentsInChildren<Renderer>(true).Where(r => r.gameObject.layer != 3 && !(r is ParticleSystemRenderer))
                .GroupBy(r => r.GetComponentInParent(aeroType, true)).ToArray();
            foreach (var group in groups)
            {
                if (group.Key == null)
                    throw new InvalidDataException(group.First().name + " has no part to take its LOD from");
                var lod = group.Key.GetComponent<LODGroup>();
                if (lod == null)
                    lod = group.Key.gameObject.AddComponent<LODGroup>();
                lod.SetLODs(new[] { new LOD(0.05f, group.Where(r => !hulls.Contains(r)).ToArray()), new LOD(0.001f, group.Where(hulls.Contains).ToArray()) });
                lod.RecalculateBounds();
                lod.size = size;
            }
            b.Report.Add($"LODGroup: one on each of {groups.Length} parts, {groups.Sum(g => g.Count()) - hulls.Count} renderers to 5% of the screen, {hulls.Count} LOD1 hulls to 0.1%, size {size:F2} m");
        }
    }
}
