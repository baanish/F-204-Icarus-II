"""The Icarus's own 25 mm gun pod for the centreline station: a body drawn for the belly around the stock rotary gun.

The stock pod (gun_25mm_trainer_pod) is the T/A-30's: a flat-sided adapter block for that jet's pylon over a bulb that
hangs the gun 0.61 m below the hardpoint. On the Icarus the pod is the owner's design (2026-11-27): the adapter is gone,
the gun rides up under the skin and a body of its own wraps it. Each section is a rounded keel KEEL under the belly's
centreline, a shallow underside out to a chine CHINE under it at CHINE_X, and a straight cheek from there up to the skin
at TOP, 0.66 m across, which stops short of the conformal troughs' rims. Aft of its widest station it shrinks into the
belly; forward it narrows, its keel held under the gun's barrels, and over its last NOSE metres every section turns
into a U round the barrels, which leave through an opening in a small fore cap.

The pod is a store in its own collection, its mesh in the mount's frame (origin on the centreline hardpoint). Only
the body is new: IcarusAuthor.GunPod.cs copies the stock mount, keeps its gun, ammunition and firing, raises the gun to
GUN_AXIS and draws this body in place of the stock one.

Frame: Blender, nose -Y, up +Z, left +X; station s = y + 8.
"""
import math

import bpy
from mathutils import Matrix, Vector

import build_icarus as bi

COLLECTION = "GunPod"  # its own, beside Stores, which tip_tanks.BUDGET measures whole
NAME = "gunpod_25mm_body"
KEY = "baanish_icarus_gunpod_25mm"
ROOT_PART = "fuselage_mid"
# The centreline hardpoint, metres forward of the root part's origin, 5 mm under the skin (IcarusAuthor.Centreline.cs
# CentrelineStation, IcarusAuthor.Stations.cs).
STATION, INSET = 0.8, 0.005
# The body, by aircraft Z (forward of the root part's origin): its aft and fore ends, the fraction of its length at its
# widest, and how much the fore part narrows (the owner's pick, measured clear of gear, doors, intakes and deck).
AFT_Z, FORE_Z, WIDEST, FORE_NARROW = -0.55, 2.46, 0.45, 0.35
# The section, metres: half-span of the top edge on the skin, the chine's half-span, the chine's and the keel's depth
# under the belly's centreline, and how far the top edge is sunk into the skin.
TOP, CHINE_X, CHINE, KEEL, EMBED = 0.33, 0.14, 0.11, 0.15, 0.01
# The gun's axis under the hardpoint, which holds the barrels 16.75 mm under the belly and the muzzle's ray 5.55 mm clear
# of the root collider with the gear up; the opening round it in the fore cap.
GUN_AXIS, OPENING = 0.1066, 0.068
# The barrels' radius and the body's wall under them; the nose's length and its U's radius round the gun's axis.
BARREL, WALL, NOSE, NOSE_R = 0.064, 0.015, 0.55, 0.085
# The fraction of its length over which the keel eases down to clear the barrels, ending at its widest station.
EASE = 0.1
# The collider: a capsule along the pod inside the body, clear of every other part's collider (centre in the
# hardpoint's frame, aircraft axes).
COLLIDER = {"centre": [0.0, -0.0694, 0.24], "radius": 0.031, "length": 1.46}
RINGS, KEEL_STEPS, CHEEK_STEPS, ARC_STEPS = 48, 8, 8, 10
SPREAD = 0.0008


def skin_field(p, s):
    skin, zc = bi.skin_field(p, s)
    sq = bi.area_squeeze(p, s)
    return (lambda x, z: skin(x / sq, zc + (z - zc) / sq) * sq), zc


def skin_z(p, x, s, step=0.005):
    """The uncut skin's lowest point over x at station s (it spans the troughs, which are cut later)."""
    field, zc = skin_field(p, s)
    hi = zc - 3.0
    while field(x, hi) > 0:
        hi += step
        if hi > zc + 1.0:
            raise ValueError(f"gun pod: no skin over x {x:.3f} at s {s:.3f}")
    lo = hi - step
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        if field(x, mid) > 0:
            lo = mid
        else:
            hi = mid
    return hi


def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def section(p, s, u, axis_z, nose):
    """The right half of the section at fraction u from the aft end, keel to top edge, as (x, z) world points; nose is
    how far (0 to 1) it has turned into the U round the barrels."""
    if u < WIDEST:
        g = (1 - ((WIDEST - u) / WIDEST) ** 2) ** 0.55
        depth = g
    else:
        g = 1 - FORE_NARROW * smooth((u - WIDEST) / (1 - WIDEST))
        depth = 1.0
    t, c = max(0.004, TOP * g), CHINE_X * g
    b0 = skin_z(p, 0.0, s)
    extra = max(0.0, b0 - KEEL - (axis_z - BARREL - WALL)) * smooth((u - WIDEST + EASE) / EASE)
    zt, zc, zk = skin_z(p, t, s) + EMBED, b0 - CHINE * depth - extra, b0 - KEEL * depth - extra
    half = [(c * q / KEEL_STEPS, zk + (zc - zk) * (q / KEEL_STEPS) ** 1.6) for q in range(KEEL_STEPS + 1)]
    for q in range(1, CHEEK_STEPS + 1):
        x = c + (t - c) * q / CHEEK_STEPS
        half.append((x, min(zc + (zt - zc) * q / CHEEK_STEPS, skin_z(p, x, s) + EMBED)))
    if nose <= 0:
        return half
    u_shape = [(NOSE_R * math.sin(0.5 * math.pi * q / KEEL_STEPS), axis_z - NOSE_R * math.cos(0.5 * math.pi * q / KEEL_STEPS))
               for q in range(KEEL_STEPS + 1)]
    top = skin_z(p, NOSE_R, s) + EMBED
    u_shape += [(NOSE_R, axis_z + (top - axis_z) * q / CHEEK_STEPS) for q in range(1, CHEEK_STEPS + 1)]
    w = smooth(nose)
    return [(a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w) for a, b in zip(half, u_shape)]


def hardpoint(icarus):
    """The centreline hardpoint, world: STATION forward of the root part's origin, INSET under the skin."""
    root = bpy.data.objects[ROOT_PART]
    s = root.matrix_world.translation.y + bi.S0 - STATION
    return Vector((0.0, s - bi.S0, skin_z(bi.PARAMS, 0.0, s) - INSET))


def mesh(p, hp):
    """The body's vertices (world) and faces: the rings, a point at the aft end and the fore cap with the opening."""
    s_aft, s_fore = hp.y + bi.S0 - (AFT_Z - STATION), hp.y + bi.S0 - (FORE_Z - STATION)
    rings = []
    for k in range(RINGS + 1):
        u = k / RINGS
        s = s_aft + (s_fore - s_aft) * u
        nose = (s_aft - s - (s_aft - s_fore - NOSE)) / NOSE
        half = section(p, s, u, hp.z - GUN_AXIS, nose)
        ring = [(-x, z) for x, z in reversed(half[1:])] + half
        rings.append([Vector((x, s - bi.S0, z)) for x, z in ring])
    verts = [v for r in rings for v in r]
    m = len(rings[0])
    faces = [[a * m + i, a * m + i + 1, (a + 1) * m + i + 1, (a + 1) * m + i] for a in range(RINGS) for i in range(m - 1)]
    tip = len(verts)
    verts.append(sum(rings[0], Vector()) / m)
    faces += [[i + 1, i, tip] for i in range(m - 1)]
    # Every ring is drawn the same way round, so one winding serves the sides and the aft point: the lowest face's.
    keel = min(faces, key=lambda f: sum(verts[i].z for i in f))
    a, b, c = (verts[i] for i in keel[:3])
    if (b - a).cross(c - a).z > 0:
        faces = [list(reversed(f)) for f in faces]
    # The fore cap: each rim point to the opening round the gun at its own angle, then the arc over the opening to the
    # skin, which closes the cap between the cheeks' top edges.
    axis = Vector((0.0, s_fore - bi.S0, hp.z - GUN_AXIS))
    angles = []
    for v in rings[-1]:
        a = math.atan2(v.z - axis.z, v.x - axis.x)
        while angles and a > angles[-1] + math.pi:
            a -= 2 * math.pi
        while angles and a < angles[-1] - math.pi:
            a += 2 * math.pi
        angles.append(a)
    hole = len(verts)
    verts += [axis + OPENING * Vector((math.cos(a), 0.0, math.sin(a))) for a in angles]
    base = RINGS * m
    faces += [[base + i, base + i + 1, hole + i + 1, hole + i] for i in range(m - 1)]
    turn = 2 * math.pi if angles[-1] > angles[0] else -2 * math.pi
    arc = [angles[-1] + (angles[0] + turn - angles[-1]) * q / ARC_STEPS for q in range(ARC_STEPS + 1)]
    lip, over = len(verts), len(verts) + ARC_STEPS + 1
    verts += [axis + OPENING * Vector((math.cos(a), 0.0, math.sin(a))) for a in arc]
    s_fore_skin = s_fore
    for a in arc:
        x = axis.x + OPENING * math.cos(a)
        verts.append(Vector((x, axis.y, skin_z(p, x, s_fore_skin) + EMBED)))
    faces += [[lip + q, lip + q + 1, over + q + 1, over + q] for q in range(ARC_STEPS)]
    faces.append([base + m - 1, over, lip])
    faces.append([over + ARC_STEPS, base, lip + ARC_STEPS])
    return verts, faces, s_aft, s_fore


def outward(verts, faces, s_fore):
    """The fore cap's faces wound to face forward; mesh() winds the rest."""
    fore_y = s_fore - bi.S0
    out = []
    for f in faces:
        a, b, c = (verts[i] for i in f[:3])
        forward = all(abs(verts[i].y - fore_y) < 1e-6 for i in f) and (b - a).cross(c - a).y > 0
        out.append(list(reversed(f)) if forward else f)
    return out


def skin_uv(icarus, hp):
    """The atlas UV of the belly's skin just behind the hardpoint, read from below."""
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform

    import uvs

    best = None
    start, ray = Vector((0.003, hp.y + 0.05, hp.z - 1.0)), Vector((0, 0, 1))
    for obj in icarus.all_objects:
        if obj.type != "MESH" or "UVMap" not in obj.data.uv_layers or uvs.SKIN not in [m.name for m in obj.data.materials if m]:
            continue
        me = obj.data
        me.calc_loop_triangles()
        uv = me.uv_layers["UVMap"].data
        tris = [t for t in me.loop_triangles if me.materials[t.material_index] and me.materials[t.material_index].name == uvs.SKIN]
        if not tris:
            continue
        corners = [[obj.matrix_world @ me.vertices[i].co for i in t.vertices] for t in tris]
        tree = BVHTree.FromPolygons([v for c in corners for v in c], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))],
                                    all_triangles=True)
        at, _, index, dist = tree.ray_cast(start, ray, 2.0)
        if at is not None and (best is None or dist < best[0]):
            best = (dist, barycentric_transform(at, *corners[index], *[Vector((*uv[i].uv, 0)) for i in tris[index].loops]).to_2d())
    if best is None:
        raise ValueError("gun pod paint: no belly skin over the centreline hardpoint")
    return best[1]


def build(p, mats, icarus):
    """The body in its own collection, hung on the centreline hardpoint; its mesh is in the mount's frame."""
    collection = bi.collection(COLLECTION)
    hp = hardpoint(icarus)
    verts, faces, s_aft, s_fore = mesh(p, hp)
    faces = outward(verts, faces, s_fore)
    me = bpy.data.meshes.new(NAME)
    me.from_pydata([tuple(v - hp) for v in verts], [], faces)
    me.validate()
    me.update()
    obj = bpy.data.objects.new(NAME, me)
    collection.objects.link(obj)
    obj.matrix_world = Matrix.Translation(hp)
    bi.finish(obj, mats["body"])
    point = skin_uv(icarus, hp)
    layer = me.uv_layers.new(name="UVMap")
    length = s_aft - s_fore
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        layer.data[loop.index].uv = point + SPREAD * Vector((co.x / (2 * TOP), co.y / length))
    obj["paint_uv"] = list(point)
    return obj


def export(to_unity, icarus):
    """The pod for blockout.json: its key, the hardpoint it was drawn on (world, Unity axes), and in the hardpoint's frame
    (aircraft axes) the gun's axis height, the opening and the collider."""
    obj = bpy.data.objects[NAME]
    return {"key": KEY, "part": ROOT_PART, "hardpoint_unity": to_unity(obj.matrix_world.translation),
            "gun_axis_y": -GUN_AXIS, "opening": OPENING, "collider": COLLIDER}
