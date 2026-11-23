"""Checks of the SVG rendering.

Run from the repository root:
    python3 -m unittest discover -s provenance -v
"""

import unittest
import xml.dom.minidom
from pathlib import Path

from build_graph import build_run
from render import ancestors, render_graph
from runs import select_runs

RUNS = Path(__file__).resolve().parents[1] / "artifact" / "runs"
ANCHOR = "O:file:tests/test_expense_summary.py@v1"


class Render(unittest.TestCase):
    def test_every_run_renders_well_formed_svg(self):
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                graph, _ = build_run(run)
                document = xml.dom.minidom.parseString(render_graph(graph))
                self.assertEqual(document.documentElement.tagName, "svg")
                labels = [t.firstChild.data for t in document.getElementsByTagName("text") if t.firstChild]
                calls = [n for n in graph["nodes"] if n["kind"] == "call"]
                # Every call and every turn is drawn.
                for call in calls:
                    self.assertIn(f"C{call['index']}", labels)
                for turn in (n for n in graph["nodes"] if n["kind"] == "turn"):
                    self.assertIn(f"T{turn['index']}", labels)

    def test_backward_slice_of_run_006(self):
        graph, _ = build_run(RUNS / "run-006")
        kept = ancestors(graph, ANCHOR)
        self.assertEqual(len(kept) - 1, 41)
        self.assertIn("O:file:docs/project-notes.md@v0", kept)
        svg = render_graph(graph, ancestors_of=ANCHOR, highlight=["C:2", "C:12", ANCHOR])
        document = xml.dom.minidom.parseString(svg)
        labels = [t.firstChild.data for t in document.getElementsByTagName("text") if t.firstChild]
        self.assertIn("C12", labels)
        self.assertNotIn("C13", labels)          # issued after the anchor
        self.assertIn("docs/project-notes.md", labels)
        self.assertNotIn("outputs/report.md", labels)

    def test_unknown_nodes_are_rejected(self):
        graph, _ = build_run(RUNS / "run-001")
        with self.assertRaises(ValueError):
            render_graph(graph, ancestors_of="O:file:missing@v0")
        with self.assertRaises(ValueError):
            render_graph(graph, highlight=["C:999"])


if __name__ == "__main__":
    unittest.main()
