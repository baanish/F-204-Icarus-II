using System.Collections;
using System.Collections.Generic;
using System.Linq;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// Test support for BareMetalFirstPick, which acts only in the aircraft menu the runner never opens. [Diagnostics]
/// OpenAircraftMenu, set to an airbase's UniqueName, opens the menu there as the map's buttons do (GameplayUI.SelectAirbase,
/// then SelectAircraft) and shows the Icarus four times (AircraftSelectionMenu.SetSelectedType spawns a fresh preview and
/// runs LoadoutSelector.LoadDefaults): with no saved choice each show would draw its own random livery. After each it logs
/// the livery the menu chose, the livery texture the preview wears, which is what a dropped load gets wrong, and whether a
/// choice stayed saved for the Icarus, then one "done" line with the three lists. Switching diagnostics off stops it.
/// Its reflection runs only inside a probe, never at startup.
/// </summary>
static class AircraftMenuProbe
{
    const int Shows = 4;
    const float LoadWaitS = 4f;

    internal static void Install(ConfigFile config, MonoBehaviour host)
    {
        if (!IcarusPlugin.Log.StageEnabled) return;
        var airbase = config.Bind("Diagnostics", "OpenAircraftMenu", "",
            "Test support: set to an airbase's UniqueName to open the aircraft menu there and log the Icarus's first livery");
        airbase.SettingChanged += (_, _) =>
        {
            if (IcarusPlugin.Log.StageEnabled && airbase.Value != "") host.StartCoroutine(Probe(airbase.Value));
        };
    }

    static IEnumerator Probe(string name)
    {
        var previewOf = AccessTools.FieldRefAccess<AircraftSelectionMenu, Aircraft>("previewAircraft");
        var selectorOf = AccessTools.FieldRefAccess<AircraftSelectionMenu, LoadoutSelector>("loadoutSelector");
        var offeredBy = AccessTools.FieldRefAccess<AircraftSelectionMenu, List<AircraftDefinition>>("aircraftSelection");
        var at = FactionRegistry.airbaseLookup.Values.FirstOrDefault(a => a != null && a.SavedAirbase?.UniqueName == name);
        var definition = Encyclopedia.Lookup != null && Encyclopedia.Lookup.TryGetValue(IcarusPlugin.JsonKey, out var found)
            ? found as AircraftDefinition : null;
        if (at == null || definition == null)
        {
            IcarusPlugin.Log.Info($"menu-livery: no airbase {name} or no Icarus definition");
            yield break;
        }
        var ui = SceneSingleton<GameplayUI>.i;
        ui.SelectAirbase(at);
        ui.SelectAircraft();
        var menu = Object.FindObjectOfType<AircraftSelectionMenu>();
        if (menu == null || !offeredBy(menu).Contains(definition))
        {
            IcarusPlugin.Log.Info($"menu-livery: {name} opened no menu offering the Icarus");
            yield break;
        }
        string faction = at.CurrentHQ.faction.factionName;
        var chosen = new List<string>();
        var worn = new List<string>();
        var saved = new List<string>();
        for (int i = 1; i <= Shows; i++)
        {
            menu.SetSelectedType(definition);
            yield return new WaitForSecondsRealtime(LoadWaitS);
            if (!IcarusPlugin.Log.StageEnabled || menu == null) yield break;
            var key = selectorOf(menu).CurrentLivery;
            chosen.Add(key.Type == LiveryKey.KeyType.Builtin ? definition.aircraftParameters.liveries[key.Index].name : key.ToString());
            var skin = previewOf(menu)?.GetComponentsInChildren<MeshRenderer>()
                .Select(r => r.sharedMaterial).FirstOrDefault(m => m != null && m.HasProperty("_Livery") && m.GetTexture("_Livery") != null);
            worn.Add(skin != null ? skin.GetTexture("_Livery").name : "none");
            saved.Add(GameManager.aircraftCustomization.ContainsKey(definition) ? "yes" : "no");
            IcarusPlugin.Log.Info($"menu-livery {faction} {i}: chose {chosen[i - 1]}, wears {worn[i - 1]}, saved {saved[i - 1]}");
        }
        IcarusPlugin.Log.Info($"menu-livery {faction} done: chose {string.Join(",", chosen)}; wore {string.Join(",", worn)}; saved {string.Join(",", saved)}");
    }
}
