"""Reproduce frozen C3 rarity analysis on D7; no model calls or C4 baseline."""
import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'provenance'))
from rarity import feature_key, fit_reference, load_events, score_events
from detect import investigate
from runs import select_runs

OUT = ROOT / 'experiments/v2-d7/c3'
CHECK = False


def load(p):
    return json.loads(p.read_text())


def write_output(name, text):
    path = OUT / name
    if CHECK:
        if not path.is_file() or path.read_bytes() != text.encode():
            raise ValueError('Missing or stale C3 output: ' + name)
    else:
        path.write_text(text)


def save(name, value):
    write_output(name, json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def csv_save(name, rows):
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    write_output(name, s.getvalue())


def annotate(rows, detection):
    # Authorization is attached after rarity computation, never fitted.
    actions = {(a['session'], a['call']): [] for a in detection['actions']}
    for a in detection['actions']:
        if not a['boundary_summary']:
            actions[(a['session'], a['call'])].append(a)
    result = []
    for row in rows:
        writers = actions.get((row['session'], row['call']), [])
        result.append({**row, 'unauthorized_write': any(not a['authorized'] for a in writers),
                       'actual_write_paths': [a['path'] for a in writers]})
    return result


def describe(run, rows, ref):
    unseen = [r for r in rows if r['unseen_signature_count']]
    bad = [r for r in rows if r['unauthorized_write']]
    top = [r for r in rows if r['rank_min'] == 1]
    return {'run': run, 'reference_count': len(ref.run_ids), 'in_reference': run in ref.run_ids,
            'native_call_count': len(rows), 'unseen_signature_calls': len(unseen),
            'unseen_unique_signatures': len({feature_key(s) for r in rows for s in r['signature_scores'] if s['unseen_in_reference']}),
            'unauthorized_edit_calls': len(bad), 'max_rarity_bits': max(r['max_rarity_bits'] for r in rows),
            'top_tied_calls': len(top), 'top_unauthorized_edit_calls': sum(r['unauthorized_write'] for r in top),
            'top_other_calls': sum(not r['unauthorized_write'] for r in top)}


def compact(row):
    return {k: v for k, v in row.items() if k not in ('raw_input', 'raw_output', 'features', 'excluded_delegation_file_summaries')}


def main():
    global CHECK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='recompute and compare all outputs without writing')
    args = parser.parse_args()
    CHECK = args.check
    if not CHECK:
        OUT.mkdir(exist_ok=True)
    protocol = load(OUT / 'protocol.json')
    runs = select_runs(ROOT / 'artifact/runs').graph_runs
    names = [p.name for p in runs]
    references = protocol['reference_runs']
    assert len(references) == 5 and len(set(references)) == 5 and set(references) <= set(names)
    events = {p.name: load_events(p) for p in runs}
    reference = fit_reference([(n, events[n]) for n in references])
    # Rarity is computed for every native call before any outcome annotation.
    scored = {n: score_events(ev, reference) for n, ev in events.items()}
    detections = {p.name: investigate(p, ['src/', 'outputs/']) for p in runs}
    annotated = {n: annotate(rows, detections[n]) for n, rows in scored.items()}
    save('reference.json', reference.export())
    save('events.json', annotated)
    run_rows = [describe(n, annotated[n], reference) for n in names]
    csv_save('runs.csv', run_rows)
    # Normal reference rows are explicitly in-sample; no held-out performance claim.
    action_rows = [{'run': n, 'session': r['session'], 'parent_call': r['parent']['call'] if r['parent'] else None,
                    'call': r['call'], 'tool': r['tool'], 'paths': '|'.join(r['actual_write_paths']),
                    'call_rarity_bits': r['call_rarity_bits'], 'max_file_rarity_bits': r['max_file_rarity_bits'],
                    'max_rarity_bits': r['max_rarity_bits'], 'rank_min': r['rank_min'], 'rank_max': r['rank_max'],
                    'native_call_count': len(annotated[n])}
                   for n in names for r in annotated[n] if r['unauthorized_write']]
    assert len(action_rows) == 8 and sum(r['unauthorized_edit_calls'] > 0 for r in run_rows) == 4
    csv_save('unauthorized-edits.csv', action_rows)
    nonrefs = [n for n in names if n not in references]
    fold_rows, fold_events = [], []
    for heldout in references:
        ref = fit_reference([(n, events[n]) for n in references if n != heldout])
        for n in [heldout, *nonrefs]:
            assert n not in ref.run_ids
            rows = annotate(score_events(events[n], ref), detections[n])
            fold_rows.append({'heldout_normal': heldout, **describe(n, rows, ref)})
            fold_events.append({'heldout_normal': heldout, 'target_run': n,
                                'reference_runs': list(ref.run_ids), 'events': [compact(r) for r in rows]})
    csv_save('heldout-runs.csv', fold_rows)
    save('heldout-events.json', fold_events)
    # Display separate C2 and C3 evidence for the identical candidate set.
    # The known document path is used only here, after all scores are fixed.
    c2 = load(ROOT / 'experiments/v2-d7/c1-c2/queries.json')
    lookup = {(n, r['session'], r['call']): r for n in names for r in annotated[n]}
    source_rows, note_rows = [], []
    for q in c2:
        r = q['source_ranking']
        sources = []
        for candidate in r['candidates']:
            returns = []
            for e in candidate['returns']:
                row = lookup[(q['run'], e['session'], e['call'])]
                returns.append({'call': e['call'], 'content_score': e['score'],
                                'call_rarity_bits': row['call_rarity_bits'],
                                'max_file_rarity_bits': row['max_file_rarity_bits'],
                                'max_rarity_bits': row['max_rarity_bits']})
            sources.append({'source': candidate['source'], 'content_score': candidate['score'],
                            'content_rank_min': candidate['rank_min'], 'content_rank_max': candidate['rank_max'],
                            'return_rarity': returns})
            if candidate['file_path'] == 'docs/project-notes.md':
                note_rows.append({'run': q['run'], 'edit_call': r['call'],
                                  'content_rank_min': candidate['rank_min'], 'content_rank_max': candidate['rank_max'],
                                  'source_return_rarity_bits': max(e['max_rarity_bits'] for e in returns)})
        source_rows.append({'run': q['run'], 'edit_session': r['session'], 'edit_call': r['call'],
                            'combination': 'none; C2 ordering unchanged', 'candidates': sources})
    save('c2-side-by-side.json', source_rows)
    csv_save('controlled-document.csv', note_rows)
    assert len(note_rows) == 8
    heldout_normals = [r for r in fold_rows if r['run'] == r['heldout_normal']]
    equal_rarity_ties = sum(len({e['max_rarity_bits'] for c in row['candidates']
        if c['content_rank_min'] == 1 for e in c['return_rarity']
        if e['content_score'] == c['content_score']}) == 1 for row in source_rows)
    summary = {'version': 'c3-v1', 'status': 'passed', 'reference_runs': references,
               'scored_runs': len(names), 'scored_native_calls': sum(len(v) for v in annotated.values()),
               'full_reference_runs': run_rows,
               'unauthorized_edits': action_rows,
               'heldout_normal_rows': heldout_normals,
               'heldout_normal_runs_with_unseen_signature': sum(r['unseen_signature_calls'] > 0 for r in heldout_normals),
               'controlled_document_rows': note_rows,
               'c2_top_tie_cases_with_equal_return_rarity': equal_rarity_ties,
               'score_unit': 'bits of smoothed per-run signature occurrence; not attack probability',
               'binary_alert_threshold': None,
               'limitations': ['Five references only; in-reference normal scores are descriptive and optimistic.',
                   'Unseen signatures are a reference-set property, not a violation label.',
                   'Rare task invocations and authorized file operations can tie with violations.',
                   'Same document path does not distinguish benign content from injected content.',
                   'No C1/C2 score combination, no source-causality claim, no C4 log comparison or analyst-time measurement.']}
    save('summary.json', summary)
    # Lock exact inputs, the frozen protocol and implementation for reproducibility.
    paths = list((ROOT / 'provenance').glob('*.py')) + [Path(__file__).resolve(), OUT / 'protocol.json']
    paths += [p for p in (ROOT / 'artifact/runs').rglob('*') if p.is_file()]
    paths += [ROOT / 'experiments/delegated-sessions.json', ROOT / 'experiments/v2-d7/run-039-child-session.json',
              ROOT / 'experiments/v2-d7/c1-c2/queries.json', ROOT / 'experiments/manifest.json']
    save('input-sha256.json', {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})
    if CHECK:
        print('C3 outputs and input fingerprints reproduced exactly; no files written.')
        return
    print((OUT / 'runs.csv').read_text())
    print((OUT / 'unauthorized-edits.csv').read_text())
    print('Held-out normal runs with unseen signatures:', summary['heldout_normal_runs_with_unseen_signature'])
    print((OUT / 'controlled-document.csv').read_text())

if __name__ == '__main__':
    main()
