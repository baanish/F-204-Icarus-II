using System.Collections.Generic;
using System.Text;
using BepInEx.Logging;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Every line the mod writes starts with "[Icarus]", so it greps out of LogOutput.log and player.log alike.
/// Info, Warning and Error are unbounded: for startup and one-shot lines only. Stage lines are bounded to one line per key
/// per second, with a 60 s summary of how often each key fired.
/// </summary>
public sealed class IcarusLog
{
    const float KeyIntervalS = 1f;
    const float SummaryIntervalS = 60f;

    sealed class StageKey
    {
        public float LastLoggedAt = float.NegativeInfinity;
        public int Count;
        public int Suppressed;
    }

    readonly ManualLogSource source;
    readonly Dictionary<string, StageKey> stages = new();
    float nextSummaryAt = SummaryIntervalS;

    public IcarusLog(ManualLogSource source) => this.source = source;

    /// <summary>Off drops stage lines and their summaries; Info, Warning and Error still print.</summary>
    public bool StageEnabled { get; set; } = true;

    public void Info(string message) => source.LogInfo("[Icarus] " + message);

    public void Warning(string message) => source.LogWarning("[Icarus] " + message);

    public void Error(string message) => source.LogError("[Icarus] " + message);

    public void Stage(string key, string message)
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

        stage.Count++;
        float now = Time.unscaledTime;
        if (now - stage.LastLoggedAt < KeyIntervalS)
        {
            stage.Suppressed++;
            return;
        }

        stage.LastLoggedAt = now;
        source.LogInfo("[Icarus] " + key + ": " + message);
    }

    /// <summary>Called every frame; prints and resets the per-key counters once every 60 s when any key fired.</summary>
    public void Tick()
    {
        float now = Time.unscaledTime;
        if (now < nextSummaryAt)
        {
            return;
        }

        nextSummaryAt = now + SummaryIntervalS;
        StringBuilder? line = null;
        foreach (KeyValuePair<string, StageKey> entry in stages)
        {
            StageKey stage = entry.Value;
            if (stage.Count == 0)
            {
                continue;
            }

            line ??= new StringBuilder("[Icarus] last 60 s:");
            line.Append(' ').Append(entry.Key).Append('=').Append(stage.Count);
            if (stage.Suppressed > 0)
            {
                line.Append(" (").Append(stage.Suppressed).Append(" suppressed)");
            }

            stage.Count = 0;
            stage.Suppressed = 0;
        }

        if (line != null)
        {
            source.LogInfo(line.ToString());
        }
    }
}
