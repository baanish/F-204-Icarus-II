"""Publication checks inspect the intended bytes and constrain exceptions."""
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


def windows_path(relative, drive='Q', separator='/'):
    return drive + chr(58) + separator + relative.replace('/', separator)


class PublicCheckTests(unittest.TestCase):
    def setUp(self):
        self.repo = ROOT / '.cache/public-check-tests' / uuid.uuid4().hex
        self.repo.mkdir(parents=True)
        self.addCleanup(self.remove_repository)
        self.git('init', '-q')
        export = self.repo / 'art/export/sample.txt'
        export.parent.mkdir(parents=True)
        export.write_bytes(b'export')
        (self.repo / 'art/export-manifest.json').write_text(json.dumps({
            'art/export/sample.txt': hashlib.sha256(export.read_bytes()).hexdigest()}))
        self.sample = self.repo / 'sample.txt'
        self.sample.write_text('safe')
        (self.repo / 'test_public_check.py').write_bytes(Path(__file__).read_bytes())
        self.git('add', '.')

    def remove_repository(self):
        if not self.repo.resolve().is_relative_to(ROOT / '.cache/public-check-tests'):
            raise ValueError('Test repository escaped workspace scratch')
        literal = str(self.repo).replace("'", "''")
        subprocess.run(['pwsh', '-NoProfile', '-Command',
                        f"Remove-Item -LiteralPath '{literal}' -Recurse -Force"], check=True)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout

    def check(self, all_files=True):
        result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'tools/Check-Public.ps1'),
                                 '-Repo', str(self.repo), *(['-All'] if all_files else [])],
                                capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def test_whole_tree_reads_worktree_and_staged_mode_reads_index(self):
        self.sample.write_text(windows_path('privatefolder/private/file'))
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn('private development path', output)
        code, output = self.check(False)
        self.assertEqual(code, 0, output)

    def test_new_path_rules_and_machine_word_boundaries(self):
        names = json.loads((ROOT / 'tools/public-check-allowlist.json').read_text())[0]['values']
        for value in [windows_path('privatetree/task/file'),
                      windows_path('Users/owner/privatefolder/file', 'R', '\\'),
                      windows_path('SteamLibrary/' + 'users/owner/library', 'S'), *names]:
            with self.subTest(value=value):
                self.sample.write_text(value)
                code, output = self.check()
                self.assertEqual(code, 1, output)
        self.sample.write_text(windows_path('SteamLibrary/steamapps/common/Nuclear Option', 'D') + '\n' +
                               ' '.join('prefix' + name + 'suffix' for name in names))
        code, output = self.check()
        self.assertEqual(code, 0, output)

    def test_account_name_matches_whole_words_only(self):
        account = 'own' + 'er'
        self.sample.write_text(account + 'd')
        code, output = self.check()
        self.assertEqual(code, 0, output)
        self.sample.write_text(account)
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn('private username', output)

    def test_allowlist_requires_exact_path_rule_and_value(self):
        value = json.loads((ROOT / 'tools/public-check-allowlist.json').read_text())[0]['values'][0]
        self.sample.write_text(value)
        config = self.repo / 'tools/public-check-allowlist.json'
        config.parent.mkdir()
        entries = [{'path': path, 'rule': 'private machine name', 'values': [value],
                    'reason': 'Synthetic rule fixture.'} for path in
                   ('sample.txt', 'tools/public-check-allowlist.json')]
        config.write_text(json.dumps(entries))
        code, output = self.check()
        self.assertEqual(code, 0, output)
        self.assertIn('PUBLIC ALLOW: sample.txt', output)
        self.sample.write_text(value + ' ' + windows_path('privatetree/private'))
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn('private development path', output)

    def test_lfs_objects_are_scanned_and_hash_checked_in_both_modes(self):
        content = windows_path('privatefolder/private').encode()
        oid = hashlib.sha256(content).hexdigest()
        path = self.repo / f'.git/lfs/objects/{oid[:2]}/{oid[2:4]}/{oid}'
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
        self.sample.write_text(f'version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(content)}\n')
        self.git('add', 'sample.txt')
        for all_files in (True, False):
            code, output = self.check(all_files)
            self.assertEqual(code, 1, output)
            self.assertIn('private development path', output)
        path.write_bytes(b'corrupt')
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn('does not match its pointer', output)

    def test_export_hashes_are_checked_in_whole_tree_mode(self):
        (self.repo / 'art/export/sample.txt').write_bytes(b'changed export')
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn('export hash differs', output)


if __name__ == '__main__':
    unittest.main()
