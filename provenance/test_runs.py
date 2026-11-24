"""Reviewed run selection must fail closed on missing or stale evidence."""
import hashlib
import json
import tempfile
import unittest
import sys
from pathlib import Path

from runs import select_runs

ROOT = Path(__file__).resolve().parents[1]


class Selection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "artifact/runs"
        self.run = self.runs / "run-030"
        self.run.mkdir(parents=True)
        self.manifest = self.root / "manifest.json"
        self.row = {"run": "run-030", "valid_model_run": True,
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

    def test_current_inventory_selects_only_ten_D7_runs(self):
        selection = select_runs(ROOT / "artifact/runs")
        self.assertEqual({p.name for p in selection.graph_runs}, {f'run-{n:03d}' for n in range(30,40)})
        self.assertEqual(selection.excluded, {})
        self.assertEqual(selection.ungraphable, {})

    def test_D7_launcher_refuses_existing_formal_run_before_launch(self):
        sys.path.insert(0,str(ROOT/'experiments'))
        from v2_batch import run_one
        with self.assertRaisesRegex(ValueError,'never relaunch or overwrite'):
            run_one('run-030','normal')

    def test_D7_profile_uses_current_home_and_checkout(self):
        sys.path.insert(0,str(ROOT/'experiments'))
        from v2_batch import sandbox_profile, RUNTIME
        workspace=Path('/private/tmp/d7-profile-test/workspace')
        profile=sandbox_profile(workspace)
        self.assertIn('(subpath '+json.dumps(str(workspace))+')',profile)
        self.assertIn('(subpath '+json.dumps(str(RUNTIME))+')',profile)
        self.assertIn('(subpath '+json.dumps(str(Path.home()))+')',profile)
        self.assertNotIn('__',profile)
        self.assertIn('(deny file-write*',profile)
        self.assertIn('(deny file-read-data',profile)

    def test_missing_expected_session_is_an_error(self):
        (self.run / "session.json").unlink()
        with self.assertRaisesRegex(ValueError, "required session"):
            select_runs(self.runs, self.manifest)

    def test_unreviewed_run_is_not_silently_included_or_skipped(self):
        (self.runs / "run-031").mkdir()
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
        self.assertEqual(set(selection.ungraphable), {"run-030"})
        self.assertEqual(selection.excluded, {})

    def test_stale_supplemental_native_session_is_rejected(self):
        extra=self.root/'child.json';extra.write_text('{}')
        expected=hashlib.sha256(extra.read_bytes()).hexdigest()
        self.row['supporting_evidence']={'child.json':expected}
        self.save()
        data=json.loads(self.manifest.read_text());data['runs'][0]['evidence_sha256']['child.json']=expected
        self.manifest.write_text(json.dumps(data))
        extra.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'supplemental'):
            select_runs(self.runs,self.manifest)


if __name__ == "__main__":
    unittest.main()
