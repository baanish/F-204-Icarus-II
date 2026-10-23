"""Geometry/cache contracts. Run inside Blender through tools/Run-Blender.ps1."""
import ast
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager
from uuid import uuid4
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "art/blender"))
import build_icarus as bi
import build_cache
import geometry_cache
import internals


def original_functions(path, names, namespace):
    source = subprocess.check_output(["git", "show", "4d815d5:" + path], cwd=ROOT).decode()
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for function in functions:
        function.decorator_list = []
    scope = dict(namespace)
    exec(compile(ast.Module(body=functions, type_ignores=[]), path, "exec"), scope)
    return scope


@contextmanager
def test_repo():
    repo = ROOT / ".cache/build-cache-tests" / uuid4().hex
    repo.mkdir(parents=True)
    yield repo


class GeometryCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = original_functions("art/blender/build_icarus.py", {"blended_ring", "skin_ring"}, vars(bi))

    def tearDown(self):
        geometry_cache.clear()

    def test_every_loft_station_matches_original_exactly(self):
        for station in bi.fuselage_stations(bi.PARAMS):
            with self.subTest(station=station):
                expected = self.original["blended_ring"](bi.PARAMS, station)
                actual = bi.blended_ring(bi.PARAMS, station)
                self.assertEqual([tuple(v) for v in expected], [tuple(v) for v in actual])

    def test_mutation_angles_parameters_and_clipping(self):
        p = copy.deepcopy(bi.PARAMS)
        expected = bi.blended_ring(p, 7.5)
        changed = bi.blended_ring(p, 7.5)
        changed[0].x = 999
        self.assertEqual([tuple(v) for v in expected], [tuple(v) for v in bi.blended_ring(p, 7.5)])
        p["area_rule"]["depth"] += .01
        for station, angles in ((7.5, [0., .1, .3, 2., 4.]), (10., None)):
            self.assertEqual([tuple(v) for v in self.original["blended_ring"](p, station, angles)],
                             [tuple(v) for v in bi.blended_ring(p, station, angles)])
        original = original_functions("art/blender/internals.py", {"ring_at"}, vars(internals))["ring_at"]
        for inset, floor, lo, hi, count in ((.03, None, None, None, None), (.04, -.15, .26, .92, 48)):
            args = (p, 8.2, inset, floor, lo, hi, count)
            self.assertEqual([tuple(v) for v in original(*args)], [tuple(v) for v in internals.ring_at(*args)])


class BuildCacheTests(unittest.TestCase):
    def test_geometry_cache_is_cleared_between_builds_and_after_failure(self):
        calls = []

        @geometry_cache.ring
        def sample(p, station):
            calls.append(station)
            return [bi.P(station, p["blend"], 0)]

        sample(bi.PARAMS, 1.)
        base = bi.PARAMS
        with patch.object(bi, "_build", side_effect=lambda repo: sample(bi.PARAMS, 1.)):
            bi.build()
            bi.build(overrides={"blend": .3})
        self.assertIs(base, bi.PARAMS)
        self.assertEqual(3, len(calls))

        def fail(repo):
            sample(bi.PARAMS, 1.)
            raise ValueError("check failed")

        with patch.object(bi, "_build", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "check failed"):
                bi.build(overrides={"blend": .3})
        sample(dict(base, blend=.3), 1.)
        self.assertIs(base, bi.PARAMS)
        self.assertEqual(5, len(calls))

    def test_sources_references_missing_files_parameters_and_environment_invalidate(self):
        with test_repo() as temporary:
            repo = Path(temporary)
            (repo / "art/blender").mkdir(parents=True)
            source = repo / "art/blender/example.py"
            source.write_text("first")
            parameters = copy.deepcopy(bi.PARAMS)
            initial = json.dumps(build_cache.inputs(repo, parameters), sort_keys=True)
            source.write_text("second")
            self.assertNotEqual(initial, json.dumps(build_cache.inputs(repo, parameters), sort_keys=True))
            source.write_text("first")
            reference = repo / parameters["references"]["dir"] / "top.png"
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"new reference")
            self.assertNotEqual(initial, json.dumps(build_cache.inputs(repo, parameters), sort_keys=True))
            reference.unlink()
            with patch.dict(os.environ, {"ICARUS_CYCLES_CPU": "different"}):
                self.assertNotEqual(initial, json.dumps(build_cache.inputs(repo, parameters), sort_keys=True))
            with patch.dict(os.environ, {"ICARUS_NO_BUILD_CACHE": "1"}):
                self.assertEqual(initial, json.dumps(build_cache.inputs(repo, parameters), sort_keys=True))
            parameters["area_rule"]["depth"] += .01
            self.assertNotEqual(initial, json.dumps(build_cache.inputs(repo, parameters), sort_keys=True))

    def test_failed_build_is_not_published(self):
        with test_repo() as temporary:
            repo = Path(temporary)
            with patch.object(bi, "build", side_effect=ValueError("check failed")):
                with self.assertRaisesRegex(ValueError, "check failed"):
                    build_cache.load_or_build(repo)
            self.assertFalse((repo / ".cache/build-cache").exists())

    def test_force_rebuild_bypasses_cache(self):
        with patch.dict(os.environ, {"ICARUS_NO_BUILD_CACHE": "1"}), patch.object(bi, "build", return_value={}) as build:
            self.assertEqual({}, bi.build_cached(overrides={"blend": .3}))
            self.assertEqual({"blend": .3}, build.call_args.args[1])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful():
        raise SystemExit(1)
