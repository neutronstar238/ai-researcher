# AI-Researcher Home

> Evidence first. A claim is not ready until it links to retrieval, validation, and review evidence.

## Start Here

- [[_system/dashboards/research-loop|Research Loop Dashboard]]
- [[exploration/index|Global Topic Index]]
- [[projects/ai_researcher_system/index|Current Project]]
- [[_system/plugins/recommended-plugins|Recommended Obsidian Plugins]]

## Active Memory Zones

| Zone | Purpose |
|---|---|
| `exploration/topics/` | Live literature refreshes and cross-project discovery. |
| `exploration/skills/` | Reusable skill cards distilled from successful or failed runs. |
| `exploration/strategy_cards/` | Strategy candidates, shadow evaluations, and rollback notes. |
| `projects/ai_researcher_system/issues/` | Reviewer findings and self-loop follow-up tasks. |
| `projects/ai_researcher_system/review/` | Evidence-constrained LLM or human review notes. |
| `projects/ai_researcher_system/paper/` | Drafts that must cite local evidence. |

## Operator Commands

```bash
poetry run airesearcher autopilot --watch --cycles 0 --interval-seconds 86400
poetry run airesearcher issue-followups --vault autoresearch-vault --project-id ai_researcher_system
```
