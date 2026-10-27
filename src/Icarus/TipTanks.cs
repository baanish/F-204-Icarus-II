using System;
using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The tip tanks' fuel (art/blender/tip_tanks.py, IcarusAuthor.TipTanks.cs). Each tank is a store the game hangs and
/// releases like a bomb; its store mass is the full tank. While a tank hangs, this keeps the internal cells topped up from
/// it and moves the same mass from the tank's hardpoint to the cells, so the jet burns the tank first and its weight
/// follows the fuel; once the tanks run dry the internal fuel goes down. A release takes the full store mass off the wing
/// (MountedMissile.RemoveFromHardpoint), and this gives back what had already moved, so the jet sheds the shell and the
/// fuel left in it. This is the MiG-29 mods' ledger (.internal research R2); the internal cells stay stock.
///
/// The ledger runs where the aircraft is simulated (the owner: the player's own client, the host for AI), as the game's
/// own fuel burn does. Nothing of it is sent over the network: the tanks' presence and their release are the game's
/// networked store release (Aircraft.CmdLaunchMissile, RpcLaunchMissile), and the falling tank is a networked round.
/// Other peers' copies show the full store mass until the release, as with any stock store.
///
/// The fuel readouts (HUD gauge, status bar and warnings, the cockpit needle, the AI's fuel check) read
/// Aircraft.GetFuelLevel and GetFuelQuantity, which know only the internal cells: the patches add the tanks' fuel and
/// capacity while they hang. Firing one tank releases the other on the same station, so the pair goes together and the
/// jet never flies with one full tank on one tip. An AI-flown Icarus drops its tanks once they are dry.
///
/// Each tank's nav lenses show the state and colour of the wing lens beside them, and its skin takes the jet's livery.
/// </summary>
sealed class TipTanks : MonoBehaviour
{
    /// <summary>The round's UnitDefinition.jsonKey (IcarusAuthor.TipTankRound).</summary>
    const string RoundKey = "baanish_icarus_tip_tank_round";
    /// <summary>Fuel a tank holds, kg (art/blender/tip_tanks.py FUEL_KG: 170 US gal of jet fuel).</summary>
    internal const float FuelKg = 500f;
    /// <summary>kg/s into the internal cells: more than full afterburner burns, so the cells stay full while a tank has fuel.</summary>
    const float TransferRate = 30f;
    const float RefreshS = 0.5f, ReportS = 5f;
    // IcarusAuthor.TipTankLensPrefix: the tank's lenses, "top" and "bottom".
    const string LensPrefix = "tip_tank_lens_";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("tip-tanks", typeof(Aircraft), nameof(Aircraft.GetFuelLevel), Type.EmptyTypes,
            postfix: AccessTools.Method(typeof(TipTanks), nameof(AfterGetFuelLevel))),
        new("tip-tanks", typeof(Aircraft), nameof(Aircraft.GetFuelQuantity), Type.EmptyTypes,
            postfix: AccessTools.Method(typeof(TipTanks), nameof(AfterGetFuelQuantity))),
    };

    static readonly AccessTools.FieldRef<Weapon, Hardpoint> HardpointOf = AccessTools.FieldRefAccess<Weapon, Hardpoint>("hardpoint");
    static readonly AccessTools.FieldRef<FuelTank, UnitPart> CellPart = AccessTools.FieldRefAccess<FuelTank, UnitPart>("part");
    static readonly Dictionary<WeaponInfo, bool> IsTankInfo = new();
    static readonly int LiveryId = Shader.PropertyToID("_Livery"), GlossId = Shader.PropertyToID("_Glossiness"), MetallicId = Shader.PropertyToID("_Metallic");

    sealed class Tank
    {
        public Weapon Weapon = null!;
        public WeaponStation Station = null!;
        public string Side = "";
        public float Fuel, Moved;
        public bool Attached;
        public Renderer? Skin;
        public Renderer? Top, Bottom;
    }

    Aircraft aircraft = null!;
    readonly List<Tank> tanks = new();
    readonly MaterialPropertyBlock paint = new();
    float nextRefresh, nextReport;

    float External => tanks.Where(t => t.Attached).Sum(t => t.Fuel);
    float ExternalCapacity => tanks.Count(t => t.Attached) * FuelKg;

    void Start()
    {
        aircraft = GetComponent<Aircraft>();
        aircraft.OnRearmUnit += OnRearm;
    }

    void OnDestroy()
    {
        if (aircraft != null) aircraft.OnRearmUnit -= OnRearm;
    }

    static bool IsTank(WeaponInfo? info)
    {
        if (info == null) return false;
        if (!IsTankInfo.TryGetValue(info, out bool tank))
        {
            tank = info.weaponPrefab != null && info.weaponPrefab.TryGetComponent<Missile>(out var round)
                && round.definition != null && round.definition.jsonKey == RoundKey;
            IsTankInfo[info] = tank;
        }

        return tank;
    }

    void Refresh()
    {
        tanks.RemoveAll(t => t.Weapon == null);
        foreach (WeaponStation station in aircraft.weaponStations)
        {
            if (!IsTank(station.WeaponInfo)) continue;
            foreach (Weapon weapon in station.Weapons)
            {
                if (weapon == null || tanks.Exists(t => t.Weapon == weapon)) continue;
                bool attached = weapon.GetAmmoLoaded() > 0;
                Renderer[] lenses = weapon.GetComponentsInChildren<Renderer>(true);
                var tank = new Tank
                {
                    Weapon = weapon, Station = station, Attached = attached, Fuel = attached ? FuelKg : 0f,
                    Side = aircraft.transform.InverseTransformPoint(weapon.transform.position).x < 0 ? "L" : "R",
                    Skin = weapon.GetComponent<Renderer>(),
                    Top = lenses.FirstOrDefault(r => r.name == LensPrefix + "top"),
                    Bottom = lenses.FirstOrDefault(r => r.name == LensPrefix + "bottom"),
                };
                tanks.Add(tank);
                IcarusPlugin.Log.Stage("tip-tanks-" + tank.Side, $"tip tank {tank.Side} on {aircraft.persistentID}: attached {attached}, {tank.Fuel:0} kg, lenses {tank.Top != null && tank.Bottom != null}, local sim {aircraft.LocalSim}");
            }
        }

        Dress();
    }

    // Rearmed on the ground: a tank still hanging is full again (the game puts the full store mass back on a fired one;
    // one that never left gets back the mass it gave the cells).
    void OnRearm()
    {
        foreach (Tank t in tanks)
        {
            if (!t.Attached || t.Weapon == null) continue;
            ShiftStoreMass(t, t.Moved);
            t.Moved = 0f;
            t.Fuel = FuelKg;
        }
    }

    static void ShiftStoreMass(Tank t, float amount)
    {
        if (amount != 0f) HardpointOf(t.Weapon)?.ModifyMass(amount);
    }

    void FixedUpdate()
    {
        if (aircraft == null || !aircraft.LocalSim) return;
        if (Time.time >= nextRefresh)
        {
            nextRefresh = Time.time + RefreshS;
            Refresh();
        }

        if (tanks.Count == 0) return;
        bool released = false;
        foreach (Tank t in tanks)
        {
            bool attached = t.Weapon.GetAmmoLoaded() > 0;
            if (t.Attached && !attached)
            {
                // The game took the full store mass off the wing; what already went to the cells comes back.
                ShiftStoreMass(t, t.Moved);
                IcarusPlugin.Log.Stage("tip-tanks-release", $"tip tank {t.Side} released with {t.Fuel:0} kg; {t.Moved:0} kg had moved to the cells; mass {aircraft.GetMass():0} kg", everyOccurrence: true);
                t.Moved = 0f;
                t.Fuel = 0f;
                released = true;
            }
            else if (!t.Attached && attached)
            {
                t.Moved = 0f;
                t.Fuel = FuelKg; // hung again (rearm)
            }

            t.Attached = attached;
        }

        if (released) ReleasePairs();
        Transfer(Time.fixedDeltaTime);
        Report();
    }

    // The other tank of a station goes with the first, through the same networked release the trigger uses.
    void ReleasePairs()
    {
        foreach (var station in tanks.Where(t => t.Attached && tanks.Any(o => o.Station == t.Station && !o.Attached)).Select(t => t.Station).Distinct().ToArray())
        {
            station.LaunchMount(aircraft, null, aircraft.GlobalPosition() + aircraft.transform.forward * 1000f);
        }
    }

    void Transfer(float dt)
    {
        float external = External;
        if (external <= 0f) return;
        List<FuelTank> cells = aircraft.GetFuelTanks();
        float room = 0f;
        foreach (FuelTank cell in cells)
        {
            if (cell != null) room += Mathf.Max(0f, cell.GetCapacity() - cell.fuelMass);
        }

        float amount = Mathf.Min(room, external, TransferRate * dt);
        if (amount <= 0.0001f) return;
        foreach (FuelTank cell in cells)
        {
            if (cell == null) continue;
            float free = Mathf.Max(0f, cell.GetCapacity() - cell.fuelMass);
            if (free <= 0f) continue;
            float share = amount * free / room;
            cell.fuelMass += share;
            UnitPart part = CellPart(cell);
            if (part != null && part.rb != null) part.ModifyMass(share);
        }

        // Out of the tanks by what each holds, so a pair drains together.
        foreach (Tank t in tanks)
        {
            if (!t.Attached || t.Fuel <= 0f) continue;
            float share = amount * t.Fuel / external;
            t.Fuel -= share;
            t.Moved += share;
            ShiftStoreMass(t, -share);
        }
    }

    void Report()
    {
        if (Time.time < nextReport || ExternalCapacity <= 0f) return;
        nextReport = Time.time + ReportS;
        float cells = aircraft.GetFuelTanks().Sum(c => c == null ? 0f : c.fuelMass);
        IcarusPlugin.Log.Stage("tip-tanks-fuel", $"tip tanks {External:0} of {ExternalCapacity:0} kg, internal {cells:0} kg, fuel level {aircraft.GetFuelLevel():P1}, mass {aircraft.GetMass():0} kg");
    }

    void Update()
    {
        if (aircraft == null) return;
        if (!aircraft.LocalSim && Time.time >= nextRefresh)
        {
            nextRefresh = Time.time + RefreshS;
            Refresh();
        }

        if (!aircraft.LocalSim || !aircraft.IsServer || GameManager.IsLocalAircraft(aircraft)) return;
        // An AI-flown Icarus drops its tanks once they are dry; ReleasePairs takes the second of each pair.
        if (tanks.Any(t => t.Attached) && External < 1f)
        {
            foreach (WeaponStation station in tanks.Where(t => t.Attached).Select(t => t.Station).Distinct().ToArray())
            {
                if (!station.SafetyIsOn(aircraft)) station.LaunchMount(aircraft, null, aircraft.GlobalPosition() + aircraft.transform.forward * 1000f);
            }
        }
    }

    // Each hanging tank's lenses show the wing lens beside them (NavLights swaps that lens's material), and its skin the
    // livery the wing wears (UnitPart.SetLivery sets _Livery and _Glossiness, BareMetalLivery the _Metallic map).
    void Dress()
    {
        if (tanks.Count == 0) return;
        AeroPart[] parts = IcarusSystems.Parts(aircraft);
        foreach (Tank t in tanks)
        {
            if (!t.Attached) continue;
            AeroPart? wing = parts.FirstOrDefault(p => p != null && p.name == "wing_skin_" + t.Side);
            if (wing == null) continue;
            Renderer? upper = wing.transform.Find("navlight_" + t.Side)?.GetComponent<Renderer>();
            Renderer? lower = wing.transform.Find("navlight_lower_" + t.Side)?.GetComponent<Renderer>();
            if (t.Top != null && upper != null) t.Top.sharedMaterial = upper.sharedMaterial;
            if (t.Bottom != null && lower != null) t.Bottom.sharedMaterial = lower.sharedMaterial;
            Material? skin = wing.GetComponent<Renderer>()?.sharedMaterial;
            if (t.Skin == null || skin == null) continue;
            t.Skin.GetPropertyBlock(paint);
            if (skin.HasProperty(LiveryId) && skin.GetTexture(LiveryId) is Texture livery) paint.SetTexture(LiveryId, livery);
            if (skin.HasProperty(MetallicId) && skin.GetTexture(MetallicId) is Texture metallic) paint.SetTexture(MetallicId, metallic);
            if (skin.HasProperty(GlossId)) paint.SetFloat(GlossId, skin.GetFloat(GlossId));
            t.Skin.SetPropertyBlock(paint);
        }
    }

    static void AfterGetFuelLevel(Aircraft __instance, ref float __result)
    {
        if (!__instance.TryGetComponent<TipTanks>(out var t)) return;
        float extra = t.ExternalCapacity;
        if (extra <= 0f) return;
        float capacity = 0f;
        foreach (FuelTank cell in __instance.GetFuelTanks())
        {
            if (cell != null) capacity += cell.GetCapacity();
        }

        __result = (__result * capacity + t.External) / (capacity + extra);
    }

    static void AfterGetFuelQuantity(Aircraft __instance, ref float __result)
    {
        if (__instance.TryGetComponent<TipTanks>(out var t)) __result += t.External;
    }
}
