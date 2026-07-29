---
title: Task 261.2.3 independent confirmatory adjudication
entry_id: task-261-2-3-confirmatory-adjudication
entry_type: project_progress
project_id: autoresearch-ccfb
created_at: 2026-07-29T05:16:59Z
updated_at: 2026-07-29T05:16:59Z
status: completed-negative-confirmatory
tags:
  - bounded-autonomy
  - confirmatory-evaluation
  - negative-result
  - control-graph
  - provenance-v2
  - reproducibility
related_run_ids:
  - task261-bounded-autonomous-clean-v2
  - task2612-mechanism-foundation-live-v3
  - task2612-mechanism-development-live-v12
  - task2612-mechanism-confirmatory-live-v1
links:
  - task-261-2-2-generated-mechanism-development
  - task-261-2-generated-mechanism-evidence-survey-2026
---

# Task 261.2.3 independent confirmatory adjudication

Task 261.2.3 produced a valid negative scientific endpoint. This is not an execution failure:
all six independent tasks completed successfully, while the model-authored mechanism missed the
frozen minimum-coverage gate. The endpoint is retained without same-panel tuning.

## Pre-reveal freeze

- Authoritative directory:
  `runs/manual-live/task2612-mechanism-confirmatory-live-v1/`
- Development manifest:
  `55c4604474517317114fa88fa389aced28ca5ba96f2eafee6832cfcceb24737e`
- Exact generated source:
  `7b4961c62a7b8a253eb44d1e656dde3abc30dc1d6c1fc4e25b17745eca137025`
- Panel:
  `8762b50969816e8847c8b0836b5a0a3309aef7ff9faaf234826dc8ec0f921019`
- Confirmatory task bundle:
  `bc066ae68146cc1bf2d2f2aa1466b8fedc47235a5030c9f699b6ac5f4f1ba09c`
- Preregistration:
  `1e499a27da3bbba08be9f7a2e47de06c5c49d216c96230d46388971ad3659464`
- Execution environment:
  `0198b9e7a8c13258d139ce4398162c6c272c491aa64ff3358aa63a06a67b1ea8`
- Immutable Control Graph:
  `fe2d9e96b264d86b5ae87602dce4628c72de49019d17a48344cba8051b7fab44`

Before reveal, the status command revalidated every frozen file and reported
`frozen_unrevealed`, zero confirmatory result artifacts, no endpoint, and no scientific result.
The three development and six confirmatory source fingerprints are unique within their
partitions and mutually disjoint.

The frozen scientific policy was:

- Primary metric: `unsupported_claim_rate_at_minimum_coverage`.
- Independent unit: confirmatory task.
- Uncertainty: 20,000-resample task-level percentile bootstrap, seed `261203`.
- Minimum coverage: `0.60`.
- Maximum unsupported-accept rate: `0.10`.
- Maximum attempts per task: `1`.
- Continue after a task failure: `true`.
- Post-reveal adaptation and endpoint rewrite: `false`.
- Network and external submission: `false`.

The environment record includes the Poetry lock, Python version and executable hash, operating
system, implementation-file hashes, Git commit
`b07f3d703465766e595c4621749073cdbe01094c`, and the fact that the worktree was not clean while
the new implementation awaited task verification and commit. Freeze and execution nevertheless
matched the exact environment hash and every implementation-file digest.

## One-shot task results

| Task | Accepted / claims | Unsupported accepts | Coverage | Unsupported rate |
|---|---:|---:|---:|---:|
| `task2612-confirm-01` | 4 / 8 | 0 | 0.500 | 0.000 |
| `task2612-confirm-02` | 4 / 8 | 0 | 0.500 | 0.000 |
| `task2612-confirm-03` | 6 / 8 | 1 | 0.750 | 0.167 |
| `task2612-confirm-04` | 3 / 8 | 0 | 0.375 | 0.000 |
| `task2612-confirm-05` | 6 / 8 | 0 | 0.750 | 0.000 |
| `task2612-confirm-06` | 5 / 8 | 0 | 0.625 | 0.000 |

Every task returned a successful Harness episode. The Control Graph records exactly one attempt
for reveal, each of the six task nodes, adjudication, and the start node. All 20 abstentions and
the single unsupported accept remain in the task artifacts.

## Scientific endpoint

- Claims: 48.
- Accepted: 28.
- Abstained: 20.
- Accepted unsupported: 1.
- Coverage: `0.5833333333`; task-level bootstrap 95% interval
  `[0.4791666667, 0.6875]`.
- Unsupported-accept rate: `0.0357142857`; task-level bootstrap 95% interval
  `[0.0, 0.1]`.
- Passing scientific gates: exact task count, all executions, no network, one-shot attempts,
  unsupported-rate point estimate, and unsupported-rate interval upper bound.
- Failing scientific gate: `minimum_coverage_met`.
- Outcome: `negative_result`.
- Endpoint:
  `d449343654e28a4da877d0ab7a3bd07e334ac8cad310385996c635bacbae165d`
- Scientific projection:
  `fed38ff7a08f12562eae1488bbc951561d3279d1e181f3b89a830e13d2ddf6f9`

The evidence supports a narrow conclusion: on this panel, the mechanism kept residual risk among
accepted claims within the frozen ceiling but abstained too often to meet the frozen coverage
floor. It does not establish a positive contribution, general robustness, or publication
readiness.

## Integrity, reproduction, and rollback

- Terminal manifest:
  `3086eba1a11e7b98cd8cc5faeb3f5a0d140adf80c283a637ff9b7c52b4ba011c`
- Event Journal lineage:
  `cb2d211869175a4e870fd9336a412f6290ba85cc6888275806b0fa03c776fe95`
- Provenance-v2 bundle:
  `13cd43d0cf51c649fce41e7f995644c861c968c790e593deb6cae5098441e756`
- Evaluation/security report:
  `733ca3ac27ef93eaf4dd3df5c4692858e3ebca6754f5640ab0f349a54defc7d3`
- Independent reproduction:
  `e03114dbe4fb12841d68e199e0d5e02c2fb8e2f5bc4056ffacee752d2e63ac9b`
- Rollback rehearsal:
  `f822224b17ee99cf7b323fa7f7d2e73864b7c6cd0b48dce248b376d0b7e0360c`

The evaluation/security report passed all checks: frozen artifacts, environment, immutable
terminal graph, endpoint hash, exact result count, no network or secret-bearing environment keys,
one attempt per task, provenance claim trace, independent reproduction, rollback rehearsal, and
endpoint non-rewrite. The reproduction reran all six tasks in an initially empty directory and
independently recomputed every scientific field and gate; its projection equals the canonical
endpoint projection. The rollback rehearsal reconstructed the sealed pre-reveal state without
deleting or changing the canonical endpoint.

A post-terminal CLI run hashed all 220 files before and after loading the result. File count and
every digest were unchanged, proving idempotent terminal reload rather than a second panel
execution.

## Decision and next action

Do not tune the expression, source-count threshold, risk threshold, or compiler against these six
revealed tasks. Any future mechanism revision must use a new development partition and a newly
frozen independent confirmatory panel.

Task 261.2.4 should build the child report, manuscript, figures, tables, PDF, and claim-evidence
audit from this negative endpoint. It must state that unsupported risk passed while coverage
failed, preserve abstentions and limitations, bind every material claim to literature or
execution evidence, and keep submission readiness and external submission false.

## Related knowledge

- [[task-261-2-2-generated-mechanism-development|Task 261.2.2 generated mechanism development]]
- [[task-261-2-generated-mechanism-evidence-survey-2026|Generated mechanism evidence survey]]
