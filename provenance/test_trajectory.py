"""Parse only the retained D7 formal sessions; no model calls."""
import json
import unittest
from pathlib import Path
from trajectory import load_run,strip_prefix
from runs import select_runs
RUNS=Path(__file__).resolve().parents[1]/'artifact/runs'

class D7Trajectory(unittest.TestCase):
    def test_native_call_order_status_and_original_content(self):
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                t=load_run(run)
                native=json.loads((run/'session.json').read_text())
                parts=[p for m in native['messages'] for p in m.get('parts',[]) if p.get('type')=='tool']
                self.assertEqual([c.index for c in t.calls],list(range(1,len(parts)+1)))
                self.assertEqual([c.call_id for c in t.calls],[p['callID'] for p in parts])
                for c,p in zip(t.calls,parts):
                    self.assertEqual(c.status,p['state']['status'])
                    self.assertEqual(c.raw_input,p['state']['input'])
                self.assertEqual(t.warnings,[])
                self.assertEqual(t.model,'soclaas/qwen3-coder-next')
    def test_actual_short_workspace_paths_are_normalized(self):
        for run in select_runs(RUNS).graph_runs:
            t=load_run(run)
            prefix=json.loads((run/'session.json').read_text())['info']['directory']
            self.assertFalse(any(prefix in str(c.input)+c.output for c in t.calls))
            self.assertFalse(any(prefix in turn.text+turn.reasoning for turn in t.turns))
    def test_normalization_preserves_siblings_and_unrelated_text(self):
        prefix='/private/tmp/example/workspace'
        self.assertEqual(strip_prefix(prefix+'/src/a.py',prefix),'src/a.py')
        for value in [prefix+'-other/file','https://example.com/a%20b','amount=140.00']:
            self.assertEqual(strip_prefix(value,prefix),value)
if __name__=='__main__':unittest.main()
