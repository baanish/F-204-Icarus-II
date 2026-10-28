"""Damage maps: generated soot and torn-metal colour in reflected world coordinates, and a stock-style tear alpha.

The stock AircraftSkin shader (game D3D11 bytecode, every variant) discards a texel when
D * (alpha - 0.52) + 0.02 < 0, with D = 1 - saturate(_HitPoints / 100). Alpha at or above 0.5 never opens; a texel
of alpha a opens once D > 0.02 / (0.52 - a), so alpha 0.42 opens at HP 80 and 0.495 at HP 20. The game multiplies
the livery by lerp(1, damage RGB, D) and blends the damage normal by D everywhere, whatever the alpha.

Stock maps keep 68 to 91% of texels at or above 0.5. Here joints, frame and rib rivet rows and a ragged strip either
side of them never open, nor does most of the skin; the rest is cut into world-space shards inside each structural
panel (panels.py), and each shard opens from its middle outwards, from the HP its rank gives it. The soot stays in
the colour and does not choose where metal tears.
"""
import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.spatial import cKDTree

from rasterize import PX_PER_M, read_source, triplanar
from panels import tangent_normal

SHARD_M = .55  # mean shard pitch in world metres; shards are clipped by the structural panels
TEARABLE = .40  # share of shards that ever open
FIRST_HP, LAST_HP = 92, -18  # open HP of the first and last ranked shard (below 0: only its middle opens)
RANK_CURVE = 1.25  # above 1 front-loads the opening towards high HP
GROWTH_HP = 26  # HP between a shard's middle and its rim opening
EDGE_RAG = .14  # how far, in rim units, the torn-metal detail moves a border between shards
JOINT_STRIP_M = .022  # seam distance that never opens: the joint and both its fastener rows
FASTENER_STRIP_M = .016  # around each rivet or screw head, closing a row into a strip
CLOSED_ALPHA, LINE_ALPHA = 200 / 255, 1.0


def open_alpha(hp):
    """The highest alpha byte, over 255, that the shader has discarded once the part is down to `hp`."""
    d = np.clip(1 - np.asarray(hp, np.float64) / 100, 1e-6, 1)
    threshold = np.clip(255 * (.52 - .02 / d), 0, 255)
    return np.maximum(np.ceil(threshold) - 1, 0) / 255


def warp(position):
    """Low-frequency world offset so shard edges are irregular but stay long and straight."""
    offset = np.zeros_like(position)
    rng = np.random.default_rng(204)
    for _ in range(4):
        direction = rng.normal(size=3)
        direction /= np.linalg.norm(direction)
        phase = position @ direction * rng.uniform(4, 9) + rng.uniform(0, 2 * np.pi)
        offset += np.outer(np.sin(phase), rng.normal(size=3)) * .02
    return position + offset


def tear_alpha(position, used, fields, luminance):
    where = np.flatnonzero(used)
    pos = position.reshape(-1, 3)[where].astype(np.float64)
    lo, hi = pos.min(axis=0) - SHARD_M, pos.max(axis=0) + SHARD_M
    rng = np.random.default_rng(2040)
    grid = np.stack(np.meshgrid(*[np.arange(l, h, SHARD_M) for l, h in zip(lo, hi)], indexing='ij'), -1).reshape(-1, 3)
    sites = grid + rng.uniform(-.45, .45, grid.shape) * SHARD_M
    distance, nearest = cKDTree(sites).query(warp(pos), k=2, workers=-1)
    rim = distance[:, 0] / np.maximum(distance[:, 1], 1e-9)  # 0 at a shard's site, 1 on its edge
    # Centimetre-scale structure of the generated torn metal, about -1 to 1, roughens every tear edge.
    detail = gaussian_filter(luminance, 1.5) - gaussian_filter(luminance, 10)
    detail = np.clip(detail / max(detail[used].std(), 1e-6), -2.5, 2.5).ravel()[where] / 2.5
    # Near an edge, the detail hands texels to the neighbouring shard, so no border between shards is straight.
    swap = rim + EDGE_RAG * detail > 1
    site = np.where(swap, nearest[:, 1], nearest[:, 0])
    rim = np.where(swap, 2 - rim, rim)
    panel = fields['panel'].ravel()[where]
    rank = (rng.random(len(sites))[site] + (panel % 7919) * .6180339887) % 1
    start = FIRST_HP + (LAST_HP - FIRST_HP) * (rank / TEARABLE) ** RANK_CURVE
    hp = start + GROWTH_HP * (.5 - rim - .3 * detail)
    alpha = np.where((rank < TEARABLE) & (hp > 0), open_alpha(hp), CLOSED_ALPHA)
    fastener = (fields['rivet'] > 0) | (fields['screw'] > 0)
    to_fastener = distance_transform_edt(~fastener).ravel()[where] / PX_PER_M
    strip = ((fields['seam_distance'].ravel()[where] < JOINT_STRIP_M * (1 + .45 * detail))
             | (to_fastener < FASTENER_STRIP_M * (1 + .45 * detail)))
    alpha = np.where(strip, LINE_ALPHA, alpha)
    full = np.full(used.shape, LINE_ALPHA)
    full.ravel()[where] = alpha
    return full


def compose_damage(position, normal, used, fade, surface_height, fields):
    colour = triplanar(read_source('damage_source.png'), position, normal, 2.6)
    lum = colour.mean(axis=-1)
    # Damage relief follows the generated tears and scorch, with no procedural noise.
    height = (lum - gaussian_filter(lum, 8)) * 0.65 * fade + surface_height
    return np.dstack((colour, tear_alpha(position, used, fields, lum))), tangent_normal(height, used, 3)
