"""Fingerprint the bake runtime without constructing aircraft geometry."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'art/blender'))
import build_cache
import build_icarus


if __name__ == '__main__':
    repo = ROOT
    fingerprint = build_cache.inputs(repo, build_icarus.PARAMS)
    # Cache location and bypass switches do not affect baked pixels.
    for name in ('ICARUS_NO_SKIN_CACHE', 'ICARUS_BLENDER', 'OPTIX_CACHE_PATH'):
        fingerprint['environment'].pop(name, None)
    target = Path(sys.argv[sys.argv.index('--') + 1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fingerprint, sort_keys=True), encoding='utf-8')
