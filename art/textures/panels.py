"""Generated surface relief plus placed closed access panels and flap hinge slot."""
import numpy as np
from scipy.ndimage import gaussian_filter, binary_erosion, binary_dilation, label, find_objects, distance_transform_edt

# World x, longitudinal y, z; the port is shut and has no gun opening.
ACCESS_PANELS = (
    ('closed_gun_port', ('skin_forward_L', 'skin_forward_R'), -3.95, 0.15, 0.48, 0.24),
    ('aux_door', ('skin_mid_L', 'skin_mid_R'), 1.55, 0.32, 0.45, 0.32),
    ('under_vent', ('skin_aft_L', 'skin_aft_R'), 4.35, -0.28, 0.52, 0.24),
)


def relief(generated, position, part, names, fade):
    used = part > 0
    valid = used & (generated.mean(axis=2) > 0.2)
    lum = generated @ np.array((0.2126, 0.7152, 0.0722))
    support = gaussian_filter(valid.astype(float), 18)
    mean = gaussian_filter(np.where(valid, lum, 0), 18) / np.maximum(support, 1e-8)
    residual = np.clip((lum - mean) * 1.65, -0.25, 0.2)
    confidence = np.clip((distance_transform_edt(valid) - 1) / 3, 0, 1)
    residual *= confidence * fade
    dark = (residual < -.045) & (fade > .5)
    labels, _ = label(dark)
    rivets = np.zeros(used.shape, np.float32)
    line_mask = dark.copy()
    fasteners = 0
    for index, box in enumerate(find_objects(labels), 1):
        if box is None:
            continue
        region = labels[box] == index
        h, w = region.shape
        if region.sum() <= 36 and max(h, w) <= 7 and min(h, w) >= 1:
            y, x = np.unravel_index(np.argmin(np.where(region, residual[box], 1)), region.shape)
            rivets[box[0].start + y, box[1].start + x] = 1
            line_mask[box] &= ~region
            fasteners += 1
    # Morphological medial pixels keep grooves centred on generated dark strokes while fixing their physical width.
    skeleton = np.zeros(used.shape, bool)
    remaining = line_mask
    while remaining.any():
        eroded = binary_erosion(remaining)
        skeleton |= remaining & ~binary_dilation(eroded)
        remaining = eroded
    distance_to_seam = distance_transform_edt(~skeleton)
    grooves = np.exp(-(distance_to_seam / .9) ** 2) * (distance_to_seam <= 1.5)
    dimples = gaussian_filter(rivets, .5) / (1 / (2 * np.pi * .5 ** 2))
    # 2 to 3 texel grooves and 1 to 2 texel dimples. Residual microtexture retains generated raised rims.
    height = (-.34 * grooves - .24 * dimples + gaussian_filter(residual, .55) * .30) * fade
    layout = np.zeros(used.shape, np.float32)
    y, z = position[..., 1], position[..., 2]
    for _, allowed, cy, cz, width, tall in ACCESS_PANELS:
        selected = np.isin(part, [names.index(n) + 1 for n in allowed if n in names])
        dy, dz = abs(y - cy) - width / 2, abs(z - cz) - tall / 2
        edge = abs(np.maximum(dy, dz))
        layout += selected * np.exp(-(edge / 0.008) ** 2) * 0.10
    flap = np.isin(part, [i + 1 for i, n in enumerate(names) if n.startswith('flap_')])
    layout += flap * np.exp(-((y - 1.6) / 0.009) ** 2) * 0.08
    height -= layout * fade
    cavity = np.clip(1 + np.minimum(height, 0) * 0.18 - layout * fade * .35, 0.75, 1)
    report = {'extracted_fasteners': fasteners, 'seam_medial_pixels': int(skeleton.sum()),
              'groove_width_px': [2, 3], 'fastener_width_px': [1, 2],
              'groove_height_px': -.34, 'fastener_height_px': -.24,
              'positions': 'medial pixels and dark compact components of the same generated luminance residual used in colour'}
    return height, cavity, residual, confidence, report


def tangent_normal(height, used, strength=1.8):
    # Image rows run opposite to UV V, so the tangent Y slope has the opposite sign to X.
    gy, gx = np.gradient(height)
    normal = np.stack((-gx * strength, gy * strength, np.ones_like(height)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    normal[~used] = (0, 0, 1)
    return normal * 0.5 + 0.5
