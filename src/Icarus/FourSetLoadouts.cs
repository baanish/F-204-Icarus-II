using HarmonyLib;

namespace Icarus;

/// <summary>
/// Keeps the loadouts of missions saved before the Centreline set. Those list four Icarus hardpoint sets, the game reads
/// one mount per listed set (SavedLoadout.CreateLoadout), and WeaponManager.InitializeWeaponManager replaces a loadout
/// whose length is not the aircraft's set count with the default one, so the jet lost its authored stores. Just before
/// that comparison, on every peer, the missing Centreline entry is filled in empty, which is what the mission had when it
/// was saved.
/// </summary>
static class FourSetLoadouts
{
    const string Feature = "four-set-loadouts";
    const int SetsBeforeCentreline = 4;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(WeaponManager), nameof(WeaponManager.InitializeWeaponManager),
            prefix: AccessTools.Method(typeof(FourSetLoadouts), nameof(BeforeInitialize))),
    };

    static void BeforeInitialize(WeaponManager __instance, Aircraft ___aircraft)
    {
        if (IcarusPlugin.FeaturesOff.Contains(Feature) || ___aircraft == null || ___aircraft.definition == null ||
            ___aircraft.definition.jsonKey != IcarusPlugin.JsonKey || __instance.hardpointSets.Length != SetsBeforeCentreline + 1) return;
        var weapons = ___aircraft.loadout?.weapons;
        if (weapons == null || weapons.Count != SetsBeforeCentreline) return;
        weapons.Add(null);
        if (IcarusPlugin.Log.StageEnabled)
            IcarusPlugin.Log.Stage(Feature, "filled in an empty Centreline entry: " + string.Join("|", weapons.ConvertAll(m => m != null ? m.jsonKey : "")), everyOccurrence: true);
    }
}
