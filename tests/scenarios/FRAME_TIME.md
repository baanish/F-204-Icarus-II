# Compare frame time before accepting added cost

Run this queue at the first buildable change that adds parts, colliders, joints or per-frame code.
Build the plugin and content bundle first, as for the other scenarios. From the repo root:

```powershell
python tools/frame_gate.py --repeats 3 --manifest .cache/frame-gate/candidate.json
```

The queue alternates Icarus and FS-12 Revoker (`Fighter1`, the stock aircraft key):
one Icarus, one Revoker, eight Icarus, eight Revokers, repeated three times.
Each run uses uncapped rendering, the same camera, map, starting speed and half fuel.
The Icarus flies clean. The Revoker uses its stock default loadout, matching the stock comparison scenarios.
Equal fuel fractions do not mean equal aircraft masses.
With eight aircraft, seven AI wingmen start 400 m apart alongside the player's aircraft.
Only the player's aircraft receives the missile hit.

The four `frames_*.scenario.jsonc` files measure three windows: 10 seconds intact,
10 seconds immediately after the hit, then 30 seconds of debris.
A missed missile fails the run. The runner stops at any lint, setup, run or measurement failure.
It requires VSync off and a frame cap of 1000 FPS, the framework's `--uncapped` setting, or -1 for no cap.
It rejects incomplete windows. It does not impose an invented performance budget.
Review the measured cost against stock and against the previous build before continuing the change.

The table reports the median of each phase's run p95 values, not a pooled p95.
The ratio divides that median by the Revoker's median for the same phase and aircraft count.
Per-extra-jet milliseconds means `(eight-aircraft median - one-aircraft median) / 7`.
It includes AI and scene costs, so it is an incremental scene measurement rather than isolated aircraft CPU time.
Keep resolution, graphics settings and the content build fixed within a queue.
Use separate manifests for separate builds. A manifest lists only that queue's run folders, avoiding stale results.
To print a saved queue without launching the game:

```powershell
python tools/frame_gate.py --table-only --manifest .cache/frame-gate/candidate.json
```

Regenerate the four scenarios and two Revoker missions from the tracked missile-hit scenario and Icarus missions:

```powershell
python tests/scenarios/make_frame_scenarios.py
```

The Icarus plugin's `AgenticState()` diagnostic method exposes the active loadout under
`mods.baanish.icarus.loadout`. It joins mount keys in hardpoint-set order with `|`, preserving empty sets.
Three empty sets produce `||`; tip tanks alone produce `baanish_icarus_tip_tank||`.
Performance scenarios require that exact value before flying or recording. Missing telemetry fails setup too.
This checks the game's active loadout after default fallback, rather than trusting the mission's requested loadout.
The diagnostic method is sampled by the test framework and adds no update loop.
Manual launch scenarios have no automated measurement verdict; the framework's `launch` command ignores their steps.
