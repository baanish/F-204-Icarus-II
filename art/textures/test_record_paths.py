"""Portable texture records retain provenance and reject changed dependencies."""
import importlib.util
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from record_paths import ROOT, portable_record, portable_text, read_json, resolve_record, write_json


class RecordPathTests(unittest.TestCase):
    def directory(self):
        path = ROOT / '.cache/record-path-tests' / uuid.uuid4().hex
        path.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, path)
        return path

    def test_paths_and_hash_keys_round_trip_from_another_directory(self):
        value = {'input_sha256': {(ROOT / 'art/textures/input.png').as_posix(): 'digest'},
                 'source': str(ROOT / '.cache/review/source.png'),
                 'original': 'codex:generated_images/run/image.png', 'output': 'image.png'}
        saved = portable_record(value)
        self.assertEqual(saved, {'input_sha256': {'art/textures/input.png': 'digest'},
                                'source': '.cache/review/source.png',
                                'original': 'codex:generated_images/run/image.png', 'output': 'image.png'})
        self.assertEqual(resolve_record(saved)['input_sha256'], value['input_sha256'])
        path = self.directory() / 'record.json'
        write_json(path, value)
        self.assertEqual(json.loads(path.read_text()), saved)
        self.assertEqual(read_json(path)['source'], (ROOT / '.cache/review/source.png').as_posix())

    def test_historical_checkout_paths_in_context_are_relative(self):
        text = 'Source: X:/old checkout/art/textures/generated/part.png.\n- Z:\\old\\.cache\\review\\guide.png'
        self.assertEqual(portable_text(text),
                         'Source: art/textures/generated/part.png.\n- .cache\\review\\guide.png')
        self.assertEqual(portable_record('Z:\\old\\art\\textures\\part.png'), 'art/textures/part.png')
        self.assertEqual(portable_record('X:/old/F-240-Icarus-II/t3-123abc'), 'checkout:t3-123abc')

    def test_conversion_updates_transitive_hashes_and_is_idempotent(self):
        spec = importlib.util.spec_from_file_location('convert_records', ROOT / 'tools/Make-TextureRecordsPortable.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = self.directory()
        generated = root / 'art/textures/generated'
        generated.mkdir(parents=True)
        source = generated / 'source.context.md'
        source.write_text('Source: X:/previous/art/textures/source.png\n')
        manifest = generated / 'parts.json'
        digest = module.hashlib.sha256(source.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({'input_sha256': {str(source): digest}}, separators=(',', ':')))
        outer = generated / 'current.json'
        digest = module.hashlib.sha256(manifest.read_bytes()).hexdigest()
        outer.write_text(json.dumps({'input_sha256': {str(manifest): digest}}))
        with patch.object(module, 'ROOT', root), patch('record_paths.ROOT', root):
            self.assertEqual(len(module.convert_records(generated)), 3)
            self.assertNotIn('\n', manifest.read_text())
            self.assertEqual(module.convert_records(generated), [])
            module.check_dependencies(generated)
            source.write_text('changed native source')
            with self.assertRaisesRegex(ValueError, 'dependency differs'):
                module.check_dependencies(generated)
            with self.assertRaisesRegex(ValueError, 'dependency differs before conversion'):
                module.convert_records(generated)


if __name__ == '__main__':
    unittest.main()
