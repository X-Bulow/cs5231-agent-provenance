"""Verify completed A3 collection without launching agents or rechecking code."""
import json
from collections import Counter
from datetime import datetime

from build_manifest import ROOT, OUT, build, read_json, sha
from a3_record import verify_locks, BATCH, PROTOCOL, RUNTIME


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    protocol = verify_locks()
    protocol_hash = sha(PROTOCOL.read_bytes())
    initial_audit = read_json(OUT / "audit/a1-a2-verification.json")
    require(protocol_hash == initial_audit["protocol_sha256"], "A2 protocol changed")
    for name in ("manifest.json", "manifest.csv"):
        require(sha((OUT / "audit" / ("a1-" + name)).read_bytes()) == initial_audit[name.replace(".", "_") + "_sha256"], "A1 archived output differs")
    original = read_json(OUT / "audit/a1-original-run-files.json")
    old_ids = set(protocol["exclude_from_new_batch"])
    old_current = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes())
                   for name in old_ids for p in (ROOT / "artifact/runs" / name).rglob("*")
                   if p.is_file() and not p.is_symlink()}
    require(old_current == original, "Old runs changed, lost or gained files")
    for name, content in build().items():
        require((OUT / name).read_text() == content, f"Current manifest is stale: {name}")
    rows = {r["run"]: r for r in read_json(OUT / "manifest.json")["runs"]}
    records = [read_json(path) for path in sorted(BATCH.glob("run-*.json"))]
    schedule = protocol["initial_schedule"]
    require([r["run"] for r in records] == [s["proposed_run"] for s in schedule], "This batch requires review for replacements or missing records")
    counts = Counter()
    attempts = Counter()
    previous_end = None
    per_run = []
    for record, slot in zip(records, schedule):
        name = record["run"]
        require(record["state"] == "collected_checked_valid", f"Unfinished or uncertain run: {name}")
        require(record["condition"] == slot["condition"] and record["slot"] == slot["slot"], "Order/condition differs")
        require(record["protocol_sha256"] == protocol_hash, "Per-run protocol changed")
        require(record["actual_models"] == [protocol["model"]], "Wrong actual model")
        require(record["baseline_sha256"] == protocol["input_lock"]["expected_baseline_canonical_sha256"][record["condition"]], "Initial state mismatch")
        require(record["prompt_sha256"] == protocol["input_lock"]["prompt_sha256"], "Prompt mismatch")
        require(record["sandbox_normalized_sha256"] == protocol["sandbox_lock"]["normalized_template_sha256"], "Sandbox semantics differ")
        run = ROOT / "artifact/runs" / name
        require(sha((RUNTIME / (name + ".sb")).read_bytes()) == record["sandbox_sha256"], "Run sandbox changed after collection")
        for filename, expected in record["raw_files_sha256"].items():
            require(sha((run / filename).read_bytes()) == expected, f"Collected raw file changed: {name}/{filename}")
        execution = read_json(run / "execution.json")
        start, end = [datetime.fromisoformat(execution[key]) for key in ("started_at", "ended_at")]
        require(start < end and (previous_end is None or previous_end <= start), "Runs overlap or timestamps are inconsistent")
        previous_end = end
        require(execution["timeout_seconds"] == protocol["timeout_seconds"]["collector"], "Timeout changed")
        row = rows[name]
        require(row["valid_model_run"] and row["workspace_matches_saved_check"] and row["event_session_call_ids_agree"], "Invalid or inconsistent collected evidence")
        require(row["saved_independent_checks_total"] == 9, "Independent check did not cover nine cases")
        counts[record["condition"]] += 1
        attempts[record["condition"]] += 1
        per_run.append({"run": name, "condition": record["condition"],
            "started_at": execution["started_at"], "ended_at": execution["ended_at"],
            "elapsed_seconds": round((end - start).total_seconds(), 3),
            "json_events": row["json_events"], "tool_calls": row["tool_calls"],
            "independent_checks_passed": row["saved_independent_checks_passed"], "independent_checks_total": 9,
            "protected_paths_changed": row["protected_paths_changed"], "source_changed": row["source_changed"],
            "report_present": row["report_present"], "payload_contact": row["attack_payload_contact"],
            "changed_text_calls": [e["call"] for e in row["changed_text_return_evidence"]],
            "collection_status": record["collection_status"], "valid_model_run": True})
    require(all(counts[c] == protocol["target_valid_runs_per_condition"] for c in protocol["conditions"]), "Collection target not met")
    require(all(attempts[c] <= protocol["max_attempts_per_condition"] for c in protocol["conditions"]), "Attempt cap exceeded")
    require(len(rows) == len(old_ids) + len(records), "Manifest lost or gained an unreviewed run")
    print(json.dumps({"status": "passed", "batch": protocol["protocol_id"], "phase": "A3 collection and independent checks complete; A4 review pending",
        "protocol_sha256": protocol_hash, "unchanged_original_files": len(original),
        "locked_source_files": len(protocol["input_lock"]["files_sha256"]),
        "valid_runs_by_condition": dict(counts), "attempts_by_condition": dict(attempts),
        "replacement_attempts": 0, "runs": per_run,
        "manifest_json_sha256": sha((OUT / "manifest.json").read_bytes()),
        "manifest_csv_sha256": sha((OUT / "manifest.csv").read_bytes())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
