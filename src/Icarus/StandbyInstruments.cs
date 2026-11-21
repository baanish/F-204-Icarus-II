using UnityEngine;

namespace Icarus;

/// <summary>
/// Turns the cockpit's live instruments: the standby attitude indicator's ball, steady in pitch and roll about the
/// instrument case's own axes as ArtificialHorizon reads the attitude, the fuel gauge's needle, the clock's hands
/// from the game's time of day, and shortens the tip tank tape's bars to the fuel left in each tank. The export builds
/// each as its own mesh with its origin on its pivot, the ball's horizon across its window, every needle pointing
/// straight up and every bar full (art/blender/cockpit_front.py STANDBY, NEEDLES and TIP_BARS). The game draws them
/// only in the cockpit view, and they move only while drawn.
/// </summary>
sealed class StandbyInstruments : MonoBehaviour
{
    // The stem the standby indicator stands on leans back this far from upright (art/blender/cockpit_front.py TILT): the
    // case's axes are the aircraft's turned this far about its lateral axis, so the ball rolls about the window's centre.
    const float CaseTiltDeg = 25f;

    // The fuel scale, degrees clockwise from straight up (art/blender/cockpit_atlas.py dial_fuel): E at -135, F at +135.
    const float FuelEmptyDeg = -135f, FuelSweepDeg = 270f;

    [SerializeField] Renderer shown = null!;
    [SerializeField] Transform fuel = null!, hour = null!, minute = null!;
    [SerializeField] Transform tipLeft = null!, tipRight = null!;

    Aircraft aircraft = null!;
    Transform ball = null!;
    TipTanks? tips;
    Quaternion aircraftInParent, ballRest, fuelRest, hourRest, minuteRest;
    readonly Quaternion caseTilt = Quaternion.AngleAxis(CaseTiltDeg, Vector3.right);

    void Start()
    {
        aircraft = GetComponent<Aircraft>();
        if (shown == null || fuel == null || hour == null || minute == null || tipLeft == null || tipRight == null)
        {
            IcarusPlugin.Log.Error("standby instruments: missing cockpit instrument references; the instruments stay still");
            enabled = false;
            return;
        }

        ball = shown.transform;
        aircraftInParent = Quaternion.Inverse(ball.parent.rotation) * aircraft.transform.rotation;
        ballRest = Quaternion.Inverse(aircraft.transform.rotation) * ball.rotation;
        fuelRest = fuel.localRotation;
        hourRest = hour.localRotation;
        minuteRest = minute.localRotation;
        tips = GetComponent<TipTanks>();
    }

    static void Fill(Transform foot, float share)
    {
        foot.localScale = new Vector3(1f, Mathf.Clamp01(share), 1f);
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

        fuel.localRotation = fuelRest * Quaternion.AngleAxis(FuelEmptyDeg + FuelSweepDeg * Mathf.Clamp01(aircraft.GetFuelLevel()), Vector3.forward);
        Fill(tipLeft, tips != null ? tips.Fill("L") : 0f);
        Fill(tipRight, tips != null ? tips.Fill("R") : 0f);
        LevelInfo? info = NetworkSceneSingleton<LevelInfo>.i;
        if (info != null)
        {
            float hours = info.timeOfDay;
            hour.localRotation = hourRest * Quaternion.AngleAxis((hours % 12f) * 30f, Vector3.forward);
            minute.localRotation = minuteRest * Quaternion.AngleAxis((hours % 1f) * 360f, Vector3.forward);
        }
    }
}
