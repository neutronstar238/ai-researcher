# AI-Researcher System Project

This project area tracks repository-level self-evolution evidence for AI-Researcher.

## Canonical Areas

- `issues/`: reviewer findings, blocked gates, and self-loop follow-up tasks.
- `review/`: evidence-constrained LLM or human review notes.
- `paper/`: manuscript and paper-build evidence that must cite local artifacts.
- `progress/`: historical project progress notes produced by the runtime or earlier governed tasks.

## Operating Rule

Claims made from this project area must remain traceable to retrieval, experiment,
validation, review, or paper-build artifacts.

## Current Architecture Evidence

- [[exploration/graph-harness-loop-open-science-2026|AutoResearch vNext Graph, Harness, Loop, and Open Science refactor research]] — task 262.1 cross-search, repository gap audit, four-plane graph architecture, phased migration gates, rollback strategy, and source registry.
- [[projects/ai_researcher_system/progress/task-262-2-kernel-contracts|Task 262.2 canonical event and four-plane graph contracts]] — strict content-addressed run-event and graph schemas, explicit control-loop boundaries, deterministic JSON Schema export, and zero legacy-service behavior change.
- [[projects/ai_researcher_system/progress/task-262-3-atomic-event-journal|Task 262.3 atomic event journal, replay, and fork]] — contiguous immutable event files, lineage and terminal seals, idempotent crash recovery, deterministic replay/checkpoint/fork, and zero legacy-service write-path change.
- [[projects/ai_researcher_system/progress/task-262-4-bounded-harness|Task 262.4 bounded HarnessSpec and episode packages]] — versioned execution policies, truthful blocked/failed/negative-result semantics, sealed content-addressed episodes, deterministic fixtures, and a verified local Qwen adapter.
- [[projects/ai_researcher_system/progress/task-262-5-durable-control-graph|Task 262.5 durable LoopSpec and Control Graph]] — frozen loop topology and policy, journal-only replay, idempotent crash recovery, explicit approval/retry/compensation/pivot/escalation/holdout semantics, LangGraph characterization, and a sealed Harness-to-Control-Graph development vertical.
- [[projects/ai_researcher_system/progress/task-262-6-prov-evidence-v2|Task 262.6 W3C PROV-aligned evidence v2 and Vault projections]] — content-addressed Entity/Activity/Agent causal records, support/contradict/limit evidence, validation history, EvidenceGraph v1 compatibility, approval-gated source notes, and a tamper-blocking real-round query.
- [[projects/ai_researcher_system/progress/task-262-7-open-science-research-object|Task 262.7 validated Open Science research objects]] — RO-Crate/Workflow Run/PROV interoperability, consistent software/citation/contribution/identifier metadata, SPDX/SLSA construction records, approval-gated views, sensitive-data checks, and clean-directory assertion replay over a real negative-result round.

## Current Competition Evidence

- [[projects/ai_researcher_system/progress/task-259-7-3-2-recovery-negative-adjudication|Task 259.7.3.2 recovery negative adjudication]] — the sealed 252-cell recovery completed and reproduced without human intervention, failed the noisy cross-system confidence gate, stopped the mechanism family, and kept Gate B closed.
- [[projects/ai_researcher_system/progress/task-259-7-3-1-recovery-truth-freeze|Task 259.7.3.1 recovery truth freeze]] — all recovery equations, source hashes, candidate/seed resolution, and analysis hashes were frozen while unseen results remained sealed.
- [[projects/ai_researcher_system/progress/task-259-7-2-weak-form-development-smoke|Task 259.7.2 weak-form development smoke]] — the hash-bound candidate and checkpoint path worked on development cells; clean PDE scaling was fixed and noisy PDE was already a negative signal while unseen cells were still sealed at that stage.
- [[projects/ai_researcher_system/progress/task-259-7-1-gate-a-recovery-preregistration|Task 259.7.1 Gate A recovery preregistration]] — the fresh, result-blind recovery contract that froze the disjoint matrix before implementation or results.
