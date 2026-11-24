"""Render the retained D7 timelines and protected-write slices."""
import unittest
import xml.dom.minidom
from pathlib import Path
from build_graph import build_run
from render import ancestors,render_graph
from runs import select_runs
RUNS=Path(__file__).resolve().parents[1]/'artifact/runs'

class D7Render(unittest.TestCase):
    def test_all_D7_timelines_are_valid_and_include_calls_and_turns(self):
        for run in select_runs(RUNS).graph_runs:
            g,_=build_run(run)
            doc=xml.dom.minidom.parseString(render_graph(g))
            labels=[t.firstChild.data for t in doc.getElementsByTagName('text') if t.firstChild]
            for node in g['nodes']:
                if node['kind']=='call':self.assertIn(f"C{node['index']}",labels)
                if node['kind']=='turn':self.assertIn(f"T{node['index']}",labels)
    def test_slice_excludes_future_calls(self):
        g,_=build_run(RUNS/'run-031');anchor='O:file:tests/test_expense_summary.py@v1'
        kept=ancestors(g,anchor)
        self.assertIn('C:2',kept)
        self.assertIn('C:9',kept)
        self.assertNotIn('C:11',kept)
        xml.dom.minidom.parseString(render_graph(g,ancestors_of=anchor))
    def test_unknown_nodes_are_rejected(self):
        g,_=build_run(RUNS/'run-030')
        with self.assertRaises(ValueError):render_graph(g,ancestors_of='missing')
        with self.assertRaises(ValueError):render_graph(g,highlight=['C:999'])
if __name__=='__main__':unittest.main()
