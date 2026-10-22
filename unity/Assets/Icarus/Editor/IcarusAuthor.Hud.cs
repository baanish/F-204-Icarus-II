using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        private const string HudExtrasPath = ModFolder + "/Icarus_HUDExtras.prefab";
        // SpeedGauge.overspeedThreshold, in m/s of Aircraft.speed (inertial speed): past it the HUD's speed readout turns red,
        // OVERSPEED blinks and the voice calls it. The Revoker's HUD warns at 580, just under where its core thrust runs out
        // (592). The Icarus holds 797 to 803 m/s level at 15 km (Mach 2.75 at the game's 290 m/s speed of sound up there) and
        // 832 at 18 km, and its core thrust runs out at 912 (the Turbojet's maxSpeed 760 x 1.2), so 850 warns past the flown
        // envelope, in a dive, short of the engine's limit. The readout's colour below the threshold is SpeedGauge's own
        // code-built gradient on takeoffSpeed (green from twice it up), not serialized and not touched here.
        private const float OverspeedThreshold = 850f;

        // The Revoker's HUD extras (the afterburner and airbrake flags, both of which the Icarus has) as the Icarus's own copy,
        // its speed gauge's overspeed warning moved to the Icarus's speeds.
        private static GameObject AuthorHudExtras()
        {
            var instance = (GameObject)Object.Instantiate(Load<GameObject>(DonorHudExtras));
            try
            {
                instance.name = Path.GetFileNameWithoutExtension(HudExtrasPath);
                var gauge = new SerializedObject(instance.GetComponentsInChildren(GameType("SpeedGauge"), true).Single());
                Prop(gauge, "overspeedThreshold").floatValue = OverspeedThreshold;
                gauge.ApplyModifiedPropertiesWithoutUndo();
                Debug.Log($"[Icarus] stage: HUD extras copied from the Revoker's with overspeed at {OverspeedThreshold} m/s");
                return SavePrefab(instance, HudExtrasPath);
            }
            finally
            {
                Object.DestroyImmediate(instance);
            }
        }
    }
}
