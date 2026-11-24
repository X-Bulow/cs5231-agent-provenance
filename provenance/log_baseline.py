"""Automated flat-log baseline: no graph imports, graph files or source labels.

python3 -B provenance/log_baseline.py artifact/runs/run-039 --allow src/ --allow outputs/
Add --call 11 --child-of 3 for prior-return ranking of a native child action.
"""
from __future__ import annotations
import argparse
import json
import posixpath
from pathlib import Path
from records import allowed, call_record, workspace_hashes
from trajectory import load_run
from shell import analyze_command, grep_output_paths
from content_match import before_action, rank_from_returns


def normalized(path):
    return posixpath.normpath(path.strip()) if path.strip() else ''


def scan_session(t, baseline, existing=None, parent=None):
    """Flat rows in execution scope order; only a mutable path set is maintained."""
    existing = set(baseline) if existing is None else existing
    rows, diagnostics = [], []
    for c in t.calls:
        operations = {}
        written = set()

        def read(path, basis='recorded', rule=None, require_existing=False):
            if path and path not in written and (not require_existing or path in existing):
                operations.setdefault(('READ', path), {'relation': 'READ', 'path': path,
                    'basis': basis, 'rule': rule, 'deleted': False})
                existing.add(path)

        def write(path, deleted=False, basis='recorded', rule=None):
            if path:
                key = ('WRITE', path)
                if key not in operations:
                    operations[key] = {'relation': 'WRITE', 'path': path,
                        'basis': basis, 'rule': rule, 'deleted': deleted}
                operations[key]['deleted'] = deleted
                written.add(path)
                if deleted:
                    existing.discard(path)
                else:
                    existing.add(path)

        if c.status == 'completed' and c.tool != 'invalid':
            path = normalized(str(c.input.get('filePath', '')))
            if c.tool == 'skill':
                skill = '.agents/skills/' + str(c.input.get('name', '')).strip() + '/SKILL.md'
                if skill in baseline:
                    read(skill)
            elif c.tool == 'read':
                if path != '.' and '<type>directory</type>' not in c.output:
                    read(path)
            elif c.tool == 'edit':
                read(path)
                write(path)
            elif c.tool == 'write':
                write(path)
            elif c.tool == 'grep':
                for p in grep_output_paths(c.output):
                    read(normalized(p), 'inferred', 'tool-output', require_existing=True)
            elif c.tool == 'bash' and isinstance(c.input.get('command'), str):
                analysis = analyze_command(c.input['command'], existing, c.exit_code,
                    output=c.output, raw_command=(c.raw_input or c.input).get('command'))
                diagnostics.extend({'session': t.session_id, 'call': c.index, 'note': n} for n in analysis.notes)
                for op in analysis.ops:
                    if op.kind == 'read':
                        read(op.path, 'inferred', op.rule, require_existing=True)
                    else:
                        if op.append and op.path not in written:
                            read(op.path, 'inferred', op.rule, require_existing=True)
                        write(op.path, op.kind == 'delete', 'inferred', op.rule)
                if 'grep' in analysis.programs:
                    for p in grep_output_paths(c.output):
                        read(normalized(p), 'inferred', 'tool-output', require_existing=True)
        row = {**call_record(t, c), 'parent': parent, 'operations': list(operations.values())}
        rows.append(row)
        # Child actions are real rows, not duplicated writes on the task row.
        if c.index in t.delegated:
            child = scan_session(t.delegated[c.index], baseline, existing,
                                 {'session': t.session_id, 'call': c.index, 'call_id': c.call_id})
            rows.extend(child['rows'])
            diagnostics.extend(child['diagnostics'])
    return {'rows': rows, 'diagnostics': diagnostics}


def inspect_run(run, prefixes):
    run = Path(run)
    t = load_run(run)
    baseline = json.loads((run / 'baseline.json').read_text())
    result = scan_session(t, baseline)
    actions = [{**r, **op, 'authorized': allowed(op['path'], prefixes)}
               for r in result['rows'] for op in r['operations'] if op['relation'] == 'WRITE']
    final = workspace_hashes(run)
    differences = [{'path': p, 'before': baseline.get(p), 'after': final.get(p),
                    'authorized': allowed(p, prefixes)}
                   for p in sorted(set(baseline) | set(final)) if baseline.get(p) != final.get(p)]
    return {'run': run.name, 'allowed_directories': list(prefixes), **result,
            'actions': actions, 'final_differences': differences,
            'unexplained_final_changes': [d for d in differences if not any(a['path'] == d['path'] for a in actions)]}


def rank_logged_returns(t, rows, target, path, before_text=None):
    paths = {row['call']: [op['path'] for op in row['operations'] if op['relation'] == 'READ']
             for row in rows if row['session'] == t.session_id}
    return rank_from_returns(t, target, path, paths, before_text)


def query_log(run, call, child_of=None, path=None):
    run = Path(run)
    parent = load_run(run)
    t = parent.delegated[child_of] if child_of is not None else parent
    c = next((c for c in t.calls if c.index == call), None)
    if c is None:
        raise ValueError('Unknown native call')
    baseline = json.loads((run / 'baseline.json').read_text())
    logged = scan_session(parent, baseline)
    prior = [row for row in logged['rows'] if row['session'] == t.session_id
             and before_action(next(k for k in t.calls if k.index == row['call']), c)]
    result = {'run': run.name, 'action': call_record(t, c), 'prior_call_count': len(prior),
              'prior_calls': prior}
    path = path or c.input.get('filePath')
    if path:
        result['source_ranking'] = rank_logged_returns(t, logged['rows'], c, path)
    if child_of is not None:
        result['parent_boundary'] = {'session': parent.session_id, 'call': child_of}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--allow', action='append', required=True)
    p.add_argument('--call', type=int)
    p.add_argument('--child-of', type=int)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result = inspect_run(a.run, a.allow)
    if a.call is not None:
        result['query'] = query_log(a.run, a.call, a.child_of)
    text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if a.output:
        a.output.write_text(text)
    else:
        print(text, end='')

if __name__ == '__main__':
    main()
