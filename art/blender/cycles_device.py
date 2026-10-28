"""The Cycles device every bake and render uses: the GPU through OptiX (NVIDIA) or oneAPI (Intel) when one is
present, else the CPU.

Blender runs these scripts with --factory-startup, which resets Cycles to the CPU, so each caller asks here.
ICARUS_CYCLES_CPU=1 forces the CPU, for a bake that must match one made there."""
import os
import pathlib

import bpy

CACHE = pathlib.Path(__file__).resolve().parents[2] / ".cache" / "optix-cache"


def use_gpu(scene):
    """Point scene's Cycles at the first backend with a GPU (OptiX, then oneAPI) and return "GPU", or leave it on the
    CPU and return "CPU"."""
    scene.cycles.device = "CPU"
    if os.environ.get("ICARUS_CYCLES_CPU") == "1":
        return "CPU"
    CACHE.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPTIX_CACHE_PATH", str(CACHE))
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
        except (TypeError, RuntimeError):
            continue
        for device in prefs.devices:
            device.use = device.type == backend
        if any(device.use for device in prefs.devices):
            scene.cycles.device = "GPU"
            return "GPU"
    return "CPU"
