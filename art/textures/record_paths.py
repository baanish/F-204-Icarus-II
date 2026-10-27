"""Texture records store repo-relative paths; readers resolve them from ROOT.

Bare filenames remain relative to their record's directory. External generation
identifiers such as codex:generated_images/... remain provenance, not repo paths.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REPO_PREFIXES = ('art/', '.cache/', 'tools/', 'tests/', 'unity/')
# Old checkout prefixes can occur inside prompts as well as JSON path fields.
CHECKOUT_PREFIX = re.compile(r'[A-Za-z]:[/\\][^\r\n"\'<>]*?[/\\](?=(?:art[/\\]textures|\.cache[/\\]review)[/\\])')


def portable_text(value):
    value = value.replace(ROOT.as_posix() + '/', '').replace(str(ROOT) + '\\', '')
    return CHECKOUT_PREFIX.sub('', value)


def portable_record(value):
    if isinstance(value, dict):
        return {portable_record(key): portable_record(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_record(item) for item in value]
    if isinstance(value, str):
        result = portable_text(value)
        normalized = result.replace('\\', '/')
        checkout = re.fullmatch(r'[A-Za-z]:/(?:[^/]+/)*F-240-Icarus-II/(t3-[0-9a-f]+)', normalized)
        if checkout:
            return 'checkout:' + checkout[1]
        if normalized == ROOT.as_posix():
            return '.'
        if normalized.startswith(REPO_PREFIXES):
            result = normalized
        return result
    return value


def resolve_record(value):
    if isinstance(value, dict):
        return {resolve_record(key): resolve_record(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_record(item) for item in value]
    if isinstance(value, str) and value.startswith(REPO_PREFIXES):
        return (ROOT / value).as_posix()
    return value


def read_json(path):
    return resolve_record(json.loads(Path(path).read_text(encoding='utf-8')))


def write_json(path, value):
    Path(path).write_text(json.dumps(portable_record(value), indent=2) + '\n', encoding='utf-8')
