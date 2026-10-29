using System.Linq;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.Networking;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Fun.HelipadSpawn (off by default): a player may spawn the Icarus on a helipad, standing on its tail with the gear up,
/// and full afterburner launches it straight up. The spawn is decided where the game spawns aircraft (the host), so the
/// host's setting rules; every peer draws a helipad Icarus upright whatever its own setting. AI never spawns there.
/// </summary>
static class HelipadLaunch
{
    const string Feature = "helipad-launch";

    static ConfigEntry<bool> allow = null!;

    internal static void Install(ConfigFile config) =>
        allow = config.Bind("Fun", "HelipadSpawn", false,
            "Lets you spawn the Icarus on helipads, standing on its tail with the gear up. Full afterburner launches it " +
            "straight up like a rocket. This is for the memes and obviously not balanced. Players only: the AI never " +
            "spawns there. Don't use it in multiplayer: the host's setting decides who may spawn there, and a joining " +
            "player's Icarus breaks apart on the pad as it spawns.");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(Hangar), nameof(Hangar.GetAvailableAircraft),
            postfix: AccessTools.Method(typeof(HelipadLaunch), nameof(AfterAvailable))),
        new(Feature, typeof(Hangar), nameof(Hangar.CanSpawnAircraft),
            postfix: AccessTools.Method(typeof(HelipadLaunch), nameof(AfterCanSpawn))),
        new(Feature, typeof(Hangar), nameof(Hangar.TrySpawnAircraft),
            prefix: AccessTools.Method(typeof(HelipadLaunch), nameof(BeforeTrySpawn))),
        new(Feature, typeof(Spawner), nameof(Spawner.SpawnAircraft),
            prefix: AccessTools.Method(typeof(HelipadLaunch), nameof(BeforeSpawn))),
        new(Feature, typeof(Aircraft), "OnStartClient",
            postfix: AccessTools.Method(typeof(HelipadLaunch), nameof(AfterStartClient))),
    };

    static bool Patched => !IcarusPlugin.FeaturesOff.Contains(Feature);
    static bool Enabled => Patched && allow.Value;
    static bool IsPad(Hangar hangar) => hangar != null && hangar.GetUnit().definition.code == "HPAD";
    static bool IsIcarus(AircraftDefinition definition) => definition != null && definition.jsonKey == IcarusPlugin.JsonKey;

    static void AfterAvailable(Hangar __instance, ref AircraftDefinition[] __result)
    {
        if (!Enabled && IsPad(__instance))
            __result = __result.Where(d => !IsIcarus(d)).ToArray();
    }

    static void AfterCanSpawn(Hangar __instance, AircraftDefinition definition, ref bool __result)
    {
        if (!Enabled && IsPad(__instance) && IsIcarus(definition)) __result = false;
    }

    // FactionHQ.DeployAIAircraft passes a null player through Airbase.TrySpawnAircraft.
    static bool BeforeTrySpawn(Hangar __instance, Player player, AircraftDefinition definition, ref Airbase.TrySpawnResult __result)
    {
        if (!IsPad(__instance) || !IsIcarus(definition) || (Enabled && player != null)) return true;
        __result = default;
        return false;
    }

    static void BeforeSpawn(Player player, GameObject prefab, Hangar spawningHangar,
        ref GlobalPosition globalPosition, ref Quaternion rotation, ref Vector3 startingVel)
    {
        if (!Enabled || player == null || !IsPad(spawningHangar)) return;
        var definition = prefab.GetComponent<Aircraft>().definition;
        if (!IsIcarus(definition)) return;
        var pad = spawningHangar.GetSpawnTransform();
        // SetRestPose derives length and spawnOffset.z from the same mesh bounds.
        // Negating their minimum z puts the rearmost visible point just above the pad.
        float tailHeight = definition.length * 0.5f + definition.spawnOffset.z + 0.05f;
        globalPosition = pad.GlobalPosition() + Vector3.up * tailHeight;
        rotation = Quaternion.LookRotation(Vector3.up, -pad.forward);
        startingVel = Vector3.zero;
    }

    static void AfterStartClient(Aircraft __instance)
    {
        // The host already allowed this spawn, so a peer with the setting off still draws it upright.
        if (!Patched || !IsIcarus(__instance.definition) || !IsPad(__instance.NetworkspawningHangar)) return;
        // The stock client reconstructs a horizontal pose from the hangar, ignoring startRotation.
        __instance.transform.SetPositionAndRotation(__instance.startPosition.ToLocalPosition(), __instance.startRotation);
        __instance.rb.position = __instance.transform.position;
        __instance.rb.rotation = __instance.transform.rotation;
        if (!__instance.LocalSim) return;
        __instance.SetGear(false);
        __instance.SetGear(LandingGear.GearState.LockedRetracted);
        __instance.GetInputs().throttle = 0;
        __instance.gameObject.AddComponent<HelipadLaunchHold>().Initialize(__instance);
    }
}

// The narrow tail is a launch stand: idle holds the body until full afterburner releases it.
sealed class HelipadLaunchHold : MonoBehaviour
{
    Aircraft aircraft = null!;
    RigidbodyConstraints constraints;

    internal void Initialize(Aircraft value)
    {
        aircraft = value;
        constraints = aircraft.rb.constraints;
        aircraft.rb.velocity = Vector3.zero;
        aircraft.rb.angularVelocity = Vector3.zero;
        aircraft.rb.constraints = RigidbodyConstraints.FreezeAll;
    }

    void FixedUpdate()
    {
        if (aircraft.GetInputs().throttle < 0.99f && !IcarusPlugin.FeaturesOff.Contains("helipad-launch") && !aircraft.disabled) return;
        aircraft.rb.constraints = constraints;
        Destroy(this);
    }
}
