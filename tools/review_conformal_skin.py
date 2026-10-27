"""Bare-metal close-ups of the conformal trough's NACA ducts, the underside, the nose and a raking view along the skin.

pwsh -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/review_conformal_skin.py -- --tag after [--scene <skin.blend>]

Renders the saved skin scene (art/blender/bake_skin.py writes it; default this checkout's) in the bare-metal livery
(4) through art/blender/skin_closeups.py's setup, into .cache/review/share/conformal_skin/<tag>_<view>.png.
"""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "art/blender"))
import skin_closeups  # noqa: E402
import skin_review  # noqa: E402

OUT = ROOT / ".cache/review/share/conformal_skin"
# Blender axes (nose -Y, left +X, up +Z). The ducts: the forward ramp near s 5.0 to 5.35 (y -3.0 to -2.65), the aft
# one near s 8.73 to 9.08 (y 0.73 to 1.08), on the trough line x 0.55.
DUCTS = {"front": (-2.8, -1), "rear": (0.9, 1)}
SUN = {"low": (0.3, -1.0, -0.25), "under": (0.5, -0.6, -1.0), "rake": (1.0, 0.15, 0.08), "nose": (1.0, -0.8, 0.6)}


def views():
    out = {}
    for side, x in (("L", 0.55), ("R", -0.55)):
        sign = 1 if x > 0 else -1
        for end, (y, way) in DUCTS.items():
            target = (x * 0.95, y, -0.28)
            # the owner's two angles: looking up from below and a little outboard, and a low three-quarter from
            # outboard, ahead of the forward duct and behind the aft one
            out["%s_%s_below" % (side, end)] = ((x + sign * 0.5, y - way * 0.25, -1.9), target, 50, "under")
            out["%s_%s_quarter" % (side, end)] = ((x + sign * 1.5, y + way * 1.4, -0.95), target, 50, "low")
    out["underside"] = ((0.0, -0.6, -23.0), (0.0, -0.6, 0.0), 50, "under")
    out["nose_side"] = ((6.5, -6.0, 0.3), (0.0, -6.0, 0.3), 50, "nose")
    out["nose_quarter"] = ((3.4, -10.6, 1.5), (0.0, -6.4, 0.25), 50, "nose")
    out["raking"] = ((2.6, -15.0, 0.5), (0.0, 1.5, 0.35), 60, "rake")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--scene")
    parser.add_argument("--views")
    parser.add_argument("--samples", type=int, default=64)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.scene:
        skin_closeups.SCENE = Path(args.scene)
    skin_closeups.RESOLUTION = (1920, 1080)
    table = views()
    names = args.views.split(",") if args.views else list(table)
    skin_closeups.VIEWS.update({name: spec[:3] for name, spec in table.items()})
    OUT.mkdir(parents=True, exist_ok=True)
    scene, camera, sun = skin_closeups.setup(args.samples)
    skin_review.preview_material(4)
    for name in names:
        sun.rotation_euler = Vector(SUN[table[name][3]]).to_track_quat("Z", "Y").to_euler()
        skin_closeups.aim(camera, name)
        if name == "underside":  # the length across the frame
            camera.rotation_euler.rotate_axis("Z", math.pi / 2)
        scene.render.filepath = str(OUT / ("%s_%s.png" % (args.tag, name)))
        bpy.ops.render.render(write_still=True)
        print("RENDERED", scene.render.filepath, flush=True)


if __name__ == "__main__":
    main()
