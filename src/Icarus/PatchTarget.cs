using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace Icarus;

/// <summary>
/// One Harmony patch the mod wants, named by the feature it serves. The game method is looked up by name, so a game
/// update that renames or removes it switches that feature off instead of failing the plugin.
/// </summary>
public sealed class PatchTarget
{
    public PatchTarget(string feature, Type type, string method, Type[]? parameters = null, MethodInfo? prefix = null, MethodInfo? postfix = null, MethodInfo? transpiler = null, bool diagnostic = false)
    {
        Feature = feature;
        Type = type;
        Method = method;
        Parameters = parameters;
        Prefix = prefix;
        Postfix = postfix;
        Transpiler = transpiler;
        Diagnostic = diagnostic;
    }

    public string Feature { get; }
    public Type Type { get; }
    public string Method { get; }
    public Type[]? Parameters { get; }
    public MethodInfo? Prefix { get; }
    public MethodInfo? Postfix { get; }
    public MethodInfo? Transpiler { get; }
    /// <summary>Exists only to measure or log: installed only when Diagnostics.StageLogging is on at startup, so players
    /// run no diagnostic hooks (AGENTS.md rule 12).</summary>
    public bool Diagnostic { get; }

    string Name => Type.Name + "." + Method;

    /// <summary>
    /// Patches enabled targets and reports failures. Returns the features switched off, so their code can stand down.
    /// </summary>
    public static HashSet<string> InstallAll(Harmony harmony, IReadOnlyList<PatchTarget> targets, IcarusLog log)
    {
        var off = new HashSet<string>();
        var installed = new List<(PatchTarget Target, MethodInfo Original)>();
        foreach (PatchTarget target in targets)
        {
            if (target.Diagnostic && !log.StageEnabled)
            {
                off.Add(target.Feature);
                continue;
            }
            if (off.Contains(target.Feature)) continue;
            try
            {
                MethodInfo? original = AccessTools.DeclaredMethod(target.Type, target.Method, target.Parameters);
                if (original == null) throw new MissingMethodException(target.Type.FullName, target.Method);
                installed.Add((target, original));
                harmony.Patch(
                    original,
                    target.Prefix == null ? null : new HarmonyMethod(target.Prefix),
                    target.Postfix == null ? null : new HarmonyMethod(target.Postfix),
                    target.Transpiler == null ? null : new HarmonyMethod(target.Transpiler));
            }
            catch (Exception e)
            {
                off.Add(target.Feature);
                for (int i = installed.Count - 1; i >= 0; i--)
                {
                    var entry = installed[i];
                    if (entry.Target.Feature != target.Feature) continue;
                    foreach (MethodInfo? patch in new[] { entry.Target.Prefix, entry.Target.Postfix, entry.Target.Transpiler })
                    {
                        if (patch != null) harmony.Unpatch(entry.Original, patch);
                    }
                }
                log.Error($"patch {target.Feature}: {target.Name} failed to patch: feature off ({e.GetType().Name}: {e.Message})");
            }
        }

        int diagnosticCount = 0;
        foreach (var entry in installed)
            if (entry.Target.Diagnostic && !off.Contains(entry.Target.Feature)) diagnosticCount++;
        log.Info($"diagnostic patches: {diagnosticCount} installed (StageLogging={log.StageEnabled})");
        return off;
    }
}
