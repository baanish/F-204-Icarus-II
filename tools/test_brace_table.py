"""The export's clearance table names the same braces as the Unity author: art/blender/clearance.py BRACES against
IcarusAuthor.Parts.cs Braces. A brace missing from the export's table would make the carve hold a jointed pair a full
clearance apart. Reads both as text, so it runs without Blender: python -m pytest tools/test_brace_table.py
"""
import ast
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def export_braces():
    tree = ast.parse((REPO / "art/blender/clearance.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "BRACES" for t in n.targets))
    return {tuple(pair) for pair in ast.literal_eval(node.value)}


def author_braces():
    text = (REPO / "unity/Assets/Icarus/Editor/IcarusAuthor.Parts.cs").read_text(encoding="utf-8")
    root = re.search(r'RootPart = "(\w+)"', (REPO / "unity/Assets/Icarus/Editor/IcarusAuthor.cs").read_text(encoding="utf-8")).group(1)
    table = re.search(r"\)\[\] Braces =\s*\{(.*?)\};", text, re.S).group(1)
    pairs = re.findall(r'\(\s*"(\w+)",\s*("\w+"|RootPart),\s*"\w+",', table)
    return {(owner, root if to == "RootPart" else to.strip('"')) for owner, to in pairs}


class BraceTable(unittest.TestCase):
    def test_export_names_the_author_braces(self):
        author = author_braces()
        self.assertIn(("cockpit_cell", "fuselage_mid"), author)
        self.assertEqual(export_braces(), author)


if __name__ == "__main__":
    unittest.main()
