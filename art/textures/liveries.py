"""World-position paint policy. Generated sources provide surface detail, not scheme placement."""
import json

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter, grey_closing, grey_opening

from rasterize import ROOT, smoothstep, triplanar

# Share of the generated per-part paint's tonal variation kept in albedo. Its painted seams, rivets and
# pitting are removed first: relief and fasteners come from panels.py's airframe layout instead.
PAINT_GRAIN = .45
SOURCE_BLUR_PX = 8  # about 1 cm on the 1.6 to 1.8 m triplanar sources: blotches stay, grain goes


def specifications():
    return [json.loads(path.read_text()) for path in sorted((ROOT / 'art/textures/liveries').glob('*.json'))]


def paint_grain(generated, used):
    """Broad tone of the generated base as a signed albedo residual at its own resolution."""
    luminance = generated @ np.array((.2126, .7152, .0722))
    _, index = distance_transform_edt(~used, return_indices=True)
    luminance = luminance[index[0], index[1]]
    # Closing removes dark strokes and dots up to 6 px (the generator's own panel lines and rivets);
    # opening removes bright specks; the blur leaves soft blotches only.
    clean = gaussian_filter(grey_opening(grey_closing(luminance, size=7), size=5), 2.5)
    support = gaussian_filter(used.astype(float), 18)
    mean = gaussian_filter(np.where(used, clean, 0), 18) / np.maximum(support, 1e-8)
    return np.clip((clean - mean) * 1.65 * PAINT_GRAIN, -.05, .05) * used


def soften(source):
    return gaussian_filter(source, (SOURCE_BLUR_PX, SOURCE_BLUR_PX, 0), mode='wrap')


def value_noise(points, scale, rng):
    """Smooth 3D value noise on a `scale`-metre lattice of seeded random values, in [0, 1]."""
    lattice = rng.random((64, 64, 64))
    cell = points / scale
    base = np.floor(cell).astype(np.int64)
    t = cell - base
    t = t * t * (3 - 2 * t)
    total = 0
    for corner in np.ndindex(2, 2, 2):
        index = (base + corner) % 64
        weight = np.prod(np.where(corner, t, 1 - t), axis=-1)
        total = total + weight * lattice[index[..., 0], index[..., 1], index[..., 2]]
    return total


def pixel_fields(points, spec):
    """Two patch fields, each two octaves of value noise, sampled once per world-space voxel of `block_m`."""
    block = spec['block_m']
    voxels, inverse = np.unique(np.floor(points.reshape(-1, 3) / block).astype(np.int64), axis=0, return_inverse=True)
    centre = (voxels + .5) * block
    rng = np.random.default_rng(spec['seed'])
    patch = spec['patch_m']
    fields = []
    for _ in range(2):
        field = .7 * value_noise(centre, patch, rng) + .3 * value_noise(centre, patch / 2.5, rng)
        fields.append(field[inverse.ravel()].reshape(points.shape[:-1]))
    return fields


def pixel_tones(position, spec):
    """Index into spec['tones'] (light, blue-grey, mid, dark) for each point: stock-style square-pixel camo.

    The stock Revoker's BDF Gray Camo paints square blocks of about 0.17 m (19.5 texels at its 114 px/m) in a light
    ground, blue-grey patches with a lighter half-tone at their edges, and dark patches; its two sides do not mirror.
    Here the blocks are world-space voxels, so they stay square on axis-facing skin, keep one size on every part and
    run across part and UV boundaries; x keeps its sign, so the sides differ as stock's do. Thresholds come from the
    fields' own distribution over the airframe's box, so every texel set (the whole atlas or a subset) gets the same
    answer and the tone shares land near spec['shares'].
    """
    bg, dark = pixel_fields(position, spec)
    sample = np.random.default_rng(spec['seed'] + 1).uniform((-4, -9, -1.5), (4, 9.5, 3.5), (200000, 3))
    sbg, sdark = pixel_fields(sample, spec)
    light_share, bg_share, mid_share, dark_share = spec['shares']
    dark_cut = np.quantile(sdark + .35 * sbg, 1 - dark_share)
    is_dark = dark + .35 * bg > dark_cut
    rest = ~(sdark + .35 * sbg > dark_cut)
    bg_cut = np.quantile(sbg[rest], 1 - bg_share / (1 - dark_share))
    mid_cut = np.quantile(sbg[rest], 1 - (bg_share + mid_share) / (1 - dark_share))
    return np.where(is_dark, 3, np.where(bg > bg_cut, 1, np.where(bg > mid_cut, 2, 0)))


def paint(position, normal, source, spec):
    """Scheme colour; `source` is the livery's softened triplanar detail image."""
    x, y, z = abs(position[..., 0]), position[..., 1], position[..., 2]
    lower, upper = np.array(spec['lower']), np.array(spec['upper'])
    if spec['pattern'] == 'pixel':
        colour = np.array(spec['tones'])[pixel_tones(position, spec)]
        detail = triplanar(source, position, normal, spec['source_scale_m']).mean(axis=-1)
        modulation = np.clip(1 + (detail - source.mean()) * spec['wear_strength'], 0.78, 1.14)
        return colour * modulation[..., None]
    if spec['pattern'] == 'splinter':
        # Convex regions cut by world planes keep the splinter edges straight and reflect exactly across x=0.
        field = np.full(x.shape, -np.inf)
        for planes in spec['splinters']:
            region = np.full(x.shape, np.inf)
            for nx, ny, nz, offset in planes:
                region = np.minimum(region, nx * x + ny * y + nz * z + offset)
            field = np.maximum(field, region)
        blend = smoothstep((field + .01) / .02)
    else:
        blend = smoothstep((z - spec['demarcation'][0]) / spec['demarcation'][1])
    colour = lower + (upper - lower) * blend[..., None]
    detail = triplanar(source, position, normal, spec['source_scale_m']).mean(axis=-1)
    modulation = np.clip(1 + (detail - source.mean()) * spec['wear_strength'], 0.78, 1.14)
    colour *= modulation[..., None]
    if spec['pattern'] == 'bands':
        bands = np.maximum(smoothstep((0.36 - abs(y + 2.4)) / 0.025),
                           smoothstep((0.34 - abs(y - 4.55)) / 0.025))
        colour = colour * (1 - bands[..., None]) + np.array(spec['band']) * bands[..., None]
    return colour
