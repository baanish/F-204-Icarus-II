using System.Linq;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace Icarus;

/// <summary>
/// The inner canopy panes, the glass the cockpit view draws, wear the stock fighter1_canopy_int, whose grime layer
/// (canopyGrime at intensity 0.8) catches the sun as a bright veil over the whole canopy wrapped round the pilot, so
/// towards the sun the view whites out. Each Icarus's own copy of that material drops the grime, which keeps the tint,
/// the faint scratches and the frame but no veil (smoothness 0 and scratches 0 each left the veil in place). The copy is
/// Renderer.material, the one Canopy cracks (it sets _Cracked_Amount there), so the panes still crack. A grime-free
/// variant can't ship in the bundle: Blueprinter can't patch the game's glass and crack textures into a mod material.
/// IcarusAuthor's A15 keeps the panes on the stock material and in the Canopy's glassRenderers.
/// </summary>
static class InnerGlass
{
    static readonly FieldInfo Canopies = AccessTools.Field(typeof(Aircraft), "canopies");
    static readonly FieldInfo GlassRenderers = AccessTools.Field(typeof(Canopy), "glassRenderers");

    internal static void RemoveGrime(Aircraft aircraft)
    {
        Renderer[] panes = ((Canopy[])Canopies.GetValue(aircraft)).Where(c => c != null)
            .SelectMany(c => (Renderer[])GlassRenderers.GetValue(c)).Where(r => r != null).ToArray();
        if (panes.Length == 0)
        {
            IcarusPlugin.Log.Error("inner glass: no canopy glass renderers; the panes keep the stock grime");
            return;
        }

        foreach (Renderer pane in panes)
        {
            pane.material.SetFloat("_Grime_Intensity", 0f);
        }
    }
}
