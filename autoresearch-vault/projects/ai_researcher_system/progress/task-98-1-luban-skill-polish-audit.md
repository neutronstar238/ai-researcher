---
title: "Task 98.1 - Luban-inspired skill polish audit"
type: project-progress
task_id: "98.1"
status: completed
created: 2026-06-13
tags:
  - ai-researcher
  - luban-skill
  - skill-evolution
  - obsidian
---

# Task 98.1 - Luban-Inspired Skill Polish Audit

## Decision

`LearnPrompt/luban-skill` is a good methodology reference for AI-Researcher's skill evolution layer. The repository should not copy Luban's skill text, examples, assets, plugin manifests, screenshots, or generated reports. Instead, AI-Researcher now exposes a deterministic `skill-polish-audit` gate for Obsidian skill cards.

## Gate Shape

The gate checks six promotion blockers:

- Material challenge: the skill card has source evidence and issue/failure evidence.
- Peer positioning: the operator records comparable skill/project references with URLs.
- Measurement gate: the skill has validation checks plus live or held-out evidence refs.
- Bounded edit discipline: candidates keep shadow-evaluation status, rollback target, and rejected-edit buffer.
- Installable asset: the skill has a shareable or installable asset reference.
- Furnace loop: the candidate preserves follow-up observation refs and rejected-edit history.

## Repository Artifacts

- `src/autoresearch/knowledge/skills.py`
- `airesearcher skill-polish-audit`
- `/research:skill-polish-audit`
- `tests/unit/knowledge/test_skills.py`
- `tests/unit/cli/test_main.py`

## Boundary

This task adapts the audit idea into AI-Researcher's own deterministic gate. It is not a vendored copy of Luban and does not include upstream skill content. The generated audit report should be treated as promotion evidence, not as permission to overwrite a parent skill automatically.

## Links

- [[task-97-1-opencode-code-agent-contract]]
- [[task-96-1-paper-build-quality-gate]]
