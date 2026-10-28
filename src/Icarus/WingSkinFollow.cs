using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Draws each wing skin in its authored pose on its spar while the two are jointed. The skin and the spar (ribs, spars and
/// both wing tanks) are separate rigidbodies on a FixedJoint, and the internals sit 1.3 to 2.2 mm under the skin; at 9 g
/// the joint lets the skin drift 4 to 5 mm, so the internals showed through the top of the wing. Only the skin's
/// renderers move: its rigidbody, mass, colliders and joint stay the game's, and once the joint breaks or either part
/// detaches the renderers return to the skin's own body so it tears off and falls as before.
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
            __instance.definition.jsonKey != IcarusPlugin.JsonKey) return;
        AeroPart[] parts = IcarusSystems.Parts(__instance);
        foreach (string side in new[] { "L", "R" })
        {
            AeroPart skin = parts.FirstOrDefault(p => p.name == "wing_skin_" + side);
            AeroPart spar = parts.FirstOrDefault(p => p.name == "wing_spar_" + side);
            if (skin == null || spar == null || skin.GetComponent<WingSkinPose>() != null) continue;
            skin.gameObject.AddComponent<WingSkinPose>().Begin(__instance, skin, spar);
        }
    }
}

sealed class WingSkinPose : MonoBehaviour
{
    static readonly AccessTools.FieldRef<UnitPart, DamageMaterial> DamageOf = AccessTools.FieldRefAccess<UnitPart, DamageMaterial>("damageMaterial");
    Aircraft aircraft = null!;
    AeroPart skin = null!, spar = null!;
    Vector3 restPosition;
    Quaternion restRotation;
    float reportAt;
    Transform[] visuals = null!;
    Vector3[] visualPositions = null!;
    Quaternion[] visualRotations = null!;
    bool released;

    internal void Begin(Aircraft owner, AeroPart panel, AeroPart structure)
    {
        aircraft = owner;
        skin = panel;
        spar = structure;
        restPosition = spar.transform.InverseTransformPoint(skin.transform.position);
        restRotation = Quaternion.Inverse(spar.transform.rotation) * skin.transform.rotation;
        MoveRootRenderer();
        visuals = skin.GetComponentsInChildren<MeshRenderer>(true)
            .Where(r => r.transform != skin.transform && r.GetComponentInParent<UnitPart>() == skin).Select(r => r.transform).Distinct().ToArray();
        visualPositions = visuals.Select(t => skin.transform.InverseTransformPoint(t.position)).ToArray();
        visualRotations = visuals.Select(t => Quaternion.Inverse(skin.transform.rotation) * t.rotation).ToArray();
        IcarusPlugin.Log.Info($"wing-skin authored: {skin.name} offset={restPosition.ToString("F6")} rotation={restRotation.ToString("F6")}");
    }

    // The authored renderer shares the rigidbody's transform. Give only its mesh a child transform,
    // retaining the same material instances and the game's damage and distance-visibility ownership.
    void MoveRootRenderer()
    {
        MeshRenderer source = skin.GetComponent<MeshRenderer>();
        MeshFilter filter = skin.GetComponent<MeshFilter>();
        if (source == null || filter == null) return;
        Transform child = new GameObject("wing_skin_visible") { layer = skin.gameObject.layer }.transform;
        child.SetParent(skin.transform, false);
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
        DamageMaterial damage = DamageOf(skin);
        for (int i = 0; i < damage.renderers.Count; i++)
            if (damage.renderers[i] == source) damage.renderers[i] = target;
        LODGroup group = skin.GetComponent<LODGroup>();
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
        if (skin == null) return;
        if (aircraft == null || spar == null || skin.rb == null || spar.rb == null)
        {
            Release();
            return;
        }
        if (!released && skin.rb == aircraft.rb && !skin.IsDetached() && !spar.IsDetached())
        {
            RestoreVisuals();
            return;
        }
        bool attached = !skin.IsDetached() && !spar.IsDetached() && skin.Joints.Any(j => j.connectedPart == spar && j.joint != null);
        Vector3 position = spar.transform.TransformPoint(restPosition);
        Quaternion rotation = spar.transform.rotation * restRotation;
        if (attached && !released)
        {
            for (int i = 0; i < visuals.Length; i++)
                if (visuals[i] != null)
                    visuals[i].SetPositionAndRotation(position + rotation * visualPositions[i], rotation * visualRotations[i]);
        }
        else if (!released)
        {
            Release();
        }
        if (Time.time < reportAt || !IcarusPlugin.Log.StageEnabled) return;
        reportAt = Time.time + 1f;
        Vector3 delta = Quaternion.Inverse(spar.rb.rotation) * (skin.rb.position - spar.rb.position) - restPosition;
        Quaternion rotationError = Quaternion.Inverse(restRotation) * Quaternion.Inverse(spar.rb.rotation) * skin.rb.rotation;
        float angle = 2f * Mathf.Atan2(new Vector3(rotationError.x, rotationError.y, rotationError.z).magnitude, Mathf.Abs(rotationError.w)) * Mathf.Rad2Deg;
        float drawnMm = visuals.Length == 0 ? float.NaN : Vector3.Distance(visuals[0].position, position + rotation * visualPositions[0]) * 1000f;
        float load = Vector3.Dot(aircraft.accel + Vector3.up, aircraft.transform.up);
        IcarusPlugin.Log.Stage("wing-skin-" + skin.name,
            $"g={load:F3} physical_mm={delta.magnitude * 1000f:F4} xyz_mm={(delta * 1000f).ToString("F4")} physical_deg={angle:F5} attached={attached} drawn_mm={drawnMm:F4}");
        if (released)
        {
            float bodyDrawnMm = visuals.Length == 0 ? float.NaN : Vector3.Distance(visuals[0].position, skin.transform.TransformPoint(visualPositions[0])) * 1000f;
            var global = skin.transform.GlobalPosition();
            IcarusPlugin.Log.Stage("wing-debris-" + skin.name,
                $"position=({global.x:F3}, {global.y:F3}, {global.z:F3}) velocity={skin.rb.velocity.ToString("F3")} body_drawn_mm={bodyDrawnMm:F4}");
        }
    }

    void RestoreVisuals()
    {
        for (int i = 0; i < visuals.Length; i++)
            if (visuals[i] != null)
                visuals[i].SetPositionAndRotation(skin.transform.TransformPoint(visualPositions[i]), skin.transform.rotation * visualRotations[i]);
    }

    void Release()
    {
        if (released) return;
        RestoreVisuals();
        released = true;
        IcarusPlugin.Log.Info($"wing-skin released: {skin.name}; renderer follows debris body");
    }
}
