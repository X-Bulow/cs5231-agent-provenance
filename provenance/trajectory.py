"""Parse a recorded agent run into turns and tool calls.

This is the first stage of graph construction. It reads the native OpenCode
session export of one run and returns a uniform, machine-independent view of
it; it creates no graph nodes or edges yet.

Numbering follows docs/graph-format.md:
  * turns are numbered from 1 in the order of assistant messages;
  * tool calls are numbered from 1 across the whole session, in the order
    session.json lists them (the order in which the model issued them);
  * the absolute workspace prefix is stripped from every recorded string.

Everything else is kept as recorded. In particular the prompt is verbatim,
including the quotation marks the OpenCode CLI stores around it.

Usage:
    python3 provenance/trajectory.py artifact/runs/run-030
    python3 provenance/trajectory.py artifact/runs/run-030 --calls
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Call:
    """One tool call issued by a turn."""

    index: int                 # k, 1-based across the session
    turn: int                  # index of the turn that issued the call
    tool: str
    call_id: str
    status: str                # "completed" or "error"
    input: dict[str, Any]      # recorded arguments, workspace prefix stripped
    output: str                # text returned to the model (error text on failure)
    truncated: bool
    exit_code: int | None      # bash only
    time_start: int | None     # milliseconds since the epoch
    time_end: int | None
    raw_input: dict[str, Any] | None = None  # source bytes for content hashing, not graph display
    raw_output: str | None = None


@dataclass
class Turn:
    """One model response (one assistant message)."""

    index: int                 # n, 1-based
    message_id: str
    calls: list[int]           # indexes of the calls this turn issued
    text: str
    reasoning: str
    time_start: int | None
    time_end: int | None


@dataclass
class UserMessage:
    index: int
    message_id: str
    before_turn: int           # first assistant turn after arrival; may be len(turns)+1
    text: str
    raw_text: str
    time_start: int | None


@dataclass
class Trajectory:
    run: str
    session_id: str
    agent: str
    agent_version: str
    model: str
    prompt: str
    turns: list[Turn]
    calls: list[Call]
    warnings: list[str] = field(default_factory=list)
    normalization_notes: list[str] = field(default_factory=list)
    user_messages: list[UserMessage] = field(default_factory=list)
    delegated: dict[int, Trajectory] = field(default_factory=dict)


def strip_prefix(value: Any, prefix: str) -> Any:
    """Normalize only known workspace-prefix spellings, never URL-decode text.

    Spaces within this exact prefix may be literal, %20, or backslash-escaped;
    a path component may be shell-quoted. This is an analysis representation,
    not evidence that the original command was valid or executed successfully.
    The original session is untouched; Call.raw_input preserves write content.
    """
    if isinstance(value, str):
        parts = []
        for component in prefix.rstrip("/").split("/"):
            escaped = re.escape(component).replace(r"\ ", r"(?: |%20|\\+ )")
            parts.append(f"(?:{escaped}|'{escaped}'|\"{escaped}\")" if component else "")
        pattern = "/".join(parts)
        # Do not rewrite a sibling whose name merely starts with 'workspace'.
        return re.sub(pattern + r"(/|(?=$|[\s'\"<>),;:]))",
                      lambda match: "" if match.group(1) == "/" else ".", value)
    if isinstance(value, list):
        return [strip_prefix(item, prefix) for item in value]
    if isinstance(value, dict):
        return {key: strip_prefix(item, prefix) for key, item in value.items()}
    return value


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _event_call_ids(path: Path) -> list[str]:
    """Call ids of the tool_use records in events.jsonl, in order."""
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if isinstance(event, dict) and event.get("type") == "tool_use":
            ids.append(event.get("part", {}).get("callID"))
    return ids


def load_run(run_dir: str | Path, *, session_path: Path | None = None) -> Trajectory:
    """Read one run directory and return its turns and tool calls."""
    run_dir = Path(run_dir).resolve()
    session = _load_json(session_path or run_dir / "session.json")
    info = session["info"]
    prefix = info["directory"].rstrip("/")
    warnings: list[str] = []

    execution_path = run_dir / "execution.json"
    execution = _load_json(execution_path) if execution_path.is_file() else {}
    if not execution:
        warnings.append("execution.json is missing; agent and model taken from session.json")
    recorded_model = info.get("model", {})
    model = execution.get("model") or "/".join(
        part for part in (recorded_model.get("providerID"), recorded_model.get("id")) if part)

    prompt_parts: list[str] = []
    user_messages: list[UserMessage] = []
    turns: list[Turn] = []
    calls: list[Call] = []

    for message in session["messages"]:
        role = message["info"].get("role")
        parts = message.get("parts", [])
        if role == "user":
            text = "\n".join(part.get("text", "") for part in parts if part.get("type") == "text")
            user_messages.append(UserMessage(len(user_messages)+1, message['info'].get('id',''),
                len(turns)+1, strip_prefix(text,prefix), text,
                (message['info'].get('time') or {}).get('created')))
            # Backward-compatible initial prompt, never future continuation text.
            if len(user_messages) == 1:
                prompt_parts.append(text)
            continue
        if role != "assistant":
            warnings.append(f"ignored message with role {role!r}")
            continue

        turn_index = len(turns) + 1
        text: list[str] = []
        reasoning: list[str] = []
        issued: list[int] = []
        for part in parts:
            kind = part.get("type")
            if kind == "text":
                text.append(part.get("text", ""))
            elif kind == "reasoning":
                reasoning.append(part.get("text", ""))
            elif kind == "tool":
                state = part.get("state", {})
                metadata = state.get("metadata") or {}
                times = state.get("time") or {}
                status = state.get("status", "")
                # A failed call records its message under "error", not "output".
                raw_output = state.get("output") if status == "completed" else state.get("error")
                call = Call(
                    index=len(calls) + 1,
                    turn=turn_index,
                    tool=part.get("tool", ""),
                    call_id=part.get("callID", ""),
                    status=status,
                    input=strip_prefix(state.get("input") or {}, prefix),
                    output=strip_prefix(raw_output or "", prefix),
                    truncated=bool(metadata.get("truncated", False)),
                    exit_code=metadata.get("exit") if part.get("tool") == "bash" else None,
                    time_start=times.get("start"),
                    time_end=times.get("end"),
                    raw_input=state.get("input") or {},
                    raw_output=raw_output or "",
                )
                calls.append(call)
                issued.append(call.index)

        message_times = message["info"].get("time") or {}
        turns.append(Turn(
            index=turn_index,
            message_id=message["info"].get("id", ""),
            calls=issued,
            text=strip_prefix("\n".join(text), prefix),
            reasoning=strip_prefix("\n".join(reasoning), prefix),
            time_start=message_times.get("created"),
            time_end=message_times.get("completed"),
        ))

    if not prompt_parts:
        warnings.append("no user message found; prompt is empty")
    for call in calls:
        if call.status not in ("completed", "error"):
            warnings.append(f"call {call.index} has unexpected status {call.status!r}")

    # The event stream is an independent record of the same session. Calls
    # issued by one turn run concurrently and are logged as they finish, so the
    # two records may order them differently within a turn, never across turns.
    events_path = run_dir / "events.jsonl"
    if session_path is not None:
        warnings.append('delegated session has no independent events.jsonl stream')
    elif events_path.is_file():
        turn_of = {call.call_id: call.turn for call in calls}
        event_ids = _event_call_ids(events_path)
        if sorted(event_ids, key=str) != sorted(turn_of, key=str):
            warnings.append("events.jsonl and session.json record different tool calls")
        else:
            event_turns = [turn_of[call_id] for call_id in event_ids]
            if event_turns != sorted(event_turns):
                warnings.append("events.jsonl orders tool calls across turns differently from session.json")
    else:
        warnings.append("events.jsonl is missing; no cross-check performed")

    normalization_notes = []
    marker = run_dir.name + "/workspace"
    for call in calls:
        if marker in json.dumps(call.input) or marker in call.output:
            normalization_notes.append(
                f"C:{call.index}: unresolved workspace path expression retained; see raw session")
    trajectory = Trajectory(
        run=run_dir.name,
        session_id=info.get("id", ""),
        agent=execution.get("agent", "opencode"),
        agent_version=execution.get("agent_version") or info.get("version", ""),
        model=model,
        prompt=strip_prefix("\n".join(prompt_parts), prefix),
        turns=turns,
        calls=calls,
        warnings=warnings,
        normalization_notes=normalization_notes,
        user_messages=user_messages,
    )
    if session_path is None:
        index_path=run_dir.parents[2] / 'experiments/delegated-sessions.json'
        refs=_load_json(index_path).get('runs',{}).get(run_dir.name,[]) if index_path.exists() else []
        by_call={ref['parent_call_id']:ref for ref in refs}
        if len(by_call)!=len(refs):
            raise ValueError('Duplicate delegated-session references')
        used=set()
        for call in calls:
            if call.tool!='task' or call.status!='completed':
                continue
            part=next(p for m in session['messages'] for p in m.get('parts',[]) if p.get('type')=='tool' and p.get('callID')==call.call_id)
            child_id=(part['state'].get('metadata') or {}).get('sessionId')
            if not child_id:
                continue
            if call.call_id not in by_call:
                raise ValueError('Completed delegated session needs reviewed native export: '+child_id)
            ref=by_call[call.call_id];path=(run_dir.parents[2]/ref['path']).resolve()
            if not path.is_relative_to(run_dir.parents[2]) or hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:
                raise ValueError('Missing or stale delegated session evidence')
            child=_load_json(path)
            if child['info']['id']!=child_id or child['info'].get('parentID')!=info['id'] or ref['session_id']!=child_id:
                raise ValueError('Delegated session identity mismatch')
            parsed=load_run(run_dir,session_path=path)
            if child['info']['directory']!=info['directory']:
                raise ValueError('Delegated workspace differs')
            for child_call in parsed.calls:
                if child_call.time_start is not None and call.time_start is not None and child_call.time_start<call.time_start:
                    raise ValueError('Delegated operation predates parent task')
                if child_call.time_end is not None and call.time_end is not None and child_call.time_end>call.time_end:
                    raise ValueError('Delegated operation outlives parent task')
            trajectory.delegated[call.index]=parsed
            used.add(call.call_id)
        if used!=set(by_call):
            raise ValueError('Unused delegated session reference')
    return trajectory


def call_target(call: Call) -> str:
    """The most informative argument of a call, on one line, for display."""
    for key in ("filePath", "command", "pattern", "name"):
        if key in call.input:
            return " ".join(str(call.input[key]).split())
    return json.dumps(call.input, sort_keys=True)


def _counts(counter: Counter) -> str:
    return ", ".join(f"{key} {count}" for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def summarize(trajectory: Trajectory) -> str:
    lines = [
        f"run:        {trajectory.run}",
        f"model:      {trajectory.model}",
        f"agent:      {trajectory.agent} {trajectory.agent_version}",
        f"prompt:     {len(trajectory.prompt)} characters",
        f"turns:      {len(trajectory.turns)}",
        f"calls:      {len(trajectory.calls)}",
        f"status:     {_counts(Counter(call.status for call in trajectory.calls))}",
        f"tools:      {_counts(Counter(call.tool for call in trajectory.calls))}",
        f"calls/turn: {_counts(Counter(len(turn.calls) for turn in trajectory.turns))}",
    ]
    lines.extend(f"warning:    {warning}" for warning in trajectory.warnings)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a recorded agent run into turns and tool calls.")
    parser.add_argument("run", type=Path, help="run directory, e.g. artifact/runs/run-030")
    parser.add_argument("--calls", action="store_true", help="also list every tool call")
    args = parser.parse_args()
    if not (args.run / "session.json").is_file():
        parser.error(f"{args.run} has no session.json")

    trajectory = load_run(args.run)
    print(summarize(trajectory))
    if args.calls:
        print()
        for call in trajectory.calls:
            print(f"C:{call.index:<3} T:{call.turn:<3} {call.tool:<9} {call.status:<9} {call_target(call)[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
