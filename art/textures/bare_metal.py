"""Aluminium sheet tone and polish per structural skin panel (panels.py layout)."""
import numpy as np

from rasterize import smoothstep

METALLIC_MAP = 'Icarus_livery_4_m.png'


def visibility_bands(position):
    y = position[..., 1]
    return np.maximum(smoothstep((.36 - abs(y + 2.4)) / .025),
                      smoothstep((.34 - abs(y - 4.55)) / .025))


def painted_parts(position, normal, part, names):
    """Radome diagnostic mask and anti-glare paint. The radome itself keeps the livery's sheet finish."""
    x, y = abs(position[..., 0]), position[..., 1]
    radome = part == names.index('radome') + 1 if 'radome' in names else np.zeros(part.shape, bool)
    glare = (smoothstep((y + 7.7) / .06) * smoothstep((-5.8 - y) / .06)
             * smoothstep((.25 - x) / .05) * smoothstep((normal[..., 2] - .5) / .15))
    return radome, glare


def surface_map(shared, position, normal, part, names, decal_coverage, sheet_tone, relief):
    """Match compose's exact paint masks; the exhaust fields blend in by the shared map's own bare weight.

    `protected` is that weight: 1 keeps the shared exhaust values verbatim, 0 is polished sheet.
    """
    radome, glare = painted_parts(position, normal, part, names)
    paint = 1 - (1 - visibility_bands(position)) * (1 - glare) * (1 - decal_coverage)
    protected_ids = [i + 1 for i, name in enumerate(names)
                     if name == 'nozzle' or name.startswith(('nozzle_petal_', 'nozzle_seal_'))]
    protected = np.maximum(shared[..., 0], np.isin(part, protected_ids))
    result = shared.copy()
    # Each sheet carries its own polish; seams and fasteners are rougher, within the polished range.
    smooth = np.clip(.90 + sheet_tone * 1.2 - .06 * relief, .82, .96)
    painted_smooth = np.where(glare > .5, .18, .42)
    result[..., 0] = (protected * shared[..., 0] + (1 - protected) * .98) * (1 - paint)
    result[..., 3] = (protected * shared[..., 3] + (1 - protected) * smooth) * (1 - paint) + painted_smooth * paint
    return result, {'paint': paint, 'protected': protected, 'decal': decal_coverage, 'anti_glare': glare,
                    'radome': radome, 'bands': visibility_bands(position)}


def finish(colour, position, normal, panel, used):
    """Keep bands unchanged; each structural skin panel gets its own sheet tone and a fine brushed grain.

    Tone variation is an albedo art policy, not metal reflectance or new relief. Panel ids come from the
    airframe layout, so sheet boundaries sit exactly on the drawn seams and continue across UV cuts.
    """
    ids, inverse = np.unique(panel[used], return_inverse=True)
    positions = position[used].astype(np.float64)
    positions[:, 0] = abs(positions[:, 0])
    counts = np.bincount(inverse)
    centre = np.stack([np.bincount(inverse, positions[:, i]) / counts for i in range(3)], -1)
    phase = centre @ np.array([2.3, 1.7, 3.1]) + (ids % 7919) * .37
    tone = np.zeros(panel.shape, np.float32)
    warm = np.zeros(panel.shape, np.float32)
    tone[used] = (.035 * np.sin(phase) + .012 * np.cos(phase * 1.37))[inverse]
    warm[used] = (.008 * np.sin(phase * .73 + 1))[inverse]
    x, y, z = abs(position[..., 0]), position[..., 1], position[..., 2]
    transverse = np.where(abs(normal[..., 2]) > .7, y, x * .8 + z)
    polish = .005 * (.6 * np.sin(2 * np.pi * (transverse * 22 + .1 * np.sin(y * 1.7)))
                     + .4 * np.sin(2 * np.pi * (transverse * 47 + .07 * y)))
    variation = (tone + polish)[..., None] + warm[..., None] * np.array([1, .2, -.6])
    adjusted = colour + variation
    soot = smoothstep((y - 4.8) / 2.3) * (.20 + .06 * (1 - smoothstep((z + .2) / .8)))
    adjusted *= 1 - soot[..., None]
    bands = visibility_bands(position)[..., None]
    result = adjusted * (1 - bands) + colour * bands
    return result, tone, {'panels': int(len(ids)),
        'sheet_tone_range': [-.047, .047], 'warm_shift_range': [-.008, .008],
        'polish_amplitude': .005, 'maximum_aft_stain_fraction': .26,
        'panel_source': 'structural panel ids from panels.layout_fields (frames, laps, spars, access panels)',
        'scope': 'livery 4 albedo and polish; existing bands and decals retained'}
