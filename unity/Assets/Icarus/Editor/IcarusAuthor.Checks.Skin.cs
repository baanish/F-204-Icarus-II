using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        private static string CheckSkin(Build b, List<string> p)
        {
            var renderers = b.Root.GetComponentsInChildren<MeshRenderer>(true);
            var skinRenderers = renderers.Where(r => r.GetComponent<MeshFilter>() != null && r.sharedMaterials.Contains(b.Skin)).ToArray();
            var carrier = b.Root.transform.Find("Icarus_livery_materials");
            var maps = carrier == null ? null : carrier.GetComponent<MeshRenderer>();
            if (carrier == null || carrier.gameObject.activeSelf || carrier.gameObject.layer != 3 || maps == null || maps.enabled || carrier.GetComponent<MeshFilter>() != null)
                p.Add("bare metal texture carrier must be inactive, disabled, layer 3 and mesh-free");
            else
            {
                var held = maps.sharedMaterials;
                if (held.Length != 2 || held[0] != b.Skin || held[1] == null)
                    p.Add("bare metal carrier must hold shared skin and alternate material");
                else
                {
                    var metal = held[1].GetTexture("_Metallic") as Texture2D;
                    var livery = held[1].GetTexture("_Livery");
                    if (metal == null || metal.width != SkinSize || metal.height != SkinSize || metal.format != TextureFormat.DXT5)
                        p.Add("bare metal map must be " + SkinSize + " square DXT5");
                    else
                    {
                        var importer = (TextureImporter)AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(metal));
                        if (importer.sRGBTexture || importer.alphaSource != TextureImporterAlphaSource.FromInput)
                            p.Add("bare metal map must retain linear smoothness alpha");
                    }
                    if (livery != Load<Texture2D>(LiveryFolder + "/Icarus_livery_4.png") || metal == b.Skin.GetTexture("_Metallic"))
                        p.Add("bare metal carrier must identify livery 4 and a distinct metallic map");
                }
            }
            if (skinRenderers.Length == 0) p.Add("no skin renderers");
            foreach (var renderer in renderers.Where(r => r.name.Contains("_detail_")))
                p.Add("unmerged detail renderer: " + renderer.name);
            foreach (var renderer in skinRenderers)
            {
                var slots = renderer.sharedMaterials;
                if (slots[0] != b.Skin || slots.Count(m => m == b.Skin) != 1)
                    p.Add(renderer.name + " skin must occur only at slot 0");
                var owner = renderer.GetComponentInParent(GameType("AeroPart"), true);
                if (owner == null)
                    p.Add(renderer.name + " has no part owner");
                else
                {
                    var damage = Prop(new SerializedObject(owner), "damageMaterial");
                    if (!GetList(damage.FindPropertyRelative("renderers")).Contains(renderer))
                        p.Add(renderer.name + " is not listed in its part's damage renderers");
                }
                var mesh = renderer.GetComponent<MeshFilter>()?.sharedMesh;
                if (mesh == null || mesh.uv.Length != mesh.vertexCount || mesh.subMeshCount == 0)
                {
                    p.Add(renderer.name + " has no complete skin UVs");
                    continue;
                }
                var uv = mesh.uv;
                var skinSlot = System.Array.IndexOf(slots, b.Skin);
                if (skinSlot < 0 || skinSlot >= mesh.subMeshCount)
                {
                    p.Add(renderer.name + " has no skin submesh");
                    continue;
                }
                foreach (var index in mesh.GetIndices(skinSlot).Distinct())
                    if (float.IsNaN(uv[index].x) || float.IsNaN(uv[index].y) || uv[index].x < 0 || uv[index].x > 1 || uv[index].y < 0 || uv[index].y > 1)
                    {
                        p.Add(renderer.name + " skin UV outside [0,1]");
                        break;
                    }
            }
            foreach (var property in new[] { "_Basecolor", "_Livery", "_Normal", "_AO", "_Metallic", "_BasecolorDmg", "_NormalDmg" })
            {
                var texture = b.Skin.GetTexture(property) as Texture2D;
                if (texture == null || texture.width != SkinSize || texture.height != SkinSize)
                {
                    p.Add(property + " must be " + SkinSize + " square");
                    continue;
                }
                var importer = (TextureImporter)AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(texture));
                var normal = property == "_Normal" || property == "_NormalDmg";
                var linear = normal || property == "_AO" || property == "_Metallic";
                if (importer.sRGBTexture == linear || (importer.textureType == TextureImporterType.NormalMap) != normal)
                    p.Add(property + " has incorrect colour space or texture type");
                if (property == "_Metallic" && texture.format != TextureFormat.DXT5)
                    p.Add("metallic map must preserve smoothness alpha in DXT5");
            }
            var liveries = Prop(new SerializedObject(b.Parameters), "liveries");
            if (liveries.arraySize != 4) p.Add("expected four liveries, got " + liveries.arraySize);
            var textures = new HashSet<Object>();
            var primeva = Load<Object>(Stock + "MonoBehaviour/Primeva_PLACEHOLDER.asset");
            for (var i = 0; i < liveries.arraySize; i++)
            {
                var entry = liveries.GetArrayElementAtIndex(i);
                if (entry.FindPropertyRelative("faction").objectReferenceValue != primeva)
                    p.Add("livery " + i + " faction is not Primeva");
                var guid = entry.FindPropertyRelative("assetReference").FindPropertyRelative("m_AssetGUID").stringValue;
                var data = AssetDatabase.LoadAssetAtPath<Object>(AssetDatabase.GUIDToAssetPath(guid));
                if (data == null)
                {
                    p.Add("livery " + i + " has no LiveryData");
                    continue;
                }
                var so = new SerializedObject(data);
                var texture = Prop(so, "Texture").objectReferenceValue as Texture2D;
                if (texture == null || texture.width != SkinSize || texture.height != SkinSize || texture.format != TextureFormat.DXT1)
                    p.Add("livery " + i + " must be " + SkinSize + " square DXT1");
                if (texture != null && !textures.Add(texture)) p.Add("liveries share a texture");
                if (Prop(so, "Colors").arraySize == 0) p.Add("livery " + i + " has no dominant paint");
            }
            var lod = b.Root.GetComponent<LODGroup>();
            var count = lod == null || lod.GetLODs().Length == 0 ? 0 : lod.GetLODs()[0].renderers.Length;
            return $"{skinRenderers.Length} registered skin renderers, four Primeva liveries, exterior LOD0 {count} renderers";
        }
    }
}
