"""Solve the Y-duct's rows (build_icarus.PARAMS["duct"]) for its flow-area schedule and print them to paste in.

pwsh -File tools/Run-Blender.ps1 --background --factory-startup --python tools/y_duct_design.py

The branch holds the lip's ring to HOLD_S and closes on a smoothstep onto the tube by TUBE_S, round the shock cone's
cap. From there to BLEND_S each row's radius is bisected for TUBE_AREA (propulsion.duct_area), through the merge and
over the flattened floor, and from BLEND_S the area grows on a smoothstep to the engine face's: the centre line held
to CENTRE_X and CENTRE_Z throughout.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "art/blender"))
import build_icarus as bi  # noqa: E402
import propulsion  # noqa: E402

LIP = (6.86, 0.515, 0.22, 0.386)  # the duct's first ring, which the intake mouth meets
HOLD_S = 6.90  # the lip's ring holds to here, past the mouth's inner end (propulsion.build_mouth, 6.88)
# The centre line: inboard from the lip, so the narrower branches still merge ahead of the floor, then slowly over
# the flattened floor, where the trunk keeps its area by staying wide, and round onto the engine's axis at the face.
CENTRE_X = [(6.86, 0.515), (7.20, 0.49), (7.60, 0.42), (8.00, 0.31), (8.40, 0.22), (9.00, 0.125), (9.30, 0.07),
            (9.60, 0.0)]
CENTRE_Z = [(6.86, 0.22), (7.40, 0.23), (8.20, 0.27), (9.00, 0.31), (9.60, 0.35)]
TUBE_S, BLEND_S, FACE_S = propulsion.DUCT_AREAS["tube_s"] + (propulsion.DUCT_AREAS["face_s"],)
TUBE_AREA, FACE_AREA = propulsion.DUCT_AREAS["tube"], propulsion.DUCT_AREAS["face"]


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
    tube_r = radius_for(TUBE_S, cx(TUBE_S), cz(TUBE_S), TUBE_AREA)
    rows = [LIP]
    stations = [round(HOLD_S + (TUBE_S - HOLD_S) * i / 4, 4) for i in range(4)]
    stations += [round(TUBE_S + 0.1 * i, 2) for i in range(int(round((FACE_S - TUBE_S) / 0.1)) + 1)]
    for s in stations:
        if s < TUBE_S:
            r = LIP[3] + (tube_r - LIP[3]) * smooth((s - HOLD_S) / (TUBE_S - HOLD_S))
        else:
            t = max(0.0, (s - BLEND_S) / (FACE_S - BLEND_S))
            r = radius_for(s, cx(s), cz(s), TUBE_AREA + (FACE_AREA - TUBE_AREA) * smooth(t))
        rows.append((s, round(cx(s), 4), round(cz(s), 4), round(r, 4)))
    print("duct rows: " + json.dumps(rows))
    p = dict(bi.PARAMS, duct=rows)
    for s in [round(LIP[0] + 0.05 * i, 2) for i in range(int((FACE_S - LIP[0]) / 0.05) + 1)] + [FACE_S]:
        print("area s %.2f %.4f m2" % (s, propulsion.duct_area(p, s)))
    print("merge s %.3f" % bi.duct_merge_s(p))


if __name__ == "__main__":
    main()
