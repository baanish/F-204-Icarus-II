using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The Revoker panel's clearance behind the windscreen frame.
        private const float PanelBehindBow = 0.03f;

        // The Revoker's cockpit, crew and ladder move as one so its pilot's eye lands at the canopy's eye (BuildCanopy).
        private static void BuildCockpit(Build b)
        {
            var fit = BuildCanopy(b);
            var cockpit = b.Parts["cockpit_cell"].transform;
            var eye = fit.Eye;
            var helmet = (Transform)GetRef(b.Aircraft, "cockpitViewPoint");
            var delta = eye - helmet.position;
            var moved = new[] { "cockpit_interior", "cockpit_interior_simple", "targetScreen", "pilot", "joystick", "throttle" }
                .Select(n => cockpit.Find(n) ?? throw new MissingReferenceException("cockpit_cell/" + n)).ToArray();
            foreach (var t in moved)
                t.position += delta;
            // Everything of the interior above the windscreen frame's foot (the sill) must sit behind the frame, or the
            // frame crosses the pilot's view of the panel: the cockpit moves aft until it does.
            var sill = fit.Sill.min.y;
            var reach = moved[0].GetComponentsInChildren<MeshFilter>(true).Where(f => f.sharedMesh != null)
                .SelectMany(f => WorldVertices(f.transform, f.sharedMesh)).Where(v => v.y > sill).Max(v => v.z);
            var aft = Mathf.Max(0f, reach - (fit.Sill.min.z - PanelBehindBow));
            foreach (var t in moved)
                t.position += Vector3.back * aft;
            eye += Vector3.back * aft;
            delta += Vector3.back * aft;
            b.Placed.UnionWith(moved);
            var ladder = b.Find("ladder");
            ladder.position += delta;
            b.Placed.Add(ladder);

            var aircraft = new SerializedObject(b.Aircraft);
            // Hidden in cockpit view: the internal meshes round the pilot, which the Revoker interior stands inside.
            SetList(Prop(aircraft, "exteriorRenderers"), new[] { "cockpit_cell", "avionics_tray", "radar_tray" }
                .Select(n => (Object)b.Parts[n].GetComponent<MeshRenderer>()).Append(b.Visuals["gear_leg_N_visible"].GetComponent<MeshRenderer>())
                .Concat(fit.Exterior).ToArray());
            aircraft.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"cockpit: eye at {eye} ({EyeBelowCanopyTop} m under the canopy crown, {aft:F2} m aft of it to clear the windscreen frame), Revoker interior, crew and ladder moved {delta}; " +
                $"hood opens {fit.Open:+0;-0} deg on its sill hinge ({(fit.Kept ? "export sign" : "export sign flipped")}) and ejects as its own part");
        }
    }
}
