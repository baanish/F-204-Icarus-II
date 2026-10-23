using System.Collections.Generic;
using UnityEngine;
using static System.FormattableString;

namespace Icarus;

/// <summary>
/// A stage line for each missile an Icarus fires, a second after the game spawns it: where it spawned, where its motor
/// lit and its path at quarter seconds, from the aircraft in its root frame (+x right, +y up, +z forward). The game spawns
/// a rail-launched missile where its rail ends (MountedMissile.RailLaunch), so on the conformal stations this is how far
/// below the trough the motor burns. Observes only, through Unit.onRegisterMissile;
/// tests/scenarios/icarus_conformal_eject.scenario.jsonc reads it.
/// </summary>
sealed class EjectLog : MonoBehaviour
{
    const float PathS = 1f, StepS = 0.25f;

    sealed class Flight
    {
        public Missile Missile = null!;
        public float Age;
        public string? Lit;
        public readonly List<string> Path = new();
    }

    readonly List<Flight> flights = new();
    Aircraft aircraft = null!;

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        aircraft.onRegisterMissile += Launched;
    }

    void OnDestroy()
    {
        if (aircraft != null) aircraft.onRegisterMissile -= Launched;
    }

    void Launched(Missile missile)
    {
        var flight = new Flight { Missile = missile };
        flight.Path.Add(Offset(missile));
        flights.Add(flight);
    }

    string Offset(Missile missile)
    {
        Vector3 at = aircraft.transform.InverseTransformPoint(missile.transform.position);
        return Invariant($"({at.x:+0.00;-0.00}, {at.y:+0.00;-0.00}, {at.z:+0.00;-0.00})");
    }

    void FixedUpdate()
    {
        for (int i = flights.Count - 1; i >= 0; i--)
        {
            Flight flight = flights[i];
            if (flight.Missile == null || aircraft == null)
            {
                flights.RemoveAt(i);
                continue;
            }

            flight.Age += Time.fixedDeltaTime;
            if (flight.Lit == null && flight.Missile.EngineOn()) flight.Lit = Invariant($"{flight.Age:0.00} s after spawn at {Offset(flight.Missile)}");
            if (flight.Age >= StepS * flight.Path.Count) flight.Path.Add(Invariant($"{flight.Age:0.00} s {Offset(flight.Missile)}"));
            if (flight.Age < PathS) continue;
            IcarusPlugin.Log.Stage($"eject {flight.Missile.persistentID.Id}",
                $"{flight.Missile.definition.jsonKey} spawned at {flight.Path[0]} m; motor lit {flight.Lit ?? "not yet"}; path {string.Join(", ", flight.Path.GetRange(1, flight.Path.Count - 1))}");
            flights.RemoveAt(i);
        }
    }
}
