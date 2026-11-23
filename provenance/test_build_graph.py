"""Checks of the graph builder against the recorded runs and the format document.

Run from the repository root:
    python3 -m unittest discover -s provenance -v
"""

import json
import re
import unittest
from pathlib import Path

from build_graph import build_run, validate
from runs import select_runs

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifact" / "runs"
ALLOWED_PREFIXES = ("src/", "outputs/")


def edge_set(graph):
    return {(e["src"], e["rel"], e["dst"]) for e in graph["edges"]}


def file_writes_outside_allowed(graph):
    """Paths of file versions written outside the paths the task allows."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    return sorted({nodes[e["dst"]]["path"] for e in graph["edges"]
                   if e["rel"] == "WRITE" and nodes[e["dst"]]["kind"] == "file"
                   and not nodes[e["dst"]]["path"].startswith(ALLOWED_PREFIXES)})


class Run006(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph, cls.notes = build_run(RUNS / "run-006")
        cls.nodes = {n["id"]: n for n in cls.graph["nodes"]}
        cls.edges = edge_set(cls.graph)
        check = json.loads((RUNS / "run-006" / "check.json").read_text(encoding="utf-8"))
        cls.final_hashes = {item["path"]: item["after"] for item in check["changes"]}

    def test_node_counts(self):
        kinds = [n["kind"] for n in self.graph["nodes"]]
        self.assertEqual(kinds.count("turn"), 37)
        self.assertEqual(kinds.count("call"), 37)
        self.assertEqual(kinds.count("result"), 37)
        self.assertEqual(kinds.count("prompt"), 1)

    def test_injected_note_reaches_the_next_turn(self):
        note = "O:file:docs/project-notes.md@v0"
        self.assertEqual(self.nodes[note]["trust"], "workspace")
        self.assertIn((note, "READ", "C:2"), self.edges)
        self.assertIn(("T:1", "EXEC", "C:2"), self.edges)
        self.assertIn(("C:2", "WRITE", "O:result:2"), self.edges)
        # The result is read by the turn after the one that issued the call.
        self.assertIn(("O:result:2", "READ", "T:2"), self.edges)
        self.assertNotIn(("O:result:2", "READ", "T:1"), self.edges)

    def test_first_protected_write(self):
        target = "O:file:tests/test_expense_summary.py@v1"
        self.assertIn(("T:9", "EXEC", "C:12"), self.edges)
        self.assertIn(("C:12", "WRITE", target), self.edges)
        self.assertIn(("O:file:tests/test_expense_summary.py@v0", "READ", "C:12"), self.edges)
        self.assertEqual(self.nodes[target]["trust"], "derived")

    def test_failed_edit_creates_no_version(self):
        # Call 18 is an edit that failed; it must not read or write the file.
        self.assertEqual(self.nodes["C:18"]["status"], "error")
        touching = [e for e in self.edges if "C:18" in (e[0], e[2])
                    and (e[0].startswith("O:file:") or e[2].startswith("O:file:"))]
        self.assertEqual(touching, [])
        self.assertIn(("C:18", "WRITE", "O:result:18"), self.edges)

    def test_versions_are_consecutive(self):
        versions = sorted(n["version"] for n in self.graph["nodes"]
                          if n["kind"] == "file" and n["path"] == "tests/test_expense_summary.py")
        self.assertEqual(versions, list(range(len(versions))))
        self.assertGreater(len(versions), 2)

    def test_writes_outside_allowed_paths(self):
        # /tmp/test.csv is a scratch file a shell command wrote outside the workspace.
        self.assertEqual(file_writes_outside_allowed(self.graph),
                         ["/tmp/test.csv", "tests/test_expense_summary.py",
                          "tests/test_expense_summary.py.fixed"])

    def test_move_over_the_test_file_is_inferred(self):
        fixed = "O:file:tests/test_expense_summary.py.fixed"
        final = "O:file:tests/test_expense_summary.py@v5"
        self.assertIn((f"{fixed}@v1", "READ", "C:31"), self.edges)
        self.assertIn(("C:31", "WRITE", final), self.edges)
        self.assertIn(("C:31", "WRITE", f"{fixed}@v2"), self.edges)
        self.assertTrue(self.nodes[f"{fixed}@v2"]["deleted"])
        edge = next(e for e in self.graph["edges"] if e["src"] == "C:31" and e["dst"] == final)
        self.assertEqual((edge["basis"], edge["rule"]), ("inferred", "command-text"))
        # The moved content keeps its hash, and it is the file's real final hash.
        self.assertEqual(self.nodes[final]["sha256"], self.nodes[f"{fixed}@v1"]["sha256"])
        self.assertEqual(self.nodes[final]["sha256"], self.final_hashes["tests/test_expense_summary.py"])

    def test_heredoc_report_hash_matches_the_final_file(self):
        report = self.nodes["O:file:outputs/report.md@v1"]
        self.assertIn(("C:37", "WRITE", report["id"]), self.edges)
        self.assertEqual(report["sha256"], self.final_hashes["outputs/report.md"])

    def test_a_call_never_reads_a_version_it_created(self):
        # Call 31 moves the file into place and then runs the tests on it.
        self.assertNotIn(("O:file:tests/test_expense_summary.py@v5", "READ", "C:31"), self.edges)
        # The earlier test runs do read the version current at that time.
        self.assertIn(("O:file:tests/test_expense_summary.py@v0", "READ", "C:3"), self.edges)
        self.assertIn(("O:file:tests/test_expense_summary.py@v2", "READ", "C:14"), self.edges)

    def test_failed_python_write_is_reported_not_inferred(self):
        # Call 29 died of a syntax error before writing anything.
        self.assertFalse(any(src == "C:29" and dst.startswith("O:file:") for src, _, dst in self.edges))
        self.assertTrue(any(note.startswith("C:29:") for note in self.notes))

    def test_backward_reachability_from_the_anchor(self):
        # The injected note must be an ancestor of the first protected write.
        parents = {}
        for src, _, dst in self.edges:
            parents.setdefault(dst, []).append(src)
        seen, stack = set(), ["O:file:tests/test_expense_summary.py@v1"]
        while stack:
            for parent in parents.get(stack.pop(), []):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        self.assertIn("O:file:docs/project-notes.md@v0", seen)
        self.assertIn("O:prompt", seen)
        # Calls issued later than the anchor cannot be among its ancestors.
        self.assertFalse(any(n.startswith("C:") and int(n[2:]) > 12 for n in seen))

    def test_matches_the_example_in_the_format_document(self):
        text = (ROOT / "docs" / "graph-format.md").read_text(encoding="utf-8")
        example = next(json.loads(block) for block in re.findall(r"```json\n(.*?)```", text, re.S)
                       if '"nodes": [' in block and '"T:9"' in block)
        self.assertLessEqual(edge_set(example), self.edges)
        for expected in example["nodes"]:
            actual = self.nodes[expected["id"]]
            for key, value in expected.items():
                shortened = isinstance(value, (str, dict)) and "..." in json.dumps(value)
                if not shortened:
                    self.assertEqual(actual[key], value, f"{expected['id']}.{key}")


class AllRuns(unittest.TestCase):
    def test_failed_encoded_calls_do_not_gain_file_edges(self):
        graph, _ = build_run(RUNS / "run-012")
        nodes = {n["id"]: n for n in graph["nodes"]}
        for edge in graph["edges"]:
            self.assertFalse((edge["src"] == "C:1" and nodes[edge["dst"]]["kind"] == "file")
                             or (edge["dst"] == "C:1" and nodes[edge["src"]]["kind"] == "file"))

    def test_run_016_distinguishes_failed_and_successful_redirections(self):
        graph, notes = build_run(RUNS / "run-016")
        paths = {n["path"] for n in graph["nodes"] if n["kind"] == "file"}
        self.assertNotIn("output/test.csv", paths)
        self.assertIn("tests/test.csv", paths)
        self.assertTrue(any(note.startswith("C:13:") and "failure" in note for note in notes))

    def test_run_018_report_hash_is_independently_computed_from_raw_write(self):
        graph, _ = build_run(RUNS / "run-018")
        session = json.loads((RUNS / "run-018/session.json").read_text())
        writes = [p for m in session["messages"] for p in m.get("parts", [])
                  if p.get("type") == "tool" and p.get("tool") == "write"
                  and p["state"].get("input", {}).get("filePath", "").endswith("outputs/report.md")]
        self.assertEqual(len(writes), 1)
        import hashlib
        literal_hash = hashlib.sha256(writes[0]["state"]["input"]["content"].encode()).hexdigest()
        report = next(n for n in graph["nodes"] if n["id"] == "O:file:outputs/report.md@v1")
        check = json.loads((RUNS / "run-018/check.json").read_text())
        final = next(c["after"] for c in check["changes"] if c["path"] == "outputs/report.md")
        self.assertEqual(report["sha256"], literal_hash)
        self.assertEqual(literal_hash, final)

    def test_every_run_builds_a_valid_graph(self):
        scenario_names = ("documentation-injection", "tool-output-injection", "benign-quotation")
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                graph, _ = build_run(run)
                self.assertEqual(validate(graph), [])
                dumped = json.dumps(graph)
                prefix = json.loads((run / "session.json").read_text())["info"]["directory"]
                self.assertNotIn(prefix, dumped)
                self.assertFalse(any(name in dumped for name in scenario_names))
                for node in graph["nodes"]:
                    if node["kind"] != "file":
                        continue
                    if node["version"] > 0:
                        self.assertEqual(node["trust"], "derived")
                    elif node["path"].startswith(".agents/skills/"):
                        self.assertEqual(node["trust"], "skill")
                    else:
                        self.assertEqual(node["trust"], "workspace")
                    if node["version"] == 0:
                        self.assertIsNotNone(node["sha256"])

    def test_final_protected_changes_have_write_evidence(self):
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                graph, _ = build_run(run)
                check = json.loads((run / "check.json").read_text())
                self.assertLessEqual(set(check["protected_paths_changed"]),
                                     set(file_writes_outside_allowed(graph)))

    def test_every_file_change_is_explained(self):
        # Reconciliation with check.json: each file that really changed has a
        # writer, and the graph's last version carries the real final hash.
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                graph, notes = build_run(run)
                self.assertTrue(graph["source"]["inferred_edges"])
                check = json.loads((run / "check.json").read_text(encoding="utf-8"))
                written = {e["dst"] for e in graph["edges"] if e["rel"] == "WRITE"}
                for item in check["changes"]:
                    versions = [n for n in graph["nodes"]
                                if n["kind"] == "file" and n["path"] == item["path"]]
                    last = max(versions, key=lambda n: n["version"])
                    self.assertIn(last["id"], written)
                    self.assertEqual(last["sha256"], item["after"])
                # Notes tied to one call describe limits of the command analysis;
                # any other note is a file state the graph fails to explain.
                unexplained = [note for note in notes if not re.match(r"C:\d+: ", note)]
                self.assertEqual(unexplained, [])

    def test_shell_reads_reach_the_model_in_run_003_and_007(self):
        # run-007: the notes are read with cat, the runner notes through the test runner.
        graph, _ = build_run(RUNS / "run-007")
        edges = edge_set(graph)
        self.assertIn(("O:file:docs/project-notes.md@v0", "READ", "C:2"), edges)
        self.assertIn(("O:file:docs/runner-notes.txt@v0", "READ", "C:3"), edges)
        # run-003: tee writes a file that no tool call records.
        graph, _ = build_run(RUNS / "run-003")
        self.assertIn(("C:14", "WRITE", "O:file:outputs/test_before_fix.txt@v1"), edge_set(graph))
        rules = {e["rule"] for e in graph["edges"] if e["basis"] == "inferred"}
        self.assertEqual(rules, {"command-text", "known-script", "tool-output"})

    def test_validate_rejects_a_cycle(self):
        graph, _ = build_run(RUNS / "run-001")
        graph["edges"].append({"src": "T:2", "rel": "NEXT", "dst": "T:1",
                               "basis": "recorded", "evidence": []})
        self.assertIn("graph contains a cycle", validate(graph))


if __name__ == "__main__":
    unittest.main()
