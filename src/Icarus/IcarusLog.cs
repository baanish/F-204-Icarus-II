using System.Collections.Generic;
using BepInEx.Logging;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Every line the mod writes starts with "[Icarus]", so it greps out of LogOutput.log and player.log alike.
/// Info, Warning and Error are unbounded: for startup and one-shot lines only. Stage lines are bounded to one line per key
/// per second.
/// </summary>
public sealed class IcarusLog
{
    const float KeyIntervalS = 1f;

    sealed class StageKey
    {
        public float LastLoggedAt = float.NegativeInfinity;
    }

    readonly ManualLogSource source;
    readonly Dictionary<string, StageKey> stages = new();

    public IcarusLog(ManualLogSource source) => this.source = source;

    /// <summary>Off drops stage lines; Info, Warning and Error still print.</summary>
    public bool StageEnabled { get; set; }

    public void Info(string message) => source.LogInfo("[Icarus] " + message);

    public void Warning(string message) => source.LogWarning("[Icarus] " + message);

    public void Error(string message) => source.LogError("[Icarus] " + message);

    public void Stage(string key, string message, bool everyOccurrence = false)
    {
        if (!StageEnabled)
        {
            return;
        }

        if (!stages.TryGetValue(key, out StageKey stage))
        {
            stage = new StageKey();
            stages.Add(key, stage);
        }

        float now = Time.unscaledTime;
        if (!everyOccurrence && now - stage.LastLoggedAt < KeyIntervalS)
        {
            return;
        }

        stage.LastLoggedAt = now;
        source.LogInfo("[Icarus] " + key + ": " + message);
    }
}
