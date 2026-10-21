"""Local paths the store tools read, from tools/local-paths.json (gitignored; tools/local-paths.example.json shows the
keys). Relative paths are from the repo root.

game_export      the AssetRipper export's Assets folder of the installed game: the stock mount prefabs, meshes and
                 colliders, which cannot be in the public repo
python_packages  optional: a folder holding UnityPy, when it isn't installed in the Python that runs the tool
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILE = REPO / "tools" / "local-paths.json"


def load():
    if not FILE.exists():
        raise SystemExit(f"{FILE} is missing: copy tools/local-paths.example.json to tools/local-paths.json and set "
                         "game_export to the game export's Assets folder")
    paths = json.loads(FILE.read_text(encoding="utf-8"))
    export = REPO / paths.get("game_export", "")
    if not (export / "GameObject").is_dir() or not (export / "Mesh").is_dir():
        raise SystemExit(f"{FILE}: game_export {export} is not an export's Assets folder (no GameObject and Mesh in it)")
    packages = paths.get("python_packages")
    if packages:
        sys.path.insert(0, str(REPO / packages))
    return {"game_export": export}
