using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The tactical screen the borrowed Revoker cockpit instantiates (Cockpit.tacScreenUIPrefab), owned so it fits the
        // Icarus: PylonIndicator colours pylonElementSets[i] by the ammo on HardpointIndex i and throws past its last set,
        // and EngineTelemetry finds its engine by the GameObject name of the damageable carrying it.
        private const string DonorTacScreen = Stock + "GameObject/tacScreen_fighter1_PLACEHOLDER.prefab";
        private const string TacScreenPath = ModFolder + "/Icarus_TacScreen.prefab";

        // The Revoker's sets by its HardpointIndex: wingtips 0 and 5, wing pylons 1 and 4, bays 2, cannon 3. Each Icarus
        // station takes the Revoker marker standing nearest its place on the Revoker's silhouette: the outer pylons share
        // the inner pylons' markers and the conformal stations take the bay and cannon markers, until the Icarus screen.
        private static void BuildTacScreen(Build b)
        {
            var cockpit = b.Parts["cockpit_cell"].GetComponentsInChildren(GameType("Cockpit"), true).Single();
            if (GetRef(cockpit, "tacScreenUIPrefab") != Load<GameObject>(DonorTacScreen))
                throw new InvalidDataException("A7: the Revoker cockpit doesn't use " + DonorTacScreen);
            var screen = (GameObject)Object.Instantiate(Load<GameObject>(DonorTacScreen));
            try
            {
                screen.name = Path.GetFileNameWithoutExtension(TacScreenPath);
                foreach (var telemetry in screen.GetComponentsInChildren(GameType("EngineTelemetry"), true))
                {
                    var so = new SerializedObject(telemetry);
                    Prop(so, "engineName").stringValue = PrefabName; // the root, which carries the Turbojet
                    so.ApplyModifiedPropertiesWithoutUndo();
                }

                var indicator = new SerializedObject(screen.GetComponentsInChildren(GameType("PylonIndicator"), true).Single());
                var elements = Prop(indicator, "pylonElementSets");
                if (elements.arraySize != 6)
                    throw new InvalidDataException($"A7: the Revoker tac screen has {elements.arraySize} pylon sets, expected 6");
                var revoker = Enumerable.Range(0, elements.arraySize).Select(i => elements.GetArrayElementAtIndex(i)).Select(e =>
                    (Images: GetList(e.FindPropertyRelative("pylonImages")), Texts: GetList(e.FindPropertyRelative("pylonTexts")))).ToArray();
                float X(int set) => revoker[set].Images.Concat(revoker[set].Texts).OfType<Component>().Average(c => c.transform.position.x);
                (int Left, int Right) Sides(int a, int c) => X(a) <= X(c) ? (a, c) : (c, a);
                var (tipL, tipR) = Sides(0, 5);
                var (pylonL, pylonR) = Sides(1, 4);
                var map = new[] { tipL, tipR, pylonL, pylonR, pylonL, pylonR, 2, 3 };
                elements.arraySize = map.Length;
                for (var i = 0; i < map.Length; i++)
                {
                    var entry = elements.GetArrayElementAtIndex(i);
                    SetList(entry.FindPropertyRelative("pylonImages"), revoker[map[i]].Images);
                    SetList(entry.FindPropertyRelative("pylonTexts"), revoker[map[i]].Texts);
                }
                indicator.ApplyModifiedPropertiesWithoutUndo();
                Set(cockpit, "tacScreenUIPrefab", SavePrefab(screen, TacScreenPath));
                b.Report.Add($"tac screen: owned copy with engine telemetry on {PrefabName} and {map.Length} pylon sets on the Revoker markers [{string.Join(", ", map)}]");
            }
            finally
            {
                Object.DestroyImmediate(screen);
            }
        }
    }
}
