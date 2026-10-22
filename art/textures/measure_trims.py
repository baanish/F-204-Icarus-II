"""Measure approved full-width strips in local stock textures; write numbers and hashes, never pixels.

python art/textures/measure_trims.py --source <_donotship/Texture2D> --write
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

STRIPS = {
    "jet_mechanical": ("jet_mechanical_AlbedoTransparency_PLACEHOLDER.png", (0, 4, 2048, 492)),
    "aircraft_structure": ("aircraft_structure_b_PLACEHOLDER.png", (0, 32, 1024, 416)),
}


def measure(source):
    result = {}
    for name, (filename, rect) in STRIPS.items():
        path = source / filename
        with Image.open(path) as image:
            width, height = image.size
            if not (0 <= rect[0] < rect[2] <= width and 0 <= rect[1] < rect[3] <= height):
                raise ValueError("strip outside " + filename)
            result[name] = {"source": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "size": [width, height], "rect": list(rect)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    strips = measure(args.source)
    block = "# BEGIN MEASURED STRIPS\nSTRIPS = " + repr(strips) + "\n# END MEASURED STRIPS"
    path = Path(__file__).resolve().parents[1] / "blender/trims.py"
    text = path.read_text(encoding="utf-8")
    start, end = text.index("# BEGIN MEASURED STRIPS"), text.index("# END MEASURED STRIPS") + len("# END MEASURED STRIPS")
    expected = text[:start] + block + text[end:]
    if args.write:
        path.write_text(expected, encoding="utf-8", newline="\n")
    elif text != expected:
        raise SystemExit("trim measurements differ; rerun with --write")
    print(json.dumps(strips, indent=2))


if __name__ == "__main__":
    main()
