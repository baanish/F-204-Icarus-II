"""Offline checks for frame-time aggregation and rejection of invalid comparisons."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("frame_gate", Path(__file__).resolve().parents[1] / "tools/frame_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class FrameGateTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        self.reader = patch.object(Path, "read_text", lambda path, **kwargs: self.files[path])
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def fixture(self, folder, value, verdict="MEASURED", hit=True, cap=1000):
        self.files[folder / "verdict.json"] = json.dumps({"verdict": verdict})
        events = [{"name": "missile_end", "result": "hit" if hit else "miss"}]
        events += [{"name": "frames", "label": p, "frames": 100, "p95_ms": value,
                    "vsync": 0, "fps_cap": cap} for p in gate.PHASES]
        self.files[folder / "trace.jsonl"] = "\n".join(json.dumps(e) for e in events)

    def test_medians_ratios_and_incremental_cost(self):
        entries = []
        for jet in gate.JETS:
            for count in (1, 8):
                for index, offset in enumerate((0, 1, 20)):
                    folder = gate.ROOT / ".cache/frame-gate-tests" / f"{jet}_{count}_{index}"
                    self.fixture(folder, (2 if jet == "baanish_icarus" else 1) * count + offset)
                    entries.append({"jet": jet, "count": count, "folder": str(folder)})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            gate.print_table(entries)
        self.assertIn("baanish_icarus | 8 | intact | 3 | 17.000 | 1.889 | 2.000", output.getvalue())
        self.assertIn("Fighter1 | 8 | debris | 3 | 9.000 | 1.000 | 1.000", output.getvalue())

    def test_failed_missed_or_capped_run_is_rejected(self):
        for index, options in enumerate(({"verdict": "FAIL"}, {"hit": False}, {"cap": 60})):
            folder = gate.ROOT / ".cache/frame-gate-tests" / str(index)
            self.fixture(folder, 3, **options)
            with self.assertRaises(ValueError):
                gate.frame_times(folder)

    def test_missing_phase_is_rejected(self):
        folder = gate.ROOT / ".cache/frame-gate-tests/run"
        self.fixture(folder, 3)
        trace = folder / "trace.jsonl"
        self.files[trace] = "\n".join(trace.read_text().splitlines()[:-1])
        with self.assertRaises(ValueError):
            gate.frame_times(folder)


if __name__ == "__main__":
    unittest.main()
