---
title: "Task 99.1 - Broad inspiration discovery"
type: project-progress
task_id: "99.1"
status: completed
created: 2026-06-13
tags:
  - ai-researcher
  - inspiration-refresh
  - online-discovery
  - obsidian
---

# Task 99.1 - Broad Inspiration Discovery

## Decision

AI-Researcher should search beyond academic databases when looking for ideas, data sources, engineering constraints, and adjacent systems. The first implementation adds a guarded `inspiration-refresh` path for broad online signals, while keeping publication gates tied to scholarly sources, executed experiments, review evidence, and compiled paper quality.

## Source Boundary

The initial sources are:

- Hugging Face public dataset metadata, used as dataset/tooling inspiration.
- Hacker News Search, used as community/news/forum inspiration.

These sources are not scholarly evidence. Their Obsidian summaries explicitly state that they cannot be cited as research support until a later step validates the original dataset card, code, primary source, or executed experiment.

## Repository Artifacts

- `src/autoresearch/inspiration.py`
- `airesearcher inspiration-refresh`
- `/research:inspiration-refresh`
- Autopilot cycle summary field: `inspiration`
- `tests/unit/test_inspiration.py`
- `tests/unit/cli/test_main.py`

## Self-Loop Role

Each non-blocked `autopilot` or `serve` cycle now records broad inspiration as a non-scoring context artifact. This can feed future topic selection, dataset scouting, skill updates, and follow-up issue notes, but it must not weaken novelty checks or publication-readiness audits.

## Links

- [[task-98-1-luban-skill-polish-audit]]
- [[task-97-1-opencode-code-agent-contract]]
