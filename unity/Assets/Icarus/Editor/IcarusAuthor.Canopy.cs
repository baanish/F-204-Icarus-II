using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The layer the game draws only in the cockpit view (the inner glass, as on the stock cockpits).
        private const int CockpitLayer = 3;

        // The design eye's depth under the hood's crown, measured in BuildCanopy; the cockpit's report prints it.
        private static float EyeBelowCanopyTop;

        // What the cockpit is fitted to: the pilot's eye and the windscreen the interior must sit behind, both in prefab
        // space, how the hood opens, and canopy renderers to hide in the cockpit view.
        private sealed class CanopyFit
        {
            public Vector3 Eye;
            public Bounds Sill;
            public float Open;
            public bool Kept;
            public Renderer[] Exterior = Array.Empty<Renderer>();
        }

        // The hood on its sill hinge carrying its frame and both glass layers, and the windscreen's two layers on the
        // cockpit. The outer panes hide in the cockpit view; the inner panes (cockpit layer, no shadows) show there and are
        // the ones the game cracks. The Revoker canopy rig is gone; its Canopy opens the Icarus hood on its hinge and
        // ejects the canopy part.
        private static CanopyFit BuildCanopy(Build b)
        {
            var canopy = b.Parts["canopy"].transform;
            var (_, hood, frame) = HingeRig(b, "canopy", null, canopy);
            var cockpit = b.Parts["cockpit_cell"].transform;
            var outer = new[] { MeshVisual(b, "canopy_glass_outer", hood), MeshVisual(b, "windscreen", cockpit) };
            var inner = new[] { MeshVisual(b, "canopy_glass_inner", hood), MeshVisual(b, "windscreen_inner", cockpit) };
            foreach (var pane in inner)
            {
                pane.gameObject.layer = CockpitLayer;
                pane.shadowCastingMode = ShadowCastingMode.Off;
            }
            var eye = DesignEye(b);
            EyeBelowCanopyTop = WorldVertices(outer[0].transform, b.Meshes["canopy_glass_outer"].Render).Max(p => p.y) - eye.y;

            var (open, kept) = Travel(b, canopy, frame.bounds.center, "canopy", p => p.y); // the hood swings up
            var component = canopy.gameObject.AddComponent(GameType("Canopy"));
            EditorUtility.CopySerialized(b.Donor.CanopyTemplate, component);
            var so = new SerializedObject(component);
            Prop(so, "attachedPart").objectReferenceValue = b.Part("canopy");
            Prop(so, "ejectionTransform").objectReferenceValue = canopy;
            Prop(so, "ejectionCollider").objectReferenceValue = canopy.GetComponent<MeshCollider>();
            var hinges = Prop(so, "canopyHinges");
            hinges.arraySize = 1;
            hinges.GetArrayElementAtIndex(0).FindPropertyRelative("transform").objectReferenceValue = hood;
            hinges.GetArrayElementAtIndex(0).FindPropertyRelative("hingeAngle").floatValue = open;
            SetList(Prop(so, "glassRenderers"), inner);
            // Canopy pushes along its part's own forward and up (Canopy.cs FixedUpdate); the hood's hinge frame has up
            // pointing down into the cockpit, so the Revoker's push is re-expressed in that frame to point up out of it.
            var push = Vector3.up * Prop(so, "ejectionForce").vector3Value.magnitude;
            Prop(so, "ejectionForce").vector3Value = new Vector3(0f, Vector3.Dot(push, canopy.up), Vector3.Dot(push, canopy.forward));
            so.ApplyModifiedPropertiesWithoutUndo();

            var aircraft = new SerializedObject(b.Aircraft);
            SetList(Prop(aircraft, "canopies"), new Object[] { component });
            aircraft.ApplyModifiedPropertiesWithoutUndo();
            return new CanopyFit { Eye = eye, Sill = outer[1].bounds, Open = open, Kept = kept, Exterior = outer };
        }

        // canopy.EYE, which tools/export_blockout.py writes to blockout.json as design_eye, in prefab space.
        private static Vector3 DesignEye(Build b)
        {
            var json = (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path.Combine(ExportFolder, "blockout.json")));
            var eye = (List<object>)((Dictionary<string, object>)json["design_eye"])["unity"];
            return new Vector3(Convert.ToSingle(eye[0]), Convert.ToSingle(eye[1]), Convert.ToSingle(eye[2])) - b.Blockout.Origin;
        }
    }
}
