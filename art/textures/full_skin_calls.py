"""Save exact companion prompts and preserve unmodified image-generation outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image
from rasterize import ROOT, SOURCE

SOURCES = SOURCE / 'full'
OUT = ROOT / '.cache/review/wave2/p9b-round2/full'


def companion(name, base_path, kind):
    base = Path(base_path).resolve()
    context_path = base.with_suffix('.context.md')
    context = context_path.read_text() if context_path.exists() else 'See the accepted base source and its guide.'
    width, height = Image.open(base).size
    if kind == 'height':
        mapping = ('White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark '
                   'panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads '
                   'are tiny raised domes centred exactly on their visible base marks, with their existing rings '
                   'recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not '
                   'physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. '
                   'This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.')
    else:
        mapping = ('White means rough and black means smooth. Default maintained satin paint is about 160 grey. '
                   'Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and '
                   'soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes '
                   'at precisely their base-image positions. The physical boundary between painted surfaces and '
                   'the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. '
                   'This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.')
    prompt = f"""Use case: precise-object-edit.
Edit target: the attached accepted neutral-grey UV base image for F-204 Icarus II part group {name}.
Generate ONLY its matching {kind} map. The base image is authoritative for every feature position.
{mapping}

Pixel registration is the primary requirement. Keep the identical {width} x {height} whole square canvas,
every UV island, every notch and every internal feature in exactly the same pixel position. Do not crop,
zoom, rotate, reframe, resize islands or add padding. Do not improve or redesign anything. Do not add text,
legends, arrows, outlines, labels or markings. All relief and material features must already exist in the
accepted base. Preserve the dark surround as uniform black. Output a greyscale RGB image at {width} x {height}.

Aircraft context, for interpretation only:
{context}
"""
    target = SOURCES / (name + '_' + kind)
    target.with_suffix('.prompt.txt').write_text(prompt)
    target.with_suffix('.context.md').write_text(
        f'# {name} {kind} companion\n\nAccepted base: {base.as_posix()}\n'
        f'Native canvas: {width} x {height}. No registration repair or per-map warping is permitted.\n\n'
        f'{mapping}\n\n{context}\n'
        'Acceptance requires native-resolution cross-correlation displacement below one texel and '
        'reported structural feature precision and recall. A failed companion uses the base-derived '
        'fallback for that channel; failed native images remain preserved.\n')
    call = {'name': name + '_' + kind, 'kind': kind, 'prompt': target.with_suffix('.prompt.txt').as_posix(),
            'base': base.as_posix(), 'references': [base.as_posix()], 'output': target.with_suffix('.png').as_posix()}
    (OUT / (name + '_' + kind + '.call.json')).write_text(json.dumps(call, indent=2))
    (SOURCES / (name + '_' + kind + '.call.json')).write_text(json.dumps(call, indent=2))
    print(json.dumps(call))


def portable(path):
    """A generated image's original path without the user's home: codex:generated_images/... for Codex outputs, which
    the repo's public check would otherwise reject, and the posix path for anything else."""
    path = Path(path).resolve()
    codex = (Path.home() / '.codex' / 'generated_images').resolve()
    return 'codex:generated_images/' + path.relative_to(codex).as_posix() if path.is_relative_to(codex) else path.as_posix()


def record(name, original, output):
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Refusing to overwrite a native output: ' + target.as_posix())
    shutil.copy2(original, target)
    provenance = {'tool': 'image_gen.imagegen built-in', 'original': portable(original),
                  'output': target.as_posix(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                  'native_size': list(Image.open(target).size), 'transparent_background': False}
    (OUT / (name + '.generation.json')).write_text(json.dumps(provenance, indent=2))
    (SOURCES / (name + '.generation.json')).write_text(json.dumps(provenance, indent=2))
    print(json.dumps(provenance))


def failure(name, reason):
    record = {'tool': 'image_gen.imagegen built-in', 'output': None, 'accepted': False,
              'generation_error': reason, 'fallback': 'base luminance derivation'}
    (OUT / (name + '.generation.json')).write_text(json.dumps(record, indent=2))
    (SOURCES / (name + '.generation.json')).write_text(json.dumps(record, indent=2))
    print(json.dumps(record))


def status():
    manifest = json.loads((OUT / 'parts.json').read_text())
    bases, companions = [], []
    for name, group in manifest['groups'].items():
        if not Path(group['source_path']).exists():
            bases.append(name)
        else:
            for kind in ('height', 'roughness'):
                if not (OUT / (name+'_'+kind+'.generation.json')).exists():
                    companions.append([name, kind])
    print(json.dumps({'base_groups': len(manifest['groups']), 'pending_bases': bases,
                      'pending_companions_for_ready_bases': companions}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('companion')
    p.add_argument('name')
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--kind', choices=('height', 'roughness'), required=True)
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
    if args.mode == 'companion':
        companion(args.name, args.base, args.kind)
    elif args.mode == 'record':
        record(args.name, args.original, args.output)
    elif args.mode == 'failure':
        failure(args.name, args.reason)
    else:
        status()
