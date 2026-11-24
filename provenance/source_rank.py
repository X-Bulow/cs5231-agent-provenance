"""Graph adapter for fixed C2-v1 prior-return content ranking."""
from build_graph import GraphBuilder
from content_match import TOKEN, tokens, addition, before_action, rank_from_returns


def rank_sources(t, target, path, before_text=None, baseline=None):
    graph = GraphBuilder(t, baseline or {}, changes=None).build()
    nodes = {n['id']: n for n in graph['nodes']}
    paths = {}
    for e in graph['edges']:
        if e['rel'] == 'READ' and nodes[e['src']]['kind'] == 'file' and nodes[e['dst']]['kind'] == 'call':
            paths.setdefault(nodes[e['dst']]['index'], []).append(nodes[e['src']]['path'])
    return rank_from_returns(t, target, path, paths, before_text)
