using System;
using System.IO;
using System.Linq;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
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

        // Two levels as stock: the full meshes, then the LOD1 hulls down to 0.1% of the screen.
        private static void FinishRoot(Build b)
        {
            b.Root.GetComponent<Rigidbody>().mass = EmptyMass;
            var lod = b.Root.GetComponent<LODGroup>();
            var renderers = b.Root.GetComponentsInChildren<Renderer>(true).Where(r => r.gameObject.layer != 3 && !(r is ParticleSystemRenderer)).ToArray();
            var hulls = b.Lod1.ToArray();
            var full = renderers.Except(hulls).ToArray();
            lod.SetLODs(new[] { new LOD(0.05f, full), new LOD(0.001f, hulls) });
            lod.RecalculateBounds();
            lod.size = Mathf.Max(b.Size.x, b.Size.z);
            b.Report.Add($"LODGroup: {full.Length} renderers to 5% of the screen, {hulls.Length} LOD1 hulls to 0.1%, size {lod.size:F2} m");
        }
    }
}
