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
        // The Revoker's cockpit meshes the Icarus cockpit replaces; A7 fails if any is still drawn.
        private static readonly string[] RevokerCockpitMeshes =
            { "fighter1_interior", "fighter1_interior_simple", "fighter1_targetScreen", "fighter1_interior_warningLights" };

        // The Icarus cockpit (art/blender/cockpit.py) in the Revoker's systems. Its interior takes the Revoker interior's place
        // on the GameObject carrying Cockpit and CockpitWarningLights; the inner frames, tac screen and lamps are its own
        // renderers, the hood's inner frame and frame proxy riding the hood. The stock stick and throttle stand on the export's
        // pivots, and the stock seat and pilot rig keep the Revoker's offsets from its eye, moved to the canopy's eye, less the
        // seat's drop to the export's cockpit_seat.
        private static void BuildCockpit(Build b)
        {
            var fit = BuildCanopy(b);
            var cockpit = b.Parts["cockpit_cell"].transform;
            Transform Child(string n) => cockpit.Find(n) ?? throw new MissingReferenceException("cockpit_cell/" + n);
            var helmet = (Transform)GetRef(b.Aircraft, "cockpitViewPoint");
            var delta = fit.Eye - helmet.position;
            var pilot = Child("pilot");
            var ladder = b.Find("ladder");
            pilot.position += delta;
            ladder.position += delta;
            // The seat, and the pilot in it, sit at the export's seat empty: a little under the Revoker's offset from its
            // eye, so the headbox clears the hood glass. The camera point stays on the eye.
            var seat = FindDeep(pilot, "EjectionSeat");
            var drop = b.Blockout.Local("cockpit_seat") - seat.position;
            pilot.position += drop;
            helmet.position = fit.Eye;
            var stick = Child("joystick");
            var throttle = Child("throttle");
            // the pivots are the Revoker's reach from its eye moved to the Icarus eye, so they land where the move would
            var drift = Mathf.Max((b.Blockout.Local("cockpit_stick_pivot") - (stick.position + delta)).magnitude,
                (b.Blockout.Local("cockpit_throttle_pivot") - (throttle.position + delta)).magnitude);
            stick.position = b.Blockout.Local("cockpit_stick_pivot");
            throttle.position = b.Blockout.Local("cockpit_throttle_pivot");
            b.Placed.UnionWith(new[] { pilot, ladder, stick, throttle });

            var interior = Child("cockpit_interior");
            var cockpitUi = interior.GetComponent(GameType("Cockpit"));
            var warning = interior.GetComponent(GameType("CockpitWarningLights"));
            DestroyWithReferences(b, new List<Object>
            {
                interior.Find("warningLights")?.gameObject ?? throw new MissingReferenceException("cockpit_interior/warningLights"),
                Child("cockpit_interior_simple").gameObject, Child("targetScreen").gameObject,
            });
            interior.SetPositionAndRotation(b.Blockout.Local("cockpit_interior"), b.Blockout.Rotation("cockpit_interior"));
            interior.GetComponent<MeshFilter>().sharedMesh = b.Meshes["cockpit_interior"].Render;
            var inside = interior.GetComponent<MeshRenderer>();
            inside.sharedMaterials = b.Meshes["cockpit_interior"].Materials;
            b.Visuals["cockpit_interior"] = interior;

            var hood = b.Visuals["canopy_glass_inner"].parent;
            var screen = MeshVisual(b, "cockpit_tac_screen", interior);
            var lamps = MeshVisual(b, "cockpit_warning_lamps", interior);
            // The standby ball, the fuel needle and the clock's hands, each on its own pivot; the plugin turns them
            // (src/Icarus/StandbyInstruments.cs finds them by these names).
            var instruments = CockpitInstruments.Select(n => (Renderer)MeshVisual(b, n, interior)).ToArray();
            // The lever from the grip down through the quadrant's gate rides the transform Cockpit.throttles turns, so it
            // moves with the grip; its origin is the export's throttle pivot, where that transform stands.
            var lever = MeshVisual(b, ThrottleLever, interior);
            lever.transform.SetParent(throttle, true);
            var frames = new[] { MeshVisual(b, "windscreen_frame_inner", cockpit), MeshVisual(b, "canopy_frame_inner", hood) };
            var proxies = new[] { MeshVisual(b, "cockpit_proxy", cockpit), MeshVisual(b, "canopy_frame_proxy", hood) };
            var panes = new[] { "canopy_glass_inner", "windscreen_inner" }.Select(n => b.Visuals[n].GetComponent<MeshRenderer>());
            Renderer[] view = new Renderer[] { inside }.Concat(frames).Concat(panes)
                .Concat(new[] { screen, stick.GetComponent<MeshRenderer>(), throttle.GetComponent<MeshRenderer>(), lever }).Concat(instruments).ToArray();
            // Drawn only by the cockpit camera, and only once the player is in the cockpit view (Aircraft.SetCockpitRenderers).
            foreach (var r in view.Append(lamps))
            {
                r.gameObject.layer = CockpitLayer;
                r.enabled = false;
            }
            if (interior.GetComponentsInChildren<Light>(true).Length > 0)
                throw new InvalidDataException("cockpit: a Light under the interior");

            var lights = new SerializedObject(warning);
            SetList(Prop(lights, "lightRenderers"), new Object[] { lamps });
            lights.ApplyModifiedPropertiesWithoutUndo();
            Set(cockpitUi, "tacScreenRender", screen);
            // TargetCam's detach handler paints its screen with the stock no-signal material. The Revoker's target screen went
            // with its interior, and a null one throws there, which ends the part's detach before the other peers hear of it.
            Set(b.Parts["radome"].GetComponent(GameType("TargetCam")), "targetScreenRenderer", screen);
            var aircraft = new SerializedObject(b.Aircraft);
            SetList(Prop(aircraft, "cockpitRenderers"), view);
            // Hidden in the cockpit view: the internals round the pilot, the outer glass, and the proxies standing in outside
            // for what the cockpit view draws.
            SetList(Prop(aircraft, "exteriorRenderers"), new[] { "cockpit_cell", "avionics_tray", "radar_tray" }
                .Select(n => (Object)Placed(b, n).GetComponent<MeshRenderer>()).Append(b.Visuals["gear_leg_N_visible"].GetComponent<MeshRenderer>())
                .Concat(fit.Exterior).Concat(proxies).ToArray());
            aircraft.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"cockpit: eye at {fit.Eye}, the stock seat and pilot rig and the ladder moved {delta}, the seat and pilot a further {drop} to clear the hood glass, the stick and throttle on their " +
                $"pivots ({drift * 1000:F1} mm from the Revoker's reach), the throttle lever ({Tris(lever)} triangles) on the throttle; interior {Tris(inside)}, frames {Tris(frames[0])} + {Tris(frames[1])}, " +
                $"tac screen {Tris(screen)}, lamps {Tris(lamps)}, instruments {instruments.Sum(Tris)}, proxies {Tris(proxies[0])} + {Tris(proxies[1])} triangles; " +
                $"hood opens {fit.Open:+0;-0} deg on its sill hinge ({(fit.Kept ? "export sign" : "export sign flipped")}) and ejects as its own part");
        }

        private static int Tris(Renderer r) => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3;

        // The instruments' moving parts (art/blender/cockpit.py INSTRUMENTS).
        private static readonly string[] CockpitInstruments =
            { "cockpit_standby_ball", "cockpit_fuel_needle", "cockpit_clock_hour", "cockpit_clock_minute" };

        private const string ThrottleLever = "cockpit_throttle_lever"; // art/blender/cockpit.py LEVER
    }
}
