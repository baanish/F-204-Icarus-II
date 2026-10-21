"""Weapon stations: the inner wing pylon blades and their plugs, and the hooks the fuselage skin and the collider
patches ask for the conformal trough.

One blade hangs under each wing at a fraction of the span from the root row to the tip. Each carries one mount, which
the game hangs from the hardpoint at the pylon's lower edge. The wingtip stations have no blade or rail: every mount
brings its own launch rail, which bears straight on the tip face. The game hides an empty station's blade and shows its
plug instead, a stub on the blade's root footprint standing "plug" metres below the wing. The hardpoints themselves are
placed by the Unity author (IcarusAuthor.Stations.cs), which holds them to their measured positions.
"""
from mathutils import Vector

import build_icarus as bi

PYLONS = {"inner": 0.45, "length": 1.5, "depth": 0.26, "thickness": 0.10, "rake": 0.30, "bury": 0.03, "plug": 0.03}
# The conformal trough's per-station profile; None while the belly has no trough.
TROUGH = None
# Object names the other modules and the Unity author build against.
BLADES = ("pylon_inner_L", "pylon_inner_R")
PLUGS = ("pylon_inner_plug_L", "pylon_inner_plug_R")
# part name -> (parent, dry mass kg); parts.full_tree adds these to its own
TREE = {
    "pylon_inner_L": ("wing_spar_L", 0),
    "pylon_inner_R": ("wing_spar_R", 0),
    "pylon_inner_plug_L": ("wing_spar_L", 0),
    "pylon_inner_plug_R": ("wing_spar_R", 0),
}
# Triangles per component: target and cap (budget.py sums them).
BUDGET = {
    "blades": {"target": 800, "cap": 800, "objects": BLADES},
    "plugs": {"target": 64, "cap": 64, "objects": PLUGS},
}
CLOSEUPS = {}


def build(p, mats):
    return pylons(p, mats["body"])


def check(icarus):
    return None


def carve_shapes(p, s):
    """Fields (x, z) -> signed distance, negative inside, that build_icarus.blended_ring cuts out of the skin at
    station s."""
    return []


def collider_splits():
    """Planes (point, normal), Blender world space, that no skin collider patch may cross (hulls.groups)."""
    return []


def wing_at(w, x):
    """The wing section (s of the leading edge, z of the chord line, chord) at spanwise x, between planform rows."""
    sections = bi.wing_sections(w)
    for (le0, x0, z0, c0), (le1, x1, z1, c1) in zip(sections, sections[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return le0 + t * (le1 - le0), z0 + t * (z1 - z0), c0 + t * (c1 - c0)
    raise ValueError("x %.2f is outside the wing" % x)


def slab(name, s0, s1, x, z_top, depth, thick, rake, mat):
    """A vertical blade along s, its top at z_top and its lower edge raked back from the front by rake."""
    profile = [bi.P(s0, x, z_top), bi.P(s1, x, z_top), bi.P(s1 - rake / 3, x, z_top - depth), bi.P(s0 + rake, x, z_top - depth)]
    half = Vector((thick / 2, 0, 0))
    v = [q - half for q in profile] + [q + half for q in profile]
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    obj = bi.finish(bi.mesh_object(name, v, f), mat, smooth=False)
    obj["role"] = "pylon"
    return obj


def fixed_box(p, x):
    """Chord fractions (front, back) of the fixed wing box at spanwise x, the same limits build_icarus.box_stations
    leaves between the leading-edge devices and trailing-edge surfaces."""
    gap, front, back = p["surface_gap"], 0.0, 1.0
    for _, a, b, c0, c1 in p["wing_surfaces"]:
        if a - gap / 2 <= x <= b + gap / 2:
            if c0 == 0.0:
                front = max(front, c1 + gap / 2)
            else:
                back = min(back, c0 - gap / 2)
    return front, back


def pylons(p, mat):
    """The inner wing pylons and their plugs."""
    w, y = p["wing"], PYLONS
    root_x, tip_x = w["planform"][0][1], w["planform"][-1][1]
    parts = []
    for side, suffix in ((1, "_L"), (-1, "_R")):
        x = root_x + y["inner"] * (tip_x - root_x)
        le, z, chord = wing_at(w, x)
        low = z - 0.5 * w["thickness"] * chord
        length = min(y["length"], 0.75 * chord)
        # The blade's buried root stays on the fixed box, clear of the moving surfaces and the space they sweep.
        front, back = fixed_box(p, x)
        s0 = max(le + front * chord, le + 0.45 * chord - length / 2)
        s1 = min(le + back * chord, le + 0.45 * chord + length / 2)
        parts.append(slab("pylon_inner%s" % suffix, s0, s1, side * x, low + y["bury"],
                          y["depth"] + y["bury"], y["thickness"], y["rake"], mat))
        parts.append(slab("pylon_inner_plug%s" % suffix, s0, s1, side * x, low + y["bury"],
                          y["plug"] + y["bury"], y["thickness"], 0.0, mat))
    return parts
