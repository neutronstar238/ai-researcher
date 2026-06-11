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

### P-20260611-010 - Literature client mypy check failed on requests stubs and Any return

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:56:25 +08:00
- Source: `poetry run mypy src` while verifying task `6.2`.
- Symptom: Mypy reported missing `requests` stubs, an `Any` return from the HTTP helper, and imprecise request parameter dict types.
- Impact: Mocked client tests and ruff passed, but the type gate failed.
- Evidence: Mypy reported errors in `src/autoresearch/literature/clients.py`.
- Root cause: The initial client used `requests` directly and relied on inferred heterogeneous dict types.
- Workaround: None needed after using the standard-library HTTP client and explicit parameter annotations.
- Next action: Keep external API clients mockable and typed without requiring additional runtime stubs.
- Linked tasks: `6.2`
- Resolution: Replaced the default HTTP helper with `urllib.request`, added explicit `dict[str, str | int]` annotations, and cast response bytes before decoding.
- Verification: `poetry run mypy src` passed with no issues in 19 source files.

### P-20260611-009 - Pytest test module basename collision in unit tests

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:52:36 +08:00
- Source: `poetry run pytest tests/unit/literature tests/property/literature tests/smoke tests/unit` while verifying task `6.1`.
- Symptom: Pytest reported an import file mismatch because `tests/unit/config/test_models.py` and `tests/unit/literature/test_models.py` shared the same module basename.
- Impact: Literature tests could not be collected until the new test file used a unique basename.
- Evidence: Pytest reported imported module `test_models` came from `tests/unit/config/test_models.py` instead of `tests/unit/literature/test_models.py`.
- Root cause: Test directories are not Python packages, so duplicate test basenames can collide in pytest import mode.
- Workaround: Use unique test filenames across the repository.
- Next action: Prefer domain-specific test filenames such as `test_literature_models.py`.
- Linked tasks: `6.1`
- Resolution: Renamed the literature unit test file to `tests/unit/literature/test_literature_models.py`.
- Verification: `poetry run pytest tests/unit/literature tests/property/literature tests/smoke tests/unit` passed with 74 tests.

### P-20260611-008 - Hypothesis rejected function-scoped tmp_path in property tests

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:46:08 +08:00
- Source: `poetry run pytest tests/property/knowledge tests/unit/knowledge tests/smoke tests/unit` while verifying task `5.4`.
- Symptom: Hypothesis failed health checks because property tests used the function-scoped `tmp_path` fixture.
- Impact: Permission behavior was not evaluated until the test isolation issue was fixed.
- Evidence: Hypothesis reported `FailedHealthCheck` for function-scoped fixture reuse across generated inputs.
- Root cause: Property tests used a pytest fixture that is not reset for every Hypothesis example.
- Workaround: None needed after replacing the fixture with per-example `TemporaryDirectory`.
- Next action: Use per-example context managers for filesystem property tests unless a fixture is explicitly safe to share.
- Linked tasks: `5.4`
- Resolution: Replaced `tmp_path` fixture usage with `TemporaryDirectory()` inside each property test body.
- Verification: `poetry run pytest tests/property/knowledge tests/unit/knowledge tests/smoke tests/unit` passed with 67 tests.

### P-20260611-007 - Ruff import-order check failed after adding wiki-link support

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:43:06 +08:00
- Source: `poetry run ruff check src tests` while verifying task `5.3`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/knowledge/entries.py`.
- Impact: Tests and mypy passed, but the quality gate required import formatting.
- Evidence: Ruff reported one fixable `I001` finding.
- Root cause: The new `re` import was not placed according to ruff/isort ordering.
- Workaround: None needed after applying ruff's automatic fix.
- Next action: Continue to run `ruff` before marking code tasks complete.
- Linked tasks: `5.3`
- Resolution: Ran `poetry run ruff check src tests --fix`.
- Verification: `poetry run ruff check src tests` passed after the fix.

### P-20260611-006 - Ruff import-order check failed after adding vault helper

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:38:14 +08:00
- Source: `poetry run ruff check src tests` while verifying task `5.1`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/knowledge/vault.py`.
- Impact: Tests and mypy passed, but the quality gate could not pass until import formatting was normalized.
- Evidence: Ruff reported one fixable `I001` finding.
- Root cause: The new file import block did not match ruff/isort formatting expectations.
- Workaround: None needed after applying ruff's automatic fix.
- Next action: Continue to run `ruff` before marking code tasks complete.
- Linked tasks: `5.1`
- Resolution: Ran `poetry run ruff check src tests --fix`.
- Verification: `poetry run ruff check src tests` passed after the fix.

### P-20260611-005 - CostRecord broke generic schema validation-field assertion

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:29:59 +08:00
- Source: `poetry run pytest tests/unit/schemas tests/smoke tests/unit` while verifying task `3.3`.
- Symptom: `test_core_schemas_instantiate_and_serialize_to_json` failed because `CostRecord` does not contain a validation status field.
- Impact: The new cost schema behavior was valid, but the generic test assertion needed to account for non-validation bookkeeping records.
- Evidence: Pytest reported `assert "validation" in payload or isinstance(record, ExecutionRun)` failed for a serialized `CostRecord`.
- Root cause: The test list was extended with `CostRecord` without updating the existing assertion exception.
- Workaround: None needed after the assertion update.
- Next action: Re-run schema tests, ruff, and mypy before marking task `3.3` complete.
- Linked tasks: `3.3`
- Resolution: Updated the assertion so both `ExecutionRun` and `CostRecord` are accepted as lifecycle bookkeeping records without validation status.
- Verification: `poetry run pytest tests/unit/schemas tests/smoke tests/unit` passed with 45 tests after the assertion update.

### P-20260611-004 - PowerShell rejected Bash-style commit command separator

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 18:27:08 +08:00
- Source: Local command execution while committing task `3.2`.
- Symptom: `git add ... && git commit ...` failed with `The token '&&' is not a valid statement separator in this version.`
- Impact: No source changes, staging changes, or verification results were affected.
- Evidence: PowerShell returned `ParserError` before running the git commands.
- Root cause: The command used a Bash-style `&&` separator in the active PowerShell environment.
- Workaround: Run `git add` and `git commit` as separate PowerShell commands.
- Next action: Prefer separate commands or PowerShell-compatible separators in this repository.
- Linked tasks: `3.2`
- Resolution: Recorded the failed command and retried with PowerShell-compatible git commands.
- Verification: Retried using separate `git add` and `git commit` commands for task `3.2`.

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
