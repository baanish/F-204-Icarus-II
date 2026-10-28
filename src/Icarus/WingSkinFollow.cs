using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Draws each wing part that hangs off a wing box in its authored pose on the part it hangs from, while they are jointed:
/// every wing skin piece on its box, and the outer wing box on the inner one, with what rides the outer box (its skin
/// pieces, the aileron, the leading-edge flap, the nav lights and lenses, and the wingtip station with any store on it)
/// drawn on the outer box's drawn pose. Each is its own rigidbody on FixedJoints, and the joint solver lets a part drift
/// under load: at 9 g a skin drifted 4 to 5 mm off its box, showing the internals through it, and the outer box's tip
/// moved 4 to 6 mm off the inner box, opening a gap at the crank where the two meet. The tail cone draws the same way on
/// the aft core, with its rear skin panels on it, and the afterburner and the nozzle on the tail cone: the engine chain
/// hangs on the aft core (and the root) while the tail cone wraps it, and at 9 g under full afterburner the nozzle's fixed
/// shroud moved 17 mm off the tail cone's skin, which the tail cone's hot ring would show as a step. Every other fuselage
/// skin piece draws on the core it hangs on: in an 8.5 g pull they moved 1.4 to 3.5 mm off their cores, past the 2 mm a
/// seam between two pieces may open.
///
/// Only rendering moves. Each part's renderers, and its wingtip station, go under a transform of their own (a mover),
/// which this turns by the difference between the part's drawn and physical poses; its rigidbody, mass, joints,
/// colliders, lift normal, centre-of-mass marker and joint anchors stay where the game puts them, and so does a
/// surface's hinge where its lift normal rides it, so control surfaces and high-lift devices still turn their meshes.
/// The one collider that rides along is a store's on the wingtip station, which shares the store's transform, so a
/// store released there leaves from where it is drawn; on the fuselage, a subtree with a collider stays on its body, and the
/// nozzle's thrust transform (the JetNozzle's) stays put, so the thrust acts where the game puts it. Once one of the
/// joints that hold a part where it is drawn breaks (its own to its parent; for the afterburner and nozzle, every joint
/// from them down the engine chain to the aft core, and the tail cone's), or a part on it detaches, it draws on its own
/// body again, and whatever hangs off it draws on that, so a shed wing or tail cone falls as before. Simple physics
/// merges every part onto one body, which leaves nothing to drift; there everything draws on its own body. The drawn
/// pose is composed from world poses each frame, so far from the world origin it is as exact as float32 positions
/// there, the floor every separate body in the game shares (millimetres at 77 km, micrometres near the origin).
/// </summary>
static class WingSkinFollow
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("wing-skin-follow", typeof(Aircraft), nameof(Aircraft.SetComplexPhysics),
            prefix: AccessTools.Method(typeof(WingSkinFollow), nameof(BeforeComplexPhysics))),
    };

    static void BeforeComplexPhysics(Aircraft __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("wing-skin-follow") || __instance.definition == null ||
            __instance.definition.jsonKey != IcarusPlugin.JsonKey || __instance.GetComponent<WingDraw>() != null) return;
        __instance.gameObject.AddComponent<WingDraw>().Begin(__instance);
    }
}

sealed class WingDraw : MonoBehaviour
{
    static readonly AccessTools.FieldRef<UnitPart, DamageMaterial> DamageOf = AccessTools.FieldRefAccess<UnitPart, DamageMaterial>("damageMaterial");
    static readonly AccessTools.FieldRef<AeroPart, Transform> LiftNormalOf = AccessTools.FieldRefAccess<AeroPart, Transform>("liftNormal");
    static readonly AccessTools.FieldRef<UnitPart, Transform> CentreOf = AccessTools.FieldRefAccess<UnitPart, Transform>("centerOfMass");

    sealed class Follower
    {
        public AeroPart Part = null!, Leader = null!;
        public Follower? LeaderFollower;
        public (AeroPart Part, AeroPart To)[] Holds = null!;  // the joints that must stand for the part to draw on its leader
        public AeroPart Against = null!;        // the part its seam is reported against, drawn where that is a follower too
        public Follower? AgainstFollower;
        public string Kind = null!;
        public Vector3 RestPosition;            // the part's pose in its leader's frame as authored
        public Quaternion RestRotation;
        public (Transform Parent, Transform Mover)[] Groups = null!;
        public Transform Reference = null!;     // a drawn transform: its rest in Against's frame, its place on the part
        public Vector3 ReferenceRest, ReferenceLocal;
        public bool Released;
        public Vector3 DrawnPosition;
        public Quaternion DrawnRotation;
    }

    Aircraft aircraft = null!;
    readonly List<Follower> followers = new();
    float reportAt;

    internal void Begin(Aircraft owner)
    {
        aircraft = owner;
        AeroPart[] parts = IcarusSystems.Parts(aircraft);
        var physics = new HashSet<Transform>(parts.SelectMany(p => new[] { LiftNormalOf(p), CentreOf(p) }
            .Concat(p.Joints.Select(j => j.anchor))).Concat(aircraft.GetComponentsInChildren<JetNozzle>(true).Select(n => n.transform)).Where(t => t != null));
        foreach (string side in new[] { "L", "R" })
        {
            AeroPart? inner = parts.FirstOrDefault(p => p.name == "wing_spar_" + side);
            AeroPart? outer = parts.FirstOrDefault(p => p.name == "wing_spar_outer_" + side);
            if (inner == null) continue;
            // the outer box on the inner first, then the skins on either box and every other part hung on the outer box
            var chain = (outer != null && LeaderOf(outer) == inner ? new[] { outer } : new AeroPart[0])
                .Concat(parts.Where(p => p.name.StartsWith("wing_skin_") && p.name.EndsWith("_" + side) && (LeaderOf(p) == inner || LeaderOf(p) == outer)))
                .Concat(parts.Where(p => outer != null && p != outer && !p.name.StartsWith("wing_skin_") && LeaderOf(p) == outer)).ToArray();
            var mine = new Dictionary<AeroPart, Follower>();
            foreach (AeroPart part in chain)
            {
                AeroPart leader = LeaderOf(part)!;
                Follow(part, leader, mine, new[] { (part, leader) }, inner, null, part.name.StartsWith("wing_skin_") ? "wing-skin-" : "wing-draw-", physics, false);
            }
        }

        // each fuselage skin piece on the core it hangs on (the tail cone's draw with the tail cone, below)
        foreach (AeroPart piece in parts.Where(p => p.name.StartsWith("skin_") || p.name.StartsWith("dorsal_cover")))
        {
            AeroPart? on = LeaderOf(piece);
            // the root (fuselage_mid) is the aircraft's own object, named for the aircraft
            if (on != null && (on.gameObject == aircraft.gameObject || on.name.StartsWith("fuselage_") && on.name != "fuselage_tail"))
                Follow(piece, on, new Dictionary<AeroPart, Follower>(), new[] { (piece, on) }, on, null, "skin-draw-", physics, true);
        }

        // the tail cone on the aft core with what hangs on it, then the afterburner and the nozzle on the tail cone
        AeroPart? Named(string n) => parts.FirstOrDefault(p => p.name == n);
        AeroPart? aft = Named("fuselage_aft"), tail = Named("fuselage_tail"), core = Named("engine_core"), afterburner = Named("engine_afterburner"), nozzle = Named("nozzle");
        if (aft == null || tail == null || LeaderOf(tail) != aft) return;
        var drawn = new Dictionary<AeroPart, Follower>();
        Follower? cone = Follow(tail, aft, drawn, new[] { (tail, aft) }, aft, null, "tail-draw-", physics, true);
        if (cone == null) return;
        foreach (AeroPart rider in parts.Where(p => LeaderOf(p) == tail))
            Follow(rider, tail, drawn, new[] { (rider, tail) }, tail, cone, "tail-draw-", physics, true);
        if (core == null || afterburner == null || LeaderOf(core) != aft || LeaderOf(afterburner) != core) return;
        var engine = new[] { (afterburner, core), (core, aft), (tail, aft) };
        Follow(afterburner, tail, drawn, engine, tail, cone, "tail-draw-", physics, true);
        if (nozzle != null && LeaderOf(nozzle) == afterburner)
            Follow(nozzle, tail, drawn, engine.Prepend((nozzle, afterburner)).ToArray(), tail, cone, "tail-draw-", physics, true);
    }

    static AeroPart? LeaderOf(AeroPart p) => p.Joints.Length > 0 ? p.Joints[0].connectedPart as AeroPart : null;

    // Draws part on leader (drawn itself where it is in mine) while every joint in holds stands; its seam is reported
    // against against (drawn where againstFollower is given). keepColliders leaves any subtree with a collider on its body.
    Follower? Follow(AeroPart part, AeroPart leader, Dictionary<AeroPart, Follower> mine, (AeroPart, AeroPart)[] holds,
        AeroPart against, Follower? againstFollower, string kind, HashSet<Transform> physics, bool keepColliders)
    {
        MoveRootRenderer(part);
        var groups = new List<(Transform, Transform)>();
        Collect(part.transform, physics, groups, keepColliders);
        if (groups.Count == 0) return null;
        var (restPosition, restRotation) = Between(part.transform, leader.transform);
        var f = new Follower
        {
            Part = part, Leader = leader, LeaderFollower = mine.TryGetValue(leader, out var lf) ? lf : null, Holds = holds,
            Against = against, AgainstFollower = againstFollower, Kind = kind,
            RestPosition = restPosition, RestRotation = restRotation, Groups = groups.ToArray(),
        };
        // the wingtip station where there is one, the tip a crank seam opens most at, else the first drawn child
        f.Reference = f.Groups.SelectMany(g => g.Item2.Cast<Transform>()).FirstOrDefault(t => t.name.StartsWith("hardpoint_wingtip_"))
                      ?? f.Groups[0].Item2.GetChild(0);
        f.ReferenceRest = Between(f.Reference, against.transform).Position;
        f.ReferenceLocal = Relative(f.Reference, part.transform).Position;
        mine[part] = f;
        followers.Add(f);
        IcarusPlugin.Log.Info($"{kind.TrimEnd('-')} authored: {part.name} on {leader.name}, {f.Groups.Sum(g => g.Item2.childCount)} draw roots; " +
            $"offset={f.RestPosition.ToString("F6")} rotation={f.RestRotation.ToString("F6")}");
        return f;
    }

    // t's pose in other's frame, through their nearest common ancestor, each leg composed from local poses (Relative).
    static (Vector3 Position, Quaternion Rotation) Between(Transform t, Transform other)
    {
        Transform? common = other;
        while (common != null && !t.IsChildOf(common)) common = common.parent;
        if (common == null) return (other.InverseTransformPoint(t.position), Quaternion.Inverse(other.rotation) * t.rotation);
        var (tp, tr) = Relative(t, common);
        var (op, or) = Relative(other, common);
        Quaternion back = Quaternion.Inverse(or);
        return (back * (tp - op), back * tr);
    }

    // t's pose in ancestor's frame, composed from the local poses between them. Before complex physics the parts are
    // nested as authored, and their local poses hold their places exactly: world positions far from the origin round to
    // millimetres (float32 holds 7.8 mm at 77 km), which taken as a rest would draw a part that far off it for good.
    static (Vector3 Position, Quaternion Rotation) Relative(Transform t, Transform ancestor)
    {
        Vector3 position = Vector3.zero;
        Quaternion rotation = Quaternion.identity;
        for (Transform? at = t; at != ancestor; at = at.parent)
        {
            if (at == null) return (ancestor.InverseTransformPoint(t.position), Quaternion.Inverse(ancestor.rotation) * t.rotation);
            position = at.localPosition + at.localRotation * Vector3.Scale(at.localScale, position);
            rotation = at.localRotation * rotation;
        }
        return (position, rotation);
    }

    // Every child subtree of t that renders (or is a wingtip station) and holds nothing physics reads goes under a mover,
    // one per parent, made at identity, so locally nothing moves. A child that holds a physics transform (or, with
    // keepColliders, a collider) is entered instead, and another part's transform (parts are still nested until complex
    // physics unparents them) is left alone, as is a collider's own transform with keepColliders.
    static void Collect(Transform t, HashSet<Transform> physics, List<(Transform, Transform)> groups, bool keepColliders)
    {
        Transform? mover = null;
        foreach (Transform child in t.Cast<Transform>().ToArray())
        {
            if (child.GetComponent<UnitPart>() != null) continue;
            if (child.GetComponentsInChildren<Transform>(true).Any(physics.Contains) ||
                keepColliders && child.GetComponentsInChildren<Collider>(true).Length > 0)
            {
                if (!keepColliders || child.GetComponent<Collider>() == null) Collect(child, physics, groups, keepColliders);
                continue;
            }
            if (child.GetComponentsInChildren<Renderer>(true).Length == 0 && !child.name.StartsWith("hardpoint_")) continue;
            if (mover == null)
            {
                mover = new GameObject(t.name + "_drawn") { layer = t.gameObject.layer }.transform;
                mover.SetParent(t, false);
                groups.Add((t, mover));
            }
            child.SetParent(mover, false);
        }
    }

    // The part's own renderer shares its rigidbody's transform. Give only its mesh a child transform, keeping the same
    // material instances and the game's damage and distance-visibility ownership.
    static void MoveRootRenderer(AeroPart part)
    {
        MeshRenderer source = part.GetComponent<MeshRenderer>();
        MeshFilter filter = part.GetComponent<MeshFilter>();
        if (source == null || filter == null) return;
        Transform child = new GameObject(part.name + "_mesh") { layer = part.gameObject.layer }.transform;
        child.SetParent(part.transform, false);
        child.gameObject.AddComponent<MeshFilter>().sharedMesh = filter.sharedMesh;
        MeshRenderer target = child.gameObject.AddComponent<MeshRenderer>();
        target.sharedMaterials = source.sharedMaterials;
        target.enabled = source.enabled;
        target.shadowCastingMode = source.shadowCastingMode;
        target.receiveShadows = source.receiveShadows;
        target.lightProbeUsage = source.lightProbeUsage;
        target.reflectionProbeUsage = source.reflectionProbeUsage;
        target.probeAnchor = source.probeAnchor;
        MaterialPropertyBlock properties = new();
        source.GetPropertyBlock(properties);
        target.SetPropertyBlock(properties);
        DamageMaterial damage = DamageOf(part);
        for (int i = 0; i < damage.renderers.Count; i++)
            if (damage.renderers[i] == source) damage.renderers[i] = target;
        LODGroup group = part.GetComponent<LODGroup>();
        if (group != null)
        {
            LOD[] levels = group.GetLODs();
            foreach (LOD level in levels)
                for (int i = 0; i < level.renderers.Length; i++)
                    if (level.renderers[i] == source) level.renderers[i] = target;
            group.SetLODs(levels);
        }
        source.enabled = false;
        Destroy(source);
        Destroy(filter);
    }

    void LateUpdate()
    {
        if (aircraft == null) return;
        foreach (Follower f in followers)
        {
            if (f.Part == null) continue;
            Transform part = f.Part.transform;
            bool simple = f.Part.rb == null || f.Part.rb == aircraft.rb;
            if (!f.Released && !simple && (f.Leader == null || f.Leader.IsDetached() || f.Holds.Any(h => h.Part == null || h.To == null ||
                    h.Part.IsDetached() || h.To.IsDetached() || !h.Part.Joints.Any(j => j.connectedPart == h.To && j.joint != null))))
            {
                f.Released = true;
                IcarusPlugin.Log.Info($"{f.Kind.TrimEnd('-')} released: {f.Part.name}; draws on its own body");
            }
            if (f.Released || simple)
            {
                f.DrawnPosition = part.position;
                f.DrawnRotation = part.rotation;
            }
            else
            {
                Follower? lead = f.LeaderFollower;
                Vector3 leaderPosition = lead != null ? lead.DrawnPosition : f.Leader!.transform.position;
                Quaternion leaderRotation = lead != null ? lead.DrawnRotation : f.Leader!.transform.rotation;
                f.DrawnPosition = leaderPosition + leaderRotation * f.RestPosition;
                f.DrawnRotation = leaderRotation * f.RestRotation;
            }
            // the rigid move that takes the part's physical pose to its drawn one, applied at each mover's parent
            Quaternion turn = f.DrawnRotation * Quaternion.Inverse(part.rotation);
            foreach (var (parent, mover) in f.Groups)
            {
                if (parent == null || mover == null) continue;
                mover.localPosition = parent.InverseTransformPoint(f.DrawnPosition + turn * (parent.position - part.position));
                mover.localRotation = Quaternion.Inverse(parent.rotation) * turn * parent.rotation;
            }
        }
        if (Time.time < reportAt || !IcarusPlugin.Log.StageEnabled) return;
        reportAt = Time.time + 1f;
        float load = Vector3.Dot(aircraft.accel + Vector3.up, aircraft.transform.up);
        foreach (Follower f in followers)
        {
            // simple physics draws every part on the one body: nothing to report
            if (f.Part == null || f.Against == null || f.Reference == null || f.Part.rb == null || f.Part.rb == aircraft.rb) continue;
            Transform against = f.Against.transform;
            // drawn: how far the drawn reference sits off its rest in Against's drawn frame; physical: the part's body's in
            // Against's body's
            Follower? on = f.AgainstFollower;
            Vector3 drawnAt = on != null ? on.DrawnPosition : against.position;
            Quaternion drawnTurn = on != null ? on.DrawnRotation : against.rotation;
            float drawn = (Quaternion.Inverse(drawnTurn) * (f.Reference.position - drawnAt) - f.ReferenceRest).magnitude * 1000f;
            float physical = (against.InverseTransformPoint(f.Part.transform.TransformPoint(f.ReferenceLocal)) - f.ReferenceRest).magnitude * 1000f;
            string kind = f.Kind;
            // the spacing of float32 world positions where Against is, the finest any two bodies can be drawn apart
            Vector3 at = against.position;
            float far = Mathf.Max(Mathf.Abs(at.x), Mathf.Abs(at.y), Mathf.Abs(at.z));
            float ulp = (System.BitConverter.Int32BitsToSingle(System.BitConverter.SingleToInt32Bits(far) + 1) - far) * 1000f;
            IcarusPlugin.Log.Stage(kind + f.Part.name, $"g={load:F3} physical_mm={physical:F4} attached={!f.Released} drawn_mm={drawn:F4} ulp_mm={ulp:F4}");
        }
    }
}
