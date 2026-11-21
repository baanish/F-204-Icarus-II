using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Logs how many damageables each Icarus has registered, at spawn and after every loadout spawn. Unit.RegisterDamageable
/// only appends, for the unit's whole life, and the damage and break messages address a part by its byte index in that
/// list, so the count must stay under 256 however often the jet is rearmed. [Diagnostics] ReloadLoadout, raised by a
/// test, hands the server's Icarus a fresh copy of its own loadout, which removes and respawns every mount as a rearm
/// with a loadout change does (WeaponManager.SpawnWeapons).
/// </summary>
static class DamageRegistrations
{
    // Resolved on the diagnostic's first run, not with PatchTargets: the plugin reads PatchTargets at startup, so a
    // field a game update renames would otherwise fail the type's initializer and stop the whole plugin loading.
    static AccessTools.FieldRef<WeaponManager, Aircraft>? aircraftOf;
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("damage-registrations", typeof(WeaponManager), nameof(WeaponManager.SpawnWeapons),
            postfix: AccessTools.Method(typeof(DamageRegistrations), nameof(AfterSpawnWeapons)), diagnostic: true),
    };

    internal static void Install(BepInEx.Configuration.ConfigFile config)
    {
        if (!IcarusPlugin.Log.StageEnabled) return;
        var reload = config.Bind("Diagnostics", "ReloadLoadout", 0,
            "Test support: raising it gives every Icarus this machine's server owns a fresh copy of its loadout, respawning its mounts");
        reload.SettingChanged += (_, _) => ReloadAll();
    }

    static void AfterSpawnWeapons(WeaponManager __instance)
    {
        if (!IcarusPlugin.Log.StageEnabled) return;
        aircraftOf ??= AccessTools.FieldRefAccess<WeaponManager, Aircraft>("aircraft");
        Aircraft aircraft = aircraftOf(__instance);
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey) return;
        IcarusPlugin.Log.Info($"damage-registrations {aircraft.UniqueName}: {aircraft.damageables.Count} after a loadout spawn");
    }

    static void ReloadAll()
    {
        if (!IcarusPlugin.Log.StageEnabled) return;
        Aircraft[] all = Object.FindObjectsOfType<Aircraft>();
        IcarusPlugin.Log.Info($"damage-registrations: reload requested, {all.Length} aircraft");
        foreach (Aircraft aircraft in all)
        {
            if (!aircraft.IsServer || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey ||
                aircraft.Networkloadout == null) continue;
            IcarusPlugin.Log.Info($"damage-registrations {aircraft.UniqueName}: {aircraft.damageables.Count} before a reload");
            aircraft.Networkloadout = new NuclearOption.SavedMission.Loadout { weapons = new(aircraft.Networkloadout.weapons) };
        }
    }
}
