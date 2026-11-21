"""Flat-print the generated decals, load the faction roundels and place them, supersampled, only on unique skin islands."""
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, label

from rasterize import ROOT, SOURCE, OUT, PX_PER_M, sample

SUBSAMPLES = 4  # per texel axis: 16 world-space samples per texel box-filter the decal edges
PAD = 6  # transparent source pixels around every decal so supersamples past its edge read clear
SIDE_FACING = .45  # |normal x| above which a texel takes side decals; normal z for upper and lower decals
TOP_PARTS = ('wing_skin_L', 'wing_skin_R', 'flap_L_visible', 'flap_R_visible',
             'aileron_L_visible', 'aileron_R_visible')
FORWARD = ('skin_forward_L', 'skin_forward_R')
WINGS = ('wing_skin_L', 'wing_skin_R')
BOTH, LEFT, RIGHT = (1, -1), (1,), (-1,)
# The faction roundel is the game's own art, read from the local asset export (tools/local-paths.json `game_export`),
# never from the repository. Every stock livery wears the colour roundel; the grey ones are faction menu sprites.
FACTION_ROUNDELS = {'PALA': 'PALA_roundel', 'BDF': 'BDF_roundel'}
# 38 mm (1.5 in) capitals: T.O. 1-1-4 sets stencilled instructions 1/2 to 2 in high, and at the wing's 3.5 mm texels
# this is the smallest height whose strokes (about 6 mm) still span two texels. The width keeps the stencil sheet's ink
# aspect, 4.42.
NO_STEP_HEIGHT = .038
NO_STEP_WIDTH = .168
# Upper lettering reads for someone standing behind the trailing edge: along world -X, tops forward, on both wings.
# Placements named here turn a quarter to read for someone outboard facing the fuselage: aft on the left wing, forward
# on the right, tops inboard.
FACING_FUSELAGE = ('no_step_wing_root',)
# label, source, parts, centre y,z (side) or positive x,y (upper, lower), width, height in world metres, face, sides
# (+1 left, -1 right). decal_checks.py holds each one clear of the canopy, physical edges, panel seams and light fittings.
# Forward: each inside one skin panel between the butt joints at s 2.2 and 3.4 (y -5.8, -4.6), the modex in the
# first, RESCUE above the gun-port panel in the second. Fin: one above another on the panel between the front spar joint
# and the rudder hinge, each centred in that swept panel at its height.
LETTERING = (
    ('nose_modex', 'modex', FORWARD, -5.2, .14, 1.05, .43, 'side', BOTH),
    ('rescue', 'rescue', FORWARD, -3.95, .37, .52, .10, 'side', BOTH),
    ('no_step_wing_root', 'no_step', WINGS, 1.35, 1.60, NO_STEP_WIDTH, NO_STEP_HEIGHT, 'top', BOTH),
    ('no_step_flap', 'no_step', ('flap_L_visible', 'flap_R_visible'), 1.55, 3.70, NO_STEP_WIDTH, NO_STEP_HEIGHT, 'top', BOTH),
    ('no_step_aileron', 'no_step', ('aileron_L_visible', 'aileron_R_visible'), 2.65, 3.65, NO_STEP_WIDTH, NO_STEP_HEIGHT,
     'top', BOTH),
    ('fin_modex', 'modex', ('fin_skin',), 6.156, 1.47, .90, .36, 'side', BOTH),
)
# The faction word on the fin is PALA's own lettering; stock BDF fighters (Revoker, Ifrit) carry no faction word.
FACTION_LETTERING = {'PALA': (('pala', 'pala', ('fin_skin',), 5.95, 1.135, .68, .17, 'side', BOTH),), 'BDF': ()}
# Roundels where the stock FS-12 Revoker, the donor, wears them: both fin faces on every livery; PALA on all four wing
# faces, BDF on the left wing's upper face and the right wing's lower one; none on the fuselage. The Revoker's are 0.87 m
# (PALA) and 0.99 m (BDF) across. The Icarus's sit on the fin panel between the front spar joint and the rudder, above
# the modex, and on the outer wing panel between the spars, outboard of the fuel filler, each sized to that panel with
# decal_checks.py's seam and edge clearances. Widths and heights keep each roundel's own ink aspect (PALA 480 x 488,
# BDF 499 x 291 source px).
FIN = ('fin_skin',), 6.70, 2.10
WING = WINGS, 2.88, 2.88
FACTION_MARKS = {
    'PALA': (('roundel_fin', 'PALA', *FIN, .74, .752, 'side', BOTH),
             ('roundel_wing_upper', 'PALA', *WING, .68, .691, 'top', BOTH),
             ('roundel_wing_lower', 'PALA', *WING, .68, .691, 'bottom', BOTH)),
    'BDF': (('roundel_fin', 'BDF', *FIN, .80, .467, 'side', BOTH),
            ('roundel_wing_upper', 'BDF', *WING, .68, .397, 'top', LEFT),
            ('roundel_wing_lower', 'BDF', *WING, .68, .397, 'bottom', RIGHT)),
}


def placements(faction):
    return LETTERING + FACTION_LETTERING[faction] + FACTION_MARKS[faction]


def palette(pixels, count, iterations=12):
    """Farthest-point seeded k-means: the decal's flat print colours."""
    rng = np.random.default_rng(0)
    pixels = pixels[rng.choice(len(pixels), min(len(pixels), 60000), replace=False)]
    centres = [pixels[np.argmin(pixels.sum(axis=1))]]
    for _ in range(count - 1):
        centres.append(pixels[np.argmax(np.min([((pixels - c) ** 2).sum(1) for c in centres], axis=0))])
    centres = np.array(centres)
    for _ in range(iterations):
        nearest = np.argmin(((pixels[:, None] - centres[None]) ** 2).sum(-1), axis=1)
        centres = np.array([pixels[nearest == i].mean(0) for i in range(count)])
    return centres


def flat_print(rgb, count, ellipse=False, solid=False, stripes=False):
    """Crop to the ink, snap each pixel to one of `count` print colours, drop wear specks, antialias edges.

    The generated sheets carry painted wear; on the aircraft it reads as pixel damage, so it is removed here.
    Returns premultiplied RGBA with a transparent pad.
    """
    rgb = rgb.astype(np.float32) / 255
    ink = rgb.min(axis=2) < .66
    yy, xx = np.where(ink)
    box = slice(yy.min(), yy.max() + 1), slice(xx.min(), xx.max() + 1)
    rgb, ink = rgb[box], ink[box]
    h, w = ink.shape
    if ellipse:
        y, x = np.mgrid[:h, :w]
        radius = np.sqrt(((x + .5) / w * 2 - 1) ** 2 + ((y + .5) / h * 2 - 1) ** 2)
        alpha = np.clip((1 - radius) * min(h, w) / 2, 0, 1)
    elif solid:
        alpha = np.ones((h, w), np.float32)
    else:
        # Fill enclosed wear specks; counters and stencil bridges open to the background and stay.
        shape = ink.copy()
        holes, _ = label(~shape)
        shape |= (np.bincount(holes.ravel())[holes] < 400) & (holes > 0)
        blobs, _ = label(shape)
        shape &= np.bincount(blobs.ravel())[blobs] >= 400
        # Worn edge notches under about 3 source px (3 mm on the aircraft) straighten out.
        shape = gaussian_filter(shape.astype(np.float32), 3) > .5
        alpha = np.clip(gaussian_filter(shape.astype(np.float32), 1.2) * 2 - .5, 0, 1)
    opaque = alpha > .5
    colours = palette(rgb[opaque], count)
    nearest = np.argmin(((rgb[..., None, :] - colours) ** 2).sum(-1), axis=-1)
    if stripes:
        # A fin flash is plain vertical stripes: each column takes its majority colour, which drops the sheet's
        # painted chevron and tears.
        nearest[:] = [np.bincount(column, minlength=count).argmax() for column in nearest.T]
    # A 3 px majority vote removes wear specks inside each colour field; edges between colours stay sharp.
    if ellipse:
        # The outer ring is one colour; the sheet's white background must not bleed into its rim.
        nearest[radius > .9] = np.argmin(colours.sum(-1))
    votes = np.stack([gaussian_filter((nearest == i).astype(np.float32), 3) for i in range(count)], -1)
    soft = np.stack([gaussian_filter((votes.argmax(-1) == i).astype(np.float32), .9) for i in range(count)], -1)
    flat = (soft[..., None] * colours).sum(-2) / np.maximum(soft.sum(-1, keepdims=True), 1e-6)
    rgba = np.dstack((flat * alpha[..., None], alpha)).astype(np.float32)
    return np.pad(rgba, ((PAD, PAD), (PAD, PAD), (0, 0)))


def faction_roundel(faction):
    """The stock roundel, cropped to its ink and premultiplied, from the local asset export."""
    paths = ROOT / 'tools/local-paths.json'
    export = json.loads(paths.read_text()).get('game_export') if paths.is_file() else None
    path = export and ROOT.joinpath(export, 'Texture2D', FACTION_ROUNDELS[faction] + '.png')
    if not path or not path.is_file():
        raise SystemExit(f'FACTION MARKS FAIL: {FACTION_ROUNDELS[faction]}.png not found; set `game_export` in '
                         'tools/local-paths.json to the game\'s asset export folder (the one holding Texture2D)')
    rgba = np.asarray(Image.open(path).convert('RGBA'), np.float32) / 255
    yy, xx = np.where(rgba[..., 3] > 0)
    rgba = rgba[yy.min():yy.max() + 1, xx.min():xx.max() + 1]
    rgba[..., :3] *= rgba[..., 3:]
    return np.pad(rgba, ((PAD, PAD), (PAD, PAD), (0, 0)))


def sources(roundels=False):
    """The flat-printed lettering; with `roundels`, the faction roundels from the local asset export too.

    Compose never asks for the roundels, so the maps it writes into the repository cannot carry them; faction_marks.py
    paints them into the textures Unity builds from, and decal_checks.py reads them to check their placement.
    """
    decals = {'modex': flat_print(np.asarray(Image.open(SOURCE / 'digit.png').convert('RGB')), 1)}
    sheet = np.asarray(Image.open(SOURCE / 'stencils.png').convert('RGB'))
    h = sheet.shape[0]
    for name, (a, b) in {'pala': (0, .37), 'rescue': (.37, .67), 'no_step': (.67, 1)}.items():
        decals[name] = flat_print(sheet[int(a * h):int(b * h)], 1)
    canvas = Image.new('RGB', (1600, 1000), '#e6e8e7')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(ROOT / 'art/textures/fonts/BarlowCondensed-SemiBold.ttf'), 24)
    for i, (name, rgba) in enumerate(decals.items()):
        straight = rgba.copy()
        straight[..., :3] /= np.maximum(rgba[..., 3:], 1e-6)
        image = Image.fromarray(np.uint8(np.clip(straight, 0, 1) * 255 + .5), 'RGBA')
        image.thumbnail((650, 260))
        canvas.paste(image, ((i % 2) * 800 + 60, (i // 2) * 330 + 20), image)
        draw.text(((i % 2) * 800 + 60, (i // 2) * 330 + 290), name.replace('_', ' '), fill='#202932', font=font)
    canvas.save(OUT / 'insignia_lettering_sheet.png')
    if roundels:
        decals.update({faction: faction_roundel(faction) for faction in FACTION_ROUNDELS})
    return decals


def ink_projection(placement):
    """World plane coordinates and side (+1 left, -1 right) to s,t across the placement's ink box, 0 to 1.

    Upper decals read for someone behind the trailing edge, tops forward; lower ones for someone underneath, tops
    forward; upper lettering named in FACING_FUSELAGE turns a quarter, using the wings' separate UV islands.
    """
    label, _, _, cy, cz, su, sv, face, _ = placement
    if face == 'top':
        if label in FACING_FUSELAGE:
            return lambda x, y, side: (.5 + (y - cz) * side / su, .5 + (x * side - cy) / sv)
        return lambda x, y, side: (.5 - (x - side * cy) / su, .5 + (y - cz) / sv)
    if face == 'bottom':
        return lambda x, y, side: (.5 + (x - side * cy) / su, .5 + (y - cz) / sv)
    return lambda y, z, side: ((y - cy) * side / su + .5, .5 - (z - cz) / sv)


def ink_to_uv(s, t, decal):
    """Ink-box s,t to u,v on the padded decal image, whose ink fills all but PAD pixels a side."""
    ph, pw = decal.shape[:2]
    return .5 + (s - .5) * (pw - 2 * PAD) / pw, .5 + (t - .5) * (ph - 2 * PAD) / ph


def projection(placement, decal):
    """World plane coordinates and side to u,v on the padded decal, keeping the requested ink-box size."""
    to_st = ink_projection(placement)
    return lambda a, b, side: ink_to_uv(*to_st(a, b, side), decal)


def projection_coordinates(position, placement):
    """Upper and lower decals use world x,y; side decals use y,z."""
    return position[..., :2] if placement[7] != 'side' else position[..., 1:]


def covered(position, normal, part, names, placement, decal=None, margin_m=0.):
    """Texels facing the placement's projection on its sides, inside its box, with their side.

    With a decal the box is its padded image and the mapping is to its u,v; without one it is the ink box grown by
    margin_m and the mapping is to ink-box s,t.
    """
    to_uv = projection(placement, decal) if decal is not None else ink_projection(placement)
    lo_u, lo_v = (0, 0) if decal is not None else (-margin_m / placement[5], -margin_m / placement[6])
    face, sides = placement[7], placement[8]
    facing = {'top': normal[..., 2], 'bottom': -normal[..., 2]}.get(face, abs(normal[..., 0]))
    side = np.where(position[..., 0] >= 0, 1, -1)
    eligible = (np.isin(part, [names.index(s) + 1 for s in placement[2]]) & (facing > SIDE_FACING)
                & np.isin(side, sides))
    coordinates = projection_coordinates(position, placement)
    u, v = to_uv(coordinates[..., 0], coordinates[..., 1], side)
    return eligible & (u >= lo_u) & (u <= 1 - lo_u) & (v >= lo_v) & (v <= 1 - lo_v), side, to_uv


def place_decals(colour, position, normal, part, names, decals, spec, paint_coverage, dx, dy):
    """Box-filter each decal over every texel's world footprint (dx, dy: world step per texel)."""
    mask = np.zeros(part.shape, bool)
    report = []
    offsets = (np.arange(SUBSAMPLES) + .5) / SUBSAMPLES - .5
    for placement in placements(spec['faction']):
        label, name, allowed, cy, cz, width, height, face, sides = placement
        if name in FACTION_ROUNDELS:
            continue  # painted after compose by faction_marks.py, from mark_footprints' record
        decal = decals[name]
        selected, side, to_uv = covered(position, normal, part, names, placement, decal)
        p, ddx, ddy, flip = position[selected], dx[selected], dy[selected], side[selected]
        ink = np.zeros((len(p), 4), np.float32)
        for oy in offsets:
            for ox in offsets:
                q = p + ddx * ox + ddy * oy
                coordinates = projection_coordinates(q, placement)
                ink += sample(decal, *to_uv(coordinates[:, 0], coordinates[:, 1], flip))
        ink /= SUBSAMPLES ** 2
        alpha = ink[:, 3:4]
        rgb = ink[:, :3] / np.maximum(alpha, 1e-6)
        if spec['light_markings'] and name not in FACTION_ROUNDELS:
            rgb = np.full_like(rgb, .68)
        if name == 'modex' and 'number_colour' in spec:
            # Stock BDF numbers are printed near-black (CAS1 BDF Matte Gray's 7277 measures 8,8,8).
            rgb = np.broadcast_to(np.array(spec['number_colour'], rgb.dtype), rgb.shape)
        colour[selected] = colour[selected] * (1 - alpha) + rgb * alpha
        if paint_coverage is not None:
            paint_coverage[selected] = 1 - (1 - paint_coverage[selected]) * (1 - alpha[:, 0])
        mask[selected] |= alpha[:, 0] > .01
        counts = [int((selected & ((position[..., 0] >= 0) if s else (position[..., 0] < 0))).sum()) for s in (1, 0)]
        visible_ink = np.zeros(part.shape, bool)
        visible_ink[selected] = alpha[:, 0] > .01
        ink_counts = [int((visible_ink & ((position[..., 0] >= 0) if s else (position[..., 0] < 0))).sum()) for s in (1, 0)]
        wanted = [counts[i] for i, s in enumerate((1, -1)) if s in sides]
        wanted_ink = [ink_counts[i] for i, s in enumerate((1, -1)) if s in sides]
        if min(wanted) == 0:
            raise ValueError('Decal misses one side: ' + label)
        if min(wanted_ink) == 0:
            raise ValueError('Decal has no visible ink on one side: ' + label)
        centre_key = 'centre_yz' if face == 'side' else 'centre_xy'
        report.append({'label': label, 'source': name, 'parts': list(allowed), centre_key: [cy, cz], 'face': face,
                       'sides': list(sides), 'size_m': [width, height], 'left_right_texels': counts,
                       'left_right_ink_texels': ink_counts, 'supersamples_per_texel': SUBSAMPLES ** 2})
    actual = sorted(names[i - 1] for i in np.unique(part[mask]))
    if any((n.endswith('_visible') or n.startswith(('wing_', 'pylon_', 'intake_'))) and n not in TOP_PARTS
           for n in actual):
        raise ValueError('Decals touched mirrored islands: ' + str(actual))
    return mask, report, actual


MARK_MARGIN_M = .01  # a texel's supersamples reach up to half a texel past the ink box; this covers it with room
# The map from atlas texel to ink box may miss the true projection by this much at most: 1.5 texels, 5 mm. Baked
# positions are linear per triangle, so no smooth map is exact; the cubic is within 0.01 texel on 99.9% of a footprint
# and misses by up to about 1 texel only on a few texels in the ink box's corners on the curved wing rims.
MARK_RESIDUAL_TEXELS = 1.5
MARK_SCALE = 100.  # texels: keeps the cubic's basis near 1 over a footprint


MARK_CUBIC_TEXELS = 200  # smaller footprint pieces (fragments of a neighbouring island at the margin) take an affine


def mark_basis(col, row, terms):
    """Polynomial in texel offsets from a footprint's origin, by total degree: 3 terms is affine, 10 cubic.

    Wing skins are cambered, so their islands are not affine in the atlas.
    """
    x, y = np.asarray(col, np.float64) / MARK_SCALE, np.asarray(row, np.float64) / MARK_SCALE
    return np.stack([x ** (d - j) * y ** j for d in range(4) for j in range(d + 1)][:terms], -1)


def mark_footprints(position, normal, part, names, seam, fastener):
    """Where faction_marks.py paints each roundel, without the roundel: compose records it in faction_marks.json.

    Per mark, side and UV island: the texel runs of its footprint, a cubic from texel (column, row) to ink-box s,t,
    fitted over those texels and held to MARK_RESIDUAL_TEXELS of the true projection, and the seam and fastener fields under the
    footprint wherever they are not 0. Compose shades decals by those fields after placing them, so faction_marks.py
    shades the roundel by the same factor and its result equals painting the roundel in compose.
    """
    marks = []
    for faction, entries in FACTION_MARKS.items():
        for placement in entries:
            selected, side, to_st = covered(position, normal, part, names, placement, margin_m=MARK_MARGIN_M)
            for sign in placement[8]:
                # A footprint can cross a UV cut (the fin's face is more than one island); each island gets its own map.
                islands, count = label(selected & (side == sign))
                for island in range(1, count + 1):
                    rows, cols = np.nonzero(islands == island)
                    coordinates = projection_coordinates(position[rows, cols], placement)
                    st = np.stack(to_st(coordinates[:, 0], coordinates[:, 1], sign), -1)
                    origin = [float(cols.mean().round()), float(rows.mean().round())]
                    basis = mark_basis(cols - origin[0], rows - origin[1], 10 if len(rows) >= MARK_CUBIC_TEXELS else 3)
                    coefficients, *_ = np.linalg.lstsq(basis, st, rcond=None)
                    miss = abs(basis @ coefficients - st) * np.array(placement[5:7]) * PX_PER_M
                    if miss.max() > MARK_RESIDUAL_TEXELS:
                        raise ValueError(f'{faction} {placement[0]}: the footprint is not flat in the atlas '
                                         f'({miss.max():.2f} texels off its map)')
                    runs = []
                    for row in np.unique(rows):
                        columns = np.sort(cols[rows == row])
                        breaks = np.flatnonzero(np.diff(columns) > 1)
                        for start, stop in zip(np.r_[0, breaks + 1], np.r_[breaks, len(columns) - 1]):
                            runs.append([int(row), int(columns[start]), int(columns[stop]) + 1])
                    bumps = (seam[rows, cols] > 1e-5) | (fastener[rows, cols] > 1e-5)
                    marks.append({'faction': faction, 'label': placement[0], 'side': sign, 'island': island,
                                  'origin': origin, 'coefficients': coefficients.T.tolist(),
                                  'max_residual_texels': round(float(miss.max()), 4), 'runs': runs,
                                  'relief': [[int(r), int(c), round(float(a), 5), round(float(b), 5)]
                                             for r, c, a, b in zip(rows[bumps], cols[bumps], seam[rows, cols][bumps],
                                                                   fastener[rows, cols][bumps])]})
    return marks
