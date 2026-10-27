"""Convert generated text records and refresh hashes of converted dependencies.

Run from any directory with Python. Conversion is deterministic and idempotent;
all records are prepared before any file is written. Image and bake hashes stay
unchanged. Missing historical review inputs retain their recorded hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'art/textures'))
from record_paths import portable_record, portable_text, resolve_record


def convert_records(folder):
    paths = sorted(path for path in folder.rglob('*') if path.suffix in ('.json', '.md', '.txt'))
    original = {path: path.read_bytes() for path in paths}
    records = {path: portable_record(json.loads(data)) for path, data in original.items()
               if path.suffix == '.json'}
    converted, active = {}, set()

    def convert(path):
        if path in converted:
            return converted[path]
        if path in active:
            raise ValueError('Cyclic record dependency: ' + path.relative_to(ROOT).as_posix())
        active.add(path)
        if path in records:
            value = records[path]
            digests = {}

            def refresh(item):
                if isinstance(item, dict):
                    for key, child in item.items():
                        if key.endswith('_sha256') and isinstance(child, dict):
                            for dependency in child:
                                target = ROOT / dependency
                                if target in original:
                                    if hashlib.sha256(original[target]).hexdigest() != child[dependency]:
                                        raise ValueError('Record dependency differs before conversion: ' + dependency)
                                    digest = hashlib.sha256(convert(target)).hexdigest()
                                    digests[child[dependency]] = digest
                                    child[dependency] = digest
                        else:
                            refresh(child)
                elif isinstance(item, list):
                    for child in item:
                        refresh(child)

            refresh(value)
            def replace_token(match):
                old = json.loads(match[0])
                new = digests.get(old, portable_record(old))
                return json.dumps(new) if old != new else match[0]

            # Replace JSON string tokens only, retaining the original whitespace.
            data = re.sub(r'"(?:\\.|[^"\\])*"', replace_token,
                          original[path].decode('utf-8')).encode('utf-8')
        else:
            data = portable_text(original[path].decode('utf-8')).encode('utf-8')
        active.remove(path)
        converted[path] = data
        return data

    for path in paths:
        convert(path)
    changed = [path for path in paths if converted[path] != original[path]]
    for path in changed:
        path.write_bytes(converted[path])
    print(f'PORTABLE RECORDS: {len(changed)} files changed ({len(paths)} text records checked)')
    for suffix in ('.json', '.md', '.txt'):
        print(f'  {suffix}: {sum(path.suffix == suffix for path in changed)} changed')
    return changed


def check_dependencies(folder):
    checked, missing = set(), set()

    def check(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith('_sha256') and isinstance(child, dict):
                    for dependency, expected in child.items():
                        path = Path(resolve_record(dependency))
                        if not path.is_file() and dependency.startswith('.cache/'):
                            missing.add(dependency)
                            continue
                        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                            raise ValueError('Record dependency differs: ' + dependency)
                        checked.add(dependency)
                else:
                    check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    for path in sorted(folder.rglob('*.json')):
        check(json.loads(path.read_bytes()))
    print(f'DEPENDENCY CHECK PASS: {len(checked)} available inputs verified; '
          f'{len(missing)} ignored review inputs unavailable')
    for dependency in sorted(missing):
        print('  unavailable:', dependency)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify existing dependency hashes without writing')
    args = parser.parse_args()
    folder = ROOT / 'art/textures/generated'
    if args.check:
        check_dependencies(folder)
    else:
        convert_records(folder)
