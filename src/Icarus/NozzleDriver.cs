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
///
/// The actuation rides with the petals as art/blender/propulsion.py poses it (sync_ring_matrix, pivot): each link, rigid,
/// puts its eye on nozzle_sync_ring on a sphere round its petal's clevis eye; the eyes' slides along the ring's axis,
/// fitted by least squares, slide and tilt the ring. Each link and ram piece then turns about its eye, by the least
/// rotation from its rest aim, to point at its other eye. A link's clevis eye is twice its mesh's bounds centre: the
/// links are symmetric about their middles (propulsion.check_actuation).
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

    // An actuator piece turning about its eye (its origin) to aim at a point it does not ride.
    sealed class Aimed
    {
        public Transform Piece = null!;
        public Quaternion Rest;
        public Vector3 RestAim; // in its parent's frame
    }

    sealed class Link
    {
        public Aimed Aim = null!;
        public Transform Petal = null!;
        public Vector3 Clevis; // the petal's eye, in its hinge's frame
        public Vector3 Eye; // the ring's eye, in the ring's frame
        public float Length;
    }

    readonly List<Petal> petals = new();
    readonly List<Link> links = new();
    readonly List<(Aimed Cylinder, Aimed Rod)> rams = new();
    JetNozzle? nozzle;
    Transform? ring, thrust, sync;
    Vector3 syncPosition, axis;
    Quaternion syncRotation;
    float spread;

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

        FindActuation();
        IcarusPlugin.Log.Stage("nozzle", $"nozzle driver on {name}: {petals.Count} petals and seals, {links.Count} links, {rams.Count} rams");
    }

    void FindActuation()
    {
        Transform part = thrust!.parent;
        sync = part.Find("nozzle_sync_ring");
        if (sync == null)
        {
            IcarusPlugin.Log.Error("nozzle driver: missing nozzle_sync_ring; the actuation stays at its dry pose");
            return;
        }
        syncPosition = sync.localPosition;
        syncRotation = sync.localRotation;
        foreach (Transform child in sync)
        {
            if (child.name.StartsWith("nozzle_link_"))
            {
                Transform? petal = ring!.Find("nozzle_petal_" + child.name.Substring("nozzle_link_".Length));
                MeshFilter? mesh = child.GetComponent<MeshFilter>();
                if (petal == null || mesh == null || mesh.sharedMesh == null) continue;
                Vector3 clevis = child.TransformPoint(2f * mesh.sharedMesh.bounds.center);
                links.Add(new Link
                {
                    Aim = Rest(child, clevis),
                    Petal = petal,
                    Clevis = petal.InverseTransformPoint(clevis),
                    Eye = child.localPosition,
                    Length = Vector3.Distance(clevis, child.position),
                });
            }
            else if (child.name.StartsWith("nozzle_ram_") && child.name.EndsWith("_rod"))
            {
                Transform? cylinder = part.Find(child.name.Substring(0, child.name.Length - "_rod".Length) + "_cylinder");
                if (cylinder != null) rams.Add((Rest(cylinder, child.position), Rest(child, cylinder.position)));
            }
        }
        if (links.Count < 4)
        {
            IcarusPlugin.Log.Error($"nozzle driver: {links.Count} links on nozzle_sync_ring; the actuation stays at its dry pose");
            links.Clear();
            rams.Clear();
            sync = null;
            return;
        }
        // The ring's axis in its own frame: normal to the plane of its eyes, which sit round it at even angles.
        axis = Vector3.Cross(links[0].Eye, links[links.Count / 4].Eye).normalized;
        spread = 0f;
        foreach (Link link in links) spread += link.Eye.sqrMagnitude;
    }

    static Aimed Rest(Transform piece, Vector3 target) => new Aimed
    {
        Piece = piece,
        Rest = piece.localRotation,
        RestAim = piece.parent.InverseTransformPoint(target) - piece.localPosition,
    };

    static void Turn(Aimed aimed, Vector3 target)
    {
        Vector3 aim = aimed.Piece.parent.InverseTransformPoint(target) - aimed.Piece.localPosition;
        aimed.Piece.localRotation = Quaternion.FromToRotation(aimed.RestAim, aim) * aimed.Rest;
    }

    void PoseActuation()
    {
        if (sync == null) return;
        Transform part = sync.parent;
        Quaternion toRest = Quaternion.Inverse(syncRotation);
        float total = 0f;
        Vector3 tilt = Vector3.zero;
        foreach (Link link in links)
        {
            Vector3 clevis = toRest * (part.InverseTransformPoint(link.Petal.TransformPoint(link.Clevis)) - syncPosition);
            Vector3 d = link.Eye - clevis;
            float b = Vector3.Dot(d, axis);
            float root = Mathf.Sqrt(Mathf.Max(b * b - d.sqrMagnitude + link.Length * link.Length, 0f));
            float slide = Mathf.Abs(-b + root) < Mathf.Abs(-b - root) ? -b + root : -b - root;
            total += slide;
            tilt += link.Eye * slide;
        }
        tilt *= 2f / spread;
        sync.localPosition = syncPosition + syncRotation * (axis * (total / links.Count));
        sync.localRotation = syncRotation * Quaternion.FromToRotation(axis, (axis - tilt).normalized);
        foreach (Link link in links) Turn(link.Aim, link.Petal.TransformPoint(link.Clevis));
        foreach (var (cylinder, rod) in rams)
        {
            Turn(cylinder, rod.Piece.position);
            Turn(rod, cylinder.Piece.position);
        }
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
        PoseActuation();
    }
}
