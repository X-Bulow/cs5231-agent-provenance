"""Audit stored graphs, source evidence, and final hash provenance for B1/B2."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from build_manifest import ROOT, OUT, read_json, sha

sys.path.insert(0, str(ROOT / "provenance"))
from build_graph import GraphBuilder, build_run, validate
from trajectory import load_run
from runs import select_runs


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    before = read_json(OUT / "audit/b1-b2-original-run-files.json")
    current = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes())
               for p in sorted((ROOT / "artifact/runs").rglob("*")) if p.is_file() and not p.is_symlink()}
    require(before == current, "Raw experiment files changed")
    protocol = read_json(OUT / "protocol-qwen-local-doc-v1.json")
    for name, expected in protocol["input_lock"]["files_sha256"].items():
        require(sha((ROOT / name).read_bytes()) == expected, f"Course source changed: {name}")
    selection = select_runs(ROOT / "artifact/runs")
    require(not selection.ungraphable, "Valid runs lack graphable evidence")
    per_run = []
    for run in selection.graph_runs:
        graph, notes = build_run(run)
        stored_path = ROOT / "graphs" / (run.name + ".json")
        require(read_json(stored_path) == graph, f"Stored graph is stale: {run.name}")
        require(validate(graph) == [], f"Invalid structure: {run.name}")
        nodes = {n["id"]: n for n in graph["nodes"]}
        call_indices = {n["index"] for n in graph["nodes"] if n["kind"] == "call"}
        for edge in graph["edges"]:
            require(set(edge["evidence"]) <= call_indices, f"Unknown evidence call: {run.name}")
            src, dst = nodes[edge["src"]], nodes[edge["dst"]]
            for call, other in ((src, dst), (dst, src)):
                if call["kind"] == "call" and other["kind"] == "file":
                    require(call["status"] == "completed" and call["index"] in edge["evidence"],
                            f"Failed or unsupported file operation: {run.name}/{call['id']}")
        baseline = read_json(run / "baseline.json")
        # Rebuild with final reconciliation disabled. A known hash here cannot
        # have been filled from check.json. It may still come from an initial
        # hash copied along mv/cp, so do not call every such hash a literal write.
        before_check = GraphBuilder(load_run(run), baseline, changes=None).build()
        early = {n["id"]: n for n in before_check["nodes"]}
        writers = {}
        for edge in graph["edges"]:
            if edge["rel"] == "WRITE" and edge["dst"].startswith("O:file:"):
                writers.setdefault(edge["dst"], []).append(edge)
        checked = []
        check = read_json(run / "check.json")
        for item in check["changes"]:
            versions = [n for n in graph["nodes"] if n["kind"] == "file" and n["path"] == item["path"]]
            require(bool(versions), f"Changed file missing: {run.name}/{item['path']}")
            last = max(versions, key=lambda n: n["version"])
            require(last["id"] in writers, f"Writer missing: {last['id']}")
            require(last["sha256"] == item["after"], f"Final hash mismatch: {last['id']}")
            prior = early.get(last["id"], {}).get("sha256")
            if prior is not None:
                require(prior == item["after"], f"Content hash disagrees independently: {last['id']}")
            checked.append({"path": item["path"], "last_version": last["id"], "sha256": item["after"],
                "hash_support": "deletion" if last["deleted"] else "known_before_final_reconciliation" if prior is not None else "filled_from_final_check",
                "writers": [{k: e[k] for k in ("src", "basis", "evidence")} | ({"rule": e["rule"]} if "rule" in e else {}) for e in writers[last["id"]]]})
        unexpected = [note for note in notes if not note.startswith("C:")]
        require(not unexpected, f"Unreconciled state: {run.name}: {unexpected}")
        per_run.append({"run": run.name, "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
            "inferred_edges": sum(e["basis"] == "inferred" for e in graph["edges"]),
            "hash_diff_fallback_edges": sum(e.get("rule") == "hash-diff" for e in graph["edges"]),
            "changed_files": checked, "diagnostics": notes, "graph_sha256": sha(stored_path.read_bytes())})
    deltas = []
    for path in sorted((OUT / "audit/b1-b2-original-graphs").glob("run-*.json")):
        stored = ROOT / "graphs" / path.name
        old, new = read_json(path), read_json(stored)
        old_nodes = {n["id"]: n for n in old["nodes"]}
        changed = [{"node": n["id"], "fields": [k for k in sorted(n.keys() | old_nodes.get(n["id"], {}).keys()) if n.get(k) != old_nodes.get(n["id"], {}).get(k)]}
                   for n in new["nodes"] if n != old_nodes.get(n["id"])]
        deltas.append({"run": path.stem, "byte_identical": path.read_bytes() == stored.read_bytes(),
            "old_sha256": sha(path.read_bytes()), "new_sha256": sha(stored.read_bytes()),
            "edges_unchanged": old["edges"] == new["edges"], "changed_nodes": changed})
    files = [item for run in per_run for item in run["changed_files"]]
    figures = []
    for path in sorted((ROOT / "figures").glob("run-0[1][3-8]*.svg")):
        svg = ET.fromstring(path.read_text())
        require(svg.tag.endswith("}svg"), f"Invalid SVG: {path.name}")
        figures.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path.read_bytes())})
    require(len(figures) == 9, "Expected six new timelines and three slices")
    print(json.dumps({"status": "passed", "phase": "B1/B2", "raw_files_unchanged": len(current),
        "course_source_files_unchanged": len(protocol["input_lock"]["files_sha256"]),
        "graphable_runs": len(selection.graph_runs), "excluded": selection.excluded,
        "ungraphable": selection.ungraphable, "changed_files_with_writers_and_matching_final_state": len(files),
        "final_file_hash_support_counts": {kind: sum(x["hash_support"] == kind for x in files) for kind in
            ("known_before_final_reconciliation", "filled_from_final_check", "deletion")},
        "hash_support_limit": "Known before reconciliation includes literal bytes and propagated initial/earlier hashes; final-check fills are not independent predictions.",
        "existing_graph_comparison": deltas, "figures": figures, "runs": per_run}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
