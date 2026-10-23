using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The fuselage cores' whole-section boxes (IcarusAuthor.AddSectionInertia) ship disabled, because any enabled collider
/// is in the game's physics queries: off layer 13 it stops bullets (BulletSim), blast line of sight (Explosion) and lasers
/// without a damage receiver, and on layer 13 the AI's terrain checks (Autopilot) hit it. Each physics step this enables a
/// body's boxes just long enough for Unity to compute that body's automatic inertia tensor, and its centre of mass unless
/// the game set one (UnitPart.ModifyMass), then pins both explicitly, so the body keeps the mass properties the enabled
/// boxes gave it. Pinned values don't follow the game's later mass, centre and part changes, which is why it repeats
/// every step; a change made later in the same step waits one step. A20 replays those changes against enabled boxes.
/// </summary>
public sealed class SectionInertia : MonoBehaviour
{
    public const string BoxSuffix = "_inertia";

    public BoxCollider[] Boxes = Array.Empty<BoxCollider>();

    // The centre each body was last pinned with, and whether the game had set it.
    readonly Dictionary<Rigidbody, (Vector3 Center, bool GameSet)> pinned = new();
    readonly List<BoxCollider> group = new();
    Rigidbody?[] bodies = Array.Empty<Rigidbody?>();

    void FixedUpdate() => PinAll();

    /// <summary>The section boxes under these parts, each once.</summary>
    public static BoxCollider[] BoxesUnder(IEnumerable<Component> parts) =>
        parts.SelectMany(p => p.GetComponentsInChildren<BoxCollider>(true))
            .Where(c => c.name.EndsWith(BoxSuffix, StringComparison.Ordinal)).Distinct().ToArray();

    public void PinAll()
    {
        if (bodies.Length != Boxes.Length) bodies = new Rigidbody?[Boxes.Length];
        for (int i = 0; i < Boxes.Length; i++)
        {
            bodies[i] = Boxes[i] == null ? null : Boxes[i].GetComponentInParent<Rigidbody>();
        }

        for (int i = 0; i < Boxes.Length; i++)
        {
            Rigidbody? body = bodies[i];
            if (body == null || Array.IndexOf(bodies, body) < i) continue;
            group.Clear();
            for (int j = i; j < Boxes.Length; j++)
            {
                if (bodies[j] == body) group.Add(Boxes[j]);
            }

            bool gameSet = !body.automaticCenterOfMass
                && (!pinned.TryGetValue(body, out var last) || last.GameSet || body.centerOfMass != last.Center);
            Pin(body, group, automaticCenter: !gameSet);
            pinned[body] = (body.centerOfMass, gameSet);
        }
    }

    /// <summary>
    /// Unity's automatic tensor for the body with these boxes enabled, about its automatic centre or the one it has, held
    /// after the boxes are disabled again.
    /// </summary>
    public static void Pin(Rigidbody body, IReadOnlyList<BoxCollider> boxes, bool automaticCenter)
    {
        if (boxes.Count == 0) return;
        for (int i = 0; i < boxes.Count; i++) boxes[i].enabled = true;
        if (automaticCenter) body.ResetCenterOfMass();
        body.ResetInertiaTensor();
        Vector3 center = body.centerOfMass;
        Vector3 tensor = body.inertiaTensor;
        Quaternion rotation = body.inertiaTensorRotation;
        body.centerOfMass = center;
        body.inertiaTensor = tensor;
        body.inertiaTensorRotation = rotation;
        for (int i = 0; i < boxes.Count; i++) boxes[i].enabled = false;
    }
}
