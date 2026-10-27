"""Losslessly recompress texture source binaries and carry their new hashes through the text records.

PNGs go through oxipng with every colour-type, bit-depth, palette and alpha reduction off and no chunk
stripped, so each file decodes to the same mode, size and pixels. A PNG carrying C2PA content
credentials (a caBX chunk, as raw image-generation outputs do) is skipped unless --include-signed:
any re-encode invalidates the credential's hash binding, so a re-encoded file drops that chunk. NPZ members are rewritten with ZIP_LZMA, which
np.load reads through zipfile; every member's .npy bytes stay identical. A file is replaced only when the
result is smaller and verified equal.

Every tracked text record under art/ that quoted an old SHA-256 gets the new one, and records whose own
bytes change pass their new hashes on to the records that pin them, until nothing changes. Prompts and
context packs (.prompt.txt, .context.md) are never rewritten: they are the exact text sent to the image
generator, so a hash they quote is the hash of the bytes sent then. Rerunning changes no files. Needs
pyoxipng (pip install pyoxipng). Afterwards refresh the source pack and gate with
tools/Build-TextureSources.ps1 -WriteManifest and tools/Rebuild-Skin.ps1 -Part python.

    python tools/compact_texture_sources.py [--dry-run] [--include-signed] [PATH ...]

PATH defaults to art/textures/generated; every .png and .npz under it is a candidate.
"""
import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RECORD_SUFFIXES = ('.json', '.md', '.txt')
EXACT_CALL_TEXT = ('.prompt.txt', '.context.md')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def tracked(*paths):
    listed = subprocess.check_output(['git', 'ls-files', '--', *paths], cwd=ROOT, text=True).splitlines()
    return [ROOT / path for path in listed if (ROOT / path).is_file()]


def signed_png(data):
    position = 8
    while position < len(data):
        length, kind = int.from_bytes(data[position:position + 4], 'big'), data[position + 4:position + 8]
        if kind == b'caBX':
            return True
        position += 12 + length
    return False


def decoded(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.mode, image.size, np.asarray(image)


def compact_png(data):
    import oxipng
    # A re-encoded credential no longer verifies and would read as tampered, so it goes with the re-encode.
    strip = oxipng.StripChunks.strip([b'caBX']) if signed_png(data) else oxipng.StripChunks.none()
    result = oxipng.optimize_from_memory(data, level=4, strip=strip, optimize_alpha=False,
                                         bit_depth_reduction=False, color_type_reduction=False,
                                         palette_reduction=False, grayscale_reduction=False)
    (mode, size, pixels), (new_mode, new_size, new_pixels) = decoded(data), decoded(result)
    if (mode, size) != (new_mode, new_size) or not np.array_equal(pixels, new_pixels):
        raise ValueError('PNG recompression changed the decoded image')
    return result


def compact_npz(data):
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_LZMA) as target:
        members = [(info, source.read(info)) for info in source.infolist()]
        for info, member in members:
            entry = zipfile.ZipInfo(info.filename, info.date_time)
            entry.compress_type = zipfile.ZIP_LZMA
            entry.external_attr = info.external_attr
            target.writestr(entry, member)
    result = buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(result)) as check:
        if [(i.filename, check.read(i)) for i in check.infolist()] != [(i.filename, m) for i, m in members]:
            raise ValueError('NPZ recompression changed a member')
    with np.load(io.BytesIO(data), allow_pickle=False) as before, np.load(io.BytesIO(result), allow_pickle=False) as after:
        if sorted(before.files) != sorted(after.files) or any(
                not np.array_equal(before[name], after[name]) for name in before.files):
            raise ValueError('NPZ recompression changed an array')
    return result


def carry_hashes(digests, edited=None, ignore=()):
    """Return {record: new bytes} for tracked art/ records after substituting old -> new digests until stable.

    digests maps old to new SHA-256 for changed binaries; edited holds records already changed in memory,
    whose own old -> new hashes are carried too. Paths in ignore (removed files) take no part.
    """
    edited = edited or {}
    records = [path for path in tracked('art') if path.suffix in RECORD_SUFFIXES and path not in ignore]
    original = {path: path.read_bytes() for path in records}
    rewritable = [path for path in records if not path.name.endswith(EXACT_CALL_TEXT)]
    mapping, current = dict(digests), {path: edited.get(path, original[path]) for path in records}
    for _ in range(64):
        mapping.update({sha256(original[path]): sha256(data) for path, data in current.items() if data != original[path]})
        updated = dict(current)
        for path in rewritable:
            text = edited.get(path, original[path]).decode('utf-8')
            for old, new in mapping.items():
                text = text.replace(old, new)
            updated[path] = text.encode('utf-8')
        if updated == current:
            stale = [path.relative_to(ROOT).as_posix() for path in records if path not in rewritable and
                     path in edited]
            if stale:
                raise ValueError('Refusing to rewrite exact generator text: ' + ', '.join(stale))
            return {path: data for path, data in current.items() if data != original[path]}
        current = updated
    raise ValueError('Record hashes did not settle; is there a hash cycle?')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('paths', nargs='*', default=['art/textures/generated'])
    parser.add_argument('--dry-run', action='store_true', help='report savings without writing')
    parser.add_argument('--include-signed', action='store_true', help='also re-encode PNGs carrying C2PA credentials')
    args = parser.parse_args()
    # The skin rebuild rewrites these itself, so recompressing them gains nothing.
    outputs = {ROOT / path for path in json.loads((ROOT / 'art/textures/texture-sources.json').read_text())['outputs']}
    binaries = sorted(path for folder in args.paths for pattern in ('*.png', '*.npz')
                      for path in (ROOT / folder).rglob(pattern) if path not in outputs)
    changed, results, skipped_signed, before_total, after_total = {}, {}, 0, 0, 0
    for path in binaries:
        data = path.read_bytes()
        if path.suffix == '.png' and not args.include_signed and signed_png(data):
            skipped_signed += 1
            continue
        key = sha256(data)
        if key not in results:
            results[key] = compact_png(data) if path.suffix == '.png' else compact_npz(data)
        result = results[key]
        before_total += len(data)
        after_total += min(len(data), len(result))
        if len(result) < len(data):
            changed[path] = result
    digests = {sha256(path.read_bytes()): sha256(result) for path, result in changed.items()}
    left = {sha256(path.read_bytes()) for path in binaries if path not in changed}
    if set(digests) & left:
        raise ValueError('An old digest also belongs to a file left unchanged')
    rewritten = carry_hashes(digests)
    print(f'COMPACT: {len(changed)} of {len(binaries)} binaries smaller, {skipped_signed} signed PNGs skipped; '
          f'{before_total / 1e6:.2f} -> {after_total / 1e6:.2f} MB; {len(rewritten)} text records carry new hashes')
    if args.dry_run:
        return
    for path, result in changed.items():
        path.write_bytes(result)
    for path, data in rewritten.items():
        path.write_bytes(data)


if __name__ == '__main__':
    main()
