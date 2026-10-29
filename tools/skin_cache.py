"""Checked skin results. Rebuild-Skin.ps1 owns the PASS gate before publication.

The Blender probe reuses the geometry fingerprint, including parameters, runtime
and bake device. Immutable pack files are inputs; current atlas maps are outputs.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'art/blender'))
from cache_root import cache_root

BAKE = '.cache/review/wave2/p9b/02'
REVIEW = '.cache/review/wave2/p9b-round2'
ATLAS = 'art/textures/generated/full/source-atlas'
MAPS = tuple(f'art/export/textures/Icarus_livery_{i}.png' for i in range(1, 5)) + tuple(
    f'art/export/textures/Icarus_skin_{s}.png' for s in ('n', 'm', 'ao', 'dmg_b', 'dmg_n')) + (
    'art/export/textures/Icarus_livery_4_m.png',)
COCKPIT_MAPS = tuple('art/export/textures/Icarus_Cockpit_' + suffix + '.png'
                     for suffix in ('b', 'n', 'm', 'ao'))
REQUIRED = MAPS + COCKPIT_MAPS + ('art/export-manifest.json', 'art/textures/gate.json',
                   ATLAS + '/current/parts.json', ATLAS + '/current/coverage.json',
                   ATLAS + '/provenance.json', BAKE + '/geometry_maps.npz',
                   BAKE + '/ao_maps.npz', BAKE + '/skin.blend', REVIEW + '/structure.json',
                   REVIEW + '/full/measurements.json')
PACK_OUTPUTS = {ATLAS + '/' + name for name in (
    'provenance.json', 'README.md', 'native/assembled.png', 'native/alignment.json', 'native/stitch.json')}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pack_path(repo, name):
    normalized = name.replace('\\', '/')
    for marker in ('art/textures/', '.cache/review/'):
        if marker in normalized:
            normalized = marker + normalized.split(marker, 1)[1]
            break
    path = repo / normalized
    path.resolve().relative_to(repo.resolve())
    return path


def fingerprint(repo, geometry, versions):
    paths = set()
    for pattern in ('art/blender/**/*.py', 'art/textures/*.py', 'art/textures/liveries/*.json',
                    'art/textures/fonts/*', 'art/textures/*.txt'):
        paths.update(p for p in repo.glob(pattern) if p.is_file())
    paths.update(repo / name for name in ('tools/Rebuild-Skin.ps1', 'tools/Run-Blender.ps1',
                                        'tools/skin_cache.py', 'tools/export_manifest.py',
                                        'art/textures/texture-sources.json'))
    pins = json.loads((repo / 'art/textures/texture-sources.json').read_text(encoding='utf-8'))
    excluded = set(pins.get('outputs', [])) | PACK_OUTPUTS
    paths.update(repo / name for name in pins['files'] if name not in excluded and
                 not name.startswith(ATLAS + '/current/') and name != ATLAS + '/provenance.json')
    # Include unpinned prompts/policies and newly added accepted source files too.
    paths.update(p for p in (repo / 'art/textures/generated').rglob('*') if p.is_file() and
                 p.relative_to(repo).as_posix() not in excluded and
                 not p.relative_to(repo).as_posix().startswith(ATLAS + '/current/') and
                 p.relative_to(repo).as_posix() != ATLAS + '/provenance.json')
    native = repo / ATLAS / 'native/parts.json'
    record = json.loads(native.read_text(encoding='utf-8'))
    for field in ('input_sha256', 'generation_input_sha256'):
        paths.update(pack_path(repo, name) for name in record[field])
    files = {p.relative_to(repo).as_posix(): digest(p) for p in sorted(paths)}
    return {'schema': 1, 'files': files, 'geometry': geometry, 'versions': versions}


def key_for(inputs):
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def output_paths(repo):
    paths = {repo / name for name in REQUIRED}
    for directory in (BAKE, REVIEW, ATLAS + '/current'):
        paths.update(p for p in (repo / directory).rglob('*') if p.is_file() and
                     p.name != 'rebuild-commands.json')
    paths.add(repo / ATLAS / 'native/assembled.png')
    paths.update(repo / name for name in PACK_OUTPUTS if (repo / name).is_file())
    return sorted(paths)


def restore(repo, folder, key):
    try:
        record = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if record['key'] != key or record['checks_passed'] is not True:
            return False
        outputs = record['outputs']
        if not isinstance(outputs, dict) or not set(REQUIRED) <= outputs.keys():
            return False
        for name, expected in outputs.items():
            if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:
                return False
            if digest(folder / 'files' / name) != expected:
                return False
        for name, expected in outputs.items():
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / 'files' / name, target)
            if digest(target) != expected:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def publish(repo, folder, key, inputs):
    folder.parent.mkdir(parents=True, exist_ok=True)
    # Short name: key plus suffix pushed the longest output past Windows' 260-character path limit.
    staging = folder.parent / uuid4().hex
    staging.mkdir()
    try:
        outputs = {}
        for path in output_paths(repo):
            name = path.relative_to(repo).as_posix()
            target = staging / 'files' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            outputs[name] = digest(target)
        record = {'key': key, 'inputs': inputs, 'checks_passed': True, 'outputs': outputs}
        folder.mkdir(exist_ok=True)
        # Manifest last: partial publication or a failed writer cannot create a hit.
        for name in outputs:
            target = folder / 'files' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / 'files' / name, target)
        pending = staging / 'manifest.json'
        pending.write_text(json.dumps(record, indent=2), encoding='utf-8')
        os.replace(pending, folder / 'manifest.json')
    finally:
        shutil.rmtree(staging)


def refresh_gate(repo):
    # Non-skin exports and HEAD can change without changing the skin inputs.
    from export_manifest import export_hashes
    manifest = repo / 'art/export-manifest.json'
    manifest.write_text(json.dumps(export_hashes(repo), indent=2) + '\n', encoding='utf-8')
    path = repo / 'art/textures/gate.json'
    gate = json.loads(path.read_text(encoding='utf-8'))
    gate['inputs']['art/export-manifest.json'] = digest(manifest)
    try:
        gate['geometry_commit'] = subprocess.check_output(
            ['git', '-C', str(repo), 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        gate.pop('geometry_commit', None)
    path.write_text(json.dumps(gate, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('restore', 'publish'))
    parser.add_argument('--geometry', type=Path, required=True)
    args = parser.parse_args()
    versions = {'python': platform.python_version(), 'platform': platform.platform(),
                **{name: importlib.metadata.version(name) for name in ('numpy', 'scipy', 'Pillow')}}
    inputs = fingerprint(ROOT, json.loads(args.geometry.read_text(encoding='utf-8')), versions)
    pending = args.geometry.with_suffix('.skin-inputs.json')
    key = key_for(inputs)
    folder = cache_root(ROOT) / 'skin-cache' / key
    if args.mode == 'restore':
        pending.write_text(json.dumps(inputs, sort_keys=True), encoding='utf-8')
        if os.environ.get('ICARUS_NO_SKIN_CACHE') != '1' and restore(ROOT, folder, key):
            refresh_gate(ROOT)
            print('SKIN CACHE HIT ' + key)
            return
        print('SKIN CACHE MISS ' + key)
        raise SystemExit(3)
    if inputs != json.loads(pending.read_text(encoding='utf-8')):
        raise ValueError('Skin inputs changed during rebuild; result was not cached')
    publish(ROOT, folder, key, inputs)
    print('SKIN CACHE SAVED ' + key)


if __name__ == '__main__':
    main()
