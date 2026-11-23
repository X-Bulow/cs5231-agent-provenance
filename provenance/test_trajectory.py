"""Checks of the trajectory parser against the recorded runs.

Run from the repository root:
    python3 -m unittest discover -s provenance -v
"""

import unittest
import json
from collections import Counter
from pathlib import Path

from trajectory import load_run, strip_prefix
from runs import select_runs

RUNS = Path(__file__).resolve().parents[1] / "artifact" / "runs"


class Run006(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trajectory = load_run(RUNS / "run-006")

    def test_counts(self):
        t = self.trajectory
        self.assertEqual(len(t.turns), 37)
        self.assertEqual(len(t.calls), 37)
        self.assertEqual(Counter(c.status for c in t.calls), {"completed": 31, "error": 6})
        self.assertEqual(Counter(c.tool for c in t.calls),
                         {"bash": 17, "edit": 9, "read": 7, "glob": 2, "write": 2})

    def test_numbering_is_consistent(self):
        t = self.trajectory
        self.assertEqual([c.index for c in t.calls], list(range(1, len(t.calls) + 1)))
        self.assertEqual([n.index for n in t.turns], list(range(1, len(t.turns) + 1)))
        for turn in t.turns:
            for index in turn.calls:
                self.assertEqual(t.calls[index - 1].turn, turn.index)
        self.assertEqual(sorted(i for turn in t.turns for i in turn.calls),
                         [c.index for c in t.calls])

    def test_known_calls(self):
        calls = self.trajectory.calls
        self.assertEqual((calls[1].turn, calls[1].tool), (1, "read"))
        self.assertEqual(calls[1].input["filePath"], "docs/project-notes.md")
        self.assertEqual((calls[11].turn, calls[11].tool), (9, "edit"))
        self.assertEqual(calls[11].input["filePath"], "tests/test_expense_summary.py")
        self.assertEqual((calls[30].turn, calls[30].tool), (29, "bash"))
        self.assertIn("mv tests/test_expense_summary.py.fixed", calls[30].input["command"])

    def test_failed_call_keeps_error_text(self):
        failed = [c for c in self.trajectory.calls if c.status == "error"]
        self.assertTrue(all(c.output for c in failed))

    def test_prompt_and_no_warnings(self):
        t = self.trajectory
        # The prompt is kept verbatim; the CLI records it wrapped in quotes.
        self.assertTrue(t.prompt.startswith('"Use the Superpowers systematic-debugging skill'))
        self.assertEqual(len(t.prompt), 1522)
        self.assertEqual(t.warnings, [])
        self.assertEqual(t.model, "soclaas/qwen3.5:9b")


class Run001(unittest.TestCase):
    def test_same_turn_calls_keep_session_order(self):
        # Turn 3 issues a glob and a read together; events.jsonl logs the read
        # first because it finished first. Numbering follows session.json.
        t = load_run(RUNS / "run-001")
        self.assertEqual(t.turns[2].calls, [4, 5])
        self.assertEqual([t.calls[3].tool, t.calls[4].tool], ["glob", "read"])
        self.assertEqual(t.warnings, [])

    def test_counts(self):
        t = load_run(RUNS / "run-001")
        self.assertEqual(len(t.turns), 10)
        self.assertEqual(len(t.calls), 13)
        self.assertEqual(Counter(c.status for c in t.calls), {"completed": 13})
        self.assertEqual(Counter(c.tool for c in t.calls),
                         {"read": 6, "bash": 3, "glob": 1, "edit": 1, "write": 1, "invalid": 1})


class AllRuns(unittest.TestCase):
    def test_no_absolute_workspace_paths_remain(self):
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                t = load_run(run)
                marker = json.loads((run / "session.json").read_text())["info"]["directory"]
                texts = [t.prompt]
                texts += [turn.text + turn.reasoning for turn in t.turns]
                texts += [str(call.input) + call.output for call in t.calls]
                self.assertFalse(any(marker in text for text in texts))
                self.assertEqual(t.warnings, [])


class PrefixNormalization(unittest.TestCase):
    prefix = "/Users/example/NUS study/group project/run-012/workspace"

    def test_known_mixed_encoded_and_shell_escaped_prefixes(self):
        aliases = [self.prefix, self.prefix.replace(" ", "%20"),
                   self.prefix.replace("study/group ", "study/group%20"),
                   self.prefix.replace(" ", "\\ "),
                   self.prefix.replace(" ", "\\\\ "),
                   self.prefix.replace("NUS study", "'NUS\\ study'").replace("group project", "group\\ project")]
        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(strip_prefix(alias + "/src/a.py", self.prefix), "src/a.py")
                self.assertEqual(strip_prefix('cd "' + alias + '"', self.prefix), 'cd "."')

    def test_other_text_sibling_paths_and_variables_are_preserved(self):
        for text in ["https://example.com/a%20b", "keep tests/a%20b.py and 140.00",
                     self.prefix + "-other/file", "$HOME/NUS study/group project/run-012/workspace",
                     "project/run-012/workspace/data/a.csv: No such file"]:
            self.assertEqual(strip_prefix(text, self.prefix), text)

    def test_failed_encoded_path_stays_failed_and_raw_input_is_retained(self):
        t = load_run(RUNS / "run-012")
        self.assertEqual(t.calls[0].status, "error")
        self.assertIn("NUS%20study", t.calls[0].raw_input["command"])
        self.assertNotIn("NUS%20study", t.calls[0].input["command"])

    def test_malformed_path_is_reported_not_repaired(self):
        t = load_run(RUNS / "run-015")
        self.assertIn("NUS%20study", t.calls[7].input["command"])
        self.assertTrue(any(note.startswith("C:8:") for note in t.normalization_notes))


if __name__ == "__main__":
    unittest.main()
