# Experiments

Configuration, records and analysis outputs of the runs. The results come from the ten runs of the matched dataset, `run-030` to `run-039`: five `normal` and five `documentation-injection`. Ten extension runs, `run-040` to `run-049`, cover the other two scenarios and are kept apart from the matched dataset.

## Files

| Path | Content |
| --- | --- |
| `d7/protocol.json` | The fixed run configuration: model, settings, schedule, initial file hashes |
| `d7/input-lock.json` | Hashes of every input file the configuration depends on |
| `d7/controlled_collect.py` | The collector: at most four segments in one session within 600 seconds; the model must be given explicitly |
| `d7/config-d7.json`, `d7/execution-policy-d7.txt`, `d7/sandbox-template.sb` | OpenCode settings, the generic system instruction, and the template of the access rules |
| `v2_batch.py` | `verify` checks the inputs against the lock; `run` collects one new run and refuses to overwrite an existing one |
| `manifest.json`, `manifest.csv`, `review-notes.json` | Inventory of the ten runs of the matched dataset |
| `delegated-sessions.json` | Links the sub-session of run-039 to its parent, with its hash |
| `build_manifest.py`, `v2_results.py`, `v2_verify.py` | Check the recorded evidence, summarize the outcomes, and validate the graphs |
| `v2-d7/capture/` | The protocol, the pre-flight record and the access rules exactly as they were at collection time. They document what was executed and are never edited |
| `v2-d7/run-NNN-*` | Per-run environment record, checker log, collector log, file hashes and edit replay |
| `v2-d7/results.json`, `results.csv`, `manual-review.json` | Outcome of each run of the matched dataset, with the manual review of its report and final answer |
| `v2-d7/c1-c2/`, `c3/`, `c4/` | Outputs of the three analysis steps below |

The recorded metadata keeps the paths and the context of the machine the runs were collected on. A model's own statement that it finished the task is a record to be checked, not a verdict.

## Analysis steps

All three run offline and call no model.

| Step | Command | Output | Write-up |
| --- | --- | --- | --- |
| Detection, tracking and source ranking | `python3 experiments/c1_c2.py` | `v2-d7/c1-c2/` | [docs/c1-c2-analysis.md](../docs/c1-c2-analysis.md) |
| Rarity score | `python3 experiments/c3_results.py` | `v2-d7/c3/` | [docs/c3-analysis.md](../docs/c3-analysis.md) |
| Comparison with the flat-log baseline | `python3 experiments/c4_results.py` | `v2-d7/c4/` | [docs/c4-evaluation.md](../docs/c4-evaluation.md) |

`c3_results.py --check` and `c4_results.py --check` recompute the outputs and compare them with the stored files without writing anything.

These scripts cover the matched dataset only. For the extension runs, the tools under `provenance/` were run on each run directly; the write-ups above report the results in their last sections.
