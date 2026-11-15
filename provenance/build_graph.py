"""Build the provenance graph of one recorded run.

Output format: docs/graph-format.md (version 1). The builder creates

  * the edges the trajectory records directly (patterns 1 to 7);
  * edges inferred for shell commands (patterns 8 and 9), see shell.py;
  * file versions, trust labels, and content hashes where they are known.

After construction it reconciles the graph with the independent before/after
file comparison in check.json and reports anything the graph cannot explain.

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

from shell import analyze_command, grep_output_paths
from trajectory import Call, Trajectory, load_run

SCHEMA_VERSION = 1
RELATIONS = ("EXEC", "READ", "WRITE", "NEXT")
SKILL_PREFIX = ".agents/skills/"


def normalize_path(path: str) -> str:
    """Workspace-relative POSIX path; paths outside the workspace stay absolute."""
    return posixpath.normpath(path.strip()) if path.strip() else ""


class GraphBuilder:
    def __init__(self, trajectory: Trajectory, baseline: dict[str, str],
                 changes: dict[str, tuple[str | None, str | None]] | None = None):
        self.trajectory = trajectory
        self.baseline = baseline
        self.changes = changes            # path -> (hash before, hash after); None if unknown
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.latest: dict[str, int] = {}  # path -> latest version number
        self.notes: list[str] = []        # things the graph cannot fully explain

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

    def _latest_node(self, path: str) -> dict[str, Any] | None:
        if path in self.latest:
            return self.nodes.get(f"O:file:{path}@v{self.latest[path]}")
        return None

    def existing_files(self) -> set[str]:
        """Paths that exist at this point, as far as the graph knows."""
        paths = set(self.baseline) | set(self.latest)
        return {path for path in paths
                if not (self._latest_node(path) or {}).get("deleted", False)}

    def current_version(self, path: str, call: Call) -> str:
        """Node id of the latest version of path, creating it on first use."""
        if path not in self.latest:
            if path in self.baseline:
                self.latest[path] = 0
            else:
                # A file that nothing in the graph created so far.
                self.latest[path] = 1
                self.notes.append(f"C:{call.index} reads {path}, which has no known origin")
        return self._file_node(path, self.latest[path])

    def next_version(self, path: str, sha256: str | None = None) -> str:
        """Node id of a new version of path."""
        self.latest[path] = self.latest[path] + 1 if path in self.latest else 1
        return self._file_node(path, self.latest[path], sha256)

    # -- edges ---------------------------------------------------------------

    def _add_edge(self, src: str, rel: str, dst: str, evidence: list[int],
                  rule: str | None = None) -> None:
        key = (src, rel, dst)
        if key not in self.edges:
            edge: dict[str, Any] = {"src": src, "rel": rel, "dst": dst,
                                    "basis": "inferred" if rule else "recorded", "evidence": []}
            if rule:
                edge["rule"] = rule
            self.edges[key] = edge
        edge = self.edges[key]
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
                self._recorded_file_edges(call, call_id, evidence)
                self._inferred_file_edges(call, call_id, evidence)

        self._reconcile()
        nodes = sorted(self.nodes.values(), key=_node_order)
        edges = sorted(self.edges.values(), key=_edge_order)
        return {
            "schema_version": SCHEMA_VERSION,
            "run": t.run,
            "source": {
                "session_id": t.session_id, "agent": t.agent,
                "agent_version": t.agent_version, "model": t.model,
                "inferred_edges": True,
            },
            "nodes": nodes,
            "edges": edges,
        }

    def _recorded_file_edges(self, call: Call, call_id: str, evidence: list[int]) -> None:
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

    def _inferred_file_edges(self, call: Call, call_id: str, evidence: list[int]) -> None:
        """Patterns 8 and 9: file operations inferred for shell and grep calls."""
        if call.tool == "grep":
            for name in grep_output_paths(call.output):
                path = normalize_path(name)
                if path in self.existing_files():
                    self._add_edge(self.current_version(path, call), "READ", call_id,
                                   evidence, rule="tool-output")
            return
        if call.tool != "bash" or not isinstance(call.input.get("command"), str):
            return

        analysis = analyze_command(call.input["command"], self.existing_files(), call.exit_code)
        self.notes.extend(f"C:{call.index}: {note}" for note in analysis.notes)
        written: dict[str, str] = {}      # path -> version node this call created

        def read(path: str, rule: str) -> None:
            # A call cannot depend on a version it created itself: data flow
            # inside one call is below the granularity of the graph.
            if path not in written and path in self.existing_files():
                self._add_edge(self.current_version(path, call), "READ", call_id, evidence, rule=rule)

        for op in analysis.ops:
            if op.kind == "read":
                read(op.path, op.rule)
                continue
            sha256 = op.sha256
            if op.copy_of:
                sha256 = (self._latest_node(op.copy_of) or {}).get("sha256")
            if op.path in written:
                node = self.nodes[written[op.path]]
            else:
                if op.kind == "write" and op.append:
                    read(op.path, op.rule)
                written[op.path] = self.next_version(op.path)
                node = self.nodes[written[op.path]]
                self._add_edge(call_id, "WRITE", node["id"], evidence, rule=op.rule)
            node["deleted"] = op.kind == "delete"
            node["sha256"] = None if op.kind == "delete" else sha256

        if "grep" in analysis.programs:
            for name in grep_output_paths(call.output):
                read(normalize_path(name), "tool-output")

    # -- reconciliation with the independent file comparison -----------------

    def _has_writer(self, path: str) -> bool:
        return any(rel == "WRITE" and dst.startswith(f"O:file:{path}@v")
                   for _, rel, dst in self.edges)

    def _reconcile(self) -> None:
        """Compare the graph with the files' real state before and after the run."""
        if self.changes is None:
            self.notes.append("check.json is missing; the graph was not reconciled with file hashes")
            return

        # Rule hash-diff: a file changed but nothing in the graph writes it.
        for path, (_, after) in sorted(self.changes.items()):
            if self._has_writer(path):
                continue
            candidates = [call for call in self.trajectory.calls
                          if call.tool == "bash" and call.status == "completed"
                          and path in str(call.input.get("command", ""))]
            if not candidates:
                self.notes.append(f"{path} changed during the run, and no call explains the change")
                continue
            call = candidates[-1]
            node = self.nodes[self.next_version(path)]
            node["deleted"] = after is None
            self._add_edge(f"C:{call.index}", "WRITE", node["id"], [call.index], rule="hash-diff")

        # Final hashes. check.json covers the workspace only.
        for path in sorted(self.latest):
            if path.startswith("/"):
                continue
            node = self._latest_node(path)
            final = self.changes[path][1] if path in self.changes else self.baseline.get(path)
            if node["version"] == 0:
                continue
            if final is None:
                if not node["deleted"]:
                    self.notes.append(f"{path}: the graph ends with an existing version, "
                                      "but the file is absent at the end of the run")
            elif node["deleted"]:
                self.notes.append(f"{path}: the graph ends with a deletion, "
                                  "but the file exists at the end of the run")
            elif node["sha256"] is None:
                # Taken on the assumption that the graph's last version is the
                # file's final state; an unseen later change would break this.
                node["sha256"] = final
            elif node["sha256"] != final:
                self.notes.append(f"{path}: the final content differs from the last version "
                                  "in the graph, so a later modification was not captured")
            if path not in self.changes and path in self.baseline:
                self.notes.append(f"{path}: written during the run, but its final content "
                                  "equals the baseline")


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


_ALLOWED_SHAPES = {
    ("prompt", "READ", "turn"),     # pattern 1
    ("turn", "NEXT", "turn"),       # pattern 2
    ("turn", "EXEC", "call"),       # pattern 3
    ("call", "WRITE", "result"),    # pattern 4
    ("result", "READ", "turn"),     # pattern 5
    ("file", "READ", "call"),       # patterns 6 and 8
    ("call", "WRITE", "file"),      # patterns 7 and 9
}
_RULES = {"command-text", "known-script", "tool-output", "hash-diff"}


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
        if edge["basis"] == "inferred" and edge.get("rule") not in _RULES:
            problems.append(f"inferred edge without a known rule: {label}")
        if edge["basis"] == "recorded" and "rule" in edge:
            problems.append(f"recorded edge with a rule: {label}")
        if edge["evidence"] != sorted(set(edge["evidence"])):
            problems.append(f"evidence not ascending in {label}")
        if (kinds[src], rel, kinds[dst]) not in _ALLOWED_SHAPES:
            problems.append(f"edge shape not allowed: {label}")
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


def build_run(run_dir: str | Path) -> tuple[dict[str, Any], list[str]]:
    """Build the graph of one run. Returns the graph and notes on what it cannot explain."""
    run_dir = Path(run_dir)
    trajectory = load_run(run_dir)
    baseline = json.loads((run_dir / "baseline.json").read_text(encoding="utf-8"))
    changes = None
    check_path = run_dir / "check.json"
    if check_path.is_file():
        check = json.loads(check_path.read_text(encoding="utf-8"))
        changes = {item["path"]: (item["before"], item["after"]) for item in check["changes"]}
    builder = GraphBuilder(trajectory, baseline, changes)
    graph = builder.build()
    problems = validate(graph)
    if problems:
        raise ValueError(f"{run_dir.name}: invalid graph: " + "; ".join(problems))
    return graph, list(trajectory.warnings) + builder.notes


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
    inferred = sum(1 for edge in graph["edges"] if edge["basis"] == "inferred")
    node_text = ", ".join(f"{kinds.get(kind, 0)} {kind}" for kind in _KIND_ORDER)
    edge_text = ", ".join(f"{rels.get(rel, 0)} {rel}" for rel in RELATIONS)
    return (f"{graph['run']}: {len(graph['nodes'])} nodes ({node_text}); "
            f"{len(graph['edges'])} edges ({edge_text}; {inferred} inferred)")


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
