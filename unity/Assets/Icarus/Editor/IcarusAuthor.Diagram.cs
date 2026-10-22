using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The damage diagram's and the tac screen front profile's art, drawn from the built aircraft by
        // tools/status_diagram.py, which writes the PNGs here and their layout, in the stock prefabs' UI units, to
        // art/diagram.json.
        private const string DiagramFolder = ModFolder + "/Diagram";
        private static string DiagramLayoutPath => Path.Combine(RepoRoot, "art", "diagram.json");

        // The Revoker's tac screen markers by the Icarus station each stands on in the front profile.
        private static readonly (string Marker, string Station)[] FrontProfileMarkers =
        {
            ("hardpoint_TipL", "wingtip_L"), ("hardpoint_TipR", "wingtip_R"), ("hardpoint_PylonL", "pylon_L"),
            ("hardpoint_PylonR", "pylon_R"), ("hardpoint_BayL", "conformal_L"), ("hardpoint_Gun", "conformal_R"),
        };

        private static Dictionary<string, object> DiagramLayout(string section) =>
            (Dictionary<string, object>)((Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(DiagramLayoutPath)))[section];

        private static Vector2 LayoutVector(object value)
        {
            var list = (List<object>)value;
            return new Vector2((float)(double)list[0], (float)(double)list[1]);
        }

        private static Sprite DiagramSprite(string file)
        {
            var path = DiagramFolder + "/" + file;
            if (!(AssetImporter.GetAtPath(path) is TextureImporter importer))
            {
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
                importer = AssetImporter.GetAtPath(path) as TextureImporter ?? throw new FileNotFoundException("Run tools/status_diagram.py first.", path);
            }
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.mipmapEnabled = false;
            importer.alphaSource = TextureImporterAlphaSource.None;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.SaveAndReimport();
            return Load<Sprite>(path);
        }

        // UnityEngine.UI isn't referenced here, so an Image's sprite is set by its serialized name.
        private static void SetSprite(GameObject go, Sprite sprite)
        {
            var image = go.GetComponents<Component>().Single(c => new SerializedObject(c).FindProperty("m_Sprite") != null);
            Set(image, "m_Sprite", sprite);
        }

        // The Revoker's status display with its art replaced: the Icarus's top view as the background, and one image per
        // damageable part, laid out as art/diagram.json places it. PartStatusDisplay finds its part by the image's
        // GameObject name, and the root part's GameObject carries the prefab's name, as the Revoker's carries "Fighter1".
        // Each image is a copy of a Revoker part image, so it keeps the additive material and tint the game recolours.
        private static GameObject AuthorStatusDisplay()
        {
            var layout = DiagramLayout("status");
            var instance = (GameObject)Object.Instantiate(Load<GameObject>(DonorStatusDisplay));
            try
            {
                instance.name = Path.GetFileNameWithoutExtension(StatusDisplayPath);
                var so = new SerializedObject(instance.GetComponent(GameType("StatusDisplay")));
                var entries = Prop(so, "statusDisplays");
                var revoker = Enumerable.Range(0, entries.arraySize).Select(i => (Component)entries.GetArrayElementAtIndex(i).FindPropertyRelative("partImage").objectReferenceValue).ToArray();
                var threshold = entries.GetArrayElementAtIndex(0).FindPropertyRelative("redStatusThreshold").floatValue;
                var template = Object.Instantiate(revoker[0].gameObject);
                try
                {
                    foreach (var image in revoker)
                        Object.DestroyImmediate(image.gameObject);
                    SetSprite(((Component)Prop(so, "aircraftBackground").objectReferenceValue).gameObject, DiagramSprite((string)layout["background"]));
                    var parts = (Dictionary<string, object>)layout["parts"];
                    entries.arraySize = parts.Count;
                    var i = 0;
                    foreach (var part in parts.OrderBy(p => p.Key, System.StringComparer.Ordinal))
                    {
                        var spec = (Dictionary<string, object>)part.Value;
                        var go = Object.Instantiate(template, instance.transform, false);
                        go.name = part.Key == RootPart ? PrefabName : part.Key;
                        var rect = (RectTransform)go.transform;
                        rect.localScale = Vector3.one;
                        rect.anchoredPosition = LayoutVector(spec["centre"]);
                        rect.sizeDelta = LayoutVector(spec["size"]);
                        SetSprite(go, DiagramSprite((string)spec["sprite"]));
                        var entry = entries.GetArrayElementAtIndex(i++);
                        entry.FindPropertyRelative("partImage").objectReferenceValue = go.GetComponents<Component>().Single(c => new SerializedObject(c).FindProperty("m_Sprite") != null);
                        entry.FindPropertyRelative("redStatusThreshold").floatValue = threshold;
                    }
                }
                finally
                {
                    Object.DestroyImmediate(template);
                }
                // The engine fire lamp moves onto the Icarus's engine, its caption staying where it was, and stays on top.
                var fire = (RectTransform)((GameObject)Prop(so, "failureIndicators").GetArrayElementAtIndex(0).objectReferenceValue).transform;
                var engine = (Dictionary<string, object>)((Dictionary<string, object>)layout["parts"])["engine_core"];
                var shift = LayoutVector(engine["centre"]) - fire.anchoredPosition;
                fire.anchoredPosition += shift;
                fire.sizeDelta = LayoutVector(engine["size"]);
                foreach (RectTransform caption in fire)
                    caption.anchoredPosition -= shift;
                fire.SetAsLastSibling();
                so.ApplyModifiedPropertiesWithoutUndo();
                Debug.Log($"[Icarus] stage: damage diagram {entries.arraySize} part images from {DiagramLayoutPath}, engine fire lamp at {fire.anchoredPosition}");
                return SavePrefab(instance, StatusDisplayPath);
            }
            finally
            {
                Object.DestroyImmediate(instance);
            }
        }

        // The tac screen's front profile redrawn as the Icarus's, each station marker moved onto its station.
        private static void DressFrontProfile(GameObject screen)
        {
            var layout = DiagramLayout("front");
            var profile = screen.GetComponentsInChildren<RectTransform>(true).Single(t => t.name == "frontProfile");
            SetSprite(profile.gameObject, DiagramSprite((string)layout["sprite"]));
            var markers = (Dictionary<string, object>)layout["markers"];
            foreach (var (marker, station) in FrontProfileMarkers)
                ((RectTransform)(profile.Find(marker) ?? throw new InvalidDataException("frontProfile has no " + marker))).anchoredPosition = LayoutVector(markers[station]);
        }
    }
}
