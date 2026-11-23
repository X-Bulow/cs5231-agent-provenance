"""Prepare or finalize ONE A3 run; never launch a model or advance the schedule.

Collection uses the unmodified course collect.py in a separate command.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from build_manifest import ROOT, OUT, canonical_sha, sha, read_json

RUNTIME = ROOT.parent / ".experiment-env"
PROTOCOL = OUT / "protocol-qwen-local-doc-v1.json"
BATCH = OUT / "batches/qwen-local-doc-v1"


def now():
    return datetime.now(ZoneInfo("Asia/Singapore")).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def verify_locks():
    protocol = read_json(PROTOCOL)
    for name, expected in protocol["input_lock"]["files_sha256"].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"Locked input changed: {name}")
    if sha((RUNTIME / "config/opencode/opencode.json").read_bytes()) != protocol["generation_settings"]["local_noncredential_config_sha256"]:
        raise ValueError("Noncredential configuration changed; pause batch")
    if sha((RUNTIME / "run-012.sb").read_bytes()) != protocol["sandbox_lock"]["template_sha256"]:
        raise ValueError("Sandbox template changed; pause batch")
    if read_json(RUNTIME / "opencode/node_modules/opencode-ai/package.json")["version"] != protocol["agent_version"]:
        raise ValueError("OpenCode version differs")
    if platform.python_version() != protocol["local_python_version"]:
        raise ValueError("Python version differs")
    original = read_json(OUT / "audit/a1-original-run-files.json")
    for name, expected in original.items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"Original run file changed: {name}")
    return protocol


def prepare(name):
    protocol = verify_locks()
    slots = {s["proposed_run"]: s for s in protocol["initial_schedule"]}
    if name not in slots:
        raise ValueError("Replacement run needs explicit protocol-based assignment")
    slot = slots[name]
    records = sorted(BATCH.glob("run-*.json"))
    if len(records) != slot["slot"] - 1:
        raise ValueError("Previous planned runs must be finalized first")
    for path in records:
        previous = read_json(path)
        if previous["state"] != "collected_checked_valid":
            raise ValueError("Previous run needs review before advancing")
    run = ROOT / "artifact/runs" / name
    if run.exists() or (BATCH / (name + ".json")).exists() or (RUNTIME / (name + ".sb")).exists():
        raise ValueError("Run, record or sandbox already exists; never overwrite")
    # Preserve A1 outputs before they are extended for the new batch.
    for filename in ("manifest.json", "manifest.csv", "review-notes.json"):
        target = OUT / "audit" / ("a1-" + filename)
        if not target.exists():
            target.write_bytes((OUT / filename).read_bytes())
    subprocess.run([sys.executable, "-B", str(ROOT / "artifact/scripts/prepare.py"),
                    slot["condition"], "--output", str(run)], check=True)
    baseline = read_json(run / "baseline.json")
    if baseline != protocol["input_lock"]["expected_initial_file_hashes"][slot["condition"]]:
        raise ValueError("Prepared initial state differs; preserve and pause")
    if sha((run / "prompt.txt").read_bytes()) != protocol["input_lock"]["prompt_sha256"]:
        raise ValueError("Prepared task differs; preserve and pause")
    sandbox = (RUNTIME / "run-012.sb").read_text().replace("run-012", name)
    (RUNTIME / (name + ".sb")).write_text(sandbox)
    record = {
        "run": name, "protocol_id": protocol["protocol_id"], "protocol_sha256": sha(PROTOCOL.read_bytes()),
        "condition": slot["condition"], "slot": slot["slot"], "state": "prepared_not_collected",
        "prepared_at": now(), "environment_group": "local-2026-11-23-sandbox",
        "batch_group": protocol["protocol_id"], "model": protocol["model"], "agent_version": protocol["agent_version"],
        "python_version": platform.python_version(), "additional_os_sandbox": True,
        "prompt_sha256": sha((run / "prompt.txt").read_bytes()), "baseline_sha256": canonical_sha(baseline),
        "input_locks_verified": True,
        "local_noncredential_config_sha256": protocol["generation_settings"]["local_noncredential_config_sha256"],
        "sandbox_profile": "../.experiment-env/" + name + ".sb", "sandbox_sha256": sha(sandbox.encode()),
        "sandbox_normalized_sha256": sha(sandbox.replace(name, "__RUN__").encode()),
        "generation_parameters": "Implicit defaults not archived per request; unchanged local configuration",
        "backend_revision": "unknown", "timeout_seconds": protocol["timeout_seconds"]["collector"],
        "evidence_location": f"artifact/runs/{name}",
    }
    if record["sandbox_normalized_sha256"] != protocol["sandbox_lock"]["normalized_template_sha256"]:
        raise ValueError("Derived sandbox differs beyond run identifier")
    write_json(BATCH / (name + ".json"), record)
    print(json.dumps({"run": name, "condition": slot["condition"], "status": record["state"]}))


def finish(name):
    protocol = verify_locks()
    path = BATCH / (name + ".json")
    record = read_json(path)
    run = ROOT / "artifact/runs" / name
    if record["state"] != "prepared_not_collected":
        raise ValueError("Already finalized; inspect instead of overwriting")
    if sha(PROTOCOL.read_bytes()) != record["protocol_sha256"]:
        raise ValueError("Protocol changed during run")
    if sha((RUNTIME / (name + ".sb")).read_bytes()) != record["sandbox_sha256"]:
        raise ValueError("Run sandbox changed")
    execution = read_json(run / "execution.json")
    if execution.get("status") == "running":
        raise ValueError("Collection is still running")
    # check.py writes only this fresh run's check.json, and runs a source COPY.
    if (run / "check.json").exists():
        raise ValueError("Existing independent check must not be overwritten")
    result = subprocess.run([sys.executable, "-B", str(ROOT / "artifact/scripts/check.py"), str(run)], capture_output=True, text=True)
    (BATCH / (name + "-check.log")).write_text(result.stdout + result.stderr)
    if result.returncode not in (0, 1) or not (run / "check.json").is_file():
        record.update(state="pause_checker_failure", checker_exit_code=result.returncode)
        write_json(path, record)
        raise ValueError("Checker failed to produce a result")
    session_path = run / "session.json"
    try:
        session = read_json(session_path)
    except (OSError, json.JSONDecodeError):
        record.update(state="pause_session_review_required", checker_exit_code=result.returncode)
        write_json(path, record)
        raise ValueError("Session export unavailable; review events before any next run")
    turns = [m for m in session["messages"] if m["info"].get("role") == "assistant"]
    actual = sorted({m["info"].get("providerID", "") + "/" + m["info"].get("modelID", "") for m in turns})
    generated = any(p.get("type") in ("text", "reasoning", "tool") for m in turns for p in m.get("parts", []))
    if not generated or actual != [protocol["model"]] or execution["model"] != protocol["model"] or execution["agent_version"] != protocol["agent_version"]:
        record.update(state="pause_model_or_validity_review", actual_models=actual)
        write_json(path, record)
        raise ValueError("Actual model or response validity requires review")
    check = read_json(run / "check.json")
    record.update(state="collected_checked_valid", finalized_at=now(), actual_models=actual,
        valid_model_run=True, collector_exit_code=execution["collector_exit_code"], collection_status=execution["status"],
        checker_exit_code=result.returncode, independent_checks_passed=sum(c["passed"] for c in check["checks"]),
        independent_checks_total=len(check["checks"]), protected_paths_changed=check["protected_paths_changed"],
        changed_paths=[c["path"] for c in check["changes"]],
        source_changed=any(c["path"].startswith("src/") for c in check["changes"]),
        report_present=(run / "workspace/outputs/report.md").is_file(),
        json_events=execution["event_summary"]["json_records"],
        raw_files_sha256={p.name: sha(p.read_bytes()) for p in run.iterdir() if p.is_file()},
        validity_note="真实模型响应；任务与初始状态符合协议。任务结果不用于筛除样本。")
    write_json(path, record)
    reviews_path = OUT / "review-notes.json"
    reviews = read_json(reviews_path)
    if name in reviews["runs"]:
        raise ValueError("Existing review entry must not be overwritten")
    reviews["runs"][name] = {
        "environment_group": record["environment_group"], "role": "fixed-batch-qwen-local-doc-v1",
        "python_version": record["python_version"], "additional_os_sandbox": True,
        "environment_evidence": path.relative_to(ROOT).as_posix(),
        "notes": ["属于A2固定新批次；完整任务与报告真实性待A4审阅，未用结果好坏筛除。"],
    }
    write_json(reviews_path, reviews)
    subprocess.run([sys.executable, "-B", str(OUT / "build_manifest.py")], check=True)
    row = next(r for r in read_json(OUT / "manifest.json")["runs"] if r["run"] == name)
    progress = ROOT.parent / "progress.md"
    entry = (
        f"\n### A3 单次采集完成：{name}（{record['condition']}，{now()}）\n\n"
        f"- 从固定模板准备的新工作区完成真实采集，实际模型核实为 {protocol['model']}；"
        f"采集状态 {execution['status']}，退出码 {execution['collector_exit_code']}，"
        f"{record['json_events']} 条事件，原生会话可解析。配置、源文件和原始历史文件校验保持一致。\n"
        f"- 对本次新运行执行老师 `check.py`，退出码 {result.returncode}；"
        f"独立源码输入检查通过 {record['independent_checks_passed']}/{record['independent_checks_total']}，"
        f"最终受保护变化 {json.dumps(record['protected_paths_changed'], ensure_ascii=False)}，"
        f"源码是否变化 {record['source_changed']}，报告是否存在 {record['report_present']}。"
        "检查器返回 1 是有效实验结果，不因此补跑。\n"
        f"- 完整替换文本的返回调用为 {[e['call'] for e in row['changed_text_return_evidence']]}；"
        f"攻击载荷接触状态为 {row['attack_payload_contact']}。该记录仅表明接触，不证明指令造成动作。\n"
        f"- 原始证据：`cs5231-agent-provenance/artifact/runs/{name}/`；"
        f"环境及检查日志：`experiments/batches/qwen-local-doc-v1/{name}.json` 与 `{name}-check.log`。"
        "本次计入固定批次的有效模型运行；完整任务与报告真实性留待 A4，不在本步骤声称完成。\n"
    )
    progress.write_text(progress.read_text() + entry)
    print(json.dumps({"run": name, "condition": record["condition"], "valid_model_run": True,
        "checks_passed": record["independent_checks_passed"], "checks_total": record["independent_checks_total"],
        "protected_paths_changed": record["protected_paths_changed"],
        "payload_contact": row["attack_payload_contact"], "payload_calls": [e["call"] for e in row["changed_text_return_evidence"]],
        "report_present": record["report_present"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finish"))
    parser.add_argument("run")
    args = parser.parse_args()
    if not __import__("re").fullmatch(r"run-\d{3,}", args.run):
        parser.error("Expected numeric run ID")
    (prepare if args.action == "prepare" else finish)(args.run)


if __name__ == "__main__":
    main()
