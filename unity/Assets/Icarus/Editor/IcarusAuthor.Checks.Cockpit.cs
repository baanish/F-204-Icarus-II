using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The stock seat's rail (EjectionSeat, the PilotDismounted nozzle's up in the cockpit frame), the last step where its
        // colliders turn on and its end, and the pilot capsule swept along it (radius, ends below and above the Pilot).
        private static readonly Vector3 SeatRail = new Vector3(-0.024f, 0.973f, 0.230f);
        private const float RailCollidable = 1.44f, RailEnd = 1.50f, CapsuleRadius = 0.25f, CapsuleBelow = 0.40f, CapsuleAbove = 0.90f;

        private static string CheckCockpit(Build b, Object parameters, List<string> p)
        {
            var aircraft = new SerializedObject(b.Aircraft);
            foreach (var field in new[] { "cockpit", "controlsFilter", "weaponManager", "targetCam", "radar", "EOTS", "powerSupply", "cockpitViewPoint", "definition" })
                if (Prop(aircraft, field).objectReferenceValue == null) p.Add("Aircraft." + field + " is null");
            if (GetList(Prop(aircraft, "pilots")).Any(o => o == null)) p.Add("a null pilot");
            if (GetList(Prop(aircraft, "groundEquipment")).Any(o => o == null)) p.Add("dead ground equipment");
            if (GetList(Prop(aircraft, "exteriorRenderers")).Any(o => o == null)) p.Add("a null exterior renderer");
            var revoker = b.Root.GetComponentsInChildren<MeshFilter>(true).Where(f => f.sharedMesh != null && RevokerCockpitMeshes.Contains(f.sharedMesh.name)).ToArray();
            if (revoker.Length > 0) p.Add("Revoker cockpit meshes remain: " + string.Join(", ", revoker.Select(f => PathOf(f.transform, b.Root.transform) + " " + f.sharedMesh.name)));
            // The tac screen: one pylon set per HardpointIndex (PylonIndicator indexes them directly), and every engine
            // gauge named for a damageable that carries the engine.
            var cockpitUi = b.Parts["cockpit_cell"].GetComponentsInChildren(GameType("Cockpit"), true).Single();
            var screen = GetRef(cockpitUi, "tacScreenUIPrefab") as GameObject;
            var manager = new SerializedObject(b.Parts["cockpit_cell"].GetComponent(GameType("WeaponManager")));
            var stationSets = Prop(manager, "hardpointSets");
            var stations = Enumerable.Range(0, stationSets.arraySize).SelectMany(i =>
            {
                var hardpoints = stationSets.GetArrayElementAtIndex(i).FindPropertyRelative("hardpoints");
                return Enumerable.Range(0, hardpoints.arraySize).Select(j => hardpoints.GetArrayElementAtIndex(j).FindPropertyRelative("HardpointIndex").intValue);
            }).ToArray();
            var pylonSets = 0;
            if (screen == null || !AssetDatabase.GetAssetPath(screen).StartsWith(ModFolder, StringComparison.Ordinal))
                p.Add("the cockpit's tac screen isn't the Icarus copy");
            else
            {
                var pylons = Prop(new SerializedObject(screen.GetComponentsInChildren(GameType("PylonIndicator"), true).Single()), "pylonElementSets");
                pylonSets = pylons.arraySize;
                if (pylonSets <= stations.Max()) p.Add($"the tac screen has {pylonSets} pylon sets for HardpointIndex up to {stations.Max()}");
                foreach (var telemetry in screen.GetComponentsInChildren(GameType("EngineTelemetry"), true))
                {
                    var engineName = Prop(new SerializedObject(telemetry), "engineName").stringValue;
                    var carriers = b.Root.GetComponentsInChildren(GameType("Turbojet"), true).Where(t => t.gameObject.name == engineName && t.GetComponent(GameType("AeroPart")) != null).ToArray();
                    if (carriers.Length != 1) p.Add($"tac screen engine gauge names {engineName}, which {carriers.Length} engine parts carry");
                }
            }
            var so = new SerializedObject(parameters);
            var hud = (GameObject)Prop(so, "HUDExtras").objectReferenceValue;
            var speedGauge = hud == null ? null : hud.GetComponentsInChildren(GameType("SpeedGauge"), true).SingleOrDefault();
            if (hud == null || AssetDatabase.GetAssetPath(hud) != HudExtrasPath || speedGauge == null
                || Prop(new SerializedObject(speedGauge), "overspeedThreshold").floatValue != OverspeedThreshold)
                p.Add($"HUDExtras isn't the Icarus's copy of the afterburner-and-airbrake HUD with overspeed at {OverspeedThreshold} m/s");
            var display = (GameObject)Prop(so, "StatusDisplay").objectReferenceValue;
            var images = display == null ? new string[0] : Enumerable.Range(0, Prop(new SerializedObject(display.GetComponent(GameType("StatusDisplay"))), "statusDisplays").arraySize)
                .Select(i => ((Component)Prop(new SerializedObject(display.GetComponent(GameType("StatusDisplay"))), "statusDisplays").GetArrayElementAtIndex(i).FindPropertyRelative("partImage").objectReferenceValue).gameObject.name).ToArray();
            var partNames = All(b, "AeroPart").Select(a => a.gameObject.name).ToArray();
            foreach (var image in images)
                if (partNames.Count(n => n == image) != 1) p.Add($"damage diagram image {image} matches {partNames.Count(n => n == image)} parts");
            foreach (var part in partNames.Except(images))
                p.Add($"part {part} has no damage diagram image");
            if (images.Length == 0) p.Add("no damage diagram images");
            var cameras = new[] { "camMountForward", "camMountRear" }.Select(f => (Transform)Prop(new SerializedObject(b.Parts["radome"].GetComponent(GameType("TargetCam"))), f).objectReferenceValue).ToArray();
            var minimum = float.PositiveInfinity;
            foreach (var r in b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.gameObject.layer != 3))
                foreach (var camera in cameras)
                    minimum = Mathf.Min(minimum, Vector3.Distance(camera.position, r.bounds.ClosestPoint(camera.position)));
            if (minimum < CameraClearance - 0.01f) p.Add($"a target camera is {minimum:F2} m from the airframe, under {CameraClearance}");
            return $"aircraft links set, no Revoker interior mesh, tac screen with {pylonSets} pylon sets for {stations.Length} stations and its engine gauges on the engine, HUD extras with afterburner and airbrake and overspeed at {OverspeedThreshold} m/s, {images.Length} diagram images on unique parts covering all {partNames.Length}, target cameras {minimum:F2} m clear";
        }

        private static string CheckEscape(Build b, List<string> p)
        {
            var pilots = All(b, "Pilot");
            var listed = GetList(Prop(new SerializedObject(b.Aircraft), "pilots"));
            if (pilots.Length != 1 || listed.Length != 1 || listed[0] != pilots[0]) p.Add($"{pilots.Length} Pilots, Aircraft.pilots [{string.Join(", ", listed.Select(o => o == null ? "null" : o.name))}]");
            if (pilots.Length > 0 && !Prop(new SerializedObject(pilots[0]), "ejectionSeat").boolValue) p.Add("the pilot has no ejection seat");
            if (pilots.Length > 0 && Prop(new SerializedObject(pilots[0]), "unitPart").objectReferenceValue != b.Part("cockpit_cell")) p.Add("the pilot isn't on cockpit_cell");
            if (All(b, "EscapeCapsule").Length > 0) p.Add("an EscapeCapsule remains");
            var canopies = GetList(Prop(new SerializedObject(b.Aircraft), "canopies"));
            var canopy = b.Parts["canopy"].GetComponent(GameType("Canopy"));
            if (canopies.Length != 1 || canopies[0] != canopy) p.Add("Aircraft.canopies isn't the canopy part's Canopy");
            if (canopy != null)
            {
                var so = new SerializedObject(canopy);
                if (Prop(so, "attachedPart").objectReferenceValue != b.Part("canopy") || Prop(so, "ejectionTransform").objectReferenceValue != b.Parts["canopy"].transform) p.Add("the Canopy doesn't eject the canopy part");
                if (GetList(Prop(so, "glassRenderers")).Any(r => r == null)) p.Add("a null canopy glass renderer");
                var hinges = Prop(so, "canopyHinges");
                var hood = hinges.arraySize == 1 ? hinges.GetArrayElementAtIndex(0).FindPropertyRelative("transform").objectReferenceValue as Transform : null;
                if (hood == null || hood.parent != b.Parts["canopy"].transform || hinges.GetArrayElementAtIndex(0).FindPropertyRelative("hingeAngle").floatValue == 0)
                    p.Add("the canopy doesn't open its hood on the canopy hinge");
                // Canopy pushes along its part's forward x ejectionForce.z plus up x ejectionForce.y.
                var force = Prop(so, "ejectionForce").vector3Value;
                var push = b.Parts["canopy"].transform.forward * force.z + b.Parts["canopy"].transform.up * force.y;
                if (push.sqrMagnitude < 1f || Vector3.Dot(push.normalized, Vector3.up) < 0.9f)
                    p.Add($"the canopy ejects along {push.normalized}, not up out of the aircraft");
            }
            if (pilots.Length == 0)
                return "no pilot";
            // The seat rides its rail out after the canopy goes; the capsule must clear every other airframe collider.
            var crew = new HashSet<Collider>(pilots.SelectMany(x => x.GetComponentsInChildren<Collider>(true)));
            var airframe = b.Root.GetComponentsInChildren<Collider>(true)
                .Where(c => c.enabled && !c.isTrigger && c.gameObject.layer != IgnoreCollisionsLayer && !crew.Contains(c) && !c.transform.IsChildOf(b.Parts["canopy"].transform) && !(c is MeshCollider m && m.sharedMesh == null)).ToArray();
            var probe = new GameObject("escape_probe").AddComponent<CapsuleCollider>();
            try
            {
                probe.radius = CapsuleRadius;
                probe.height = CapsuleBelow + CapsuleAbove;
                probe.center = new Vector3(0, (CapsuleAbove - CapsuleBelow) / 2, 0);
                foreach (var rail in new[] { RailCollidable, RailEnd })
                {
                    probe.transform.position = pilots[0].transform.position + b.Parts["cockpit_cell"].transform.TransformDirection(SeatRail) * rail;
                    Physics.SyncTransforms();
                    foreach (var c in airframe)
                        if (Physics.ComputePenetration(probe, probe.transform.position, probe.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.001f)
                            p.Add($"the seat at {rail} m up its rail overlaps {PathOf(c.transform, b.Root.transform)} by {depth:F3} m");
                }
            }
            finally
            {
                Object.DestroyImmediate(probe.gameObject);
            }
            return $"one pilot with an ejection seat, no capsule, the canopy part ejects, the seat clears {airframe.Length} colliders at {RailCollidable} and {RailEnd} m";
        }

        // The renderers the cockpit view draws (Cockpit rule 1): the joined interior, both inner frames, both inner panes, the
        // tac screen, the stock stick and throttle, and the instruments' moving parts (the standby ball, the fuel needle, the
        // clock's hands), which the plugin turns and so cannot join the interior.
        private static readonly string[] CockpitViewRenderers =
            { "canopy_frame_inner", "canopy_glass_inner", "cockpit_clock_hour", "cockpit_clock_minute", "cockpit_fuel_needle", "cockpit_interior",
              "cockpit_standby_ball", "cockpit_tac_screen", "joystick", "throttle", "windscreen_frame_inner", "windscreen_inner" };

        // A15: Cockpit rules 20 to 24 (lists, layers, serialized states, proxies in LOD0), the materials each renderer wears,
        // and the triangle bands of rules 2, 3, 20, 23 and 26.
        private static string CheckCockpitRenderers(Build b, List<string> p)
        {
            var aircraft = new SerializedObject(b.Aircraft);
            var view = GetList(Prop(aircraft, "cockpitRenderers")).OfType<Renderer>().ToArray();
            var names = view.Select(r => r.name).OrderBy(n => n, StringComparer.Ordinal).ToArray();
            if (!names.SequenceEqual(CockpitViewRenderers)) p.Add($"cockpitRenderers are [{string.Join(", ", names)}]");
            foreach (var r in view)
            {
                if (r.gameObject.layer != CockpitLayer) p.Add($"{r.name} is on layer {r.gameObject.layer}");
                if (r.enabled) p.Add(r.name + " is serialized enabled");
            }
            Material Stocked(string slot) => Load<Material>(Stock + "Material/" + slot + "_PLACEHOLDER.mat");
            int Count(Renderer r) => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3;
            Renderer Named(string n) => view.FirstOrDefault(r => r.name == n);
            foreach (var n in new[] { "cockpit_interior", "canopy_frame_inner", "windscreen_frame_inner" }.Concat(CockpitInstruments))
                if (Named(n) != null && (Named(n).sharedMaterials.Length != 1 || Named(n).sharedMaterial.name != CockpitSlot)) p.Add(n + " isn't on the cockpit atlas");
            var cockpitUi = b.Parts["cockpit_cell"].GetComponentsInChildren(GameType("Cockpit"), true).Single();
            var screen = GetRef(cockpitUi, "tacScreenRender") as Renderer;
            if (screen == null || screen.name != "cockpit_tac_screen" || screen.sharedMaterial != Stocked("tacScreenDisplay"))
                p.Add("Cockpit.tacScreenRender isn't cockpit_tac_screen on tacScreenDisplay");
            var lamps = GetList(Prop(new SerializedObject(b.Parts["cockpit_cell"].GetComponentsInChildren(GameType("CockpitWarningLights"), true).Single()), "lightRenderers")).OfType<Renderer>().ToArray();
            if (lamps.Length != 1 || lamps[0].name != "cockpit_warning_lamps" || lamps[0].enabled || lamps[0].gameObject.layer != CockpitLayer
                || lamps[0].sharedMaterial != Stocked("CockpitWarningLight") || Count(lamps[0]) < 40 || Count(lamps[0]) > 80)
                p.Add("CockpitWarningLights.lightRenderers isn't the Icarus lamp mesh, 40 to 80 triangles on CockpitWarningLight, layer 3, serialized off");
            var exterior = GetList(Prop(aircraft, "exteriorRenderers")).OfType<Renderer>().ToArray();
            var lod0 = b.Root.GetComponentsInChildren<LODGroup>(true).SelectMany(g => g.GetLODs()[0].renderers).ToArray();
            var proxies = new[] { ("cockpit_proxy", 700, 1030), ("canopy_frame_proxy", 240, 1900) }.Select(e => (e, r: exterior.FirstOrDefault(x => x.name == e.Item1))).ToArray();
            foreach (var ((name, lo, hi), r) in proxies)
            {
                if (r == null) p.Add(name + " isn't in exteriorRenderers");
                else if (!r.enabled || r.gameObject.layer == CockpitLayer || r.sharedMaterial != Stocked("Matte_black") || !lod0.Contains(r) || Count(r) < lo || Count(r) > hi)
                    p.Add($"{name} isn't an enabled Matte_black renderer in LOD0 of {lo} to {hi} triangles");
            }
            if (exterior.Any(r => r.gameObject.layer == CockpitLayer)) p.Add("an exteriorRenderers entry on the cockpit layer");
            if (view.Intersect(exterior).Any()) p.Add("a renderer in both cockpitRenderers and exteriorRenderers");
            var interior = Named("cockpit_interior");
            if (b.Parts["cockpit_cell"].GetComponentsInChildren<Light>(true).Any(l => view.Any(r => l.transform.IsChildOf(r.transform))))
                p.Add("a Light in the cockpit");
            var total = view.Sum(Count);
            var frame = Named("canopy_frame_inner");
            if (interior == null || frame == null)
                return "no interior";
            // Cockpit rule 2's 13,500 raised to 16,000 for the cockpit's detail (owner, 2026-10-22; art/blender/cockpit.py RULES)
            if (Count(interior) < 10500 || Count(interior) > 16000) p.Add($"the interior has {Count(interior)} triangles, outside 10,500 to 16,000");
            if (Count(frame) < 1300 || Count(frame) > 8000) p.Add($"the hood's inner frame has {Count(frame)} triangles, outside 1,300 to 8,000");
            if (total > 35000) p.Add($"the cockpit renderers have {total} triangles, over 35,000");
            return $"{view.Length} cockpit renderers on layer 3 serialized off, {total} triangles (interior {Count(interior)}, inner frames {Count(frame)} + {Count(Named("windscreen_frame_inner"))}); " +
                $"tac screen on tacScreenDisplay, lamps {Count(lamps[0])} in CockpitWarningLights, proxies {Count(proxies[0].r)} + {Count(proxies[1].r)} in exteriorRenderers and LOD0, no cockpit Light";
        }
    }
}
