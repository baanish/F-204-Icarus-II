using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // R7's first-cut engine: a 65 kN core plus 45 kN of afterburner, maxSpeed raised past the stock 522 m/s cap, and its
        // fuel rates (kg per roughly one-second check).
        private const float MaxThrust = 65000f, EngineMaxSpeed = 760f, MinDensity = 0.10f, FuelMin = 0.45f, FuelMax = 2.5f;
        private const float AfterburnerThrust = 45000f, AfterburnerFuel = 5.5f, AfterburnerStart = 0.90f, AfterburnerEnd = 1.00f, AfterburnerSmoothing = 2f;
        private static readonly Vector2 ThrottleRemap = new Vector2(0f, 0.88f);
        private const float MinRpm = 1000f, MaxRpm = 3000f, SpoolRate = 1500f, StartupRate = 200f;
        // R7's altitudeThrust keys (altitude, factor, in and out tangent): linear between 0, 10, 15 and 19 km.
        private static readonly float[][] AltitudeThrust =
        {
            new[] { 0f, 1.0f, -2e-5f, -2e-5f }, new[] { 10000f, 0.8f, -2e-5f, -5e-5f },
            new[] { 15000f, 0.55f, -5e-5f, -6.25e-5f }, new[] { 19000f, 0.3f, -6.25e-5f, -6.25e-5f },
        };
        // R12: stock vectoring kept at 4 degrees in pitch and yaw, no roll mixing. The cutoff sits above the top speed
        // (912 m/s, where the thrust taper ends): the Revoker's 250 m/s left the Icarus, rarely that slow, without it.
        private static readonly Vector3 ThrustVectoring = new Vector3(4f, 4f, 0f);
        private const float VectoringMaxAirspeed = 1000f;
        // R13: the engine fails from its core and nozzle, at the Revoker's threshold.
        private const float EngineDamageThreshold = 50f;
        // fighter1_afterburner_nozzle's bounds: the glow cylinder the Revoker's nozzle is sized to.
        private const float RevokerGlowRadius = 0.517f, RevokerGlowLength = 0.6f;

        // The Revoker's Turbojet stays on the root. Its JetNozzle's GameObject becomes thrust_vector, an identity pivot at
        // the petal ring's centre under the Icarus nozzle part that the Turbojet turns for vectoring; the thrust axis, flame
        // and glow ride on it. The petals and seals hang from nozzle_vector, which stays still: NozzleDriver (src/Icarus)
        // opens them with afterburner and deflects them to follow thrust_vector.
        private static void BuildEngine(Build b)
        {
            var nozzlePart = b.Parts["nozzle"].transform;
            var ring = new GameObject("nozzle_vector") { layer = nozzlePart.gameObject.layer }.transform;
            ring.SetParent(nozzlePart, false);
            ring.SetPositionAndRotation(b.Blockout.Local("nozzle_vector"), b.Blockout.Rotation("nozzle_vector"));
            b.Visuals["nozzle_vector"] = ring;
            var petals = 0;
            var nozzleRenderers = new List<Object> { nozzlePart.GetComponent<MeshRenderer>() };
            float petalLength = 0;
            foreach (var hingeName in b.Blockout.Parts.Values.Where(p => p.BlenderParent == "nozzle_vector").Select(p => p.Name).OrderBy(n => n, System.StringComparer.Ordinal))
            {
                if (!b.Blockout.Parts[hingeName].IsHinge || !b.Blockout.HasMesh(hingeName + "_visible"))
                    throw new InvalidDataException(hingeName + " under nozzle_vector isn't a hinge with a _visible mesh");
                var hinge = new GameObject(hingeName) { layer = ring.gameObject.layer }.transform;
                hinge.SetParent(ring, false);
                hinge.SetPositionAndRotation(b.Blockout.Local(hingeName), b.Blockout.Rotation(hingeName));
                var visible = new GameObject(hingeName + "_visible") { layer = ring.gameObject.layer };
                visible.transform.SetParent(hinge, false);
                visible.transform.SetPositionAndRotation(b.Blockout.Local(hingeName + "_visible"), b.Blockout.Rotation(hingeName + "_visible"));
                visible.AddComponent<MeshFilter>().sharedMesh = b.Meshes[hingeName + "_visible"].Render;
                var renderer = visible.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = b.Meshes[hingeName + "_visible"].Materials;
                nozzleRenderers.Add(renderer);
                b.Visuals[hingeName] = hinge;
                b.Visuals[hingeName + "_visible"] = visible.transform;
                petalLength = Mathf.Max(petalLength, b.Meshes[hingeName + "_visible"].Render.bounds.size.z);
                petals++;
            }
            if (petals != 32 || ring.childCount != 32)
                throw new InvalidDataException($"A2: nozzle_vector has {petals} petals and seals, expected 32 hinges for NozzleDriver");
            if (petalLength <= 0)
                throw new InvalidDataException("A2: nozzle petals have no axial length for flame and glow scaling");
            // The actuation (art/blender/propulsion.py ACTUATION): the sync ring and the rams' cylinders ride the nozzle part,
            // the links and the rams' rods the ring. NozzleDriver slides and tilts the ring with the petals and turns each
            // piece about its eye toward the other's.
            var sync = MeshVisual(b, "nozzle_sync_ring", nozzlePart);
            nozzleRenderers.Add(sync);
            foreach (var piece in b.Blockout.Parts.Values.Where(p => p.Name.StartsWith("nozzle_link_") || p.Name.StartsWith("nozzle_ram_"))
                         .OrderBy(p => p.Name, System.StringComparer.Ordinal))
                nozzleRenderers.Add(MeshVisual(b, piece.Name, piece.BlenderParent == "nozzle_sync_ring" ? sync.transform : nozzlePart));
            var rams = b.Blockout.Parts.Keys.Count(n => n.StartsWith("nozzle_ram_") && n.EndsWith("_rod"));
            if (rams == 0 || sync.transform.childCount != 16 + rams || nozzleRenderers.Count != 34 + 16 + 2 * rams)
                throw new InvalidDataException($"A2: nozzle actuation has {sync.transform.childCount} links and rods on its ring and {nozzleRenderers.Count - 34} pieces in all, expected 16 links and {rams} rams");
            var nozzleDamage = new SerializedObject(b.Part("nozzle"));
            SetList(Prop(nozzleDamage, "damageMaterial").FindPropertyRelative("renderers"), nozzleRenderers);
            nozzleDamage.ApplyModifiedPropertiesWithoutUndo();
            if (GetList(Prop(new SerializedObject(b.Part("nozzle")), "damageMaterial").FindPropertyRelative("renderers")).Length != nozzleRenderers.Count)
                throw new InvalidDataException("A2: nozzle damage must cover the shroud, all 32 petal and seal renderers and every actuation piece");

            var thrust = b.Parts["fuselage_aft"].transform.Find("thrust_vector") ?? throw new MissingReferenceException("fuselage_aft/thrust_vector");
            var jet = thrust.GetComponent(GameType("JetNozzle"));
            var heatHaze = b.Parts["fuselage_aft"].transform.Find("heat_haze") ?? throw new MissingReferenceException("fuselage_aft/heat_haze");
            thrust.SetParent(nozzlePart, true);
            thrust.SetPositionAndRotation(ring.position, nozzlePart.rotation);
            // The Revoker's flame and glow meshes are built to hang from its nozzle pivot at the throat: the glow a cylinder
            // of radius 0.517 m, 0.6 m long, just behind it; the flame from 0.8 m behind it. They hang from the Icarus ring
            // the same way, scaled to its radius across and to the petals' length along, as does the haze.
            var exit = ring.position + Vector3.back * petalLength * 0.95f;
            var ringRadius = ring.Cast<Transform>().Max(h => new Vector2(h.localPosition.x, h.localPosition.y).magnitude);
            var effectScale = new Vector3(ringRadius / RevokerGlowRadius, ringRadius / RevokerGlowRadius, petalLength / RevokerGlowLength);
            var flame = thrust.Find("afterburner_flame");
            var glow = thrust.Find("afterburner_nozzle_glow");
            heatHaze.SetParent(thrust, false);
            foreach (var t in new[] { flame, glow, heatHaze })
            {
                t.localPosition = Vector3.zero;
                t.localScale = effectScale;
            }
            b.Report.Add($"nozzle effects: petal length {petalLength:0.000} m, ring radius {ringRadius:0.000} m, " +
                $"flame/glow/haze scale {effectScale}, 32 NozzleDriver hinges, a sync ring with 16 links and {rams} rams, {nozzleRenderers.Count} damage renderers");
            b.Placed.UnionWith(new[] { thrust, flame, glow, heatHaze, thrust.Find("thrustTransform") });

            var so = new SerializedObject(jet);
            Prop(so, "part").objectReferenceValue = b.Part("nozzle");
            Prop(so, "vectorTransforms").arraySize = 0;
            var afterburners = Prop(so, "afterburners");
            if (afterburners.arraySize != 1)
                throw new InvalidDataException($"A2: the Revoker's nozzle has {afterburners.arraySize} afterburners, expected one");
            var ab = afterburners.GetArrayElementAtIndex(0);
            ab.FindPropertyRelative("thrust").floatValue = AfterburnerThrust;
            ab.FindPropertyRelative("fuelConsumption").floatValue = AfterburnerFuel;
            ab.FindPropertyRelative("throttleStart").floatValue = AfterburnerStart;
            ab.FindPropertyRelative("throttleEnd").floatValue = AfterburnerEnd;
            ab.FindPropertyRelative("smoothing").floatValue = AfterburnerSmoothing;
            so.ApplyModifiedPropertiesWithoutUndo();

            var engine = b.Root.GetComponent(GameType("Turbojet"));
            var te = new SerializedObject(engine);
            Prop(te, "maxThrust").floatValue = MaxThrust;
            Prop(te, "maxSpeed").floatValue = EngineMaxSpeed;
            Prop(te, "minDensity").floatValue = MinDensity;
            Prop(te, "fuelConsumptionMin").floatValue = FuelMin;
            Prop(te, "fuelConsumptionMax").floatValue = FuelMax;
            Prop(te, "throttleRemap").vector2Value = ThrottleRemap;
            Prop(te, "minRPM").floatValue = MinRpm;
            Prop(te, "maxRPM").floatValue = MaxRpm;
            Prop(te, "spoolRate").floatValue = SpoolRate;
            Prop(te, "startupRate").floatValue = StartupRate;
            Prop(te, "altitudeThrust").animationCurveValue = Curve(AltitudeThrust);
            Prop(te, "thrustVectoring").vector3Value = ThrustVectoring;
            var gain = Prop(te, "thrustVectoringGain").vector3Value;
            Prop(te, "thrustVectoringGain").vector3Value = new Vector3(gain.x, gain.y, 0f);
            Prop(te, "thrustVectoringMaxAirspeed").floatValue = VectoringMaxAirspeed;
            Prop(te, "damageThreshold").floatValue = EngineDamageThreshold;
            SetList(Prop(te, "vectoringTransforms"), new Object[] { thrust });
            SetList(Prop(te, "criticalParts"), new Object[] { b.Part("engine_core"), b.Part("nozzle") });
            SetList(Prop(te, "nozzles"), new Object[] { jet });
            te.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"engine: {MaxThrust / 1000:0} kN core + {AfterburnerThrust / 1000:0} kN afterburner, maxSpeed {EngineMaxSpeed}, fuel {FuelMin}..{FuelMax} + {AfterburnerFuel}, " +
                $"vectoring {ThrustVectoring} below {VectoringMaxAirspeed} m/s on thrust_vector at {thrust.position}; {petals} petals and seals under nozzle_vector, exit at {exit}");
        }
    }
}
