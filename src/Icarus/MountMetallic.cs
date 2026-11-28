using UnityEngine;

namespace Icarus;

/// <summary>
/// The stock mount livery has no metallic map, so a mount drawn as part of the airframe takes the map BareMetalLivery
/// puts on the part's skin it sits on (the tail hook on its fin, the 25 mm pod body on the belly).
/// </summary>
sealed class MountMetallic : MonoBehaviour
{
    const float RefreshS = 0.5f;
    static readonly int MetallicId = Shader.PropertyToID("_Metallic");

    internal Renderer? Source;
    // The mount's renderers drawn on the airframe's atlas; every renderer of the mount when left unset.
    internal Renderer[]? Targets;
    MaterialPropertyBlock? block;
    Texture? applied;
    float next;

    void Start()
    {
        Targets ??= GetComponentsInChildren<Renderer>(true);
        block = new MaterialPropertyBlock();
    }

    void Update()
    {
        if (Time.time < next || Source == null || block == null) return;
        next = Time.time + RefreshS;
        Material livery = Source.sharedMaterial;
        if (Targets == null || livery == null || !livery.HasProperty(MetallicId) || livery.GetTexture(MetallicId) is not Texture metallic
            || metallic == applied) return;
        applied = metallic;
        foreach (Renderer renderer in Targets)
        {
            renderer.GetPropertyBlock(block);
            block.SetTexture(MetallicId, metallic);
            renderer.SetPropertyBlock(block);
        }
    }
}
