using System;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The pilot's eye sits this far under the canopy's highest point, below it (art/blender/canopy.py EYE_BELOW_CROWN).
        private const float EyeBelowCanopyTop = 0.20f;

        // What the cockpit is fitted to: the pilot's eye and the windscreen frame the interior must sit behind, both in
        // prefab space, how the hood opens, and canopy renderers to hide in the cockpit view.
        private sealed class CanopyFit
        {
            public Vector3 Eye;
            public Bounds Sill;
            public float Open;
            public bool Kept;
            public Renderer[] Exterior = Array.Empty<Renderer>();
        }

        // The hood on its sill hinge, the windscreen and its frame. The Revoker canopy rig is gone; its Canopy opens the
        // Icarus hood on its hinge and ejects the canopy part.
        private static CanopyFit BuildCanopy(Build b)
        {
            var canopy = b.Parts["canopy"].transform;
            var (_, hood, glass) = HingeRig(b, "canopy", null, canopy);
            var cockpit = b.Parts["cockpit_cell"].transform;
            var windscreen = MeshVisual(b, "windscreen", cockpit);
            var bow = MeshVisual(b, "windscreen_frame", cockpit);
            var points = WorldVertices(glass.transform, b.Meshes["canopy_visible"].Render);
            var topY = points.Max(p => p.y);
            var crown = points.Where(p => p.y > topY - 0.01f).ToArray();
            var eye = new Vector3(0f, topY - EyeBelowCanopyTop, crown.Average(p => p.z));

            var (open, kept) = Travel(b, canopy, glass.bounds.center, "canopy", p => p.y); // the hood swings up
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
            SetList(Prop(so, "glassRenderers"), new Object[] { glass, windscreen });
            // Canopy pushes along its part's own forward and up (Canopy.cs FixedUpdate); the hood's hinge frame has up
            // pointing down into the cockpit, so the Revoker's push is re-expressed in that frame to point up out of it.
            var push = Vector3.up * Prop(so, "ejectionForce").vector3Value.magnitude;
            Prop(so, "ejectionForce").vector3Value = new Vector3(0f, Vector3.Dot(push, canopy.up), Vector3.Dot(push, canopy.forward));
            so.ApplyModifiedPropertiesWithoutUndo();

            var aircraft = new SerializedObject(b.Aircraft);
            SetList(Prop(aircraft, "canopies"), new Object[] { component });
            aircraft.ApplyModifiedPropertiesWithoutUndo();
            return new CanopyFit { Eye = eye, Sill = bow.bounds, Open = open, Kept = kept };
        }
    }
}
