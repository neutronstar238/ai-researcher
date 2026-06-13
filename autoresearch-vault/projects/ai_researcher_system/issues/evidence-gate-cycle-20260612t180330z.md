---
backlinks: []
created_at: '2026-06-13T00:19:02.423116Z'
entry_id: evidence_gate_issue_ai_researcher_system_cycle-20260612t180330z
entry_type: issue_note
keywords:
- evidence-gate
- release-blocker
- quality-gate
links:
- evidence_gate_ai_researcher_system_cycle-20260612t180330z
project_id: ai_researcher_system
related_run_ids: []
related_task_ids:
- '72.1'
source_refs:
- runs/manual-live/evidence-gate-task72/evidence-gate.json
- runs/manual-live/evidence-gate-task72/evidence-gate.md
tags:
- open
- evidence-gate
- blocked
title: Evidence release gate blockers cycle-20260612t180330z
updated_at: '2026-06-13T00:19:02.423116Z'
zone: project
---

# Evidence release gate blockers for cycle-20260612T180330Z

- Review note: [[evidence_gate_ai_researcher_system_cycle-20260612t180330z]]
- Verdict: `blocked`
- Release allowed: `false`
- Issue fingerprint: `evidence-gate:cycle-20260612T180330Z`

## Failed Checks

### publication_release_gate

- Severity: `blocking`
- Evidence refs: `runs/manual-live/serve-paper-structure/cycle-20260612T180330Z/publication-audit.json`
- Message: Publication audit gate verdict=needs_revision, publishable=false.
- Next action: Do not release as paper-ready until publication-audit reports pass/publishable.
