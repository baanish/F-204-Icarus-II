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
        // The Icarus's own 25 mm gun pod on the Centreline station: the stock gun_25mm_trainer_pod's mount and gun, its gun
        // raised under the belly, in a body drawn for the Icarus (art/blender/gun_pod.py) in place of the stock pod's,
        // which hangs a T/A-30 pylon adapter 0.61 m under the hardpoint.
        private const string GunPod25 = "baanish_icarus_gunpod_25mm";
        private const string GunPodBody = "gunpod_25mm_body";

        private static Dictionary<string, object> GunPodLayout() =>
            (Dictionary<string, object>)((Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(ExportFolder, "blockout.json"))))["gun_pod"];

        private static Mesh ImportGunPodMesh(Dictionary<string, object> layout)
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
            var mesh = AssetDatabase.LoadAllAssetsAtPath(target).OfType<Mesh>().SingleOrDefault(m => m.name == GunPodBody)
                ?? throw new InvalidDataException($"{target} has no {GunPodBody} mesh");
            var box = (List<object>)layout["bounds_unity"];
            if ((mesh.bounds.min - Vec3(box[0])).magnitude > 0.02f || (mesh.bounds.max - Vec3(box[1])).magnitude > 0.02f)
                throw new InvalidDataException($"{GunPodBody}: imported bounds {mesh.bounds.min}..{mesh.bounds.max} differ from the export's");
            return mesh;
        }

        private static Object AuthorGunPodMount()
        {
            BlueprinterAssets.EnsureFolder(MountFolder);
            var layout = GunPodLayout();
            if ((string)layout["key"] != GunPod25)
                throw new InvalidDataException($"blockout.json's gun pod is {layout["key"]}, not {GunPod25}");
            var mesh = ImportGunPodMesh(layout);
            // The body was drawn on the hardpoint where Blender's skin puts it; the built one is where A5 holds it.
            var drawnOn = Vec3(layout["hardpoint_unity"]) - Blockout.Load(ExportFolder).Origin;
            var offset = drawnOn - MeasuredHardpoints["hardpoint_centreline"].Position;
            if (offset.magnitude > 0.03f)
                throw new InvalidDataException($"{GunPodBody} was drawn on a hardpoint {offset.magnitude:F3} m from the centreline station's");
            var prefabPath = MountFolder + "/" + GunPod25 + ".prefab";
            var assetPath = MountFolder + "/" + GunPod25 + ".asset";
            var copies = new[] { ("GameObject/gun_25mm_trainer_pod_PLACEHOLDER.prefab", prefabPath), ("MonoBehaviour/gun_25mm_trainer_pod_PLACEHOLDER.asset", assetPath) };
            foreach (var (source, target) in copies)
            {
                File.Copy(Stock + source, target, true); // keeps the target's .meta, so its GUID survives
                AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
            }
            var root = PrefabUtility.LoadPrefabContents(prefabPath);
            string placed;
            try
            {
                root.name = GunPod25;
                var pod = root.transform.Find("gunpod") ?? throw new InvalidDataException("gun_25mm_trainer_pod has no gunpod");
                var barrel = root.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == "trainer_gunpod_barrel")
                    ?? throw new InvalidDataException("gun_25mm_trainer_pod has no trainer_gunpod_barrel");
                // The gun rises with the stock pod's whole gun assembly, so its axis lands where the body leaves room for it.
                var lift = offset.y + Float(layout, "gun_axis_y") - root.transform.InverseTransformPoint(barrel.position).y;
                pod.localPosition += Vector3.up * lift;
                pod.GetComponent<MeshRenderer>().enabled = false;
                var capsule = pod.GetComponent<CapsuleCollider>() ?? throw new InvalidDataException("gun_25mm_trainer_pod's gunpod has no capsule");
                var collider = (Dictionary<string, object>)layout["collider"];
                capsule.direction = 2;
                capsule.radius = Float(collider, "radius");
                capsule.height = Float(collider, "length") + 2f * capsule.radius;
                capsule.center = pod.InverseTransformPoint(root.transform.TransformPoint(offset + Vec3(collider["centre"])));
                var body = new GameObject(GunPodBody) { layer = pod.gameObject.layer };
                body.transform.SetParent(root.transform, false);
                body.transform.localPosition = offset;
                body.AddComponent<MeshFilter>().sharedMesh = mesh;
                var skin = body.AddComponent<MeshRenderer>();
                skin.sharedMaterials = new[] { Load<Material>(SkinPath) };
                var paint = root.GetComponent(GameType("ColorableMount"));
                if (paint == null)
                    AuthorMountPaint(root, skin);
                else
                {
                    var so = new SerializedObject(paint);
                    Prop(so, "colorableRenderers").arraySize = 0;
                    SetList(Prop(so, "skinnableRenderers"), new Object[] { skin });
                    so.ApplyModifiedPropertiesWithoutUndo();
                }
                placed = $"gun raised {lift:F3} m, body {offset.y * 1000f:F1} mm off the hardpoint";
                SavePrefab(root, prefabPath);
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
            var mount = Load<Object>(assetPath);
            mount.name = GunPod25;
            var asset = new SerializedObject(mount);
            Prop(asset, "jsonKey").stringValue = GunPod25;
            Prop(asset, "prefab").objectReferenceValue = Load<GameObject>(prefabPath);
            asset.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(mount);
            AssetDatabase.SaveAssets();
            Debug.Log($"[Icarus] stage: gun pod mount {GunPod25}: {placed}, {mesh.triangles.Length / 3} triangles");
            return mount;
        }

        private static float Float(Dictionary<string, object> d, string key) => System.Convert.ToSingle(d[key]);
    }
}
