"""The generated images and arrays the skin tools read ship in the release's texture-sources ZIP, not in git.

art/textures/texture-sources.json pins every file. Tools that read them call require_texture_sources() first,
so a checkout without them stops with the fetch command instead of a missing-file error mid-rebuild.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'art/textures/texture-sources.json'
FETCH = 'pwsh -NoProfile -File tools/Fetch-TextureSources.ps1'


def require_texture_sources():
    missing = [path for path in json.loads(MANIFEST.read_text(encoding='utf-8'))['files']
               if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit(f'{len(missing)} texture source files are missing (first: {missing[0]}). '
                         f'Fetch them with: {FETCH}')


if __name__ == '__main__':
    require_texture_sources()
    print('TEXTURE SOURCES PRESENT')
