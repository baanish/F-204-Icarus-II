"""Shared atlas sampling and padding, with left-canonical world projection."""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, zoom

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache/review/wave2/p9b/02'
SOURCE = ROOT / 'art/textures/generated'
EXPORT = ROOT / 'art/export/textures'
SIZE = 4096  # production skin atlas: art/blender/uvs.py ATLAS_SIZE
PAINT_SIZE = 2048  # generated paint registration and AO bake: uvs.PAINT_SIZE
PX_PER_M = 300  # uvs.TEXEL_DENSITY
GUTTER_PX = 16


def sample(image, u, v, repeat=False):
    h, w = image.shape[:2]
    x = (u % 1) * w if repeat else np.clip(u, 0, 1) * (w - 1)
    y = (v % 1) * h if repeat else np.clip(v, 0, 1) * (h - 1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - ix)[..., None], (y - iy)[..., None]
    jx, jy = (ix + 1) % w, (iy + 1) % h
    ix, iy = ix % w, iy % h
    return ((1 - fx) * (1 - fy) * image[iy, ix] + fx * (1 - fy) * image[iy, jx]
            + (1 - fx) * fy * image[jy, ix] + fx * fy * image[jy, jx])


def triplanar(image, position, normal, scale=1.6):
    p = position.copy()
    p[..., 0] = abs(p[..., 0])
    weight = abs(normal) ** 4
    weight /= np.maximum(weight.sum(axis=-1, keepdims=True), 1e-8)
    result = np.zeros((*position.shape[:-1], image.shape[-1]), np.float32)
    for axis, (a, b) in enumerate(((1, 2), (0, 2), (0, 1))):
        result += sample(image, p[..., a] / scale, p[..., b] / scale, True) * weight[..., axis:axis + 1]
    return result


def read_source(name):
    return np.asarray(Image.open(SOURCE / name).convert('RGB'), np.float32) / 255


def dilate(values, used):
    result = values.copy()
    distance, index = distance_transform_edt(~used, return_indices=True)
    band = (~used) & (distance <= GUTTER_PX)
    result[band] = values[index[0][band], index[1][band]]
    return result


def save_map(path, values, used):
    rgb = np.uint8(np.clip(values, 0, 1) * 255 + 0.5)
    rgb[~used] = 0
    Image.fromarray(dilate(rgb, used)).save(path)


def smoothstep(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def upsample(values, used):
    """A PAINT_SIZE field bilinearly sampled at SIZE texel centres, padded from the nearest skin first."""
    _, index = distance_transform_edt(~used, return_indices=True)
    padded = values[index[0], index[1]]
    factor = SIZE / values.shape[0]
    return zoom(padded, (factor, factor) + (1,) * (values.ndim - 2), order=1, grid_mode=True, mode='nearest')


def extend_geometry(position, normal, part, width=3):
    """Extrapolate each island's world position a few texels past its edge along its own UV derivatives.

    Features evaluated there keep their true shape, so image-space gradients stay correct up to UV cuts.
    Returns position, normal and part over the band, the evaluated mask, and the per-texel derivatives.
    """
    used = part > 0
    derivatives = []
    for axis in (1, 0):
        ahead, behind = np.roll(position, -1, axis), np.roll(position, 1, axis)
        forward = used & (np.roll(part, -1, axis) == part)
        backward = used & (np.roll(part, 1, axis) == part)
        step = np.where(forward[..., None], ahead - position, np.where(backward[..., None], position - behind, np.nan))
        derivatives.append(step)
    known = used & np.isfinite(derivatives[0]).all(-1) & np.isfinite(derivatives[1]).all(-1)
    _, index = distance_transform_edt(~known, return_indices=True)
    dx, dy = (d[index[0], index[1]] for d in derivatives)
    distance, nearest = distance_transform_edt(~used, return_indices=True)
    band = ~used & (distance <= width)
    yy, xx = np.nonzero(band)
    iy, ix = nearest[0][band], nearest[1][band]
    position, normal, part = position.copy(), normal.copy(), part.copy()
    position[band] = position[iy, ix] + dx[iy, ix] * (xx - ix)[:, None] + dy[iy, ix] * (yy - iy)[:, None]
    normal[band] = normal[iy, ix]
    part[band] = part[iy, ix]
    return position, normal, part, used | band, dx, dy
