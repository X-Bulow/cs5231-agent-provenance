"""Select graphable runs using the reviewed inventory, never scenario labels.

Missing, unreviewed or stale records are errors. Explicit infrastructure
failures and valid responses without an exported session are reported apart.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunSelection:
    graph_runs: list[Path]
    excluded: dict[str, str]
    ungraphable: dict[str, str]


def select_runs(runs: str | Path, manifest: str | Path | None = None) -> RunSelection:
    runs = Path(runs).resolve()
    root = runs.parent.parent
    manifest = Path(manifest) if manifest else root / "experiments/manifest.json"
    inventory = json.loads(manifest.read_text(encoding="utf-8"))
    rows = inventory["runs"]
    names = [row["run"] for row in rows]
    if len(set(names)) != len(names) or any(not re.fullmatch(r"run-\d+", name) for name in names):
        raise ValueError("Invalid or duplicate run IDs in manifest")
    actual = {p.name for p in runs.glob("run-*") if p.is_dir()}
    if actual != set(names):
        raise ValueError(f"Run set differs from manifest: unreviewed={sorted(actual-set(names))}; missing={sorted(set(names)-actual)}")
    result = RunSelection([], {}, {})
    for row in sorted(rows, key=lambda r: r["run"]):
        run = runs / row["run"]
        for name in ("execution.json", "baseline.json", "check.json", "prompt.txt", "events.jsonl"):
            path = run / name
            expected = row["evidence_sha256"].get(path.relative_to(root).as_posix())
            if not path.is_file() or expected is None or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"{run.name}: missing or stale inventory evidence: {name}")
        session = run / "session.json"
        if row["valid_model_run"] is False:
            if session.exists():
                raise ValueError(f"{run.name}: excluded run unexpectedly has a session; review validity")
            if row["validity"] != "infrastructure_failure_before_model_response":
                raise ValueError(f"{run.name}: exclusion needs an explicit reviewed reason")
            result.excluded[run.name] = row["validity"]
        elif row["valid_model_run"] is True:
            if row["session_present"] is False:
                if session.exists():
                    raise ValueError(f"{run.name}: session appeared after review")
                result.ungraphable[run.name] = "valid model response, native session export unavailable"
                continue
            expected = row["evidence_sha256"].get(session.relative_to(root).as_posix())
            if not session.is_file() or expected is None or hashlib.sha256(session.read_bytes()).hexdigest() != expected:
                raise ValueError(f"{run.name}: missing or stale required session.json")
            json.loads(session.read_text(encoding="utf-8"))
            result.graph_runs.append(run)
        else:
            raise ValueError(f"{run.name}: model-run validity is unknown; review before analysis")
    return result
