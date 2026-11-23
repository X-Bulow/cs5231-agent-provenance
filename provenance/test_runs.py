"""Reviewed run selection must fail closed on missing or stale evidence."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runs import select_runs

ROOT = Path(__file__).resolve().parents[1]


class Selection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "artifact/runs"
        self.run = self.runs / "run-001"
        self.run.mkdir(parents=True)
        self.manifest = self.root / "manifest.json"
        self.row = {"run": "run-001", "valid_model_run": True,
                    "session_present": True, "evidence_sha256": {}}
        for name in ("execution.json", "baseline.json", "check.json", "session.json"):
            (self.run / name).write_text("{}")
        (self.run / "events.jsonl").write_text("")
        (self.run / "prompt.txt").write_text("task")
        self.save()

    def save(self):
        self.row["evidence_sha256"] = {
            p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.run.iterdir() if p.is_file()}
        self.manifest.write_text(json.dumps({"runs": [self.row]}))

    def test_current_inventory_selects_sixteen_and_preserves_failure_records(self):
        selection = select_runs(ROOT / "artifact/runs")
        self.assertEqual(len(selection.graph_runs), 16)
        self.assertEqual(set(selection.excluded), {"run-009", "run-010"})
        self.assertEqual(selection.ungraphable, {})

    def test_missing_expected_session_is_an_error(self):
        (self.run / "session.json").unlink()
        with self.assertRaisesRegex(ValueError, "required session"):
            select_runs(self.runs, self.manifest)

    def test_unreviewed_run_is_not_silently_included_or_skipped(self):
        (self.runs / "run-002").mkdir()
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            select_runs(self.runs, self.manifest)

    def test_stale_event_file_is_an_error(self):
        (self.run / "events.jsonl").write_text('{"type":"text"}\n')
        with self.assertRaisesRegex(ValueError, "stale"):
            select_runs(self.runs, self.manifest)

    def test_unknown_validity_needs_review(self):
        self.row["valid_model_run"] = None
        self.save()
        with self.assertRaisesRegex(ValueError, "unknown"):
            select_runs(self.runs, self.manifest)

    def test_valid_response_without_export_is_reported_separately(self):
        (self.run / "session.json").unlink()
        self.row["session_present"] = False
        self.save()
        selection = select_runs(self.runs, self.manifest)
        self.assertEqual(selection.graph_runs, [])
        self.assertEqual(set(selection.ungraphable), {"run-001"})
        self.assertEqual(selection.excluded, {})


if __name__ == "__main__":
    unittest.main()
