"""Shared atlas sampling and padding, with left-canonical world projection."""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache/review/wave2/p9b/02'
SOURCE = ROOT / 'art/textures/generated'
EXPORT = ROOT / 'art/export/textures'
SIZE = 2048


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
    band = (~used) & (distance <= 8)
    result[band] = values[index[0][band], index[1][band]]
    return result


def save_map(path, values, used):
    rgb = np.uint8(np.clip(values, 0, 1) * 255 + 0.5)
    rgb[~used] = 0
    Image.fromarray(dilate(rgb, used)).save(path)


def smoothstep(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)
