using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEditor;
using Object = UnityEngine.Object;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // A16: the plugin's stock-mission supply (src/Icarus/StockMissionSupply.cs) keeps its own copies of the Icarus
        // jsonKey, the Revoker key its factories trade away and the faction it supplies; a drift between those and the
        // authored aircraft makes the supply silently do nothing. The livery, loadouts and hangars the AI needs are A13 and
        // A5; the factory table against the stock missions is tools/stock_supply.py.
        private static string CheckStockSupply(Object definition, List<string> p)
        {
            var plugin = AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a => a.GetName().Name == "Icarus");
            if (plugin == null)
            {
                p.Add("Icarus.dll isn't loaded in the editor (tools/Build-Icarus.ps1 copies it to Assets/Plugins)");
                return "no plugin";
            }
            object Const(string type, string name) =>
                plugin.GetType(type, true).GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)?.GetRawConstantValue()
                ?? throw new MissingFieldException(type, name);
            var pluginKey = (string)Const("Icarus.IcarusPlugin", "JsonKey");
            var revoker = (string)Const("Icarus.StockMissionSupply", "Revoker");
            var faction = (string)Const("Icarus.StockMissionSupply", "Faction");
            var reserve = (int)Const("Icarus.StockMissionSupply", "StartingReserve");
            var authored = Prop(new SerializedObject(definition), "jsonKey").stringValue;
            if (pluginKey != authored) p.Add($"the plugin supplies {pluginKey}, the aircraft is {authored}");
            var donorKey = Prop(new SerializedObject(Load<Object>(DonorDefinition)), "jsonKey").stringValue;
            if (revoker != donorKey) p.Add($"the plugin's factories trade away {revoker}, the Revoker is {donorKey}");
            var primeva = Prop(new SerializedObject(Load<Object>(Stock + "MonoBehaviour/Primeva_PLACEHOLDER.asset")), "factionName").stringValue;
            if (faction != primeva) p.Add($"the plugin supplies faction {faction}, the liveries are {primeva}'s");
            if (reserve <= 0) p.Add("StartingReserve " + reserve);
            return $"the plugin adds {reserve} {pluginKey} to {faction} and trades {revoker} factories for it";
        }
    }
}
