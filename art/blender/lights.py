"""Light empties and blade antennas. The Unity author puts the Revoker's lamps on the light empties
(IcarusAuthor.Systems.cs PlaceSystems).
"""
from mathutils import Matrix, Vector

import build_icarus as bi
import gear
import stations

LIGHTS = [  # (name, s, x, z, kind, colour)
    ("light_nav_L", None, None, None, "nav", "red"),  # at the left wingtip, placed from the wing
    ("light_nav_R", None, None, None, "nav", "green"),
    ("light_beacon_top", 15.20, 0.0, 2.90, "anticollision", "red"),
    ("light_beacon_belly", 9.00, 0.0, -0.40, "anticollision", "red"),
    ("light_formation_L", 6.30, 0.95, 0.30, "formation", "green"),
    ("light_formation_R", 6.30, -0.95, 0.30, "formation", "green"),
    ("light_landing", None, None, None, "landing", "white"),  # on the nose leg
]
ANTENNAS = [  # (name, s, z of root, height, chord, which side: top or belly)
    ("antenna_uhf_top", 7.20, None, 0.20, 0.30, "top"),
    ("antenna_iff_belly", 6.40, None, 0.15, 0.22, "belly"),
    ("antenna_datalink_top", 11.60, None, 0.16, 0.26, "top"),
]
# part name -> (parent, dry mass kg); parts.full_tree adds these to its own
TREE = {
    "light_nav_L": ("wing_skin_L", 0),
    "light_nav_R": ("wing_skin_R", 0),
    "light_beacon_top": ("fin_skin", 0),
    "light_beacon_belly": ("fuselage_mid", 0),
    "light_formation_L": ("skin_mid_L", 0),
    "light_formation_R": ("skin_mid_R", 0),
    "light_landing": ("gear_leg_N", 0),
    "antenna_uhf_top": ("dorsal_cover", 0),
    "antenna_iff_belly": ("skin_mid_L", 0),
    "antenna_datalink_top": ("dorsal_cover", 0),
}
# Triangles per component: target and cap (budget.py sums them). The nav lenses are the Revoker's own meshes.
BUDGET = {
    "formation_strips": {"target": 16, "cap": 16, "objects": ("light_formation_",)},
    "antennas": {"target": 180, "cap": 180, "objects": ("antenna_",)},
}
CLOSEUPS = {}


def build(p, mats):
    return lights_and_antennas(p, {"antenna": mats["body"]})


def check(icarus):
    return None


def lights_and_antennas(p, mats):
    w = p["wing"]
    # The nav lamps sit on top of the tip, 0.075 m inboard of the tip face the wingtip store's rail bears on, as on
    # the Revoker.
    lamp_x = w["planform"][-1][1] - 0.075
    lamp_le, lamp_z, lamp_chord = stations.wing_at(w, lamp_x)
    parts = []
    for name, s, x, z, kind, colour in LIGHTS:
        if kind == "nav":
            side = 1 if name.endswith("_L") else -1
            pos = bi.P(lamp_le + lamp_chord * 0.35, side * lamp_x, lamp_z + bi.airfoil(0.35) * w["thickness"] * lamp_chord)
        elif kind == "landing":
            g = gear.GEAR["nose"]
            pos = bi.P(g["wheel_s"] - 0.15, 0.0, gear.GEAR["ground_z"] + g["wheel_d"] + 0.15)
        else:
            pos = bi.P(s, x, z)
        e = bi.empty(name, Matrix.Translation(pos))
        e["light"] = kind
        e["colour"] = colour
        parts.append(e)
    for name, s, _, h, chord, where in ANTENNAS:
        ring = bi.blended_ring(p, s)
        z0 = max(v.z for v in ring) if where == "top" else min(v.z for v in ring)
        up = 1 if where == "top" else -1
        verts = [bi.P(s - chord / 2, 0.0, z0 - up * 0.02), bi.P(s + chord / 2, 0.0, z0 - up * 0.02),
                 bi.P(s + chord * 0.1, 0.0, z0 + up * h), bi.P(s - chord * 0.05, 0.0, z0 + up * h)]
        thick = Vector((0.006, 0, 0))
        v = [q - thick for q in verts] + [q + thick for q in verts]
        f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        obj = bi.finish(bi.mesh_object(name, v, f), mats["antenna"], smooth=False)
        obj["role"] = "antenna"
        parts.append(obj)
    return parts
