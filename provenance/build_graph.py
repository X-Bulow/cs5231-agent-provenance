"""Build the provenance graph of one recorded run.

Output format: docs/graph-format.md (version 1). This stage creates the
edges that the trajectory records directly (patterns 1 to 7), together with
file versions and trust labels. Edges inferred for shell commands (patterns
8 and 9) are not produced yet, and `source.inferred_edges` says so.

Usage:
    python3 provenance/build_graph.py artifact/runs/run-006 graphs/run-006.json
    python3 provenance/build_graph.py --all artifact/runs graphs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import sys
from pathlib import Path
from typing import Any

from trajectory import Call, Trajectory, load_run

SCHEMA_VERSION = 1
RELATIONS = ("EXEC", "READ", "WRITE", "NEXT")
SKILL_PREFIX = ".agents/skills/"


def normalize_path(path: str) -> str:
    """Workspace-relative POSIX path; paths outside the workspace stay absolute."""
    return posixpath.normpath(path.strip()) if path.strip() else ""


class GraphBuilder:
    def __init__(self, trajectory: Trajectory, baseline: dict[str, str]):
        self.trajectory = trajectory
        self.baseline = baseline
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.latest: dict[str, int] = {}      # path -> latest version number
        self.notes: list[str] = []            # things the next stage must resolve

    # -- nodes ---------------------------------------------------------------

    def _add_node(self, node: dict[str, Any]) -> str:
        self.nodes.setdefault(node["id"], node)
        return node["id"]

    def _file_node(self, path: str, version: int, sha256: str | None = None) -> str:
        if version == 0:
            trust = "skill" if path.startswith(SKILL_PREFIX) else "workspace"
            sha256 = self.baseline.get(path)
        else:
            trust = "derived"
        return self._add_node({
            "id": f"O:file:{path}@v{version}", "kind": "file", "path": path,
            "version": version, "trust": trust, "sha256": sha256, "deleted": False,
        })

    def current_version(self, path: str, call: Call) -> str:
        """Node id of the latest version of path, creating it on first use."""
        if path not in self.latest:
            if path in self.baseline:
                self.latest[path] = 0
            else:
                # Read of a file that no recorded write created, typically one
                # produced by a shell command. Its origin is an inferred edge.
                self.latest[path] = 1
                self.notes.append(f"C:{call.index} reads {path}, which has no recorded origin")
        return self._file_node(path, self.latest[path])

    def next_version(self, path: str, sha256: str | None = None) -> str:
        """Node id of a new version of path."""
        if path in self.latest:
            version = self.latest[path] + 1
        else:
            version = 1          # follows the baseline @v0, or is the first version
        self.latest[path] = version
        return self._file_node(path, version, sha256)

    # -- edges ---------------------------------------------------------------

    def _add_edge(self, src: str, rel: str, dst: str, evidence: list[int]) -> None:
        edge = self.edges.setdefault((src, rel, dst), {
            "src": src, "rel": rel, "dst": dst, "basis": "recorded", "evidence": []})
        edge["evidence"] = sorted(set(edge["evidence"]) | set(evidence))

    # -- construction --------------------------------------------------------

    def build(self) -> dict[str, Any]:
        t = self.trajectory
        self._add_node({"id": "O:prompt", "kind": "prompt", "trust": "user", "content": t.prompt})

        for turn in t.turns:
            self._add_node({
                "id": f"T:{turn.index}", "kind": "turn", "index": turn.index,
                "message_id": turn.message_id, "calls": list(turn.calls),
                "text": turn.text, "reasoning": turn.reasoning,
                "time_start": turn.time_start, "time_end": turn.time_end,
            })
        if t.turns:
            self._add_edge("O:prompt", "READ", "T:1", [])                    # pattern 1
        for turn in t.turns[1:]:
            self._add_edge(f"T:{turn.index - 1}", "NEXT", f"T:{turn.index}", [])  # pattern 2

        last_turn = len(t.turns)
        for call in t.calls:
            call_id = self._add_node({
                "id": f"C:{call.index}", "kind": "call", "index": call.index,
                "turn": call.turn, "tool": call.tool, "call_id": call.call_id,
                "status": call.status, "input": call.input, "exit_code": call.exit_code,
                "time_start": call.time_start, "time_end": call.time_end,
            })
            result_id = self._add_node({
                "id": f"O:result:{call.index}", "kind": "result", "call": call.index,
                "trust": "derived", "content": call.output, "truncated": call.truncated,
            })
            evidence = [call.index]
            self._add_edge(f"T:{call.turn}", "EXEC", call_id, evidence)       # pattern 3
            self._add_edge(call_id, "WRITE", result_id, evidence)             # pattern 4
            if call.turn < last_turn:
                self._add_edge(result_id, "READ", f"T:{call.turn + 1}", evidence)  # pattern 5
            if call.status == "completed":
                self._file_edges(call, call_id, evidence)

        nodes = sorted(self.nodes.values(), key=_node_order)
        edges = sorted(self.edges.values(), key=_edge_order)
        return {
            "schema_version": SCHEMA_VERSION,
            "run": t.run,
            "source": {
                "session_id": t.session_id, "agent": t.agent,
                "agent_version": t.agent_version, "model": t.model,
                "inferred_edges": False,
            },
            "nodes": nodes,
            "edges": edges,
        }

    def _file_edges(self, call: Call, call_id: str, evidence: list[int]) -> None:
        """Patterns 6 and 7: file reads and writes that the tool call records."""
        tool = call.tool
        if tool == "skill":
            name = str(call.input.get("name", "")).strip()
            path = f"{SKILL_PREFIX}{name}/SKILL.md"
            if path in self.baseline:
                self._add_edge(self.current_version(path, call), "READ", call_id, evidence)
            else:
                self.notes.append(f"C:{call.index} loads skill {name!r}, which is not in the workspace")
            return
        if tool not in ("read", "edit", "write"):
            return
        path = normalize_path(str(call.input.get("filePath", "")))
        if not path:
            return
        if tool == "read":
            # Reading a directory returns a listing and no file content.
            if path == "." or "<type>directory</type>" in call.output:
                return
            self._add_edge(self.current_version(path, call), "READ", call_id, evidence)
        elif tool == "edit":
            # An edit patches the existing content, so it depends on it.
            self._add_edge(self.current_version(path, call), "READ", call_id, evidence)
            self._add_edge(call_id, "WRITE", self.next_version(path), evidence)
        else:
            content = call.input.get("content")
            sha256 = (hashlib.sha256(content.encode("utf-8")).hexdigest()
                      if isinstance(content, str) else None)
            self._add_edge(call_id, "WRITE", self.next_version(path, sha256), evidence)


_KIND_ORDER = {"turn": 0, "call": 1, "prompt": 2, "file": 3, "result": 4}


def _node_order(node: dict[str, Any]) -> tuple:
    kind = node["kind"]
    if kind in ("turn", "call"):
        return (_KIND_ORDER[kind], node["index"], "")
    if kind == "file":
        return (_KIND_ORDER[kind], node["path"], node["version"])
    if kind == "result":
        return (_KIND_ORDER[kind], node["call"], "")
    return (_KIND_ORDER[kind], 0, "")


def _edge_order(edge: dict[str, Any]) -> tuple:
    first = edge["evidence"][0] if edge["evidence"] else 0
    return (first, RELATIONS.index(edge["rel"]), edge["src"], edge["dst"])


def validate(graph: dict[str, Any]) -> list[str]:
    """Return every way the graph departs from docs/graph-format.md."""
    problems: list[str] = []
    ids = [node["id"] for node in graph["nodes"]]
    if len(ids) != len(set(ids)):
        problems.append("duplicate node ids")
    kinds = {node["id"]: node["kind"] for node in graph["nodes"]}
    seen: set[tuple[str, str, str]] = set()
    successors: dict[str, list[str]] = {node_id: [] for node_id in kinds}
    indegree = {node_id: 0 for node_id in kinds}

    for edge in graph["edges"]:
        src, rel, dst = edge["src"], edge["rel"], edge["dst"]
        label = f"{src} -{rel}-> {dst}"
        if src not in kinds or dst not in kinds:
            problems.append(f"dangling edge {label}")
            continue
        if (src, rel, dst) in seen:
            problems.append(f"duplicate edge {label}")
        seen.add((src, rel, dst))
        if rel not in RELATIONS:
            problems.append(f"unknown relation in {label}")
        if edge["basis"] not in ("recorded", "inferred"):
            problems.append(f"unknown basis in {label}")
        if edge["basis"] == "inferred" and not edge.get("rule"):
            problems.append(f"inferred edge without a rule: {label}")
        if edge["evidence"] != sorted(set(edge["evidence"])):
            problems.append(f"evidence not ascending in {label}")
        shape = (kinds[src], rel, kinds[dst])
        if shape not in _ALLOWED_SHAPES:
            problems.append(f"edge shape {shape} not allowed: {label}")
        successors[src].append(dst)
        indegree[dst] += 1

    # Every edge must point forward in time, so the graph has to be acyclic.
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for successor in successors[node_id]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    if visited != len(kinds):
        problems.append("graph contains a cycle")
    return problems


_ALLOWED_SHAPES = {
    ("prompt", "READ", "turn"),     # pattern 1
    ("turn", "NEXT", "turn"),       # pattern 2
    ("turn", "EXEC", "call"),       # pattern 3
    ("call", "WRITE", "result"),    # pattern 4
    ("result", "READ", "turn"),     # pattern 5
    ("file", "READ", "call"),       # patterns 6 and 8
    ("call", "WRITE", "file"),      # patterns 7 and 9
}


def build_run(run_dir: str | Path) -> tuple[dict[str, Any], list[str]]:
    """Build the graph of one run. Returns the graph and notes for the next stage."""
    run_dir = Path(run_dir)
    trajectory = load_run(run_dir)
    baseline = json.loads((run_dir / "baseline.json").read_text(encoding="utf-8"))
    builder = GraphBuilder(trajectory, baseline)
    graph = builder.build()
    problems = validate(graph)
    if problems:
        raise ValueError(f"{run_dir.name}: invalid graph: " + "; ".join(problems))
    notes = list(trajectory.warnings) + builder.notes + unexplained_changes(graph, run_dir)
    return graph, notes


def unexplained_changes(graph: dict[str, Any], run_dir: Path) -> list[str]:
    """Files that changed during the run with no write edge in the graph.

    Uses the independent before/after comparison in check.json. Each such file
    was modified by something the trajectory does not record directly.
    """
    check_path = run_dir / "check.json"
    if not check_path.is_file():
        return ["check.json is missing; file changes not compared"]
    written = {node["path"] for node in graph["nodes"]
               if node["kind"] == "file" and node["version"] > 0}
    changed = [item["path"] for item in json.loads(check_path.read_text(encoding="utf-8"))["changes"]]
    return [f"{path} changed during the run but no recorded write explains it"
            for path in changed if path not in written]


def write_graph(graph: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def describe(graph: dict[str, Any]) -> str:
    kinds: dict[str, int] = {}
    for node in graph["nodes"]:
        kinds[node["kind"]] = kinds.get(node["kind"], 0) + 1
    rels: dict[str, int] = {}
    for edge in graph["edges"]:
        rels[edge["rel"]] = rels.get(edge["rel"], 0) + 1
    node_text = ", ".join(f"{kinds.get(kind, 0)} {kind}" for kind in _KIND_ORDER)
    edge_text = ", ".join(f"{rels.get(rel, 0)} {rel}" for rel in RELATIONS)
    return f"{graph['run']}: {len(graph['nodes'])} nodes ({node_text}); {len(graph['edges'])} edges ({edge_text})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the provenance graph of a recorded run.")
    parser.add_argument("--all", action="store_true",
                        help="treat the arguments as a directory of runs and an output directory")
    parser.add_argument("run", type=Path, help="run directory (or runs directory with --all)")
    parser.add_argument("output", type=Path, help="output JSON file (or directory with --all)")
    args = parser.parse_args()

    if args.all:
        jobs = [(run, args.output / f"{run.name}.json")
                for run in sorted(args.run.glob("run-*")) if (run / "session.json").is_file()]
    else:
        jobs = [(args.run, args.output)]
    if not jobs:
        parser.error("no run with a session.json found")

    for run, output in jobs:
        graph, notes = build_run(run)
        write_graph(graph, output)
        print(describe(graph))
        for note in notes:
            print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
