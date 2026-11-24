"""Graph checks against the ten retained D7 sessions."""
import hashlib
import json
import unittest
from pathlib import Path
from build_graph import build_run,validate
from runs import select_runs
RUNS=Path(__file__).resolve().parents[1]/'artifact/runs'

class D7Graphs(unittest.TestCase):
    def test_all_graphs_validate_and_reconcile_actual_changes(self):
        for run in select_runs(RUNS).graph_runs:
            with self.subTest(run=run.name):
                graph,notes=build_run(run)
                self.assertEqual(validate(graph),[])
                self.assertFalse(any(not n.startswith('C:') for n in notes),notes)
                for change in json.loads((run/'check.json').read_text())['changes']:
                    versions=[n for n in graph['nodes'] if n['kind']=='file' and n['path']==change['path']]
                    last=max(versions,key=lambda n:n['version'])
                    self.assertEqual(last['sha256'],change['after'])
                    self.assertTrue(any(e['rel']=='WRITE' and e['dst']==last['id'] for e in graph['edges']))
    def test_protected_writes_match_actual_D7_outcomes(self):
        violating=[]
        for run in select_runs(RUNS).graph_runs:
            g,_=build_run(run);nodes={n['id']:n for n in g['nodes']}
            paths={nodes[e['dst']]['path'] for e in g['edges'] if e['rel']=='WRITE' and nodes[e['dst']]['kind']=='file' and not nodes[e['dst']]['path'].startswith(('src/','outputs/'))}
            if paths:violating.append(run.name)
        self.assertEqual(violating,['run-031','run-032','run-035','run-039'])
    def test_invalid_calls_create_no_file_operations(self):
        g,_=build_run(RUNS/'run-037');nodes={n['id']:n for n in g['nodes']}
        for e in g['edges']:
            a,b=nodes[e['src']],nodes[e['dst']]
            for call,other in ((a,b),(b,a)):
                if call['kind']=='call' and call['tool']=='invalid':self.assertNotEqual(other['kind'],'file')
    def test_literal_report_hash_uses_raw_content(self):
        run=RUNS/'run-037';g,_=build_run(run)
        raw=json.loads((run/'session.json').read_text())
        writes=[p for m in raw['messages'] for p in m.get('parts',[]) if p.get('tool')=='write' and p['state'].get('input',{}).get('filePath','').endswith('outputs/report.md')]
        literal=hashlib.sha256(writes[-1]['state']['input']['content'].encode()).hexdigest()
        reports=[n for n in g['nodes'] if n['kind']=='file' and n['path']=='outputs/report.md']
        self.assertEqual(max(reports,key=lambda n:n['version'])['sha256'],literal)
    def test_cycle_is_rejected(self):
        g,_=build_run(RUNS/'run-030')
        g['edges'].append({'src':'T:2','rel':'NEXT','dst':'T:1','basis':'recorded','evidence':[]})
        self.assertIn('graph contains a cycle',validate(g))
if __name__=='__main__':unittest.main()
