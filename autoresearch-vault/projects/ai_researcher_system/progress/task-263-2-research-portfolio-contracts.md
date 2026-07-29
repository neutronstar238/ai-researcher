---
title: Task 263.2 research question, opportunity, and portfolio contracts
date: 2026-07-29
status: completed
task: "263.2"
tags:
  - research-question-certificate
  - replication-first
  - portfolio-search
  - multi-fidelity
  - publication-gate
---

# Task 263.2 research question, opportunity, and portfolio contracts

Task 263.2 implements the first code slice of the publishability recovery plan. It creates a strict,
provider-neutral, content-addressed front end for deciding whether a research track may consume novelty-search
budget. It does not call a model, retrieve literature, run an experiment, reveal a confirmatory panel, generate
a paper, authorize publication, or change any Task 259—261 result.

## Implemented contracts

- `ResearchQuestionCertificate` freezes one main claim, literature cutoff, primitives, assumptions, mechanism,
  nearest-work tension, falsifier, failure update, minimal decisive test, objective primary metric, meaningful
  effect, strong baseline, null/control, ablations, prospective power evidence, disjoint development/confirmatory
  units, budget, and a result-blind publication endpoint.
- `ResearchOpportunity` binds the certificate to verified sources, a nearest-work delta matrix, an objective
  evaluator, a clean-room baseline reproduction plan/evidence, and explicit data, license, compute, and source
  availability.
- `OpportunityAssessment` has two stages. `track_selection` can admit a promising track with a baseline smoke and
  reproduction plan. `novelty_search` additionally requires an independently reproduced, within-tolerance
  baseline. Every check is conjunctive; weighted scores and LLM overrides are fixed false.
- `PortfolioSpec` requires 8—16 branches, at least three mechanism families, a null/rule arm, unique branch
  evidence/deltas, ordered F0—F3 fidelity stages, non-increasing survivors, an exploration quota, bounded branch
  reservations, full branch retention, at most one confirmatory claim, and zero sealed-evidence visibility.
- `PortfolioAssessment` independently recomputes the branch, diversity, budget, fidelity, result-blind,
  external-action, retention, and confirmatory-boundary checks.

Every hashed contract revalidates its canonical digest on load and exposes `verify_integrity()` so an in-memory
`model_copy` mutation cannot reach an assessment. Nested certificate, baseline, opportunity, assessment, and
portfolio changes therefore fail closed.

## Gate semantics

The implementation separates three statements that were previously easy to conflate:

1. A topic may be interesting enough to inspect.
2. A topic has a reproducible baseline and sufficient evidence to begin novelty search.
3. A diverse, budget-bounded portfolio is safe to execute on development units.

Only the third statement creates a `PortfolioSpec`. None of them means that a scientific claim passed, a paper is
publishable, or an external submission is authorized.

## Deterministic verification

- 16 focused unit/property tests passed. They cover order-invariant hashes, JSON round trips, disjoint-unit and
  power-count checks, nested and in-memory tampering, external-action rejection, track-versus-novelty staging,
  conjunctive blockers, source/baseline binding, 8-branch diversity, null/rule presence, F0—F3 ordering, insufficient
  budget, blocked opportunities, sealed evidence, post-freeze hypothesis changes, and publication-route changes.
- The complete research test package passed with 54 tests before the final hardening additions.
- The full repository suite passed with 999 tests and 17 opt-in live tests skipped at 87% coverage.
- Repository-wide Ruff passed.
- Mypy passed across 159 source files.
- The 16 exported JSON Schemas are deterministic; their bundle SHA-256 is
  `47cf6a3f5c0a2cd52dfaf5f6427dfbf71efde272671de74464a6aa0e84797629`.

No live external smoke applies to this slice because it defines and deterministically validates contracts only.
Task 263.3 owns the first real source/repository/data opportunity tournament and must pair deterministic fixtures
with live checks.

## Next action

Run Task 263.3 across at least three independently evidenced tracks. A track may advance to Task 263.4 only if its
track-selection assessment passes; it may not create a novelty portfolio until the selected strong baseline is
independently reproduced and the novelty-search assessment passes.

## Related

- [[exploration/publishability-recovery-ai-scientist-2026|Publishability recovery research]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
- [[projects/ai_researcher_system/progress/task-262-10-vnext-release-boundary|vNext release boundary]]
