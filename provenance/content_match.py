"""Graph-free fixed content ranking shared without source-location labels.

No scenario labels, known source path, final outcome or future messages enter
scoring. This is candidate retrieval, never an attribution of model causality.
"""
from collections import Counter
import difflib
import re
from records import call_record

TOKEN = re.compile(r'-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z_0-9]*(?:[/.][A-Za-z_0-9.-]+)*')


def tokens(text):
    return Counter(TOKEN.findall(text))


def addition(old, new):
    """Added lexical occurrences and full changed lines, excluding unchanged context."""
    novel = sorted((tokens(new) - tokens(old)).keys())
    lines = []
    for tag, i, j, k, l in difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False).get_opcodes():
        if tag in ('insert', 'replace'):
            lines.extend(' '.join(s.split()) for s in new.splitlines()[k:l] if s.strip())
    return {'added_tokens': novel, 'added_lines': sorted(set(lines))}


def before_action(c, target):
    # Calls in the same assistant response cannot consume each other's returns.
    if c.turn >= target.turn:
        return False
    # A timestamp contradiction is excluded rather than silently time-travelled.
    if c.time_end is not None and target.time_start is not None:
        return c.time_end <= target.time_start
    return True


def rank_from_returns(t, target, path, read_paths, before_text=None):
    raw = target.raw_input or target.input
    if target.tool == 'edit':
        delta = addition(raw['oldString'], raw['newString'])
    elif target.tool == 'write' and before_text is not None:
        delta = addition(before_text, raw['content'])
    else:
        return {'status': 'unavailable', 'reason': 'Exact before/after content is unavailable.', 'candidates': []}
    groups = {}
    for c in t.calls:
        if not before_action(c, target) or not c.output.strip():
            continue
        paths = sorted(set(read_paths.get(c.index, [])))
        source = paths[0] if len(paths) == 1 and c.tool in ('read', 'skill') and c.status == 'completed' else None
        key = 'file:' + source if source else f'return:{t.session_id}/C:{c.index}'
        text = c.output
        lexemes = tokens(text)
        matched = [x for x in delta['added_tokens'] if x in lexemes]
        normalized = ' '.join(text.split())
        lines = [line for line in delta['added_lines'] if line in normalized]
        # Exact normalized relative path only; no basename or injection-specific feature.
        path_match = path in lexemes
        score = int(path_match) + len(matched) + len(lines)
        evidence = {**call_record(t, c), 'matched_target_path': path if path_match else None,
                    'matched_added_tokens': matched, 'matched_added_lines': lines,
                    'score': score}
        item = groups.setdefault(key, {'source': key, 'file_path': source,
                     'score': 0, 'returns': [], 'related_paths': paths})
        item['returns'].append(evidence)
        item['score'] = max(item['score'], score)
    candidates = sorted(groups.values(), key=lambda x: (-x['score'], x['source']))
    for item in candidates:
        item['rank_min'] = 1 + sum(c['score'] > item['score'] for c in candidates)
        item['rank_max'] = sum(c['score'] >= item['score'] for c in candidates)
        item['best_call_evidence'] = [e['call'] for e in item['returns'] if e['score'] == item['score']]
    return {'status': 'ranked', 'session': t.session_id, 'call': target.index,
            'target_path': path, **delta, 'candidate_count': len(candidates),
            'rule': 'v1: one point for exact target path, each distinct added token, and each full added line; source score=max(return scores); competition rank interval includes ties.',
            'visibility': 'Only earlier turns in this native session; parent returns are not assumed visible in a child. No user messages are candidates.',
            'candidates': candidates}
