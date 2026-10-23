using System;
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
        // Joint strength classes, after the Revoker's own joints (fuselage 100 kN, wing roots 50, wingtips 35, ailerons 30,
        // flaps and cheeks 10; torque equal to force): frames and spars hold, panels shed. The game multiplies them by 10
        // on the simulating peer and weakens them with the part's hit points. The fuselage sections break apart at the VT-7
        // Vagrant's strength (its cockpit and rear fuselage joints, 50 kN): the forward section at 60, the cockpit and
        // the aft section at 50.
        private enum JointClass { Frame, ForwardSection, Section, Spar, Primary, Surface, Flap, Panel }

        private static readonly Dictionary<JointClass, float> JointForces = new Dictionary<JointClass, float>
        {
            { JointClass.Frame, 100000f }, { JointClass.ForwardSection, 60000f }, { JointClass.Section, 50000f },
            { JointClass.Spar, 60000f }, { JointClass.Primary, 40000f },
            { JointClass.Surface, 30000f }, { JointClass.Flap, 15000f }, { JointClass.Panel, 10000f },
        };
        // The forward section's Revoker "fuselage" armour keeps two thirds of its joint at 0 HP (structuralThreshold -200);
        // the Vagrant's sections keep half (-100).
        private const float ForwardSectionThreshold = -100f;
        // Extra joints between parts whose colliders touch (BraceTouchingParts), as weak as a panel's.
        private const float BraceForce = 10000f;
        // The Revoker runs 6 to 8; the light skins and dry tanks hang off cores ten to sixty times their mass.
        private const int JointSolverIterations = 12;

        private sealed class PartSpec
        {
            public string Name, Parent, Armour, Reuse;
            public JointClass Joint;
        }

        private static PartSpec P(string name, string parent, JointClass joint, string armour, string reuse = null) =>
            new PartSpec { Name = name, Parent = parent, Joint = joint, Armour = armour, Reuse = reuse };

        // R13's "Suggested decision" tree, with the stabilator as one all-moving piece; parents before children. Armour is the
        // Revoker part whose armour class the part takes. Reuse is the Revoker GameObject that becomes the part, carrying
        // its systems: the root holds the aircraft, engine and countermeasures, the fuselage its vapour cone, the cockpit
        // the weapon manager, fly-by-wire, autopilot, crew and displays, the nose the radar and cameras, the tail the
        // JetNozzle and flare points.
        private static readonly PartSpec[] Tree =
        {
            P(RootPart, null, JointClass.Frame, "", ""),
            P("fuselage_forward", RootPart, JointClass.ForwardSection, "fuselage", "fuselage"),
            P("cockpit_cell", "fuselage_forward", JointClass.Section, "fuselage/cockpit", "fuselage/cockpit"),
            P("radome", "cockpit_cell", JointClass.Panel, "fuselage/cockpit/nose", "fuselage/cockpit/nose"),
            P("radar_tray", "cockpit_cell", JointClass.Primary, "fuselage/cockpit/nose"),
            P("canopy", "cockpit_cell", JointClass.Panel, "fuselage/cockpit/nose"),
            P("gear_leg_N", "cockpit_cell", JointClass.Primary, "fuselage/intake_L"),
            P("avionics_tray", "fuselage_forward", JointClass.Primary, "fuselage/cockpit/nose"),
            P("fuel_aux", "fuselage_forward", JointClass.Primary, "wing1b_L"),
            P("skin_forward_L", "fuselage_forward", JointClass.Panel, "fuselage/cockpit/cheek_L"),
            P("skin_forward_R", "fuselage_forward", JointClass.Panel, "fuselage/cockpit/cheek_L"),
            P("fuselage_aft", RootPart, JointClass.Section, "tail", "tail"),
            P("engine_core", "fuselage_aft", JointClass.Spar, "tail"),
            P("nozzle", "engine_core", JointClass.Primary, "tail"),
            P("fin_spar", "fuselage_aft", JointClass.Spar, "vstab1"),
            P("fin_skin", "fin_spar", JointClass.Panel, "vstab1/vstab2"),
            P("rudder", "fin_spar", JointClass.Surface, "vstab1/vstab2/rudder"),
            P("stabilator", "fin_spar", JointClass.Surface, "vstab1/vstab2"),
            P("skin_aft_L", "fuselage_aft", JointClass.Panel, "fuselage/cockpit/cheek_L"),
            P("skin_aft_R", "fuselage_aft", JointClass.Panel, "fuselage/cockpit/cheek_L"),
            P("intake_duct_L", RootPart, JointClass.Primary, "fuselage/intake_L"),
            P("intake_duct_R", RootPart, JointClass.Primary, "fuselage/intake_L"),
            P("wing_spar_L", RootPart, JointClass.Spar, "fuselage/wing1a_L"),
            P("wing_skin_L", "wing_spar_L", JointClass.Panel, "fuselage/wing1a_L/wing2_L"),
            P("aileron_L", "wing_spar_L", JointClass.Surface, "fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L"),
            P("flap_L", "wing_spar_L", JointClass.Flap, "fuselage/wing1a_L/wing2_L/flap_L"),
            P("lef_L", "wing_spar_L", JointClass.Flap, "fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L"),
            P("wing_spar_R", RootPart, JointClass.Spar, "fuselage/wing1a_L"),
            P("wing_skin_R", "wing_spar_R", JointClass.Panel, "fuselage/wing1a_L/wing2_L"),
            P("aileron_R", "wing_spar_R", JointClass.Surface, "fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L"),
            P("flap_R", "wing_spar_R", JointClass.Flap, "fuselage/wing1a_L/wing2_L/flap_L"),
            P("lef_R", "wing_spar_R", JointClass.Flap, "fuselage/wing1a_L/wing2_L/wingtip_L/aileron_L"),
            P("gear_leg_L", RootPart, JointClass.Primary, "fuselage/intake_L"),
            P("gear_leg_R", RootPart, JointClass.Primary, "fuselage/intake_L"),
            P("fuel_forward_main", RootPart, JointClass.Primary, "wing1b_L"),
            P("fuel_aft_center", RootPart, JointClass.Primary, "wing1b_L"),
            P("fuel_aft_L", RootPart, JointClass.Primary, "wing1b_L"),
            P("fuel_aft_R", RootPart, JointClass.Primary, "wing1b_L"),
            P("skin_mid_L", RootPart, JointClass.Panel, "fuselage/cockpit/cheek_L"),
            P("skin_mid_R", RootPart, JointClass.Panel, "fuselage/cockpit/cheek_L"),
            P("dorsal_cover", RootPart, JointClass.Panel, "fuselage/cockpit/cheek_L"),
        };

        private static readonly string[] R13Tanks = { "fuel_forward_main", "fuel_aft_center", "fuel_aft_L", "fuel_aft_R", "fuel_aux" };
        // Fuel cells the export adds beyond R13 carry no dry mass of their own ("their dry mass is in their hosts"); each
        // still becomes its own part, so its one collider and same-object FuelTank are hit on their own (R13), and takes
        // this much from its host, since a part needs mass.
        private const float CellMass = 5f;

        // A part's export entry: its mesh, or for a hinged surface the hinge empty whose _visible child is the mesh.
        private static BlockoutPart MeshEntry(Blockout blockout, string name) =>
            blockout.Parts[name].IsHinge ? blockout.Parts[name + "_visible"] : blockout.Parts[name];

        private static void BuildParts(Build b)
        {
            PlanParts(b);
            var aeroType = GameType("AeroPart");
            var reused = b.Specs.Where(s => s.Reuse != null).ToDictionary(s => s.Name, s => s.Reuse == "" ? b.Root : b.Find(s.Reuse).gameObject);
            foreach (var spec in b.Specs)
            {
                GameObject go;
                if (spec.Reuse != null)
                {
                    go = reused[spec.Name];
                    go.name = spec.Parent == null ? PrefabName : spec.Name;
                }
                else
                {
                    go = new GameObject(spec.Name) { layer = b.Root.layer };
                    EditorUtility.CopySerialized(b.Donor.AeroTemplate, go.AddComponent(aeroType));
                }
                b.Parts[spec.Name] = go;
                if (spec.Parent != null)
                {
                    go.transform.SetParent(b.Parts[spec.Parent].transform, true);
                    go.transform.SetPositionAndRotation(b.Blockout.Local(spec.Name), b.Blockout.Rotation(spec.Name));
                }
                var entry = MeshEntry(b.Blockout, spec.Name);
                if (entry != b.Blockout.Parts[spec.Name] && (Vector3.Distance(entry.Pivot, b.Blockout.Parts[spec.Name].Pivot) > 1e-4f
                    || Quaternion.Angle(entry.Rotation, b.Blockout.Rotation(spec.Name)) > 0.01f))
                    throw new InvalidDataException($"{spec.Name}: its _visible mesh doesn't sit at its hinge, so its colliders can't sit on the part.");
                SetColliders(b, go, entry.Name);
                if (Array.IndexOf(StructureCores, spec.Name) >= 0)
                    AddSectionInertia(go, b.Meshes[spec.Name].Render.bounds);
                if (!b.Blockout.Parts[spec.Name].IsHinge)
                {
                    Ensure<MeshFilter>(go).sharedMesh = b.Meshes[spec.Name].Render;
                    Ensure<MeshRenderer>(go).sharedMaterials = b.Meshes[spec.Name].Materials;
                }
                ConfigurePart(b, go, b.Mass[spec.Name]);
                if (spec.Parent != null)
                    b.Joints[spec.Name] = new List<string> { spec.Parent };
                var fuel = b.Blockout.Parts[spec.Name].Number("fuel_kg");
                if (fuel > 0)
                {
                    // On the part's own GameObject, for Unit.RpcFuelTankStatus's same-transform lookup.
                    var tank = go.AddComponent(GameType("FuelTank"));
                    EditorUtility.CopySerialized(b.Donor.TankTemplate, tank);
                    var so = new SerializedObject(tank);
                    Prop(so, "fuelCapacity").floatValue = fuel;
                    Prop(so, "part").objectReferenceValue = go.GetComponent(aeroType);
                    Prop(so, "connectedTanks").arraySize = 0;
                    so.ApplyModifiedPropertiesWithoutUndo();
                }
            }
            b.Report.Add($"parts: {b.Specs.Count} AeroParts ({Tree.Length} on the R13 tree), {b.Mass.Values.Sum():0} kg dry, " +
                $"tanks {string.Join(", ", b.Tanks.Select(t => t + " " + b.Blockout.Parts[t].Number("fuel_kg")))}");
        }

        // The export must hold every R13 part, each under its R13 parent through its Blender parents; the only other parts
        // it may add are fuel cells. Plans the part list (R13's, then the extra cells under their hosts) and dry masses.
        private static void PlanParts(Build b)
        {
            var problems = new List<string>();
            var names = new HashSet<string>(Tree.Select(s => s.Name));
            b.Specs.AddRange(Tree);
            foreach (var spec in Tree.Where(s => b.Blockout.Has(s.Name)))
                b.Mass[spec.Name] = MeshEntry(b.Blockout, spec.Name).Number("mass_kg");
            foreach (var cell in b.Blockout.Parts.Values.Where(p => p.Text("role") == "fuel_tank" && !names.Contains(p.Name)).OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                var host = cell.BlenderParent;
                while (host != null && !names.Contains(host))
                    host = b.Blockout.Parts[host].BlenderParent;
                if (host == null || cell.Fbx == null)
                {
                    problems.Add($"fuel cell {cell.Name} has no mesh or no R13 host");
                    continue;
                }
                b.Specs.Add(P(cell.Name, host, JointClass.Primary, "wing1b_L"));
                var own = cell.Number("mass_kg");
                b.Mass[cell.Name] = own > 0 ? own : CellMass;
                if (own <= 0 && b.Mass.ContainsKey(host))
                    b.Mass[host] -= CellMass;
            }
            b.Tanks.AddRange(b.Specs.Where(s => b.Blockout.Has(s.Name) && b.Blockout.Parts[s.Name].Number("fuel_kg") > 0).Select(s => s.Name));
            foreach (var spec in Tree)
            {
                if (!b.Blockout.Has(spec.Name))
                {
                    problems.Add(spec.Name + " is missing from the export");
                    continue;
                }
                var part = b.Blockout.Parts[spec.Name];
                if (part.IsHinge && !b.Blockout.HasMesh(spec.Name + "_visible"))
                    problems.Add(spec.Name + " is a hinge without a _visible mesh");
                else if (!part.IsHinge && part.Fbx == null)
                    problems.Add(spec.Name + " has no mesh");
                var parent = part.BlenderParent;
                while (parent != null && !names.Contains(parent))
                    parent = b.Blockout.Parts[parent].BlenderParent;
                if (parent != spec.Parent)
                    problems.Add($"{spec.Name} hangs under {parent ?? "nothing"} in the export, under {spec.Parent ?? "nothing"} in R13");
                if (MeshEntry(b.Blockout, spec.Name).Number("mass_kg") <= 0)
                    problems.Add(spec.Name + " has no mass_kg");
            }
            // Any other massive mesh would be a part the tree doesn't know.
            var planned = new HashSet<string>(b.Specs.Select(s => s.Name));
            foreach (var part in b.Blockout.Parts.Values.Where(p => p.Number("mass_kg") > 0 && !planned.Contains(p.Name)
                         && !(p.Name.EndsWith("_visible", StringComparison.Ordinal) && names.Contains(p.Name.Substring(0, p.Name.Length - 8)))))
                problems.Add($"{part.Name} carries {part.Number("mass_kg")} kg but isn't an R13 part or a fuel cell");
            var dry = b.Mass.Values.Sum();
            if (Mathf.Abs(dry - EmptyMass) > 1f)
                problems.Add($"the parts' mass_kg add up to {dry}, not R7's {EmptyMass}");
            if (b.Mass.Values.Any(m => m <= 0))
                problems.Add("a part is left without mass: " + string.Join(", ", b.Mass.Where(m => m.Value <= 0).Select(m => m.Key)));
            var fuel = b.Tanks.Sum(t => b.Blockout.Parts[t].Number("fuel_kg"));
            if (Mathf.Abs(fuel - FuelMass) > 1f)
                problems.Add($"the tanks' fuel_kg add up to {fuel}, not R7's {FuelMass}");
            foreach (var tank in R13Tanks)
                if (!b.Tanks.Contains(tank) || b.Blockout.Parts[tank].Text("role") != "fuel_tank")
                    problems.Add(tank + " isn't a fuel_tank with fuel_kg");
            if (problems.Count > 0)
                throw new InvalidDataException("R13 part tree check failed:\n  " + string.Join("\n  ", problems));
            Debug.Log($"[Icarus] check R13 tree PASS: {Tree.Length} R13 parts and {b.Specs.Count - Tree.Length} extra fuel cells [{string.Join(", ", b.Specs.Skip(Tree.Length).Select(s => s.Name + " on " + s.Parent))}], {dry:0} kg dry, {b.Tanks.Count} tanks with {fuel:0} kg");
        }

        // The fuselage cores' hulls are frame shells carved round what they hold (art/blender/hulls.py), and Unity takes a
        // Rigidbody's inertia from its colliders, so a core with hulls on only part of its section spins wrong: the main
        // tyres' side force, a metre and a half below the root, flipped the root's roll every physics step and the jet
        // reared up on the runway. A box over the core's whole section, on the game's IgnoreCollisions layer (no hits, no
        // ground cast, no contacts), gives it a fuselage section's inertia.
        private static readonly string[] StructureCores = { RootPart, "fuselage_forward", "fuselage_aft" };
        internal const int IgnoreCollisionsLayer = 15; // PhysicsLayers.IgnoreCollisions

        private static void AddSectionInertia(GameObject part, Bounds section)
        {
            var box = new GameObject(part.name + "_inertia") { layer = IgnoreCollisionsLayer };
            box.transform.SetParent(part.transform, false);
            var collider = box.AddComponent<BoxCollider>();
            collider.center = section.center;
            collider.size = section.size;
        }

        // The export's convex pieces, in the part's own frame (the part sits where its mesh does).
        private static void SetColliders(Build b, GameObject go, string meshName)
        {
            foreach (var old in go.GetComponents<MeshCollider>())
                Object.DestroyImmediate(old);
            var pieces = b.Meshes[meshName].Colliders;
            if (pieces.Length == 0)
                throw new InvalidDataException(meshName + " has no collider pieces; a part's Rigidbody with no collider gets a unit inertia tensor.");
            foreach (var piece in pieces)
            {
                var col = go.AddComponent<MeshCollider>();
                col.sharedMesh = piece;
                col.convex = true;
            }
        }

        private static void ConfigurePart(Build b, GameObject go, float mass)
        {
            var so = new SerializedObject(go.GetComponent(GameType("AeroPart")));
            Prop(so, "parentUnit").objectReferenceValue = b.Aircraft;
            Prop(so, "mass").floatValue = mass;
            Prop(so, "wingArea").floatValue = 0;
            Prop(so, "dragArea").floatValue = 0;
            Prop(so, "airfoil").intValue = BodyAirfoil;
            Prop(so, "streamlining").floatValue = 0;
            Prop(so, "centerOfLift").vector3Value = Vector3.zero;
            Prop(so, "connectedAnchor").objectReferenceValue = null;
            Prop(so, "liftNormal").objectReferenceValue = null;
            Prop(so, "disintegrateObjects").arraySize = 0;
            Prop(so, "joints").arraySize = 0;
            var renderers = Prop(so, "damageMaterial").FindPropertyRelative("renderers");
            var own = go.GetComponent<MeshRenderer>();
            SetList(renderers, own != null ? new Object[] { own } : new Object[0]);
            // The mass centre for UnitPart.ModifyMass (fuel, stores): the centre of the hulls' bounds.
            var com = go.transform.Find("CoM") ?? new GameObject("CoM") { layer = go.layer }.transform;
            com.SetParent(go.transform, false);
            com.position = BoundsOf(go.GetComponents<MeshCollider>().SelectMany(c => Corners(c.sharedMesh.bounds).Select(go.transform.TransformPoint))).center;
            Prop(so, "centerOfMass").objectReferenceValue = com;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        // Armour, thresholds and hit points from each part's Revoker armour class (R13); every part starts at 100 HP.
        private static void AuthorDamage(Build b)
        {
            foreach (var spec in b.Specs)
            {
                var so = new SerializedObject(b.Part(spec.Name));
                foreach (var value in b.Donor.Armour[spec.Armour])
                    Prop(so, value.Key).floatValue = value.Value;
                if (spec.Name == "fuselage_forward")
                    Prop(so, "structuralThreshold").floatValue = ForwardSectionThreshold;
                Num(so, "hitPoints", 100f);
                var critical = Prop(so, "criticalPart");
                if (critical.propertyType == SerializedPropertyType.Boolean)
                    critical.boolValue = false;
                else
                    Num(critical, 0);
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            b.Report.Add("damage: armour from " + string.Join("; ", b.Specs.GroupBy(s => s.Armour).Select(g => (g.Key == "" ? "Fighter1" : g.Key) + " -> " + string.Join(", ", g.Select(s => s.Name)))));
        }

        // Parts whose colliders touch but share no joint collide with each other, which blows an aircraft apart; a brace
        // joint (as stock cross joints do) holds each such pair. Each is reported, so the art can inset what shouldn't touch.
        private static void BraceTouchingParts(Build b)
        {
            Physics.SyncTransforms();
            var aeroType = GameType("AeroPart");
            var probe = b.Root.GetComponent<MeshCollider>();
            if (probe == null || !Physics.ComputePenetration(probe, probe.transform.position, probe.transform.rotation, probe, probe.transform.position + Vector3.up * 0.05f, probe.transform.rotation, out _, out _))
                throw new InvalidDataException("A12: the overlap check can't see a hull overlapping a copy of itself; it would miss real overlaps.");
            var colliders = b.Root.GetComponentsInChildren<Collider>(true)
                .Where(c => c.enabled && !c.isTrigger && c.gameObject.layer != IgnoreCollisionsLayer && !(c is MeshCollider m && m.sharedMesh == null))
                .Select(c => (collider: c, part: c.GetComponentInParent(aeroType, true))).Where(c => c.part != null).ToArray();
            var name = b.Parts.ToDictionary(p => (Object)p.Value.GetComponent(aeroType), p => p.Key);
            bool Linked(string x, string y) => b.Joints.TryGetValue(x, out var a) && a.Contains(y) || b.Joints.TryGetValue(y, out var c) && c.Contains(x);
            var braces = new List<string>();
            var blocking = new List<string>();
            for (var i = 0; i < colliders.Length; i++)
                for (var j = i + 1; j < colliders.Length; j++)
                {
                    var (a, pa) = colliders[i];
                    var (c, pc) = colliders[j];
                    if (pa == pc || !a.bounds.Intersects(c.bounds))
                        continue;
                    var (na, nc) = (name[pa], name[pc]);
                    if (Linked(na, nc))
                        continue;
                    if (Physics.ComputePenetration(a, a.transform.position, a.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.005f)
                    {
                        // The brace goes on the part further from the root, so a shed panel takes its braces with it.
                        var (child, other) = Depth(b.Parts[na].transform) >= Depth(b.Parts[nc].transform) ? (na, nc) : (nc, na);
                        if (!b.Joints.ContainsKey(child))
                            throw new InvalidDataException($"{child} overlaps {other} by {depth:F3} m and can't be braced; it is the root");
                        b.Joints[child].Add(other);
                        braces.Add($"{child}->{other} ({depth:F3} m)");
                        if (!Shelters(na) && !Shelters(nc))
                            blocking.Add($"{na} / {nc} {depth:F3} m");
                    }
                }
            b.Report.Add($"braces: {braces.Count} touching pairs jointed, {braces.Count - blocking.Count} of them a part inside a structure core or against a skin panel (intended); " +
                $"{blocking.Count} where one part's collider would block hits on another: {string.Join(", ", blocking)}");
        }

        // The structure cores (frame shells and spars), the thin skin panels and the intake ducts the fuel cells wrap, which
        // other parts sit inside or against by design: a hit passes through them to what is underneath. A cell's one hull
        // fills its duct cut-out (art/blender/hulls.py).
        private static bool Shelters(string part) => part == "fuselage_forward" || part == RootPart || part == "fuselage_aft"
            || part.StartsWith("wing_spar_", StringComparison.Ordinal) || part == "fin_spar"
            || part.StartsWith("skin_", StringComparison.Ordinal) || part.StartsWith("wing_skin_", StringComparison.Ordinal) || part == "fin_skin" || part == "dorsal_cover"
            || part == "radome" || part.StartsWith("intake_duct_", StringComparison.Ordinal);

        private static int Depth(Transform t)
        {
            var depth = 0;
            for (; t.parent != null; t = t.parent)
                depth++;
            return depth;
        }

        // Serialized PartJoints: the first to the parent part (AeroPart.Awake reads joints[0]), then braces. Each is pinned
        // where its two parts' colliders meet.
        private static void WriteJoints(Build b)
        {
            var aeroType = GameType("AeroPart");
            var donorJoints = Prop(new SerializedObject(b.Donor.AeroTemplate), "joints");
            var sound = donorJoints.arraySize > 0 ? donorJoints.GetArrayElementAtIndex(0).FindPropertyRelative("breakSound").objectReferenceValue : null;
            var spec = b.Specs.ToDictionary(s => s.Name);
            Physics.SyncTransforms();
            foreach (var entry in b.Parts)
            {
                var so = new SerializedObject(entry.Value.GetComponent(aeroType));
                var joints = Prop(so, "joints");
                var list = b.Joints.TryGetValue(entry.Key, out var l) ? l : new List<string>();
                joints.arraySize = list.Count;
                for (var i = 0; i < list.Count; i++)
                {
                    var force = i == 0 ? JointForces[spec[entry.Key].Joint] : BraceForce;
                    var joint = joints.GetArrayElementAtIndex(i);
                    joint.FindPropertyRelative("connectedPart").objectReferenceValue = b.Part(list[i]);
                    joint.FindPropertyRelative("tensor").objectReferenceValue = i == 0 ? null : b.Part(BraceTensor(spec, entry.Key, list[i]));
                    joint.FindPropertyRelative("solverIterations").intValue = JointSolverIterations;
                    joint.FindPropertyRelative("breakForce").floatValue = force;
                    joint.FindPropertyRelative("breakTorque").floatValue = force;
                    joint.FindPropertyRelative("anchor").objectReferenceValue = JointAnchor(entry.Value, b.Parts[list[i]]);
                    joint.FindPropertyRelative("breakSound").objectReferenceValue = sound;
                    joint.FindPropertyRelative("joint").objectReferenceValue = null;
                }
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            b.Report.Add("joints: " + string.Join(", ", Enum.GetValues(typeof(JointClass)).Cast<JointClass>().Select(c => $"{c} {JointForces[c] / 1000:0} kN")) + $", braces {BraceForce / 1000:0} kN, {JointSolverIterations} solver iterations");
        }

        // A brace's tensor, by the stock cross joints' rule: the brace owner's ancestor directly under the lowest common
        // ancestor of the two parts it joins. The brace lets go when that ancestor's own joint breaks
        // (AeroPart.Part_OnTensorBreak), so a section that breaks off takes its braces with it instead of hanging on them.
        private static string BraceTensor(Dictionary<string, PartSpec> spec, string owner, string other)
        {
            var above = new HashSet<string>();
            for (var p = other; p != null; p = spec[p].Parent)
                above.Add(p);
            var tensor = owner;
            while (spec[tensor].Parent != null && !above.Contains(spec[tensor].Parent))
                tensor = spec[tensor].Parent;
            return tensor;
        }

        // Where two parts meet: the middle of their colliders' common bounds, or of the gap between them.
        private static Transform JointAnchor(GameObject part, GameObject other)
        {
            Bounds Hull(GameObject go) => go.GetComponents<Collider>().Where(c => c.gameObject.layer != IgnoreCollisionsLayer && !(c is MeshCollider m && m.sharedMesh == null)).Select(c => c.bounds).Aggregate((a, c) => { a.Encapsulate(c); return a; });
            var a = Hull(part);
            var o = Hull(other);
            var lo = Vector3.Max(a.min, o.min);
            var hi = Vector3.Min(a.max, o.max);
            var name = "joint_" + other.name;
            var anchor = part.transform.Find(name) ?? new GameObject(name) { layer = part.layer }.transform;
            anchor.SetParent(part.transform, false);
            anchor.position = (lo + hi) / 2;
            return anchor;
        }
    }
}
