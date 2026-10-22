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
        // pivots, and the stock seat and pilot rig keep the Revoker's offsets from its eye, moved to the canopy's eye.
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
            var frames = new[] { MeshVisual(b, "windscreen_frame_inner", cockpit), MeshVisual(b, "canopy_frame_inner", hood) };
            var proxies = new[] { MeshVisual(b, "cockpit_proxy", cockpit), MeshVisual(b, "canopy_frame_proxy", hood) };
            var panes = new[] { "canopy_glass_inner", "windscreen_inner" }.Select(n => b.Visuals[n].GetComponent<MeshRenderer>());
            Renderer[] view = new Renderer[] { inside }.Concat(frames).Concat(panes)
                .Concat(new[] { screen, stick.GetComponent<MeshRenderer>(), throttle.GetComponent<MeshRenderer>() }).ToArray();
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
            var aircraft = new SerializedObject(b.Aircraft);
            SetList(Prop(aircraft, "cockpitRenderers"), view);
            // Hidden in the cockpit view: the internals round the pilot, the outer glass, and the proxies standing in outside
            // for what the cockpit view draws.
            SetList(Prop(aircraft, "exteriorRenderers"), new[] { "cockpit_cell", "avionics_tray", "radar_tray" }
                .Select(n => (Object)b.Parts[n].GetComponent<MeshRenderer>()).Append(b.Visuals["gear_leg_N_visible"].GetComponent<MeshRenderer>())
                .Concat(fit.Exterior).Concat(proxies).ToArray());
            aircraft.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"cockpit: eye at {fit.Eye}, the stock seat and pilot rig and the ladder moved {delta}, the stick and throttle on their " +
                $"pivots ({drift * 1000:F1} mm from the Revoker's reach); interior {Tris(inside)}, frames {Tris(frames[0])} + {Tris(frames[1])}, " +
                $"tac screen {Tris(screen)}, lamps {Tris(lamps)}, proxies {Tris(proxies[0])} + {Tris(proxies[1])} triangles; " +
                $"hood opens {fit.Open:+0;-0} deg on its sill hinge ({(fit.Kept ? "export sign" : "export sign flipped")}) and ejects as its own part");
        }

        private static int Tris(Renderer r) => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3;
    }
}
