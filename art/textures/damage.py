"""Generated soot and torn-metal source projected in reflected world coordinates."""
import numpy as np
from scipy.ndimage import gaussian_filter

from rasterize import read_source, triplanar
from panels import tangent_normal


def compose_damage(position, normal, used, fade, surface_height):
    colour = triplanar(read_source('damage_source.png'), position, normal, 2.6)
    lum = colour.mean(axis=-1)
    # Damage relief follows the generated tears and scorch, with no procedural noise.
    height = (lum - gaussian_filter(lum, 8)) * 0.65 * fade + surface_height
    severity = np.clip((0.62 - lum) * 1.5 + 0.28, 0.12, 0.95)
    return np.dstack((colour, severity)), tangent_normal(height, used, 3)
