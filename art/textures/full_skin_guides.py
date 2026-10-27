"""Inventory canonical UV charts, pack dense guides, and record paint ownership.

Run inventory, guides, then context. Existing pilot assets are read-only inputs.
Transfer maps contain flattened atlas indices, never raster component identities.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion, binary_closing, binary_fill_holes, distance_transform_edt, find_objects, label
from scipy.spatial import cKDTree

from panels import ACCESS_PANELS
from pilot2_parts import font, guide_array, layout
from record_paths import portable_record, portable_text, resolve_record
from rasterize import ROOT, OUT as BAKE, SOURCE

OUT = ROOT / '.cache/review/wave2/p9b-round2/full'
SOURCES = SOURCE / 'full'
PILOT = OUT.parent
STYLE = ROOT / 'art/textures/round2_style.txt'
SIZE = 1536
NATIVE_SIZE = 1254
MIN_NATIVE_PXM = 220
TINY_TEXELS = 400


def write_json(path, data):
    path.write_text(json.dumps(portable_record(data), indent=2) + '\n', encoding='utf-8')


def relocate_record(value):
    """Keep native originals intact while resolving repository assets in this checkout."""
    if isinstance(value, dict):
        return {key: relocate_record(item) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate_record(item) for item in value]
    if isinstance(value, str):
        normalized = value.replace('\\', '/')
        for marker in ('/art/textures/', '/.cache/review/'):
            if marker in normalized and normalized[1:3] == ':/':
                return ROOT.as_posix() + marker + normalized.split(marker, 1)[1]
    return value


def load_inputs():
    data = np.load(BAKE / 'geometry_maps.npz')
    names = resolve_record(json.loads((BAKE / 'atlas_triangles.json').read_text()))['parts']
    if not names or len(set(names)) != len(names):
        raise ValueError('Expected unique canonical object names')
    if data['part'].shape != (2048, 2048):
        raise ValueError('Expected the current 2048-square canonical bake')
    return data, names


def generation_exists(group_name):
    return any((folder / (group_name + suffix)).is_file()
               for folder in (SOURCES, SOURCE / 'pilot2')
               for suffix in ('.png', '.generation.json', '.source-stitch.json'))


def input_hashes():
    paths = [BAKE / 'geometry_maps.npz', BAKE / 'atlas_triangles.json',
             PILOT / 'structure.json', PILOT / 'parts.json', STYLE]
    return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def chart_records(mask, pos, normal, part_name):
    labels, _ = label(mask)
    result = []
    for component, box in enumerate(find_objects(labels), 1):
        if box is None:
            continue
        local = labels[box] == component
        yy, xx = np.where(local)
        yy, xx = yy + box[0].start, xx + box[1].start
        p = pos[yy, xx]
        n = normal[yy, xx].mean(0)
        centre = p.mean(0)
        axis = int(np.argmax(abs(n)))
        face = ('out' if n[0] >= 0 else 'in') if axis == 0 else (
            ('aft' if n[1] >= 0 else 'forward') if axis == 1 else
            ('upper' if n[2] >= 0 else 'lower'))
        result.append({'part': part_name, 'texels': len(xx),
                       'atlas_box': [int(xx.min()), int(yy.min()), int(xx.max()+1), int(yy.max()+1)],
                       'centroid_m': centre.tolist(), 'mean_world_normal': n.tolist(),
                       'world_bounds_m': [p.min(0).tolist(), p.max(0).tolist()],
                       'semantic_face': face, '_indices': yy * mask.shape[1] + xx})
    result.sort(key=lambda c: (c['semantic_face'], *c['centroid_m']))
    for index, chart in enumerate(result):
        chart['chart_key'] = f'{part_name}:{chart["semantic_face"]}:{index:03d}'
    return result


def public_chart(chart):
    return {k: v for k, v in chart.items() if not k.startswith('_')}


def mask_from_indices(indices, shape=(2048, 2048)):
    result = np.zeros(shape, bool)
    result.ravel()[indices] = True
    return result


def save_mask(name, indices):
    path = OUT / (name + '.mask.png')
    Image.fromarray(mask_from_indices(indices).astype(np.uint8) * 255).save(path)
    return path.as_posix()


def pack_charts(charts):
    boxes = [(i, (slice(c['atlas_box'][1], c['atlas_box'][3]),
                  slice(c['atlas_box'][0], c['atlas_box'][2]))) for i, c in enumerate(charts, 1)]
    scale, packed = layout(boxes)
    for item in packed:
        chart = charts[item.pop('component') - 1]
        item.update(public_chart(chart))
    return scale, packed


def describe(part_name, face):
    if part_name.startswith('nozzle_petal'):
        return 'Representative variable exhaust petal. Fine longitudinal heat streaks and restrained soot toward the aft lip; preserve overlap edges. Shared around the engine axis.'
    if part_name.startswith('nozzle_seal'):
        return 'Representative narrow exhaust seal between petals. Restrained heat staining and aft soot. No decorative access panels. Shared around the engine axis.'
    descriptions = {
        'nozzle': 'Fixed exhaust shroud between the rear fuselage and movable petal ring. Circumferential attachment seams, restrained aft soot and heat staining.',
        'dorsal_cover': 'Dorsal fuselage cover behind the canopy. Follow frame stations. Keep antenna mounting zones quiet; no antenna artwork is baked into the skin.',
        'canopy_visible': 'Opaque canopy framing and sill only. Follow frame edges and seals. No glass, cockpit instruments or invented access panels.',
        'intake_duct_L': 'Left intake lip and duct. Smooth clean lip, restrained downstream grime, no walkway or fuel filler.',
        'skin_forward_L': 'Forward fuselage around the cockpit. The gun-port access panel stays closed. Radome ahead, intake aft, canopy sill above.',
        'skin_mid_L': 'Mid fuselage between intake and aft engine bay. Follow circumferential frame stations. Closed auxiliary door follows the orange guide.',
        'skin_aft_L': 'Aft engine-bay fuselage ahead of the exhaust. Closed underside vent cover follows the orange guide. Restrained soot only near the nozzle.',
        'wing_skin_L': 'Fixed lower wing skin. Follow actual spars and ribs. Moving leading edge, flap and aileron meet the control boundaries. No upper walkway on the underside.',
        'stabilator_visible': 'All-moving horizontal tail. Hinge and root attachment meet the fin. Sparse flush construction, clean leading edge. No invented internal spar grid.',
        'rudder_visible': 'Separate vertical tail control. Leading hinge meets the fin trailing cut. Fine hinge seam, sparse flush fasteners.',
        'ventral_fin': 'Ventral directional fin below the aft fuselage. Keep the leading edge clean and root attachment restrained.',
        'aileron_L_visible': 'Left outboard trailing control. Leading hinge meets the fixed wing; sparse spanwise flush fastening and closed end caps.',
        'flap_L_visible': 'Left inboard trailing flap. Leading hinge meets the wing. Restrained slot grime and construction along the real hinge.',
        'lef_L_visible': 'Left leading-edge flap. Smooth leading nose, hinge at its aft cut. No walkway, fuel filler or access grid.',
        'speed_brake_L_visible': 'Left fuselage speed brake. Perimeter and hinge are real boundaries; restrained edge grime, no decorative slots.',
        'gear_door_N_L_visible': 'Left nose gear door. Exterior paint and clean inner face; perimeter gasket and hinge attachment. No opening painted into the closed door.',
        'gear_door_main_L_visible': 'Left main gear door. Follow perimeter and hinge, restrained wheel-well grime inside.',
        'pylon_inner_L': 'Left inner stores pylon. Wing attachment above, store attachment below. Sparse service fasteners and clean neutral seam margins.',
        'pylon_inner_plug_L': 'Left inner pylon mounting plug. Small flush attachment faces, restrained mechanical seams.',
    }
    return descriptions.get(part_name, 'Remaining UV charts of the canonical exterior part. Preserve clean paint continuity with the accepted parent source.') + f' World-normal chart family: {face}.'


def inventory():
    if (SOURCE / 'full/source-atlas/native/parts.json').is_file():
        from source_atlas_mapping import restore_inventory
        restore_inventory(BAKE, OUT)
        return
    if (OUT / 'parts.json').is_file() and 'source_atlas_manifest' in resolve_record(json.loads((OUT / 'parts.json').read_text())):
        raise ValueError('This atlas requires its persisted native source pack before inventory can rebuild maps')
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)
    data, names = load_inputs()
    part, pos, normal = data['part'], data['position'][..., :3], data['normal'][..., :3]
    used = part > 0
    owner = np.zeros(part.shape, np.uint16)
    groups, all_charts, rules = {}, {}, []
    pilot = resolve_record(json.loads((PILOT / 'parts.json').read_text()))

    def add_group(name, part_name, charts, reused=None):
        indices = np.concatenate([c['_indices'] for c in charts])
        if np.any(owner.ravel()[indices]):
            raise ValueError(f'Overlapping direct ownership: {name}')
        owner.ravel()[indices] = len(groups) + 1
        if reused:
            scale, packed = reused['guide_scale'], reused['charts']
        else:
            scale, packed = pack_charts(charts)
            by_key = {c['chart_key']: c for c in charts}
            for index, chart in enumerate(packed):
                chart['mask'] = save_mask(name + f'.chart_{index:03d}', by_key[chart['chart_key']]['_indices'])
        density = scale * 150 * NATIVE_SIZE / SIZE
        if density < MIN_NATIVE_PXM:
            raise ValueError(f'{name}: {density:.1f} native px/m, split the group')
        group = {'parts': [part_name], 'part': part_name, 'mask': save_mask(name, indices),
                 'skin_texels': len(indices), 'charts': packed, 'guide_scale': scale,
                 'guide_px_per_m': scale * 150, 'native_px_per_m_at_1254': density,
                 'description': reused['description'] if reused else describe(part_name, charts[0]['semantic_face']),
                 'source_path': ((SOURCE / 'pilot2' if reused else SOURCES) / (name + '.png')).as_posix(),
                 'generation_required': not bool(reused),
                 'references': {'guide': ((SOURCE / 'pilot2' if reused else SOURCES) / (name + '.guide.png')).as_posix(),
                                'style_anchor': (SOURCE / 'pilot2/style_anchor.png').as_posix(),
                                'template': ((SOURCE / 'pilot2' if reused else SOURCES) / (name + '.template.png')).as_posix(),
                                'shared_style': STYLE.as_posix(), 'earlier_neighbor_strips': []}}
        groups[name] = group

    for name, group in pilot['groups'].items():
        mask = np.asarray(Image.open(group['mask'])) > 0
        if np.any(mask & (part != names.index(group['part']) + 1)):
            raise ValueError(f'Pilot mask no longer matches canonical {group["part"]}')
        charts = chart_records(mask, pos, normal, group['part'])
        add_group(name, group['part'], charts, group)

    for part_id, part_name in enumerate(names, 1):
        all_charts[part_name] = chart_records(part == part_id, pos, normal, part_name)
        if part_name.endswith('_R') or (part_name.startswith(('nozzle_petal_', 'nozzle_seal_')) and '_00_' not in part_name):
            continue
        remaining = (part == part_id) & (owner == 0)
        if part_name == 'fin_skin':
            # The other fin face reuses the accepted left face, including its root.
            continue
        charts = chart_records(remaining, pos, normal, part_name)
        significant = [c for c in charts if c['texels'] >= TINY_TEXELS and
                       min(c['atlas_box'][2] - c['atlas_box'][0], c['atlas_box'][3] - c['atlas_box'][1]) >= 3]
        if part_name == 'dorsal_cover':
            significant = [c for c in significant if c['semantic_face'] not in ('in', 'out')]
        if not significant:
            significant = [max(charts, key=lambda c: c['texels'])] if charts else []
        if part_name == 'radome':
            # Thin attachment/end charts inherit accepted composite material.
            continue
        buckets = {}
        for chart in significant:
            # Fuselage and large flying surfaces use actual face normals. Small parts stay together.
            face = chart['semantic_face'] if part_name in ('skin_forward_L', 'skin_mid_L', 'skin_aft_L', 'wing_skin_L', 'stabilator_visible', 'dorsal_cover') else 'all'
            buckets.setdefault(face, []).append(chart)
        if len(buckets) > 1:
            # Narrow end faces share a dense sheet call rather than commissioning another base.
            largest = max(buckets, key=lambda face: sum(c['texels'] for c in buckets[face]))
            for face in list(buckets):
                if face != largest and sum(c['texels'] for c in buckets[face]) < 10000:
                    buckets[largest].extend(buckets.pop(face))

        def split_pack(group_name, selected):
            scale, _ = pack_charts(selected)
            if scale * 150 * NATIVE_SIZE / SIZE >= MIN_NATIVE_PXM:
                add_group(group_name, part_name, selected)
                return
            if len(selected) > 1:
                ordered = sorted(selected, key=lambda c: c['centroid_m'][1])
                middle = len(ordered) // 2
                split_pack(group_name + '_front', ordered[:middle])
                split_pack(group_name + '_rear', ordered[middle:])
                return
            chart = selected[0]
            indices = chart['_indices']
            points = pos.reshape(-1, 3)[indices]
            axis = int(np.argmax(np.ptp(points, axis=0)))
            median = float(np.median(points[:, axis]))
            for suffix, take in [('front', points[:, axis] <= median), ('rear', points[:, axis] > median)]:
                if not take.any() or take.all():
                    raise ValueError(f'Cannot split {group_name}')
                subsets = chart_records(mask_from_indices(indices[take]), pos, normal, part_name)
                split_pack(group_name + '_' + suffix, subsets)

        for face, selected in buckets.items():
            split_pack(part_name.removesuffix('_visible') + '_' + face, selected)

    # Parent paint is explicitly shared onto thin UV end caps, seams and raster slivers.
    def transfer(rule_name, target_indices, source_indices, mode, transform=None, tolerance=None):
        if len(target_indices) == 0:
            return
        query = pos.reshape(-1, 3)[target_indices].copy()
        query_normal = normal.reshape(-1, 3)[target_indices].copy()
        if transform is not None:
            query_normal = transform(query + query_normal) - transform(query)
            query = transform(query)
        source_points = pos.reshape(-1, 3)[source_indices]
        source_normals = normal.reshape(-1, 3)[source_indices]
        _, nearest = cKDTree(np.column_stack((source_points, source_normals * .02))).query(
            np.column_stack((query, query_normal * .02)))
        distance = np.linalg.norm(query-source_points[nearest], axis=1)
        matched = np.ones(len(query), bool) if tolerance is None else distance <= tolerance
        path = OUT / (rule_name + '.transfer.npz')
        source = source_indices[nearest]
        np.savez_compressed(path, target_indices=target_indices, source_indices=source,
                            distance_m=distance.astype(np.float32), matched=matched)
        owners = np.unique(owner.ravel()[source])
        group_names = [list(groups)[int(i)-1] for i in owners if i]
        rules.append({'name': rule_name, 'mode': mode, 'map': path.as_posix(),
                      'target_texels': len(query), 'geometric_matches': int(matched.sum()),
                      'unmatched_surface_texels': int((~matched).sum()),
                      'max_distance_m': float(distance.max()), 'match_tolerance_m': tolerance,
                      'source_groups': group_names,
                      'unmatched_policy': 'nearest parent paint only; no independent geometric-detail claim',
                      'target_mask': save_mask(rule_name, target_indices)})
        owner.ravel()[target_indices] = owner.ravel()[source]

    for part_id, part_name in enumerate(names, 1):
        if part_name.endswith('_R') or (part_name.startswith(('nozzle_petal_', 'nozzle_seal_')) and '_00_' not in part_name):
            continue
        target = np.flatnonzero((part == part_id) & (owner == 0))
        source = np.flatnonzero((part == part_id) & (owner > 0))
        if part_name == 'fin_skin':
            transfer('fin_other_face', target, source, 'world_mirror_x',
                     lambda p: p * np.array([-1, 1, 1]), .045)
        elif len(target):
            transfer(part_name + '_shared_edges', target, source, 'parent_shared_nearest_paint')

    for part_id, part_name in enumerate(names, 1):
        target = np.flatnonzero((part == part_id) & (owner == 0))
        if part_name.endswith('_R'):
            parent = part_name[:-1] + 'L'
            source = np.flatnonzero((part == names.index(parent) + 1) & (owner > 0))
            transfer(part_name + '_mirror', target, source, 'world_mirror_x',
                     lambda p: p * np.array([-1, 1, 1]), .045)
        elif part_name.startswith(('nozzle_petal_', 'nozzle_seal_')) and '_00_' not in part_name:
            family = 'nozzle_petal' if part_name.startswith('nozzle_petal') else 'nozzle_seal'
            parent = family + '_00_visible'
            source = np.flatnonzero((part == names.index(parent) + 1) & (owner > 0))
            # Rotation angle is fitted from actual centroids; the axis centre comes from the full ring.
            family_mask = np.isin(part, [i+1 for i, n in enumerate(names) if n.startswith(family + '_')])
            centre = (pos[family_mask].min(0) + pos[family_mask].max(0)) / 2
            a = pos.reshape(-1, 3)[source].mean(0) - centre
            b = pos.reshape(-1, 3)[target].mean(0) - centre
            angle = float(np.arctan2(a[2], a[0]) - np.arctan2(b[2], b[0]))

            def rotate(points):
                p = points - centre
                x, z = p[:, 0].copy(), p[:, 2].copy()
                p[:, 0] = np.cos(angle)*x - np.sin(angle)*z
                p[:, 2] = np.sin(angle)*x + np.cos(angle)*z
                return p + centre

            transfer(part_name + '_rotation', target, source, 'world_rotation_y', rotate, .045)
            rules[-1].update({'axis': [0, 1, 0], 'axis_point_m': centre.tolist(), 'angle_radians': angle})

    # Neighbours are measured from the world-position bake, independent of atlas proximity.
    centroids = {n: np.mean(pos[part == i+1], axis=0) for i, n in enumerate(names)}
    for name, group in groups.items():
        group['source_parts'] = [group['part']]
        group_index = list(groups).index(name) + 1
        group['parts'] = [names[int(i)-1] for i in np.unique(part[owner == group_index]) if i]
        p = centroids[group['part']]
        group['physical_neighbors'] = sorted((n for n in names if n != group['part'] and not n.startswith('nozzle_')),
                                            key=lambda n: float(np.linalg.norm(centroids[n] - p)))[:4]
        group['neighbor_method'] = 'four closest canonical part centroids; context states actual construction where known'
        base_folder = SOURCES if group['generation_required'] else SOURCE / 'pilot2'
        group['context_path'] = (base_folder / (name + '.context.md')).as_posix()
        group['prompt_path'] = (base_folder / (name + '.prompt.txt')).as_posix()
        stitch_path = SOURCES / (name + '.source-stitch.json')
        if stitch_path.exists():
            group['source_stitch'] = relocate_record(resolve_record(json.loads(stitch_path.read_text())))
            group['source_path'] = (SOURCES / (name + '.stitched.png')).as_posix()
        for stem in (name, name + '_height', name + '_roughness'):
            for suffix in ('.generation.json', '.call.json', '.source-stitch.json', '.failed-attempt.json'):
                record = SOURCES / (stem + suffix)
                if stem == name and not group['generation_required'] and suffix == '.call.json':
                    record = base_folder / (stem + suffix)
                if record.exists():
                    write_json(OUT / record.name, relocate_record(resolve_record(json.loads(record.read_text()))))

    missing = used & (owner == 0)
    unassigned = []
    for i, part_name in enumerate(names, 1):
        for chart in chart_records(missing & (part == i), pos, normal, part_name):
            unassigned.append(public_chart(chart))
    per_part = {}
    for i, part_name in enumerate(names, 1):
        m = part == i
        per_part[part_name] = {'canonical_texels': int(m.sum()), 'assigned_texels': int((m & (owner > 0)).sum()),
                               'groups': [list(groups)[int(v)-1] for v in np.unique(owner[m]) if v],
                               'islands': [public_chart(c) for c in all_charts[part_name]]}
    direct = sum(g['skin_texels'] for g in groups.values())
    coverage = {'schema_version': 1, 'canonical_texels': int(used.sum()), 'direct_texels': direct,
                'transferred_texels': sum(r['target_texels'] for r in rules),
                'assigned_texels': int((used & (owner > 0)).sum()), 'unassigned_texels': int(missing.sum()),
                'unassigned_islands': unassigned, 'parts': per_part,
                'direct_group_masks': {n: g['mask'] for n, g in groups.items()}, 'rules': rules,
                'shared_edge_policy': 'nearest same-part generated parent paint; no old quadrant artwork',
                'paired_uv_policy': 'paired moving parts and wing use canonical left UV; unique fuselage R uses world mirror',
                'owner_map': (OUT / 'ownership.npz').as_posix(),
                'transfer_index_convention': 'row-major flattened 2048x2048 atlas; apply rules in listed order',
                'unmatched_surface_texels': sum(r['unmatched_surface_texels'] for r in rules)}
    manifest = {'schema_version': 1, 'guide_size': SIZE, 'native_size_for_density': NATIVE_SIZE,
                'minimum_native_px_per_m': MIN_NATIVE_PXM, 'shared_style': STYLE.as_posix(),
                'input_sha256': input_hashes(),
                'selection_policy': 'canonical object name, connected UV charts, dominant world normal and world centroid; accepted pilot masks are immutable exceptions',
                'density_policy': 'split a base call below 220 native px/m at 1254 square; atlas density convention is 150 px/m',
                'tiny_chart_policy': 'under 400 texels or under 3 atlas pixels wide inherits same-part paint; dorsal vertical rim strips inherit dorsal paint',
                'bake': (BAKE / 'geometry_maps.npz').as_posix(), 'structure': (PILOT / 'structure.json').as_posix(),
                'groups': groups, 'coverage': (OUT / 'coverage.json').as_posix()}
    np.savez_compressed(OUT / 'ownership.npz', group_index=owner, group_names=np.array(list(groups)))
    write_json(OUT / 'parts.json', manifest)
    write_json(OUT / 'coverage.json', coverage)
    print(json.dumps(portable_record({'new_groups': [n for n, g in groups.items() if g['generation_required']],
                      'reused_groups': [n for n, g in groups.items() if not g['generation_required']],
                      'canonical_texels': coverage['canonical_texels'], 'unassigned_texels': coverage['unassigned_texels'],
                      'unmatched_surface_texels': coverage['unmatched_surface_texels']})))
    if missing.any():
        raise ValueError('Unassigned canonical islands are recorded in coverage.json')


def selected_groups(name):
    manifest = resolve_record(json.loads((OUT / 'parts.json').read_text()))
    groups = manifest['groups']
    if name and name not in groups:
        raise ValueError(f'Unknown group {name}; choose from {list(groups)}')
    return manifest, {name: groups[name]} if name else groups


def guides(name=None):
    manifest, groups = selected_groups(name)
    if 'source_atlas_manifest' in manifest:
        from source_atlas_mapping import current_guides
        current_guides(OUT / 'parts.json', name)
        return
    data, names = load_inputs()
    pos, normal = data['position'][..., :3], data['normal'][..., :3]
    structure = resolve_record(json.loads((PILOT / 'structure.json').read_text()))
    x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
    frames, spars = structure['frames'], structure['spars']
    frame_distance = abs((y + structure['S0'] - frames['s0'] + frames['pitch']/2) % frames['pitch'] - frames['pitch']/2)
    profile = np.asarray(structure['wing_profile'])
    le = np.interp(abs(x), profile[:, 1], profile[:, 0]) - structure['S0']
    chord = np.interp(abs(x), profile[:, 1], profile[:, 3])
    fraction = (y - le) / chord
    spar_distance = np.minimum(abs(fraction-spars['front_f']), abs(fraction-spars['rear_f'])) * chord
    start, end = .62, profile[-1, 1] - .06
    ribs = np.linspace(start, end, int((end-start)/spars['rib_pitch'])+1)
    rib_distance = np.min(abs(abs(x[..., None])-ribs), axis=-1)
    wing_lines = (spar_distance < .009) | ((rib_distance < .009) & (fraction > spars['front_f']) & (fraction < spars['rear_f']))
    for group_name, group in groups.items():
        if not group['generation_required']:
            continue
        selected = np.asarray(Image.open(group['mask'])) > 0
        base = np.full((*selected.shape, 3), (37, 43, 48), np.uint8)
        base[selected] = 128
        clean = base.copy()
        part_name = group['part']
        if part_name.startswith('skin_') or part_name == 'dorsal_cover':
            base[selected & (frame_distance < .009)] = (45, 157, 223)
        if part_name == 'wing_skin_L':
            base[selected & wing_lines] = (45, 157, 223)
            base[selected & (normal[..., 2] > .3) & (abs(x) < 1.05) & (fraction > .28) & (fraction < .62)] = (171, 155, 83)
            fuel = np.sqrt((abs(x)-2.25)**2 + (fraction-.43)**2 * chord**2)
            base[selected & (normal[..., 2] > .3) & (abs(fuel-.055) < .009)] = (242, 152, 51)
        for _, allowed, cy, cz, width, height in ACCESS_PANELS:
            if part_name in allowed:
                edge = abs(np.maximum(abs(y-cy)-width/2, abs(z-cz)-height/2))
                base[selected & (edge < .009)] = (242, 152, 51)
        controls = {'wing_skin_L': ['aileron_L_visible', 'flap_L_visible', 'lef_L_visible'],
                    'aileron_L_visible': ['wing_skin_L'], 'flap_L_visible': ['wing_skin_L'],
                    'lef_L_visible': ['wing_skin_L'], 'rudder_visible': ['fin_skin'],
                    'stabilator_visible': ['fin_skin']}
        neighbors = controls.get(part_name, [])
        if neighbors:
            adjacent = np.isin(data['part'], [names.index(n)+1 for n in neighbors])
            distance, _ = cKDTree(pos[adjacent]).query(pos[selected])
            edge = np.zeros(selected.shape, bool)
            edge[selected] = distance < .035
            base[edge] = (220, 115, 185)
        border = selected & ~binary_erosion(selected)
        base[border] = (235, 240, 240)
        guide = Image.new('RGB', (SIZE, SIZE), '#252b30')
        template = guide.copy()
        draw = ImageDraw.Draw(guide)
        draw.text((40, 18), group_name.upper(), font=font(32), fill='white')
        draw.text((40, 65), 'BLUE structure | ORANGE access/fuel | YELLOW walkway | WHITE UV cuts', font=font(22), fill='#bac7d0')
        draw.text((40, 94), 'PINK measured control/root boundary within 35 mm', font=font(19), fill='#dc73b9')
        for chart in group['charts']:
            gx, gy, ex, ey = chart['guide_box']
            x0, y0, x1, y1 = chart['atlas_box']
            chart_mask = np.asarray(Image.open(chart['mask'])) > 0
            local = chart_mask[y0:y1, x0:x1]
            for image, values in ((guide, base), (template, clean)):
                crop = values[y0:y1, x0:x1].copy()
                crop[~local] = (37, 43, 48)
                image.paste(guide_array(crop, [0, 0, x1-x0, y1-y0], chart['rotate_ccw'], (ex-gx, ey-gy), True), (gx, gy))
            yy, xx = np.where(local)
            p = pos[y0:y1, x0:x1][local]
            uv = np.column_stack((xx-xx.mean(), yy-yy.mean()))
            projection = np.linalg.lstsq(p-p.mean(0), uv, rcond=None)[0]
            centre = np.array([(gx+ex)/2, (gy+ey)/2])
            axes = [('FWD', [0, -1, 0], '#65d6f5'), ('UP', [0, 0, 1], '#94eaaa'),
                    ('OUT', [1 if p[:, 0].mean() >= 0 else -1, 0, 0], '#e2a2ec')]
            for index, (text, axis, colour) in enumerate(axes):
                vector = np.asarray(axis) @ projection
                if chart['rotate_ccw']:
                    vector = np.array([vector[1], -vector[0]])
                if np.linalg.norm(vector) < 22.5:
                    draw.text((gx, ey+5+index*18), text+' normal to sheet', font=font(16), fill=colour)
                    continue
                vector *= 55 / np.linalg.norm(vector)
                a = centre + [0, (index-1)*24]
                b = a + vector
                draw.line([tuple(a), tuple(b)], fill=colour, width=3)
                side = np.array([-vector[1], vector[0]])*.10
                back = b-vector*.18
                draw.polygon([tuple(b), tuple(back+side), tuple(back-side)], fill=colour)
                draw.text(tuple(b+3), text, font=font(18), fill=colour)
            dimensions = np.ptp(p, axis=0)
            draw.text((gx, max(106, gy-26)), 'XYZ '+', '.join(f'{v:.2f}' for v in dimensions)+' m', font=font(20), fill='white')
        draw.text((40, SIZE-48), f'{group["guide_px_per_m"]:.0f} guide px/m | {group["native_px_per_m_at_1254"]:.0f} native px/m at 1254 square', font=font(25), fill='white')
        if generation_exists(group_name):
            current = OUT / 'current-guides'
            current.mkdir(parents=True, exist_ok=True)
            guide.save(current / (group_name + '.guide.png'))
            template.save(current / (group_name + '.template.png'))
        else:
            guide.save(group['references']['guide'])
            template.save(group['references']['template'])
        print('GUIDE', group_name)


def context(name=None):
    manifest, groups = selected_groups(name)
    shared = STYLE.read_text(encoding='utf-8').strip()
    for group_name, group in groups.items():
        if generation_exists(group_name):
            print('PRESERVED GENERATION CONTEXT', group_name)
            continue
        if not group['generation_required']:
            print('REUSED CONTEXT', group_name)
            continue
        physical = '\n'.join(f'- Atlas {c["atlas_box"]}, guide {c["guide_box"]}, CCW rotation {c["rotate_ccw"]}. World bounds in metres {c["world_bounds_m"]}.' for c in group['charts'])
        neighbors = ', '.join(group['physical_neighbors'])
        references = [group['references'][key] for key in ('guide', 'style_anchor', 'template')]
        prior = [(n, g) for n, g in manifest['groups'].items() if n != group_name
                 and Path(g['source_path']).is_file()
                 and (g['part'] == group['part'] or g['part'] in group['physical_neighbors'])]
        strips = []
        for prior_name, prior_group in prior[:2]:
            rgb = np.asarray(Image.open(prior_group['source_path']).convert('RGB'))
            inside = binary_fill_holes(binary_closing(rgb.mean(axis=2) > 82, iterations=3))
            distance = distance_transform_edt(inside)
            edge = rgb[(distance >= 3) & (distance < 15)]
            if not len(edge):
                raise ValueError('No painted edge band: '+prior_name)
            indices = np.linspace(0, len(edge)-1, 1024*64).astype(int)
            strip = SOURCES / (group_name+'.neighbor_'+prior_name+'.png')
            Image.fromarray(edge[indices].reshape(64, 1024, 3)).save(strip)
            strips.append(strip.as_posix())
        references.extend(strips)
        group['references']['earlier_neighbor_strips'] = strips
        continuity = ('Additional images are native painted edge samples from '+', '.join(n for n, _ in prior[:2])+
                      '. Use these for paint-grain and joint treatment. Structural lines continue through the '
                      'same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.') if strips else 'No generated physical-neighbour edge image exists yet; retain uniform neutral margins.'
        prompt = f'''Use case: flat UV diffuse albedo source for one aircraft skin group.
Target: {group_name}, canonical object {group['part']} on the Icarus II modernised F-104 interceptor.
{group['description']}

Image 1 is the labelled UV guide. Image 2 is the accepted material style anchor. Image 3 is the exact clean template.
{continuity}
Paint every supplied island at the same position, size and orientation. Register the full square canvas without cropping, zooming or rearranging. Extend paint 12 guide pixels beyond islands; preserve dark background elsewhere. Remove all arrows, labels, coloured guide ink and white boundaries. No aircraft illustration or perspective view. No baked text or markings. The compositor adds scheme colours and decals.

Guide canvas: 1536 square. Density: {group['guide_px_per_m']:.1f} px/m. At 1254 square the native density is {group['native_px_per_m_at_1254']:.1f} px/m. Fastener heads are about 4 mm and joints 1 to 2 mm. Preserve sparse true-scale detail.
{physical}

FWD is world -Y, UP is +Z, OUT points away from centreline. Blue ink marks actual fuselage frames or wing spars/ribs from structure.json. Orange marks closed access panels from panels.ACCESS_PANELS or the explicit fuel-filler art decision. Yellow marks upper root walkway only. On new guides pink marks measured control/root adjacency within 35 mm; accepted pilot guides retain their original legend. White outlines include UV cuts. Never outline every UV island in dark paint.
Frames use 0.6 m pitch. Wing spars use chord fractions 0.175 and 0.70. Do not invent internal spar grids on the fin or tail. Antenna mounting zones belong on the dorsal cover; no antenna illustration. Fuel filler belongs only on the upper fixed wing. Foot wear belongs only near the upper wing root. Soot belongs near the aft exhaust and downstream intake recess, not across all paint.
Nearby canonical parts by world centroid: {neighbors}. Continue neutral paint across adjacent sheets. Keep hinge and separate control edges distinct. Mirror partners and nozzle repetitions reuse their canonical source through coverage.json, rather than independent generation. Thin edge charts receive nearest parent paint and carry no independent structural detail.

Shared style block:
{shared}
'''
        note = f'''# {group_name}

{group['description']}

Generation required: {group['generation_required']}. Source: {group['source_path']}.
Guide density {group['guide_px_per_m']:.1f} px/m; native density at 1254 square {group['native_px_per_m_at_1254']:.1f} px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

{physical}

Closest part centroids: {neighbors}. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in { (OUT / 'coverage.json').as_posix() }.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
{continuity}

References in image order:
''' + '\n'.join('- '+p for p in references) + '\n\nShared style block:\n'+shared+'\n'
        Path(group['prompt_path']).write_text(portable_text(prompt), encoding='utf-8')
        Path(group['context_path']).write_text(portable_text(note), encoding='utf-8')
        call = {'name': group_name, 'generation_required': group['generation_required'],
                'prompt': group['prompt_path'], 'references': references, 'source_path': group['source_path']}
        write_json(OUT / (group_name+'.call.json'), call)
        write_json(SOURCES / (group_name+'.call.json'), call)
        print('CONTEXT', group_name)
    write_json(OUT / 'parts.json', manifest)


def check():
    manifest, groups = selected_groups(None)
    if 'source_atlas_manifest' in manifest:
        from source_atlas_mapping import check_inventory
        check_inventory(OUT / 'parts.json')
        return
    if manifest['input_sha256'] != input_hashes():
        raise ValueError('Inputs changed after inventory; regenerate before using guides')
    data, names = load_inputs()
    coverage = resolve_record(json.loads((OUT / 'coverage.json').read_text()))
    direct = np.zeros(data['part'].shape, np.uint16)
    shared = STYLE.read_text(encoding='utf-8').strip()
    for name, group in groups.items():
        mask_image = Image.open(group['mask'])
        if mask_image.mode != 'L' or mask_image.size != (2048, 2048):
            raise ValueError(f'{name}: mask must be 2048 grayscale')
        mask = np.asarray(mask_image) > 0
        assert int(mask.sum()) == group['skin_texels'], name
        assert not direct[mask].any(), name
        direct[mask] = list(groups).index(name)+1
        assert group['native_px_per_m_at_1254'] >= MIN_NATIVE_PXM, name
        for key in ('guide', 'template', 'style_anchor'):
            path = Path(group['references'][key])
            assert path.is_file(), path
            if key in ('guide', 'template'):
                assert Image.open(path).size == (SIZE, SIZE), path
        for chart in group['charts']:
            gx, gy, ex, ey = chart['guide_box']
            assert 0 <= gx < ex <= SIZE and 0 <= gy < ey <= SIZE, name
        if group['generation_required']:
            chart_union = np.zeros(mask.shape, bool)
            for chart in group['charts']:
                chart_mask = np.asarray(Image.open(chart['mask'])) > 0
                assert not (chart_union & chart_mask).any(), name
                assert int(chart_mask.sum()) == chart['texels'], name
                chart_union |= chart_mask
            assert np.array_equal(chart_union, mask), name
        assert Path(group['prompt_path']).read_text(encoding='utf-8').endswith(shared+'\n'), name
        assert Path(group['context_path']).is_file(), name
        if not group['generation_required']:
            assert Path(group['source_path']).is_file(), name
    direct_count = int((direct > 0).sum())
    for rule in coverage['rules']:
        transfer = np.load(rule['map'])
        target, source = transfer['target_indices'], transfer['source_indices']
        assert len(target) == rule['target_texels'], rule['name']
        assert not direct.ravel()[target].any(), rule['name']
        assert direct.ravel()[source].all(), rule['name']
        assert int((~transfer['matched']).sum()) == rule['unmatched_surface_texels'], rule['name']
        direct.ravel()[target] = direct.ravel()[source]
    assert np.array_equal(direct > 0, data['part'] > 0)
    assert np.array_equal(direct, np.load(coverage['owner_map'])['group_index'])
    assert set(coverage['parts']) == set(names)
    assert coverage['unassigned_texels'] == 0 and coverage['unassigned_islands'] == []
    assert coverage['direct_texels'] == direct_count
    assert coverage['direct_texels'] + coverage['transferred_texels'] == coverage['canonical_texels']
    report = {'groups': len(groups), 'new_base_groups': sum(g['generation_required'] for g in groups.values()),
              'canonical_parts': len(names), 'canonical_texels': coverage['canonical_texels'],
              'minimum_native_px_per_m': min(g['native_px_per_m_at_1254'] for g in groups.values()),
              'direct_texels': direct_count, 'transferred_texels': coverage['transferred_texels'],
              'unmatched_surface_texels': coverage['unmatched_surface_texels'], 'unassigned_texels': 0}
    write_json(OUT / 'checks.json', report)
    print('CHECK PASS', json.dumps(portable_record(report)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inventory', 'guides', 'context', 'check', 'adapt', 'restore'))
    parser.add_argument('--name', help='Restrict guides/context to one manifest group')
    parser.add_argument('--source-snapshot', type=Path)
    parser.add_argument('--bake-sha256', help='Parent-verified completed geometry_maps.npz hash')
    args = parser.parse_args()
    if args.command == 'restore':
        from source_atlas_mapping import restore_inventory
        restore_inventory(BAKE, OUT)
    elif args.command == 'adapt':
        if not args.source_snapshot or not args.bake_sha256:
            parser.error('adapt requires --source-snapshot and --bake-sha256')
        from source_atlas_mapping import adapt_inventory
        adapt_inventory(args.source_snapshot, BAKE, OUT, args.bake_sha256)
    elif args.command == 'inventory':
        if args.name:
            parser.error('inventory always rebuilds the complete ownership partition')
        inventory()
    elif args.command == 'guides':
        guides(args.name)
    elif args.command == 'context':
        context(args.name)
    else:
        check()


if __name__ == '__main__':
    from texture_sources import require_texture_sources
    require_texture_sources()
    main()
