"""AO ownership and offline skin review. Imported by bake_skin inside Blender."""
import json
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache/review/wave2/p9b/02'


def bake_ao(canonical):
    import uvs
    scene = bpy.context.scene
    # Each bake texel evaluates 128 AO probes once, rather than multiplying 128 by 128.
    scene.cycles.samples = 1
    scene.render.bake.use_clear = True
    hidden = {o: o.hide_render for o in scene.objects if o.type == 'MESH'}
    groups = {s: [o.name for o in canonical if o.name.startswith('skin_' + s)] + ['fuselage_' + s]
              for s in ('forward', 'mid', 'aft')}
    groups['wing_left'] = ['wing_skin_L', 'wing_spar_L']
    contexts = [bpy.data.objects[name] for members in groups.values() for name in members
                if name not in {o.name for o in canonical}]
    arrays = {}
    try:
        for obj in hidden:
            obj.hide_render = True
        for mode in ('self', 'assembly'):
            verts, faces, coords, slots = [], [], [], []
            bake_objects = canonical if mode == 'self' else canonical + contexts
            for index, obj in enumerate(bake_objects):
                group = next((i for i, members in enumerate(groups.values()) if obj.name in members), None)
                # Separating bake copies leaves all self occluders intact and excludes moving neighbours.
                offset = 30 * (index + 4 if mode == 'self' or group is None else group)
                base = len(verts)
                verts.extend((p.x + offset, p.y, p.z) for p in (obj.matrix_world @ v.co for v in obj.data.vertices))
                for face in obj.data.polygons:
                    faces.append([base + i for i in face.vertices])
                    coords.extend(tuple(obj.data.uv_layers.active.data[i].uv) for i in face.loop_indices)
                    slots.append(0 if obj.data.materials[face.material_index].name == uvs.SKIN else 1)
            mesh = bpy.data.meshes.new('Skin_AO_' + mode)
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            uv = mesh.uv_layers.new(name='UVMap')
            for loop, co in zip(uv.data, coords):
                loop.uv = co
            obj = bpy.data.objects.new('Skin_AO_' + mode, mesh)
            scene.collection.objects.link(obj)
            image = bpy.data.images.new('Skin_AO_' + mode, width=2048, height=2048, alpha=True, float_buffer=True)
            image.colorspace_settings.name = 'Non-Color'
            sink = bpy.data.images.new('Skin_AO_trim_sink', width=8, height=8)
            for target_image in (image, sink):
                mat = bpy.data.materials.new('Skin_AO_bake')
                mat.use_nodes = True
                nodes, links = mat.node_tree.nodes, mat.node_tree.links
                nodes.clear()
                output = nodes.new('ShaderNodeOutputMaterial')
                emit = nodes.new('ShaderNodeEmission')
                ao = nodes.new('ShaderNodeAmbientOcclusion')
                ao.only_local = True
                ao.samples = 128
                ao.inputs['Distance'].default_value = .6
                links.new(ao.outputs['AO'], emit.inputs['Color'])
                links.new(emit.outputs[0], output.inputs['Surface'])
                target = nodes.new('ShaderNodeTexImage')
                target.image = target_image
                nodes.active = target
                mesh.materials.append(mat)
            for face, slot in zip(mesh.polygons, slots):
                face.material_index = slot
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.bake(type='EMIT')
            pixels = np.empty(2048 * 2048 * 4, np.float32)
            image.pixels.foreach_get(pixels)
            arrays[mode] = pixels.reshape(2048, 2048, 4)[::-1, :, 0].copy()
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.images.remove(image)
            bpy.data.images.remove(sink)
            print('SKIN AO PASS', mode, flush=True)
        assembly = np.clip(arrays['assembly'] / np.maximum(arrays['self'], 1e-5), 0, 1)
        np.savez_compressed(OUT / 'ao_maps.npz', self=arrays['self'], assembly=assembly,
                            combined=arrays['self'] * assembly)
        (OUT / 'ao_policy.json').write_text(json.dumps({'samples': 128, 'distance_m': .6,
            'cycles_samples': 1, 'ao_probes_per_sample': 128,
            'bake_copy_separation_m': 30, 'stable_groups': groups,
            'self_only': [o.name for o in canonical if not any(o.name in group for group in groups.values())]}, indent=2))
    finally:
        for obj, hide in hidden.items():
            obj.hide_render = hide
        scene.cycles.samples = 32


def review_maps(livery_id=None):
    import os
    import bake_skin as bake
    from mathutils import Matrix
    import math

    bpy.ops.wm.open_mainfile(filepath=str(OUT / 'skin.blend'))
    from mathutils import Vector
    bpy.data.objects['Skin_sun'].rotation_euler = Vector((6, -8, 12)).to_track_quat('Z', 'Y').to_euler()
    cache = OUT / 'optix-cache'
    cache.mkdir(exist_ok=True)
    os.environ['OPTIX_CACHE_PATH'] = str(cache)
    scene = bpy.context.scene
    scene.cycles.samples = 32
    prefs = bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
        if any(device.use for device in prefs.devices):
            scene.cycles.device = 'GPU'
    except (TypeError, RuntimeError):
        scene.cycles.device = 'CPU'
    bake.VIEWS.update({'intake': ((4, -4, 1.5), (.6, -.5, .3), 3.8),
                       'wing': ((6, -2, 5), (1.9, 1.8, -.2), 4.8),
                       'belly': ((10, 0, -15), (0, 0, 0), 18)})
    stores = load_stores()
    rendered = []
    for i in range(1, 5):
        if livery_id is not None and i != livery_id:
            continue
        preview_material(i)
        for loaded in (False, True):
            station_state(stores, loaded)
            name = 'livery_%d_%s' % (i, 'loaded' if loaded else 'empty')
            for view in ('top', 'side', 'front_quarter', 'rear_quarter'):
                bake.render(name, view)
                rendered.append(name + '_' + view + '.png')
        for view in ('nose', 'wing_root'):
            bake.render('livery_%d_close' % i, view)
            rendered.append('livery_%d_close_%s.png' % (i, view))
    if livery_id is not None:
        print('SKIN LIVERY REVIEW PASS', livery_id, len(rendered), flush=True)
        return
    station_state(stores, False)
    sun = bpy.data.objects['Skin_sun']
    original_sun = sun.rotation_euler.copy()
    sun.rotation_euler = Vector((4, -8, 2)).to_track_quat('Z', 'Y').to_euler()
    for clay in (True, False):
        preview_material(1, clay=clay)
        name = 'raking_clay' if clay else 'raking_livery_1'
        for view in ('nose', 'wing_root'):
            bake.render(name, view)
            rendered.append(name + '_' + view + '.png')
    sun.rotation_euler = original_sun
    preview_material(1, clay=True)
    for view in ('top', 'side', 'nose', 'intake', 'wing'):
        bake.render('clay_normal_ao', view)
        rendered.append('clay_normal_ao_' + view + '.png')
    matrices = {}
    for name in ('canopy', 'flap_L', 'flap_R', 'lef_L', 'lef_R', 'speed_brake_L', 'speed_brake_R',
                 'gear_door_N_L', 'gear_door_N_R', 'gear_door_main_L', 'gear_door_main_R'):
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise ValueError('Missing articulated review part: ' + name)
        matrices[obj] = obj.matrix_basis.copy()
        travel = obj.get('travel_deg', obj.get('deflection_deg', 30))
        if 'deflection_deg' in obj:
            visible = bpy.data.objects[name + '_visible']
            centre = sum((v.co for v in visible.data.vertices), Vector()) / len(visible.data.vertices)
            centre = visible.matrix_local @ centre
            def score(sign):
                point = obj.matrix_world @ Matrix.Rotation(math.radians(sign), 4, 'X') @ centre
                return abs(point.x) if name.startswith('speed_brake') else -point.z
            travel *= 1 if score(1) > score(-1) else -1
        obj.matrix_basis = obj.matrix_basis @ Matrix.Rotation(math.radians(travel), 4, 'X')
    bpy.context.view_layer.update()
    for view in ('front_quarter', 'rear_quarter', 'belly'):
        bake.render('ao_deployed_open', view)
        rendered.append('ao_deployed_open_' + view + '.png')
    for obj, matrix in matrices.items():
        obj.matrix_basis = matrix
    detached_views(bake)
    rendered += ['ao_detached_front_quarter.png', 'ao_detached_rear_quarter.png']
    preview_material(1, damage=True)
    for view in ('front_quarter', 'rear_quarter', 'nose'):
        bake.render('damage_full', view)
        rendered.append('damage_full_' + view + '.png')
    preview_material(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'review.blend'))
    settings = {'resolution': [1600, 1000], 'engine': 'CYCLES', 'samples': 32,
                'device': scene.cycles.device, 'views': bake.VIEWS,
                'sun_direction': [6, -8, 12], 'raking_sun_direction': [4, -8, 2],
                'sun_energy': 2.5, 'world_strength': .7, 'view_transform': 'AgX',
                'stations': 'stock MMR-S3 tip rails, twin MMR-S3 inner racks, own conformal AAM-29 mounts',
                'clay': 'neutral base with normal and AO only', 'renders': rendered}
    (OUT / 'render_manifest.json').write_text(json.dumps(settings, indent=2))
    print('SKIN REVIEW PASS', len(rendered), flush=True)


def detached_views(bake):
    wing = bpy.data.objects['wing_spar_L']
    detached = [wing, *wing.children_recursive, bpy.data.objects['skin_forward_R']]
    hidden = {obj: obj.hide_render for obj in detached}
    try:
        for obj in hidden:
            obj.hide_render = True
        for view in ('front_quarter', 'rear_quarter'):
            bake.render('ao_detached', view)
    finally:
        for obj, value in hidden.items():
            obj.hide_render = value


def preview_material(livery, clay=False, damage=False):
    import uvs
    mat = bpy.data.materials[uvs.SKIN]
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    links.new(bsdf.outputs[0], output.inputs['Surface'])
    folder = ROOT / 'art/export/textures'
    def texture(name, linear=False):
        node = nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(str(folder / name), check_existing=True)
        if linear:
            node.image.colorspace_settings.name = 'Non-Color'
        return node
    colour = texture('Icarus_skin_dmg_b.png' if damage else 'Icarus_livery_%d.png' % livery)
    ao = texture('Icarus_skin_ao.png', True)
    multiply = nodes.new('ShaderNodeMixRGB')
    multiply.blend_type = 'MULTIPLY'
    multiply.inputs[0].default_value = 1
    multiply.inputs[1].default_value = (.55, .55, .55, 1)
    if not clay:
        links.new(colour.outputs['Color'], multiply.inputs[1])
    links.new(ao.outputs['Color'], multiply.inputs[2])
    links.new(multiply.outputs[0], bsdf.inputs['Base Color'])
    normal = texture('Icarus_skin_dmg_n.png' if damage else 'Icarus_skin_n.png', True)
    normal_map = nodes.new('ShaderNodeNormalMap')
    links.new(normal.outputs['Color'], normal_map.inputs['Color'])
    links.new(normal_map.outputs[0], bsdf.inputs['Normal'])
    metal = texture('Icarus_skin_m.png', True)
    separate = nodes.new('ShaderNodeSeparateColor')
    links.new(metal.outputs['Color'], separate.inputs[0])
    if not clay:
        links.new(separate.outputs['Red'], bsdf.inputs['Metallic'])
        roughness = nodes.new('ShaderNodeMath')
        roughness.operation = 'SUBTRACT'
        roughness.inputs[0].default_value = 1
        links.new(metal.outputs['Alpha'], roughness.inputs[1])
        links.new(roughness.outputs[0], bsdf.inputs['Roughness'])
    else:
        bsdf.inputs['Roughness'].default_value = .6


def load_stores():
    import sys
    import math
    from mathutils import Matrix, Vector
    sys.path.insert(0, str(ROOT / 'tools'))
    from stores import paths
    from stores.mounts import load_mount
    from stores.prefab_tree import asset_index
    from trough_sections import missile_mesh
    import stations
    root = paths.load()['game_export']
    index = asset_index(root, 'Mesh')
    collection = bpy.data.collections.new('Skin_review_stores')
    bpy.context.scene.collection.children.link(collection)
    mat = bpy.data.materials.new('Skin_review_store')
    mat.diffuse_color = (.46, .49, .48, 1)
    mat.use_nodes = True
    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.46, .49, .48, 1)
    objects = []
    def hang(name, vertices, triangles, hp, roll=0):
        rotate = Matrix.Rotation(math.radians(roll), 4, 'Y')
        coords = [Vector(hp) + rotate @ Vector((-x, -z, y)) for x, y, z in vertices]
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([tuple(v) for v in coords], [], [tuple(t) for t in triangles])
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        mesh.materials.append(mat)
        objects.append(obj)
    (tip_v, tip_t), _ = load_mount(root, index, 'AAM1_single')
    (inner_v, inner_t), _ = load_mount(root, index, 'AAM1_double')
    layout = stations.export(lambda p: (-p[0], p[2], -p[1]))
    # Tip coordinates from the measured root-frame station table, before the Unity import axis reflection.
    for side in (1, -1):
        hang('Skin_review_tip_' + str(side), tip_v, tip_t, (side * 3.395, 2.7835, -.562), -90 * side)
        blade = bpy.data.objects['pylon_inner_' + ('L' if side == 1 else 'R')]
        points = [blade.matrix_world @ v.co for v in blade.data.vertices]
        low = min(p.z for p in points)
        edge = [p.y for p in points if p.z < low + .01]
        hp = (sum(p.x for p in points) / len(points), (min(edge) + max(edge)) / 2, low)
        hang('Skin_review_inner_' + str(side), inner_v, inner_t, hp)
        verts, tris = missile_mesh(index, 'AAM2')
        m = layout['mounts']['AAM2_single']
        pitch = math.radians(m['pitch'])
        placed = [(x + m['position'][0], y * math.cos(pitch) - z * math.sin(pitch) + m['position'][1],
                   y * math.sin(pitch) + z * math.cos(pitch) + m['position'][2]) for x, y, z in verts]
        c = stations.CONFORMAL
        # CONFORMAL s is nose-referenced; Blender world y subtracts the generator's S0.
        import build_icarus
        hang('Skin_review_conformal_' + str(side), placed, tris, (side * c['x'], c['s'] - build_icarus.S0, c['z']))
    return objects


def station_state(stores, loaded):
    for obj in stores:
        obj.hide_render = not loaded
    for side in ('L', 'R'):
        bpy.data.objects['pylon_inner_' + side].hide_render = not loaded
        bpy.data.objects['pylon_inner_plug_' + side].hide_render = loaded
