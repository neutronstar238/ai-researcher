# Agent Development Standard and Change Log

This file defines the project development standard for coding agents and records what each agent changed in this repository. Every agent that edits files must append an entry before handoff.

## Development Standard

### Task Discipline

- Work from `.kiro/specs/auto-research-system/tasks.md`.
- Start one task or subtask at a time.
- State the success criteria before implementing when the task is non-trivial.
- Do not mark a task complete until its verification steps have passed.
- If verification cannot run, keep the task unchecked and record the blocker in `Problem.md`.

### Change Scope

- Make the smallest change that satisfies the active task.
- Do not refactor unrelated code, rename unrelated files, or clean up unrelated dead code.
- Keep implemented behavior aligned with `AutoResearch_System_Research_Plan.md` and `AutoResearch_System_Execution_Plan.md`.
- User-facing claims in docs must distinguish planned capabilities from implemented capabilities.

### Verification

- Prefer narrow checks first, then broader checks when the task touches shared behavior.
- For docs-only changes, verify file existence, links, and key required phrases.
- For code changes, run the relevant unit, integration, lint, type, or smoke checks listed in the task.
- Record all verification in this file.

### Problem Tracking

- Add a `Problem.md` entry for missing modules, failed commands, unclear requirements, skipped verification, security concerns, or any issue likely to affect the next agent.
- Link problem IDs back to the relevant task where possible.

### Git Version Management

- After completing a task or subtask in `tasks.md`, passing its verification, and updating `Agent.md` and `Problem.md`, create one git commit for that completed task or subtask.
- Use a focused commit message that names the task, for example `docs: complete task 0.1 governance baseline`.
- Do not combine unrelated tasks in one commit.
- Do not commit a task whose verification is blocked; leave it unchecked and document the blocker.
- Before committing, review `git status --short` and stage only files relevant to the completed task.

## Entry Template

```markdown
### YYYY-MM-DD HH:mm:ss +TZ - Agent Name - Task

- Request: Short description or task ID.
- Files changed:
  - `path/to/file`
- Summary:
  - What changed and why.
- Verification:
  - Command or check: result.
- Problems:
  - `P-YYYYMMDD-NNN` updated, or `None`.
- Follow-up:
  - Remaining work, or `None`.
```

## Entries

### 2026-06-11 18:00:00 +08:00 - Codex - Task 1.1 config data models

- Request: Continue implementing `.kiro/specs/auto-research-system/tasks.md`, starting with task `1.1`.
- Files changed:
  - `src/autoresearch/config/models.py`
  - `src/autoresearch/config/__init__.py`
  - `tests/unit/config/test_models.py`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `Problem.md`
  - `Agent.md`
- Summary:
  - Added minimal Pydantic configuration models for system, agent, compute, knowledge base, and literature settings.
  - Kept defaults local-first, sandbox-enabled, and aligned with the canonical `autoresearch-vault/` Obsidian vault path.
  - Temporarily narrowed `autoresearch.config` exports to existing model APIs so `SystemConfig` imports honestly before task `1.2` adds the parser.
  - Added focused tests for default values and basic Pydantic bounds.
  - Marked task `1.1` complete in `tasks.md`.
- Verification:
  - `PYTHONPATH=src python -c "from autoresearch.config import SystemConfig; print(SystemConfig().knowledge_base.vault_path)"`: passed, printed `autoresearch-vault`.
  - `PYTHONPATH=src python -c "from autoresearch.config import AgentConfig, ComputeConfig, KnowledgeBaseConfig, LiteratureConfig, SystemConfig; c=SystemConfig(); assert str(c.knowledge_base.vault_path) == 'autoresearch-vault'; assert c.compute.sandbox_enabled; assert c.literature.databases == ['arxiv', 'semantic_scholar']; print('config models ok')"`: passed.
  - `PYTHONPATH=src python -m pytest -o addopts='' tests/unit/config/test_models.py`: passed, 2 tests.
  - `python -m pytest tests/unit/config/test_models.py`: blocked by missing pytest-cov in the active environment.
  - `python -m ruff check src/autoresearch/config tests/unit/config/test_models.py`: blocked because ruff is not installed in the active environment.
  - `poetry --version`: blocked because Poetry is not on PATH.
- Problems:
  - `P-20260611-001` partially resolved.
  - `P-20260611-003` added.
- Follow-up:
  - Task `1.2` should add `ConfigParser` and `ConfigFormat`, then restore parser exports from `autoresearch.config`.

### 2026-06-11 17:36:49 +08:00 - Codex - Documentation planning bootstrap

- Request: Create project planning conventions, a detailed executable task plan, problem logging, and bilingual open-source README pages.
- Files changed:
  - `AGENTS.md`
  - `Agent.md`
  - `Problem.md`
  - `README.md`
  - `README.zh-CN.md`
  - `.kiro/specs/auto-research-system/tasks.md`
  - `autoresearch-vault/README.md`
- Summary:
  - Added repository-wide agent instructions and required change logging rules.
  - Added this agent development standard and change log as the required place for future agents to record file changes and development rules.
  - Added the rule that each completed and verified `tasks.md` task or subtask must be committed as one focused git commit.
  - Added a problem log with the initial scaffold issue discovered during repository inspection.
  - Re-read Kiro requirements and design sections for Obsidian Knowledge Base, Agent evolution, knowledge auto-evolution, permissions, and version history after user review.
  - Re-centered the plan on the Obsidian-compatible `autoresearch-vault/` as the unified self-loop and self-evolution substrate.
  - Reworked the README into an English default open-source landing page with a Chinese version.
  - Rewrote the implementation task plan around the research and execution plans, with detailed executable tasks and verification gates.
  - Added `autoresearch-vault/README.md` so the canonical vault path is present in the repository.
- Verification:
  - Read the two project planning docs, existing Kiro task plan, `pyproject.toml`, and current source skeleton.
  - Read Kiro `requirements.md` and `design.md` sections for Agent evolution, Knowledge Base structure, permissions, knowledge auto-evolution, version history, and Obsidian rationale.
  - `Test-Path` confirmed `AGENTS.md`, `Agent.md`, `Problem.md`, `README.md`, `README.zh-CN.md`, and `.kiro/specs/auto-research-system/tasks.md` exist.
  - `rg` confirmed required terms and links: `Development Standard`, `Git Version Management`, `one focused git commit`, `README.zh-CN`, `Task Dependency Graph`, `P-20260611-001`, `Phase 0`, and `Phase 5`.
  - `rg` confirmed `autoresearch-vault/` is the documented Obsidian vault path and the temporary alternate vault path is no longer referenced.
  - Removed trailing whitespace from the two imported root planning Markdown files so staged whitespace checks can pass.
  - `git diff --check` reported no whitespace errors; Git only warned that LF will be converted to CRLF on future checkout/touch.
- Problems:
  - `P-20260611-001` added.
  - `P-20260611-002` added and resolved.
- Follow-up:
  - Complete Phase 0 implementation tasks before treating `pytest`, `ruff`, `mypy`, or the `autoresearch` CLI as functional project gates.
