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
    static readonly AccessTools.FieldRef<WeaponManager, Aircraft> AircraftOf = AccessTools.FieldRefAccess<WeaponManager, Aircraft>("aircraft");
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("damage-registrations", typeof(WeaponManager), nameof(WeaponManager.SpawnWeapons),
            postfix: AccessTools.Method(typeof(DamageRegistrations), nameof(AfterSpawnWeapons))),
    };

    internal static void Install(BepInEx.Configuration.ConfigFile config)
    {
        var reload = config.Bind("Diagnostics", "ReloadLoadout", 0,
            "Test support: raising it gives every Icarus this machine's server owns a fresh copy of its loadout, respawning its mounts");
        reload.SettingChanged += (_, _) => ReloadAll();
    }

    static void AfterSpawnWeapons(WeaponManager __instance)
    {
        Aircraft aircraft = AircraftOf(__instance);
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey) return;
        IcarusPlugin.Log.Info($"damage-registrations {aircraft.UniqueName}: {aircraft.damageables.Count} after a loadout spawn");
    }

    static void ReloadAll()
    {
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
