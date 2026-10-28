using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.Networking;
using UnityEngine;
using static System.FormattableString;

namespace Icarus;

/// <summary>
/// Tuning v0: the flight-model scalars the game reads live (engine, afterburner, thrust vectoring, wing and drag area, AI
/// speeds), held in the [Tuning.*] sections of BepInEx/config/baanish.icarus.cfg and applied to every Icarus whenever the
/// file is saved or an entry changes in the configuration manager. A value below 0 means the shipped one, the value
/// authored into the prefab, captured from each aircraft before anything is applied and logged at its first sight.
/// While any remote peer is connected (hosting with a client in, or joining anyone) every knob reads its shipped value
/// on every machine, so peers fly the same aircraft. Mass, fuel, control ranges and airfoil curves are not live here.
/// </summary>
static class Tuning
{
    /// <summary>Degrees each petal opens at full afterburner; visual only, so it isn't locked to the shipped value.</summary>
    internal static float NozzleOpenDegrees => nozzleOpen == null ? DefaultNozzleOpen : nozzleOpen.Value;

    const float DefaultNozzleOpen = 15f;
    // The main wing's AeroParts whose area WingArea scales; the leading-edge and trailing-edge flaps have their area held
    // by a HighLiftDevice, which WingArea rescales through its cached endpoints.
    static readonly string[] MainWing = { "wing_spar_L", "wing_spar_R", "wing_spar_outer_L", "wing_spar_outer_R", "aileron_L", "aileron_R", "flap_L", "flap_R", "lef_L", "lef_R" };

    sealed class Knob
    {
        public string Section = "", Key = "", Unit = "";
        public ConfigEntry<float> Entry = null!;
    }

    sealed class Part
    {
        public AeroPart Aero = null!;
        public HighLiftDevice? Device;
        public float ShippedArea, ShippedDrag, ShippedDeployed, AreaDelta, DragDelta;
        public bool MainWing;
    }

    sealed class Record
    {
        public Aircraft Aircraft = null!;
        public Turbojet Engine = null!;
        public JetNozzle Nozzle = null!;
        public object[] Afterburners = Array.Empty<object>();
        public readonly Dictionary<string, float> Shipped = new();
        public AnimationCurve ShippedAltitude = null!;
        public Vector3 ShippedVectoring;
        public readonly List<Part> Parts = new();
        public int SeenFrame;
        public bool Applied;
    }

    static readonly FieldInfo Afterburners = AccessTools.Field(typeof(JetNozzle), "afterburners");
    static readonly FieldInfo HldDeployed = AccessTools.Field(typeof(HighLiftDevice), "deployedArea");
    static readonly FieldInfo HldRetracted = AccessTools.Field(typeof(HighLiftDevice), "partAreaRetracted");
    static readonly FieldInfo HldDeployedArea = AccessTools.Field(typeof(HighLiftDevice), "partAreaDeployed");
    static readonly FieldInfo HldPosition = AccessTools.Field(typeof(HighLiftDevice), "position");
    static readonly FieldInfo HldPart = AccessTools.Field(typeof(HighLiftDevice), "aeroPart");

    static readonly List<Knob> knobs = new();
    static readonly List<Record> records = new();
    static ConfigFile config = null!;
    static IcarusLog log = null!;
    static ConfigEntry<float>? nozzleOpen;
    static ConfigEntry<string> altitudeThrust = null!;
    static AircraftParameters? parameters;
    static readonly Dictionary<string, float> shippedParameters = new();
    static FileSystemWatcher? watcher;
    static volatile bool fileChanged;
    static bool pending, locked;
    static string lastSummary = "";

    public static void Install(ConfigFile file, IcarusLog logger)
    {
        config = file;
        log = logger;
        Bind("Tuning.Engine", "MaxThrust", "N", "Turbojet core thrust at sea level, before altitudeThrust (Turbojet.maxThrust)");
        Bind("Tuning.Engine", "MaxSpeed", "m/s", "Core thrust falls linearly to zero from this speed to 1.2 times it (Turbojet.maxSpeed)");
        Bind("Tuning.Engine", "MinDensity", "kg/m3", "The engine runs only above this air density (Turbojet.minDensity)");
        Bind("Tuning.Engine", "SpoolRate", "RPM/s", "RPM slew rate (Turbojet.spoolRate)");
        Bind("Tuning.Engine", "FuelMin", "kg per check", "Core fuel at idle, drawn about once a second (Turbojet.fuelConsumptionMin)");
        Bind("Tuning.Engine", "FuelMax", "kg per check", "Core fuel at full dry throttle (Turbojet.fuelConsumptionMax)");
        altitudeThrust = config.Bind("Tuning.Engine", "AltitudeThrust", "",
            "Core thrust factor by altitude as 'metres:factor' pairs, linear between them, e.g. '0:1, 10000:0.8, 15000:0.55, 19000:0.3'; blank is the shipped curve");
        Bind("Tuning.Afterburner", "Thrust", "N", "Afterburner thrust added on top of the core, scaled by density clamped to 0.4..1");
        Bind("Tuning.Afterburner", "Fuel", "kg per check", "Extra fuel at full afterburner");
        Bind("Tuning.Vectoring", "PitchDegrees", "deg", "Thrust vectoring pitch limit (Turbojet.thrustVectoring.x)");
        Bind("Tuning.Vectoring", "YawDegrees", "deg", "Thrust vectoring yaw limit (Turbojet.thrustVectoring.y)");
        Bind("Tuning.Vectoring", "MaxAirspeed", "m/s", "Vectoring snaps to zero above this airspeed (Turbojet.thrustVectoringMaxAirspeed)");
        Bind("Tuning.Aero", "WingArea", "m2", "Total main wing area, both sides with their surfaces and flaps; each part keeps its share");
        Bind("Tuning.Aero", "DragArea", "game units", "Total parasite dragArea of every part (half of it is the physical CdA); each part keeps its share, damage drag is kept");
        Bind("Tuning.AI", "CornerSpeed", "m/s", "AircraftParameters.cornerSpeed, read by the autopilot");
        Bind("Tuning.AI", "LandingSpeed", "m/s", "AircraftParameters.landingSpeed; an AI already on approach keeps its cached speed");
        Bind("Tuning.AI", "TakeoffSpeed", "m/s", "AircraftParameters.takeoffSpeed");
        Bind("Tuning.AI", "TurningRadius", "m", "AircraftParameters.turningRadius");
        nozzleOpen = config.Bind("Nozzle", "OpenDegrees", DefaultNozzleOpen, "Degrees each nozzle petal opens at full afterburner (visual)");

        foreach (Knob knob in knobs)
        {
            knob.Entry.SettingChanged += (_, _) => pending = true;
        }

        altitudeThrust.SettingChanged += (_, _) => pending = true;
        string path = config.ConfigFilePath;
        watcher = new FileSystemWatcher(Path.GetDirectoryName(path), Path.GetFileName(path))
        {
            NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.Size,
            EnableRaisingEvents = true,
        };
        watcher.Changed += (_, _) => fileChanged = true;
        log.Info($"tuning: watching {Path.GetFileName(path)}; {knobs.Count + 1} live knobs, below 0 (or blank) is the shipped value");
    }

    static void Bind(string section, string key, string unit, string description)
    {
        knobs.Add(new Knob
        {
            Section = section, Key = key, Unit = unit,
            Entry = config.Bind(section, key, -1f, $"{description}. In {unit}; below 0 is the shipped value. Locked to shipped while a remote peer is connected."),
        });
    }

    /// <summary>Captures the aircraft's shipped values; the first apply waits a frame for every part's Start.</summary>
    public static void Track(Aircraft aircraft)
    {
        if (records.Any(r => r.Aircraft == aircraft)) return;
        Turbojet? engine = IcarusSystems.Engine(aircraft);
        JetNozzle? nozzle = engine == null ? null : IcarusSystems.Nozzle(engine);
        if (engine == null || nozzle == null)
        {
            log.Error($"tuning: {aircraft.name} has no Turbojet or JetNozzle; not tuned");
            return;
        }

        var record = new Record { Aircraft = aircraft, Engine = engine, Nozzle = nozzle, SeenFrame = Time.frameCount };
        foreach (string field in new[] { "maxThrust", "maxSpeed", "minDensity", "spoolRate", "fuelConsumptionMin", "fuelConsumptionMax", "thrustVectoringMaxAirspeed" })
        {
            record.Shipped[field] = (float)AccessTools.Field(typeof(Turbojet), field).GetValue(engine);
        }

        record.ShippedAltitude = new AnimationCurve(((AnimationCurve)AccessTools.Field(typeof(Turbojet), "altitudeThrust").GetValue(engine)).keys);
        record.ShippedVectoring = (Vector3)AccessTools.Field(typeof(Turbojet), "thrustVectoring").GetValue(engine);
        record.Afterburners = ((Array)Afterburners.GetValue(nozzle)).Cast<object>().ToArray();
        for (int i = 0; i < record.Afterburners.Length; i++)
        {
            record.Shipped["ab" + i + ".thrust"] = (float)AfterburnerField(record.Afterburners[i], "thrust").GetValue(record.Afterburners[i]);
            record.Shipped["ab" + i + ".fuel"] = (float)AfterburnerField(record.Afterburners[i], "fuelConsumption").GetValue(record.Afterburners[i]);
        }

        AeroPart[] parts = IcarusSystems.Parts(aircraft);
        var devices = parts.SelectMany(p => p.GetComponents<HighLiftDevice>()).ToDictionary(d => (AeroPart)HldPart.GetValue(d));
        foreach (AeroPart part in parts)
        {
            devices.TryGetValue(part, out HighLiftDevice? device);
            record.Parts.Add(new Part
            {
                Aero = part, Device = device, ShippedArea = part.GetWingArea(), ShippedDrag = part.dragArea,
                ShippedDeployed = device != null ? (float)HldDeployed.GetValue(device) : 0f, MainWing = MainWing.Contains(part.name),
            });
        }

        if (parameters == null)
        {
            parameters = aircraft.GetAircraftParameters();
            shippedParameters["cornerSpeed"] = parameters.cornerSpeed;
            shippedParameters["landingSpeed"] = parameters.landingSpeed;
            shippedParameters["takeoffSpeed"] = parameters.takeoffSpeed;
            shippedParameters["turningRadius"] = parameters.turningRadius;
        }

        records.Add(record);
        log.Info(Invariant($"tuning: shipped values of {aircraft.name}: MaxThrust {record.Shipped["maxThrust"]}, MaxSpeed {record.Shipped["maxSpeed"]}, MinDensity {record.Shipped["minDensity"]}, SpoolRate {record.Shipped["spoolRate"]}, FuelMin {record.Shipped["fuelConsumptionMin"]}, FuelMax {record.Shipped["fuelConsumptionMax"]}, ")
            + Invariant($"AltitudeThrust '{CurveText(record.ShippedAltitude)}', Afterburner.Thrust {Shipped(record, "ab0.thrust")}, Afterburner.Fuel {Shipped(record, "ab0.fuel")}, ")
            + Invariant($"Vectoring.PitchDegrees {record.ShippedVectoring.x}, Vectoring.YawDegrees {record.ShippedVectoring.y}, Vectoring.MaxAirspeed {record.Shipped["thrustVectoringMaxAirspeed"]}, ")
            + Invariant($"WingArea {record.Parts.Where(p => p.MainWing).Sum(p => p.ShippedArea):0.###} (flaps retracted), DragArea {record.Parts.Sum(p => p.ShippedDrag):0.###}, ")
            + Invariant($"CornerSpeed {shippedParameters["cornerSpeed"]}, LandingSpeed {shippedParameters["landingSpeed"]}, TakeoffSpeed {shippedParameters["takeoffSpeed"]}, TurningRadius {shippedParameters["turningRadius"]}"));
    }

    static float Shipped(Record record, string key) => record.Shipped.TryGetValue(key, out float value) ? value : float.NaN;

    public static void Update()
    {
        if (fileChanged)
        {
            fileChanged = false;
            try
            {
                config.Reload();
                pending = true;
                log.Stage("tuning-file", "config file saved; reloaded");
            }
            catch (IOException e)
            {
                fileChanged = true; // still being written; try next frame
                log.Stage("tuning-file", $"reload deferred: {e.Message}");
            }
        }

        // Every frame, so a peer that connects is under shipped values within the frame, before its scene load and spawns.
        RefreshLock();

        records.RemoveAll(r => r.Aircraft == null || r.Engine == null || r.Nozzle == null);
        bool fresh = records.Any(r => !r.Applied && Time.frameCount > r.SeenFrame + 1);
        if (!pending && !fresh) return;
        pending = false;
        foreach (Record record in records.Where(r => Time.frameCount > r.SeenFrame + 1))
        {
            try
            {
                Apply(record);
                record.Applied = true;
            }
            catch (Exception e)
            {
                log.Error($"tuning: apply to {record.Aircraft.name} failed: {e}");
            }
        }
    }

    static void RefreshLock()
    {
        bool remote = RemotePeerConnected();
        if (remote == locked) return;
        locked = remote;
        pending = true;
        log.Info(locked ? "tuning: a remote peer is connected; every knob reads its shipped value" : "tuning: no remote peer; the tuning file applies again");
    }

    /// <summary>Hosting with any client in, or a client connecting or connected to anyone.</summary>
    static bool RemotePeerConnected()
    {
        try
        {
            NetworkManagerNuclearOption manager = NetworkManagerNuclearOption.i;
            if (manager == null) return false;
            if (manager.Server != null && manager.Server.Active)
                return manager.Server.AllPlayers.Any(p => p.IsConnected && !p.IsHost);
            return manager.Client != null && manager.Client.Active && !manager.Client.IsHost;
        }
        catch (Exception)
        {
            return false;
        }
    }

    static float Value(string key, float shipped)
    {
        Knob knob = knobs.First(k => k.Key == key);
        return locked || knob.Entry.Value < 0f ? shipped : knob.Entry.Value;
    }

    static void Apply(Record r)
    {
        RefreshLock();
        Turbojet engine = r.Engine;
        SetField(engine, "maxThrust", Value("MaxThrust", r.Shipped["maxThrust"]));
        SetField(engine, "maxSpeed", Value("MaxSpeed", r.Shipped["maxSpeed"]));
        SetField(engine, "minDensity", Value("MinDensity", r.Shipped["minDensity"]));
        SetField(engine, "spoolRate", Value("SpoolRate", r.Shipped["spoolRate"]));
        SetField(engine, "fuelConsumptionMin", Value("FuelMin", r.Shipped["fuelConsumptionMin"]));
        SetField(engine, "fuelConsumptionMax", Value("FuelMax", r.Shipped["fuelConsumptionMax"]));
        AnimationCurve curve = locked ? r.ShippedAltitude : ParseCurve(altitudeThrust.Value) ?? r.ShippedAltitude;
        AccessTools.Field(typeof(Turbojet), "altitudeThrust").SetValue(engine, new AnimationCurve(curve.keys));
        var vectoring = new Vector3(Value("PitchDegrees", r.ShippedVectoring.x), Value("YawDegrees", r.ShippedVectoring.y), r.ShippedVectoring.z);
        AccessTools.Field(typeof(Turbojet), "thrustVectoring").SetValue(engine, vectoring);
        SetField(engine, "thrustVectoringMaxAirspeed", Value("MaxAirspeed", r.Shipped["thrustVectoringMaxAirspeed"]));
        for (int i = 0; i < r.Afterburners.Length; i++)
        {
            // One afterburner stage on the Icarus; the knobs set the first and scale any others alike.
            float thrustScale = Value("Thrust", r.Shipped["ab0.thrust"]) / Mathf.Max(r.Shipped["ab0.thrust"], 1e-6f);
            float fuelScale = Value("Fuel", r.Shipped["ab0.fuel"]) / Mathf.Max(r.Shipped["ab0.fuel"], 1e-6f);
            AfterburnerField(r.Afterburners[i], "thrust").SetValue(r.Afterburners[i], r.Shipped["ab" + i + ".thrust"] * thrustScale);
            AfterburnerField(r.Afterburners[i], "fuelConsumption").SetValue(r.Afterburners[i], r.Shipped["ab" + i + ".fuel"] * fuelScale);
        }

        float shippedWing = r.Parts.Where(p => p.MainWing).Sum(p => p.ShippedArea);
        float wingScale = Value("WingArea", shippedWing) / Mathf.Max(shippedWing, 1e-6f);
        float shippedDrag = r.Parts.Sum(p => p.ShippedDrag);
        float dragScale = Value("DragArea", shippedDrag) / Mathf.Max(shippedDrag, 1e-6f);
        foreach (Part part in r.Parts.Where(p => p.Aero != null))
        {
            float dragDelta = part.ShippedDrag * (dragScale - 1f);
            part.Aero.ModifyDrag(dragDelta - part.DragDelta);
            part.DragDelta = dragDelta;
            if (!part.MainWing) continue;
            if (part.Device != null)
            {
                // HighLiftDevice caches its two areas at Start and writes the part's area itself whenever it moves.
                float retracted = part.ShippedArea * wingScale, deployed = part.ShippedDeployed * wingScale;
                HldDeployed.SetValue(part.Device, deployed);
                HldRetracted.SetValue(part.Device, retracted);
                HldDeployedArea.SetValue(part.Device, retracted + deployed);
                part.Aero.SetWingArea(Mathf.Lerp(retracted, retracted + deployed, (float)HldPosition.GetValue(part.Device)));
            }
            else
            {
                float areaDelta = part.ShippedArea * (wingScale - 1f);
                part.Aero.ModifyWingArea(areaDelta - part.AreaDelta);
                part.AreaDelta = areaDelta;
            }
        }

        if (parameters != null)
        {
            parameters.cornerSpeed = Value("CornerSpeed", shippedParameters["cornerSpeed"]);
            parameters.landingSpeed = Value("LandingSpeed", shippedParameters["landingSpeed"]);
            parameters.takeoffSpeed = Value("TakeoffSpeed", shippedParameters["takeoffSpeed"]);
            parameters.turningRadius = Value("TurningRadius", shippedParameters["turningRadius"]);
        }

        // Readback: every knob as the aircraft now holds it, and a hash peers can compare.
        string summary = Invariant($"MaxThrust {engine.maxThrust} MaxSpeed {GetField(engine, "maxSpeed")} MinDensity {GetField(engine, "minDensity")} SpoolRate {GetField(engine, "spoolRate")} ")
            + Invariant($"FuelMin {GetField(engine, "fuelConsumptionMin")} FuelMax {GetField(engine, "fuelConsumptionMax")} AltitudeThrust '{CurveText((AnimationCurve)AccessTools.Field(typeof(Turbojet), "altitudeThrust").GetValue(engine))}' ")
            + Invariant($"Afterburner.Thrust {r.Nozzle.GetMaxThrust()} Afterburner.Fuel {(r.Afterburners.Length > 0 ? AfterburnerField(r.Afterburners[0], "fuelConsumption").GetValue(r.Afterburners[0]) : 0f)} ")
            + Invariant($"Vectoring {(Vector3)AccessTools.Field(typeof(Turbojet), "thrustVectoring").GetValue(engine)} MaxAirspeed {GetField(engine, "thrustVectoringMaxAirspeed")} ")
            + Invariant($"WingArea {r.Parts.Where(p => p.MainWing && p.Aero != null).Sum(p => p.Device != null ? (float)HldRetracted.GetValue(p.Device) : p.Aero.GetWingArea()):0.###} (retracted) DragArea {r.Parts.Where(p => p.Aero != null).Sum(p => p.Aero.dragArea):0.###} ")
            + (parameters == null ? "" : Invariant($"CornerSpeed {parameters.cornerSpeed} LandingSpeed {parameters.landingSpeed} TakeoffSpeed {parameters.takeoffSpeed} TurningRadius {parameters.turningRadius}"));
        if (summary != lastSummary || !r.Applied)
        {
            lastSummary = summary;
            log.Info($"tuning: {(locked ? "locked to shipped" : "applied")} on {r.Aircraft.name}, hash {Hash(summary)}: {summary}");
        }
    }

    static FieldInfo AfterburnerField(object afterburner, string name) =>
        afterburner.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)
        ?? throw new MissingFieldException(afterburner.GetType().Name, name);

    static void SetField(Turbojet engine, string name, float value) => AccessTools.Field(typeof(Turbojet), name).SetValue(engine, value);

    static float GetField(Turbojet engine, string name) => (float)AccessTools.Field(typeof(Turbojet), name).GetValue(engine);

    static AnimationCurve? ParseCurve(string text)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;
        try
        {
            var points = text.Split(',').Select(pair => pair.Split(':'))
                .Select(p => new Vector2(float.Parse(p[0].Trim(), CultureInfo.InvariantCulture), float.Parse(p[1].Trim(), CultureInfo.InvariantCulture)))
                .OrderBy(p => p.x).ToArray();
            var keys = new Keyframe[points.Length];
            for (int i = 0; i < points.Length; i++)
            {
                float inSlope = i > 0 ? (points[i].y - points[i - 1].y) / (points[i].x - points[i - 1].x) : 0f;
                float outSlope = i < points.Length - 1 ? (points[i + 1].y - points[i].y) / (points[i + 1].x - points[i].x) : 0f;
                keys[i] = new Keyframe(points[i].x, points[i].y, i > 0 ? inSlope : outSlope, i < points.Length - 1 ? outSlope : inSlope);
            }

            return new AnimationCurve(keys) { preWrapMode = WrapMode.ClampForever, postWrapMode = WrapMode.ClampForever };
        }
        catch (Exception e)
        {
            log.Stage("tuning-curve", $"AltitudeThrust '{text}' doesn't parse ({e.Message}); using the shipped curve");
            return null;
        }
    }

    static string CurveText(AnimationCurve curve) => string.Join(", ", curve.keys.Select(k => Invariant($"{k.time}:{k.value}")));

    /// <summary>FNV-1a, stable across machines and runs, unlike string.GetHashCode.</summary>
    static string Hash(string text)
    {
        uint hash = 2166136261;
        foreach (byte b in Encoding.UTF8.GetBytes(text))
        {
            hash = (hash ^ b) * 16777619;
        }

        return hash.ToString("x8", CultureInfo.InvariantCulture);
    }
}
