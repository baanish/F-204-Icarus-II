"""Flat-print the generated decals and place them, supersampled, only on unique skin islands."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, label

from rasterize import ROOT, SOURCE, OUT, sample

SUBSAMPLES = 4  # per texel axis: 16 world-space samples per texel box-filter the decal edges
PAD = 6  # transparent source pixels around every decal so supersamples past its edge read clear
SIDE_FACING = .45  # |normal x| above which a texel takes side decals
TOP_PARTS = ('wing_skin_L', 'wing_skin_R', 'flap_L_visible', 'flap_R_visible',
             'aileron_L_visible', 'aileron_R_visible')
FORWARD = ('skin_forward_L', 'skin_forward_R')
# label, source, parts, centre y,z (side) or positive x,y (top), width, height, in world metres; both sides.
# decal_checks.py holds each one clear of the canopy, physical edges, panel seams and light fittings.
# Forward: each inside one skin panel between the butt joints at s 2.2, 3.4 and 4.6 (y -5.8, -4.6, -3.4), the modex
# in the first, RESCUE above the gun-port panel in the second, the
# roundel in the third ahead of the Bare Metal band. Fin: one above another on the panel between the front spar joint
# and the rudder hinge, each centred in that swept panel at its height, the formation strip ahead of the joint.
PLACEMENTS = (
    ('nose_modex', 'modex', FORWARD, -5.2, .14, 1.05, .43),
    ('roundel', 'roundel', FORWARD, -3.08, .20, .50, .50),
    ('rescue', 'rescue', FORWARD, -3.95, .37, .52, .10),
    ('no_step_wing_root', 'no_step', ('wing_skin_L', 'wing_skin_R'), 1.35, 1.60, .38, .07),
    ('no_step_flap', 'no_step', ('flap_L_visible', 'flap_R_visible'), 1.55, 3.70, .38, .07),
    ('no_step_aileron', 'no_step', ('aileron_L_visible', 'aileron_R_visible'), 2.65, 3.65, .38, .07),
    ('fin_flash', 'flash', ('fin_skin',), 6.60, 2.05, .35, .66),
    ('fin_modex', 'modex', ('fin_skin',), 6.156, 1.47, .90, .36),
    ('pala', 'pala', ('fin_skin',), 5.95, 1.135, .68, .17),
)


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


def sources():
    sheet = np.asarray(Image.open(SOURCE / 'mark.png').convert('RGB'))
    split = int(sheet.shape[1] * 0.61)
    decals = {'roundel': flat_print(sheet[:, :split], 2, ellipse=True),
              'flash': flat_print(sheet[:, split:], 3, solid=True, stripes=True),
              'modex': flat_print(np.asarray(Image.open(SOURCE / 'digit.png').convert('RGB')), 1)}
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
    return decals


def projection(placement, decal):
    """World plane coordinates and side (+1 left, -1 right) to decal u,v, retaining the requested ink-box size.

    Upper lettering reads in the same world x direction on both wings, using their separate UV islands.
    """
    _, _, _, cy, cz, width, height = placement
    ph, pw = decal.shape[:2]
    su, sv = width * pw / (pw - 2 * PAD), height * ph / (ph - 2 * PAD)
    if placement[2][0] in TOP_PARTS:
        return lambda x, y, side: ((x - side * cy) / su + .5, .5 - (y - cz) / sv)
    return lambda y, z, side: ((y - cy) * side / su + .5, .5 - (z - cz) / sv)


def projection_coordinates(position, placement):
    """Upper wing lettering uses world x,y; side lettering uses y,z."""
    return position[..., :2] if placement[2][0] in TOP_PARTS else position[..., 1:]


def covered(position, normal, part, names, placement, decal):
    """Texels facing the placement's side or upper projection, inside its box, with their side."""
    to_uv = projection(placement, decal)
    facing = normal[..., 2] if placement[2][0] in TOP_PARTS else abs(normal[..., 0])
    eligible = np.isin(part, [names.index(s) + 1 for s in placement[2]]) & (facing > SIDE_FACING)
    side = np.where(position[..., 0] >= 0, 1, -1)
    coordinates = projection_coordinates(position, placement)
    u, v = to_uv(coordinates[..., 0], coordinates[..., 1], side)
    return eligible & (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1), side, to_uv


def place_decals(colour, position, normal, part, names, decals, spec, paint_coverage, dx, dy):
    """Box-filter each decal over every texel's world footprint (dx, dy: world step per texel)."""
    mask = np.zeros(part.shape, bool)
    report = []
    offsets = (np.arange(SUBSAMPLES) + .5) / SUBSAMPLES - .5
    for placement in PLACEMENTS:
        label, name, allowed, cy, cz, width, height = placement
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
        if spec['light_markings'] and name not in ('roundel', 'flash'):
            rgb = np.full_like(rgb, .68)
        colour[selected] = colour[selected] * (1 - alpha) + rgb * alpha
        if paint_coverage is not None:
            paint_coverage[selected] = 1 - (1 - paint_coverage[selected]) * (1 - alpha[:, 0])
        mask[selected] |= alpha[:, 0] > .01
        counts = [int((selected & ((position[..., 0] >= 0) if s else (position[..., 0] < 0))).sum()) for s in (1, 0)]
        visible_ink = np.zeros(part.shape, bool)
        visible_ink[selected] = alpha[:, 0] > .01
        ink_counts = [int((visible_ink & ((position[..., 0] >= 0) if s else (position[..., 0] < 0))).sum()) for s in (1, 0)]
        if min(counts) == 0:
            raise ValueError('Decal misses one side: ' + label)
        if min(ink_counts) == 0:
            raise ValueError('Decal has no visible ink on one side: ' + label)
        centre_key = 'centre_xy' if allowed[0] in TOP_PARTS else 'centre_yz'
        report.append({'label': label, 'source': name, 'parts': list(allowed), centre_key: [cy, cz],
                       'size_m': [width, height], 'left_right_texels': counts, 'left_right_ink_texels': ink_counts,
                       'supersamples_per_texel': SUBSAMPLES ** 2})
    actual = sorted(names[i - 1] for i in np.unique(part[mask]))
    if any((n.endswith('_visible') or n.startswith(('wing_', 'pylon_', 'intake_'))) and n not in TOP_PARTS
           for n in actual):
        raise ValueError('Decals touched mirrored islands: ' + str(actual))
    return mask, report, actual
