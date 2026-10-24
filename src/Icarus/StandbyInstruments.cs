using System.Linq;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Turns the cockpit's live instruments: the standby attitude indicator's ball, steady in pitch and roll about the
/// instrument case's own axes as ArtificialHorizon reads the attitude, the fuel gauge's needle, and the clock's hands
/// from the game's time of day. The export builds each as its own mesh with its origin on its pivot, the ball's horizon
/// across its window and every needle pointing straight up (art/blender/cockpit_front.py STANDBY and NEEDLES). The game
/// draws them only in the cockpit view, and they turn only while drawn.
/// </summary>
sealed class StandbyInstruments : MonoBehaviour
{
    // The stem the standby indicator stands on leans back this far from upright (art/blender/cockpit_front.py TILT): the
    // case's axes are the aircraft's turned this far about its lateral axis, so the ball rolls about the window's centre.
    const float CaseTiltDeg = 25f;

    // The fuel scale, degrees clockwise from straight up (art/blender/cockpit_atlas.py dial_fuel): E at -135, F at +135.
    const float FuelEmptyDeg = -135f, FuelSweepDeg = 270f;

    sealed class Needle
    {
        public Transform Pivot = null!;
        public Quaternion Rest;
        public Vector3 Clockwise; // the axis, in the needle's own frame, a positive turn about which goes clockwise
    }

    Aircraft aircraft = null!;
    Transform ball = null!;
    Renderer shown = null!;
    Needle? fuel, hour, minute;
    Quaternion aircraftInParent, ballRest;
    readonly Quaternion caseTilt = Quaternion.AngleAxis(CaseTiltDeg, Vector3.right);

    void Start()
    {
        aircraft = GetComponent<Aircraft>();
        // Complex physics unparents the parts from the root, so the cockpit's meshes are found under the parts.
        var all = IcarusSystems.Parts(aircraft).SelectMany(p => p.GetComponentsInChildren<Transform>(true)).ToArray();
        Transform? Find(string name) => all.FirstOrDefault(t => t.name == name);
        Transform? found = Find("cockpit_standby_ball");
        if (found == null || found.parent == null)
        {
            IcarusPlugin.Log.Error("standby instruments: no cockpit_standby_ball; the ball, fuel needle and clock stay still");
            enabled = false;
            return;
        }

        ball = found;
        shown = ball.GetComponent<Renderer>();
        aircraftInParent = Quaternion.Inverse(ball.parent.rotation) * aircraft.transform.rotation;
        ballRest = Quaternion.Inverse(aircraft.transform.rotation) * ball.rotation;
        fuel = Pointer(Find("cockpit_fuel_needle"));
        hour = Pointer(Find("cockpit_clock_hour"));
        minute = Pointer(Find("cockpit_clock_minute"));
        IcarusPlugin.Log.Stage("instruments", $"standby instruments: ball, fuel needle {fuel != null}, clock hands {hour != null && minute != null}");
    }

    // A needle's axis: its mesh is the needle's top faces only, so their mean normal is the dial's, out toward the pilot.
    // Which way about it is clockwise is measured: a quarter turn from straight up must bring the tip to the pilot's right.
    Needle? Pointer(Transform? t)
    {
        Mesh? mesh = t != null ? t.GetComponent<MeshFilter>()?.sharedMesh : null;
        if (t == null || mesh == null)
        {
            IcarusPlugin.Log.Error($"standby instruments: missing {(t == null ? "needle" : t.name + "'s mesh")}; it stays still");
            return null;
        }

        Vector3 axis = mesh.normals.Aggregate(Vector3.zero, (a, n) => a + n).normalized;
        Vector3 tip = mesh.vertices.OrderByDescending(v => v.sqrMagnitude).First();
        Vector3 turned = t.TransformDirection(Quaternion.AngleAxis(90f, axis) * tip);
        if (Vector3.Dot(turned, aircraft.transform.right) < 0f) axis = -axis;
        return new Needle { Pivot = t, Rest = t.localRotation, Clockwise = axis };
    }

    static void Turn(Needle? needle, float degrees)
    {
        if (needle != null) needle.Pivot.localRotation = needle.Rest * Quaternion.AngleAxis(degrees, needle.Clockwise);
    }

    void LateUpdate()
    {
        if (!shown.enabled) return;
        // The aircraft's attitude without its heading, as the cockpit (which may have broken away) carries it.
        Quaternion attitude = ball.parent.rotation * aircraftInParent;
        Vector3 forward = attitude * Vector3.forward;
        Vector3 flat = Vector3.ProjectOnPlane(forward, Vector3.up);
        if (flat.sqrMagnitude < 1e-4f) flat = Vector3.ProjectOnPlane(attitude * (forward.y > 0f ? Vector3.down : Vector3.up), Vector3.up);
        Quaternion level = Quaternion.Inverse(Quaternion.LookRotation(flat, Vector3.up)) * attitude;
        // A world-steady ball turns against the attitude; about the case's axes, so its horizon rolls round the window.
        ball.rotation = attitude * caseTilt * Quaternion.Inverse(level) * Quaternion.Inverse(caseTilt) * ballRest;

        Turn(fuel, FuelEmptyDeg + FuelSweepDeg * Mathf.Clamp01(aircraft.GetFuelLevel()));
        LevelInfo? info = NetworkSceneSingleton<LevelInfo>.i;
        if (info != null)
        {
            float hours = info.timeOfDay;
            Turn(hour, (hours % 12f) * 30f);
            Turn(minute, (hours % 1f) * 360f);
        }
    }
}
