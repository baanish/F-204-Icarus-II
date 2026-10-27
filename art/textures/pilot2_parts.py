"""Repack UV charts into dense part guides, preserve generation context and stitch the results."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label, find_objects, binary_erosion, binary_closing, binary_fill_holes, distance_transform_edt
from scipy.spatial import cKDTree

from record_paths import portable_record, portable_text, resolve_record
from rasterize import ROOT, OUT as BAKE, SOURCE, sample
from panels import ACCESS_PANELS

OUT = ROOT / '.cache/review/wave2/p9b-round2'
SOURCES = SOURCE / 'pilot2'
SIZE = 1536
GROUPS = {
    'radome': ('radome', [2, 3, 4, 6], 'The dielectric radar nose, ahead of the cockpit. Four tapered charts wrap its left, underside, right and top quadrants. This is smooth composite, not a sheet-metal patchwork. Only the attachment rim at the wide aft end has a fine joint. No rivet grid across the composite. Very faint longitudinal cleaning traces, no metal scratches.'),
    'forward_left': ('skin_forward_L', [12], 'The left forward fuselage side below the cockpit, between the radome and intake. Forward is toward the radome. The closed gun-port panel is an avionics access cover, no gun opening. Frame stations support circumferential fastener rows, not a dense rectangular greeble grid. Leave clean stencil zones under the cockpit sill; decals come later. The canopy sill is above this sheet, the intake is aft.'),
    'wing_root': ('wing_skin_L', [13], 'The upper inboard wing root and strake, joining the left fuselage fillet to the main upper wing. A narrow curved sheet, not an entire triangular wing. The yellow guide zone indicates a restrained antislip walkway near the fuselage. It is a subtle grey material change with soft shoe scuffs, no black racing stripe or text. Blue structural lines follow the actual spars and ribs. Outboard it meets the upper wing.'),
    'wing_upper': ('wing_skin_L', [7, 2], 'Two upper wing charts: inboard cranked panel and outboard fixed wing box. The smaller tip panel starts beyond the planform crank. The leading-edge flap, trailing flap and aileron are separate parts, absent from these islands. Their cut edges are real hinge boundaries, not extra access covers. Follow the two spars and actual rib stations. Keep a small fuel filler within the tank box, between the spars and outboard of the crank, diameter about 0.11 m. No walkway outboard.'),
    'fin_left': ('fin_skin', [11, 12, 1], 'Left face of the vertical fin, its lower root fillet and small top cap, above the rear fuselage. The rudder is a separate trailing control surface and is absent. Use a fine perimeter joint near that cut boundary, a few flush fasteners near the base and one restrained root service cover. No invented fin spar grid: the current model has no separate fin spar layout exported here. Keep broad skin clean. Generated detail is reflected in aircraft world coordinates to the other face; the compositor adds readable separate fin markings.'),
}


def inputs():
    data = np.load(BAKE / 'geometry_maps.npz')
    return data, resolve_record(json.loads((BAKE / 'atlas_triangles.json').read_text()))['parts']


def chart_masks(part, name, names):
    return label(part == names.index(name) + 1)[0]


def font(size):
    return ImageFont.truetype(str(ROOT / 'art/textures/fonts/BarlowCondensed-SemiBold.ttf'), size)


def layout(charts):
    # A shelf pack keeps one scale for every island in a call. Only 90 degree rotations are permitted.
    boxes = []
    for index, box in charts:
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start
        rotate = h > w * 2
        boxes.append((index, box, rotate, h if rotate else w, w if rotate else h))
    best = None
    for scale in np.arange(.5, 7, .02):
        x, y, row = 40, 150, 0
        packed = []
        for index, box, rotate, w, h in sorted(boxes, key=lambda q: -q[4]):
            width, height = int(w * scale), int(h * scale)
            if x + width > SIZE - 40:
                x, y, row = 40, y + row + 85, 0
            if width > SIZE - 80 or y + height > SIZE - 95:
                break
            packed.append({'component': index, 'atlas_box': [box[1].start, box[0].start, box[1].stop, box[0].stop],
                           'rotate_ccw': rotate, 'guide_box': [x, y, x + width, y + height]})
            x += width + 60
            row = max(row, height)
        if len(packed) == len(boxes):
            best = scale, packed
    if best is None:
        raise ValueError('Part charts do not fit guide')
    return best


def guide_array(array, box, rotate, size, nearest=False):
    x0, y0, x1, y1 = box
    crop = array[y0:y1, x0:x1]
    if rotate:
        crop = np.rot90(crop)
    return Image.fromarray(crop).resize(size, Image.Resampling.NEAREST if nearest else Image.Resampling.BILINEAR)


def source_charts(image, count):
    # Dark panel strokes can bisect an island. Close those strokes before finding its outer silhouette.
    silhouette = binary_fill_holes(binary_closing(image.mean(axis=2) > .32, iterations=3))
    labels, _ = label(silhouette)
    candidates = [(i, box, int((labels[box] == i).sum())) for i, box in enumerate(find_objects(labels), 1)
                  if box is not None and (labels[box] == i).sum() > 200]
    candidates = sorted(candidates, key=lambda c: -c[2])[:count]
    if len(candidates) != count:
        raise ValueError(f'Expected {count} source silhouettes, found {len(candidates)}')
    candidates.sort(key=lambda c: (c[1][0].start, c[1][1].start))
    return labels, candidates


def guides():
    if any((SOURCES / (name + suffix)).exists() for name in GROUPS
           for suffix in ('.png', '.generation.json')):
        if (SOURCE / 'full/source-atlas/native/parts.json').is_file():
            from full_skin_guides import inventory
            from source_atlas_mapping import current_guides
            current = OUT / 'full'
            inventory()
            current_guides(current / 'parts.json')
            print('CURRENT OWNERSHIP ONLY; accepted pilot generation inputs preserved')
            return
        raise ValueError('Accepted pilot generation inputs are immutable; restore the frozen native source pack before inventory')
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)
    data, names = inputs()
    part, pos, normal = data['part'], data['position'][..., :3], data['normal'][..., :3]
    structure = resolve_record(json.loads((OUT / 'structure.json').read_text()))
    frame = structure['frames']
    x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
    frame_distance = abs((y + structure['S0'] - frame['s0'] + frame['pitch'] / 2) % frame['pitch'] - frame['pitch'] / 2)
    wp = np.array(structure['wing_profile'])
    le, chord = np.interp(x, wp[:, 1], wp[:, 0]) - structure['S0'], np.interp(x, wp[:, 1], wp[:, 3])
    fraction = (y - le) / chord
    spars = structure['spars']
    spar_distance = np.minimum(abs(fraction - spars['front_f']), abs(fraction - spars['rear_f'])) * chord
    x0, x1 = .62, wp[-1, 1] - .06
    rib_x = np.linspace(x0, x1, int((x1 - x0) / spars['rib_pitch']) + 1)
    rib_distance = np.min(abs(x[..., None] - rib_x), axis=-1)
    wing_lines = (spar_distance < .009) | ((rib_distance < .009) & (fraction > spars['front_f']) & (fraction < spars['rear_f']))
    manifest = {'guide_size': SIZE, 'groups': {}, 'shared_style': (ROOT / 'art/textures/round2_style.txt').as_posix()}
    for name, (part_name, components, description) in GROUPS.items():
        labels = chart_masks(part, part_name, names)
        objects = find_objects(labels)
        selected = np.isin(labels, components)
        charts = [(i, objects[i - 1]) for i in components]
        scale, packed = layout(charts)
        guide = Image.new('RGB', (SIZE, SIZE), '#252b30')
        clean = Image.new('RGB', (SIZE, SIZE), '#252b30')
        draw = ImageDraw.Draw(guide)
        draw.text((40, 20), name.replace('_', ' ').upper() + ' | UV CHART GUIDE', font=font(36), fill='white')
        draw.text((40, 72), 'BLUE structure | ORANGE access | YELLOW walkway | WHITE outline', font=font(25), fill='#b8c4cd')
        base = np.full((*part.shape, 3), 128, np.uint8)
        base[~selected] = (37, 43, 48)
        if name == 'forward_left':
            base[selected & (frame_distance < .009)] = (45, 157, 223)
            for _, allowed, cy, cz, width, tall in ACCESS_PANELS:
                if part_name in allowed:
                    dy, dz = abs(y - cy) - width / 2, abs(z - cz) - tall / 2
                    base[selected & (abs(np.maximum(dy, dz)) < .009)] = (242, 152, 51)
        if name.startswith('wing'):
            base[selected & wing_lines] = (45, 157, 223)
            if name == 'wing_root':
                walkway = selected & (x < 1.05) & (fraction > .28) & (fraction < .62)
                base[walkway] = (171, 155, 83)
        outline = selected & ~binary_erosion(selected)
        base[outline] = (235, 240, 240)
        clean_array = np.full_like(base, 128)
        clean_array[~selected] = (37, 43, 48)
        for item in packed:
            gx, gy, ex, ey = item['guide_box']
            size = ex - gx, ey - gy
            box, rotate = item['atlas_box'], item['rotate_ccw']
            guide.paste(guide_array(base, box, rotate, size, True), (gx, gy))
            clean.paste(guide_array(clean_array, box, rotate, size, True), (gx, gy))
            m = labels == item['component']
            p = pos[m]
            n = normal[m].mean(axis=0)
            bounds = np.array([p.min(0), p.max(0)])
            item['world_bounds_m'] = bounds.tolist()
            item['area_m2_at_150pxm'] = float(m.sum() / 150 ** 2)
            # Fit local UV directions to world coordinates, then rotate with the chart.
            yy, xx = np.where(m)
            uv = np.column_stack((xx - xx.mean(), yy - yy.mean()))
            projection = np.linalg.lstsq(p - p.mean(0), uv, rcond=None)[0]
            arrows = [('FWD', np.array([0, -1, 0]), '#65d6f5'), ('UP', np.array([0, 0, 1]), '#94eaaa'), ('OUT', np.array([1 if p[:, 0].mean() >= 0 else -1, 0, 0]), '#e2a2ec')]
            centre = np.array([(gx + ex) / 2, (gy + ey) / 2])
            for index, (label_text, axis, colour) in enumerate(arrows):
                v = axis @ projection
                if rotate:
                    v = np.array([v[1], -v[0]])
                if np.linalg.norm(v) < .15 * 150:
                    draw.text((gx, ey + 7 + index * 19), label_text + ' normal to sheet', font=font(17), fill=colour)
                else:
                    v = v / np.linalg.norm(v) * 60
                    start = centre + [0, (index - 1) * 28]
                    end = start + v
                    draw.line([tuple(start), tuple(end)], fill=colour, width=3)
                    back = end - v * .18
                    side = np.array([-v[1], v[0]]) * .1
                    draw.polygon([tuple(end), tuple(back + side), tuple(back - side)], fill=colour)
                    draw.text(tuple(end + 4), label_text, font=font(20), fill=colour)
            label_y = max(110, gy - 27)
            draw.text((gx, label_y), 'CHART ' + str(item['component']) + ' | ' + ','.join(f'{a:.2f}' for a in np.ptp(bounds, axis=0)) + ' m XYZ', font=font(20), fill='white')
        draw.text((40, SIZE - 47), f'{scale * 150:.0f} guide px/m | artwork uses the same square canvas | remove all guide ink', font=font(26), fill='white')
        guide.save(SOURCES / (name + '.guide.png'))
        clean.save(SOURCES / (name + '.template.png'))
        mask = Image.fromarray(selected.astype(np.uint8) * 255)
        mask.save(OUT / (name + '.mask.png'))
        manifest['groups'][name] = {'part': part_name, 'description': description, 'guide_scale': scale,
                                    'guide_px_per_m': scale * 150, 'charts': packed,
                                    'skin_texels': int(selected.sum()), 'mask': (OUT / (name + '.mask.png')).as_posix()}
    (OUT / 'parts.json').write_text(json.dumps(portable_record(manifest), indent=2))
    print('PILOT GUIDE PASS', {n: round(g['guide_px_per_m']) for n, g in manifest['groups'].items()})


def context(name):
    if any((SOURCES / (name + suffix)).exists() for suffix in ('.png', '.generation.json')):
        raise ValueError('Accepted pilot prompt and reference inputs are immutable: ' + name)
    manifest = resolve_record(json.loads((OUT / 'parts.json').read_text()))
    g = manifest['groups'][name]
    prior_parts = {'radome': [], 'forward_left': ['radome'], 'wing_root': ['forward_left'],
                   'wing_upper': ['wing_root'], 'fin_left': ['wing_upper']}
    generated = [n for n in prior_parts[name] if (SOURCES / (n + '.png')).exists()]
    # Preserve thin edge bands of prior part art, never a game texture or a livery atlas.
    references = []
    for other in generated:
        src = Image.open(SOURCES / (other + '.png')).convert('RGB')
        labels, candidates = source_charts(np.asarray(src, np.float32) / 255, len(manifest['groups'][other]['charts']))
        inside = np.isin(labels, [c[0] for c in candidates])
        distance = distance_transform_edt(inside)
        band = (distance >= 3) & (distance < 15)
        edge_values = np.asarray(src)[band]
        # Flatten the real island edge bands into a strip; placement stays documented in the part guides.
        indices = np.linspace(0, len(edge_values) - 1, src.width * 96).astype(int)
        tile = Image.fromarray(edge_values[indices].reshape(96, src.width, 3))
        path = SOURCES / (name + '.neighbor_' + other + '.png')
        tile.save(path)
        references.append(path.as_posix())
    shared = (ROOT / 'art/textures/round2_style.txt').read_text().strip()
    physical = '\n'.join(f"- Chart {c['component']}: world XYZ bounds in metres {c['world_bounds_m']}; surface area about {c['area_m2_at_150pxm']:.3f} square metres. Guide rectangle {c['guide_box']}. Rotated CCW 90 degrees: {c['rotate_ccw']}." for c in g['charts'])
    neighbors = {'radome': 'The aft wide rims meet the forward fuselage at the radome break. This first part has no generated neighbours. Keep these rims uniform.',
        'forward_left': 'Its forward rim meets the radome, its upper edge the cockpit sill and its aft edge the intake and mid fuselage. Radome art is available as a continuity reference. The sill and intake are not generated yet. Do not invent a joint crossing the radome break.',
        'wing_root': 'Inboard meets the skin_mid_L fillet, which stays round-1 during the pilot. Outboard meets wing_upper, generated next. Leave edge strips uniform neutral paint so seams can be joined. The forward fuselage is separated by the intake and is a style reference only.',
        'wing_upper': 'The inboard fixed sheet meets the already generated wing_root. The small outboard fixed box meets the inboard cranked sheet at the crank. LEF, flap and aileron edges meet separate moving parts that retain round-1 art during the pilot. Continue spar rows to corresponding positions, with no dark border around each UV chart.',
        'fin_left': 'The lower fillet meets the aft fuselage. The trailing cut meets the rudder, and the top meets the stabilator. These neighbours remain round-1 for the pilot. No generated adjacent part exists. Earlier parts are material-scale references only.'}[name]
    reference_list = [(SOURCES / (name + '.guide.png')).as_posix(), (SOURCES / 'style_anchor.png').as_posix(), (SOURCES / (name + '.template.png')).as_posix()] + references
    prompt = f"""Use case: stylized-concept. Asset type: flat UV albedo source for an aircraft part, not an aircraft illustration.
Target: {name}, {g['part']} of F-204 Icarus II, a modernised F-104 Starfighter interceptor in Primeva PALA service. Four final schemes are Navy blue-grey over light grey, Black night interceptor, Desert splinter and Bare Metal with high-visibility bands. This call supplies only neutral unmarked base detail; scripted scheme colours and decals are applied later.

Part and construction:
{g['description']}

Image 1 is our own labelled UV guide. Image 2 is our own generated style anchor, material treatment only. Image 3 is the clean UV silhouette template, the exact output layout. Remaining images, if any, are edge strips from our earlier generated parts, material continuity references only. Never reproduce guide labels, arrows, coloured construction ink or white outlines. Do not paint an aircraft view, perspective, wings or parts outside the supplied silhouettes. Paint every template island at its exact position, scale and orientation on this square canvas. Extend grey paint 12 guide pixels beyond the silhouette into the dark surround. Preserve the dark background elsewhere. All content in the 1536-square input is registered to the entire output square with no crop, zoom, rearrangement or added border. Request 2048-square output. The production atlas remains 2048 square at about 150 px/m; this enlarged part source deliberately supplies finer detail.

Physical mapping:
{physical}
The guide's common sampling density is {g['guide_px_per_m']:.1f} px/m. Native output density equals that value times actual image width / 1536. Fastener heads should be about 4 mm physical diameter. Panel joints about 1 to 2 mm, no exaggerated dark trenches. Blue lines are actual frame, spar or rib positions: paint restrained flush fastening there, not thick blue or black bars. Orange outlines are closed access covers. Yellow areas are walkway zones, not yellow paint. White silhouette edges can be UV cuts through continuous skin, so do not add a dark outline around every island.

Neighbours and seam contract:
{neighbors}
Use clean neutral edge strips. Broad source colour is removed by the compositor and fine detail fades near UV cuts, but panel geometry must still make sense across parts. Prior edge reference strips illustrate paint grain only when the physical neighbour is absent.

Shared style block:
{shared}
"""
    context_text = f"# {name} generation context\n\n{g['description']}\n\nThe aircraft's nose points world -Y, up is +Z and left outboard is +X. FWD, UP and OUT arrows in the guide are fitted independently on each chart from the actual world-position bake. Normal-to-sheet axes are labelled rather than guessed. All size values use metres.\n\n{physical}\n\nGuide density: {g['guide_px_per_m']:.1f} px/m. The actual native density is recorded in generation.json after generation. The atlas density stays about 150 px/m; source oversampling does not increase the final atlas resolution.\n\nStructure comes from art/blender/internals.py via structure.json: fuselage frames start at s=1.6 m with 0.6 m pitch; wing spars follow chord fractions 0.175 and 0.70, with rib locations built from the same interval calculation as internals.py. Access covers come from panels.ACCESS_PANELS. The gun-port cover stays closed. Fin root cover and wing filler are explicit art decisions, not claims about modelled interior structure. The radome has no metal fastener grid.\n\n{neighbors}\n\nReference inputs in tool order:\n" + '\n'.join('- ' + p for p in reference_list) + '\n\nOnly our own layout, material generation and current neutral render inputs are permitted. No game texture is supplied.\n\nShared style block:\n' + shared + '\n'
    (SOURCES / (name + '.context.md')).write_text(portable_text(context_text))
    (SOURCES / (name + '.prompt.txt')).write_text(portable_text(prompt))
    (OUT / (name + '.call.json')).write_text(json.dumps(portable_record({'prompt': (SOURCES / (name + '.prompt.txt')).as_posix(), 'references': reference_list}), indent=2))
    print('PILOT CONTEXT PASS', name, reference_list)


def stitch(base, part, manifest_path):
    manifest = resolve_record(json.loads(Path(manifest_path).read_text()))
    report = {}
    pos = np.load(BAKE / 'geometry_maps.npz')['position'][..., :3]
    for name, group in manifest['groups'].items():
        path = SOURCES / (name + '.png')
        if not path.exists():
            raise ValueError('Missing generated part: ' + str(path))
        image = np.asarray(Image.open(path).convert('RGB'), np.float32) / 255
        source_labels, candidates = source_charts(image, len(group['charts']))
        density_values, registrations = [], []
        mask = np.asarray(Image.open(group['mask'])) > 0
        for chart, (source_id, source_box, _) in zip(sorted(group['charts'], key=lambda c: (c['guide_box'][1], c['guide_box'][0])), candidates):
            x0, y0, x1, y1 = chart['atlas_box']
            yy, xx = np.mgrid[y0:y1, x0:x1]
            u, v = (xx + .5 - x0) / (x1 - x0), (yy + .5 - y0) / (y1 - y0)
            if chart['rotate_ccw']:
                u, v = v, 1 - u
            sy, sx = source_box
            sh, sw = sy.stop - sy.start, sx.stop - sx.start
            target_w, target_h = (y1 - y0, x1 - x0) if chart['rotate_ccw'] else (x1 - x0, y1 - y0)
            density = min(sw / target_w, sh / target_h) * 150
            density_values.append(density)
            if density < 180:
                raise ValueError(f'{name} native source density below 180 px/m: {density}')
            selected = mask[y0:y1, x0:x1]
            silhouette = source_labels[source_box] == source_id
            if chart['rotate_ccw']:
                silhouette = np.rot90(silhouette, -1)
            silhouette = np.asarray(Image.fromarray(silhouette).resize((x1 - x0, y1 - y0), Image.Resampling.NEAREST))
            iou = float((silhouette & selected).sum() / (silhouette | selected).sum())
            if iou < .70:
                raise ValueError(f'{name} chart {chart["component"]} silhouette registration failed: {iou}')
            # Fill source edge mismatches from the closest actual paint texel before sampling.
            # The generated silhouette is guidance, not authority over the aircraft's UV boundary.
            source_inside = source_labels == source_id
            _, index = distance_transform_edt(~source_inside, return_indices=True)
            padded_image = image[index[0], index[1]]
            mapped = sample(padded_image, (sx.start + u * (sw - 1)) / (image.shape[1] - 1),
                            (sy.start + v * (sh - 1)) / (image.shape[0] - 1))
            base[y0:y1, x0:x1][selected] = mapped[selected]
            registrations.append({'chart': chart['component'], 'source_box': [sx.start, sy.start, sx.stop, sy.stop],
                                  'normalized_silhouette_iou': iou, 'native_px_per_m_min_axis': density})
        if name == 'fin_left':
            target = (part == part[mask][0]) & (pos[..., 0] < -.001)
            distance, index = cKDTree(pos[mask][:, 1:]).query(pos[target][:, 1:])
            close = distance < .015
            values = base[target]
            values[close] = base[mask][index[close]]
            base[target] = values
            report['fin_reflection'] = {'target_texels': int(close.sum()), 'max_matching_distance_m': float(distance[close].max())}
        report[name] = {'native_size': [image.shape[1], image.shape[0]], 'native_px_per_m_min_axis': min(density_values),
                        'registration': registrations, 'skin_texels': int(mask.sum()),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (OUT / 'stitch.json').write_text(json.dumps(portable_record(report), indent=2))
    return base


def compose(version):
    import compose_skin
    compose_skin.EXPORT = OUT / version / 'art/export/textures'
    compose_skin.compose(OUT / 'parts.json' if version == 'pilot2' else None)
    shutil.copy2(BAKE / 'composition.json', OUT / (version + '_composition.json'))
    shutil.copy2(BAKE / 'generated_base_assembled.png', OUT / (version + '_assembled.png'))
    shutil.copy2(BAKE / 'surface_fields.npz', OUT / (version + '_surface_fields.npz'))


def service_relief(height, cavity, part, pos, names, manifest_path):
    # Maintained flush skin uses 0.3 of the legacy relief. A 0.34 px seam becomes 0.102 px, about 0.68 mm at 150 px/m.
    # Paint scratches remain visible in colour; they must not read as punched or corroded sheet metal.
    manifest = resolve_record(json.loads(Path(manifest_path).read_text()))
    selected = np.logical_or.reduce([np.asarray(Image.open(g['mask'])) > 0 for g in manifest['groups'].values()])
    selected |= (part == names.index('fin_skin') + 1) & (pos[..., 0] < 0)
    height[selected] *= .3
    cavity[selected] = 1 + (cavity[selected] - 1) * .3
    return height, cavity, {'decision': 'maintained flush skin, paint scuffs are not deep dents',
                            'legacy_height_scale': .3, 'seam_depth_px': .102,
                            'seam_depth_mm_at_150pxm': .68, 'selected_texels': int(selected.sum())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('guides', 'context', 'compose'))
    parser.add_argument('--name', choices=GROUPS)
    parser.add_argument('--version', choices=('round1', 'pilot2'))
    args = parser.parse_args()
    if args.mode == 'guides':
        guides()
    elif args.mode == 'context':
        context(args.name)
    else:
        compose(args.version)
