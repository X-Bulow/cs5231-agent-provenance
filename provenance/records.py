"""Graph-free serialization and lexical path policy shared by both methods."""
import hashlib
import posixpath


def digest(data):
    return hashlib.sha256(data).hexdigest()


def allowed(path, prefixes):
    path = posixpath.normpath(path)
    if path.startswith('/') or path == '..' or path.startswith('../'):
        return False
    return any(path.startswith(posixpath.normpath(p).rstrip('/') + '/') for p in prefixes)


def workspace_hashes(run):
    return {p.relative_to(run / 'workspace').as_posix(): digest(p.read_bytes())
            for p in sorted((run / 'workspace').rglob('*')) if p.is_file()}


def call_record(t, c):
    return {'session': t.session_id, 'call': c.index, 'call_id': c.call_id,
            'turn': c.turn, 'tool': c.tool, 'status': c.status,
            'exit_code': c.exit_code, 'time_start': c.time_start, 'time_end': c.time_end,
            'raw_input': c.raw_input, 'raw_output': c.raw_output}


