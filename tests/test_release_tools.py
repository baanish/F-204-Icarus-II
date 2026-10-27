"""Offline release contract checks. Never invokes the publisher or accesses GitHub."""

import hashlib
import json
import subprocess
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAG = "v0.0.1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseToolsTests(unittest.TestCase):
    def setUp(self):
        (REPO / ".cache").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=REPO / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def package(self, *, local=False, extra=None, mismatch=False, metadata=None):
        meta = {
            "id": "baanish.icarus", "sourceCommit": "a" * 40, "local": local,
            "bundle": {"fileName": "icarus_0.0.1.nobp", "hash": "sha256:" + sha256(b"bundle")},
            "artifact": {
                "fileName": "Icarus.dll", "version": "0.0.1", "category": "preRelease",
                "type": "plugin", "gameVersion": "0.34.2", "downloadUrl": "",
                "hash": "sha256:" + sha256(b"plugin"),
                "dependencies": [{"id": "com.nikkorap.blueprinter", "version": "2.1.1"}],
            },
        }
        if metadata:
            metadata(meta)
        payload = {
            "Icarus.dll": b"plugin", "icarus_0.0.1.nobp": b"bundle",
            "meta.json": json.dumps(meta).encode(), "README.md": b"install",
            "LICENSE": b"MIT", "audio/CREDITS.md": b"audio credits", "fonts/OFL.txt": b"font license",
        }
        if extra:
            payload[extra] = b"must not ship"
        (self.root / "meta.json").write_bytes(payload["meta.json"])
        suffix = "-LOCAL" if local else ""
        names = [f"Icarus-{TAG}{suffix}-nomm.zip", f"Icarus-{TAG}{suffix}-plugin-only.zip"]
        for index, name in enumerate(names):
            prefix = "BepInEx/plugins/baanish.icarus/" if index else ""
            with zipfile.ZipFile(self.root / name, "w") as archive:
                for path, data in sorted(payload.items()):
                    if mismatch and index and path == "Icarus.dll":
                        data = b"different plugin"
                    entry = zipfile.ZipInfo(prefix + path, date_time=(2026, 1, 1, 0, 0, 0))
                    archive.writestr(entry, data)
        (self.root / "RELEASE-NOTES.md").write_text("Prerelease, Blueprinter required.")
        self.assets = names + ["RELEASE-NOTES.md", "SHA256SUMS.txt"]
        self.checksums()

    def checksums(self):
        (self.root / "SHA256SUMS.txt").write_text("".join(
            f"{sha256((self.root / name).read_bytes())}  {name}\n" for name in self.assets[:-1]
        ))

    def verify(self, *args):
        return subprocess.run([
            "pwsh", "-NoProfile", "-File", str(REPO / "tools/Verify-Release.ps1"),
            "-Directory", str(self.root), "-Tag", TAG, *args,
        ], capture_output=True, text=True)

    def test_valid_pair_and_rehearsal_policy(self):
        self.package()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.package(local=True)
        self.assertNotEqual(self.verify().returncode, 0)
        result = self.verify("-AllowLocal")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_allowlist_rejects_loader_debug_and_path_entries(self):
        for extra in ("BepInEx.dll", "Blueprinter.dll", "Icarus.pdb", "Icarus.xml", "Icarus.deps.json", "../outside"):
            with self.subTest(extra=extra):
                self.package(extra=extra)
                result = self.verify()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unexpected or duplicate entry", result.stderr)

    def test_checksums_and_paired_payloads(self):
        self.package()
        with (self.root / self.assets[0]).open("ab") as stream:
            stream.write(b"tampered")
        self.assertIn("Checksum mismatch", self.verify().stderr)
        self.package(mismatch=True)
        self.assertIn("Archives disagree", self.verify().stderr)

    def test_required_credits_sorted_entries_and_fixed_time(self):
        for mutation in ("missing-credit", "reordered", "timestamp", "duplicate"):
            with self.subTest(mutation=mutation):
                self.package()
                path = self.root / self.assets[0]
                with zipfile.ZipFile(path) as archive:
                    entries = [(entry, archive.read(entry)) for entry in archive.infolist()]
                if mutation == "missing-credit":
                    entries = [(e, data) for e, data in entries if e.filename != "fonts/OFL.txt"]
                elif mutation == "reordered":
                    entries.reverse()
                elif mutation == "timestamp":
                    entries[0][0].date_time = (2026, 2, 1, 0, 0, 0)
                else:
                    entries.append(entries[0])
                with warnings.catch_warnings(), zipfile.ZipFile(path, "w") as archive:
                    warnings.simplefilter("ignore", UserWarning)
                    for entry, data in entries:
                        archive.writestr(entry, data)
                self.checksums()
                self.assertNotEqual(self.verify().returncode, 0)

    def test_dependency_commit_and_paths(self):
        for mutate in (
            lambda m: m["artifact"].update(dependencies=[]),
            lambda m: m.update(sourceCommit="short"),
            lambda m: m.update(path="E:/private/source"),
            lambda m: m["artifact"].update(category="release"),
            lambda m: m["bundle"].update(hash="sha256:" + "0" * 64),
        ):
            with self.subTest(mutate=mutate):
                self.package(metadata=mutate)
                self.assertNotEqual(self.verify().returncode, 0)

    def test_skip_build_cannot_produce_a_publishable_release(self):
        result = subprocess.run([
            "pwsh", "-NoProfile", "-File", str(REPO / "tools/Package-Release.ps1"), "-SkipBuild",
        ], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("-SkipBuild requires -AllowDirty", result.stdout)

    def test_published_order_prerelease_and_digests(self):
        self.package()
        base = "https://github.com/baanish/F-204-Icarus-II/releases"
        release = {"tag_name": TAG, "draft": False, "prerelease": True,
                   "html_url": f"{base}/tag/{TAG}", "assets": [
                       {"name": name, "browser_download_url": f"{base}/download/{TAG}/{name}",
                        "size": (self.root / name).stat().st_size,
                        "digest": "sha256:" + sha256((self.root / name).read_bytes())}
                       for name in self.assets]}
        path = self.root / "release.json"
        def verify_release():
            path.write_text(json.dumps(release))
            return self.verify("-ReleaseJson", str(path))
        result = verify_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        release["assets"].reverse()
        self.assertIn("NOMM archive first", verify_release().stderr)
        release["assets"].reverse()
        release["prerelease"] = False
        self.assertIn("published prerelease", verify_release().stderr)
        release["prerelease"] = True
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        self.assertIn("GitHub asset mismatch", verify_release().stderr)


if __name__ == "__main__":
    unittest.main()
