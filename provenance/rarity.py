"""Exploratory per-run occurrence rarity; independent of authorization/content.

python3 -B provenance/rarity.py artifact/runs/run-039 \
    --reference artifact/runs/run-030 --reference artifact/runs/run-033
Use all five specified normal references for the primary D7 experiment.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import math
import posixpath
from pathlib import Path
from typing import Optional
from build_graph import GraphBuilder
from detect import call_record
from trajectory import load_run

Signature = tuple[str, str, Optional[str]]


def signature(tool, relation, path=None) -> Signature:
    if relation not in ('CALL', 'READ', 'WRITE', 'DELETE'):
        raise ValueError('Unsupported rarity relation')
    if (relation == 'CALL') != (path is None):
        raise ValueError('CALL requires null path; file relation requires path')
    return tool, relation, posixpath.normpath(path) if path is not None else None


def signature_dict(key):
    return dict(zip(('tool', 'relation', 'path'), key))


def feature_key(feature):
    return signature(feature['tool'], feature['relation'], feature['path'])


def extract_events(t, baseline, parent=None):
    """One row per native call; delegated file summaries are never real events."""
    graph = GraphBuilder(t, baseline, changes=None).build()
    nodes = {n['id']: n for n in graph['nodes']}
    file_edges = defaultdict(list)
    excluded = defaultdict(list)
    for e in graph['edges']:
        src, dst = nodes[e['src']], nodes[e['dst']]
        if e['rel'] == 'READ' and src['kind'] == 'file' and dst['kind'] == 'call':
            c, f, relation = dst, src, 'READ'
        elif e['rel'] == 'WRITE' and src['kind'] == 'call' and dst['kind'] == 'file':
            c, f, relation = src, dst, 'DELETE' if dst['deleted'] else 'WRITE'
        else:
            continue
        item = {**signature_dict(signature(c['tool'], relation, f['path'])),
                'basis': e['basis'], 'edge': e}
        if e.get('rule') == 'delegated-session':
            excluded[c['index']].append(item)
        else:
            file_edges[c['index']].append(item)
    events = []
    for c in t.calls:
        # A failed invocation is observed, not a successful file operation.
        features = [{**signature_dict(signature(c.tool, 'CALL')),
                     'basis': 'recorded', 'edge': None}]
        features.extend(file_edges[c.index])
        event = {**call_record(t, c), 'features': features, 'parent': parent,
                 'excluded_delegation_file_summaries': excluded[c.index]}
        events.append(event)
    for c, child in t.delegated.items():
        events.extend(extract_events(child, baseline, {'session': t.session_id, 'call': c}))
    return events


def load_events(run):
    run = Path(run)
    return extract_events(load_run(run), json.loads((run / 'baseline.json').read_text()))


@dataclass(frozen=True)
class Reference:
    run_ids: tuple[str, ...]
    support: dict[Signature, frozenset[str]]

    def score(self, key):
        witnesses = sorted(self.support.get(key, ()))
        n, total = len(witnesses), len(self.run_ids)
        probability = (n + 1) / (total + 2)
        return {**signature_dict(key), 'reference_support': n, 'reference_runs': total,
                'supporting_runs': witnesses, 'smoothed_probability': probability,
                'rarity_bits': -math.log2(probability), 'unseen_in_reference': n == 0}

    def export(self):
        return {'version': 'c3-v1', 'reference_runs': list(self.run_ids),
                'count_unit': 'complete-run signature presence',
                'probability': '(support+1)/(reference_runs+2)',
                'rarity_bits': '-log2(probability)',
                'signature_count': len(self.support),
                'signatures': [self.score(k) for k in sorted(self.support, key=lambda k: json.dumps(k))]}


def fit_reference(runs):
    """runs is [(stable run id, extracted events)]; no labels/outcomes required."""
    ids = [run_id for run_id, _ in runs]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Need nonempty, distinct reference run IDs')
    support = defaultdict(set)
    for run_id, events in runs:
        for key in {feature_key(f) for event in events for f in event['features']}:
            support[key].add(run_id)
    return Reference(tuple(sorted(ids)), {k: frozenset(v) for k, v in support.items()})


def score_events(events, reference):
    rows = []
    for event in events:
        keys = {feature_key(f) for f in event['features']}
        scored = [reference.score(k) for k in sorted(keys, key=lambda k: json.dumps(k))]
        calls = [s for s in scored if s['relation'] == 'CALL']
        files = [s for s in scored if s['relation'] != 'CALL']
        if len(calls) != 1:
            raise ValueError('Each event must have exactly one native CALL feature')
        row = {**event, 'signature_scores': scored, 'call_rarity_bits': calls[0]['rarity_bits'],
               'max_file_rarity_bits': max((s['rarity_bits'] for s in files), default=None),
               'max_rarity_bits': max(s['rarity_bits'] for s in scored),
               'unseen_signature_count': sum(s['unseen_in_reference'] for s in scored)}
        rows.append(row)
    # Competition rank intervals preserve all ties across actual calls in one run.
    for row in rows:
        row['rank_min'] = 1 + sum(r['max_rarity_bits'] > row['max_rarity_bits'] for r in rows)
        row['rank_max'] = sum(r['max_rarity_bits'] >= row['max_rarity_bits'] for r in rows)
    return sorted(rows, key=lambda r: (-r['max_rarity_bits'], r['session'], r['call']))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--reference', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    ref = fit_reference([(path.name, load_events(path)) for path in a.reference])
    result = {'run': a.run.name, 'in_reference': a.run.name in ref.run_ids,
              'reference': ref.export(), 'events': score_events(load_events(a.run), ref)}
    text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if a.output:
        a.output.write_text(text)
    else:
        print(text, end='')

if __name__ == '__main__':
    main()
