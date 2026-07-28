---
title: Task 262.4 bounded HarnessSpec and episode packages
date: 2026-07-28
status: completed
task: "262.4"
tags:
  - kernel
  - harness-engineering
  - episode-package
  - bounded-execution
  - local-qwen
---

# Task 262.4 bounded HarnessSpec and episode packages

## Result

`autoresearch.kernel` now has a provider-neutral v1 harness contract and a single-trial bounded
runner on top of the task 262.3 journal. The domain contract contains no model-vendor SDK,
LangGraph checkpoint, endpoint, API key, or provider-specific response type.

`HarnessSpec` content-addresses and cross-validates versioned policies for:

- task instructions, success criteria, structured output, forbidden actions, and stop conditions;
- bounded context sources and contamination domains;
- model identity, capabilities, attempts, output tokens, temperature, and deliberation;
- allowlisted tools, side effects, sandboxing, network default-deny, and call budgets;
- Vault/short-term/cache memory access and mutable-state/checkpoint rules;
- granted, approval-required, forbidden, and unknown permissions;
- artifact, grader, journal-seal, trajectory, observability, redaction, and failure-attribution rules;
- token, cost, wall-time, tool-call, retry, uncertainty, intervention, and evaluation gates.

`EpisodePackage` separately binds the frozen task/spec, one or more trial records, the complete
trajectory, final environment outcome, grader results, costs, interventions, approvals, failures,
tool calls, produced artifacts, terminal event, journal seal, and lineage hash. The package and spec
both carry canonical SHA-256 digests and detect nested mutation before export.

## Truthful failure boundary

The task 262.4 runner intentionally performs one bounded trial; graph-level retry, pivot, resume, and
multi-node loop semantics belong to task 262.5. It emits a terminal journal event and sealed episode
for each accepted run:

- missing model/tool/approval or exhausted starting budget becomes `blocked`;
- invalid structured output, tool execution failure, grader/configuration failure, or unexpected
  adapter error becomes `failed`;
- a valid execution that misses frozen grader thresholds becomes `negative_result`;
- only a valid execution that passes the frozen evaluation policy becomes `succeeded`.

Blocked and failed paths carry no synthesized scientific output. Secret-like values and direct email
identifiers are rejected before task/spec/model/grader/package content can be persisted. Endpoint,
credential, and raw model text are absent from events and episode packages.

## Adapters and verification

- `DeterministicFixtureAdapter` and `ExactFieldGrader` provide deterministic CI characterization.
- `OpenAICompatibleHarnessAdapter` maps the existing configurable client into the provider-neutral
  protocol and retains only provider/model identifiers, structured output, bounded usage, and safe
  trajectory summaries.
- The configured local `qwen3.5-sprint:9b-8k` path completed a real strict-schema call and produced a
  successful sealed episode. This proves the local adapter path, not a scientific result or model
  quality claim.
- Focused verification passed 31 tests with one default-skipped live test; `harness.py` reached 92%
  and the OpenAI-compatible adapter reached 98% line coverage.
- The explicit live smoke passed 1 test in 45.18 seconds against the local endpoint.
- Full regression passed with 824 tests and 6 opt-in live tests skipped; repository line coverage was
  86%. Full Ruff passed and Mypy passed for 140 source files.

## Frozen boundaries

- Competition, Campaign, Sprint, EvidenceGraph, AuditLog, and existing state/scientific artifacts
  remain authoritative and unchanged.
- No framework or dependency version changed.
- The harness does not authorize public release, external submission, permission expansion, or
  access to a confirmatory holdout.
- Task 262.5 must define durable multi-node loop semantics rather than extending this runner with a
  second hidden control plane.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-3-atomic-event-journal|Task 262.3 atomic event journal]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
