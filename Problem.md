# Problem Log

Use this file to record blockers, defects, risks, failed commands, and important partial-verification notes. Keep entries factual and update them as work progresses.

## Status Values

- `Open`: still affects current or future work.
- `Investigating`: root cause is not confirmed yet.
- `Mitigated`: workaround exists, but the underlying issue remains.
- `Resolved`: fix has been verified.
- `Won't Fix`: intentionally accepted with rationale.

## Entry Template

```markdown
### P-YYYYMMDD-NNN - Short title

- Status:
- Severity: Low | Medium | High | Critical
- Discovered:
- Source:
- Symptom:
- Impact:
- Evidence:
- Root cause:
- Workaround:
- Next action:
- Linked tasks:
- Resolution:
- Verification:
```

## Problems

### P-20260611-001 - Python scaffold references modules and CLI that do not exist yet

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-11 17:36:49 +08:00
- Source: Repository inspection while preparing project planning documents.
- Symptom: `pyproject.toml` registers `autoresearch = "autoresearch.cli.main:app"`, but `src/autoresearch/cli/main.py` is not present.
- Impact: Resolved for scaffold imports and direct CLI execution. Broad package verification is tracked separately in `P-20260611-003`.
- Evidence: `rg -n "cli|main" -S pyproject.toml src` finds the CLI entry point reference; `rg --files src` does not list `src/autoresearch/cli/main.py`.
- Root cause: The repository is still in planning/scaffold stage and the previous task plan marked some setup work ahead of implementation reality.
- Workaround: None needed for scaffold imports or direct CLI execution after task `1.3`.
- Next action: Continue Phase 0 tasks for broader smoke tests and project test harness.
- Linked tasks: `0.5`, `1.1`, `1.2`, `1.5`, `1.6`
- Resolution: Resolved by tasks `1.1`, `1.2`, and `1.3`; config models, config parser, and CLI entry point now exist.
- Verification: `PYTHONPATH=src python -m autoresearch.cli.main version` printed `0.1.0`; `PYTHONPATH=src python -m autoresearch.cli.main doctor` reported OK for Python, package import, config import, parser, project root, and knowledge vault.

### P-20260611-002 - Planning docs underweighted Obsidian as the self-loop and self-evolution substrate

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-11, during user review of the first documentation plan.
- Source: User pointed out that Kiro requirements and design contain the core innovation: an Obsidian unified knowledge base built specifically for self-looping and self-evolution.
- Symptom: The first rewritten plan mentioned a local knowledge base but did not make the Obsidian vault the central product and architecture substrate across Phase 0 through Phase 4.
- Impact: Future agents could incorrectly treat Obsidian as a replaceable storage detail instead of the project's main differentiator and long-term memory layer.
- Evidence: `requirements.md` Requirements 2, 6, 7, 8, and 28; `design.md` Knowledge Base Component and Obsidian technology rationale.
- Root cause: The initial rewrite emphasized the trusted execution loop more strongly than the original Obsidian-driven self-loop and self-evolution idea.
- Workaround: None needed after documentation revision.
- Next action: Keep Obsidian vault layout, wiki-links, topic index, failure library, skill library, and strategy library visible in implementation tasks and README.
- Linked tasks: `0.7`, `5.1`, `5.2`, `5.3`, `5.4`, `5.5`, `20.1`, `22.1`, `23.1`, `26.1`
- Resolution: README, `AGENTS.md`, `tasks.md`, and `autoresearch-vault/README.md` were revised to make Obsidian the unified knowledge substrate for self-looping and self-evolution.
- Verification: `rg` confirmed `autoresearch-vault/` is the documented Obsidian vault path, self-loop/self-evolution language is present, and the temporary alternate vault path is no longer referenced.

### P-20260611-003 - Local verification environment lacks Poetry, ruff, and pytest-cov

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-11, while verifying task `1.1`.
- Source: Local command execution in `E:\AIResearch`.
- Symptom: `poetry --version` fails because Poetry is not on PATH. `python -m ruff check ...` fails because `ruff` is not installed in the active Python environment. `python -m pytest tests/unit/config/test_models.py` fails before collecting tests because pyproject addopts include `--cov=src/autoresearch`, but pytest-cov is not installed.
- Impact: Resolved for current Phase 0 test commands. Broad verification commands are now available in the current shell, though future agents should still prefer the project Poetry workflow once dependencies are fully locked.
- Evidence: `poetry --version` returned CommandNotFoundException; `python -m ruff check src/autoresearch/config tests/unit/config/test_models.py` returned `No module named ruff`; `python -m pytest tests/unit/config/test_models.py` reported unrecognized `--cov` arguments.
- Root cause: The active Python environment is not the project Poetry environment and is missing declared dev dependencies.
- Workaround: No longer needed for pytest coverage or Poetry availability in the current shell.
- Next action: During task `1.5`, run and harden the full `ruff`, `mypy`, and pytest command set.
- Linked tasks: `1.1`, `1.4`, `1.5`
- Resolution: Installed Poetry, pytest-cov, pytest-asyncio, and ruff into the active Python environment. Added `pythonpath = ["src"]` to pytest configuration so tests can import the package without manual `PYTHONPATH`.
- Verification: `poetry --version` printed `Poetry (version 2.4.1)`; `poetry run pytest tests/smoke tests/unit/config` passed with 18 tests and coverage enabled; `poetry run pytest tests/smoke tests/unit` passed with 21 tests and coverage enabled.
