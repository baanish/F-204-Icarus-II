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
        // station takes the Revoker marker standing nearest its place on the Revoker's silhouette: the conformal stations
        // take the bay and cannon markers, moved and retitled.
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
                var gunWeapon = LayOutStores(screen);
                float X(int set) => revoker[set].Images.Concat(revoker[set].Texts).OfType<Component>().Average(c => c.transform.position.x);
                (int Left, int Right) Sides(int a, int c) => X(a) <= X(c) ? (a, c) : (c, a);
                var (tipL, tipR) = Sides(0, 5);
                var (pylonL, pylonR) = Sides(1, 4);
                var map = new[] { tipL, tipR, pylonL, pylonR, 2, 3 };
                elements.arraySize = map.Length;
                for (var i = 0; i < map.Length; i++)
                {
                    var entry = elements.GetArrayElementAtIndex(i);
                    SetList(entry.FindPropertyRelative("pylonImages"), revoker[map[i]].Images);
                    // the cannon's set (3) recolours the WEAPON line its box gained with the others'
                    SetList(entry.FindPropertyRelative("pylonTexts"), map[i] == 3 ? revoker[3].Texts.Append(gunWeapon).ToArray() : revoker[map[i]].Texts);
                }
                indicator.ApplyModifiedPropertiesWithoutUndo();
                // The front profile becomes the Icarus's with every marker on its station, the Revoker's bay and gun dots on
                // the conformal stations (its +x is the aircraft's left).
                DressFrontProfile(screen);
                Set(cockpit, "tacScreenUIPrefab", SavePrefab(screen, TacScreenPath));
                b.Report.Add($"tac screen: owned copy with engine telemetry on {PrefabName} and {map.Length} pylon sets on the Revoker markers [{string.Join(", ", map)}], the Icarus front profile with every marker on its station over a row of six station boxes, {string.Join(" ", StationBoxes.Select(s => s.Title))}");
            }
            finally
            {
                Object.DestroyImmediate(screen);
            }
        }

        // The stores page (WeaponPanel): the front profile over one row of six station boxes, right wingtip to left as the
        // profile shows them, each box three centred lines (station, WEAPON, its state) that shrink to fit its width. The
        // Revoker drew the profile over its boxes, its markers on their titles, and its cannon as a banner in the top
        // corner whose station and state ran together once retitled.
        private static readonly (string Box, string Title)[] StationBoxes =
        {
            ("Box_TipR", "R.TIP"), ("Box_PylonR", "R.PYLON"), ("Box_Gun", "R.CONF"), ("Box_Bay", "L.CONF"), ("Box_PylonL", "L.PYLON"),
            ("Box_TipL", "L.TIP"),
        };
        private const float BoxWidth = 70f, BoxHeight = 64f, BoxGap = 3f, PanelMargin = 4f, LinePitch = 20f;

        // Returns the cannon box's new WEAPON line, for its pylon set to recolour.
        private static Component LayOutStores(GameObject screen)
        {
            RectTransform Named(string n) => screen.GetComponentsInChildren<RectTransform>(true).Single(t => t.name == n);
            Component Text(Transform t) => t.GetComponents<Component>().Single(c => new SerializedObject(c).FindProperty("m_text") != null);
            var panel = Named("WeaponPanel");
            var size = panel.sizeDelta;
            var row = StationBoxes.Length * BoxWidth + (StationBoxes.Length - 1) * BoxGap;
            if (row > size.x - 2 * PanelMargin)
                throw new InvalidDataException($"A7: six {BoxWidth}-wide station boxes ({row}) overrun the weapon panel ({size.x})");
            var gun = Named("Box_Gun");
            var weapon = Object.Instantiate(Named("Box_Bay").Find("WPN").gameObject, gun, false);
            weapon.name = "WPN";
            var bottom = -size.y / 2 + PanelMargin;
            for (var i = 0; i < StationBoxes.Length; i++)
            {
                var box = Named(StationBoxes[i].Box);
                box.anchorMin = box.anchorMax = box.pivot = new Vector2(0.5f, 0.5f);
                box.anchoredPosition = new Vector2(-row / 2 + BoxWidth / 2 + i * (BoxWidth + BoxGap), bottom + BoxHeight / 2);
                box.sizeDelta = new Vector2(BoxWidth, BoxHeight);
                foreach (var (line, y) in new[] { ("Title", LinePitch), ("WPN", 0f), ("Value", -LinePitch) })
                {
                    var rect = (RectTransform)box.Find(line);
                    rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(0.5f, 0.5f);
                    rect.anchoredPosition = new Vector2(0f, y);
                    rect.sizeDelta = new Vector2((BoxWidth - 6f) / rect.localScale.x, rect.sizeDelta.y);
                    var text = new SerializedObject(Text(rect));
                    if (line == "Title") Prop(text, "m_text").stringValue = StationBoxes[i].Title;
                    Prop(text, "m_HorizontalAlignment").intValue = 2; // centre
                    Prop(text, "m_enableWordWrapping").boolValue = false;
                    Prop(text, "m_enableAutoSizing").boolValue = true;
                    Prop(text, "m_fontSizeMin").floatValue = 20f;
                    Prop(text, "m_fontSizeMax").floatValue = Prop(text, "m_fontSize").floatValue;
                    text.ApplyModifiedPropertiesWithoutUndo();
                }
            }
            // the profile over the row, as large as the space above it allows
            var profile = Named("frontProfile");
            var floor = bottom + BoxHeight + BoxGap;
            var top = size.y / 2 - PanelMargin;
            var scale = Mathf.Min((top - floor) / profile.sizeDelta.y, (size.x - 2 * PanelMargin) / profile.sizeDelta.x);
            profile.localScale = new Vector3(scale, scale, 1f);
            profile.anchoredPosition = new Vector2(0f, (top + floor) / 2);
            return Text(weapon.transform);
        }
    }
}
