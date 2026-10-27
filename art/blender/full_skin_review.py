"""Render the saved skin scene; --plan computes native-mask cameras without Blender."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'art/textures'))
from record_paths import resolve_record

FULL = ROOT / '.cache/review/wave2/p9b-round2/full'
BAKE = ROOT / '.cache/review/wave2/p9b/02'
RENDERS = FULL / 'renders'
TEXTURES = FULL / 'art/export/textures'
MAPS = [f'Icarus_livery_{i}.png' for i in range(1, 5)] + [
    f'Icarus_skin_{suffix}.png' for suffix in ('n', 'ao', 'm', 'dmg_b', 'dmg_n')] + ['Icarus_livery_4_m.png']
RESOLUTION = (1600, 1000)
OVERVIEWS = {
    'top': ((0, 0, 35), (0, 0, 0), 20),
    'side': ((28, 0, 1), (0, 0, .6), 20),
    'front_quarter': ((16, -23, 12), (0, 0, .4), 18),
    'rear_quarter': ((-16, 22, 11), (0, 0, .4), 18),
}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / max(float(np.linalg.norm(vector)), 1e-12)


def camera_basis(direction, roll_top=False):
    outward = unit(direction)
    reference = (0, 1, 0) if abs(outward[2]) > .95 else (0, 0, 1)
    right = unit(np.cross(reference, outward))
    up = np.cross(outward, right)
    if roll_top:
        right, up = up, -right
    return np.stack((right, up, outward))


def camera(bounds, direction):
    bounds = np.asarray(bounds)
    target = bounds.mean(axis=0)
    basis = camera_basis(direction)
    corners = np.array(list(itertools.product(*zip(*bounds))))
    projected = (corners - target) @ basis.T
    span = np.ptp(projected, axis=0)
    if span[1] > span[0]:
        basis[0], basis[1] = basis[1].copy(), -basis[0].copy()
        span[0], span[1] = span[1], span[0]
    scale = max(float(span[0]), float(span[1]) * RESOLUTION[0] / RESOLUTION[1], .1) * 1.2
    distance = max(float(np.linalg.norm(bounds[1] - bounds[0])) * 4, 1)
    return {'location': (target + basis[2] * distance).tolist(), 'target': target.tolist(),
            'basis_rows': basis.tolist(), 'ortho_scale': scale,
            'sun_direction': unit(basis[0] - .35 * basis[1] + .22 * basis[2]).tolist()}


def view_directions(normals):
    """Use at most two views; opposite faces must not disappear in a mean normal."""
    sample = normals[::max(1, len(normals) // 8192)]
    candidates = [unit(v) for v in itertools.product((-1, 0, 1), repeat=3) if any(v)]
    mean = sample.mean(axis=0)
    if np.linalg.norm(mean) > .1:
        candidates.insert(0, unit(mean))
    directions = np.asarray(candidates)
    dots = sample @ directions.T
    facing = dots > .05
    first = max(range(len(directions)), key=lambda i: facing[:, i].mean() + .02 * np.maximum(dots[:, i], 0).mean())
    opposed = any((sample[:, axis] > .45).mean() > .12 and
                  (sample[:, axis] < -.45).mean() > .12 for axis in range(3))
    if not opposed and facing[:, first].mean() >= .98:
        return [directions[first]]
    pairs = (pair for pair in itertools.combinations(range(len(directions)), 2)
             if not opposed or directions[pair[0]] @ directions[pair[1]] < -.2)
    a, b = max(pairs, key=lambda pair: np.any(facing[:, pair], axis=1).mean()
               + .2 * np.maximum(dots[:, pair].max(axis=1), 0).mean())
    return [directions[a], directions[b]]


def load_mask(path, bpy=None):
    if bpy is None:
        from PIL import Image
        with Image.open(path) as image:
            return np.asarray(image.convert('L')) > 127
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape(image.size[1], image.size[0], -1)[::-1, :, 0] > .5
    finally:
        bpy.data.images.remove(image)


def build_plan(group=None, overview_only=False, navy=False, bpy=None, groups_only=False):
    manifest_path = FULL / 'parts.json'
    manifest = resolve_record(json.loads(manifest_path.read_text()))
    if group is not None and group not in manifest['groups']:
        raise ValueError(f'Unknown group {group!r}; choose from {", ".join(manifest["groups"])}')
    bake_path = Path(manifest['bake'])
    atlas_path = bake_path.with_name('atlas_triangles.json')
    names = json.loads(atlas_path.read_text())['parts']
    with np.load(bake_path) as data:
        part = data['part']
        position = data['position'][..., :3]
        normal = data['normal'][..., :3]
    groups, renders = {}, []
    for name, spec in manifest['groups'].items():
        if overview_only or (group is not None and name != group):
            continue
        sources = spec['source_parts']
        mask = load_mask(spec['mask'], bpy)
        if mask.shape != part.shape or not mask.any():
            raise ValueError(f'Empty or wrong-sized native mask: {name}')
        ids = [names.index(source) + 1 for source in sources]
        if np.any(mask & ~np.isin(part, ids)):
            raise ValueError(f'Mask includes non-source parts: {name}')
        if int(mask.sum()) != spec['skin_texels']:
            raise ValueError(f'Mask texel count changed: {name}')
        points, normals = position[mask], normal[mask]
        if not np.isfinite(points).all() or not np.isfinite(normals).all():
            raise ValueError(f'Nonfinite native bake: {name}')
        normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        bounds = np.stack((points.min(axis=0), points.max(axis=0)))
        directions = view_directions(normals)
        facing = np.stack([normals @ direction > .05 for direction in directions], axis=1)
        groups[name] = {'source_parts': sources, 'mask': spec['mask'], 'mask_sha256': sha256(spec['mask']),
                        'native_mask_texels': int(mask.sum()), 'world_bounds_m': bounds.tolist(),
                        'normal_facing_union_fraction': float(facing.any(axis=1).mean()),
                        'coverage_method': 'native-mask normals dot camera direction > 0.05; occlusion untested'}
        for i, direction in enumerate(directions):
            view = camera(bounds, direction)
            view['normal_facing_fraction'] = float(facing[:, i].mean())
            for material in (('clay', 'navy') if navy and i == 0 else ('clay',)):
                renders.append({'file': f'groups/{name}_{material}_{i + 1:02d}.png', 'group': name,
                                'material': material, 'livery': 1, 'view': f'face_{i + 1:02d}',
                                'camera': view, 'visible_parts': sources, 'status': 'planned'})
    if group is None and not groups_only:
        for livery in range(1, 5):
            for name, (location, target, scale) in OVERVIEWS.items():
                basis = camera_basis(np.asarray(location) - target, roll_top=name == 'top')
                view = {'location': list(location), 'target': list(target), 'ortho_scale': scale,
                        'basis_rows': basis.tolist(), 'sun_direction': [6, -8, 12]}
                renders.append({'file': f'overviews/livery_{livery}_{name}.png', 'group': None,
                                'material': 'overview', 'livery': livery, 'view': name,
                                'camera': view, 'visible_parts': None, 'status': 'planned'})
    return {'schema_version': 1, 'geometry': str(BAKE / 'skin.blend'),
            'input_sha256': {str(path): sha256(path) for path in (manifest_path, bake_path, atlas_path)},
            'resolution': list(RESOLUTION), 'samples': 32, 'engine': 'CYCLES', 'view_transform': 'AgX',
            'framing': 'all native-mask world bounds, long axis horizontal, orthographic width with 20 percent margin',
            'groups': groups, 'renders': renders}


def preview_material(bpy, livery, clay, glossiness=None, metallic_map=None):
    """Match skin_review.preview_material, consuming the full run's smoothness alpha."""
    mat = bpy.data.materials['Icarus_Body']
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    links.new(bsdf.outputs[0], output.inputs['Surface'])

    def texture(name, linear=True):
        node = nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(str(TEXTURES / name), check_existing=True)
        node.image.colorspace_settings.name = 'Non-Color' if linear else 'sRGB'
        return node

    ao = texture('Icarus_skin_ao.png')
    multiply = nodes.new('ShaderNodeMixRGB')
    multiply.blend_type = 'MULTIPLY'
    multiply.inputs[0].default_value = 1
    multiply.inputs[1].default_value = (.55, .55, .55, 1)
    if not clay:
        colour = texture(f'Icarus_livery_{livery}.png', linear=False)
        links.new(colour.outputs['Color'], multiply.inputs[1])
    links.new(ao.outputs['Color'], multiply.inputs[2])
    links.new(multiply.outputs[0], bsdf.inputs['Base Color'])
    normal = texture('Icarus_skin_n.png')
    normal_map = nodes.new('ShaderNodeNormalMap')
    normal_map.space = 'TANGENT'
    links.new(normal.outputs['Color'], normal_map.inputs['Color'])
    links.new(normal_map.outputs['Normal'], bsdf.inputs['Normal'])
    bsdf.inputs['Metallic'].default_value = 0
    bsdf.inputs['Roughness'].default_value = .6
    if not clay:
        metal = texture(metallic_map or ('Icarus_livery_4_m.png' if livery == 4 else 'Icarus_skin_m.png'))
        separate = nodes.new('ShaderNodeSeparateColor')
        links.new(metal.outputs['Color'], separate.inputs[0])
        links.new(separate.outputs['Red'], bsdf.inputs['Metallic'])
        roughness = nodes.new('ShaderNodeMath')
        roughness.operation = 'SUBTRACT'
        roughness.inputs[0].default_value = 1
        gloss = nodes.new('ShaderNodeMath')
        gloss.operation = 'MAXIMUM'
        if glossiness is None:
            spec = next((ROOT / 'art/textures/liveries').glob(f'{livery}_*.json'))
            glossiness = json.loads(spec.read_text())['glossiness']
        gloss.inputs[1].default_value = glossiness
        links.new(metal.outputs['Alpha'], gloss.inputs[0])
        links.new(gloss.outputs[0], roughness.inputs[1])
        floor = nodes.new('ShaderNodeMath')
        floor.operation = 'MAXIMUM'
        floor.inputs[1].default_value = float(np.sqrt(.0078125))
        links.new(roughness.outputs[0], floor.inputs[0])
        links.new(floor.outputs[0], bsdf.inputs['Roughness'])


def configure_scene(bpy):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 32
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = True
    scene.cycles.seed = 0
    scene.cycles.device = 'CPU'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
        if any(device.use for device in prefs.devices):
            scene.cycles.device = 'GPU'
    except (TypeError, RuntimeError) as error:
        print('FULL SKIN OPTIX UNAVAILABLE', str(error), flush=True)
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.use_border = False
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes['Background']
    background.inputs[0].default_value = (.16, .19, .24, 1)
    background.inputs[1].default_value = .7
    sun = bpy.data.objects['Skin_sun']
    sun.data.energy = 2.5
    for obj in scene.objects:
        if obj.type == 'LIGHT':
            obj.hide_render = obj != sun
    scene.camera = bpy.data.objects['Skin_camera']
    scene.camera.data.type = 'ORTHO'
    scene.camera.data.clip_start = .001
    scene.camera.data.clip_end = 1000
    scene.camera.data.dof.use_dof = False
    scene.camera.data.shift_x = scene.camera.data.shift_y = 0
    for side in ('L', 'R'):
        bpy.data.objects[f'pylon_inner_{side}'].hide_render = True
        bpy.data.objects[f'pylon_inner_plug_{side}'].hide_render = False
    return scene


def alignment_evidence():
    path = FULL / 'alignment.json'
    return {'path': str(path), 'status': 'available' if path.is_file() else 'missing',
            'sha256': sha256(path) if path.is_file() else None,
            'report': json.loads(path.read_text()) if path.is_file() else None}


def visible_meshes(layer):
    if layer.exclude or layer.collection.hide_render:
        return set()
    visible = {obj for obj in layer.collection.objects if obj.type == 'MESH' and not obj.hide_render}
    for child in layer.children:
        visible.update(visible_meshes(child))
    return visible


def render(args):
    missing = [str(TEXTURES / name) for name in MAPS if not (TEXTURES / name).is_file()]
    if missing:
        raise FileNotFoundError('Compose all nine full maps before rendering: ' + ', '.join(missing))
    cache = RENDERS / 'optix-cache'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['OPTIX_CACHE_PATH'] = str(cache)
    import bpy
    from mathutils import Matrix, Vector

    bpy.ops.wm.open_mainfile(filepath=str(BAKE / 'skin.blend'))
    plan = build_plan(args.group, args.overview_only, args.navy, bpy, args.groups_only)
    scene = configure_scene(bpy)
    for entry in plan['renders']:
        if entry['visible_parts'] is None:
            continue
        corners = np.array([tuple(bpy.data.objects[name].matrix_world @ Vector(corner))
                            for name in entry['visible_parts']
                            for corner in bpy.data.objects[name].bound_box])
        bounds = np.stack((corners.min(axis=0), corners.max(axis=0)))
        previous_view = entry['camera']
        entry['camera'] = camera(bounds, previous_view['basis_rows'][2])
        entry['camera']['normal_facing_fraction'] = previous_view['normal_facing_fraction']
        entry['camera']['framing_bounds_m'] = bounds.tolist()
    plan['framing'] = 'entire visible mesh world bounds, orthographic width with 20 percent margin'
    meshes = [obj for obj in scene.objects if obj.type == 'MESH']
    overview_visibility = {obj: obj.hide_render for obj in meshes}
    maps = {name: sha256(TEXTURES / name) for name in MAPS}
    alignment = alignment_evidence()
    metadata = {'map_sha256': maps, 'alignment_sha256': alignment['sha256'],
                'geometry_sha256': sha256(BAKE / 'skin.blend'), 'device': scene.cycles.device,
                'samples': 32, 'resolution': list(RESOLUTION)}
    for entry in plan['renders']:
        entry.update(metadata)
    manifest_path = FULL / 'render_manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    if previous.get('geometry_sha256') != metadata['geometry_sha256']:
        previous = {}
    retained = [entry for entry in previous.get('renders', [])
                if (args.group is not None and entry['group'] != args.group)
                or (args.overview_only and entry['group'] is not None)
                or (args.groups_only and entry['group'] is None)]
    manifest = {**plan, **metadata, 'optix_cache': str(cache), 'alignment': alignment,
                'height_usage': {'status': 'alignment_report_available' if alignment['report'] is not None else 'awaiting_alignment_report',
                                 'consumer': 'Icarus_skin_n.png; same normal/AO in clay and Navy',
                                 'direct_height_displacement': False,
                                 'generated_height_acceptance': 'see alignment report; not inferred from PNG presence'},
                'material_policy': {'clay': 'neutral 0.55 times AO; metallic 0; roughness 0.6',
                                    'navy_and_overview': 'livery times AO; metallic R; smoothness=max(alpha,livery gloss); D3D11 roughness floor approximation',
                                    'group_lighting': 'matched clay/Navy camera-relative raking sun; exact directions per view'},
                'stations': 'empty; inner pylons hidden, plugs visible; no external store meshes loaded',
                'groups': {**previous.get('groups', {}), **plan['groups']},
                'renders': retained + plan['renders']}

    def save_manifest():
        manifest['requested_complete'] = all(entry['status'] == 'rendered' for entry in plan['renders'])
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')

    save_manifest()
    try:
        for entry in plan['renders']:
            sources = entry['visible_parts']
            for obj in meshes:
                obj.hide_render = overview_visibility[obj] if sources is None else obj.name not in sources
            if sources is not None:
                for name in sources:
                    obj = bpy.data.objects.get(name)
                    if obj not in overview_visibility:
                        raise ValueError('Source mesh absent from saved scene: ' + name)
                    if obj not in visible_meshes(bpy.context.view_layer.layer_collection):
                        raise ValueError('Source mesh excluded from render collections: ' + name)
            entry['visible_parts'] = sorted(obj.name for obj in visible_meshes(bpy.context.view_layer.layer_collection))
            preview_material(bpy, entry['livery'], entry['material'] == 'clay')
            view = entry['camera']
            scene.camera.location = view['location']
            scene.camera.rotation_euler = Matrix(view['basis_rows']).transposed().to_euler()
            scene.camera.data.ortho_scale = view['ortho_scale']
            bpy.data.objects['Skin_sun'].rotation_euler = Vector(view['sun_direction']).to_track_quat('Z', 'Y').to_euler()
            path = RENDERS / entry['file']
            path.parent.mkdir(parents=True, exist_ok=True)
            scene.render.filepath = str(path)
            bpy.context.view_layer.update()
            bpy.ops.render.render(write_still=True)
            entry['status'] = 'rendered'
            entry['png_sha256'] = sha256(path)
            save_manifest()
            print('FULL SKIN RENDER PASS', entry['file'], flush=True)
    finally:
        for obj, hidden in overview_visibility.items():
            obj.hide_render = hidden
    print('FULL SKIN REVIEW PASS', len(plan['renders']), manifest_path, flush=True)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--group', metavar='NAME', help='render only this manifest source group')
    selection.add_argument('--overview-only', action='store_true', help='render only the 16 empty-aircraft overviews')
    selection.add_argument('--groups-only', action='store_true', help='render only source-group views')
    parser.add_argument('--navy', action='store_true', help='add one matched Navy preview per selected group')
    parser.add_argument('--plan', action='store_true', help='print cameras and bounds without Blender, maps, or writes')
    if argv is None:
        if '--' in sys.argv:
            argv = sys.argv[sys.argv.index('--') + 1:]
        else:
            argv = [] if '--python' in sys.argv or '-P' in sys.argv else sys.argv[1:]
    return parser.parse_args(argv)


if __name__ == '__main__':
    options = arguments()
    if options.plan:
        print(json.dumps(build_plan(options.group, options.overview_only, options.navy, groups_only=options.groups_only), indent=2))
    else:
        render(options)
