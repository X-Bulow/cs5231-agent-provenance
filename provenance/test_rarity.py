"""Rarity correctness, held-out boundaries and counterexamples; no model calls."""
import math
from pathlib import Path
import unittest
from rarity import extract_events, fit_reference, load_events, score_events, signature
from test_investigation import call, session

ROOT = Path(__file__).resolve().parents[1]


def sample(tool='read', path='docs/a', index=1):
    return extract_events(session([call(index, tool, {'filePath': path}, 'content')]), {path: 'hash'})


class RarityTests(unittest.TestCase):
    def test_run_presence_not_operation_frequency(self):
        events = sample()
        r = fit_reference([('a', events * 10), ('b', [])])
        s = r.score(signature('read', 'READ', 'docs/a'))
        self.assertEqual(s['reference_support'], 1)
        self.assertEqual(s['reference_runs'], 2)
        self.assertEqual(s['smoothed_probability'], 0.5)
        self.assertEqual(s['rarity_bits'], 1)
        self.assertEqual(s['supporting_runs'], ['a'])

    def test_unseen_path_and_tool_have_finite_equal_maximum(self):
        r = fit_reference([(str(i), sample()) for i in range(5)])
        for key in (signature('read', 'READ', 'unseen'), signature('edit', 'CALL')):
            s = r.score(key)
            self.assertEqual(s['reference_support'], 0)
            self.assertAlmostEqual(s['rarity_bits'], math.log2(7))
            self.assertTrue(math.isfinite(s['rarity_bits']))
        self.assertAlmostEqual(r.score(signature('read', 'CALL'))['rarity_bits'], math.log2(7/6))

    def test_tools_and_relations_are_distinct(self):
        r = fit_reference([('a', sample())])
        self.assertEqual(r.score(signature('read', 'READ', 'docs/a'))['reference_support'], 1)
        self.assertEqual(r.score(signature('bash', 'READ', 'docs/a'))['reference_support'], 0)
        self.assertEqual(r.score(signature('read', 'WRITE', 'docs/a'))['reference_support'], 0)
        deletion = extract_events(session([call(1, 'bash', {'command': 'rm docs/a'})]), {'docs/a': 'h'})
        f = next(f for f in deletion[0]['features'] if f['relation'] == 'DELETE')
        self.assertEqual(f['basis'], 'inferred')
        self.assertEqual(f['path'], 'docs/a')

    def test_normalization_removes_node_and_version_dependence(self):
        a = sample(path='docs/../docs/a')
        b = sample(path='docs/a', index=4)
        r = fit_reference([('a', a), ('b', b)])
        self.assertEqual(r.score(signature('read', 'READ', 'docs/a'))['reference_support'], 2)

    def test_failed_invalid_have_no_successful_file_features(self):
        t = session([call(1, 'edit', {'filePath': 'tests/a', 'oldString': 'x', 'newString': 'y'}, status='error'),
                     call(2, 'invalid', {'filePath': 'tests/a'}, 'Unavailable tool')])
        events = extract_events(t, {'tests/a': 'hash'})
        self.assertTrue(all([f['relation'] for f in e['features']] == ['CALL'] for e in events))

    def test_empty_file_neighborhood_has_null_file_score(self):
        events = extract_events(session([call(1, 'bash', {'command': 'pwd'}, '.')]), {})
        row = score_events(events, fit_reference([('r', [])]))[0]
        self.assertIsNone(row['max_file_rarity_bits'])
        self.assertEqual(row['max_rarity_bits'], row['call_rarity_bits'])
        self.assertEqual(score_events([], fit_reference([('r', [])])), [])

    def test_reference_requires_nonempty_distinct_run_ids(self):
        with self.assertRaises(ValueError):
            fit_reference([])
        with self.assertRaises(ValueError):
            fit_reference([('same', []), ('same', [])])

    def test_delegation_summary_excluded_child_is_same_statistical_run(self):
        t = session([call(1, 'task', {'prompt': 'work'}, 'done')])
        child = session([call(1, 'edit', {'filePath': 'tests/a', 'oldString': 'x', 'newString': 'y'}),
                         call(2, 'edit', {'filePath': 'tests/a', 'oldString': 'y', 'newString': 'z'})])
        child.session_id = 'child'
        t.delegated[1] = child
        events = extract_events(t, {'tests/a': 'h'})
        self.assertEqual(len(events), 3)
        parent = events[0]
        self.assertEqual([f['relation'] for f in parent['features']], ['CALL'])
        self.assertTrue(parent['excluded_delegation_file_summaries'])
        r = fit_reference([('one-run', events)])
        self.assertEqual(r.score(signature('edit', 'WRITE', 'tests/a'))['reference_support'], 1)
        self.assertEqual(len(r.run_ids), 1)
        self.assertTrue(all(e['parent']['call'] == 1 for e in events[1:]))

    def test_equal_scores_are_ties_repetition_does_not_sum(self):
        events = sample()
        r = fit_reference([('reference', events)])
        scored = score_events(events * 3, r)
        self.assertEqual([(e['rank_min'], e['rank_max']) for e in scored], [(1, 3)] * 3)
        self.assertTrue(all(e['max_rarity_bits'] == scored[0]['max_rarity_bits'] for e in scored))

    def test_larger_candidate_universe_does_not_change_bernoulli_denominator(self):
        events = sample()
        r1 = fit_reference([('a', events)])
        r2 = fit_reference([('a', events + sample(path='another'))])
        key = signature('read', 'READ', 'docs/a')
        self.assertEqual(r1.score(key), r2.score(key))

    def test_heldout_reference_does_not_include_target(self):
        a, b = sample(path='only-a'), sample(path='only-b')
        ref = fit_reference([('b', b)])
        rows = score_events(a, ref)
        self.assertNotIn('a', ref.run_ids)
        self.assertEqual(next(s for s in rows[0]['signature_scores'] if s['relation'] == 'READ')['reference_support'], 0)

    def test_real_039_task_and_child_writes_stay_distinct(self):
        events = load_events(ROOT / 'artifact/runs/run-039')
        parent = next(e for e in events if e['tool'] == 'task')
        self.assertEqual([f['relation'] for f in parent['features']], ['CALL'])
        writes = [e for e in events if any(f['relation'] == 'WRITE' and f['path'].startswith('tests/') for f in e['features'])]
        self.assertEqual([e['call'] for e in writes], [11, 12])
        self.assertTrue(all(e['parent']['call'] == 3 for e in writes))

if __name__ == '__main__':
    unittest.main()
