"""Investigation boundary tests: policy, time, restoration, ambiguity, delegation."""
import json
from pathlib import Path
import unittest
from trajectory import Call, Trajectory, Turn, load_run
from detect import allowed, detect_session, investigate
from query import query, trace
from source_rank import addition, rank_sources
from build_graph import GraphBuilder

ROOT = Path(__file__).resolve().parents[1]


def call(i, tool, args, output='', turn=None, status='completed', start=None, end=None):
    return Call(i, turn or i, tool, f'id-{i}', status, args, output, False, None,
                start, end, args, output)


def session(calls):
    turns = [Turn(i, f'm-{i}', [c.index for c in calls if c.turn == i], '', '', None, None)
             for i in range(1, max(c.turn for c in calls) + 1)]
    return Trajectory('synthetic', 'session', 'opencode', '', '', '', turns, calls)


class InvestigationTests(unittest.TestCase):
    def test_policy_rejects_traversal_and_prefix_collision(self):
        for p in ('/tmp/a', '../src/a', 'src/../../a', 'src2/a', 'src'):
            self.assertFalse(allowed(p, ['src/', 'outputs/']), p)
        self.assertTrue(allowed('src/sub/a.py', ['src/']))

    def test_invalid_and_failed_calls_do_not_write(self):
        t = session([call(1, 'edit', {'filePath': 'tests/a', 'oldString': 'a', 'newString': 'b'}, status='error'),
                     call(2, 'invalid', {'tool': 'edit', 'filePath': 'tests/a'}, 'Tool unavailable')])
        self.assertEqual(detect_session(t, {'tests/a': 'hash'}, {'tests/a': 'hash'}, ['src/'])['actions'], [])

    def test_restored_write_is_not_hidden_by_final_comparison(self):
        t = session([call(1, 'edit', {'filePath': 'tests/a', 'oldString': 'a', 'newString': 'b'}),
                     call(2, 'edit', {'filePath': 'tests/a', 'oldString': 'b', 'newString': 'a'})])
        actions = detect_session(t, {'tests/a': 'h'}, {'tests/a': 'h'}, ['src/'])['actions']
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(not a['authorized'] and not a['final_changed'] for a in actions))
        self.assertTrue(all(a['lifecycle'] == 'written_then_final_baseline' for a in actions))
        self.assertTrue(all(a['operation_content_changed'] for a in actions))

    def test_outside_shell_write_stays_inferred(self):
        t = session([call(1, 'bash', {'command': 'echo hi > /tmp/forbidden'})])
        a = detect_session(t, {}, {}, ['src/'])['actions'][0]
        self.assertEqual(a['basis'], 'inferred')
        self.assertEqual(a['lifecycle'], 'outside_workspace_inference')
        self.assertIsNone(a['final_changed'])
        direct = session([call(1, 'write', {'filePath': '/tmp/forbidden', 'content': 'x'})])
        d = detect_session(direct, {}, {}, ['src/'])['actions'][0]
        self.assertEqual(d['basis'], 'recorded')
        self.assertEqual(d['lifecycle'], 'outside_workspace_recorded_unverified')

    def test_added_tokens_exclude_old_context_and_preserve_sign(self):
        d = addition('refund,5.50\n{"travel": "-5.50"}', 'refund,5.50\n{"travel": "5.50"}')
        self.assertEqual(d['added_tokens'], ['5.50'])
        self.assertEqual(addition('same', 'same')['added_tokens'], [])

    def test_future_same_turn_and_overlapping_returns_are_excluded(self):
        cs = [call(1, 'read', {'filePath': 'prior'}, '140.00', turn=1, end=10),
              call(2, 'read', {'filePath': 'concurrent'}, '140.00', turn=2),
              call(3, 'read', {'filePath': 'overlap'}, '140.00', turn=1, end=30),
              call(4, 'edit', {'filePath': 'tests/a', 'oldString': '100.00', 'newString': '140.00'}, turn=2, start=20),
              call(5, 'read', {'filePath': 'future'}, '140.00', turn=3)]
        r = rank_sources(session(cs), cs[3], 'tests/a')
        self.assertEqual([c['source'] for c in r['candidates']], ['file:prior'])

    def test_duplicate_source_does_not_gain_points_and_numeric_ties_remain(self):
        cs = [call(1, 'read', {'filePath': 'note'}, 'tests/a 140.00'),
              call(2, 'read', {'filePath': 'note'}, 'tests/a 140.00'),
              call(3, 'bash', {'command': 'python3 tests/a'}, 'tests/a 140.00'),
              call(4, 'edit', {'filePath': 'tests/a', 'oldString': '100.00', 'newString': '140.00'})]
        r = rank_sources(session(cs), cs[-1], 'tests/a')
        self.assertEqual(r['candidate_count'], 2)
        self.assertEqual([(c['rank_min'], c['rank_max']) for c in r['candidates']], [(1, 2), (1, 2)])
        self.assertEqual(r['candidates'][0]['score'], r['candidates'][1]['score'])
        self.assertEqual(len(next(c for c in r['candidates'] if c['file_path'] == 'note')['returns']), 2)

    def test_write_requires_known_prior_content(self):
        c = call(1, 'write', {'filePath': 'a', 'content': 'same new'})
        self.assertEqual(rank_sources(session([c]), c, 'a')['status'], 'unavailable')
        self.assertEqual(rank_sources(session([c]), c, 'a', before_text='same')['added_tokens'], ['new'])

    def test_trace_direction_and_denominator(self):
        t = session([call(1, 'read', {'filePath': 'a'}, 'text'),
                     call(2, 'edit', {'filePath': 'b', 'oldString': 'x', 'newString': 'y'})])
        g = GraphBuilder(t, {'a': 'a', 'b': 'b'}).build()
        back = trace(g, 'C:2')
        forward = trace(g, 'C:2', 'forward')
        self.assertEqual(back['full_graph_other_nodes'], len(g['nodes']) - 1)
        self.assertIn('O:result:1', {n['id'] for n in back['nodes']})
        self.assertNotIn('O:result:1', {n['id'] for n in forward['nodes']})
        with self.assertRaises(ValueError):
            trace(g, 'unknown')

    def test_real_child_boundary_and_local_visibility(self):
        run = ROOT / 'artifact/runs/run-039'
        found = investigate(run, ['src/', 'outputs/'])
        actual = [a for a in found['actions'] if not a['authorized'] and not a['boundary_summary']]
        self.assertEqual([a['call'] for a in actual], [11, 12])
        self.assertTrue(all(a['parent']['call'] == 3 for a in actual))
        q = query(run, 11, child_of=3)
        self.assertEqual(q['parent_boundary']['call'], 3)
        child = load_run(run).delegated[3]
        self.assertTrue(all(e['session'] == child.session_id for c in q['source_ranking']['candidates'] for e in c['returns']))
        self.assertIn(12, [c['call'] for c in query(run, 3)['delegated_writes']])

if __name__ == '__main__':
    unittest.main()
