"""Checked aircraft snapshots for fresh bake, export and review processes.

Only successful builds publish entries. The blend and generated cockpit maps are
verified before reuse; missing or modified entries rebuild through the normal checks.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

import bpy
import numpy as np

import build_icarus as bi
import cycles_device


COLLECTIONS = ("Icarus", "Internals", "Colliders", "LOD1", "References")
TEXTURES = tuple("Icarus_Cockpit_" + suffix + ".png" for suffix in ("b", "n", "m", "ao"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def inputs(repo, parameters):
    sources = sorted((repo / "art/blender").rglob("*.py"))
    references = parameters["references"]
    sources += [repo / references["dir"] / references[view]["file"] for view in ("top", "side", "front")]
    scene = bpy.context.scene
    previous_device = scene.cycles.device
    try:
        backend = cycles_device.use_gpu(scene)
        devices = [(device.name, device.type, device.id) for device in
                   bpy.context.preferences.addons["cycles"].preferences.devices if device.use]
    finally:
        scene.cycles.device = previous_device
    return {
        "files": {str(path.relative_to(repo)): digest(path) for path in sources},
        "parameters": parameters,
        "blender": [bpy.app.version_string, bpy.app.build_hash.decode()],
        "numpy": np.__version__,
        "cycles": [backend, sorted(devices)],
        "environment": {key: value for key, value in sorted(os.environ.items())
                        if key != "ICARUS_NO_BUILD_CACHE" and
                        (key.startswith(("ICARUS_", "BLENDER_", "CYCLES_", "CUDA_", "OPTIX_")) or
                         key in ("PYTHONHASHSEED", "OCIO", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"))},
    }


def load_or_build(repo=None, overrides=None):
    repo = Path(repo or Path(__file__).resolve().parents[2]).resolve()
    # Appending into an already-built scene would rename materials and objects.
    # Live edits and repeated variant builds retain build()'s existing semantics.
    if os.environ.get("ICARUS_NO_BUILD_CACHE") == "1" or any(bpy.data.collections.get(n) for n in COLLECTIONS):
        return bi.build(str(repo), overrides)
    parameters = dict(bi.PARAMS, **(overrides or {}))
    fingerprint = inputs(repo, parameters)
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    folder = repo / ".cache/build-cache"
    blend = folder / (key + ".blend")
    manifest = folder / (key + ".json")
    textures = repo / "art/export/textures"
    record = None
    if manifest.is_file():
        try:
            candidate = json.loads(manifest.read_text(encoding="utf-8"))
            if (candidate["key"] == key and candidate["checks_passed"] is True
                    and candidate["blend_sha256"] == digest(blend)
                    and all(digest(folder / key / name) == candidate["textures"][name] for name in TEXTURES)):
                record = candidate
        except (OSError, ValueError, KeyError, TypeError):
            pass
    if record is not None:
        with bpy.data.libraries.load(str(blend), link=False) as (available, loaded):
            if not set(COLLECTIONS) <= set(available.collections):
                raise ValueError("build cache is missing aircraft collections: " + str(blend))
            loaded.collections = list(COLLECTIONS)
        for collection in loaded.collections:
            bpy.context.scene.collection.children.link(collection)
        bi.TARGET = bpy.data.collections["Icarus"]
        import cockpit
        import cockpit_atlas

        cockpit.LAST.clear()
        cockpit.LAST.update(record["cockpit"])
        atlas = cockpit_atlas.Atlas()
        atlas.panel_rects = cockpit.LAST.pop("panel_rects")
        cockpit.LAST["atlas"] = atlas
        textures.mkdir(parents=True, exist_ok=True)
        for name in TEXTURES:
            shutil.copyfile(folder / key / name, textures / name)
        bpy.context.view_layer.update()
        # Store choices and the local stock meshes are outside the scene fingerprint.
        import lights

        lights.check(bi.TARGET)
        print("BUILD CACHE HIT " + key + ": all build checks passed", flush=True)
        return record["metrics"]

    print("BUILD CACHE MISS " + key, flush=True)
    metrics = bi.build(str(repo), overrides)
    import cockpit

    folder.mkdir(parents=True, exist_ok=True)
    staging = folder / (key + "-" + uuid4().hex)
    staging.mkdir()
    try:
        snapshot = staging / "scene.blend"
        bpy.data.libraries.write(str(snapshot), {bpy.context.scene}, path_remap="ABSOLUTE", compress=True)
        for name in TEXTURES:
            shutil.copyfile(textures / name, staging / name)
        state = {name: cockpit.LAST[name] for name in ("groups", "frame_shell", "face_groups",
                                                       "cell_lid_faces", "frame_faces_trimmed", "measure")}
        state["panel_rects"] = cockpit.LAST["atlas"].panel_rects
        record = {"key": key, "inputs": fingerprint, "checks_passed": True, "metrics": metrics,
                  "cockpit": state, "blend_sha256": digest(snapshot),
                  "textures": {name: digest(staging / name) for name in TEXTURES}}
        # Publish the manifest last, so an interrupted writer cannot create a hit.
        (folder / key).mkdir(exist_ok=True)
        for name in TEXTURES:
            os.replace(staging / name, folder / key / name)
        os.replace(snapshot, blend)
        pending = staging / "manifest.json"
        pending.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(pending, manifest)
    finally:
        for path in staging.iterdir():
            path.unlink()
        staging.rmdir()
    print("BUILD CACHE SAVED " + key, flush=True)
    return metrics
