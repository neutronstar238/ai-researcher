---
title: "Task 97.1 - OpenCode direct code-agent contract"
type: project-progress
task_id: "97.1"
status: completed
created: 2026-06-13
tags:
  - ai-researcher
  - opencode
  - code-agent
  - evidence-gate
---

# Task 97.1 - OpenCode Direct Code-Agent Contract

## Decision

AI-Researcher should prefer direct OpenCode integration for external code drafting instead of routing the default path through cc-switch and Claude Code. OpenCode is treated as a replaceable code-generation executor; AI-Researcher remains responsible for diff capture, tests, evidence gates, dangerous-command approval, merge/rollback, Obsidian memory, and `Agent.md` logging.

## Evidence

- Official OpenCode CLI docs describe non-interactive `opencode run`, headless `opencode serve`, and ACP server modes.
- Official OpenCode permission docs describe `allow`, `ask`, and `deny` actions with granular bash/edit rules.
- Official OpenCode skill docs describe project-local `.opencode/skills/<name>/SKILL.md` discovery and YAML frontmatter.
- GitHub reports `anomalyco/opencode` as MIT licensed, and `npm view opencode-ai version license repository --json` returned `license=MIT`.

## Repository Artifacts

- `src/autoresearch/integrations/opencode.py`
- `tests/unit/integrations/test_opencode.py`
- `airesearcher code-agents opencode init|list`
- `integrations/opencode/code-agent.json` generated during verification

## Boundary

The task does not vendor OpenCode code, prompts, screenshots, auth files, transcripts, or assets. The local workstation did not have the `opencode` binary installed, so task `97.1` verifies the repository contract and manifest generation only. A future live smoke should install OpenCode on the target operator machine and run a bounded non-destructive `opencode run` inside a disposable worktree before claiming end-to-end OpenCode execution.

## Links

- [[task-96-1-paper-build-quality-gate]]
- [[task-95-1-structured-similarity-queries]]
