"""World-position paint policy. Generated sources provide surface detail, not scheme placement."""
import json

import numpy as np

from rasterize import ROOT, smoothstep, triplanar


def specifications():
    return [json.loads(path.read_text()) for path in sorted((ROOT / 'art/textures/liveries').glob('*.json'))]


def paint(position, normal, source, spec):
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
