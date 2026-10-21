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
        private static string CheckGear(Build b, List<string> p)
        {
            var gears = All(b, "LandingGear");
            if (gears.Length != 3) p.Add(gears.Length + " LandingGears");
            foreach (var g in gears)
            {
                var so = new SerializedObject(g);
                // The gear rides its leg's mount on the part that leg hangs on, and pushes on that part.
                Transform Mount(string l) => b.Parts[b.Specs.First(s => s.Name == l).Parent].transform.Find(l + "_mount");
                var leg = Legs.FirstOrDefault(l => Mount(l.Leg) != null && g.transform.IsChildOf(Mount(l.Leg)));
                var part = leg.Leg == null ? null : Mount(leg.Leg);
                var carrierPart = Prop(so, "attachedPart").objectReferenceValue as Component;
                if (part == null) p.Add(g.name + " isn't on a gear leg mount");
                else if (carrierPart == null || carrierPart.transform != part.parent) p.Add(g.name + " doesn't push on the part its rig rides");
                foreach (var field in new[] { "bumpStop", "unsprung", "axle", "gearCollider", "gearHinge", "tireNoiseSound", "tireSkidSound" })
                    if (Prop(so, field).objectReferenceValue == null) p.Add($"{g.name}.{field} is null");
                var wheels = GetList(Prop(so, "wheels")).Cast<Transform>().ToArray();
                if (wheels.Length == 0 || wheels.Any(w => w == null)) p.Add(g.name + " has no wheel or a null one");
                var hinge = Prop(so, "gearHinge").objectReferenceValue as Transform;
                if (part == null || carrierPart == null || hinge == null || wheels.Length == 0 || wheels[0] == null)
                    continue;
                if (!hinge.IsChildOf(part.transform) || Quaternion.Angle(hinge.localRotation, Quaternion.identity) > 0.01f)
                    p.Add(g.name + "'s gear hinge isn't at rest on its leg mount");
                // A negative fold reads back near 360 through localEulerAngles.x as the leg locks down, which LandingGear
                // takes for a broken wheel above 10 degrees.
                if (Prop(so, "foldDegrees").floatValue <= 0f) p.Add($"{g.name} folds {Prop(so, "foldDegrees").floatValue} deg; stowing must be a positive turn");
                // BreakWheel takes the leg's mass from its carrier's Rigidbody.
                var carrier = GetFloat(carrierPart, "mass");
                if (Prop(so, "mass").floatValue <= 0f || Prop(so, "mass").floatValue >= carrier)
                    p.Add($"{g.name} breaks off with {Prop(so, "mass").floatValue} kg of its {carrier} kg carrier");
                if (leg.Doors == null || Prop(so, "gearDoors").arraySize != leg.Doors.Length) p.Add($"{g.name} lists {Prop(so, "gearDoors").arraySize} doors");
                // Stowing must carry the wheel up into the airframe.
                var down = wheels[0].position;
                hinge.localRotation = Quaternion.Euler(Prop(so, "foldDegrees").floatValue, 0, 0);
                var up = wheels[0].position;
                hinge.localRotation = Quaternion.identity;
                if (up.y - down.y < 0.2f) p.Add($"{g.name} stows its wheel {up.y - down.y:F2} m higher, not up into the airframe");
            }
            // Each leg's ground cast, castPoint down suspensionTravel, must meet no collider of the aircraft.
            Physics.SyncTransforms();
            var airframe = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger && c.gameObject.layer != IgnoreCollisionsLayer && !(c is MeshCollider m && m.sharedMesh == null)).ToArray();
            foreach (var g in gears)
            {
                var so = new SerializedObject(g);
                var cast = Prop(so, "castPoint").objectReferenceValue as Transform ?? ((GameObject)Prop(so, "bumpStop").objectReferenceValue).transform;
                var travel = Prop(so, "suspensionTravel").floatValue;
                foreach (var c in airframe)
                    if (c.Raycast(new Ray(cast.position, -cast.up), out var hit, travel))
                        p.Add($"{g.name}'s ground cast meets {PathOf(c.transform, b.Root.transform)} {hit.distance:F2} m down");
            }
            if (Mathf.Abs(b.Size.y - F104Height) > 0.5f) p.Add($"stance {b.Size.y:F2} m tall on its gear, not near the F-104G's {F104Height}");
            var filter = b.Parts["cockpit_cell"].GetComponent(GameType("ControlsFilter"));
            var noseGear = gears.OrderByDescending(g => g.transform.position.z).FirstOrDefault();
            var links = new List<Object>();
            var it = new SerializedObject(filter).GetIterator();
            while (it.Next(true))
                if (it.propertyType == SerializedPropertyType.ObjectReference && it.objectReferenceValue != null && it.objectReferenceValue.GetType().Name == "LandingGear")
                    links.Add(it.objectReferenceValue);
            if (links.Count == 0 || links.Any(l => l != noseGear)) p.Add("ControlsFilter's nose gear link isn't the nose LandingGear");
            var contacts = Contacts(b);
            return $"{gears.Length} Revoker LandingGears driving the Icarus gear_leg hinges, wheels stow upward, doors listed, nose steering linked, {b.Size.y:F2} m tall at rest; free contacts {string.Join(", ", contacts.Select(c => c.Name + " " + c.Contact.ToString("F2")))}";
        }
    }
}
