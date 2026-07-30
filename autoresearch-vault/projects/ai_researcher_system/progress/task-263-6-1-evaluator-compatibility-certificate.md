---
title: Task 263.6.1 evaluator compatibility certificate
date: 2026-07-31
status: completed
task: "263.6.1"
tags:
  - autoresearch
  - confirmation
  - evaluator-integrity
  - harness
  - label-semantics
  - reproducibility
  - result-blind
---

# Task 263.6.1 Evaluator Compatibility Certificate

## Decision

The next-version tabular confirmation evaluator is:

`certified`.

This is a measurement-system certificate, not a scientific result. It does
not repair the frozen v1 endpoint, reopen its consumed panel, establish a
policy effect, authorize a new confirmation, or unlock publication.

Task 263.6 remains open. Task 263.7 remains blocked. Public release and
external submission remain unauthorized.

## Why this gate was necessary

The first one-use confirmation ended as `invalid_confirmation`. The original
runner let pandas infer numeric-looking training class labels as numbers while
the separately sealed JSON truth retained strings. It then inverse-transformed
predictions to numeric values and mixed them with string truth in balanced
accuracy. The resulting 69 failures covered exactly 23 classification tasks
and all three seeds.

That failure showed an important boundary: byte hashes, exact replay, a
durable graph, and complete provenance can prove that an error repeats, but
they cannot prove that the evaluator's cross-format semantics are correct.
The evaluator therefore had to be calibrated before any further scientific
interpretation.

## v2 evaluator contract

The standalone v2 runner changes only the evaluator boundary:

- classification target is read from CSV with string dtype;
- sealed classification labels must also be strings;
- F3 truth is transformed through the training `LabelEncoder`, so truth and
  prediction are scored in one integer vocabulary;
- regression targets remain finite floats;
- F1/F2 reject any `labels_path` or `labels_sha256`;
- F2 attempt directories contain no label file;
- fit/predict exceptions are `candidate` failures;
- malformed or mismatched inputs are `input` failures;
- prediction/metric defects are `evaluator` failures;
- the intentional invalid branch produces a valid candidate-domain artifact;
- input/evaluator failures return a nonzero process code;
- output and every readable input remain path-confined;
- the runner imports no network client and receives a network-disabled
  environment.

The frozen Task 263.5 mixed-feature learner implementation remains a
hash-pinned dependency. The Task 263.6 v1 runner, controller, orchestrator,
freeze, report, and result tree were not modified.

## Result-blind fixture corpus

Four deterministic 36-train/12-test ARFF fixtures cover the missing semantic
surface:

| Fixture | Family | Encoding | Properties |
|---|---|---|---|
| `dense-numeric-labels` | classification | dense | numeric-looking class tokens |
| `sparse-string-labels` | classification | sparse | sparse ARFF and string classes |
| `dense-quoted-mixed-classification` | classification | dense | quoted commas, mixed features, test-only unseen category |
| `dense-mixed-regression` | regression | dense | mixed features, test-only unseen category, float target |

Each fixture is converted through the actual ARFF parser into CSV inputs and
a content-addressed JSON label artifact. The next-version materializer is
called twice. Its existing-file branch reloads the manifest, verifies every
hash and split, reconstructs `feature_columns`, and returns exactly the same
semantic fixture. A deterministic tamper test proves the branch fails closed.
This directly closes the next-version form of the v1 resume defect without
editing the frozen source.

## Two-interpreter matrix

The certificate used the two clean interpreters already pinned by the
result-free confirmation freeze. It selected one result-free representative
for each valid learner plus both linear preprocessing decisions:

- dummy/prior;
- linear with imputation;
- linear with standardization;
- LightGBM;
- XGBoost;
- random forest;
- extra trees;
- histogram gradient boosting;
- LightGBM/XGBoost ensemble.

The exact matrix retained:

| Probe class | Count |
|---|---:|
| Valid F3: 9 configurations × 4 fixtures × 2 roles × 2 repeats | 144 |
| Expected `invalid_probe` candidate-domain controls | 4 |
| F2 physical label-isolation probes | 4 |
| Total subprocess probes | 152 |

All valid probes succeeded. All four invalid controls failed only in the
expected `candidate` domain with code `intentional_invalid_probe`. All four
F2 probes succeeded with no label file, no label config field, no label hash,
and `labels_accessed=false`.

## Conjunctive result

All 15 certificate checks passed:

- every allowed learner is covered;
- every required fixture property is covered;
- all valid probes succeed;
- both pinned interpreters are used;
- within-interpreter prediction/scientific replay is exact;
- cross-interpreter scientific projection is exact;
- F2 label isolation is proved;
- fixture resume reconstructs and verifies metadata;
- invalid control is candidate-attributed;
- null-prior has zero integrity failures;
- unexpected candidate failures are zero;
- evaluator failures are zero;
- input failures are zero;
- network is disabled;
- package, interpreter, runner, schema, and protected v1 source hashes verify;
- no v1 result, task bundle, execution index, or reveal artifact was read.

The report recursively binds 1,242 artifacts: fixture sources and manifests,
attempt inputs and configs, process statuses, stdout/stderr digests, runner
results, frozen execution assets, schemas, Markdown, and the report itself.

## Immutable identities

- source result-free v1 freeze:
  `7069ae95433cf7f83c86d35993dd3bd88020e919102d01594574c1860b3c8031`;
- v2 confirmation runner:
  `7bc71786216ba48addc3ab4212c2b18b9ffd1ed0da3a60cc18b942d23afc77fd`;
- certificate orchestrator:
  `97c2152427c7a075731fb83fe421351ae7f9728d60d691f3e867a54e4b1fd1bc`;
- schema bundle:
  `6b9a4353a819ba4f7abf8354b8c43b07b67b568327f9938240436f1a0e8b1d3e`;
- report:
  `e3709c8b834bfcc52ed7fb74389278e6c5a3e36d4bf13d32ddad7118f4aa797b`;
- manifest:
  `4e3251eb2453fffaa37a4f6849251396e3f1fc88f882739faa07a5e8d4dda73c`.

## Verification

- eight deterministic unit/property tests passed;
- the opt-in 152-probe live certificate passed in 222.72 seconds;
- exact reload and second invocation preserved report and manifest hashes;
- canonical full regression passed with 1,066 tests, 24 opt-in skips, and 84%
  coverage in 173.72 seconds;
- repository-wide Ruff passed;
- Mypy passed across 168 source files;
- Poetry validation passed with existing metadata warnings only;
- recursive artifact inventory and diff checks passed.

## Research-path implication

The certificate converts lessons from AI Scientist evaluation, PaperBench/
MLR-Bench replication failures, Graph of Trace, and code-as-harness work into
a concrete rule: the scientific evaluator is itself an instrument and must
receive cross-serialization calibration, null behavior, failure-domain, and
independent replay evidence before it can adjudicate a claim.

The next allowed step is [[task-263-6-0-invalid-confirmation-diagnosis|the
predeclared recovery path]] Task 263.6.2. It must:

1. bind the exact v1 freeze, report, failure pattern, and this certificate;
2. freeze its stop/advance rule before reading repaired outcomes;
3. label every output `consumed-panel`, `technical`, and `exploratory`;
4. make independent-confirmation and publication eligibility permanently
   false;
5. close `portfolio_memory` if the corrected effect is not directionally
   positive and practically plausible;
6. forbid a fresh panel unless a new mechanism, new development evidence,
   a new research-question certificate, and a disjoint zero-result panel are
   approved prospectively.

## Links

- Parent project: [[../index|AI-Researcher System Project]]
- Invalid v1 diagnosis:
  [[task-263-6-0-invalid-confirmation-diagnosis]]
- Publishability recovery:
  [[../../../exploration/publishability-recovery-ai-scientist-2026]]
- Graph/Harness/Open Science research:
  [[../../../exploration/graph-harness-loop-open-science-2026]]
