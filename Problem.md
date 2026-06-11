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

- Status: Open
- Severity: Medium
- Discovered: 2026-06-11 17:36:49 +08:00
- Source: Repository inspection while preparing project planning documents.
- Symptom: `src/autoresearch/config/__init__.py` imports `.models` and `.parser`, but those files are not present. `pyproject.toml` registers `autoresearch = "autoresearch.cli.main:app"`, but `src/autoresearch/cli/main.py` is not present.
- Impact: Import smoke tests, package installation checks, and CLI execution cannot be treated as passing until the missing modules and tests are implemented.
- Evidence: `rg -n "models|parser|cli|main" -S .` found references in `pyproject.toml` and `src/autoresearch/config/__init__.py`; `rg --files` did not list the referenced modules.
- Root cause: The repository is still in planning/scaffold stage and the previous task plan marked some setup work ahead of implementation reality.
- Workaround: Keep README and tasks explicit that the CLI and broad verification gates are planned Phase 0 work.
- Next action: Implement Phase 0 tasks for config parser, CLI skeleton, import smoke tests, and project test harness.
- Linked tasks: `0.5`, `1.1`, `1.2`, `1.5`, `1.6`
- Resolution: Partially resolved by task `1.1`; `src/autoresearch/config/models.py` now exists and config model imports work. Parser and CLI entry point remain pending.
- Verification: `PYTHONPATH=src python -c "from autoresearch.config import SystemConfig; print(SystemConfig().knowledge_base.vault_path)"` prints `autoresearch-vault`.

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

- Status: Open
- Severity: Medium
- Discovered: 2026-06-11, while verifying task `1.1`.
- Source: Local command execution in `E:\AIResearch`.
- Symptom: `poetry --version` fails because Poetry is not on PATH. `python -m ruff check ...` fails because `ruff` is not installed in the active Python environment. `python -m pytest tests/unit/config/test_models.py` fails before collecting tests because pyproject addopts include `--cov=src/autoresearch`, but pytest-cov is not installed.
- Impact: Broad Phase 0 verification commands from `tasks.md` cannot be treated as available in the current shell until the development environment is installed or commands are run through a proper Poetry environment.
- Evidence: `poetry --version` returned CommandNotFoundException; `python -m ruff check src/autoresearch/config tests/unit/config/test_models.py` returned `No module named ruff`; `python -m pytest tests/unit/config/test_models.py` reported unrecognized `--cov` arguments.
- Root cause: The active Python environment is not the project Poetry environment and is missing declared dev dependencies.
- Workaround: For task `1.1`, run focused tests with `PYTHONPATH=src python -m pytest -o addopts='' tests/unit/config/test_models.py`.
- Next action: During tasks `1.4` and `1.5`, install or document the Poetry/dev dependency environment and restore broad verification commands without disabling addopts.
- Linked tasks: `1.1`, `1.4`, `1.5`
- Resolution: Pending.
- Verification: Pending.
