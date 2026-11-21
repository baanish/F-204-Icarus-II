"""Offline release contract checks. Never invokes the publisher or accesses GitHub."""

import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
import zlib
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import livery_kit as kit  # noqa: E402

TAG = "v0.0.1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseToolsTests(unittest.TestCase):
    def setUp(self):
        (REPO / ".cache").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=REPO / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.painted_hashes(b"painted livery")

    def package(self, *, local=False, extra=None, mismatch=False, metadata=None, sources=None, kit_root=None,
                invalid_kit_png=None, invalid_kit_data=b"placeholder text"):
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
        source_files = {"art/textures/generated/full/part.png": b"base", "art/textures/generated/old.npz": b"bake"}
        manifest = {path: sha256(data) for path, data in source_files.items()}
        entries = dict(source_files, **{"texture-sources.json": json.dumps({"files": manifest}).encode()})
        if sources:
            sources(entries)
        names.append(f"Icarus-{TAG}{suffix}-texture-sources.zip")
        with zipfile.ZipFile(self.root / names[-1], "w") as archive:
            for path, data in sorted(entries.items()):
                archive.writestr(zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0)), data)
        self.kit_name = f"icarus_livery_kit_{TAG[1:]}{suffix}.zip"
        names.append(self.kit_name)
        top = kit_root or kit.kit_name(TAG[1:])
        png = io.BytesIO()
        Image.new("RGB", (1, 1)).save(png, format="PNG")
        kit_payload = {f"maps/{name}": (kit.EXPORT / name).read_bytes() for name in kit.SHARED_MAPS}
        kit_payload["install/IcarusLiveryBuilder.cs"] = (kit.DOCS / "IcarusLiveryBuilder.cs").read_bytes()
        kit_payload["install/meta.json"] = json.dumps({"AircraftKey": kit.JSON_KEY}).encode()
        # model files that store one texture path each, beside model/ (livery_kit.model_texture_problems)
        texture = b"..\\examples\\Icarus_livery_1.png"
        node = b"RelativeFilename" + b"S" + struct.pack("<I", len(texture)) + texture
        kit_payload["model/icarus_paint_model.fbx"] = (
            b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400)
            + struct.pack("<IIIB", 27 + 13 + len(node), 1, len(node) - 16, 16) + node + bytes(13))
        kit_payload["model/icarus_paint_model.blend"] = b"BLENDER-v405\x00\x01//../maps/Icarus_skin_n.png\x00"
        if invalid_kit_png:
            kit_payload[invalid_kit_png] = invalid_kit_data
        with zipfile.ZipFile(self.root / self.kit_name, "w") as archive:
            for path in kit.expected_files(kit.specifications()):
                data = kit_payload.get(path, png.getvalue() if path.endswith(".png") else b"kit fixture")
                archive.writestr(zipfile.ZipInfo(f"{top}/{path}", date_time=kit.FIXED_TIME), data)
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
        ], capture_output=True, text=True, env=self.env)

    def test_valid_pair_and_rehearsal_policy(self):
        self.package()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.package(local=True)
        self.assertNotEqual(self.verify().returncode, 0)
        result = self.verify("-AllowLocal")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_verification_requires_roundel_references(self):
        self.package()
        Path(self.env["ICARUS_FACTION_MARKS_HASHES"]).unlink()
        self.env["ICARUS_SKIP_ROUNDEL_EXPORT"] = "1"
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        diagnostic = " ".join(line.lstrip(" |") for line in result.stderr.splitlines())
        self.assertIn("no stock roundels from the local game export or recorded painted-output hashes are available",
                      diagnostic)

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

    def test_livery_kit_requires_a_checksum_and_the_versioned_root(self):
        self.package()
        self.assets.remove(self.kit_name)
        self.checksums()
        self.assertIn("must cover every archive", self.verify().stderr)
        self.package()
        with (self.root / self.kit_name).open("ab") as stream:
            stream.write(b"tampered")
        self.assertIn(f"Checksum mismatch: {self.kit_name}", self.verify().stderr)
        self.package(kit_root="icarus_livery_kit_0.0.2")
        self.assertIn("Invalid livery kit", self.verify().stderr)

    def test_livery_kit_rejects_placeholder_png_with_matching_checksum(self):
        entry = "examples/Icarus_livery_1.png"
        self.package(invalid_kit_png=entry)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{kit.kit_name(TAG[1:])}/{entry} is not a valid PNG", result.stderr)

    def test_livery_kit_rejects_png_whose_pixels_do_not_decode(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        # every chunk checksum is right, but the pixel stream holds one byte where a 1 by 1 RGB row needs four
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b""))
        entry = "examples/Icarus_livery_1.png"
        self.package(invalid_kit_png=entry, invalid_kit_data=png)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{kit.kit_name(TAG[1:])}/{entry} is not a valid PNG", result.stderr)

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

    def test_texture_sources_match_their_manifest(self):
        for name, mutate in (
            ("tampered", lambda e: e.update({"art/textures/generated/full/part.png": b"other"})),
            ("unpinned", lambda e: e.update({"art/textures/generated/extra.png": b"extra"})),
            ("outside", lambda e: e.update({"tools/Build-Icarus.ps1": b"script"})),
            ("missing", lambda e: e.pop("art/textures/generated/old.npz")),
            ("no manifest", lambda e: e.pop("texture-sources.json")),
        ):
            with self.subTest(name=name):
                self.package(sources=mutate)
                self.assertNotEqual(self.verify().returncode, 0)

    def painted_hashes(self, data):
        """A stand-in for faction_marks.py's record of the liveries it painted with the game's roundels."""
        path = self.root / "marks.json"
        path.write_text(json.dumps({"inputs": {}, "outputs": {"Icarus_livery_1.png": sha256(data)}}))
        return {**os.environ, "ICARUS_FACTION_MARKS_HASHES": str(path)}

    def test_texture_sources_reject_a_painted_livery(self):
        self.package(sources=lambda e: e.update({"art/textures/generated/full/painted.png": b"painted livery"}) or
                     e.update({"texture-sources.json": json.dumps({"files": {
                         path: sha256(data) for path, data in e.items() if path != "texture-sources.json"}}).encode()}))
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Game art in", result.stderr + result.stdout)

    def test_public_check_rejects_a_painted_livery_in_a_tracked_path(self):
        repo = self.root / "repo"
        (repo / "art").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        def check(name, data):
            (repo / "art" / name).write_bytes(data)
            subprocess.run(["git", "-C", str(repo), "add", "art/" + name], check=True)
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(REPO / "tools/Check-Public.ps1"), "-Repo", str(repo)],
                                    capture_output=True, text=True, env=self.env)
            subprocess.run(["git", "-C", str(repo), "rm", "-q", "--cached", "art/" + name], check=True)
            return result
        result = check("clean.png", b"logo-free")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = check("Icarus_livery_1.png", b"painted livery")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is the painted Icarus_livery_1.png", result.stdout)

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
        kit_asset = next(asset for asset in release["assets"] if asset["name"] == self.kit_name)
        kit_asset["digest"] = "sha256:" + "0" * 64
        self.assertIn("GitHub asset mismatch", verify_release().stderr)


if __name__ == "__main__":
    unittest.main()
