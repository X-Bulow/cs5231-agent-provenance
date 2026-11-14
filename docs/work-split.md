# Proposed Division of Work (for discussion)

This document splits the project into three parts so that each of us can pick one after discussion. The direction and method are described in the [README](../README.md); reading its Sections 1 to 3 first is recommended.

The parts follow the order of the pipeline: **A produces the data, B turns the data into graphs, and C analyzes and evaluates on the graphs.** Each part includes code and the matching report sections, and the workloads are roughly equal.

| | Part A: Experiments and data | Part B: Provenance graph construction | Part C: Analysis and evaluation |
| --- | --- | --- | --- |
| In one sentence | Run the agent to get reliable, matched data | Turn trajectories into a queryable graph | Find the injected source on the graph and evaluate how well this works |
| Main work | Design and run experiments | Write parsing and graph-building code | Write query, scoring, and evaluation code |
| Course material | Module 1: attacks and threat models | Module 2: audit logs and provenance graphs | Module 2: backward and forward tracking, NoDoze |
| Report sections | Problem statement, threat model, experimental setup | Graph model within the technical design | Analysis method within the technical design, evaluation, limitations |
| Estimated effort | About 3 to 4 days | About 3 to 4 days | About 4 days |
| Largest uncertainty | Attack success is not controllable and needs repeated attempts | File operations inside shell commands are not visible | Dependency explosion may make backward tracking too broad |

The estimates are rough and assume a few hours of work per day.

## Part A: Experiments and data

**Goal:** give B and C enough runs that are clearly labeled and properly matched.

**Tasks**

1. **Write down the threat model.** What the attacker controls (document content in the workspace), what the attacker does not control (the user's task, the skills, executable test code), and what the attacker wants (the agent edits protected tests and falsely reports the fix as complete).
2. **Add runs.** Each condition currently has one run. For the four scenarios and two models, repeat each condition several times (5 each is suggested) so that results are not attributable to chance.
3. **Run counterfactual controls.** For conditions where a violation occurred, remove the injection and rerun from the same starting state, as evidence on whether the injection caused the action.
4. **Try payload variants.** Change the wording or placement of the injection and record every change. Keep unsuccessful attempts too. Optional: remove the trust statement at the end of the task instruction and see whether the success rate changes.
5. **Maintain a run manifest.** One table listing each run's number, scenario, model, payload version, and outcome class. The manifest lives under `experiments/`, outside the agent's working directory.
6. **Classify the outcome of every run.** Use the five classes from the project guide: the payload never reached the model; it reached the model and the agent continued the legitimate task; a violation was attempted but blocked; a violation occurred; the task failed for an unrelated reason. Which class run-007 belongs to needs to be established first.

**Deliverables**

- `experiments/manifest.csv`: the run manifest.
- `experiments/payloads/`: payload variants with notes on what changed.
- New run directories, starting at `artifact/runs/run-009`.
- Report sections: problem statement (including the Module 1 analogy in README Section 2.1), threat model, experimental setup.

**Prerequisites:** access to SoC's SoCLaaS models and a local OpenCode installation.

**Suits:** someone willing to run experiments repeatedly and keep careful records. This part has the least code but the most waiting.

## Part B: Provenance graph construction

**Goal:** a program that takes a run directory and outputs a provenance graph in the agreed format.

**Tasks**

1. **Parse the trajectory.** Read `events.jsonl` and `session.json` into one uniform event sequence: each turn, and for each tool call its tool name, arguments, returned text, and time.
2. **Build nodes and edges.** Follow [graph-format.md](graph-format.md): turns `T`, tool calls `C`, objects `O`; edges `EXEC`, `READ`, `WRITE`, `NEXT`. Every edge carries the tool calls that support it.
3. **Version files.** Each write to a file creates a new version node, so that we can tell whether a read saw the content before or after a modification.
4. **Assign trust labels.** Using `baseline.json` and paths, label objects as `user`, `skill`, `workspace`, or `derived`.
5. **Handle the observation boundary.** The trajectory does not record which files a shell command reads or writes internally. Add these edges by parsing the command text and comparing hashes before and after, and mark them `inferred`. Two cases to cover: the `mv` on a test file in run-006, and `run_tests.py` printing `runner-notes.txt` in run-003.
6. **Export and visualize.** Output JSON, and also render the graph (Graphviz or Mermaid) for the report and the presentation.

**Deliverables**

- `provenance/build_graph.py`, used as `python3 provenance/build_graph.py artifact/runs/run-006 graphs/run-006.json`.
- `graphs/run-00X.json`: graphs for the 8 existing runs.
- Rendered graphs for at least run-001 and run-006.
- Report section: the graph model within the technical design, including the Module 2 mapping in README Section 2.2 and the differences from Homework 2 (trust labels, file versions, `inferred` edges).

**Prerequisites:** none; the 8 existing runs are enough to start.

**Suits:** someone who likes writing data-processing code. Experience from building graphs in Homework 2 Part A and B2 carries over directly.

## Part C: Analysis and evaluation

**Goal:** on the graphs produced by B, answer which input led to the unauthorized action and what it contaminated, and show what this method adds over simpler alternatives.

**Tasks**

1. **Detection point.** Implement one rule: any `WRITE` edge outside `src/` and `outputs/` is an alert. Output the list of anchors.
2. **Backward tracking.** Traverse in reverse from an anchor and return the candidate sources, listing those labeled `workspace` first.
3. **Forward tracking.** Traverse forward from a given object, such as the injected document, and return the file versions and reports written afterwards.
4. **Handle dependency explosion.** This is the core of the technical design; see README Section 3.5. Partition by turn; rank candidate sources by content evidence (which source contains the distinctive content found in the action's arguments); combine with the counterfactual runs from A for the final judgment.
5. **Simplified NoDoze.** Using the formula from Homework 2 Part B3, with graphs of normal runs as the reference, compute anomaly scores for the edges and nodes of the run under analysis.
6. **Evaluation.** Three measures: whether the true injected source is in the backward-tracking result; how much smaller the returned subgraph is than the full graph; where the true source ranks. Then compare with the baseline of searching a flat log for keywords, with attention to whether the baseline raises a false alarm on `benign-quotation`.

**Deliverables**

- `provenance/detect.py`, `provenance/query.py`, `provenance/score.py`.
- `results/`: anchors, backward subgraphs, rankings, and scores for each run.
- Report sections: the analysis method within the technical design, evaluation results, limitations.

**Prerequisites:** depends on B's graph format. The format is fixed in [graph-format.md](graph-format.md), so C can develop against the run-006 excerpt given there without waiting for B.

**Suits:** someone comfortable with algorithms and the course papers (BackTracker, BEEP, NoDoze). This is conceptually the hardest part and maps most directly onto the 10 marks for technical design.

## Interfaces between the parts

To work in parallel, we fix two interfaces up front:

- **A → B:** the run directory format. It is already fixed by the artifact's scripts and needs no further discussion.
- **B → C:** the JSON format of the graph. It is specified in [graph-format.md](graph-format.md), which lists every node and edge field, shows how Part C is expected to use the graph, and includes a worked excerpt from run-006.

## Shared work

These belong to no single part and are done together:

- **Report integration:** merge the sections from the three parts into one report with consistent terminology and figures. One person should own the final edit.
- **Presentation:** 2026-11-25 (Wednesday) 19:00, not graded; a video may be submitted instead.
- **Individual reports:** written by each person, 5 marks, describing individual contribution. Ideas and analysis not adopted by the team can be included.

## Suggested schedule

| Date | Target |
| --- | --- |
| Nov 15 (Sun) | Discuss this document, choose parts, raise any objections to the graph JSON format |
| Nov 18 (Wed) | Full pipeline working on run-006: build the graph, detect the anchor, track back to the injected source |
| Nov 22 (Sun) | A's additional experiments finished; C's evaluation numbers available |
| Nov 24 (Tue) | Report draft and presentation material finished |
| Nov 25 (Wed) | Presentation at 19:00 |

The Nov 18 target matters most: the sooner the pipeline works on one run, the sooner we find out whether the method has problems.

## To decide in discussion

1. Who takes which part, and who owns the final edit of the report.
2. Whether anyone needs a change to the graph JSON format in [graph-format.md](graph-format.md).
3. How many repetitions per condition. More repetitions give more reliable conclusions but take more time.
4. The report deadline. The course slides do not state one; it needs to be confirmed with the instructor.
5. If the group has four people: Part C can be split in two, with one person on the tracking queries (tasks 1 to 4) and one on anomaly scoring and evaluation (tasks 5 and 6).
