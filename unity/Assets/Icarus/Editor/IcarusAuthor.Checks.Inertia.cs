using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Debug = UnityEngine.Debug;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        private const float InertiaTensorLimit = 1e-4f, InertiaCenterLimitM = 1e-5f;

        // The game's changes to a core's body, in order: a new body (AeroPart.CreateRB, or the root's mass in
        // Aircraft.SetSimplePhysics), fuel in and out (UnitPart.ModifyMass sets the mass and the part's CoM),
        // Aircraft.SetComplexPhysics's centre reset, and a wheel breaking off (LandingGear.BreakWheel).
        private static readonly (string Name, Action<Rigidbody, Transform> Change)[] InertiaSteps =
        {
            ("created", (rb, com) => { }),
            ("fuel loaded", (rb, com) => { rb.mass *= 1.3f; rb.centerOfMass = com.localPosition; }),
            ("fuel burnt", (rb, com) => { rb.mass *= 0.9f; rb.centerOfMass = com.localPosition; }),
            ("centre reset", (rb, com) => rb.ResetCenterOfMass()),
            ("wheel lost", (rb, com) => rb.mass -= 50f),
        };

        // The cores' section boxes ship disabled (A19), and src/Icarus/SectionInertia.cs pins their bodies' mass properties
        // each step. Two copies of the aircraft take the game's changes: one with the boxes enabled, as they shipped before
        // and as Unity derives mass properties from them (the contract), and one with them disabled, pinned after each change
        // as the plugin does. Every core's body must match in mass, centre and full tensor, in complex physics (a body per
        // part) and simple (one body).
        private static string CheckSectionInertia(Build b, List<string> problems)
        {
            foreach (var core in StructureCores)
            {
                var own = SectionInertia.BoxesUnder(new[] { b.Parts[core].transform }).Where(c => c.transform.parent == b.Parts[core].transform).ToArray();
                if (own.Length != 1 || own[0].enabled || own[0].gameObject.layer != IgnoreCollisionsLayer)
                    problems.Add($"{core}: {own.Length} section boxes, expected one, disabled, on layer {IgnoreCollisionsLayer}");
            }
            var all = SectionInertia.BoxesUnder(new[] { b.Root.transform }).Length;
            if (all != StructureCores.Length)
                problems.Add($"{all} section boxes on the aircraft, expected {StructureCores.Length}");
            if (problems.Count > 0)
                return "section boxes misplaced";

            var states = 0;
            float worstTensor = 0, worstCenter = 0, unpinned = float.MaxValue;
            var micros = new List<string>();
            foreach (var merged in new[] { false, true })
            {
                var physics = merged ? "simple" : "complex";
                var scene = EditorSceneManager.NewPreviewScene();
                try
                {
                    var stock = InertiaCopy(b.Root, scene, merged, boxesEnabled: true, out _);
                    var ours = InertiaCopy(b.Root, scene, merged, boxesEnabled: false, out var boxes);
                    if (boxes.Length != StructureCores.Length || stock.Count != ours.Count || stock.Count != (merged ? 1 : StructureCores.Length))
                    {
                        problems.Add($"{physics}: {boxes.Length} boxes on {ours.Count} bodies, against {stock.Count} with boxes enabled");
                        continue;
                    }
                    var sections = ours[0].Body.gameObject.AddComponent<SectionInertia>();
                    sections.Boxes = boxes;
                    foreach (var step in InertiaSteps)
                    {
                        for (var i = 0; i < stock.Count; i++)
                        {
                            step.Change(stock[i].Body, stock[i].Com);
                            step.Change(ours[i].Body, ours[i].Com);
                        }
                        if (step.Name == "created")
                            for (var i = 0; i < stock.Count; i++)
                                unpinned = Mathf.Min(unpinned, TensorGap(stock[i].Body, ours[i].Body));
                        sections.PinAll();
                        if (sections.Boxes.Any(c => c.enabled))
                            problems.Add($"{physics} {step.Name}: a section box stays enabled after pinning");
                        for (var i = 0; i < stock.Count; i++)
                        {
                            Rigidbody want = stock[i].Body, got = ours[i].Body;
                            var tensor = TensorGap(want, got);
                            var center = Vector3.Distance(want.centerOfMass, got.centerOfMass);
                            worstTensor = Mathf.Max(worstTensor, tensor);
                            worstCenter = Mathf.Max(worstCenter, center);
                            var label = $"{physics} {stock[i].Name} {step.Name}";
                            Debug.Log($"[Icarus] inertia parity {label}: mass {want.mass:R}/{got.mass:R}, boxes enabled {want.inertiaTensor.ToString("F4")} {want.inertiaTensorRotation.ToString("F5")} centre {want.centerOfMass.ToString("F5")}, pinned {got.inertiaTensor.ToString("F4")} {got.inertiaTensorRotation.ToString("F5")} centre {got.centerOfMass.ToString("F5")}; tensor error {tensor:R}, centre error {center:R} m");
                            if (!(tensor <= InertiaTensorLimit) || !(center <= InertiaCenterLimitM) || want.mass != got.mass)
                                problems.Add($"{label}: relative tensor error {tensor:R}, centre error {center:R} m, mass {want.mass:R} against {got.mass:R}");
                            states++;
                        }
                    }
                    const int runs = 200;
                    var clock = Stopwatch.StartNew();
                    for (var i = 0; i < runs; i++)
                        sections.PinAll();
                    micros.Add($"{physics} {clock.Elapsed.TotalMilliseconds * 1000 / runs:0} us");
                }
                finally
                {
                    EditorSceneManager.ClosePreviewScene(scene);
                }
            }
            // The boxes must matter, or the comparison proves nothing.
            if (!(unpinned > 0.01f))
                problems.Add($"the boxes change a new core body's tensor by only {unpinned:R}");
            return $"{states} body states over {InertiaSteps.Length} game changes in complex and simple physics match the enabled boxes: "
                + $"worst tensor error {worstTensor:R} (limit {InertiaTensorLimit:R}), centre {worstCenter:R} m (limit {InertiaCenterLimitM:R}), mass equal; "
                + $"unpinned, the least tensor error is {unpinned:0.00}; a step's pinning takes {string.Join(", ", micros)} in the editor";
        }

        private sealed class InertiaBody
        {
            public string Name;
            public Rigidbody Body;
            public Transform Com;
        }

        // A copy of the aircraft with the bodies the game gives it: in complex physics every part leaves the hierarchy on a
        // body of its own with its own mass (AeroPart.CreateRB), in simple physics the root's body carries every part and the
        // dry mass (Aircraft.SetSimplePhysics). Returns the bodies holding a section box, in the same order for every copy.
        private static List<InertiaBody> InertiaCopy(GameObject root, Scene scene, bool merged, bool boxesEnabled, out BoxCollider[] boxes)
        {
            var copy = Object.Instantiate(root, Vector3.zero, Quaternion.identity);
            SceneManager.MoveGameObjectToScene(copy, scene);
            var parts = copy.GetComponentsInChildren(GameType("AeroPart"), true);
            foreach (var wheel in copy.GetComponentsInChildren<WheelCollider>(true))
                Object.DestroyImmediate(wheel);
            foreach (var extra in copy.GetComponentsInChildren<Rigidbody>(true).Where(r => r.gameObject != copy))
                Object.DestroyImmediate(extra);
            boxes = SectionInertia.BoxesUnder(parts);
            foreach (var box in boxes)
                box.enabled = boxesEnabled;
            if (!merged)
                foreach (var part in parts.Where(p => p.gameObject != copy))
                    part.transform.SetParent(null, true);
            Physics.SyncTransforms();
            var dry = parts.Sum(p => GetFloat(p, "mass"));
            var bodies = new List<InertiaBody>();
            foreach (var part in parts.Where(p => !merged || p.gameObject == copy))
            {
                if (!part.TryGetComponent<Rigidbody>(out var rb))
                    rb = part.gameObject.AddComponent<Rigidbody>();
                rb.useGravity = false;
                rb.mass = merged ? dry : GetFloat(part, "mass");
                rb.ResetCenterOfMass();
                rb.ResetInertiaTensor();
                if (SectionInertia.BoxesUnder(new[] { part }).Length > 0)
                    bodies.Add(new InertiaBody { Name = part.gameObject == copy ? RootPart : part.name, Body = rb, Com = (Transform)GetRef(part, "centerOfMass") });
            }
            return bodies;
        }

        // The largest difference between the two bodies' inertia matrices in the body frame, over the first's largest entry.
        private static float TensorGap(Rigidbody want, Rigidbody got)
        {
            Matrix4x4 Matrix(Rigidbody rb)
            {
                var r = Matrix4x4.Rotate(rb.inertiaTensorRotation);
                return r * Matrix4x4.Scale(rb.inertiaTensor) * r.transpose;
            }
            Matrix4x4 a = Matrix(want), c = Matrix(got);
            float error = 0, magnitude = 0;
            for (var i = 0; i < 3; i++)
                for (var j = 0; j < 3; j++)
                {
                    error = Mathf.Max(error, Mathf.Abs(a[i, j] - c[i, j]));
                    magnitude = Mathf.Max(magnitude, Mathf.Abs(a[i, j]));
                }
            return error / magnitude;
        }
    }
}
