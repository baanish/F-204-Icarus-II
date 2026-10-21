"""The cockpit interior, built on the canopy's design eye (canopy.EYE). Nothing is built here yet: the Unity author
places the Revoker's interior (IcarusAuthor.Cockpit.cs).
"""
# Object names the other modules and the Unity author build against. Renderers drawn in the cockpit view (layer 3)
# carry role "cockpit_view"; the proxies, seen from outside, carry "visual". Role "cockpit" is the cockpit_cell part.
INTERIOR = "cockpit_interior"
FRAMES_INNER = ("windscreen_frame_inner", "canopy_frame_inner")
TAC_SCREEN, WARNING_LAMPS = "cockpit_tac_screen", "cockpit_warning_lamps"
PROXIES = ("cockpit_proxy", "canopy_frame_proxy")
PIVOTS = ("cockpit_stick_pivot", "cockpit_throttle_pivot")  # empties the stock stick and throttle hang from
# Triangles per renderer: target and cap (budget.py sums them). The cockpit's hard limit is 35,000 in all; the stock
# stick (1,890) and throttle (880) count toward it but are not built here. The warning lamps (40 to 80) and the stock
# seat count toward no total.
BUDGET = {
    "interior": {"target": 12500, "cap": 13500, "objects": (INTERIOR,), "cockpit": True},
    "canopy_frame_inner": {"target": 2600, "cap": 8000, "objects": ("canopy_frame_inner",), "cockpit": True},
    "windscreen_frame_inner": {"target": 1000, "cap": 1000, "objects": ("windscreen_frame_inner",), "cockpit": True},
    "tac_screen": {"target": 120, "cap": 120, "objects": (TAC_SCREEN,), "cockpit": True},
    "stock_hotas": {"target": 2770, "cap": 2770, "objects": (), "cockpit": True},
    "proxies": {"target": 940, "cap": 2930, "objects": PROXIES},
}
CLOSEUPS = {}


def build(p, mats):
    return []


def check(icarus):
    return None
