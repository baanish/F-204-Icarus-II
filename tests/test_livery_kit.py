"""Livery kit contract checks (tools/livery_kit.py). The built-kit checks run on build/icarus_livery_kit_<version>.zip
when tools/Build-LiveryKit.ps1 has made it, and the roundel checks when the local asset export is set."""

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import livery_kit as kit  # noqa: E402
from liveries import specifications  # noqa: E402

SPECS = specifications()
VERSION = kit.plugin_version()
TOP = kit.kit_name(VERSION)
BUILT = REPO / "build" / (TOP + ".zip")


def roundels_available():
    try:
        return all(path.is_file() for path in kit.faction_marks.roundel_paths(
            __import__("json").loads(kit.faction_marks.RECORD.read_text())).values())
    except (OSError, ValueError):
        return False


class LiveryKitContractTests(unittest.TestCase):
    def setUp(self):
        (REPO / ".cache").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=REPO / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_contract_lists_every_livery_and_its_layers(self):
        files = kit.expected_files(SPECS)
        self.assertEqual(len(SPECS), 7)
        for spec in SPECS:
            stem = f"Icarus_livery_{spec['id']}"
            for name in (f"examples/{stem}.png", f"template/layers/{stem}_base.png", f"template/layers/{stem}_markings.png"):
                self.assertIn(name, files)
            self.assertEqual(f"examples/{stem}_m.png" in files, spec["pattern"] == "bands")
        self.assertEqual(len(files), 4 + 3 + 7 * 3 + 2 + 6 + 2)
        self.assertEqual(files, sorted(set(files)))

    def stage(self, names, payloads=None):
        stage = self.root / "stage"
        payloads = payloads or {}
        for name in names:
            (stage / name).parent.mkdir(parents=True, exist_ok=True)
            (stage / name).write_bytes(payloads.get(name, name.encode()))
        return stage

    def test_zip_is_deterministic_and_held_to_the_contract(self):
        names = kit.expected_files(SPECS)
        png = io.BytesIO()
        Image.new("RGB", (1, 1)).save(png, format="PNG")
        payloads = {name: png.getvalue() for name in names if name.endswith(".png")}
        payloads.update({f"maps/{name}": (kit.EXPORT / name).read_bytes() for name in kit.SHARED_MAPS})
        payloads["install/IcarusLiveryBuilder.cs"] = (kit.DOCS / "IcarusLiveryBuilder.cs").read_bytes()
        payloads["install/meta.json"] = kit.meta_example().encode()
        stage = self.stage(names, payloads)
        first, second = self.root / "a.zip", self.root / "b.zip"
        kit.write_zip(stage, first, TOP)
        kit.write_zip(stage, second, TOP)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        kit.check_zip(first, TOP, SPECS)
        extra = self.root / "extra.zip"
        kit.write_zip(self.stage(["examples/stray.png"]), extra, TOP)
        with self.assertRaises(SystemExit):
            kit.check_zip(extra, TOP, SPECS)

    def test_panel_line_overlay_darkens_paint_as_compose_did(self):
        seam = np.array([[0, 1, .5, 0]], np.float64)
        fastener = np.array([[0, 0, .25, 1]], np.float64)
        used = np.ones_like(seam, bool)
        overlay = np.asarray(kit.panel_lines(seam, fastener, used), np.float64)
        colour = np.full((1, 4, 3), 200.0)
        over = colour * (1 - overlay[..., 3:] / 255)
        expected = colour * kit.shade(seam, fastener, "paint")[..., None]
        self.assertTrue(np.all(np.abs(over - expected) <= 1), (over, expected))
        self.assertEqual(overlay[0, :, 3].astype(int).tolist(), [0, 77, 48, 41])

    def test_local_paths_are_found(self):
        stage = self.stage(["model/clean.fbx"])
        (stage / "model/leak.fbx").write_bytes(b"\0" + str(REPO).encode() + b"\\x.png\0")
        self.assertEqual(kit.local_paths(stage, self.root), ["model/leak.fbx"])


class LiveryWorkshopTagTests(unittest.TestCase):
    """The plugin's Workshop tag (src/Icarus/LiveryWorkshopTag.cs) is the authored display name, as every stock
    aircraft's is, and passes what the game does with tags: Steam returns them comma-joined and the game splits on commas
    (SteamWorkshop.ParseTags), and its uploader caps a typed tag at 32 characters (UploadWorkshopPanel)."""

    def test_tag_is_the_display_name_and_a_valid_tag(self):
        import re
        tag = re.search(r'const string Tag = "([^"]+)"',
                        (REPO / "src/Icarus/LiveryWorkshopTag.cs").read_text(encoding="utf-8")).group(1)
        name = re.search(r'"unitName"\)\.stringValue = "([^"]+)"',
                         (REPO / "unity/Assets/Icarus/Editor/IcarusAuthor.Identity.cs").read_text(encoding="utf-8")).group(1)
        self.assertEqual(tag, name)
        self.assertNotIn(",", tag)
        self.assertEqual(tag, tag.strip())
        self.assertLessEqual(len(tag), 32)
        self.assertTrue(tag.isascii() and tag.isprintable())


@unittest.skipUnless(BUILT.is_file(), f"build/{TOP}.zip not built (tools/Build-LiveryKit.ps1)")
class BuiltLiveryKitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(BUILT)
        cls.addClassCleanup(cls.archive.close)

    def read(self, name):
        return self.archive.read(TOP + "/" + name)

    def test_contents_match_the_contract(self):
        kit.check_zip(BUILT, TOP, SPECS)

    def test_maps_are_atlas_sized(self):
        for name in kit.expected_files(SPECS):
            if name.endswith(".png"):
                with Image.open(io.BytesIO(self.read(name))) as image:
                    self.assertEqual(image.size, (kit.SIZE, kit.SIZE), name)

    def test_shared_maps_are_the_shipped_bytes(self):
        for name in kit.SHARED_MAPS:
            self.assertEqual(self.read("maps/" + name), (kit.EXPORT / name).read_bytes(), name)

    def test_text_has_no_dashes_and_meta_names_the_icarus(self):
        for name in ("README.md", "LICENSE.txt", "install/meta.json", "template/Icarus_parts.csv"):
            text = self.read(name).decode("utf-8")
            self.assertNotRegex(text, "[\u2013\u2014]", name)
        self.assertIn('"AircraftKey": "baanish_icarus"', self.read("install/meta.json").decode())

    @unittest.skipUnless(roundels_available(), "no local asset export: the roundels cannot be read")
    def test_examples_carry_roundels_and_base_maps_do_not(self):
        record = __import__("json").loads(kit.faction_marks.RECORD.read_text())
        with tempfile.TemporaryDirectory(dir=REPO / ".cache") as temp:
            for spec in SPECS:
                stem = f"Icarus_livery_{spec['id']}"
                for name, marked in ((f"examples/{stem}.png", True), (f"template/layers/{stem}_base.png", False)):
                    path = Path(temp) / Path(name).name
                    path.write_bytes(self.read(name))
                    scores = kit.logo_scores(path, record, spec["faction"])
                    if marked:
                        self.assertGreaterEqual(min(scores), kit.faction_marks.MARKED_MIN, name)
                    else:
                        self.assertLessEqual(max(scores, default=0), kit.faction_marks.CLEAN_MAX, name)


if __name__ == "__main__":
    unittest.main()
