"""Undo an export's byte noise: every FBX under art/export that Blender rewrote with the same content (compare_exports.py:
only its timestamp and UIDs differ from HEAD's) goes back to HEAD's bytes, with the Unity project's copy of it, and
blockout.json's FBX hashes follow the files left on disk, so a commit carries only the meshes that changed.

python tools/revert_export_noise.py

Run after an export into art/export, before tools/export_manifest.py --write (which this runs last) and the Unity build.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from compare_exports import fbx_content

UNITY = {"tip_tank.fbx": "unity/Assets/Blueprinter/Mods/icarus/Mounts/tip_tank.fbx"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)


def main():
    changed = git("diff", "--name-only", "--diff-filter=M", "--", "art/export").decode().split()
    noise = [f for f in changed if f.endswith(".fbx") and fbx_content(git("show", "HEAD:" + f)) == fbx_content((REPO / f).read_bytes())]
    copies = [UNITY.get(Path(f).name, "unity/Assets/Blueprinter/Mods/icarus/Blockout/" + Path(f).name) for f in noise]
    targets = [t for t in noise + copies if (REPO / t).exists() and subprocess.run(["git", "diff", "--quiet", "--", t], cwd=REPO).returncode]
    if targets:
        git("checkout", "--", *targets)
    blockout = REPO / "art/export/blockout.json"
    raw = blockout.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    data = json.loads(raw)
    fixed = 0
    for entry in list(data["parts"].values()) + [data["tip_tank"]]:
        if entry.get("fbx"):
            digest = hashlib.sha256((REPO / "art/export" / entry["fbx"]).read_bytes()).hexdigest()
            if entry.get("sha256") != digest:
                entry["sha256"], fixed = digest, fixed + 1
    blockout.write_bytes((json.dumps(data, indent=1) + "\n").replace("\n", newline).encode("utf-8"))
    subprocess.check_call([sys.executable, str(REPO / "tools/export_manifest.py"), "--write"], cwd=REPO)
    print("EXPORT NOISE: %d of %d changed FBXs were noise, reverted with their Unity copies; %d blockout hashes resynced; kept %s"
          % (len(noise), len(changed), fixed, [f for f in changed if f not in noise]))


if __name__ == "__main__":
    main()
