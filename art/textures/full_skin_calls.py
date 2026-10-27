"""Preserve unmodified image-generation outputs and record failed generations."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image
from record_paths import portable_record, portable_text, resolve_record
from rasterize import ROOT, SOURCE

SOURCES = SOURCE / 'full'
OUT = ROOT / '.cache/review/wave2/p9b-round2/full'


def portable(path):
    """Keep original generation identifiers without publishing local directories."""
    path = Path(path).resolve()
    codex = (Path.home() / '.codex' / 'generated_images').resolve()
    if path.is_relative_to(codex):
        return 'codex:generated_images/' + path.relative_to(codex).as_posix()
    if path.is_relative_to(ROOT):
        return path.relative_to(ROOT).as_posix()
    raise ValueError('Original must be a repository file or a generated image in the configured home directory')


def record(name, original, output):
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Refusing to overwrite a native output: ' + target.as_posix())
    origin = portable(original)
    shutil.copy2(original, target)
    provenance = {'tool': 'image_gen.imagegen built-in', 'original': origin,
                  'output': target.as_posix(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                  'native_size': list(Image.open(target).size), 'transparent_background': False}
    (OUT / (name + '.generation.json')).write_text(json.dumps(portable_record(provenance), indent=2))
    (SOURCES / (name + '.generation.json')).write_text(json.dumps(portable_record(provenance), indent=2))
    print(json.dumps(portable_record(provenance)))


def failure(name, reason):
    record = {'tool': 'image_gen.imagegen built-in', 'output': None, 'accepted': False,
              'generation_error': reason, 'fallback': 'base luminance derivation'}
    (OUT / (name + '.generation.json')).write_text(json.dumps(portable_record(record), indent=2))
    (SOURCES / (name + '.generation.json')).write_text(json.dumps(portable_record(record), indent=2))
    print(json.dumps(portable_record(record)))


def status():
    manifest = resolve_record(json.loads((OUT / 'parts.json').read_text()))
    bases = [name for name, group in manifest['groups'].items() if not Path(group['source_path']).exists()]
    print(json.dumps(portable_record({'base_groups': len(manifest['groups']), 'pending_bases': bases})))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('record')
    p.add_argument('name')
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('failure')
    p.add_argument('name')
    p.add_argument('--reason', required=True)
    sub.add_parser('status')
    args = parser.parse_args()
    SOURCES.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == 'record':
        record(args.name, args.original, args.output)
    elif args.mode == 'failure':
        failure(args.name, args.reason)
    else:
        status()
