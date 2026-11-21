namespace Icarus;

/// <summary>
/// Gives the Icarus a Steam Workshop tag, so players can share its liveries through the game's own uploader: that
/// refuses a livery whose aircraft has no tag (AircraftLiveryMod.TryGetItem) and otherwise sends the tag to Steam beside
/// "Aircraft Livery". Like every stock aircraft's, the tag is the display name. The authored definition cannot carry it:
/// the Unity project's game library predates UnitDefinition.WorkshopTag, so the field is never serialized. So the tag is
/// set here, once, by assignment, as soon as Blueprinter has put the Icarus in the encyclopedia; a tag the definition
/// already has is kept. Subscribed liveries are matched by their meta.json's AircraftKey, not by this tag.
/// </summary>
static class LiveryWorkshopTag
{
    public const string Tag = "F-204 Icarus II";

    static bool applied;

    internal static void Update(IcarusLog log)
    {
        if (applied || Encyclopedia.Lookup == null ||
            !Encyclopedia.Lookup.TryGetValue(IcarusPlugin.JsonKey, out UnitDefinition definition)) return;
        applied = true;
        if (string.IsNullOrEmpty(definition.WorkshopTag)) definition.WorkshopTag = Tag;
        log.Info($"workshop tag: {definition.jsonKey} liveries upload tagged '{definition.WorkshopTag}'");
    }
}
