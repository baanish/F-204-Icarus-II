using System.Collections.Generic;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The cockpit's slots: Icarus_Int_Cockpit, the cockpit cell's flat review colour, and Icarus_Cockpit, the slot of
        // the cockpit atlas (art/blender/cockpit.py), which wears the same flat material until the atlas exists.
        private const string CockpitSlot = "Icarus_Cockpit";

        private static void AuthorCockpitMaterial(Dictionary<string, Material> map)
        {
            var flat = AuthorFlat("Icarus_Int_Cockpit", new Color32(155, 157, 160, 255), 0.2f, 0.4f);
            map["Icarus_Int_Cockpit"] = flat;
            map[CockpitSlot] = flat;
        }
    }
}
