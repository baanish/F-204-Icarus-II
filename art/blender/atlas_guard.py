"""Which UV pack a skin was baked against. Blender's island packer changes between versions (5.2.3 and 5.3.0 pack the
same islands differently), and a skin baked against meshes from another pack is scrambled in game, which no offline
check sees. So the export (tools/export_blockout.py) records each skin part's UV coordinates as a SHA-256, the skin
bake (bake_skin.py prepare) records the same for the geometry it baked, and the steps that turn a bake into the
shipped maps (art/textures/compose_skin.py, faction_marks.py) refuse a bake whose record differs, naming the parts.

Pure Python: Blender and the texture scripts both import it.
"""
import hashlib
import struct

STEPS = 8  # coordinates are hashed to an eighth of a texel at the atlas size


def uv_digest(coords, size):
    """SHA-256 of (u, v) pairs in the order given (a part's skin loops), each rounded to 1/STEPS texel."""
    h = hashlib.sha256()
    scale = size * STEPS
    for u, v in coords:
        h.update(struct.pack('<qq', round(u * scale), round(v * scale)))
    return h.hexdigest()


def whole(parts):
    """One digest over every part's, by name: what a record of footprints on the atlas depends on."""
    h = hashlib.sha256()
    for name in sorted(parts):
        h.update(name.encode() + b'\0' + parts[name].encode() + b'\n')
    return h.hexdigest()


def mismatched(expected, actual):
    """The parts whose digests differ, or that one record has and the other lacks."""
    return sorted(name for name in set(expected) | set(actual) if expected.get(name) != actual.get(name))


def require_same(exported, baked, what):
    """Raise unless two atlas records ({"blender", "size", "skin_uv_sha256"}) describe the same skin UVs."""
    if exported is None or baked is None:
        raise ValueError(f'{what}: no atlas record to compare (rerun tools/export_blockout.py and bake_skin.py prepare)')
    if exported.get('size') != baked.get('size'):
        raise ValueError(f'{what}: atlas size {baked.get("size")} against the export\'s {exported.get("size")}')
    parts = mismatched(exported['skin_uv_sha256'], baked['skin_uv_sha256'])
    if parts:
        raise ValueError(f'{what}: the skin UVs differ from the exported meshes\' on {len(parts)} parts ({", ".join(parts[:12])}); '
                         f'baked on Blender {baked.get("blender")}, exported on {exported.get("blender")}: bake and export in one run')
