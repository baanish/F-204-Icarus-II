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


def paint(position, normal, source, spec):
    """Scheme colour; `source` is the livery's softened triplanar detail image."""
    x, y, z = abs(position[..., 0]), position[..., 1], position[..., 2]
    lower, upper = np.array(spec['lower']), np.array(spec['upper'])
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
