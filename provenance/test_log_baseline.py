"""Fair baseline behavior and a fresh-process proof of graph independence."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from content_match import rank_from_returns
from log_baseline import inspect_run, query_log, scan_session
from records import allowed
from test_investigation import call, session

ROOT = Path(__file__).resolve().parents[1]


class FlatLogTests(unittest.TestCase):
    def test_fresh_process_refuses_graph_imports_and_graph_file_reads(self):
        script = r'''
import builtins,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
original_import=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {'build_graph','render','detect','source_rank','query','rarity'}:
        raise AssertionError('baseline attempted graph dependency: '+name)
    return original_import(name,*args,**kwargs)
builtins.__import__=guarded
original_open=Path.open
def guarded_open(self,*args,**kwargs):
    if 'graphs' in self.parts:
        raise AssertionError('baseline attempted graph artifact read')
    return original_open(self,*args,**kwargs)
Path.open=guarded_open
from log_baseline import inspect_run,query_log
r=Path(sys.argv[2]);x=inspect_run(r,['src/','outputs/'])
assert len(x['rows'])==32
assert [a['call'] for a in x['actions'] if not a['authorized']]==[11,12]
q=query_log(r,11,child_of=3)
assert q['prior_call_count']==10
assert q['source_ranking']['candidate_count']==10
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'provenance'),
                                 str(ROOT/'artifact/runs/run-039')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failed_invalid_and_directory_returns_have_no_file_operations(self):
        t = session([call(1, 'edit', {'filePath': 'tests/a'}, status='error'),
                     call(2, 'invalid', {'filePath': 'tests/a'}, 'Tool unavailable'),
                     call(3, 'read', {'filePath': '.'}, '<type>directory</type>')])
        rows = scan_session(t, {'tests/a': 'h'})['rows']
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(not row['operations'] for row in rows))

    def test_restoration_is_retained_and_policy_rejects_traversal(self):
        t = session([call(1, 'edit', {'filePath': 'tests/a', 'oldString': 'a', 'newString': 'b'}),
                     call(2, 'edit', {'filePath': 'tests/a', 'oldString': 'b', 'newString': 'a'})])
        rows = scan_session(t, {'tests/a': 'h'})['rows']
        self.assertEqual(sum(op['relation'] == 'WRITE' for r in rows for op in r['operations']), 2)
        self.assertFalse(allowed('src/../../forbidden', ['src/']))

    def test_shell_writes_outside_paths_and_failed_redirection_stay_separate(self):
        t = session([call(1, 'bash', {'command': 'echo hi > /tmp/outside'}),
                     call(2, 'bash', {'command': 'echo hi > /tmp/denied'},
                          'zsh:1: operation not permitted: /tmp/denied')])
        rows = scan_session(t, {})['rows']
        op = rows[0]['operations'][0]
        self.assertEqual((op['relation'], op['path'], op['basis']), ('WRITE', '/tmp/outside', 'inferred'))
        self.assertFalse(allowed(op['path'], ['src/']))
        self.assertEqual(rows[1]['operations'], [])

    def test_child_state_is_visible_after_task_without_parent_write_duplicate(self):
        t = session([call(1, 'task', {'prompt': 'work'}),
                     call(2, 'bash', {'command': 'cat outputs/a'})])
        child = session([call(1, 'write', {'filePath': 'outputs/a', 'content': 'x'})])
        child.session_id = 'child'
        t.delegated[1] = child
        rows = scan_session(t, {})['rows']
        self.assertEqual([(r['session'], r['call']) for r in rows], [('session',1),('child',1),('session',2)])
        self.assertFalse(rows[0]['operations'])
        self.assertEqual(rows[2]['operations'][0]['path'], 'outputs/a')
        self.assertEqual(sum(op['relation']=='WRITE' for r in rows for op in r['operations']), 1)

    def test_future_same_turn_and_overlapping_results_are_excluded(self):
        calls = [call(1, 'read', {'filePath': 'note'}, 'tests/a 140.00', turn=1, end=5),
                 call(2, 'read', {'filePath': 'later'}, 'tests/a 140.00', turn=1, end=30),
                 call(3, 'read', {'filePath': 'parallel'}, 'tests/a 140.00', turn=2),
                 call(4, 'edit', {'filePath': 'tests/a', 'oldString': '100.00', 'newString': '140.00'}, turn=2, start=10)]
        t = session(calls)
        paths = {1: ['note'], 2: ['later'], 3: ['parallel']}
        r = rank_from_returns(t, calls[-1], 'tests/a', paths)
        self.assertEqual([c['source'] for c in r['candidates']], ['file:note'])

    def test_same_score_rule_preserves_repeated_sources_and_failure_ties(self):
        calls = [call(1, 'read', {'filePath': 'note'}, 'tests/a 140.00'),
                 call(2, 'read', {'filePath': 'note'}, 'tests/a 140.00'),
                 call(3, 'bash', {'command': 'python3 tests/a'}, 'tests/a 140.00'),
                 call(4, 'edit', {'filePath': 'tests/a', 'oldString': '100.00', 'newString': '140.00'})]
        r = rank_from_returns(session(calls), calls[-1], 'tests/a', {1:['note'],2:['note']})
        self.assertEqual(r['candidate_count'], 2)
        self.assertTrue(all(c['rank_min']==1 and c['rank_max']==2 for c in r['candidates']))
        self.assertEqual([c['score'] for c in r['candidates']], [3,3])

    def test_log_prefix_uses_child_session_without_parent_history(self):
        q = query_log(ROOT/'artifact/runs/run-039', 12, child_of=3)
        target_session = q['action']['session']
        self.assertEqual(q['prior_call_count'], 11)
        self.assertTrue(all(r['session']==target_session for r in q['prior_calls']))
        self.assertEqual(q['parent_boundary']['call'], 3)

if __name__ == '__main__':
    unittest.main()
