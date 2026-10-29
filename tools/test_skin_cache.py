"""Skin cache contracts, runnable with ordinary Python and no Blender process."""
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import skin_cache as cache
from cache_root import cache_root


class SkinCacheTests(unittest.TestCase):
    def cleanup_repo(self):
        def writable(function, path, error):
            os.chmod(path, stat.S_IWRITE)
            function(path)
        shutil.rmtree(self.repo, onexc=writable)

    def setUp(self):
        self.repo = cache.ROOT / '.cache/skin-cache-tests' / uuid4().hex
        self.repo.mkdir(parents=True)
        self.addCleanup(self.cleanup_repo)
        self.geometry = {'parameters': {'size': 2}, 'blender': ['version', 'build'],
                         'numpy': 'version', 'files': {'geometry.py': 'hash'}, 'cycles': ['CPU', []]}
        self.versions = {'python': 'version', 'Pillow': 'version'}
        self.write('art/textures/texture-sources.json', json.dumps({'files': {
            'art/textures/generated/base.png': 'pin'}, 'outputs': [cache.ATLAS + '/native/assembled.png']}))
        self.write('art/textures/generated/base.png')
        self.write(cache.ATLAS + '/native/parts.json', json.dumps({
            'input_sha256': {'art/textures/generated/base.png': 'pin'},
            'generation_input_sha256': {'art/textures/generated/frozen.npz': 'pin'}}))
        self.write('art/textures/generated/frozen.npz')
        for name in ('tools/Rebuild-Skin.ps1', 'tools/Run-Blender.ps1', 'tools/skin_cache.py',
                     'tools/export_manifest.py', 'art/blender/geometry.py',
                     'art/textures/compose_skin.py', 'art/textures/fonts/font.ttf'):
            self.write(name)

    def write(self, name, value='first'):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        return path

    def key(self):
        return cache.key_for(cache.fingerprint(self.repo, self.geometry, self.versions))

    def test_input_changes_invalidate(self):
        for name in ('art/blender/geometry.py', 'art/textures/compose_skin.py',
                     'art/textures/generated/base.png', 'art/textures/generated/frozen.npz',
                     'art/textures/texture-sources.json', 'art/textures/fonts/font.ttf'):
            with self.subTest(name=name):
                before = self.key()
                path = self.repo / name
                original = path.read_text(encoding='utf-8')
                path.write_text(original + ' ', encoding='utf-8')
                self.assertNotEqual(before, self.key())
                path.write_text(original, encoding='utf-8')

    def test_versions_parameters_and_device_invalidate(self):
        before = self.key()
        for field in self.geometry:
            with self.subTest(field=field):
                original = copy.deepcopy(self.geometry)
                self.geometry[field] = 'changed'
                self.assertNotEqual(before, self.key())
                self.geometry = original
        self.versions['Pillow'] = 'new'
        self.assertNotEqual(before, self.key())

    def test_outputs_and_unrelated_files_do_not_invalidate(self):
        before = self.key()
        for name in cache.REQUIRED + tuple(cache.PACK_OUTPUTS) + ('README.md',):
            self.write(name, 'output')
        self.assertEqual(before, self.key())

    def test_hit_restores_outputs_and_corruption_is_a_miss(self):
        for name in cache.REQUIRED:
            self.write(name, name)
        self.write(cache.ATLAS + '/native/assembled.png')
        folder = self.repo / '.cache/entries/key'
        cache.publish(self.repo, folder, 'key', {})
        self.write(cache.MAPS[0], 'local change')
        self.assertTrue(cache.restore(self.repo, folder, 'key'))
        self.assertEqual(cache.MAPS[0], (self.repo / cache.MAPS[0]).read_text())
        (folder / 'files' / cache.MAPS[0]).write_text('corrupt')
        self.assertFalse(cache.restore(self.repo, folder, 'key'))
        # The normal rebuild can replace a damaged entry and make it reusable.
        cache.publish(self.repo, folder, 'key', {})
        self.assertTrue(cache.restore(self.repo, folder, 'key'))

    def test_incomplete_or_failed_entry_is_a_miss(self):
        folder = self.repo / '.cache/entries/key'
        folder.mkdir(parents=True)
        for value in ('{', json.dumps({'key': 'key', 'checks_passed': False, 'outputs': {}}),
                      json.dumps({'key': 'key', 'checks_passed': True, 'outputs': None}),
                      json.dumps({'key': 'key', 'checks_passed': True, 'outputs': {}})):
            (folder / 'manifest.json').write_text(value)
            self.assertFalse(cache.restore(self.repo, folder, 'key'))

    def test_identical_inputs_in_another_checkout_have_same_key(self):
        inputs = cache.fingerprint(self.repo, self.geometry, self.versions)
        copied = self.repo / 'copy'
        for name in inputs['files']:
            target = copied / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.repo / name, target)
        self.assertEqual(cache.key_for(inputs), cache.key_for(
            cache.fingerprint(copied, self.geometry, self.versions)))

    def test_failed_publication_never_creates_hit(self):
        folder = self.repo / '.cache/entries/key'
        with self.assertRaises(FileNotFoundError):
            cache.publish(self.repo, folder, 'key', {})
        self.assertFalse(cache.restore(self.repo, folder, 'key'))

    def test_bypass_forces_miss_even_with_valid_entry(self):
        geometry = self.write('geometry.json', '{}')
        with patch.object(cache, 'ROOT', self.repo), patch.object(cache, 'fingerprint', return_value={}), \
                patch.object(cache.importlib.metadata, 'version', return_value='version'), \
                patch.object(cache, 'restore') as restore, \
                patch.dict(os.environ, {'ICARUS_NO_SKIN_CACHE': '1'}), \
                patch.object(sys, 'argv', ['skin_cache.py', 'restore', '--geometry', str(geometry)]):
            with self.assertRaises(SystemExit) as miss:
                cache.main()
            self.assertEqual(3, miss.exception.code)
            restore.assert_not_called()

    def test_hit_refreshes_non_skin_export_hashes_and_commit(self):
        self.write('art/export/aircraft.obj', 'new geometry export')
        self.write('art/textures/gate.json', json.dumps({
            'geometry_commit': 'old', 'inputs': {'art/export-manifest.json': 'old'}, 'outputs': {'skin': 'hash'}}))
        with patch.object(cache.subprocess, 'check_output', return_value='new-commit\n'):
            cache.refresh_gate(self.repo)
        gate = json.loads((self.repo / 'art/textures/gate.json').read_text())
        self.assertEqual('new-commit', gate['geometry_commit'])
        self.assertEqual(cache.digest(self.repo / 'art/export-manifest.json'),
                         gate['inputs']['art/export-manifest.json'])
        self.assertEqual({'skin': 'hash'}, gate['outputs'])
        self.assertIn('art/export/aircraft.obj', json.loads((self.repo / 'art/export-manifest.json').read_text()))

    def test_worktree_uses_shared_root_and_copy_uses_local_root(self):
        main = self.repo / 'main'
        tree = self.repo / 'tree'
        subprocess.run(['git', 'init', '-q', str(main)], check=True)
        subprocess.run(['git', '-C', str(main), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
        subprocess.run(['git', '-C', str(main), 'worktree', 'add', '-q', '--detach', str(tree)], check=True)
        self.addCleanup(subprocess.run, ['git', '-C', str(main), 'worktree', 'remove', '--force', str(tree)], check=True)
        self.assertEqual(main / '.cache', cache_root(tree))
        self.assertEqual(main / '.cache', cache_root(main))
        # A copied remote tree can sit inside another checkout; don't inherit its cache.
        copied = self.repo / 'copied'
        copied.mkdir()
        self.assertEqual(copied / '.cache', cache_root(copied))
        with patch('cache_root.subprocess.check_output', side_effect=FileNotFoundError):
            self.assertEqual(tree / '.cache', cache_root(tree))


if __name__ == '__main__':
    unittest.main()
