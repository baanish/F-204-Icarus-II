using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // The balance the 5% MAC margin was tuned on, before the breakup split (BalanceFromBatch on that prefab): the
        // centre of mass in the root's frame, empty and with full internal fuel. Splitting a part keeps its family's first
        // moment (art/blender/parts.py MOMENT_SPLITS, skin pieces by area), so the centres may move only by rounding.
        private static readonly Vector3 PinnedEmptyCg = new Vector3(-0.00119854242f, 0.0266057253f, -0.7802818f),
            PinnedFullCg = new Vector3(-0.0007295151f, 0.0538963675f, -0.235217616f);
        private const float BalanceTolerance = 0.01f;
        // Damage registrations: Unit.RegisterDamageable only appends and sends a part's index as a byte, so the list must
        // stay under 256 for the jet's life. The prefab's own damageables plus the one the default loadout's mounts add
        // at spawn (42 in game against 41 parts, tests/scenarios/damage_registrations.scenario.jsonc; reloading the
        // loadout added none) must stay at most RegistrationLimit, which leaves room for a long sortie of rearms.
        private const int LoadoutRegistrations = 1, RegistrationLimit = 100;

        // The parts split from one family (art/blender/parts.py family_mass_kg): skin pieces by family name, the
        // moment-split boxes by the part they were split from.
        private static IGrouping<string, string>[] SplitFamilies(Build b) =>
            b.Specs.Where(s => b.Blockout.Has(s.Name) && MeshEntry(b.Blockout, s.Name).Number("family_mass_kg") > 0)
                .GroupBy(s => MeshEntry(b.Blockout, s.Name).Text("family") ?? SkinFamily(s.Name), s => s.Name).ToArray();

        // Each split family's first moment as the family had it. A part's mass and fuel sit at its centre-of-mass marker,
        // the centre of its hulls' bounds (ConfigurePart), and the family's sat at the centre of all of them. The generator
        // shares a family's mass physically (the wing boxes keep their span moment, skins share by area), and the pieces'
        // markers then leave a moment along the fuselage that moved the centre of mass 48 mm aft; keeping that moment by
        // the mass split instead would leave the outer wing box 15 kg and the outer skins none, since the family's marker
        // sits at the inner pieces' own station. So the markers move instead, along the fuselage and vertically (span
        // moments cancel between the mirrored sides), never out of their pieces' bounds: all of a family's by the same
        // amount, or, where two pieces carry fuel unevenly, each by what keeps the moment empty and full alike, as near
        // as their bounds allow. Returns a line a family.
        private static List<string> KeepFamilyMoments(Build b)
        {
            var lines = new List<string>();
            var root = b.Root.transform;
            foreach (var family in SplitFamilies(b))
            {
                var names = family.ToArray();
                Bounds Hulls(IEnumerable<string> parts) =>
                    BoundsOf(parts.Select(n => PreCarveBox(b, n, "mass_box_world")).SelectMany(box => Corners(box)).Select(root.InverseTransformPoint));
                var centre = Hulls(names).center;
                var bounds = names.Select(n => Hulls(new[] { n })).ToArray();
                var mass = names.Select(n => b.Mass[n]).ToArray();
                var fuel = names.Select(n => b.Blockout.Parts[n].Number("fuel_kg")).ToArray();
                var moves = names.Select(_ => Vector3.zero).ToArray();
                for (var axis = 1; axis < 3; axis++)
                {
                    float Lo(int i) => bounds[i].min[axis] - bounds[i].center[axis];
                    float Hi(int i) => bounds[i].max[axis] - bounds[i].center[axis];
                    var dry = -Enumerable.Range(0, names.Length).Sum(i => mass[i] * (bounds[i].center[axis] - centre[axis]));
                    var full = -Enumerable.Range(0, names.Length).Sum(i => (mass[i] + fuel[i]) * (bounds[i].center[axis] - centre[axis]));
                    var det = names.Length == 2 ? mass[0] * (mass[1] + fuel[1]) - mass[1] * (mass[0] + fuel[0]) : 0f;
                    if (Mathf.Abs(det) > 1e-3f)
                    {
                        var second = Mathf.Clamp((mass[0] * full - (mass[0] + fuel[0]) * dry) / det, Lo(1), Hi(1));
                        moves[1][axis] = second;
                        moves[0][axis] = Mathf.Clamp((dry - mass[1] * second) / mass[0], Lo(0), Hi(0));
                    }
                    else
                        for (var i = 0; i < names.Length; i++)
                            moves[i][axis] = Mathf.Clamp(dry / mass.Sum(), Lo(i), Hi(i));
                }
                for (var i = 0; i < names.Length; i++)
                    ((Transform)GetRef(b.Part(names[i]), "centerOfMass")).position = root.TransformPoint(bounds[i].center + moves[i]);
                lines.Add(family.Key + ": " + string.Join(", ", names.Select((n, i) => $"{n} {moves[i].ToString("F3")} m")));
            }
            return lines;
        }

        // The aircraft's centre of mass in its root's frame, empty and with every tank full: each part's mass, and each
        // tank's fuel, at its part's centre-of-mass marker, as UnitPart.ModifyMass puts it.
        private static (Vector3 Empty, Vector3 Full) Balance(GameObject root)
        {
            Vector3 Marker(Component part) => root.transform.InverseTransformPoint(
                ((Transform)new SerializedObject(part).FindProperty("centerOfMass").objectReferenceValue ?? part.transform).position);
            var sum = Vector3.zero;
            var mass = 0f;
            foreach (var part in root.GetComponentsInChildren(GameType("AeroPart"), true))
            {
                var m = new SerializedObject(part).FindProperty("mass").floatValue;
                sum += m * Marker(part);
                mass += m;
            }
            var empty = sum / mass;
            foreach (var tank in root.GetComponentsInChildren(GameType("FuelTank"), true))
            {
                var so = new SerializedObject(tank);
                var kg = so.FindProperty("fuelCapacity").floatValue;
                sum += kg * Marker((Component)so.FindProperty("part").objectReferenceValue);
                mass += kg;
            }
            return (empty, sum / mass);
        }

        // A22: the breakup tree as authored. Every part hangs on its tree parent at its class's strength, its only other
        // joints the tail braces with their tensors; the pieces of each family split in the export weigh what the family
        // did; the balance is the pinned one; and the damage registrations leave room.
        private static string CheckBreakupTree(Build b, List<string> p)
        {
            var spec = b.Specs.ToDictionary(s => s.Name);
            foreach (var s in b.Specs)
            {
                var joints = Prop(new SerializedObject(b.Part(s.Name)), "joints");
                var braces = Braces.Where(t => t.Owner == s.Name).ToArray();
                if (joints.arraySize != (s.Parent == null ? 0 : 1 + braces.Length))
                {
                    p.Add($"{s.Name}: {joints.arraySize} joints, expected {(s.Parent == null ? 0 : 1 + braces.Length)}");
                    continue;
                }
                for (var i = 0; i < joints.arraySize; i++)
                {
                    var joint = joints.GetArrayElementAtIndex(i);
                    var to = i == 0 ? s.Parent : braces[i - 1].To;
                    var tensor = i == 0 ? null : b.Part(braces[i - 1].Tensor);
                    if (joint.FindPropertyRelative("connectedPart").objectReferenceValue != b.Part(to))
                        p.Add($"{s.Name}: joint {i} isn't to {to}");
                    if (joint.FindPropertyRelative("tensor").objectReferenceValue != tensor)
                        p.Add($"{s.Name}: joint {i}'s tensor isn't {(tensor == null ? "none" : tensor.name)}");
                    var jointClass = JointClassOf(spec[s.Name], i);
                    if (joint.FindPropertyRelative("breakForce").floatValue != JointForces[jointClass])
                        p.Add($"{s.Name}: joint {i} breaks at {joint.FindPropertyRelative("breakForce").floatValue}, not its {jointClass} class's {JointForces[jointClass]}");
                }
            }
            var families = SplitFamilies(b);
            foreach (var family in families)
            {
                var want = MeshEntry(b.Blockout, family.First()).Number("family_mass_kg");
                var got = family.Sum(n => b.Mass[n]);
                if (Mathf.Abs(got - want) > 0.5f)
                    p.Add($"{family.Key}: its pieces weigh {got:0.0} kg, the family {want:0.0}");
            }
            foreach (var n in families.SelectMany(f => f))
            {
                var marker = ((Transform)GetRef(b.Part(n), "centerOfMass")).position;
                var hulls = PreCarveBox(b, n, "mass_box_world");
                hulls.Expand(1e-4f);
                if (!hulls.Contains(marker)) p.Add($"{n}: its centre-of-mass marker lies outside its hulls' bounds");
            }
            var (empty, full) = Balance(b.Root);
            foreach (var (name, at, pin) in new[] { ("empty", empty, PinnedEmptyCg), ("full fuel", full, PinnedFullCg) })
                if (Mathf.Max(Mathf.Abs(at.x - pin.x), Mathf.Abs(at.y - pin.y), Mathf.Abs(at.z - pin.z)) > BalanceTolerance)
                    p.Add($"{name} centre of mass {at.ToString("F4")} is more than {BalanceTolerance} m from its pin {pin.ToString("F4")}");
            var damageType = Type.GetType("IDamageable, Assembly-CSharp");
            var registrations = (damageType == null ? 0 : b.Root.GetComponentsInChildren(damageType, true).Length) + LoadoutRegistrations;
            if (registrations > RegistrationLimit)
                p.Add($"{registrations} damage registrations at spawn, over {RegistrationLimit}");
            return $"{b.Specs.Count} parts on their tree joints, {Braces.Length} braces; {families.Length} split families weigh what they did, every marker inside its piece; " +
                $"centre of mass {empty.ToString("F4")} empty, {full.ToString("F4")} full (pins within {BalanceTolerance} m); {registrations} damage registrations at spawn";
        }

        // Batch entry, which authors nothing: pwsh tools/Build-Icarus.ps1 -ExecuteMethod Icarus.Editor.IcarusAuthor.BalanceFromBatch
        // logs the saved prefab's Balance, the values A22 pins.
        public static void BalanceFromBatch()
        {
            IcarusBuild.InitializeGameTasks();
            var (empty, full) = Balance(Load<GameObject>(PrefabPath));
            Debug.Log($"[Icarus] balance pins: empty ({empty.x:R}, {empty.y:R}, {empty.z:R}), full ({full.x:R}, {full.y:R}, {full.z:R})");
        }
    }
}
