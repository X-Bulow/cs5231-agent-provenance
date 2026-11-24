"""Trace ancestors/descendants and rank prior returns for an explicit action.

python3 -B provenance/query.py artifact/runs/run-039 --call 11 --child-of 3
"""
import argparse
import json
from pathlib import Path
from build_graph import GraphBuilder
from trajectory import load_run
from source_rank import rank_sources
from detect import call_record


def trace(graph, target, direction='backward'):
    nodes = {n['id']: n for n in graph['nodes']}
    if target not in nodes:
        raise ValueError('Unknown graph node: ' + target)
    if direction not in ('backward', 'forward'):
        raise ValueError('direction must be backward or forward')
    seen, todo = {target}, [target]
    adjacency = {}
    for e in graph['edges']:
        src, dst = (e['dst'], e['src']) if direction == 'backward' else (e['src'], e['dst'])
        adjacency.setdefault(src, []).append(dst)
    while todo:
        for node in adjacency.get(todo.pop(), []):
            if node not in seen:
                seen.add(node)
                todo.append(node)
    return {'target': target, 'direction': direction,
            'other_nodes': len(seen) - 1, 'full_graph_other_nodes': len(nodes) - 1,
            'node_fraction': (len(seen) - 1) / (len(nodes) - 1) if len(nodes) > 1 else 0,
            'nodes': [n for n in graph['nodes'] if n['id'] in seen],
            'edges': [e for e in graph['edges'] if e['src'] in seen and e['dst'] in seen]}


def query(run, call, direction='backward', child_of=None, path=None):
    run = Path(run)
    parent = load_run(run)
    t = parent.delegated[child_of] if child_of is not None else parent
    c = next((c for c in t.calls if c.index == call), None)
    if c is None:
        raise ValueError('Unknown call')
    baseline = json.loads((run / 'baseline.json').read_text())
    graph = GraphBuilder(t, baseline, changes=None).build()
    result = {'run': run.name, 'action': call_record(t, c),
              'trace': trace(graph, f'C:{call}', direction)}
    if child_of is not None:
        result['parent_boundary'] = {'session': parent.session_id, 'call': child_of,
            'evidence_type': 'delegated-session',
            'trace': trace(GraphBuilder(parent, baseline, changes=None).build(), f'C:{child_of}', direction)}
    if call in t.delegated:
        child = t.delegated[call]
        cg = GraphBuilder(child, baseline, changes=None).build()
        result['delegated_writes'] = [{**call_record(child, cc), 'path': n['path']}
            for e in cg['edges'] for n in [next(n for n in cg['nodes'] if n['id'] == e['dst'])]
            if e['rel'] == 'WRITE' and n['kind'] == 'file'
            for cc in child.calls if e['src'] == f'C:{cc.index}']
    path = path or c.input.get('filePath')
    if path:
        result['source_ranking'] = rank_sources(t, c, path, baseline=baseline)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--call', type=int, required=True)
    p.add_argument('--child-of', type=int)
    p.add_argument('--direction', choices=('backward', 'forward'), default='backward')
    p.add_argument('--path')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    text = json.dumps(query(a.run, a.call, a.direction, a.child_of, a.path), indent=2, ensure_ascii=False) + '\n'
    if a.output:
        a.output.write_text(text)
    else:
        print(text, end='')

if __name__ == '__main__':
    main()
