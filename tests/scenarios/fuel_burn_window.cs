using System;
using System.Text.Json;
using NoAgenticFramework.Shared;

public static class FuelBurnChecks
{
    // Judge the first empty sample against the burn mark, including samples between scenario commands.
    public static Reading FuelBurnWindow(TraceRecord sample, ConditionScope scope, JsonElement args)
    {
        var from = scope.Since(args.GetProperty("since").GetString(), sample.T);
        if (from is null)
            return new Reading(false, double.NegativeInfinity, "burn mark missing");
        double start = scope.OpenedAt(from.Value);
        double min = args.GetProperty("min_s").GetDouble(), max = args.GetProperty("max_s").GetDouble();
        double fuel = double.NaN;
        for (int i = from.Value; i < scope.Records.Count; i++)
        {
            var row = scope.Records[i];
            if (row.T > sample.T || row.Kind != RecordKinds.Sample
                || !row.Fields.TryGetValue("own.fuel_frac", out var value) || value is not double fraction)
                continue;
            fuel = fraction;
            if (fuel <= 0.002 && row.T - start < min)
                return new Reading(false, row.T - start - min, $"fuel reached {fuel:F4} before {min:F0} s");
            if (fuel < 0.002)
            {
                double elapsed = row.T - start, margin = Math.Min(elapsed - min, max - elapsed);
                return new Reading(margin >= 0, margin, $"first empty fuel sample at {elapsed:F2} s; required {min:F0} to {max:F0} s");
            }
        }
        double now = sample.T - start;
        return new Reading(false, -Math.Max(0.001, Math.Abs(max - now)), $"fuel {fuel:F4} after {now:F2} s; must empty by {max:F0} s");
    }
}
