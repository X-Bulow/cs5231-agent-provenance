"""Arrival boundaries and delegated writes checked against native evidence."""
import json
import tempfile
import unittest
from pathlib import Path

from trajectory import load_run
from build_graph import GraphBuilder,build_run,validate
from render import ancestors,render_graph

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'artifact/runs'

class Continuations(unittest.TestCase):
    def test_future_user_text_does_not_enter_initial_prompt_or_earlier_ancestry(self):
        run=RUNS/'run-030'
        raw=json.loads((run/'session.json').read_text())
        t=load_run(run);g,_=build_run(run)
        users=[m for m in raw['messages'] if m['info']['role']=='user']
        self.assertGreater(len(users),1)
        self.assertEqual(g['schema_version'],2)
        initial='\n'.join(p['text'] for p in users[0]['parts'] if p['type']=='text')
        self.assertEqual(t.user_messages[0].raw_text,initial)
        self.assertNotIn('Continue the original task',t.prompt)
        boundary=sum(m['info']['role']=='assistant' for m in raw['messages'][:raw['messages'].index(users[1])])+1
        n=next(n for n in g['nodes'] if n['id']=='O:user:2')
        self.assertEqual(n['before_turn'],boundary)
        targets=[e['dst'] for e in g['edges'] if e['src']=='O:user:2']
        self.assertEqual(targets,[f'T:{boundary}'])
        self.assertNotIn('O:user:2',ancestors(g,'C:1'))
        self.assertIn('O:user:2',ancestors(g,f'T:{boundary}'))
        self.assertIn('user 2',render_graph(g))

    def test_validator_rejects_early_user_edge(self):
        g,_=build_run(RUNS/'run-030')
        g['schema_version']=1
        self.assertTrue(any('requires schema version 2' in p for p in validate(g)))
        g['schema_version']=2
        e=next(e for e in g['edges'] if e['src']=='O:user:2')
        e['dst']='T:1'
        self.assertTrue(any('arrival boundary' in p for p in validate(g)))

    def test_two_continuations_and_trailing_message_keep_separate_arrivals(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'artifact/runs/run-100';run.mkdir(parents=True)
            messages=[]
            for role,text in [('user','INITIAL'),('assistant','one'),('user','SECOND'),('assistant','two'),('user','TRAILING')]:
                messages.append({'info':{'role':role,'id':f'm{len(messages)}'},'parts':[{'type':'text','text':text}]})
            (run/'session.json').write_text(json.dumps({'info':{'id':'s','directory':'/private/tmp/example/workspace'},'messages':messages}))
            t=load_run(run);g=GraphBuilder(t,{}).build()
            self.assertEqual(t.prompt,'INITIAL')
            self.assertEqual([u.before_turn for u in t.user_messages],[1,2,3])
            self.assertIn({'src':'O:user:2','rel':'READ','dst':'T:2','basis':'recorded','evidence':[]},g['edges'])
            self.assertFalse(any(e['src']=='O:user:3' for e in g['edges']))
            self.assertEqual(validate(g),[])

    def test_raw_short_paths_and_invalid_tool_returns_are_preserved(self):
        t=load_run(RUNS/'run-037')
        raw=json.loads((RUNS/'run-037/session.json').read_text())
        parts=[p for m in raw['messages'] for p in m['parts'] if p['type']=='tool']
        for call,p in zip(t.calls,parts):
            self.assertEqual(call.raw_input,p['state']['input'])
            self.assertEqual(call.raw_output,p['state'].get('output') or p['state'].get('error') or '')
        invalid=[c for c in t.calls if c.tool=='invalid']
        self.assertEqual([c.index for c in invalid],[5,10])
        self.assertTrue(all('unavailable' in c.output for c in invalid))

    def test_delegated_protected_write_is_backed_by_child_call_ids(self):
        t=load_run(RUNS/'run-039');g,notes=build_run(RUNS/'run-039')
        self.assertEqual(set(t.delegated),{3})
        self.assertEqual(g['schema_version'],2)
        child=t.delegated[3]
        writes=[c.index for c in child.calls if c.tool=='edit' and c.input.get('filePath')=='tests/test_expense_summary.py']
        self.assertEqual(writes,[11,12])
        edge=next(e for e in g['edges'] if e['src']=='C:3' and e['rel']=='WRITE' and e['dst']=='O:file:tests/test_expense_summary.py@v1')
        self.assertEqual(edge['rule'],'delegated-session')
        self.assertEqual(edge['child_call_evidence'],writes)
        self.assertEqual(edge['child_session_id'],child.session_id)
        self.assertEqual(validate(g),[])
        self.assertFalse(any('no call explains' in n for n in notes))

    def test_unreviewed_delegated_export_cannot_be_silently_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'artifact/runs/run-039';run.mkdir(parents=True)
            (run/'session.json').write_bytes((RUNS/'run-039/session.json').read_bytes())
            with self.assertRaisesRegex(ValueError,'needs reviewed native export'):
                load_run(run)

if __name__=='__main__':unittest.main()
