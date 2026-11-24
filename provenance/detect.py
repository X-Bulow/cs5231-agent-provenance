"""Find writes outside caller-supplied allowed directories, without scenario labels.

Usage: python3 -B provenance/detect.py artifact/runs/run-031 --allow src/ --allow outputs/
Graph inference is evidence of a possible operation, not a syscall observation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from build_graph import GraphBuilder
from trajectory import load_run
from records import allowed, call_record, digest, workspace_hashes


def detect_session(t, baseline, final, prefixes, parent=None):
    # No check.json reconciliation: final differences cannot invent a call.
    builder = GraphBuilder(t, baseline, changes=None)
    graph = builder.build()
    nodes = {n['id']: n for n in graph['nodes']}
    calls = {c.index: c for c in t.calls}
    actions = []
    diagnostics = [{'session': t.session_id, 'graph_notes': builder.notes,
                    'trajectory_warnings': t.warnings,
                    'failed_or_invalid_calls': [call_record(t, c) for c in t.calls
                        if c.status != 'completed' or c.tool == 'invalid']}]
    for e in graph['edges']:
        if e['rel'] != 'WRITE' or nodes[e['dst']]['kind'] != 'file':
            continue
        node = nodes[e['dst']]
        c = calls[nodes[e['src']]['index']]
        path = node['path']
        boundary = e.get('rule') == 'delegated-session'
        outside = path.startswith('/') or path == '..' or path.startswith('../')
        changed = baseline.get(path) != final.get(path) if not outside else None
        lifecycle = (('outside_workspace_inference' if e['basis'] == 'inferred'
                      else 'outside_workspace_recorded_unverified') if outside else
                     'final_changed' if changed else
                     'written_then_final_baseline' if path in baseline else 'absent_at_end')
        action = {**call_record(t, c), 'id': f'{t.session_id}/C:{c.index}/{path}',
                  'path': path, 'file_node': e['dst'], 'authorized': allowed(path, prefixes),
                  'evidence': e, 'basis': e['basis'], 'boundary_summary': boundary,
                  'parent': parent, 'final_changed': changed, 'lifecycle': lifecycle,
                  'operation_content_changed': None,
                  'baseline_sha256': baseline.get(path), 'final_sha256': final.get(path)}
        if c.tool == 'edit':
            action['operation_content_changed'] = c.raw_input['oldString'] != c.raw_input['newString']
        actions.append(action)
    # Child writes are actual operation starts; task summaries remain separate.
    for index, child in t.delegated.items():
        child_result = detect_session(child, baseline, final, prefixes,
            {'session': t.session_id, 'call': index, 'call_id': calls[index].call_id})
        actions.extend(child_result['actions'])
        diagnostics.extend(child_result['diagnostics'])
    return {'actions': actions, 'graph': graph, 'diagnostics': diagnostics}


def investigate(run, prefixes):
    run = Path(run).resolve()
    t = load_run(run)
    baseline = json.loads((run / 'baseline.json').read_text())
    final = workspace_hashes(run)
    result = detect_session(t, baseline, final, prefixes)
    differences = [{'path': p, 'before': baseline.get(p), 'after': final.get(p),
                    'authorized': allowed(p, prefixes)}
                   for p in sorted(set(baseline) | set(final)) if baseline.get(p) != final.get(p)]
    actions = result['actions']
    return {'run': run.name, 'allowed_directories': list(prefixes), 'actions': actions,
            'final_differences': differences, 'diagnostics': result['diagnostics'],
            'unexplained_final_changes': [d for d in differences if not any(a['path'] == d['path'] for a in actions)],
            'notes': ['Authorization uses lexical workspace paths and caller-supplied directories.',
                      'Shell writes are inferred; final differences alone do not identify a writer.',
                      'Boundary summaries are not additional child operations.',
                      'A final-baseline write may be a restoration or a no-op; inspect raw edits.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--allow', action='append', required=True)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    text = json.dumps(investigate(a.run, a.allow), indent=2, ensure_ascii=False) + '\n'
    if a.output:
        a.output.write_text(text)
    else:
        print(text, end='')

if __name__ == '__main__':
    main()
