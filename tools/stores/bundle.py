"""The built Icarus from its Blueprinter bundle (.nobp), read with UnityPy: the prefab's transform tree, every rendered
mesh, the hardpoint sets and the stock mounts registered on them, the LandingGear components and the rest pose.

Everything is in the aircraft root frame (Unity: +x right, +y up, +z forward). A pose overrides the local rotation or
position of chosen transforms, the way the game drives the gear, and world() places any transform in it.
"""
import json
import re
from pathlib import Path

import numpy as np

from stores.geometry import quat_matrix


def xyz(d):
    return np.array([d["x"], d["y"], d["z"]], float)


class Aircraft:
    def __init__(self, path):
        import UnityPy  # from tools/local-paths.json python_packages when not installed

        data = Path(path).read_bytes()
        env = UnityPy.load(data)
        objs = {o.path_id: o for o in env.objects}
        tree = {}

        def T(pid):
            if pid not in tree:
                tree[pid] = objs[pid].read_typetree()
            return tree[pid]

        self.names, self.nodes, comp_go = {}, {}, {}
        for pid, o in objs.items():
            if o.type.name == "GameObject":
                d = T(pid)
                self.names[pid] = d["m_Name"]
                for c in d["m_Component"]:
                    comp_go[c["component"]["m_PathID"]] = pid
        self.go_transform = {}
        for pid, o in objs.items():
            if o.type.name in ("Transform", "RectTransform"):
                d = T(pid)
                go = d["m_GameObject"]["m_PathID"]
                q = d["m_LocalRotation"]
                self.nodes[pid] = dict(name=self.names.get(go, ""), go=go, parent=d["m_Father"]["m_PathID"],
                                       pos=xyz(d["m_LocalPosition"]), rot=(q["x"], q["y"], q["z"], q["w"]),
                                       scale=xyz(d["m_LocalScale"]))
                self.go_transform[go] = pid
        scripts = {pid: o.read_typetree().get("m_ClassName") for pid, o in objs.items() if o.type.name == "MonoScript"}
        behaviours = {}
        for pid, o in objs.items():
            if o.type.name == "MonoBehaviour":
                d = T(pid)
                behaviours.setdefault(scripts.get(d["m_Script"]["m_PathID"]), []).append(d)
        manager = next(d for d in behaviours["WeaponManager"] if d.get("hardpointSets"))
        self.root = self._root_of(self.go_transform[manager["m_GameObject"]["m_PathID"]])
        self.sets = [(s["name"], [(self.nodes[h["transform"]["m_PathID"]]["name"], h["transform"]["m_PathID"]) for h in s["hardpoints"]])
                     for s in manager["hardpointSets"]]
        definition = next(d for d in behaviours["AircraftDefinition"])
        self.spawn_offset, self.rest_rotation = xyz(definition["spawnOffset"]), xyz(definition["restRotation"])
        self.gear = [self._gear(d) for d in behaviours["LandingGear"]]

        # The stock mounts arrive through Blueprinter's OpAddWeaponToHardpoint, by set index (patch_manifest.json).
        manifest = next(json.loads(T(pid)["m_Script"].lstrip("﻿")) for pid, o in objs.items()
                        if o.type.name == "TextAsset" and T(pid)["m_Name"] == "patch_manifest")
        self.mounts = [[] for _ in self.sets]
        for op in manifest["Ops"]:
            if op["opId"] != "OpAddWeaponToHardpoint":
                continue
            payload = json.loads(op["payloadJson"])
            for target in payload["aircraft"]:
                for i in target["hardpointIndices"]:
                    self.mounts[i].append(payload["weaponJsonKey"])

        self.meshes = {}  # transform -> (name, local verts, tris) of every enabled, active renderer under the root
        cache = {}
        for go, comps in self._components(objs, comp_go).items():
            transform = self.go_transform.get(go)
            if transform is None or self._root_of(transform) != self.root or not T(go).get("m_IsActive", 1):
                continue
            filters = [c for c in comps if objs[c].type.name == "MeshFilter"]
            renderers = [c for c in comps if objs[c].type.name == "MeshRenderer"]
            if not filters or not renderers or not T(renderers[0]).get("m_Enabled"):
                continue
            mesh = T(filters[0])["m_Mesh"]["m_PathID"]
            if mesh not in objs or re.search(r"_lod\d|colmesh", self.names[go]):
                continue
            if mesh not in cache:
                text = objs[mesh].read().export()
                verts = [(-float(a), float(b), float(c)) for a, b, c in (l.split()[1:4] for l in text.splitlines() if l.startswith("v "))]
                faces = [[int(w.split("/")[0]) - 1 for w in l.split()[1:4]] for l in text.splitlines() if l.startswith("f ")]
                cache[mesh] = (np.asarray(verts, float).reshape(-1, 3), np.asarray(faces, int).reshape(-1, 3))
            self.meshes[transform] = (self.names[go],) + cache[mesh]

    def _components(self, objs, comp_go):
        out = {}
        for comp, go in comp_go.items():
            if comp in objs:
                out.setdefault(go, []).append(comp)
        return out

    def _root_of(self, t):
        while self.nodes[t]["parent"] in self.nodes:
            t = self.nodes[t]["parent"]
        return t

    def _gear(self, d):
        transform = lambda ref: self.go_transform.get(ref["m_PathID"], ref["m_PathID"])  # a GameObject or a Transform
        return dict(
            name=self.names[d["m_GameObject"]["m_PathID"]], hinge=d["gearHinge"]["m_PathID"], fold=d["foldDegrees"],
            unsprung=transform(d["unsprung"]), bump=transform(d["bumpStop"]),
            cast=d["castPoint"]["m_PathID"] or transform(d["bumpStop"]),
            travel=d["suspensionTravel"], radius=d["wheelRadius"], max_compression=d["maxCompression"],
            moving=[(m["transform"]["m_PathID"], m["foldAngles"]["x"]) for m in d["movingParts"] if m["transform"]["m_PathID"]],
            doors=[(door["transform"]["m_PathID"], door["openAngle"]["x"]) for door in d["gearDoors"]])

    def find(self, name):
        return next(t for t, n in self.nodes.items() if n["name"] == name and self._root_of(t) == self.root)

    def world(self, t, pose=None):
        """(position, rotation matrix, scale) of transform t in the root frame under pose {transform: ("rot", q) or
        ("pos", v)}."""
        pose = pose or {}
        chain = []
        while t in self.nodes:
            chain.append(t)
            t = self.nodes[t]["parent"]
        pos, rot, scale = np.zeros(3), np.eye(3), np.ones(3)
        for node in reversed(chain[:-1]):  # the root itself is the frame
            n = self.nodes[node]
            kind, value = pose.get(node, (None, None))
            local_pos = value if kind == "pos" else n["pos"]
            local_rot = quat_matrix(value if kind == "rot" else n["rot"])
            pos = pos + rot @ (scale * local_pos)
            rot = rot @ local_rot
            scale = scale * n["scale"]
        return pos, rot, scale

    def posed(self, t, pose=None):
        """The mesh on transform t as (verts, tris) in the root frame under pose."""
        _, verts, tris = self.meshes[t]
        pos, rot, scale = self.world(t, pose)
        return pos + (verts * scale) @ rot.T, tris

    def under(self, t, ancestor):
        while t in self.nodes:
            if t == ancestor:
                return True
            t = self.nodes[t]["parent"]
        return False
