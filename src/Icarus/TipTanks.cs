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
        new("tip-tanks", typeof(Missile), "StartMissile", Type.EmptyTypes,
            postfix: AccessTools.Method(typeof(TipTanks), nameof(AfterStartMissile))),
        new("tip-tank-release", typeof(MountedMissile), nameof(MountedMissile.Fire),
            new[] { typeof(Unit), typeof(Unit), typeof(Vector3), typeof(WeaponStation), typeof(GlobalPosition) },
            prefix: AccessTools.Method(typeof(TipTanks), nameof(BeforeFire))),
        new("tip-tank-hud", typeof(CombatHUD), nameof(CombatHUD.ShowWeaponStation),
            postfix: AccessTools.Method(typeof(TipTanks), nameof(AfterShowWeaponStation))),
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
        public float Fuel, Moved, Returned;
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

    // The mass the cells took from the hardpoint goes back to it. The game's release takes the whole store mass off that
    // part (MountedMissile.Fire, through RemoveFromHardpoint) and sets its rigidbody to what is left with no floor, so with
    // the fuel already moved the part would go below zero and the solver would tear the jet apart: a tank released with
    // under about 130 kg left, on a 368 kg wing spar, did exactly that. Called before the game's subtraction.
    void ReturnMoved(Weapon weapon)
    {
        Tank? t = tanks.Find(x => x.Weapon == weapon);
        if (t == null || t.Moved == 0f) return;
        ShiftStoreMass(t, t.Moved);
        t.Returned = t.Moved;
        t.Moved = 0f;
        IcarusPlugin.Log.Stage("tip-tanks-return", $"tip tank {t.Side}: {t.Returned:0} kg given back to its hardpoint ahead of the release", everyOccurrence: true);
    }

    static void BeforeFire(MountedMissile __instance, Unit owner)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tip-tank-release") || owner == null) return;
        if (owner.TryGetComponent<TipTanks>(out var ledger)) ledger.ReturnMoved(__instance);
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
                // The game took the full store mass off the wing; what already went to the cells came back first (ReturnMoved).
                IcarusPlugin.Log.Stage("tip-tanks-release", $"tip tank {t.Side} released with {t.Fuel:0} kg; {t.Returned:0} kg had moved to the cells; mass {aircraft.GetMass():0} kg", everyOccurrence: true);
                t.Returned = 0f;
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
            if (t.Attached) DressStore(parts, t.Side, t.Skin, t.Top, t.Bottom, paint);
        }
    }

    static void DressStore(AeroPart[] parts, string side, Renderer? skin, Renderer? top, Renderer? bottom, MaterialPropertyBlock block)
    {
        AeroPart? wing = parts.FirstOrDefault(p => p != null && p.name == "wing_skin_" + side);
        if (wing == null) return;
        Renderer? upper = wing.transform.Find("navlight_" + side)?.GetComponent<Renderer>();
        Renderer? lower = wing.transform.Find("navlight_lower_" + side)?.GetComponent<Renderer>();
        if (top != null && upper != null) top.sharedMaterial = upper.sharedMaterial;
        if (bottom != null && lower != null) bottom.sharedMaterial = lower.sharedMaterial;
        Material? livery = wing.GetComponent<Renderer>()?.sharedMaterial;
        if (skin == null || livery == null) return;
        skin.GetPropertyBlock(block);
        if (livery.HasProperty(LiveryId) && livery.GetTexture(LiveryId) is Texture paint) block.SetTexture(LiveryId, paint);
        if (livery.HasProperty(MetallicId) && livery.GetTexture(MetallicId) is Texture metallic) block.SetTexture(MetallicId, metallic);
        if (livery.HasProperty(GlossId)) block.SetFloat(GlossId, livery.GetFloat(GlossId));
        skin.SetPropertyBlock(block);
    }

    // A released tank falls as its own round, a fresh copy of the round prefab the game spawns on every peer
    // (Spawner.SpawnMissile), not the store that hung: it takes the livery and lens state of the wing it left, as the
    // store had them. StartMissile runs on every peer once the round knows its owner.
    static void AfterStartMissile(Missile __instance)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tip-tanks") || __instance.definition == null || __instance.definition.jsonKey != RoundKey
            || __instance.owner is not Aircraft aircraft) return;
        string side = aircraft.transform.InverseTransformPoint(__instance.transform.position).x < 0 ? "L" : "R";
        Renderer[] renderers = __instance.GetComponentsInChildren<Renderer>(true);
        DressStore(IcarusSystems.Parts(aircraft), side, __instance.GetComponent<Renderer>(),
            renderers.FirstOrDefault(r => r.name == LensPrefix + "top"), renderers.FirstOrDefault(r => r.name == LensPrefix + "bottom"),
            new MaterialPropertyBlock());
        IcarusPlugin.Log.Stage("tip-tanks-round", $"tip tank round {side} from {aircraft.persistentID} dressed in the jet's livery", everyOccurrence: true);
    }

    // The tank is authored as a bomb (the game releases it like one), so the HUD would draw the bombing sight (pipper, fall
    // line, time of flight). A tank has nothing to aim: swap in the game's no-weapon state, as with no station selected.
    // WeaponInfo.bomb stays set: only this HUD choice and the AI's bombing mode read it, and the AI never picks a tank
    // (zero effectiveness against every role).
    static int hudSwaps;

    static void AfterShowWeaponStation(CombatHUD __instance, WeaponStation weaponStation, ref HUDWeaponState ___weaponState, GameObject ___NoWeaponUI)
    {
        if (IcarusPlugin.FeaturesOff.Contains("tip-tank-hud") || weaponStation == null || !IsTank(weaponStation.WeaponInfo)) return;
        ___weaponState.gameObject.SetActive(false);
        Destroy(___weaponState.gameObject);
        ___weaponState = Instantiate(___NoWeaponUI, SceneSingleton<FlightHud>.i.GetHUDCenter()).GetComponent<HUDWeaponState>();
        ___weaponState.SetHUDWeaponState(__instance.targetDesignator, __instance.aircraft, weaponStation);
        IcarusPlugin.Log.Stage("tip-tank-hud", $"tip tank selected, no weapon sight (selection {++hudSwaps})", everyOccurrence: true);
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
