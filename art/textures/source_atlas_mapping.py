"""Reuse registered generated paint after UV repacking, with explicit donor coverage.

Native registration remains on the immutable generation atlas. Current ownership
is measured in world space. A nearest-parent transfer promises material coverage,
not newly authored mechanical detail. No generated source file is rewritten.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

from rasterize import ROOT, SOURCE, PAINT_SIZE as ATLAS_SIZE

FIELDS = ('base', 'height', 'roughness', 'height_valid', 'roughness_valid', 'used')
POSITION_TOLERANCE_M = .015
NORMAL_COSINE = .95


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def nearest_parent(target_positions, target_normals, source_positions, source_normals):
    if not len(source_positions):
        raise ValueError('Nearest-parent transfer has no assigned donor texels')
    _, nearest = cKDTree(np.column_stack((source_positions, source_normals * .02))).query(
        np.column_stack((target_positions, target_normals * .02)))
    distance = np.linalg.norm(target_positions - source_positions[nearest], axis=1)
    cosine = np.einsum('ij,ij->i', target_normals, source_normals[nearest])
    return nearest, distance, cosine


def donor_part(name, source_names):
    """New small doors inherit their corresponding accepted parent door paint."""
    if name in source_names:
        return name, False
    replacements = {
        'gear_door_N2_L_visible': ('gear_door_N_L_visible', False),
        'gear_door_N2_R_visible': ('gear_door_N_L_visible', True),
        'gear_door_flap_L_visible': ('gear_door_main_L_visible', False),
        'gear_door_flap_R_visible': ('gear_door_main_L_visible', True),
    }
    return replacements.get(name)


def infer_donor(target_positions, target_normals, source_names, source_part, source_positions, source_normals):
    """One physical parent minimizes RMS position/normal distance over the whole part.

    This selects material paint only. New geometry never inherits a matched-detail
    claim. Equal scores choose the lexically first source name, independent of IDs.
    """
    if not len(target_positions):
        raise ValueError('Cannot choose a physical parent without current skin texels')
    scores = {}
    for name in sorted(source_names):
        indices = np.flatnonzero(source_part == source_names.index(name) + 1)
        if not indices.size:
            continue
        positions, normals = source_positions[indices], source_normals[indices]
        nearest, distance, _ = nearest_parent(target_positions, target_normals, positions, normals)
        normal_distance = np.linalg.norm(target_normals - normals[nearest], axis=1) * .02
        scores[name] = float(np.sqrt(np.mean(distance ** 2 + normal_distance ** 2)))
    if not scores:
        raise ValueError('Cannot choose a physical parent without current and source skin texels')
    donor = min(scores, key=lambda name: (scores[name], name))
    return donor, {'policy': 'minimum_whole_part_rms_world_position_and_normal',
                   'normal_weight_m': .02, 'score_m': scores[donor], 'candidate_scores_m': scores,
                   'tie_break': 'lexical source part name', 'matched_detail_claim': False}


def normalized_source_manifest(snapshot, output):
    """Resolve frozen masks and transfers without changing their preserved bytes."""
    full, pilot, bake = (snapshot / name for name in ('old-full', 'old-pilot', 'old-bake'))

    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        if isinstance(value, str):
            path = value.replace('\\', '/')
            for marker, folder in (('/.cache/review/wave2/p9b-round2/full/', full),
                                   ('/.cache/review/wave2/p9b-round2/', pilot),
                                   ('/.cache/review/wave2/p9b/02/', bake)):
                if marker in path:
                    return (folder / path.split(marker, 1)[1]).as_posix()
            if '/art/textures/' in path:
                return (ROOT / 'art/textures' / path.split('/art/textures/', 1)[1]).as_posix()
        return value

    manifest = relocate(read_json(full / 'parts.json'))
    # Hash-map keys are paths too; recursive value relocation does not change keys.
    generation_inputs = {relocate(path): digest
                         for path, digest in read_json(full / 'parts.json')['input_sha256'].items()}
    for path, digest in generation_inputs.items():
        if sha256(path) != digest:
            raise ValueError('Preserved generation-atlas input hash differs: ' + path)
    coverage = relocate(read_json(full / 'coverage.json'))
    output.mkdir(parents=True, exist_ok=True)
    copied = {}
    persisted_generation_inputs = {}
    for value, digest in generation_inputs.items():
        path = Path(value)
        if path.is_relative_to(snapshot):
            destination = output / 'generation-inputs' / path.relative_to(snapshot)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            persisted_generation_inputs[destination.as_posix()] = digest
        else:
            persisted_generation_inputs[value] = digest

    def persist(path):
        source = Path(path)
        target = output / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        copied[target.as_posix()] = sha256(target)
        return target.as_posix()

    for group in manifest['groups'].values():
        group['mask'] = persist(group['mask'])
        for chart in group['charts']:
            if 'mask' in chart:
                chart['mask'] = persist(chart['mask'])
    for rule in coverage['rules']:
        rule['map'] = persist(rule['map'])
        rule['target_mask'] = persist(rule['target_mask'])
    coverage['owner_map'] = persist(coverage['owner_map'])
    coverage['direct_group_masks'] = {name: group['mask'] for name, group in manifest['groups'].items()}
    manifest['structure'] = persist(manifest['structure'])
    manifest['coverage'] = (output / 'coverage.json').as_posix()
    manifest['generation_input_sha256'] = persisted_generation_inputs
    manifest['source_generation_bake_sha256'] = generation_inputs[relocate(read_json(full / 'parts.json')['bake'])]
    manifest.pop('bake', None)
    # Native registration consumes masks and original generated files, not the old Blender bake.
    manifest['input_sha256'] = copied
    def source_assets(value):
        if isinstance(value, dict):
            for item in value.values():
                source_assets(item)
        elif isinstance(value, list):
            for item in value:
                source_assets(item)
        elif isinstance(value, str) and '/art/textures/' in value and Path(value).is_file():
            manifest['input_sha256'][value] = sha256(value)
    source_assets(manifest['groups'])
    for name in manifest['groups']:
        for kind in ('height', 'roughness'):
            for suffix in ('.png', '.generation.json', '.failed-attempt.json', '.call.json'):
                asset = SOURCE / 'full' / (name + '_' + kind + suffix)
                if asset.is_file():
                    manifest['input_sha256'][asset.as_posix()] = sha256(asset)
    for path in sorted(full.glob('*.json')):
        if path.name.endswith(('.call.json', '.generation.json', '.failed-attempt.json', '.source-stitch.json')):
            target = output / path.name
            record = relocate(read_json(path))
            if record.get('original') and record.get('output'):
                native = Path(record['output'])
                if native.is_file() and sha256(native) == sha256(record['original']):
                    record['original_external'] = record['original']
                    record['original'] = native.as_posix()
            write_json(target, record)
            manifest['input_sha256'][target.as_posix()] = sha256(target)
    pilot_generation = read_json(SOURCE / 'pilot2/generation.json')
    for group in manifest['groups'].values():
        stitch = group.get('source_stitch')
        if stitch and Path(stitch['source']).name == 'style_anchor.png':
            stitch['source'] = persist(stitch['source'])
    shared_generation = copy.deepcopy(pilot_generation)
    shared_generation['original_external_directory'] = shared_generation['original_directory']
    shared_generation['original_directory'] = (SOURCE / 'pilot2').as_posix()
    shared_generation['outputs'] = {name: name + '.png' for name in pilot_generation['outputs']}
    write_json(output / 'generation.json', shared_generation)
    manifest['input_sha256'][(output / 'generation.json').as_posix()] = sha256(output / 'generation.json')
    for name, group in manifest['groups'].items():
        if group.get('source_stitch'):
            stitch_path = output / (name + '.source-stitch.json')
            write_json(stitch_path, group['source_stitch'])
            manifest['input_sha256'][stitch_path.as_posix()] = sha256(stitch_path)
        target = output / (name + '.generation.json')
        if not target.exists() and name in pilot_generation.get('outputs', {}):
            native = SOURCE / 'pilot2' / (name + '.png')
            original = Path(pilot_generation['original_directory']) / pilot_generation['outputs'][name]
            if sha256(native) != sha256(original):
                raise ValueError('Pilot source differs from its unmodified original: ' + name)
            write_json(target, {'tool': pilot_generation['tool'], 'original': native.as_posix(),
                                 'original_external': original.as_posix(), 'output': native.as_posix(),
                                 'sha256': sha256(native),
                                 'native_size': list(Image.open(native).size)})
        if target.is_file():
            manifest['input_sha256'][target.as_posix()] = sha256(target)
    write_json(output / 'coverage.json', coverage)
    manifest['input_sha256'][(output / 'coverage.json').as_posix()] = sha256(output / 'coverage.json')
    write_json(output / 'parts.json', manifest)
    return manifest, coverage


def save_mask(path, indices, shape):
    mask = np.zeros(shape, np.uint8)
    mask.ravel()[indices] = 255
    Image.fromarray(mask).save(path)
    return path.as_posix()


def adapt_inventory(snapshot, bake, output, expected_bake_sha256):
    snapshot, bake, output = (Path(path).resolve() for path in (snapshot, bake, output))
    current_path = bake / 'geometry_maps.npz'
    if sha256(current_path) != expected_bake_sha256:
        raise ValueError('Current geometry bake does not match the verified completed hash')
    normalized_source_manifest(snapshot, SOURCE / 'full/source-atlas/native')
    return rebuild_inventory(bake, output)


def rebuild_inventory(bake, output):
    """Rebuild current maps from the frozen native pack after a completed prepare."""
    bake, output = Path(bake).resolve(), Path(output).resolve()
    current_path = bake / 'geometry_maps.npz'
    expected_bake_sha256 = sha256(current_path)
    expected_atlas_sha256 = sha256(bake / 'atlas_triangles.json')
    persistent = SOURCE / 'full/source-atlas'
    source_manifest = read_json(persistent / 'native/parts.json')
    for path, digest in {**source_manifest['input_sha256'],
                         **source_manifest['generation_input_sha256']}.items():
        if sha256(path) != digest:
            raise ValueError('Frozen native source pack changed: ' + path)
    source_bakes = [Path(path) for path, digest in source_manifest['generation_input_sha256'].items()
                    if Path(path).name == 'geometry_maps.npz' and
                    digest == source_manifest['source_generation_bake_sha256']]
    if len(source_bakes) != 1:
        raise ValueError('Expected one frozen generation bake in the native source pack')
    source_path = source_bakes[0]
    old_names = read_json(source_path.with_name('atlas_triangles.json'))['parts']
    if not old_names or len(set(old_names)) != len(old_names):
        raise ValueError('Frozen source canonical part names must be unique')
    names = read_json(bake / 'atlas_triangles.json')['parts']
    if not names or len(set(names)) != len(names):
        raise ValueError('Current canonical part names must be unique')
    with np.load(source_path, allow_pickle=False) as data:
        old_part = data['part']
        old_pos = data['position'][..., :3].reshape(-1, 3)
        old_normal = data['normal'][..., :3].reshape(-1, 3)
    with np.load(current_path, allow_pickle=False) as data:
        part = data['part']
        pos = data['position'][..., :3].reshape(-1, 3)
        normal = data['normal'][..., :3].reshape(-1, 3)
    if part.shape != (ATLAS_SIZE, ATLAS_SIZE) or old_part.shape != part.shape:
        raise ValueError('Source and current atlases must both be 2048 square')
    source_coverage = read_json(persistent / 'native/coverage.json')
    output.mkdir(parents=True, exist_ok=True)
    maps = persistent / 'current'
    maps.mkdir(parents=True, exist_ok=True)
    with np.load(source_coverage['owner_map'], allow_pickle=False) as data:
        old_owner = data['group_index']
    if not np.array_equal(old_owner > 0, old_part > 0):
        raise ValueError('Preserved source atlas ownership is incomplete')
    owner = np.zeros(part.shape, np.uint16)
    reused = np.zeros(part.shape, bool)
    rules, per_part = [], {}
    for part_id, name in enumerate(names, 1):
        target = np.flatnonzero(part == part_id)
        if not target.size:
            raise ValueError('Canonical part has no current skin texels: ' + name)
        named_donor = donor_part(name, old_names)
        if named_donor is None:
            donor, decision = infer_donor(pos[target], normal[target], old_names, old_part,
                                          old_pos, old_normal)
            mirror = False
        else:
            donor, mirror = named_donor
            decision = {'policy': 'same_physical_part' if name == donor else 'named_gear_door_parent',
                        'matched_detail_claim': name == donor and not name.startswith(('gear_door_', 'speed_brake_'))}
        source = np.flatnonzero(old_part == old_names.index(donor) + 1)
        query, query_normal = pos[target].copy(), normal[target].copy()
        if mirror:
            query[:, 0] *= -1
            query_normal[:, 0] *= -1
        nearest, distance, cosine = nearest_parent(query, query_normal, old_pos[source], old_normal[source])
        source = source[nearest]
        native = (distance <= POSITION_TOLERANCE_M) & (cosine >= NORMAL_COSINE)
        changed = name.startswith(('gear_door_', 'speed_brake_'))
        if changed or name != donor:
            native[:] = False
        reused.ravel()[target] = native
        owner.ravel()[target] = old_owner.ravel()[source]
        path = maps / (name + '.source-transfer.npz')
        np.savez_compressed(path, target_indices=target, source_indices=source,
                            distance_m=distance.astype(np.float32), normal_cosine=cosine.astype(np.float32),
                            matched=native)
        rule = {'name': name + '_source_atlas', 'mode': 'registered_source_atlas_nearest_parent',
                'source_space': 'generation_atlas', 'map': path.as_posix(), 'target_part': name,
                'source_part': donor, 'reflect_world_x': mirror,
                'donor_decision': decision,
                'target_texels': int(target.size), 'geometric_matches': int(native.sum()),
                'native_reuse_texels': int(native.sum()), 'unmatched_surface_texels': int((~native).sum()),
                'max_distance_m': float(distance.max()), 'p95_distance_m': float(np.quantile(distance, .95)),
                'match_tolerance_m': POSITION_TOLERANCE_M, 'normal_cosine_min': NORMAL_COSINE,
                'source_groups': [list(source_manifest['groups'])[int(i)-1]
                                  for i in np.unique(old_owner.ravel()[source])],
                'unmatched_policy': 'nearest accepted parent paint; no new mechanical-detail claim',
                'target_mask': save_mask(maps / (name + '.source-transfer.mask.png'), target, part.shape)}
        rules.append(rule)
        per_part[name] = {'canonical_texels': int(target.size), 'assigned_texels': int(target.size),
                          'native_reuse_texels': int(native.sum()),
                          'parent_paint_texels': int((~native).sum()), 'groups': rule['source_groups']}
    groups = copy.deepcopy(source_manifest['groups'])
    for index, (name, group) in enumerate(groups.items(), 1):
        indices = np.flatnonzero(owner == index)
        group['generation_atlas_mask'] = group['mask']
        group['generation_atlas_charts'] = group.pop('charts')
        group['mask'] = save_mask(maps / (name + '.mask.png'), indices, part.shape)
        group['skin_texels'] = int(indices.size)
        group['parts'] = [n for i, n in enumerate(names, 1) if np.any((part == i) & (owner == index))]
        group['generation_required'] = False
    used = part > 0
    if not np.array_equal(owner > 0, used):
        raise ValueError('Current inventory contains unassigned canonical texels')
    np.savez_compressed(maps / 'ownership.npz', group_index=owner, group_names=np.array(list(groups)))
    hashes = {path.as_posix(): sha256(path) for path in
              (current_path, bake / 'atlas_triangles.json', persistent / 'native/parts.json',
               persistent / 'native/coverage.json', Path(source_coverage['owner_map']))}
    hashes.update({rule['map']: sha256(rule['map']) for rule in rules})
    hashes.update({path.as_posix(): sha256(path) for path in maps.glob('*.mask.png')})
    hashes[(maps / 'ownership.npz').as_posix()] = sha256(maps / 'ownership.npz')
    coverage = {'schema_version': 2, 'canonical_texels': int(used.sum()),
                'assigned_texels': int(used.sum()), 'unassigned_texels': 0, 'unassigned_islands': [],
                'direct_texels': 0, 'transferred_texels': int(used.sum()),
                'native_reuse_texels': int(reused.sum()),
                'unmatched_surface_texels': int((used & ~reused).sum()),
                'parts': per_part, 'rules': rules, 'owner_map': (maps / 'ownership.npz').as_posix(),
                'inferred_parent_parts': [rule['target_part'] for rule in rules
                                          if rule['donor_decision']['policy'].startswith('minimum_')],
                'transfer_index_convention': 'row-major atlas indices; source indices address immutable generation atlas; target indices address current atlas; apply rules in listed order',
                'field_contract': list(FIELDS)}
    manifest = {'schema_version': 2, 'guide_size': source_manifest['guide_size'],
                'minimum_native_px_per_m': 180, 'shared_style': source_manifest['shared_style'],
                'bake': current_path.as_posix(), 'structure': source_manifest['structure'],
                'source_atlas_manifest': (persistent / 'native/parts.json').as_posix(),
                'input_sha256': hashes, 'groups': groups,
                'coverage': (output / 'coverage.json').as_posix(),
                'selection_policy': 'world positions and normals within named physical parts; chart indices never establish identity',
                'registration_contract': 'groups[].generation_atlas_charts belong to the source atlas; current masks contain mapped ownership and are not native chart registration inputs',
                'limitations': ['New and replaced doors and speed brakes use nearest accepted parent paint, not new generated structural detail.',
                                'Brake wells and actuators on jet_mechanical are outside the skin atlas and retain their mechanical material.',
                                'Native IoU and density gates run on preserved generation-atlas charts; world reuse is measured separately.']}
    if coverage['inferred_parent_parts']:
        manifest['limitations'].append('Inferred parent material only, no matched mechanical detail: ' +
                                        ', '.join(coverage['inferred_parent_parts']))
    # Verify the prepare output remained unchanged throughout mapping.
    if (sha256(current_path) != expected_bake_sha256 or
        sha256(bake / 'atlas_triangles.json') != expected_atlas_sha256):
        raise ValueError('Current bake changed while mapping')
    write_json(maps / 'coverage.json', coverage)
    hashes[(maps / 'coverage.json').as_posix()] = sha256(maps / 'coverage.json')
    write_json(output / 'coverage.json', coverage)
    write_json(output / 'parts.json', {**manifest, 'input_sha256': {
        **hashes, (output / 'coverage.json').as_posix(): sha256(output / 'coverage.json')}})
    write_json(maps / 'parts.json', {**manifest, 'coverage': (maps / 'coverage.json').as_posix()})
    write_json(persistent / 'provenance.json', {
        'source_generation_inputs': source_manifest['generation_input_sha256'],
        'current_geometry_sha256': expected_bake_sha256,
        'current_atlas_triangles_sha256': sha256(bake / 'atlas_triangles.json'),
        'native_registration_gates': {'normalized_silhouette_iou_min': .70, 'native_px_per_m_min': 180},
        'native_companion_alignment': 'unchanged companion_maps.py gates before remapping',
        'mapping_policy': {'position_tolerance_m': POSITION_TOLERANCE_M, 'normal_cosine_min': NORMAL_COSINE,
                           'replaced_parts_always_parent_paint': ['gear_door_*', 'speed_brake_*']},
        'field_contract': list(FIELDS)})
    (persistent / 'README.md').write_text('''# Reuse the registered generation atlas

The 33 accepted source group names and native chart layouts stay in `native/parts.json`.
Its masks, ordered transfers, provenance records and input hashes are persisted here.
Original generated PNGs, guides, templates, contexts and prompts remain in their source folders.
Native registration still requires silhouette IoU >= 0.70 and density >= 180 px/m.
Companion acceptance runs before remapping with the existing native alignment gates.

`current/parts.json` assigns the current atlas through maps in `current/`.
Each rule reads immutable generation-atlas indices and writes current-atlas indices.
Apply rules in listed order to base RGB, height, roughness, both validity masks and used.
Current group masks describe mapped ownership. Native chart registration uses the source manifest.
Distances and normal agreement measure physical reuse independently of source registration.
New and replaced gear doors and brake panels carry nearest parent paint, not new authored detail.
Brake wells use the separate mechanical material and are outside this skin atlas.

After prepare and audit finish, inventory automatically remaps a changed geometry bake
from the frozen native generation inputs. No source snapshot argument or manual hash is needed:

```powershell
python art/textures/full_skin_guides.py inventory
python art/textures/full_skin_guides.py check
python art/textures/full_skin_guides.py guides
python art/textures/full_skin_registration.py
```

After copying this source pack and the original generated folders into another checkout,
prepare and audit the geometry, then run `python art/textures/full_skin_guides.py inventory`.
`restore` also rebuilds changed maps. Inventory rebinds normalized metadata
to the active checkout and refreshes metadata hashes, preserving original source inputs.
The exact old generation bake and pilot metadata are retained in `native/generation-inputs`
for independent source-atlas coverage checks. No ignored old cache is required.
Unknown canonical parts choose one source physical part by minimum whole-part RMS nearest
world position and normal distance. Normal weight is 0.02 m. Equal scores choose the
lexically first source name. Every such decision records candidate scores, marks the whole
part as parent paint and reports an art limitation. Named new-door donor rules stay fixed.
The bake and atlas hashes must stay unchanged throughout each rebuild.
Current ownership guides go to the review cache. They never replace generation references.
`remap_fields(source_fields, manifest_path)` preserves native registration report counts and
returns the six mapped arrays plus current coverage evidence in `report.source_atlas_mapping`.
''', encoding='utf-8')
    check_inventory(output / 'parts.json')
    return manifest


def restore_inventory(bake, output):
    """Restore current maps or rebuild changed geometry from the frozen native pack."""
    persistent = SOURCE / 'full/source-atlas'
    native = persistent / 'native'
    current = persistent / 'current'
    geometry_paths = {(Path(bake).resolve() / name).as_posix()
                      for name in ('geometry_maps.npz', 'atlas_triangles.json')}
    geometry_changed = not (current / 'parts.json').is_file()

    def rebind(value):
        if isinstance(value, dict):
            return {rebind(key): rebind(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebind(item) for item in value]
        if isinstance(value, str):
            normalized = value.replace('\\', '/')
            for marker in ('/art/textures/', '/.cache/review/'):
                if marker in normalized:
                    return ROOT.as_posix() + marker + normalized.split(marker, 1)[1]
        return value

    changed_metadata = set()
    for folder in (native, current):
        for path in sorted(folder.glob('*.json')):
            if path.name == 'parts.json':
                continue
            original = read_json(path)
            rebound = rebind(original)
            if rebound != original:
                write_json(path, rebound)
                changed_metadata.add(path.as_posix())
    for folder in (native, current):
        path = folder / 'parts.json'
        if not path.is_file() and folder == current:
            continue
        original = read_json(path)
        manifest = rebind(original)
        for dependency, expected in manifest['input_sha256'].items():
            actual = sha256(dependency)
            if folder == current and dependency in geometry_paths and actual != expected:
                geometry_changed = True
                continue
            if actual != expected and dependency not in changed_metadata:
                raise ValueError('Copied source pack dependency differs: ' + dependency)
            manifest['input_sha256'][dependency] = actual
        for dependency, expected in manifest.get('generation_input_sha256', {}).items():
            if sha256(dependency) != expected:
                raise ValueError('Copied generation-atlas input differs: ' + dependency)
        if manifest != original:
            write_json(path, manifest)
            changed_metadata.add(path.as_posix())
    if geometry_changed:
        print('CURRENT GEOMETRY CHANGED; rebuilding world maps from frozen native inputs')
        return rebuild_inventory(bake, output)
    manifest = read_json(current / 'parts.json')
    if Path(manifest['bake']).resolve() != (Path(bake) / 'geometry_maps.npz').resolve():
        raise ValueError('Restored bake resolves outside the current prepare directory')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'coverage.json', read_json(current / 'coverage.json'))
    write_json(output / 'parts.json', {**manifest, 'coverage': (output / 'coverage.json').as_posix(),
                                      'input_sha256': {**manifest['input_sha256'],
                                                       (output / 'coverage.json').as_posix(): sha256(output / 'coverage.json')}})
    check_inventory(output / 'parts.json')
    return manifest


def check_inventory(manifest_path):
    manifest = read_json(manifest_path)
    for path, digest in manifest['input_sha256'].items():
        if sha256(path) != digest:
            raise ValueError('Atlas adaptation input changed: ' + path)
    coverage = read_json(manifest['coverage'])
    with np.load(manifest['bake'], allow_pickle=False) as data:
        used = data['part'] > 0
    source_manifest = read_json(manifest['source_atlas_manifest'])
    source_coverage = read_json(Path(manifest['source_atlas_manifest']).parent / 'coverage.json')
    with np.load(source_coverage['owner_map'], allow_pickle=False) as data:
        source_owner = data['group_index']
    owner = np.zeros(used.shape, np.uint16)
    for rule in coverage['rules']:
        with np.load(rule['map'], allow_pickle=False) as data:
            target, source = data['target_indices'], data['source_indices']
            validate_indices(target, source, used.size, source_owner.size)
            if np.any(owner.ravel()[target]) or not source_owner.ravel()[source].all():
                raise ValueError('Overlapping targets or unassigned generation-atlas donor: ' + rule['name'])
            owner.ravel()[target] = source_owner.ravel()[source]
    if not np.array_equal(owner > 0, used):
        raise ValueError('Atlas adaptation does not cover precisely the current skin')
    for index, (name, group) in enumerate(manifest['groups'].items(), 1):
        mask = np.asarray(Image.open(group['mask'])) > 0
        if not np.array_equal(mask, owner == index) or int(mask.sum()) != group['skin_texels']:
            raise ValueError('Current group mask differs from mapped ownership: ' + name)
    if list(manifest['groups']) != list(source_manifest['groups']):
        raise ValueError('Accepted generation group names or order changed')
    report = {'groups': len(manifest['groups']), 'canonical_parts': len(coverage['parts']),
              'canonical_texels': int(used.sum()), 'unassigned_texels': 0,
              'native_reuse_texels': coverage['native_reuse_texels'],
              'nearest_parent_texels': coverage['unmatched_surface_texels'],
              'inferred_parent_parts': coverage.get('inferred_parent_parts', []),
              'inferred_parent_art_limitation': 'parent material only; no matched mechanical detail'}
    write_json(Path(manifest_path).parent / 'checks.json', report)
    print('ADAPT CHECK PASS', json.dumps(report))
    return report


def validate_indices(target, source, target_size, source_size):
    if (target.ndim != 1 or source.shape != target.shape or
        not np.issubdtype(target.dtype, np.integer) or not np.issubdtype(source.dtype, np.integer) or
        np.any(target < 0) or np.any(target >= target_size) or
        np.any(source < 0) or np.any(source >= source_size) or np.unique(target).size != target.size):
        raise ValueError('Invalid generation-atlas transfer indices')


def remap_fields(source_fields, manifest_path):
    """Copy all registered channels from a frozen source atlas into current UVs."""
    manifest = read_json(manifest_path)
    check_inventory(manifest_path)
    coverage = read_json(manifest['coverage'])
    with np.load(manifest['bake'], allow_pickle=False) as data:
        shape = data['part'].shape
    result = {key: np.zeros((*shape, 3) if key == 'base' else shape, source_fields[key].dtype)
              for key in FIELDS}
    for rule in coverage['rules']:
        with np.load(rule['map'], allow_pickle=False) as data:
            target, source = data['target_indices'], data['source_indices']
            if not source_fields['used'].ravel()[source].all():
                raise ValueError('Source compositor left unassigned transfer donors: ' + rule['name'])
            for key in FIELDS:
                channels = (-1, 3) if key == 'base' else (-1,)
                result[key].reshape(channels)[target] = source_fields[key].reshape(channels)[source]
    result['report'] = copy.deepcopy(source_fields.get('report', {}))
    result['report'].update(assigned_texels=int(result['used'].sum()),
                            source_atlas_manifest=manifest['source_atlas_manifest'],
                            transfers=coverage['rules'], atlas_size=list(shape[::-1]),
                            old_quadrant_fallback_texels=0,
                            source_atlas_mapping={
                                'native_reuse_texels': coverage['native_reuse_texels'],
                                'nearest_parent_texels': coverage['unmatched_surface_texels'],
                                'inferred_parent_parts': coverage.get('inferred_parent_parts', []),
                                'unassigned_texels': coverage['unassigned_texels'],
                                'group_registration_space': 'immutable generation atlas',
                                'current_ownership_space': 'current geometry atlas',
                                'field_contract': list(FIELDS),
                                'input_sha256': manifest['input_sha256']})
    for kind in ('height', 'roughness'):
        result['report'][kind + '_accepted_texels'] = int(result[kind + '_valid'].sum())
    return result


def current_guides(manifest_path, name=None):
    """Draw current ownership without replacing accepted generation references."""
    from pilot2_parts import font
    manifest = read_json(manifest_path)
    check_inventory(manifest_path)
    with np.load(manifest['bake'], allow_pickle=False) as data:
        part = data['part']
        normal = data['normal'][..., :3]
        position = data['position'][..., :3]
    folder = Path(manifest_path).parent / 'current-guides'
    folder.mkdir(parents=True, exist_ok=True)
    notes = {}
    for group_name, group in manifest['groups'].items():
        if name and group_name != name:
            continue
        mask = np.asarray(Image.open(group['mask'])) > 0
        rgb = np.full((*part.shape, 3), 25, np.uint8)
        rgb[part > 0] = 48
        rgb[mask] = np.round((normal[mask] + 1) * 100 + 40).astype(np.uint8)
        image = Image.new('RGB', (part.shape[1], part.shape[0] + 100), '#191919')
        image.paste(Image.fromarray(rgb), (0, 100))
        draw = ImageDraw.Draw(image)
        draw.text((20, 10), group_name + ' | CURRENT ATLAS OWNERSHIP', fill='white', font=font(30))
        draw.text((20, 52), 'Normal RGB = world XYZ | accepted generation layout stays in original guide',
                  fill='#bbbbbb', font=font(24))
        path = folder / (group_name + '.guide.png')
        image.save(path)
        points = position[mask]
        notes[group_name] = {'guide': path.as_posix(), 'current_texels': int(mask.sum()),
                             'current_parts': group['parts'],
                             'world_bounds_m': [points.min(0).tolist(), points.max(0).tolist()] if len(points) else [],
                             'generation_guide': group['references']['guide'],
                             'generation_template': group['references']['template']}
    write_json(folder / ('guides.json' if not name else name + '.json'), notes)
    print('CURRENT GUIDES PASS', len(notes))
