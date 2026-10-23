"""Compare static rear/side silhouettes with collider projections, without running Unity or the game.

Run with --help. Reads the built Icarus bundle and AssetRipper stock prefabs. Excludes landing gear,
doors, ladders, pilots, cockpit interiors, effects and lower LODs from all aircraft. Surfaces stay in
their authored neutral pose. Areas are INFERRED from triangle rasterization, not live shot tests.
Only colliders with a damageable component on the same object count as hit area, matching BulletSim.
Convex mesh colliders use their convex hull, as Unity cooking does. PNGs show visual-only red,
covered green, and collider-only blue, at the same pixels per metre for every aircraft.
"""
import argparse
import functools
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import ConvexHull

from stores import meshverts
from stores.geometry import quat_matrix
from stores.prefab_tree import asset_index, docs_of


EXCLUDED = re.compile(r"gear|wheel|ladder|chock|pilot|interior|cockpit_int|canopy_int|_lod[1-9]|colmesh|weaponbay|afterburner|muzzle|flame|glow", re.I)


def xyz(d):
    return np.array([d[k] for k in "xyz"], float)


def ref(d):
    return d.get("fileID", d.get("m_PathID", 0))


class Scene:
    def __init__(self, objects, mesh):
        self.objects, self.mesh = objects, mesh
        self.gos = {i: d for i, (k, d, _) in objects.items() if k == "GameObject"}
        self.transforms = {i: d for i, (k, d, _) in objects.items() if k in ("Transform", "RectTransform")}
        self.go_transform = {ref(d["m_GameObject"]): i for i, d in self.transforms.items()}
        self.components = {}
        for i, (k, d, _) in objects.items():
            if "m_GameObject" in d:
                self.components.setdefault(ref(d["m_GameObject"]), []).append(i)
        self.lower_lods = set()
        for k, d, _ in objects.values():
            if k == "LODGroup":
                self.lower_lods.update(ref(r["renderer"]) for lod in d["m_LODs"][1:] for r in lod["renderers"])

    @functools.cache
    def path(self, t):
        d = self.transforms[t]
        p = ref(d["m_Father"])
        n = self.gos[ref(d["m_GameObject"])]["m_Name"]
        return self.path(p) + "/" + n if p in self.transforms else n

    @functools.cache
    def world(self, t):
        d = self.transforms[t]
        q = d["m_LocalRotation"]
        m = np.eye(4)
        m[:3, :3] = quat_matrix(tuple(q[k] for k in "xyzw")) * xyz(d["m_LocalScale"])
        m[:3, 3] = xyz(d["m_LocalPosition"])
        p = ref(d["m_Father"])
        return self.world(p) @ m if p in self.transforms else np.eye(4)

    def active(self, t):
        while t in self.transforms:
            d = self.transforms[t]
            if not self.gos[ref(d["m_GameObject"])].get("m_IsActive", 1):
                return False
            t = ref(d["m_Father"])
        return True

    def placed(self, t, geometry):
        v, f = geometry
        m = self.world(t)
        return v @ m[:3, :3].T + m[:3, 3], f

    def identity(self):
        for i, (k, d, line) in self.objects.items():
            if k == "MonoBehaviour" and "cockpit" in d and "pilots" in d:
                go = ref(d["m_GameObject"])
                cp = self.objects[ref(d["cockpit"])][1]
                cg = ref(cp["m_GameObject"])
                return dict(aircraft=self.path(self.go_transform[go]), aircraft_line=line,
                            cockpit=self.path(self.go_transform[cg]), cockpit_line=self.objects[ref(d["cockpit"])][2])
        raise ValueError("Aircraft component missing")

    def geometry(self):
        identity = self.identity()
        root = identity["aircraft"]
        visual, colliders, inventory = [], [], []
        for go, cs in self.components.items():
            t = self.go_transform.get(go)
            if t is None or not self.path(t).startswith(root + "/") and self.path(t) != root:
                continue
            path = self.path(t)
            if EXCLUDED.search(path) or not self.active(t):
                continue
            filters = [self.objects[c][1] for c in cs if self.objects[c][0] == "MeshFilter"]
            for c in cs:
                k, d, line = self.objects[c]
                if not d.get("m_Enabled", 1):
                    continue
                if k == "MeshRenderer" and c not in self.lower_lods and filters and self.gos[go].get("m_Layer") != 3:
                    geometry = self.mesh(filters[0]["m_Mesh"])
                    if geometry is not None:
                        visual.append(self.placed(t, geometry))
                        inventory.append(dict(path=path, kind=k, line=line, triangles=len(geometry[1])))
                if k.endswith("Collider") and not d.get("m_IsTrigger", 0):
                    damageable = any("armorProperties" in self.objects[i][1] and "hitPoints" in self.objects[i][1] for i in cs)
                    if not damageable:
                        inventory.append(dict(path=path, kind=k, line=line, layer=self.gos[go].get("m_Layer"),
                                              excluded_from_hit_area="no damageable component on collider object"))
                        continue
                    if k == "MeshCollider":
                        geometry = self.mesh(d["m_Mesh"])
                        if geometry is None:
                            raise ValueError(f"unresolved collider mesh {path}")
                        if d.get("m_Convex", 0):
                            v = np.unique(geometry[0], axis=0)
                            geometry = v, ConvexHull(v).simplices
                    elif k == "BoxCollider":
                        v = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)])
                        v = v * xyz(d["m_Size"]) + xyz(d["m_Center"])
                        geometry = v, ConvexHull(v).simplices
                    elif k in ("SphereCollider", "CapsuleCollider"):
                        v = np.array([[np.sin(a)*np.cos(b), np.cos(a), np.sin(a)*np.sin(b)]
                                      for a in np.linspace(0, np.pi, 33) for b in np.linspace(0, 2*np.pi, 65)]) * d["m_Radius"]
                        if k == "CapsuleCollider":
                            axis = d["m_Direction"]
                            v[:, axis] += np.sign(v[:, axis]) * max(0, d["m_Height"] / 2 - d["m_Radius"])
                        v += xyz(d["m_Center"])
                        geometry = v, ConvexHull(v).simplices
                    else:
                        raise ValueError(f"unsupported collider {k} {path}")
                    colliders.append(self.placed(t, geometry))
                    inventory.append(dict(path=path, kind=k, line=line, triangles=len(geometry[1])))
        assert visual and colliders
        return visual, colliders, inventory


def stock_scene(root, name, index):
    import yaml
    source = root / "GameObject" / (name + ".prefab")
    objects = {}
    for i, d in docs_of(source).items():
        parsed = yaml.safe_load(d["body"])
        kind = next(iter(parsed))
        objects[i] = kind, parsed[kind], d["line"]

    @functools.cache
    def read_mesh(guid):
        p = index.get(guid)
        if p is None:
            return None
        return np.asarray(meshverts.positions(p)), np.asarray(meshverts.triangles(p))

    return Scene(objects, lambda d: read_mesh(d.get("guid", ""))), source


def bundle_scene(path):
    import UnityPy
    env = UnityPy.load(path.read_bytes())
    readers = {o.path_id: o for o in env.objects}
    objects = {i: (o.type.name, o.read_typetree(), None) for i, o in readers.items() if o.type.name != "Mesh"}

    @functools.cache
    def read_mesh(i):
        if i not in readers:
            return None
        obj = readers[i].read().export()
        v = [(-float(a), float(b), float(c)) for a, b, c in (l.split()[1:4] for l in obj.splitlines() if l.startswith("v "))]
        f = [[int(w.split("/")[0])-1 for w in l.split()[1:4]] for l in obj.splitlines() if l.startswith("f ")]
        return np.asarray(v).reshape(-1, 3), np.asarray(f, int).reshape(-1, 3)

    return Scene(objects, lambda d: read_mesh(ref(d)))


def raster(meshes, axes, lo, size, ppm):
    im = Image.new("1", tuple(size))
    draw = ImageDraw.Draw(im)
    for v, f in meshes:
        p = (v[:, axes] - lo) * ppm
        for tri in p[f]:
            # Degenerate projected triangles have zero area; rasterizing their edges inflates silhouettes.
            a, b = tri[1] - tri[0], tri[2] - tri[0]
            if abs(a[0]*b[1] - a[1]*b[0]) > .0001:
                draw.polygon([tuple(x) for x in tri], fill=1)
    return np.asarray(im, bool)


def measure(visual, colliders, axes, ppm, output):
    pts = np.concatenate([v[:, axes] for v, _ in visual + colliders])
    lo, hi = pts.min(0) - .05, pts.max(0) + .05
    size = np.ceil((hi-lo)*ppm).astype(int) + 1
    v, c = [raster(m, axes, lo, size, ppm) for m in (visual, colliders)]
    both = v & c
    pixels = np.zeros((*v.shape, 3), np.uint8) + 245
    pixels[v & ~c] = (210, 65, 50)
    pixels[both] = (55, 150, 90)
    pixels[c & ~v] = (50, 110, 220)
    Image.fromarray(pixels[::-1]).save(output)
    return dict(visual_m2=float(v.sum()/ppm**2), collider_m2=float(c.sum()/ppm**2),
                intersection_m2=float(both.sum()/ppm**2), coverage_percent=float(both.sum()/v.sum()*100),
                visual_missed_m2=float((v & ~c).sum()/ppm**2),
                visual_width_height_m=np.ptp(np.concatenate([v[:, axes] for v, _ in visual]), axis=0).tolist())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game-export", type=Path, required=True)
    p.add_argument("--icarus-bundle", type=Path, required=True)
    p.add_argument("--python-packages", type=Path)
    p.add_argument("--out", type=Path, default=Path(".cache/camera-targetspeed/hitboxes"))
    args = p.parse_args()
    if args.python_packages:
        sys.path.insert(0, str(args.python_packages))
    args.out.mkdir(parents=True, exist_ok=True)
    index = asset_index(args.game_export, "Mesh", "MonoScript")
    scenes = [("Icarus", bundle_scene(args.icarus_bundle), args.icarus_bundle)]
    scenes += [(n, *stock_scene(args.game_export, key, index)) for n, key in (("Revoker", "Fighter1"), ("Ifrit", "Multirole1"))]
    report = dict(method="INFERRED static orthographic union of projected triangles; 200 and 400 pixels per metre",
                  excluded_path_pattern=EXCLUDED.pattern, aircraft={})
    for name, scene, source in scenes:
        visual, colliders, inventory = scene.geometry()
        row = dict(source=str(source.resolve()), sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   identity=scene.identity(), visual_meshes=len(visual), colliders=len(colliders), inventory=inventory, views={})
        for view, axes in (("rear", [0, 1]), ("side", [2, 1])):
            row["views"][view] = {str(ppm): measure(visual, colliders, axes, ppm, args.out/f"{name}-{view}-{ppm}.png") for ppm in (200, 400)}
        report["aircraft"][name] = row
        print(name, json.dumps({k: v for k, v in row.items() if k != "inventory"}))
    (args.out / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
