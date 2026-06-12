# AI-Researcher Dashboard Product Brief

This brief defines the product surface before any full dashboard implementation. It is intentionally operational, not a landing page.

## Product Intent

The dashboard should help maintainers inspect and control an evidence-first research loop. It should expose the state already recorded by AI-Researcher: Obsidian vault entries, active projects, run history, validation outcomes, evidence coverage, costs, approvals, strategy changes, and rollback status.

The dashboard must not make unsupported research claims. It should show source-backed status, missing evidence, blocked gates, and links into `autoresearch-vault/`.

## Primary Users

| User | Primary Goal | Main Questions |
|---|---|---|
| Individual researcher | Run and inspect one local research project | What is my active project state, what evidence exists, and what needs review? |
| Team lead | Track multiple projects and intervention points | Which projects are blocked, costly, risky, or ready for review? |
| Reviewer | Audit claims, evidence, and reproducibility | Which claims are supported, which artifacts validate them, and what failed? |
| System administrator | Monitor governance, costs, queues, and rollback | Is the system healthy, within budget, and respecting approval gates? |

## Core Workflows

| Workflow | User Need | Required Surface |
|---|---|---|
| Candidate review | Approve or reject a source-backed research candidate | Candidate summary, source papers, similarity report, gap analysis, approval status |
| Run monitoring | Inspect current and historical runs | Run ID, task ID, status, metrics, logs, artifacts, cost, sandbox state |
| Validation review | Check whether results are trustworthy | Validation status, evidence links, missing artifacts, statistical notes, citation status |
| Paper draft review | Review generated writing without fabricated claims | Draft version, claim-to-evidence map, lint issues, reviewer simulation findings |
| Cost inspection | Understand spend and intervention load | Token/model cost, CPU/GPU/storage use, cost per success, human intervention count |
| Rollback approval | Decide whether to revert a strategy or config | Strategy card, release history, reward trend, risk notes, rollback target, audit review |

## MVP Information Architecture

1. Overview
   - System health, active projects, blocked gates, recent failures, cost summary.
2. Projects
   - Project list with status, evidence coverage, active tasks, open issues, latest run.
3. Runs
   - Run table with filters for status, task, project, validation result, and cost.
4. Evidence
   - Claims, artifacts, validation state, citation checks, and Obsidian links.
5. Reviews
   - Candidate approvals, validation reviews, paper draft reviews, and promotion audit reviews.
6. Strategy Evolution
   - Strategy cards, golden/shadow status, reward deltas, gray release, rollback, frozen families.
7. Admin
   - Scheduler health, audit log, budget thresholds, approval queues, and safe configuration status.

## Interaction Expectations

- Phase 5 dashboard work should be read-mostly first.
- Approval actions must show the exact audit record that will be written.
- Risky actions such as full-permission execution, rollback approval, publication, or external deployment require explicit human confirmation.
- Every status card or table row should link to its source record in `autoresearch-vault/`, an audit JSONL event, or a run artifact.
- Empty, blocked, or skipped states must be visible; hiding missing data would weaken the evidence-first contract.

## Visual Direction

- Dense operational interface, suitable for repeated inspection.
- Avoid marketing hero sections, oversized decorative cards, and product-pitch copy.
- Prefer tables, filters, status chips, compact metric rows, and detail drawers.
- Use restrained color to communicate state: passed, warning, failed, blocked, approval required, rollback active.
- The first dashboard screen should be the overview workspace, not a landing page.

## Implementation Boundaries

- Do not build the full dashboard until Phase 1 is stable enough to provide real local project and run data.
- Do not add multi-user role complexity before task 32.
- Do not let dashboard controls mutate safety policy, approval gates, license policy, or publication rules.
- Do not show fabricated demo success as real project status.
- Browser tests for task 31.2 must cover desktop and mobile layout.

## Acceptance Checklist For Dashboard Implementation

- Product users and workflows are represented in navigation or information architecture.
- Overview shows project status, runs, metrics, failures, costs, evidence coverage, and approval queue.
- Candidate review, run monitoring, validation review, paper draft review, cost inspection, and rollback approval are reachable.
- Each claim or metric links back to a source record, audit event, or artifact.
- Empty and blocked states are visible.
- Desktop and mobile browser checks pass.
