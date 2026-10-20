using System.Collections.Generic;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Opens the iris nozzle's petals with afterburner and deflects them with the thrust vector, on every peer: remote copies
/// rebuild their afterburner and vectoring state from networked inputs, so no extra messages are needed.
/// The authored prefab holds the petal and seal hinges under "nozzle_vector" at their dry pose, and the stock Turbojet
/// turns "thrust_vector" (which carries the JetNozzle and its thrust axis) for vectoring. Each hinge turns about its own
/// local X; which way opens is measured once from the petal's mesh, so the driver does not depend on the export's
/// handedness. Purely visual: forces stay with the JetNozzle.
/// </summary>
sealed class NozzleDriver : MonoBehaviour
{
    sealed class Petal
    {
        public Transform Hinge = null!;
        public Quaternion Rest;
        public Vector2 Radial; // unit, in the ring's plane
        public float OpenSign;
    }

    readonly List<Petal> petals = new();
    JetNozzle? nozzle;
    Transform? ring, thrust;

    void Start()
    {
        // The JetNozzle sits on thrust_vector and nozzle_vector beside it, both under the nozzle part, which complex
        // physics has unparented from the aircraft, so they are found from the engine's own reference.
        Turbojet? engine = IcarusSystems.Engine(GetComponent<Aircraft>());
        nozzle = engine == null ? null : IcarusSystems.Nozzle(engine);
        thrust = nozzle != null ? nozzle.transform : null;
        ring = thrust != null && thrust.parent != null ? thrust.parent.Find("nozzle_vector") : null;
        if (ring == null || thrust == null || nozzle == null)
        {
            IcarusPlugin.Log.Error($"nozzle driver: missing {(ring == null ? "nozzle_vector " : "")}{(thrust == null ? "thrust_vector " : "")}{(nozzle == null ? "JetNozzle" : "")}; petals stay at their dry pose");
            enabled = false;
            return;
        }

        foreach (Transform hinge in ring)
        {
            if (!hinge.name.StartsWith("nozzle_petal_") && !hinge.name.StartsWith("nozzle_seal_")) continue;
            MeshFilter? mesh = hinge.GetComponentInChildren<MeshFilter>();
            if (mesh == null || mesh.sharedMesh == null) continue;
            Vector3 centre = hinge.InverseTransformPoint(mesh.transform.TransformPoint(mesh.sharedMesh.bounds.center));
            var radial = new Vector2(hinge.localPosition.x, hinge.localPosition.y).normalized;
            Vector3 at = hinge.localRotation * centre;
            Vector3 turned = hinge.localRotation * Quaternion.AngleAxis(1f, Vector3.right) * centre;
            petals.Add(new Petal
            {
                Hinge = hinge,
                Rest = hinge.localRotation,
                Radial = radial,
                OpenSign = Vector2.Dot(new Vector2(turned.x - at.x, turned.y - at.y), radial) >= 0f ? 1f : -1f,
            });
        }

        IcarusPlugin.Log.Stage("nozzle", $"nozzle driver on {name}: {petals.Count} petals and seals");
    }

    void LateUpdate()
    {
        if (nozzle == null || ring == null || thrust == null)
        {
            enabled = false;
            return;
        }

        float max = nozzle.GetMaxThrust();
        float afterburner = max > 0f ? Mathf.Clamp01(nozzle.GetTotalThrust() / max) : 0f;
        float open = afterburner * Tuning.NozzleOpenDegrees;
        // The exhaust leaves along -Z of the ring at rest; its sideways part, in degrees, is how far the exit points away.
        Vector3 exhaust = ring.InverseTransformDirection(-thrust.forward);
        Vector2 deflection = new Vector2(exhaust.x, exhaust.y) * Mathf.Rad2Deg;
        foreach (Petal petal in petals)
        {
            // Every petal tip shifts toward the deflection: the petals on that side open, the far ones close.
            float angle = open + Vector2.Dot(petal.Radial, deflection);
            petal.Hinge.localRotation = petal.Rest * Quaternion.AngleAxis(petal.OpenSign * angle, Vector3.right);
        }
    }
}
