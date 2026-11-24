# Provenance Graph Model

*Draft section for the technical design part of the project report.*

*Written against the first eight runs, which are kept with their graphs at tag `partb-v1`. The numbers and the figures of run-001 and run-006 below refer to those runs. The last section describes what the matched dataset, `run-030` to `run-039`, added to the model. The current specification is `docs/graph-format.md`.*

This section describes how we turn the recorded execution of an LLM agent into a provenance graph. It covers what the graph borrows from the system provenance model of Module 2, where an agent differs from an operating system, and the three extensions we made because of those differences. The graph is the input to the detection and tracking analyses in the next section.

## From audit logs to agent trajectories

In Module 2, provenance starts from an audit log: one record per system call, naming a process, an operation, and an object. Homework 2 built a graph from such a log with two kinds of nodes, processes and objects, and three kinds of edges: `EXEC` from a parent process to a child, `READ` from an object to a process, and `WRITE` from a process to an object.

An agent run leaves a comparable log. OpenCode exports a session in which each model response lists the tool calls it issued, with their arguments and the text each call returned. We map this onto the Homework 2 model directly:

| System provenance | Agent provenance |
| --- | --- |
| Process | Turn: one model response |
| Child process created by `execve` | Tool call issued by a turn |
| File or socket | Object: the user's prompt, a version of a file, or the text a tool call returned |
| `EXEC`, parent → child | `EXEC`, turn → tool call |
| `READ`, object → process | `READ`, file → tool call; prompt or tool result → turn |
| `WRITE`, process → object | `WRITE`, tool call → file; tool call → its result |

We add one relation, `NEXT`, from each turn to the following one. A model has no memory between responses other than its context, and the context of a turn contains everything the previous turn saw and produced. `NEXT` records that carry-over.

One decision in this mapping matters for everything built on it. A tool result is read by the turn *after* the one that issued the call, because the issuing turn had finished generating its output before the tool ran. With this rule every edge points forward in time and the graph is acyclic. The statement "X could have influenced Y" then has an exact meaning: there is a path from X to Y. Tracking needs no timestamp comparison, and a file read in the same turn as a write can never appear as a cause of that write.

Figure 1 shows the graph of a normal run. Time runs left to right. Each file is a horizontal lane; a call that reads a file puts an open circle on its lane, and a call that writes it puts a filled square there.

![Provenance graph of run-001](../figures/run-001.svg)

*Figure 1. Provenance graph of run-001, a run with no injection. The agent reads the skill and the project files, runs the tests (C9), edits the implementation (C10, creating version 1 of `src/expense_summary.py`), verifies, and writes its report (C13).*

## Three extensions

### File versions

Homework 2 merged all activity on a path into one object node. For forensics on an agent that is too coarse: the agent reads a file, edits it, and reads it again, and we need to know which content each read saw. Every write therefore creates a new version node, `path@v1`, `path@v2`, and so on, and a read links to the version that was current at that call. In Figure 1, the test run C9 reads version 0 of the implementation and the test run C11 reads version 1.

Versioning is also what keeps the graph acyclic. With one node per path, a call that edits a file both reads and writes the same node.

### Trust labels

A system provenance graph does not say which objects an administrator trusts; that knowledge sits outside the graph. For prompt injection the distinction is the whole question, so we attach it to every object as a label with four values: `user` for the task prompt, `skill` for skill files the user installed, `workspace` for files that were already in the project, and `derived` for everything produced during the run, including every later file version.

The label states where an object came from. It is a recorded fact, taken from the file list captured before the run, and not a judgment about whether content is malicious. This keeps the graph free of ground truth: it contains no scenario name and no marker for the injected file. The analysis uses the labels to separate what the user supplied from what the workspace supplied.

### Inferred edges

The largest gap between the two settings is the observation boundary. A kernel audit log sees every `read` and `write`. An agent trajectory sees a tool call. For the agent's file tools that is enough: a `read` or `edit` call names its file. A shell command is opaque. The trajectory records `python3 tools/run_tests.py` and its output, and nothing about the test runner reading the tests, the implementation, and a notes file that it prints.

This gap is not a detail. In the tool-output injection scenario the payload sits in that notes file and reaches the model only through the test runner's output. A graph built from recorded edges alone has no path from the payload to the model.

We close the gap with edges inferred from the command text, each marked `inferred` and labeled with the rule that produced it:

- **`command-text`**: the command names the file as something it reads or writes, through a program argument, a redirection, `tee`, `mv`, `cp`, `rm`, or a Python import or literal path.
- **`known-script`**: declared behavior of a script in the workspace, written down from reading its source.
- **`tool-output`**: `grep` printed the path as a file with matching lines.
- **`hash-diff`**: a fallback for a file that changed with no other explanation.

The rules are deliberately asymmetric. Reads are over-approximated, because a missing read hides a possible cause. Writes are added only with support, because a spurious write to a protected file would be a false accusation. In run-006 the agent issued a command whose inline Python would have overwritten the test file, but the interpreter stopped on a syntax error before running anything. We infer no write for it and report the case instead.

This corresponds to the choice between kernel-level and application-level logging in Module 2. The trajectory is the application-level log, and the inference rules stand in for the finer instrumentation we do not have.

## Checking the graph against an independent record

Inferred edges are only useful if they are right, so we check them. The experiment harness hashes every workspace file before and after a run, independently of the trajectory. After building a graph we reconcile it with that record. Table 1 summarizes the eight runs collected so far.

| Run | Nodes | Edges | Inferred edges | Files changed | Changes explained |
| --- | --- | --- | --- | --- | --- |
| 001 | 47 | 71 | 13 | 2 | 2 |
| 002 | 65 | 104 | 20 | 2 | 2 |
| 003 | 65 | 103 | 23 | 3 | 3 |
| 004 | 71 | 108 | 18 | 2 | 2 |
| 005 | 55 | 82 | 13 | 1 | 1 |
| 006 | 129 | 216 | 52 | 2 | 2 |
| 007 | 26 | 33 | 6 | 0 | 0 |
| 008 | 54 | 72 | 8 | 1 | 1 |

*Table 1. Graph sizes and reconciliation. A change is explained when the graph contains a call that writes the file and the last version in the graph is the file's final state.*

All 13 files that changed across the runs have a writer in the graph, and the `hash-diff` fallback was never needed. For three of the 13, the final state was produced by a shell command and is explained only by an inferred edge.

The stronger check uses content hashes. For six file versions the trajectory contains the written content itself, so the graph can compute the hash without consulting the independent record: four reports written with the `write` tool, one report written through a shell here-document, and one file moved into place with `mv`. All six computed hashes equal the independent final hash. The last case is the unauthorized change in run-006: the agent wrote a replacement test file under another name and then moved it over the protected one. The trajectory records only the text of the `mv` command, and the matching hash confirms that the inferred write is what happened.

## What the graph shows for the unauthorized edit

In run-006 the project notes contained an injected instruction, and the agent edited the protected test file. Figure 2 shows everything in the graph that has a path to the first of those edits.

![Backward slice of run-006](../figures/run-006-backward-slice.svg)

*Figure 2. Backward slice from version 1 of `tests/test_expense_summary.py` in run-006. C12 is the first unauthorized edit; C2 is the call that read the injected project notes. Dashed connectors are inferred edges.*

The slice contains 41 of the other 128 nodes: 9 turns, 12 tool calls, 11 tool results, 8 files, and the prompt. It excludes every call issued after the edit, which is the forward-in-time property at work. It includes the injected file, `docs/project-notes.md`, read by C2 in the first turn.

It also shows the limit of reachability. The edit has nine possible sources: the user's prompt, one skill file, and seven workspace files. Three of the seven are present only because of inferred edges. Reachability cannot say which of the nine caused the edit, because the model's context accumulates: by turn 9 the model had seen all of them. This is the dependency explosion problem of long-running processes from Module 2, in a setting where the "process" never forgets anything. Trust labels narrow the candidates to the seven workspace files, and the next section describes how we go further.

## Limits

- **Shell analysis is heuristic.** The rules handle the constructs that occur in our runs. They do not expand variables, globs, or command substitution, and they do not see paths computed at run time, such as temporary files.
- **Script behavior is declared.** The `known-script` rule depends on a table written for this workload. Another workload needs its own entries, or real instrumentation.
- **Intermediate content is unknown.** We have hashes at the start and the end of a run. A version produced by an `edit` has no recorded content, so its hash is known only when it is the final version.
- **An edge is availability, not influence.** A path into a turn shows that content was in the model's context. Whether it caused a later action is a hypothesis that the analysis must support with further evidence.
- **Eight runs.** The checks above hold for every run we have, but the runs cover one workload, one agent, and two models.

## Implementation

The graph format is specified in `docs/graph-format.md`. The code is in `provenance/`: `trajectory.py` parses a session, `shell.py` infers the file operations of a shell command, `build_graph.py` builds and reconciles the graph, and `render.py` draws the figures. It uses only the Python standard library and has 46 automated checks, including one that compares the builder's output with the worked example in the format document.

```sh
python3 provenance/build_graph.py --all artifact/runs graphs
python3 provenance/render.py graphs/run-031.json /tmp/run-031.svg
python3 -m unittest discover -s provenance
```

## Additions for the matched dataset

The ten runs of the matched dataset brought two situations that the first eight did not contain. Both are version 2 of the format.

**Later user messages.** The collector may send a fixed request to continue in the same session. Each such message is an object that is read by the first turn produced after it arrived, and by no earlier turn. The message therefore cannot appear as a cause of anything the agent did before receiving it.

**Sub-sessions.** In run-039 the agent hands the work to a sub-session through its `task` tool, and the sub-session edits the protected test file. The parent's record shows only the `task` call. The sub-session gets a graph of its own, built from its own session export, and the parent graph attaches the files it read and wrote to the `task` call as inferred edges.

![Protected edit at the task boundary in run-039](../figures/v2-d7/run-039-protected.svg)

*Backward slice from the protected test file in run-039. C2 reads the injected project notes and C3 is the `task` call. The dashed edge from C3 summarizes the sub-session; it does not mean the parent issued an `edit`. The two edits themselves, calls 11 and 12 of the sub-session, are in the sub-session's graph.*

As before, a path in the graph shows that content was available, not that it caused the action.
