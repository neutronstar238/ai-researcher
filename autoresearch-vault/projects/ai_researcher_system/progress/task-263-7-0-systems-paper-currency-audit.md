---
title: Task 263.7.0 systems-paper publication-currency audit
date: 2026-07-31
status: completed-publication-blocked
task: "263.7.0"
tags:
  - systems-paper
  - publication-audit
  - independent-units
  - open-science
---

# Task 263.7.0 systems-paper publication-currency audit

## Completed result

AutoResearch now has an additive, tamper-evident audit of the immutable Task
`260` v2 systems-paper package. The audit freezes three research questions,
retains 21 live primary-source snapshots across five adversarial perspectives,
reconstructs task/seed/family units from the original cells, replays task-level
statistics in two clean interpreters, scans the full manuscript, classifies all
repairs by evidence dependency, and materializes JSON, Markdown, schemas, and a
recursive manifest.

The result is deliberately negative for submission readiness. Three deterministic
seeds duplicate the same scientific output; the ten independent tasks yield mean
`0.5`, 95% bootstrap interval `[0.2, 0.8]`, 5 wins/0 losses/5 ties, one-sided
`p=0.03125`, two-sided `p=0.0625`, and family-balanced mean `0.458333`. The
co-designed evaluation, two-family scope, absent external baselines, stale field
positioning, missing independent human review, and unresolved venue/authorship/
license decisions keep the paper blocked.

## Implementation

- Added strict immutable-parent and primary-source snapshot contracts.
- Added task-level independent-unit reconstruction and a pure-standard-library
  frozen statistical probe.
- Added retrieval-grounded findings, severity/non-compensation rules, full
  language scan, and seven-stage repair plan.
- Added deterministic source, statistical, persistence, schema, and tamper tests
  plus an opt-in real source/parent/two-interpreter smoke.
- Registered Tasks `263.7.1` to `263.7.7` as the executable recovery route.

## Formal evidence

Package: `runs/manual-live/task26370-systems-paper-currency-audit-v1/`

- report: `92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190`;
- source registry: `50fbd19ad2a03896988ffa2d66d5b6499cf30c9996e9613a26c1cc4e97067427`;
- independent-unit audit: `b6a6e2cb59be88ebb4dc747a8c6d36d91a2279568a3c2cde711ac12acb751eb3`;
- task projection: `4247521dab59e0a65318f8391367aa11c26323d04335697be3e1f74f322f9cba`;
- replay certificate: `de0273ff820b898a58afc3689d5d524c9f7f8b1185a7d0e5cc4a84605416d253`;
- repair plan: `4ad117a02defc318646456a9a754e91159756b5f148ae01f36f8ed1ddf36b3ec`;
- manifest: `8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9`.

## Verification

- Eight deterministic unit tests pass.
- The opt-in live smoke reaches and validates all 21 registered primary sources,
  binds the real immutable parent, and reproduces the exact task projection in
  two distinct clean Python installations.
- Focused Ruff and Mypy checks pass.
- The full paper scan records 28 restricted-language hits and no em dash; these
  remain repair inputs rather than silently edited historical evidence.
- Full regression passes with 1,136 tests, 34 opt-in skips, and 82% coverage.
- Repository-wide Ruff and Mypy across 178 source files pass; Poetry validation,
  three Vault-link tests, recursive package reload, immutable-parent parity, and
  `git diff --check` pass. Poetry emits only existing metadata-deprecation
  warnings, and Git reports the existing exploration-index CRLF normalization
  warning.

## Remaining gate

Tasks `263.7.1` to `263.7.3` may improve the existing research object without
claiming a new effect. Task `263.7.4` depends on three real human roles and the
frozen census. Tasks `263.7.5` and `263.7.6` require new independently authored
and scored evidence. Task `263.7.7` is the independent human publication
decision. Publication, release, and submission remain false.

## Related

- [[../../../exploration/task260-route-b-publication-currency-audit-2026]]
- [[../../../exploration/benchmark-validity-human-review-handoff-2026]]
- [[task-263-6-7-2-2-human-review-handoff]]
- [[../index]]
