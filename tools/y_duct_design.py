"""Solve the Y-duct's rows (build_icarus.PARAMS["duct"]) for its flow-area schedule and print them to paste in.

pwsh -File tools/Run-Blender.ps1 --background --factory-startup --python tools/y_duct_design.py

Up to the shock cones' bases (7.40) the branch is the original duct round the cone. Behind them its radius closes on
a smoothstep onto the neck, and from the neck the area (propulsion.duct_area) grows on a smoothstep to the engine
face's: each row's radius is bisected for its station's area, the centre line held to CENTRE_X and CENTRE_Z.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "art/blender"))
import build_icarus as bi  # noqa: E402
import propulsion  # noqa: E402

FRONT = [(6.86, 0.515, 0.22, 0.386), (7.13, 0.5029, 0.2254, 0.3818), (7.40, 0.4910, 0.2306, 0.3777)]
# The centre line: inboard fast behind the cones, so the branches merge early, then slowly over the flattened floor,
# where the trunk keeps its area by staying wide, and round onto the engine's axis at the face.
CENTRE_X = [(7.13, 0.50287), (7.40, 0.49105), (7.80, 0.40), (8.20, 0.29), (8.60, 0.205), (9.00, 0.135), (9.30, 0.075),
            (9.60, 0.0)]
CENTRE_Z = [(7.13, 0.22539), (7.40, 0.23064), (8.20, 0.27), (9.00, 0.31), (9.60, 0.35)]
NECK_S, NECK_AREA = 8.20, 0.377  # just above the cones' throat, 0.337 m2
FACE_S, FACE_AREA = 9.60, 0.5627  # the engine face: radius 0.46 less 8% (internals.INTERNALS["engine"])


def smooth(t):
    return t * t * (3 - 2 * t)


def table(xs):
    return lambda s: bi.pchip([q[0] for q in xs], [q[1] for q in xs], s)


def area_with(s, cx, cz, r):
    p = dict(bi.PARAMS, duct=[(s - 1, cx, cz, r), (s, cx, cz, r), (s + 1, cx, cz, r)])
    return propulsion.duct_area(p, s)


def radius_for(s, cx, cz, area):
    lo, hi = 0.1, 0.6
    for _ in range(22):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if area_with(s, cx, cz, mid) < area else (lo, mid)
    return (lo + hi) / 2


def main():
    cx, cz = table(CENTRE_X), table(CENTRE_Z)
    s0, r0 = FRONT[-1][0], FRONT[-1][3]
    neck_r = radius_for(NECK_S, cx(NECK_S), cz(NECK_S), NECK_AREA)
    rows = list(FRONT)
    for i in range(1, int(round((FACE_S - s0) / 0.1)) + 1):
        s = round(s0 + 0.1 * i, 2)
        if s <= NECK_S:
            r = r0 + (neck_r - r0) * smooth((s - s0) / (NECK_S - s0))
        else:
            r = radius_for(s, cx(s), cz(s), NECK_AREA + (FACE_AREA - NECK_AREA) * smooth((s - NECK_S) / (FACE_S - NECK_S)))
        rows.append((s, round(cx(s), 4), round(cz(s), 4), round(r, 4)))
    print("duct rows: " + json.dumps(rows))


if __name__ == "__main__":
    main()
