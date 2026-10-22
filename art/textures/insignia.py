"""Crop original generated decals and place them only on unique skin islands."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from rasterize import ROOT, SOURCE, OUT, sample


def crop_ink(rgb, ellipse=False, solid=False):
    ink = rgb.min(axis=2) < 170
    yy, xx = np.where(ink)
    rgb = rgb[yy.min():yy.max() + 1, xx.min():xx.max() + 1].astype(np.float32) / 255
    alpha = np.clip((0.92 - rgb.min(axis=2)) / 0.6, 0, 1)
    if solid:
        alpha[:] = 1
    if ellipse:
        y, x = np.mgrid[:rgb.shape[0], :rgb.shape[1]]
        radius = np.sqrt(((x + 0.5) / rgb.shape[1] * 2 - 1) ** 2 + ((y + 0.5) / rgb.shape[0] * 2 - 1) ** 2)
        alpha = np.clip((1 - radius) * min(rgb.shape[:2]) / 2, 0, 1)
    return np.dstack((rgb, alpha))


def sources():
    sheet = np.asarray(Image.open(SOURCE / 'mark.png').convert('RGB'))
    split = int(sheet.shape[1] * 0.61)
    decals = {'roundel': crop_ink(sheet[:, :split], ellipse=True), 'flash': crop_ink(sheet[:, split:], solid=True),
              'modex': crop_ink(np.asarray(Image.open(SOURCE / 'digit.png').convert('RGB')))}
    sheet = np.asarray(Image.open(SOURCE / 'stencils.png').convert('RGB'))
    h = sheet.shape[0]
    for name, (a, b) in {'pala': (0, .37), 'rescue': (.37, .67), 'no_step': (.67, 1)}.items():
        decals[name] = crop_ink(sheet[int(a * h):int(b * h)])
    canvas = Image.new('RGB', (1600, 1000), '#e6e8e7')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(ROOT / 'art/textures/fonts/BarlowCondensed-SemiBold.ttf'), 24)
    for i, (name, rgba) in enumerate(decals.items()):
        image = Image.fromarray(np.uint8(rgba * 255 + .5), 'RGBA')
        image.thumbnail((650, 260))
        canvas.paste(image, ((i % 2) * 800 + 60, (i // 2) * 330 + 20), image)
        draw.text(((i % 2) * 800 + 60, (i // 2) * 330 + 290), name.replace('_', ' '), fill='#202932', font=font)
    canvas.save(OUT / 'insignia_lettering_sheet.png')
    return decals


def place_decals(colour, position, normal, part, names, decals, spec):
    mask = np.zeros(part.shape, bool)
    report = []
    def place(name, allowed, cy, cz, width, height):
        eligible = np.isin(part, [names.index(s) + 1 for s in allowed]) & (abs(normal[..., 0]) > .45)
        u = (position[..., 1] - cy) * np.where(position[..., 0] >= 0, 1, -1) / width + .5
        v = .5 - (position[..., 2] - cz) / height
        selected = eligible & (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
        ink = sample(decals[name], u[selected], v[selected]).copy()
        if spec['light_markings'] and name not in ('roundel', 'flash'):
            ink[:, :3] = .68
        colour[selected] = colour[selected] * (1 - ink[:, 3:4]) + ink[:, :3] * ink[:, 3:4]
        mask[selected] |= ink[:, 3] > .01
        counts = [int((selected & ((position[..., 0] >= 0) if side else (position[..., 0] < 0))).sum()) for side in (1, 0)]
        visible_ink = np.zeros(part.shape, bool)
        visible_ink[selected] = ink[:, 3] > .01
        ink_counts = [int((visible_ink & ((position[..., 0] >= 0) if side else (position[..., 0] < 0))).sum()) for side in (1, 0)]
        if min(counts) == 0:
            raise ValueError('Decal misses one side: ' + name)
        if min(ink_counts) == 0:
            raise ValueError('Decal has no visible ink on one side: ' + name)
        report.append({'source': name, 'parts': allowed, 'centre_yz': [cy, cz], 'size_m': [width, height],
                       'left_right_texels': counts, 'left_right_ink_texels': ink_counts})
    forward = ['skin_forward_L', 'skin_forward_R']
    place('modex', forward, -5.5, .14, 1.05, .43)
    place('roundel', forward, -3.3, .22, .56, .56)
    place('rescue', forward, -3.3, .67, .52, .10)
    place('no_step', forward, -4.5, -.15, .38, .07)
    place('flash', ['fin_skin'], 6.25, 2.13, .38, .72)
    place('modex', ['fin_skin'], 6.25, 1.43, 1.0, .40)
    place('pala', ['fin_skin'], 6.18, 1.08, .76, .19)
    actual = sorted(names[i - 1] for i in np.unique(part[mask]))
    if any(n.endswith('_visible') or n.startswith(('wing_', 'pylon_', 'intake_')) for n in actual):
        raise ValueError('Decals touched mirrored islands: ' + str(actual))
    return mask, report, actual
