using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Fits other weapon packs' mounts, the Aryx Weaponry Pack's and Meridian Works', to the Icarus's stations as they spawn,
/// on every peer: the packs' assets are not this mod's to change.
/// <list type="bullet">
/// <item>Conformal: a pack mount hangs its missile from a pylon; on a conformal hardpoint the pylon is hidden, the missile
/// hangs at the trough's depth and pitch, and it ejects straight down before its motor lights, as the Icarus's own
/// conformal mounts do (IcarusAuthor.AuthorConformalMounts). tools/stores/geometry.py CONFORMAL_SEATS repeats the seats.</item>
/// <item>Wingtip: Meridian Works lifts each of its mounts along the mount's +Y to close a gap to the skin above it. On the
/// Icarus's rolled tip hardpoints +Y points inboard, so the lift (0.05 to 0.085 m) drives the rail into the nav lamps; the
/// mount's pieces go back where its prefab places them, which is where tools/store_clearance.py checks them.</item>
/// </list>
/// </summary>
static class PackMountFit
{
    const string Feature = "pack-mount-fit";
    const float PitchDeg = 0.5f, EjectLength = 1.5f, EjectSpeed = 6f; // IcarusAuthor.Stations.cs, art/blender/stations.py

    // By the pack's mount key: the missile's origin in the hardpoint frame (m; +y up, +z forward) and the radius (m) of
    // its capsule, where it has one. The origin puts the body 0.033 m under the trough ceiling, as stations.py's
    // mount_frame does: y = -0.033 - radius - z tan(pitch), the radius being the body's without its fins (the AGR-37's
    // and AGM-58's are their widest rings, 0.152 m and 0.104 m). The AAM-63, 3.6 m long, sits as far forward as the
    // trough runs, which keeps its tail 0.05 m off the main gear door (Stores rule 12).
    static readonly Dictionary<string, (Vector3 Origin, float Capsule)> Seats = new()
    {
        ["Aryx_SRIRM1_Single"] = (new Vector3(0f, -0.1017f, -0.15f), 0.07f),
        ["Aryx_HeavyRocket1_x1"] = (new Vector3(0f, -0.1867f, 0.2f), 0.1015f),
        ["MeridianSRM8_single"] = (new Vector3(0f, -0.1206f, 0.18f), 0.086f),
        ["MeridianSRM20_single"] = (new Vector3(0f, -0.1176f, 0.18f), 0.083f),
        ["MeridianAAM63_single"] = (new Vector3(0f, -0.1405f, 0.29f), 0.105f),
        ["MeridianJackal_single"] = (new Vector3(0f, -0.1386f, 0.18f), 0.104f),
        ["MeridianAGM58F_single"] = (new Vector3(0f, -0.1296f, 0.18f), 0.095f),
        ["MeridianBlackArrow_single"] = (new Vector3(0f, -0.1356f, 0.18f), 0.101f),
    };

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(Hardpoint), nameof(Hardpoint.SpawnMount), new[] { typeof(Aircraft), typeof(WeaponMount) },
            postfix: AccessTools.Method(typeof(PackMountFit), nameof(AfterSpawnMount))),
    };

    // After Meridian Works' own patch of the same method, which moves and dresses every piece of its mounts as they spawn.
    [HarmonyAfter("com.meridianworks")]
    static void AfterSpawnMount(Hardpoint __instance, Aircraft aircraft, WeaponMount weaponMount, GameObject __result)
    {
        if (IcarusPlugin.FeaturesOff.Contains(Feature) || __result == null || weaponMount == null || aircraft == null ||
            aircraft.definition == null || aircraft.definition.jsonKey != IcarusPlugin.JsonKey || __instance.transform == null) return;
        if (__instance.transform.name.StartsWith("hardpoint_wingtip") && weaponMount.jsonKey.StartsWith("Meridian") && weaponMount.prefab != null)
        {
            var moved = 0f;
            foreach (Transform piece in __result.transform)
                if (weaponMount.prefab.transform.Find(piece.name) is Transform authored)
                {
                    moved = Mathf.Max(moved, Vector3.Distance(piece.localPosition, authored.localPosition));
                    piece.localPosition = authored.localPosition;
                }
            if (IcarusPlugin.Log.StageEnabled)
                IcarusPlugin.Log.Stage(Feature, $"{weaponMount.jsonKey} on {__instance.transform.name} put back {moved:0.000} m to its prefab place", everyOccurrence: true);
            return;
        }
        if (!Seats.TryGetValue(weaponMount.jsonKey, out var seat) || !__instance.transform.name.StartsWith("hardpoint_conformal")) return;
        foreach (MountedMissile missile in __result.GetComponentsInChildren<MountedMissile>(true))
        {
            Traverse rail = Traverse.Create(missile);
            Traverse direction = rail.Field("railDirection"), length = rail.Field("railLength"), speed = rail.Field("railSpeed"), delay = rail.Field("railDelay");
            if (!direction.FieldExists() || !length.FieldExists() || !speed.FieldExists() || !delay.FieldExists())
            {
                // Left on its pylon: hung in the trough it would light its motor against the belly.
                IcarusPlugin.Log.Warning($"{weaponMount.jsonKey} stays on its pylon: MountedMissile has no rail fields to eject it from the trough");
                return;
            }
            foreach (Transform piece in __result.transform)
                if (piece != missile.transform) piece.gameObject.SetActive(false);
            missile.transform.localPosition = seat.Origin;
            missile.transform.localRotation = Quaternion.Euler(PitchDeg, 0f, 0f); // +x turns the nose down
            if (missile.TryGetComponent(out CapsuleCollider capsule)) capsule.radius = seat.Capsule;
            direction.SetValue(MountedMissile.RailDirection.Down);
            length.SetValue(EjectLength);
            speed.SetValue(EjectSpeed);
            delay.SetValue(0f);
            if (IcarusPlugin.Log.StageEnabled)
            {
                Vector3 local = aircraft.transform.InverseTransformPoint(missile.transform.position);
                IcarusPlugin.Log.Stage(Feature, $"{weaponMount.jsonKey} seated on {__instance.transform.name} at ({local.x:0.000}, {local.y:0.000}, {local.z:0.000})", everyOccurrence: true);
            }
        }
    }
}
