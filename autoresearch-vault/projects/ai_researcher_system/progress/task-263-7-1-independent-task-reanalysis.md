---
title: Task 263.7.1 additive independent-task reanalysis
date: 2026-07-31
status: completed-publication-blocked
task: "263.7.1"
tags:
  - systems-paper
  - independent-units
  - claim-binding
  - reproducibility
---

# Task 263.7.1 additive independent-task reanalysis

## Completed result

AutoResearch now has a separate, tamper-evident correction note for the Task
`260` v2 systems-paper analysis. It preserves the parent byte-for-byte and binds
the correction to the exact Task `263.7.0` audit commit and content hashes. The
three deterministic seeds are treated as nested idempotency records, leaving ten
independent task units.

The task vector is `[0,0,0,1,0,0,1,1,1,1]`; mean difference is `0.5`; the
frozen 20,000-resample task bootstrap interval is `[0.2,0.8]`; the exact sign
test is 5 wins, 0 losses, and 5 ties with one-sided/two-sided
`p=0.03125/0.0625`; UCI/MDBench means are `0.25/0.666667`; and the
family-balanced mean is `0.458333`.

## Complete binding surface

- 8 original claims are bound; C2 alone retires publication inference.
- All 138 numeric leaves in the frozen paper-values object have dispositions.
- Both original tables remain historical/descriptive and cannot support new
  publication inference.
- All 28 unit-sensitive LaTeX lines are bound; 8 publication-facing 30-cell
  surfaces must be retired in Task `263.7.2`.
- Nine additive note claims bind every reported statistic and boundary to the
  immutable parent and audit.
- Unbound claim, number, table, and inference-surface counts are all zero.

## Formal evidence

Package: `runs/manual-live/task26371-independent-task-reanalysis-v1/`

- report: `476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99`;
- manifest: `f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab`;
- audit binding: `c014c97241acb808f0a6de090180be33ba9cf3a54cc3eae16c66fe9ee85052d9`;
- surface inventory: `7ea653abaf1c3c7d3619ef7167161aee05badf6d847aae7d02a8a6950e23597e`;
- claim ledger: `f1f5bc960b159f6ede3cfb719e8590fd3ee77f2f50ec6d98df58d847207d4e41`;
- independent-unit audit: `b6a6e2cb59be88ebb4dc747a8c6d36d91a2279568a3c2cde711ac12acb751eb3`;
- replay certificate: `de0273ff820b898a58afc3689d5d524c9f7f8b1185a7d0e5cc4a84605416d253`.

## Verification

- Eight deterministic unit tests pass, including complete surface coverage,
  audit-drift rejection, exact projection, schema, persistence, and tamper cases.
- The opt-in real-parent smoke binds both immutable packages and reproduces the
  projection in two distinct clean Python installations.
- Full regression passes with 1,144 tests, 35 opt-in skips, and 82% coverage.
- Repository-wide Ruff, Mypy across 179 source files, Poetry validation, Vault
  links, package reload, and diff checks pass.

## Remaining gate

This is a post-audit correction, not fresh confirmatory evidence. It does not
add independent task authors, external agents, task families, an independent
scorer, or human scientific review. Publication, release, and submission remain
false. Task `263.7.2` may now rewrite the manuscript against the current field;
new scientific-effect claims remain gated by Tasks `263.7.5` through `263.7.7`.

## Related

- [[../../../exploration/task260-route-b-publication-currency-audit-2026]]
- [[task-263-7-0-systems-paper-currency-audit]]
- [[../index]]
