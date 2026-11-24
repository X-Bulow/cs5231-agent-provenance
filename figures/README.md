# Figures

## Files

| Path | Content |
| --- | --- |
| `v2-d7/run-NNN.svg` | The full graph of each of the ten runs of the matched dataset, 030 to 039 |
| `v2-d7/run-NNN-protected.svg` | For the four violating runs (031, 032, 035, 039): every node with a path to the first change of the protected test file |
| `v2-d7/run-039-child.svg` | The sub-session of run-039, with its 14 tool calls and the two edits of the test file |
| `run-001.svg`, `run-006.svg`, `run-006-backward-slice.svg` | Graphs of two of the earlier exploratory runs, which are kept at tag `partb-v1` |

`experiments/v2_verify.py` regenerates the files under `v2-d7/`. `provenance/render.py` draws any graph or backward slice.

## How to read a figure

- Time runs from left to right. `T` is a model response and `C` is a tool call; the width of a column does not represent duration. `user 2` marks where a later message from the user arrived.
- Each file is a lane. An open circle is a read, a filled square is a write that creates a new version, and a cross is a deletion. Green marks content produced during the run, which includes a legitimate fix.
- A solid connector is a recorded edge. A dashed connector is an inferred edge: either derived from the text of a shell command, or the summary of a sub-session at the call that started it.
- A path in a figure shows that content was available to a later step. It does not show that the content caused the step.
- The subtitle of a backward slice gives the number of ancestor nodes and the number of other nodes in the graph, both without the target. It is a count of graph nodes, not of files or of reading time.
