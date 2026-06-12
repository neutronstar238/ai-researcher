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

### P-20260612-081 - Third-party notice compliance test asserted a wrapped sentence

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 23:54:51 +08:00
- Source: `poetry run pytest tests/unit/compliance/test_licenses.py -q` during task `59.1` verification.
- Symptom: The new notice test failed because it looked for the exact sentence fragment `does not copy, vendor, adapt, or redistribute`, while the Markdown paragraph wrapped between `does not` and `copy`.
- Impact: The third-party notice content was present, but the regression test was brittle and blocked task verification.
- Evidence: Pytest reported one failing assertion in `test_project_notice_tracks_third_party_reference_policy`.
- Root cause: The test asserted a line-sensitive phrase instead of the stable policy clause.
- Workaround: None needed after the test assertion was made less brittle.
- Next action: Prefer compact invariant phrases for Markdown policy tests.
- Linked tasks: `59.1`
- Resolution: Changed the assertion to check the stable phrase `copy, vendor, adapt, or redistribute`.
- Verification: `poetry run pytest tests/unit/compliance/test_licenses.py -q` passed with 5 tests after the fix.

### P-20260612-080 - Documentation rename pass left extra blank lines at EOF

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 23:48:24 +08:00
- Source: `git diff --check` during task `58.1` verification.
- Symptom: Git reported `new blank line at EOF` for `tasks.md`, both README files, `CHANGELOG.md`, `autoresearch-vault/Home.md`, and `docs/deployment/kubernetes-plan.md`.
- Impact: The rename task could not pass the whitespace gate until generated document endings were normalized.
- Evidence: `git diff --check` listed six Markdown files with extra EOF blank lines.
- Root cause: The targeted PowerShell documentation replacement preserved an extra trailing blank line in several Markdown files.
- Workaround: None needed after trimming the affected files to a single final newline.
- Next action: Keep running `git diff --check` after mechanical documentation rewrites.
- Linked tasks: `58.1`
- Resolution: Trimmed the affected Markdown files to a single final newline.
- Verification: `git diff --check` passed after the cleanup.

### P-20260612-077 - Autopilot helper type annotations failed mypy

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 23:05:19 +08:00
- Source: `poetry run mypy src` during task `54.1` verification.
- Symptom: Mypy reported an invariant `list[Path]` argument where `list[Path | str]` was expected, plus an unsafe `Path(object)` conversion in `_path_text`.
- Impact: The new autopilot CLI could not pass the repository type gate.
- Evidence: `src\autoresearch\cli\main.py:1216` and `src\autoresearch\cli\main.py:1290` were reported by mypy.
- Root cause: Helper annotations were narrower than the called LLM review API and did not narrow an `object` path value before converting it.
- Workaround: None needed after the type fix.
- Next action: Keep CLI helper arguments aligned with provider APIs that accept both `Path` and `str`.
- Linked tasks: `54.1`
- Resolution: Changed the review helper evidence list to `list[Path | str]` and narrowed `_path_text` for `Path`, `str`, and fallback objects.
- Verification: `poetry run mypy src` passed with no issues found in 85 source files after the annotation and path-narrowing fix.

### P-20260612-078 - Autopilot LLM review lacked metric-value evidence

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 23:09:10 +08:00
- Source: Real `.env` single-cycle run of `poetry run autoresearch autopilot` during task `54.1`.
- Symptom: The cycle completed, but the live DeepSeek evidence review returned `review_status: below_threshold` with quality score `0.5` and did not promote review issues into the Obsidian project memory.
- Impact: The first autonomous loop could execute literature discovery, similarity checking, and a local experiment, but could not safely create self-loop follow-up tasks from the reviewer output.
- Evidence: `runs/manual-live/autopilot/cycle-20260612T150910Z/llm-review.json` reported unsupported metric claims because the evidence pack lacked the run record containing metric values.
- Root cause: The autopilot reviewer passed the validation report and evidence map, but not the ScientistBench-Lite run record that stores the concrete metrics referenced in the generated report.
- Workaround: None needed after the evidence pack fix.
- Next action: Fix the report generator evidence IDs and reproduction metadata issues that the passing live reviewer surfaced as blocking follow-ups.
- Linked tasks: `54.1`
- Resolution: Added the demo `run_record_path` to the autopilot LLM reviewer evidence bundle.
- Verification: A second real `.env` run with DeepSeek `deepseek-v4-flash` returned `review_status: passed`, quality score `1.0`, and wrote four Obsidian review issue notes plus four scheduler follow-up tasks.
- Follow-up update: Task `56.1` added reproduction metadata to run records and clarified the reviewer prompt; a real DeepSeek review of the fixed report returned verdict `pass` with quality score `1.0`.

### P-20260612-079 - Autopilot empty-literature CLI test asserted separate stderr capture

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 23:18:00 +08:00
- Source: Focused task `54.1` test run for the new empty-literature CLI failure branch.
- Symptom: `test_autopilot_command_reports_empty_literature_result` failed with `ValueError: stderr not separately captured`.
- Impact: The new user-facing error branch could not be verified until the test matched the configured Click runner behavior.
- Evidence: `poetry run pytest tests/unit/cli/test_main.py::test_autopilot_command_runs_one_non_review_cycle tests/unit/cli/test_main.py::test_autopilot_command_reports_empty_literature_result tests/unit/cli/test_main.py::test_slash_commands_init_and_list_project_templates -q` failed one test.
- Root cause: `CliRunner` in this environment merges stderr into `result.output`; the assertion incorrectly read `result.stderr`.
- Workaround: None needed after the assertion fix.
- Next action: Prefer `result.output` for Typer CLI tests in this repository unless a test explicitly opts into separate stderr capture.
- Linked tasks: `54.1`
- Resolution: Updated the assertion to check the merged CLI output.
- Verification: `poetry run pytest tests/unit/cli/test_main.py::test_autopilot_command_runs_one_non_review_cycle tests/unit/cli/test_main.py::test_autopilot_command_reports_empty_literature_result tests/unit/cli/test_main.py::test_slash_commands_init_and_list_project_templates -q` passed with 3 tests.

### P-20260612-080 - Obsidian vault test import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 23:30:00 +08:00
- Source: Focused task `55.1` ruff check after adding Obsidian vault setup tests.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `tests/unit/knowledge/test_vault.py`.
- Impact: The new Obsidian helper tests passed, but the formatting gate failed.
- Evidence: `poetry run ruff check src/autoresearch/knowledge src/autoresearch/cli/main.py tests/unit/knowledge/test_vault.py tests/unit/cli/test_main.py` returned one fixable import-order error.
- Root cause: The new `create_obsidian_vault_assets` import was not ordered according to ruff/isort.
- Workaround: None needed after automatic formatting.
- Next action: Continue running ruff before marking code tasks complete.
- Linked tasks: `55.1`
- Resolution: Ran `poetry run ruff check tests/unit/knowledge/test_vault.py --fix`.
- Verification: `poetry run ruff check src/autoresearch/knowledge src/autoresearch/cli/main.py tests/unit/knowledge/test_vault.py tests/unit/cli/test_main.py` passed after formatting.

### P-20260612-076 - Focused test command used stale deploy-setup node name

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 18:02:00 +08:00
- Source: `poetry run pytest tests/unit/literature/test_clients.py tests/unit/cli/test_main.py::test_deploy_setup_writes_env_and_non_secret_config -q` during task `52.1` verification.
- Symptom: Pytest collected zero items and reported `not found` for `test_deploy_setup_writes_env_and_non_secret_config`.
- Impact: The first focused verification command did not exercise the intended deploy-setup template regression test.
- Evidence: `rg -n "def test_deploy_setup" tests\unit\cli\test_main.py` showed the current test name is `test_deploy_setup_writes_provider_config_and_env_without_committing_secret`.
- Root cause: The verification command used a stale guessed test node name.
- Workaround: None needed after rerunning the correct test node.
- Next action: Use `rg` to confirm exact pytest node names before running narrow checks when a test was renamed.
- Linked tasks: `52.1`
- Resolution: Re-ran the focused check with the correct test node.
- Verification: `poetry run pytest tests/unit/literature/test_clients.py tests/unit/cli/test_main.py::test_deploy_setup_writes_provider_config_and_env_without_committing_secret -q` passed with 8 tests.

### P-20260612-075 - Scheduler-state missing-task test read uncaptured stderr

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 17:49:59 +08:00
- Source: `poetry run pytest tests/unit/cli/test_main.py::test_issue_followups_command_lists_open_project_issue_tasks tests/unit/cli/test_main.py::test_scheduler_state_commands_list_complete_and_remove_tasks tests/unit/cli/test_main.py::test_issue_followups_state_merge_preserves_completed_tasks -q` during task `51.1` verification.
- Symptom: The scheduler-state command test failed with `ValueError: stderr not separately captured`.
- Impact: The new scheduler-state CLI behavior could not pass the focused test gate, even though the command returned the expected non-zero status.
- Evidence: `missing_complete_result.stderr` raised because this repository's `CliRunner` invocation merges stderr into `output`.
- Root cause: The test used the wrong Click result stream for this local test runner setup.
- Workaround: None needed after the test fix.
- Next action: Use `result.output` for command-line failure text unless a test explicitly configures separate stderr capture.
- Linked tasks: `51.1`
- Resolution: Changed the assertion to inspect `missing_complete_result.output`.
- Verification: `poetry run pytest tests/unit/cli/test_main.py::test_issue_followups_command_lists_open_project_issue_tasks tests/unit/cli/test_main.py::test_scheduler_state_commands_list_complete_and_remove_tasks tests/unit/cli/test_issue_followups_state_merge_preserves_completed_tasks -q` passed with 3 tests after the assertion fix. `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` also passed.

### P-20260612-074 - Issue follow-up state records inferred as too narrow for mypy

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 17:43:05 +08:00
- Source: `poetry run mypy src` during task `50.1` verification.
- Symptom: Mypy failed with `Argument 2 to "_merge_scheduler_state" has incompatible type "list[dict[str, Collection[str]]]"; expected "list[dict[str, object]]"`.
- Impact: The issue follow-up scheduler state change could not pass the repository type gate.
- Evidence: The generated `records` list mixed strings and nested metadata dictionaries, so mypy inferred an overly specific collection type.
- Root cause: The list literal did not have an explicit `list[dict[str, object]]` annotation at the construction point.
- Workaround: None needed after the fix.
- Next action: Add explicit container annotations when CLI JSON records mix scalar and nested object fields.
- Linked tasks: `50.1`
- Resolution: Annotated `records` as `list[dict[str, object]]` before passing it to the state merge helper.
- Verification: `poetry run mypy src` passed with no issues found in 85 source files after the annotation. `poetry run ruff check src tests` passed. `poetry run pytest tests/unit/cli/test_main.py::test_issue_followups_command_lists_open_project_issue_tasks -q` passed. `poetry run pytest tests/smoke tests/unit -q` passed with 301 passed and 4 skipped.

### P-20260612-073 - Scheduler issue follow-up test import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 17:31:28 +08:00
- Source: `poetry run ruff check src tests` during task `48.1` verification.
- Symptom: Ruff failed with `tests\unit\test_scheduler.py:1:1: I001 [*] Import block is un-sorted or un-formatted`.
- Impact: The Obsidian issue scheduler adapter could not pass the repository lint gate.
- Evidence: The new `autoresearch.knowledge` import was placed after `autoresearch.observability`.
- Root cause: The test import block was not kept in ruff/isort order after adding scheduler issue-note coverage.
- Workaround: None needed after the fix.
- Next action: Keep local package imports sorted alphabetically when adding focused scheduler tests.
- Linked tasks: `48.1`
- Resolution: Moved the `autoresearch.knowledge` import before `autoresearch.observability`.
- Verification: `poetry run ruff check src tests` passed after the import-order fix. `poetry run mypy src` passed with no issues found in 85 source files. `poetry run pytest tests/unit/test_scheduler.py -q` passed with 5 tests. `poetry run pytest tests/smoke tests/unit -q` passed with 300 passed and 4 skipped.

### P-20260612-072 - Stable issue fingerprint helper failed ruff UP012

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 17:24:55 +08:00
- Source: `poetry run ruff check src tests` during task `47.1` verification.
- Symptom: Ruff failed with `src\autoresearch\llm\review_memory.py:286:19: UP012 [*] Unnecessary UTF-8 encoding argument to encode`.
- Impact: The LLM review issue deduplication change could not pass the repository lint gate.
- Evidence: The fingerprint helper used `.encode("utf-8")` when the default UTF-8 encoding is sufficient.
- Root cause: The new hash helper was written with an explicit encoding argument that violates the configured pyupgrade rule.
- Workaround: None needed after the fix.
- Next action: Prefer `.encode()` for UTF-8 byte hashing unless a non-default encoding is required.
- Linked tasks: `47.1`
- Resolution: Removed the unnecessary `"utf-8"` argument from the fingerprint helper.
- Verification: `poetry run ruff check src tests` passed after the fix. `poetry run mypy src` passed with no issues found in 85 source files. `poetry run pytest tests/unit/llm/test_review_memory.py tests/unit/cli/test_main.py::test_llm_review_command_writes_local_evidence_report -q` passed with 4 tests. `poetry run pytest tests/smoke tests/unit -q` passed with 299 passed and 4 skipped.

### P-20260612-071 - Review issue writer returned untyped JSON verdict through a typed string helper

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 17:14:56 +08:00
- Source: `poetry run mypy src` during task `46.1` verification.
- Symptom: `mypy` failed with `src/autoresearch/llm/review_memory.py:285: error: Returning Any from function declared to return "str"`.
- Impact: The review-to-issue promotion code could not pass the repository type gate.
- Evidence: The helper returned `parsed["verdict"]` after a runtime type check on `parsed.get("verdict")`, but mypy still inferred the indexed lookup as `Any`.
- Root cause: The code narrowed the `dict.get()` result but returned a separate indexed access.
- Workaround: None needed after the fix.
- Next action: Keep JSON-derived values in local typed variables before returning them from typed helpers.
- Linked tasks: `46.1`
- Resolution: Stored the verdict in a local variable, checked `isinstance(verdict, str)`, and returned that narrowed value.
- Verification: `poetry run mypy src` passed with no issues found in 85 source files after the fix. `poetry run ruff check src tests` passed. `poetry run pytest tests/smoke tests/unit -q` passed with 298 passed and 4 skipped. A real DeepSeek `autoresearch llm-review` run with `--vault runs/manual-live/review-vault-issues --project-id deepseek_live_project --source-task-id 46.1 --max-tokens 2400` passed the quality gate and wrote one review note plus two issue notes.

### P-20260612-070 - DeepSeek reviewer sometimes exhausts 1600 output tokens before returning content

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 17:04:55 +08:00
- Source: Real `autoresearch llm-review --project-id` verification for task `45.1`.
- Symptom: The configured DeepSeek V4 Flash model returned an empty `message.content` at the previous 1600 review token budget.
- Impact: Live review verification could fail before writing a JSON report or Obsidian review note, even though the same prompt can succeed with a larger budget.
- Evidence: `poetry run autoresearch llm-review ... --vault runs/manual-live/review-vault --project-id deepseek_live_project --source-task-id 45.1` failed with `LLM API message content is empty; reasoning models may need a higher --max-tokens value`.
- Root cause: Reasoning-token models can spend variable output budget before emitting final JSON; 1600 tokens was not stable enough for the evidence-constrained reviewer prompt.
- Workaround: Users can still pass `--max-tokens` explicitly for larger reviews.
- Next action: Track provider-specific behavior and consider model-aware token defaults if more providers show different output-budget needs.
- Linked tasks: `45.1`
- Resolution: Raised the LLM review default token budget from 1600 to 2400 and updated README examples.
- Verification: `poetry run autoresearch llm-review --subject runs/manual-live/demo/tabular-baseline/report/report.md --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json --config config.yaml --env-path .env --output runs/llm-review/latest-vault.json --min-quality-score 0.85 --vault runs/manual-live/review-vault --project-id deepseek_live_project --source-task-id 45.1 --max-tokens 2400` passed with quality score `1.000`, verdict `fail`, and wrote `runs/manual-live/review-vault/projects/deepseek_live_project/review/llm-review-report-a332eff33a58.md`; `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/smoke tests/unit -q` passed with 297 tests and 4 skipped.

### P-20260612-069 - LLM reviewer could pass weak evidence discipline without hard local citation gates

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 16:47:51 +08:00
- Source: User follow-up requesting an LLM-as-reviewer stage that must cite local evidence instead of inventing quality conclusions.
- Symptom: The first real `llm-review` call scored above the threshold even though one finding had empty `evidence_refs`. A later real call used nested evidence-map IDs instead of the allowed outer evidence IDs.
- Impact: A model reviewer could make unsupported or ambiguous review findings look acceptable, undermining the evidence-first validation loop.
- Evidence: `poetry run autoresearch llm-review ... --max-tokens 900` initially exposed a missing-reference finding; after hard gates were added, a default live call correctly failed at quality score `0.500` when the model cited nested IDs like `evidence_3bb...` instead of `evidence_1` or `evidence_2`.
- Root cause: The deterministic review quality score treated evidence-reference checks as ordinary weighted checks, and the first prompt did not clearly distinguish outer reviewer evidence IDs from IDs nested inside evidence artifacts. The 900 token budget was also too low for some reasoning-token model responses.
- Workaround: None needed after the fix; users can still override `--max-tokens` for unusually large reviews.
- Next action: Add more real provider fixtures if other models use different invalid citation patterns.
- Linked tasks: `44.1`
- Resolution: Added `autoresearch llm-review`, made missing/unknown evidence refs hard quality failures, listed allowed evidence IDs explicitly in the review prompt, prohibited nested file IDs as reviewer citations, raised the default review token budget to 1600, and documented the workflow in both README files.
- Verification: `poetry run pytest tests/unit/llm/test_client.py tests/unit/cli/test_main.py::test_llm_review_command_writes_local_evidence_report -q` passed with 6 tests; `poetry run ruff check src tests` passed; `poetry run mypy src` passed; `poetry run pytest tests/smoke tests/unit -q` passed with 296 tests and 4 skipped; final real DeepSeek `poetry run autoresearch llm-review --subject runs/manual-live/demo/tabular-baseline/report/report.md --evidence runs/manual-live/demo/tabular-baseline/validation/validation-report.json --evidence runs/manual-live/demo/tabular-baseline/evidence/evidence-map.json --config config.yaml --env-path .env --output runs/llm-review/latest.json --min-quality-score 0.85` passed with quality score `1.000` and verdict `needs_revision`.

### P-20260612-068 - Semantic Scholar live access needed explicit throttling and circuit breaking

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 16:34:43 +08:00
- Source: User follow-up after live literature/similarity smoke tests exposed intermittent Semantic Scholar connection reset and HTTP 429 behavior.
- Symptom: Semantic Scholar requests used the same simple retry path as other sources, had no optional API key header, and could retry immediately after HTTP 429.
- Impact: Online discovery could waste calls during provider rate limits and make real API smoke outcomes noisy, especially without a Semantic Scholar API key.
- Evidence: Prior full-chain verification recorded Semantic Scholar connection reset and HTTP 429 fetch errors while ArXiv-backed paths passed.
- Root cause: The first live literature client implementation prioritized real source calls and visible error preservation, but did not yet model Semantic Scholar's stricter access limits.
- Workaround: None needed after the fix; users can optionally add `SEMANTIC_SCHOLAR_API_KEY` to ignored `.env`.
- Next action: Track real-world provider behavior and tune cooldown/rate defaults if Semantic Scholar changes limits.
- Linked tasks: `43.1`
- Resolution: Added optional `x-api-key` support, conservative unauthenticated rate limiting, exponential retry backoff, and a 429 circuit breaker for Semantic Scholar. Updated CLI `.env` loading and documentation so local smoke tests remain local-only while live smoke tests are explicit.
- Verification: `poetry run pytest tests/unit/literature tests/unit/cli/test_main.py tests/smoke/test_literature_live.py -q` passed with 27 passed and 1 skipped; `poetry run ruff check src tests` passed; `poetry run mypy src` passed with no issues in 84 source files; `AUTORESEARCH_LIVE_APIS=1 poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py tests/smoke/test_similarity_live.py -q` passed with 3 real API smoke tests.

### P-20260612-067 - Python 3.10 CI test collection failed on runtime-subscripted LoggerAdapter

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 16:16:41 +08:00
- Source: User-provided GitHub Actions `Python 3.10` log for commit `bbf4687`.
- Symptom: `poetry run pytest tests/smoke tests/unit` collected tests but failed during import collection with 51 errors ending in `TypeError: 'type' object is not subscriptable`.
- Impact: CI could not reach smoke or unit test execution on the Python 3.10 runner even though Python 3.13 local tests passed.
- Evidence: The traceback pointed to `src/autoresearch/observability/logging.py:16`, where `ContextLoggerAdapter` inherited from `logging.LoggerAdapter[logging.Logger]`.
- Root cause: `logging.LoggerAdapter` is not runtime-subscriptable on Python 3.10, so importing observability logging raised before tests could run.
- Workaround: None needed after the fix.
- Next action: Keep standard-library runtime generics compatible with the minimum supported Python version, or guard them behind type-checking-only aliases.
- Linked tasks: `42.1`
- Resolution: Changed the logging adapter base class to inherit from `logging.LoggerAdapter` without a runtime generic subscript.
- Verification: Python 3.10 Poetry environment passed `poetry run pytest tests/smoke tests/unit -q` with 289 passed and 4 skipped; `poetry run ruff check src tests` passed; `poetry run mypy src` passed with no issues in 84 source files.

### P-20260612-066 - LLM smoke quality gate missed fact-checking evidence policy wording

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 15:57:29 +08:00
- Source: Real `autoresearch llm-smoke` run against the configured DeepSeek V4 Flash model.
- Symptom: The model output passed the quality threshold but `evidence_policy_present` failed when the model wrote `All outputs require manual fact-checking before use.`
- Impact: Quality inspection could under-score acceptable evidence-discipline language and produce confusing reports.
- Evidence: `runs/llm-smoke/manual-full-chain.json` recorded quality score `0.889` with only `evidence_policy_present` failing.
- Root cause: The evidence-policy detector recognized `evidence`, `source`, `verified`, `verification`, `pending`, and `unknown`, but not common fact-checking wording.
- Workaround: None needed after the fix.
- Next action: Add more real-output examples as fixtures if additional provider wording appears.
- Linked tasks: `41`
- Resolution: Updated the LLM smoke prompt to request source-backed evidence or independent fact-checking language and updated the quality detector to accept fact-checking phrases.
- Verification: Rerun `poetry run autoresearch llm-smoke --config config.yaml --env-path .env --output runs/llm-smoke/manual-full-chain-v2.json --min-quality-score 0.85 --max-tokens 600` passed with quality score `1.000`.

### P-20260612-065 - GitHub Actions mypy failed on Windows-only subprocess attribute

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 15:39:56 +08:00
- Source: User-provided GitHub Actions screenshot for the Python 3.10 job.
- Symptom: `poetry run mypy src` failed with `src/autoresearch/experiments/executor.py:172: error: Module has no attribute "CREATE_NEW_PROCESS_GROUP" [attr-defined]`.
- Impact: CI failed on Linux runners even though the runtime branch using the constant is Windows-only.
- Evidence: GitHub Actions log showed one mypy error in `src/autoresearch/experiments/executor.py` and an unused-config warning from `pyproject.toml`.
- Root cause: The code directly referenced `subprocess.CREATE_NEW_PROCESS_GROUP`, which is only exposed on Windows, and mypy checked the attribute against the Linux/Python 3.10 environment.
- Workaround: None needed after the fix.
- Next action: Keep OS-specific subprocess constants behind `getattr` or platform-specific helper functions.
- Linked tasks: `40`
- Resolution: Changed the Windows process-group flag lookup to `getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)` and removed stale mypy override entries.
- Verification: `poetry run mypy src` passed with no issues in 82 source files; `poetry run ruff check src tests` passed; `poetry run pytest tests/unit/cli/test_main.py -vv` passed with 12 tests; `poetry run pytest tests/unit/experiments/test_executor.py -vv` passed with 4 tests; `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed with 303 tests and 3 skipped.

### P-20260612-064 - similarity-check CLI rejected Windows UTF-8 BOM candidate JSON

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 15:15:10 +08:00
- Source: Real CLI live verification for `autoresearch similarity-check` using a temporary candidate JSON file written by PowerShell `Set-Content -Encoding UTF8`.
- Symptom: `similarity-check` failed before network execution with `Invalid candidate JSON at line 1, column 1: Unexpected UTF-8 BOM`.
- Impact: Windows users could create a valid-looking candidate JSON file that the CLI rejected during project-start similarity checks.
- Evidence: `autoresearch literature-refresh` succeeded against live ArXiv data, then `autoresearch similarity-check --candidate-file <tmp>/candidate.json ...` failed on the candidate JSON BOM.
- Root cause: The CLI read candidate JSON with `encoding="utf-8"` instead of accepting UTF-8 with BOM.
- Workaround: None needed after the fix.
- Next action: Keep CLI file readers tolerant of common Windows UTF-8 BOM output where the file format permits it.
- Linked tasks: `38`
- Resolution: Updated `_load_candidate` to read with `utf-8-sig`.
- Verification: `poetry run pytest tests/unit/cli/test_main.py -vv` passed after the fix, and the real `autoresearch similarity-check --candidate-file <bom-json> ...` CLI run completed with a source-backed finding and project-link note.

### P-20260612-063 - Task 2 schema verification referenced missing property test path

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 14:57:19 +08:00
- Source: Task `2` parent verification command `poetry run pytest tests/unit/schemas tests/property/schemas -vv`.
- Symptom: Pytest failed before running schema tests because `tests/property/schemas` does not exist.
- Impact: Parent task `2` could not be marked complete using the stale documented command.
- Evidence: Pytest reported `ERROR: file or directory not found: tests/property/schemas` and collected zero tests.
- Root cause: Schema round-trip and validation tests currently live in `tests/unit/schemas`; no property schema directory was created.
- Workaround: Use the actual schema test suite path.
- Next action: Add a dedicated `tests/property/schemas` suite before documenting that path again.
- Linked tasks: `2`
- Resolution: Updated task `2.3` verification text to use `poetry run pytest tests/unit/schemas -vv`.
- Verification: `poetry run pytest tests/unit/schemas -vv` passed with 30 tests after the task verification path was corrected.

### P-20260612-062 - Task 0 parent verification found missing task-driven wording

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 14:53:46 +08:00
- Source: Task 0 parent verification command checking `AGENTS.md` acceptance phrases.
- Symptom: Verification failed because `AGENTS.md` mentioned task-scoped work but did not contain the explicit `task-driven` wording required by task `0.1`.
- Impact: Parent task `0` could not be honestly marked complete until the repository-wide agent instructions directly satisfied the documented acceptance check.
- Evidence: The verification script reported `Missing pattern 'task-driven' in AGENTS.md`.
- Root cause: Earlier instructions captured the behavior through task and commit rules without the exact acceptance wording.
- Workaround: None needed after updating `AGENTS.md`.
- Next action: Use explicit acceptance language when parent tasks verify documentation requirements.
- Linked tasks: `0`
- Resolution: Added a task-driven work rule to the `AGENTS.md` implementation discipline section.
- Verification: Task `0` parent verification rerun passed after the `AGENTS.md` wording update.

### P-20260612-061 - Sandbox property test hit Hypothesis deadline on Windows

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 14:29:00 +08:00
- Source: `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` during Checkpoint B verification.
- Symptom: `tests/property/experiments/test_sandbox.py::test_sandbox_allows_configured_cache_and_output_dirs` failed as a Hypothesis flaky failure because the first generated example exceeded the default 200 ms deadline.
- Impact: Checkpoint B full-suite verification could not pass until the property test allowed normal Windows filesystem timing variability.
- Evidence: Hypothesis reported `DeadlineExceeded: Test took 746.90ms, which exceeds the deadline of 200.00ms`, then marked the test flaky when a later rerun took 19.56 ms.
- Root cause: The property test creates temporary directories and resolves filesystem paths; on Windows the first run can exceed Hypothesis' default deadline even though the property outcome is stable.
- Workaround: None needed after disabling the deadline for this filesystem timing-sensitive property test.
- Next action: Keep Hypothesis deadlines disabled or relaxed for filesystem-heavy property tests that are validating correctness rather than performance.
- Linked tasks: Checkpoint B
- Resolution: Added `@settings(deadline=None)` to `test_sandbox_allows_configured_cache_and_output_dirs`.
- Verification: `poetry run pytest tests/property/experiments/test_sandbox.py -vv` passed with 7 tests, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed with 295 passed and 3 skipped after the deadline setting update.

### P-20260612-060 - Docker Python 3.13 image forced NumPy source build

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 13:46:39 +08:00
- Source: `docker compose build app` using `python:3.13-slim`.
- Symptom: Docker build failed while installing project dependencies because `numpy 1.26.4` attempted a source build and no compiler was available in the slim image.
- Impact: Task `34.1` container verification could not pass with the initial Dockerfile base image.
- Evidence: Build failed with Meson reporting unknown compilers `cc`, `gcc`, and `clang` while preparing NumPy metadata.
- Root cause: The project dependency set pulled `numpy<2.0.0,>=1.26.0` through LangChain; NumPy `1.26.4` has wheels for Python 3.12 but not for Python 3.13 in the tested build path.
- Workaround: Use a supported Python runtime with available wheels.
- Next action: Keep the Docker runtime on Python 3.12 until the dependency set is updated for Python 3.13 wheels.
- Linked tasks: `34.1`
- Resolution: Changed `deploy/docker/Dockerfile` from `python:3.13-slim` to `python:3.12-slim`.
- Verification: `docker compose build app` completed successfully after the base image change.

### P-20260612-059 - Docker daemon unavailable before Compose verification

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 13:46:39 +08:00
- Source: `docker compose build app`.
- Symptom: Docker Compose could not connect to `npipe:////./pipe/dockerDesktopLinuxEngine`.
- Impact: Task `34.1` real container verification was blocked until the Docker daemon was reachable.
- Evidence: Compose reported `failed to connect to the docker API ... The system cannot find the file specified`; `docker context ls` showed `desktop-linux`; `com.docker.service` was stopped.
- Root cause: Docker Desktop Linux engine was not running at the start of verification.
- Workaround: Start Docker Desktop and wait until `docker info` succeeds.
- Next action: Check Docker daemon readiness before future container verification tasks.
- Linked tasks: `34.1`
- Resolution: Started Docker Desktop; a direct service start attempt lacked permission, but Docker Desktop came up and `docker info` succeeded.
- Verification: After Docker Desktop started, `docker compose build app` and `docker compose run --rm app` reached the Docker engine.

### P-20260612-058 - Plugin sample test used stale schema and colliding filename

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 13:37:33 +08:00
- Source: `poetry run pytest tests/unit/plugins/test_registry.py -vv` and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`.
- Symptom: The first plugin sample test failed because the fixture used unsupported `AcademicPaper` fields; after fixing that, full pytest failed with an import mismatch because `tests/unit/plugins/test_registry.py` shared a basename with `tests/property/agents/test_registry.py`.
- Impact: Task `33.1` sample plugin verification could not be accepted until the fixture matched the real model and the test module name was unique.
- Evidence: Pydantic rejected extra fields `paper_id` and `published_year`; pytest later reported imported module `test_registry` came from the unit plugin test while collecting the property agent registry test.
- Root cause: The sample fixture was written from an assumed paper schema, and the new test file used a generic basename already present elsewhere in the suite.
- Workaround: None needed after the fixture and filename fixes.
- Next action: Use actual model fields when writing fixtures, and prefer domain-specific test filenames such as `test_plugin_registry.py`.
- Linked tasks: `33.1`
- Resolution: Updated the sample paper fixture to use the real `AcademicPaper` fields, renamed the test file to `tests/unit/plugins/test_plugin_registry.py`, and cleared test caches before rerunning full pytest.
- Verification: Focused plugin ruff, mypy, focused plugin pytest, full ruff, and full pytest passed after the fixes.

### P-20260612-057 - Requests dependency warning appears during verification

- Status: Open
- Severity: Low
- Discovered: 2026-06-12 13:30:54 +08:00
- Source: `poetry run ruff check ...`, `poetry run mypy src`, and `poetry run pytest ...`.
- Symptom: Python emitted `RequestsDependencyWarning` stating `urllib3 (2.7.0) or chardet (7.4.3)/charset_normalizer (3.4.7) doesn't match a supported version`.
- Impact: Task `32.1` verification still passed, but future real-network smoke tests may produce noisy output or dependency-sensitive behavior if this environment mismatch remains.
- Evidence: The warning appeared after focused ruff, focused mypy, focused pytest, full ruff, and full pytest commands; full pytest still reported `281 passed, 3 skipped`.
- Root cause: The active test environment has a `requests` dependency combination that `requests` warns is outside its supported range.
- Workaround: Treat the warning as non-blocking for non-network authorization work; keep real external API tests mandatory for external-source tasks.
- Next action: Resolve or pin the `requests` transitive dependency set in a dedicated dependency-maintenance task before relying on warning-free live network output.
- Linked tasks: `32.1`
- Resolution: Not resolved in task `32.1`; no authorization code path uses `requests`.
- Verification: `poetry run ruff check src tests` passed; `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed with `281 passed, 3 skipped` despite the warning.

### P-20260612-056 - Dashboard test import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 13:25:03 +08:00
- Source: `poetry run ruff check src/autoresearch/observability/dashboard.py src/autoresearch/observability/__init__.py tests/unit/observability/test_dashboard.py`.
- Symptom: Ruff reported `I001` in `tests/unit/observability/test_dashboard.py`.
- Impact: Task `31.2` focused lint verification was blocked until the test import block was sorted.
- Evidence: Ruff reported the import block was unsorted or unformatted.
- Root cause: New dashboard test imports were inserted without matching ruff/isort ordering.
- Workaround: None needed after ruff autofix.
- Next action: Keep new public API imports sorted when extending observability tests.
- Linked tasks: `31.2`
- Resolution: Ran `poetry run ruff check tests/unit/observability/test_dashboard.py --fix`.
- Verification: Focused ruff, `poetry run mypy src`, focused dashboard pytest, full ruff, and full pytest passed after the import-order fix.

### P-20260612-055 - Browser file URL and initial temp server QA path failed

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 13:25:03 +08:00
- Source: Browser QA for `file:///C:/Users/Z/AppData/Local/Temp/ai-researcher-dashboard-qa/index.html`, then temporary local HTTP server startup on port `8765`.
- Symptom: Browser Use rejected direct `file://` navigation; the first temporary HTTP server readiness check could not connect.
- Impact: Task `31.2` browser-based desktop and mobile QA could not use direct file navigation or the first server startup path.
- Evidence: Browser returned `Browser Use cannot visit the requested page because its URL is blocked by the Browser Use URL policy`; `Invoke-WebRequest` initially reported it could not connect to the remote server.
- Root cause: Browser security policy disallows direct `file://` navigation, and the first `Start-Process -FilePath "poetry"` temp-server path did not become reachable.
- Workaround: Serve the same generated static dashboard with `python -m http.server` bound to `127.0.0.1`.
- Next action: For static browser QA, use a temporary local HTTP server instead of `file://`.
- Linked tasks: `31.2`
- Resolution: Started `python -m http.server 8765 --bind 127.0.0.1` from the generated dashboard directory, verified HTTP 200, completed desktop and mobile Browser QA, then stopped the server.
- Verification: Local HTTP returned status `200`; Browser desktop QA passed with no console issues and run filtering working; Browser mobile QA passed with no console issues and no page overflow.

### P-20260612-054 - Reward export import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:56:56 +08:00
- Source: `poetry run ruff check src/autoresearch/experiments/reward.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_reward.py`.
- Symptom: Ruff reported `I001` in `src/autoresearch/experiments/__init__.py`.
- Impact: Task `28.2` focused lint verification was blocked.
- Evidence: Ruff reported the import block was unsorted or unformatted.
- Root cause: New reward exports were inserted without matching ruff/isort ordering.
- Workaround: None needed after ruff autofix.
- Next action: None.
- Linked tasks: `28.2`
- Resolution: Ran ruff autofix on `src/autoresearch/experiments/__init__.py`.
- Verification: `poetry run ruff check src/autoresearch/experiments/reward.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_reward.py`, `poetry run mypy src`, `poetry run pytest tests/unit/experiments/test_reward.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after import sorting.

### P-20260612-053 - Shadow module typing imports failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:50:57 +08:00
- Source: `poetry run ruff check src/autoresearch/experiments/shadow.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_shadow.py`.
- Symptom: Ruff reported `UP035` because `Callable` and `Mapping` were imported from `typing`.
- Impact: Task `28.1` focused lint verification was blocked.
- Evidence: Ruff required importing `Callable` and `Mapping` from `collections.abc`.
- Root cause: The new shadow module used older typing import style.
- Workaround: None needed after ruff autofix.
- Next action: None.
- Linked tasks: `28.1`
- Resolution: Ran ruff autofix on `src/autoresearch/experiments/shadow.py`.
- Verification: `poetry run ruff check src/autoresearch/experiments/shadow.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_shadow.py`, `poetry run mypy src`, `poetry run pytest tests/unit/experiments/test_shadow.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after import correction.

### P-20260612-052 - Replay export import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:42:57 +08:00
- Source: `poetry run ruff check src/autoresearch/experiments/replay.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_replay.py`.
- Symptom: Ruff reported `I001` in `src/autoresearch/experiments/__init__.py`.
- Impact: Task `27.1` focused lint verification was blocked.
- Evidence: Ruff reported the import block was unsorted or unformatted.
- Root cause: New replay exports were inserted without matching ruff/isort ordering.
- Workaround: None needed after ruff autofix.
- Next action: None.
- Linked tasks: `27.1`
- Resolution: Ran ruff autofix on `src/autoresearch/experiments/__init__.py`.
- Verification: `poetry run ruff check src/autoresearch/experiments/replay.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_replay.py`, `poetry run mypy src`, `poetry run pytest tests/unit/experiments/test_replay.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after import sorting.

### P-20260612-051 - Strategy schema import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:34:32 +08:00
- Source: `poetry run ruff check src/autoresearch/schemas/models.py src/autoresearch/schemas/__init__.py src/autoresearch/knowledge/versioning.py tests/unit/schemas/test_schema_models.py tests/unit/knowledge/test_strategy_cards.py tests/unit/knowledge/test_rollback.py`.
- Symptom: Ruff reported `I001` in `src/autoresearch/schemas/__init__.py` and `tests/unit/schemas/test_schema_models.py`.
- Impact: Task `26.1` focused lint verification was blocked.
- Evidence: Ruff reported both import blocks were unsorted or unformatted.
- Root cause: New exported strategy constants were inserted without matching ruff/isort ordering.
- Workaround: None needed after ruff autofix.
- Next action: None.
- Linked tasks: `26.1`
- Resolution: Ran ruff autofix on the affected import blocks.
- Verification: `poetry run ruff check src/autoresearch/schemas/models.py src/autoresearch/schemas/__init__.py src/autoresearch/knowledge/versioning.py tests/unit/schemas/test_schema_models.py tests/unit/knowledge/test_strategy_cards.py tests/unit/knowledge/test_rollback.py`, `poetry run mypy src`, `poetry run pytest tests/unit/schemas/test_schema_models.py tests/unit/knowledge/test_strategy_cards.py tests/unit/knowledge/test_rollback.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after import sorting.

### P-20260612-050 - Rollback version metadata needed explicit type conversion

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:21:24 +08:00
- Source: `poetry run mypy src`.
- Symptom: mypy reported `int(metadata["version"])` could receive `object`.
- Impact: Task `25.1` type verification was blocked.
- Evidence: mypy reported `src\autoresearch\knowledge\versioning.py:144: error: No overload variant of "int" matches argument type "object"`.
- Root cause: YAML metadata is typed as generic objects after parsing.
- Workaround: None needed after explicit string conversion.
- Next action: None.
- Linked tasks: `25.1`
- Resolution: Converted the parsed version with `int(str(metadata["version"]))`.
- Verification: `poetry run mypy src`, `poetry run pytest tests/unit/knowledge/test_rollback.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed.

### P-20260612-049 - Rollback foundations module had unused import

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:20:40 +08:00
- Source: `poetry run ruff check src/autoresearch/knowledge/versioning.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_rollback.py`.
- Symptom: Ruff reported unused `VersionSnapshot` in `src/autoresearch/knowledge/versioning.py`.
- Impact: Task `25.1` focused lint verification was blocked.
- Evidence: Ruff reported `F401`.
- Root cause: The implementation originally reused the naming pattern from `MarkdownKnowledgeStore` but did not need the existing `VersionSnapshot` type.
- Workaround: None needed after removing the import.
- Next action: None.
- Linked tasks: `25.1`
- Resolution: Removed the unused import.
- Verification: `poetry run ruff check src/autoresearch/knowledge/versioning.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_rollback.py`, `poetry run mypy src`, `poetry run pytest tests/unit/knowledge/test_rollback.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed.

### P-20260612-048 - Observability metrics export import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:11:44 +08:00
- Source: `poetry run ruff check src/autoresearch/observability/metrics.py src/autoresearch/observability/__init__.py tests/unit/observability/test_metrics.py`.
- Symptom: Ruff reported `I001` for `src/autoresearch/observability/__init__.py`.
- Impact: Task `24.1` focused lint verification was blocked.
- Evidence: Ruff reported the import block was unsorted or unformatted.
- Root cause: The metrics export was inserted without matching ruff/isort ordering.
- Workaround: None needed after autofix.
- Next action: None.
- Linked tasks: `24.1`
- Resolution: Ran ruff autofix on `src/autoresearch/observability/__init__.py`.
- Verification: `poetry run ruff check src/autoresearch/observability/metrics.py src/autoresearch/observability/__init__.py tests/unit/observability/test_metrics.py`, `poetry run mypy src`, `poetry run pytest tests/unit/observability/test_metrics.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after import sorting.

### P-20260612-047 - Skill property test basename caused pytest import mismatch

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 12:04:43 +08:00
- Source: `poetry run pytest tests/unit/knowledge/test_skills.py tests/property/knowledge/test_skills.py -vv`.
- Symptom: pytest reported an import file mismatch between `tests/unit/knowledge/test_skills.py` and `tests/property/knowledge/test_skills.py`.
- Impact: Task `23.2` focused test verification was blocked during collection.
- Evidence: pytest imported module `test_skills` from the unit test path while trying to collect the property test file with the same basename.
- Root cause: The property test file reused the same basename in a non-package test layout.
- Workaround: None needed after renaming the property test file.
- Next action: None.
- Linked tasks: `23.2`
- Resolution: Renamed the property test file to `tests/property/knowledge/test_skill_retrieval.py`.
- Verification: `poetry run pytest tests/unit/knowledge/test_skills.py tests/property/knowledge/test_skill_retrieval.py -vv`, `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after the property test rename.

### P-20260612-046 - Skill extraction helper had incorrect iterable type

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 11:58:02 +08:00
- Source: `poetry run mypy src`; `poetry run ruff check src/autoresearch/knowledge/skills.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_skills.py`.
- Symptom: mypy reported `_ordered_unique` as iterating over an `object`; ruff then required `Iterable` to be imported from `collections.abc`.
- Impact: Task `23.1` type verification was blocked while the implementation intent was otherwise clear.
- Evidence: mypy reported `src\autoresearch\knowledge\skills.py:265: error: "object" has no attribute "__iter__"`; ruff reported `UP035`.
- Root cause: The helper accepted any iterable, but its parameter annotation was written as `object`, then corrected with the older typing import location.
- Workaround: None needed after correcting the type annotation.
- Next action: None.
- Linked tasks: `23.1`
- Resolution: Changed `_ordered_unique` to accept `Iterable[object]` imported from `collections.abc`.
- Verification: `poetry run ruff check src/autoresearch/knowledge/skills.py src/autoresearch/knowledge/__init__.py tests/unit/knowledge/test_skills.py`, `poetry run mypy src`, `poetry run pytest tests/unit/knowledge/test_skills.py -vv`, `poetry run ruff check src tests`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after the type annotation repair.

### P-20260612-045 - Recurring failure exports caused syntax error

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 11:50:06 +08:00
- Source: `poetry run ruff check src/autoresearch/experiments/failures.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_failures.py`; `poetry run mypy src`; `poetry run pytest tests/unit/experiments/test_failures.py -vv`.
- Symptom: `src/autoresearch/experiments/__init__.py` had three `__all__` entries outside the list, causing `IndentationError`.
- Impact: Task `22.2` could not be imported or tested until package exports were repaired.
- Evidence: Ruff reported `E999 SyntaxError`; mypy reported `Unexpected indent`; pytest collection failed importing `autoresearch.experiments`.
- Root cause: Manual export patch inserted `RecurringFailurePattern`, `classify_failure_category`, and `update_recurring_failure_patterns` after the closing list bracket.
- Workaround: None needed after repairing the export list.
- Next action: None.
- Linked tasks: `22.2`
- Resolution: Moved the recurring failure exports inside `__all__`.
- Verification: `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after export repair.

### P-20260612-044 - Failure knowledge module had unused import

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 11:44:02 +08:00
- Source: `poetry run ruff check src/autoresearch/experiments/failures.py src/autoresearch/experiments/__init__.py tests/unit/experiments/test_failures.py`.
- Symptom: Ruff reported unused `typing.Any` in `src/autoresearch/experiments/failures.py`.
- Impact: Task `22.1` lint verification was blocked while mypy and focused unit tests passed.
- Evidence: Ruff reported `F401` for `typing.Any`.
- Root cause: The failure recorder implementation no longer needed `Any` after the function signatures were finalized.
- Workaround: None needed after removing the import.
- Next action: Re-run focused and full ruff checks.
- Linked tasks: `22.1`
- Resolution: Removed the unused import.
- Verification: `poetry run ruff check src tests` passed after removing the unused import.

### P-20260612-043 - Similarity API export order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 11:31:12 +08:00
- Source: `poetry run ruff check src/autoresearch/research/similarity.py src/autoresearch/research/approval.py src/autoresearch/research/__init__.py src/autoresearch/literature/__init__.py tests/unit/research/test_similarity.py tests/unit/research/test_approval.py tests/smoke/test_similarity_live.py`.
- Symptom: Ruff reported `I001` for `src/autoresearch/literature/__init__.py` after exporting the literature search protocol.
- Impact: Task `21.3` lint verification was blocked, while type checking and focused unit tests passed.
- Evidence: Ruff reported one fixable import-order error.
- Root cause: The newly exported `LiteratureSearchClient` was inserted out of ruff/isort order.
- Workaround: None needed after import sorting.
- Next action: Keep package exports sorted when adding new public APIs.
- Linked tasks: `21.3`
- Resolution: Ran ruff autofix on `src/autoresearch/literature/__init__.py`.
- Verification: `poetry run ruff check src tests` passed after the import-order fix.

### P-20260612-042 - Full ruff gate reported import ordering across existing tests

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 11:28:41 +08:00
- Source: `poetry run ruff check src tests`.
- Symptom: Ruff reported 32 `I001` import-order errors across existing test modules after dependency installation generated a lock file.
- Impact: Task `21.2` cannot be committed until the repository lint gate passes, but blindly rewriting many unrelated tests would create avoidable churn.
- Evidence: `poetry run ruff --version` reported `ruff 0.4.10`; `poetry run ruff check tests/unit/cli/test_main.py --diff` showed only import grouping/order changes in a pre-existing test file.
- Root cause: Ruff/isort was not told that `autoresearch` is the first-party package, so the locked lint environment grouped local imports with other third-party imports and flagged many existing tests.
- Workaround: None needed after configuration fix.
- Next action: Keep `autoresearch` declared as first-party when adding new package roots.
- Linked tasks: `21.2`
- Resolution: Added `[tool.ruff.lint.isort] known-first-party = ["autoresearch"]` and ran ruff autofix only on the two new live smoke test files.
- Verification: `poetry run ruff check src tests` passed.

### P-20260612-041 - CLI tests failed after dependency lock resolved Typer with Click 8.4

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 11:26:48 +08:00
- Source: `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents`.
- Symptom: Three CLI tests exited with code 2 after `poetry install --with dev` generated the current lock file.
- Impact: The daily literature refresh feature itself passed focused tests and live smoke tests, but the broader verification gate is blocked.
- Evidence: A direct `CliRunner` invocation of `init-demo --path <tmp>` returned `Got unexpected extra argument`; help rendering returned `TypeError("Parameter.make_metavar() missing 1 required positional argument: 'ctx'")`; local versions were `typer 0.12.5` and `click 8.4.1`.
- Root cause: Typer 0.12.5 is not compatible with Click 8.4 help rendering, and deferred annotations in the CLI left Typer with string annotations for option parameters.
- Workaround: None needed after dependency and annotation fix.
- Next action: Re-check CLI smoke tests if Typer or Click constraints are changed.
- Linked tasks: `21.2`
- Resolution: Constrained Click to `>=8.1,<8.2`, regenerated the lock file, installed dependencies, and removed deferred annotations from `src/autoresearch/cli/main.py` so Typer receives concrete runtime option types.
- Verification: `poetry run pytest tests/unit/cli/test_main.py -vv` passed; `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed with 202 tests passed and 2 live smoke tests skipped by default.

### P-20260612-040 - Live literature refresh changes failed ruff style checks

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 11:16:31 +08:00
- Source: `poetry run ruff check src/autoresearch/literature/clients.py src/autoresearch/literature/refresh.py src/autoresearch/literature/__init__.py tests/unit/literature/test_refresh.py tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py`.
- Symptom: Ruff reported import ordering in the new live smoke tests and `UP038` for an `isinstance()` tuple in `refresh.py`.
- Impact: Functional unit tests and mypy passed, but lint gate failed.
- Evidence: Ruff reported `I001` in `tests/smoke/test_literature_live.py` and `tests/smoke/test_literature_refresh_live.py`, plus `UP038` in `src/autoresearch/literature/refresh.py`.
- Root cause: Manual patches did not match the configured import order and pyupgrade style.
- Workaround: None needed after formatting and style fix.
- Next action: Re-run ruff after applying fixes.
- Linked tasks: `21.2`
- Resolution: Applied ruff import sorting and changed the `isinstance()` check to Python 3.10 union syntax.
- Verification: `poetry run ruff check src/autoresearch/literature/clients.py src/autoresearch/literature/refresh.py src/autoresearch/literature/__init__.py tests/unit/literature/test_refresh.py tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py` passed after the fix.

### P-20260612-039 - Live literature API tests exposed TLS and source reliability issues

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 11:06:15 +08:00
- Source: `$env:AUTORESEARCH_LIVE_LITERATURE='1'; poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py -vv`.
- Symptom: First live run failed before API parsing because Python `urllib` raised `SSL: CERTIFICATE_VERIFY_FAILED unable to get local issuer certificate`; after adding CA support, a later live run reached real services but hit ArXiv `429 Too Many Requests` and a source timeout.
- Impact: The mocked refresh pipeline tests passed, but task `21.2` could not be accepted under the live-call requirement until HTTPS verification and source-level failure handling worked against real APIs.
- Evidence: The first live run failed at `urllib.request.urlopen()`; `poetry run python -c "import certifi"` initially failed with `ModuleNotFoundError`; after installing dependencies, the next live run reported `HTTP Error 429: Too Many Requests` and `TimeoutError`.
- Root cause: The runtime lacked an explicit CA bundle for stdlib `urllib`, and the refresh pipeline treated a single source failure as a whole-run failure.
- Workaround: Do not disable TLS verification. Keep live tests opt-in, but run them for external-source tasks.
- Next action: Continue real live smoke checks for future external-source tasks; do not mark them complete from mocks alone.
- Linked tasks: `21.2`
- Resolution: Added explicit `certifi` dependency, made the urllib client verify HTTPS with `certifi.where()`, and changed refresh fetches to record per-source errors while continuing other sources.
- Verification: `$env:AUTORESEARCH_LIVE_LITERATURE='1'; poetry run pytest tests/smoke/test_literature_live.py tests/smoke/test_literature_refresh_live.py -vv` passed with real network calls after the fix.

### P-20260612-038 - Planning could be misread as local-vault-only discovery

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-12 10:57:58 +08:00
- Source: User clarified that project-start cross-checks need broad online search, not only daily local/vault analysis.
- Symptom: Recent task wording emphasized Obsidian gap analysis and daily refresh, but did not clearly state that project creation and candidate approval also require external online similarity and novelty checks.
- Impact: Future agents could incorrectly rely only on the local vault, missing duplicate or adjacent work and writing weak novelty summaries.
- Evidence: User asked whether the plan assumed all checking could be local and required online search summaries to be written into Obsidian without fabricated outcomes.
- Root cause: The planning distinction between Obsidian as memory substrate and online discovery as evidence acquisition was not explicit enough.
- Workaround: None needed after documentation and task updates.
- Next action: Implement task `21.2` and `21.3` with mocked network tests first, then optional live runs behind explicit flags.
- Linked tasks: `21.2`, `21.3`
- Resolution: Updated `tasks.md`, research plan, execution plan, and both README files to require project-start online similarity scans, scheduled online refresh, source-backed Obsidian summaries, and explicit unknown/pending markers for missing evidence.
- Verification: `rg` confirmed the online discovery, project-start similarity scan, source-backed Obsidian summary, and no-fabrication constraints are present in tasks, research plan, execution plan, README, `Problem.md`, and `Agent.md`; `git diff --check` passed with only existing Windows line-ending warnings.

### P-20260612-037 - Scheduler test imports were not sorted

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 10:52:25 +08:00
- Source: `poetry run ruff check src/autoresearch/scheduler.py src/autoresearch/observability/audit.py tests/unit/test_scheduler.py` while verifying task `21.1`.
- Symptom: Ruff reported `I001` in `tests/unit/test_scheduler.py`.
- Impact: Scheduler functionality tests passed, but the lint gate failed until imports were organized.
- Evidence: Ruff suggested organizing the import block in the new scheduler test module.
- Root cause: The new test file import order did not match the configured formatter.
- Workaround: None needed after applying ruff's import organizer.
- Next action: Re-run ruff after scheduler exports and task-status updates.
- Linked tasks: `21.1`
- Resolution: Ran ruff `--fix` on `tests/unit/test_scheduler.py`.
- Verification: `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after the fix.

### P-20260612-036 - AI-Researcher rename left user-facing old-name references

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 10:41:20 +08:00
- Source: Repository-wide `rg -n "AutoResearch System|autoresearch-system"` check before task `20.2`.
- Symptom: Planning headers, vault README, current project vault index, CLI help, package docstrings, and literature client User-Agent still used the old `AutoResearch System` or `autoresearch-system` label.
- Impact: New agents and users could see conflicting project names after the rename to `AI-Researcher`.
- Evidence: `rg` matched current user-facing files outside historical `Agent.md` entries.
- Root cause: The initial rename commit only checked README, Chinese README, `pyproject.toml`, and `tasks.md`.
- Workaround: None needed after this cleanup.
- Next action: Keep `autoresearch` as the Python package name unless a dedicated package migration is requested.
- Linked tasks: Project rename request
- Resolution: Updated user-facing project labels, CLI help text, vault README/index text, and User-Agent to `AI-Researcher` / `ai-researcher`.
- Verification: `rg -n "AutoResearch System" AutoResearch_System_Research_Plan.md AutoResearch_System_Execution_Plan.md autoresearch-vault src README.md README.zh-CN.md pyproject.toml .kiro/specs/auto-research-system/tasks.md` returned no matches.

### P-20260612-035 - Candidate lifecycle exports and tests had unsorted imports

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-12 10:37:00 +08:00
- Source: `poetry run ruff check src tests` while verifying task `20.1`.
- Symptom: Ruff reported `I001` in `src/autoresearch/research/__init__.py` and `tests/unit/research/test_candidates.py`.
- Impact: Focused candidate lifecycle tests and mypy passed, but the lint gate failed until imports were organized.
- Evidence: Ruff suggested organizing the new candidate lifecycle import blocks.
- Root cause: New exports and tests were patched in a non-isort order.
- Workaround: None needed after applying ruff's import organizer.
- Next action: Re-run ruff after adding aggregate exports and test imports.
- Linked tasks: `20.1`
- Resolution: Ran ruff `--fix` on the affected research modules.
- Verification: `poetry run ruff check src tests` passed after the fix.

### P-20260611-034 - Reproducibility package verification exposed import and enum typing issues

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 22:58:00 +08:00
- Source: `poetry run ruff check src tests` and `poetry run mypy src` while verifying task `19.1`.
- Symptom: Ruff reported unsorted imports in report modules, and mypy reported an `Any` return from `_role_dir()`.
- Impact: The focused reproducibility package test passed, but lint and type gates failed until imports and enum value typing were fixed.
- Evidence: Ruff reported `I001`; mypy reported `Returning Any from function declared to return "str"`.
- Root cause: New report exports were appended before import organization, and `Enum.value` needed an explicit `str()` cast for mypy.
- Workaround: None needed after the fix.
- Next action: Re-run ruff and mypy after adding new aggregate exports and enum-return helpers.
- Linked tasks: `19.1`
- Resolution: Ran ruff `--fix` on the affected modules and changed `_role_dir()` to return `str(role.value)`.
- Verification: `poetry run ruff check src tests` and `poetry run mypy src` passed after the fix.

### P-20260611-033 - Review test module name collided with an existing test

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 22:42:00 +08:00
- Source: `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` while verifying task `18.1`.
- Symptom: Pytest reported an import file mismatch for `tests/unit/reports/test_review.py`.
- Impact: The focused review tests passed, but the broader test suite could not collect all tests until the new report test filename was made unique.
- Evidence: Pytest had already imported `tests/unit/experiments/test_review.py` as module `test_review`.
- Root cause: Two test files in different folders shared the same basename under the current pytest import mode.
- Workaround: None needed after renaming the new file.
- Next action: Use domain-specific test module names when adding tests under folders that may share common labels.
- Linked tasks: `18.1`
- Resolution: Renamed the new report review tests to `tests/unit/reports/test_paper_review.py` and cleared test bytecode caches.
- Verification: `poetry run pytest tests/unit tests/property tests/smoke tests/integration/agents` passed after the rename.

### P-20260611-032 - Review simulator tests used avoidable dict comprehensions

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 22:33:00 +08:00
- Source: `poetry run ruff check src tests` while verifying task `18.1`.
- Symptom: Ruff reported `C420` in `tests/unit/reports/test_review.py`.
- Impact: Review simulator tests passed and mypy passed, but the lint gate failed until the duplicate dict comprehensions were simplified.
- Evidence: Ruff suggested replacing `{section: "content" for section in _sections()}` with `dict.fromkeys(...)`.
- Root cause: Test fixture setup used a verbose dict comprehension for constant values.
- Workaround: None needed after applying ruff's fix.
- Next action: Use `dict.fromkeys()` when every generated key has the same value.
- Linked tasks: `18.1`
- Resolution: Ran `poetry run ruff check tests/unit/reports/test_review.py --fix`.
- Verification: `poetry run ruff check src tests` passed after the fix.

### P-20260611-031 - Metric consistency validator imports were unsorted

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 22:05:00 +08:00
- Source: `poetry run ruff check src tests` while verifying task `16.3`.
- Symptom: Ruff reported `I001` in `src/autoresearch/reports/__init__.py` and `tests/unit/reports/test_lint.py`.
- Impact: The new validator code and tests passed, but the lint gate failed until imports were organized.
- Evidence: Ruff suggested organizing the import blocks after adding `assert_metric_consistency` and `lint_metric_consistency` exports.
- Root cause: New imports were appended in a non-isort order.
- Workaround: None needed after applying ruff's import organizer.
- Next action: Re-run ruff after touching aggregate exports and test imports.
- Linked tasks: `16.3`
- Resolution: Ran `poetry run ruff check src/autoresearch/reports/__init__.py tests/unit/reports/test_lint.py --fix`.
- Verification: `poetry run ruff check src tests` passed after the import fix.

### P-20260611-030 - Initial ablation planner patch had a stale context anchor

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 21:40:22 +08:00
- Source: `apply_patch` while implementing task `15.2`.
- Symptom: The first combined patch failed with `Failed to find expected lines in E:\AIResearch\src\autoresearch\experiments\planner.py`.
- Impact: No files were changed by the failed patch; implementation was delayed until the patch was split into smaller chunks with current file anchors.
- Evidence: The patch expected a whitespace variant near the end of `_task_from_hypothesis()` that did not exist in the current file.
- Root cause: The patch was composed against an imprecise local context anchor.
- Workaround: Re-read the current file and apply smaller patches around stable anchors.
- Next action: For larger patches in active files, inspect exact nearby lines before applying multi-hunk edits.
- Linked tasks: `15.2`
- Resolution: Reapplied the planner, export, and test updates in separate `apply_patch` calls.
- Verification: `poetry run pytest tests/unit/experiments/test_planner.py`, `poetry run ruff check src tests`, and `poetry run mypy src` passed after the split patches.

### P-20260611-029 - Figure metric parser captured a truncated metric name

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 21:28:46 +08:00
- Source: `poetry run pytest tests/unit/reports/test_lint.py tests/unit/reports/test_report_generator.py` while verifying task `14.3`.
- Symptom: The deliberate figure metric mismatch test produced a metric consistency issue for metric `y` instead of `accuracy`.
- Impact: The consistency checker still raised an issue, but the figure metric parser would have produced misleading diagnostics for figure captions or alt text.
- Evidence: Printing lint issues for `![accuracy=0.6](...)` showed `metric 'y' is missing from source metrics.json`.
- Root cause: The figure metric regex used a greedy prefix before the metric capture group, so it consumed most of `accuracy` and left only the final character.
- Workaround: None needed after the regex update.
- Next action: Keep figure metric parsing tests around any future caption syntax changes.
- Linked tasks: `14.3`
- Resolution: Changed the figure alt/caption prefix match to be non-greedy and added a test fixture figure file to avoid unrelated link noise.
- Verification: `poetry run pytest tests/unit/reports/test_lint.py tests/unit/reports/test_report_generator.py` passed after the regex update.

### P-20260611-028 - Report package aggregate import reintroduced an experiments circular import

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-11 21:28:46 +08:00
- Source: `poetry run pytest tests/unit/reports/test_lint.py tests/unit/reports/test_report_generator.py` while verifying task `14.3`.
- Symptom: Pytest collection failed with `ImportError: cannot import name 'ReportContext' from partially initialized module 'autoresearch.reports'`.
- Impact: Report lint tests could not collect when the `autoresearch.reports` aggregate package was imported before the experiments package had finished initializing.
- Evidence: Import chain was `reports.__init__ -> reports.generator -> experiments.validation -> experiments.__init__ -> demo_workflow -> reports`.
- Root cause: Runtime-only report generation imports pulled in the experiments aggregate package at module import time, recreating the circular import pattern previously seen in report/demo wiring.
- Workaround: None needed after moving runtime experiment imports out of module import time.
- Next action: Keep report modules from importing the experiments aggregate path at top level; use direct lazy imports or `TYPE_CHECKING` imports for annotations.
- Linked tasks: `14.3`
- Resolution: Made `ValidationReport` a `TYPE_CHECKING`-only import and moved `require_evidence_for_metrics` into `generate_markdown_report()`.
- Verification: Report tests collected and passed after the import-layer change.

### P-20260611-027 - Report coverage test import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 21:20:13 +08:00
- Source: `poetry run ruff check src tests` while verifying task `14.2`.
- Symptom: Ruff reported `I001` in `tests/unit/reports/test_report_generator.py`.
- Impact: The coverage enforcement tests and mypy passed, but lint failed until the standard-library imports were sorted.
- Evidence: Ruff suggested organizing imports at the top of `test_report_generator.py`.
- Root cause: `datetime` was left above `dataclasses.replace` after adding the new report coverage test.
- Workaround: None needed after sorting the imports.
- Next action: Re-run ruff after adding imports to established test files.
- Linked tasks: `14.2`
- Resolution: Moved `from dataclasses import replace` above the datetime import.
- Verification: `poetry run ruff check src tests` passed after the import-order update.

### P-20260611-026 - Evidence graph uniqueness helper used invariant dict type

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 21:14:41 +08:00
- Source: `poetry run mypy src` while verifying task `14.1`.
- Symptom: Mypy rejected calls to `_ensure_unique()` because `dict[str, ClaimNode]`, `dict[str, SourceNode]`, `dict[str, EvidenceArtifact]`, and `dict[str, EvidenceNode]` are not compatible with `dict[str, object]`.
- Impact: The evidence graph tests and ruff passed, but the type gate failed until the helper accepted a read-only covariant interface.
- Evidence: Mypy reported four `arg-type` errors in `src/autoresearch/evidence/graph.py`.
- Root cause: `_ensure_unique()` only checks key membership, but it was annotated as a mutable `dict[str, object]`; `dict` is invariant in its value type.
- Workaround: None needed after changing the helper parameter to `Mapping[str, object]`.
- Next action: Use `Mapping` for helper functions that only read from typed dictionaries.
- Linked tasks: `14.1`
- Resolution: Imported `Mapping` and changed `_ensure_unique()` to accept `Mapping[str, object]`.
- Verification: `poetry run mypy src` passed after the annotation update.

### P-20260611-025 - LangGraph workflow annotations failed lint and type gates

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 21:08:00 +08:00
- Source: `poetry run ruff check src tests` and `poetry run mypy src` while verifying task `13.3`.
- Symptom: Ruff reported `UP037` for a quoted return annotation in `workflow.py`; mypy rejected the LangGraph conditional-edge map because `dict[str, str]` is not compatible with LangGraph's `dict[Hashable, str]` expectation.
- Impact: The new workflow integration test passed, but the code quality gates failed until annotations matched the current tool expectations.
- Evidence: Ruff pointed at `ResearchWorkflowState.from_payload()` and mypy pointed at both `add_conditional_edges()` calls.
- Root cause: The first implementation used a stale quoted annotation and let mypy infer a narrower route-target dictionary type than LangGraph's API accepts.
- Workaround: None needed after the annotation update.
- Next action: Keep dynamic LangGraph edge maps explicitly annotated when routing keys are passed through the framework API.
- Linked tasks: `13.3`
- Resolution: Removed the quoted return annotation and annotated the route-target map as `dict[Hashable, str]`, including the local `targets` variable.
- Verification: `poetry run ruff check src tests` and `poetry run mypy src` passed after the update.

### P-20260611-024 - LangGraph dependency was declared but missing from active verification paths

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-11 21:08:00 +08:00
- Source: Dependency and test setup while starting task `13.3`.
- Symptom: `poetry run python -c "import langgraph"` failed with `ModuleNotFoundError`; the initial dependency search also referenced a missing `poetry.lock`; `poetry run pip install "langgraph>=0.2,<0.3"` and `poetry run python -m pip install "langgraph>=0.2,<0.3"` both failed with `The system cannot find the file specified`; the first `poetry run pytest tests/integration/agents/test_workflow.py` used the global pytest script and could not import LangGraph.
- Impact: Task `13.3` could not be implemented or verified until LangGraph was available on the same interpreter path used by the project test command.
- Evidence: `poetry run where python` pointed at the Poetry virtualenv, while `poetry run where pytest` pointed at the global Python 3.13 scripts directory; `poetry run python -m pytest ...` failed because the Poetry virtualenv did not have pytest installed.
- Root cause: The dependency was declared in `pyproject.toml` but not installed in the active environments; Poetry resolved `python` and `pytest` to different interpreter paths because the Poetry virtualenv lacked dev tool scripts.
- Workaround: Use the virtualenv Python directly for environment installs, and keep using the repository's established `poetry run pytest` command once the global verification interpreter has the declared dependency.
- Next action: In a later environment-hardening task, normalize Poetry dev dependency installation so `poetry run python -m pytest` and `poetry run pytest` use the same environment.
- Linked tasks: `13.3`
- Resolution: Installed `langgraph>=0.2,<0.3` into the Poetry virtualenv via the venv `python.exe -m pip install` and into the current global test interpreter via `python -m pip install`.
- Verification: `poetry run python -c "from langgraph.graph import StateGraph, END; print('langgraph graph ok')"` passed; `poetry run pytest tests/integration/agents/test_workflow.py` passed after the dependency was available to the test interpreter.

### P-20260611-023 - AgentRegistry list method shadowed built-in list type for mypy

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 20:53:23 +08:00
- Source: `poetry run mypy src` while verifying task `13.1`.
- Symptom: Mypy reported `Function "autoresearch.agents.registry.AgentRegistry.list" is not valid as a type` for annotations inside `AgentRegistry`.
- Impact: Agent registry property tests and ruff passed, but the type gate failed until the annotations avoided the method-name shadowing.
- Evidence: Mypy pointed to return annotations using `list[BaseAgent]` in the same class that defines a method named `list`.
- Root cause: In class scope, the `list` method name shadowed the built-in `list` generic during mypy analysis.
- Workaround: None needed after introducing a module-level type alias.
- Next action: Use module-level aliases when a required method name shadows a built-in generic in annotations.
- Linked tasks: `13.1`
- Resolution: Added `AgentList: TypeAlias = list[BaseAgent]` outside the class and used it for registry list/query return annotations.
- Verification: `poetry run mypy src` passed after the annotation update.

### P-20260611-022 - PowerShell rejected Select-Object range syntax

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 20:46:32 +08:00
- Source: Local command execution while inspecting `src/autoresearch/experiments/acceptance.py` during task `12.4`.
- Symptom: `Get-Content ... | Select-Object -Index 180..230` failed because PowerShell could not convert the string `180..230` to `System.Int32`.
- Impact: No source files or verification results were affected; the command was only for inspection.
- Evidence: PowerShell returned `Cannot bind parameter 'Index'. Cannot convert value "180..230" to type "System.Int32"`.
- Root cause: The active PowerShell syntax requires expanding the range before indexing, such as `$lines[180..230]`.
- Workaround: Use `$lines = Get-Content ...; $lines[180..230]`.
- Next action: Keep using PowerShell-native range syntax for file snippet inspection.
- Linked tasks: `12.4`
- Resolution: Re-ran the inspection with `$lines = Get-Content ...; $lines[180..230]`.
- Verification: The corrected PowerShell command printed the intended file snippet.

### P-20260611-021 - Acceptance payload annotations failed mypy

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 20:46:32 +08:00
- Source: `poetry run mypy src` while verifying task `12.4`.
- Symptom: Mypy reported `No overload variant of "list" matches argument type "object"` and said `object` was not iterable in `src/autoresearch/experiments/acceptance.py`.
- Impact: Acceptance tests and ruff passed, but the type gate failed until nested report payload annotations were made explicit.
- Evidence: Mypy pointed to `_rate(values: object)` and iteration over `payload["results"]`.
- Root cause: The acceptance helper used `dict[str, object]` and `object` annotations around nested payload data that the code then iterated.
- Workaround: None needed after tightening the annotations.
- Next action: Prefer `Iterable[...]` and `dict[str, Any]` for intentionally heterogeneous report payloads.
- Linked tasks: `12.4`
- Resolution: Changed `_rate()` to accept `Iterable[object]` and changed report payload/Markdown helper annotations to `dict[str, Any]`.
- Verification: `poetry run mypy src` passed after the annotation update.

### P-20260611-020 - Demo workflow introduced circular import and type-check issues

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-11 20:36:51 +08:00
- Source: `poetry run pytest tests/unit/cli/test_main.py tests/unit/experiments/test_demos.py`, `poetry run ruff check src tests`, and `poetry run mypy src` while verifying task `12.3`.
- Symptom: Pytest collection failed with a circular import between `autoresearch.experiments` and `autoresearch.reports`; ruff reported import ordering in `src/autoresearch/experiments/__init__.py`; mypy rejected passing `list[str]` to `expected_artifacts: list[Path | str]`.
- Impact: The new end-to-end demo command could not be accepted until import layering, formatting, and type checks were fixed.
- Evidence: Pytest reported `ImportError: cannot import name 'ValidationReport' from partially initialized module 'autoresearch.experiments'`; ruff reported `I001`; mypy reported `Argument "expected_artifacts" ... incompatible type "list[str]"`.
- Root cause: `reports/generator.py` imported validation helpers from the aggregate `autoresearch.experiments` package while `demo_workflow` imported reports and was exported from that same aggregate package; the new export also needed sorted import order, and the helper return type was too narrow for mypy.
- Workaround: None needed after the direct submodule imports and type annotation update.
- Next action: Keep workflow modules importing direct submodules when aggregate package exports would create cycles.
- Linked tasks: `12.3`
- Resolution: Changed `reports/generator.py` to import `ValidationReport` and `require_evidence_for_metrics` from direct submodules, sorted `experiments/__init__.py`, and changed `_expected_artifacts()` to return `list[Path | str]`.
- Verification: `poetry run pytest tests/unit/cli/test_main.py tests/unit/experiments/test_demos.py`, `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests/unit tests/property tests/smoke` all passed after the fix.

### P-20260611-019 - Ruff import-order check failed after exporting tabular demo

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 20:18:19 +08:00
- Source: `poetry run ruff check src tests` while verifying task `12.1`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/experiments/__init__.py`.
- Impact: The new tabular demo tests and mypy passed, but the lint gate failed until the new export import matched ruff/isort ordering.
- Evidence: Ruff showed a one-line diff moving the `.demos` import before `.evidence`.
- Root cause: The new demo exports were inserted manually below `.evidence` imports instead of in sorted module order.
- Workaround: None needed after the import-order fix.
- Next action: Re-run full pytest, ruff, and mypy before marking future demo tasks complete.
- Linked tasks: `12.1`
- Resolution: Moved the `.demos` import above `.evidence` in `src/autoresearch/experiments/__init__.py`.
- Verification: `poetry run ruff check src tests` passed after the fix; `poetry run pytest tests/unit tests/property tests/smoke` passed with 144 tests and 1 skipped.

### P-20260611-018 - Ruff import-order check failed after adding report lint

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 20:07:36 +08:00
- Source: `poetry run ruff check src tests` while verifying task `11.2`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/reports/lint.py`.
- Impact: Report lint tests, full pytest, and mypy passed, but the lint gate failed until formatting matched the repository import rules.
- Evidence: Ruff reported one fixable import-format error and showed a diff deleting an extra blank line after the imports.
- Root cause: The new lint module was manually written with one extra blank line between imports and the module constant.
- Workaround: None needed after the formatting fix.
- Next action: Continue using full ruff verification before marking future report tasks complete.
- Linked tasks: `11.2`
- Resolution: Removed the extra blank line after the import block in `src/autoresearch/reports/lint.py`.
- Verification: `poetry run ruff check src tests` passed after the fix; `poetry run pytest tests/unit tests/property tests/smoke` also passed with 142 tests and 1 skipped.

### P-20260611-017 - Pytest report test basename collided with experiment generator test

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 19:59:00 +08:00
- Source: `poetry run pytest tests/unit tests/property tests/smoke` while verifying task `11.1`.
- Symptom: Pytest reported an import file mismatch between `tests/unit/experiments/test_generator.py` and `tests/unit/reports/test_generator.py`.
- Impact: The report tests passed in isolation, but full test collection failed until the report test file had a unique basename.
- Evidence: Pytest said imported module `test_generator` pointed to the experiment generator test while collecting the report generator test.
- Root cause: Two test files in different directories shared the same basename, and pytest imported them as the same top-level module.
- Workaround: None needed after renaming the report test file.
- Next action: Keep future test filenames unique across the repository unless tests are packaged.
- Linked tasks: `11.1`
- Resolution: Renamed `tests/unit/reports/test_generator.py` to `tests/unit/reports/test_report_generator.py` and cleared test `__pycache__`.
- Verification: `poetry run pytest tests/unit tests/property tests/smoke` passed after the rename.

### P-20260611-016 - Ruff import-order check failed after exporting result collector

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 19:47:00 +08:00
- Source: `poetry run ruff check src tests` while verifying task `10.1`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/experiments/__init__.py`.
- Impact: Result collector tests and mypy passed, but the lint gate failed until the package export imports were normalized.
- Evidence: Ruff reported one fixable import-order error after adding result collector exports.
- Root cause: The new `results` export was inserted manually without matching ruff/isort's expected import order.
- Workaround: None needed after applying ruff's fix.
- Next action: Re-run full pytest, ruff, and mypy before marking task `10.1` complete.
- Linked tasks: `10.1`
- Resolution: Ran `poetry run ruff check --fix src\autoresearch\experiments\__init__.py`.
- Verification: `poetry run ruff check src tests` passed after the fix.

### P-20260611-015 - Ruff import-order check failed after adding network policy

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 19:42:00 +08:00
- Source: `poetry run ruff check src tests` while verifying task `9.3`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/experiments/network.py`.
- Impact: Tests and mypy passed, but the lint gate failed until imports were normalized.
- Evidence: Ruff reported one fixable import-order error in the new network policy module.
- Root cause: The manually added import block did not match ruff/isort's expected layout.
- Workaround: None needed after applying ruff's fix.
- Next action: Re-run full pytest, ruff, and mypy before marking task `9.3` complete.
- Linked tasks: `9.3`
- Resolution: Ran `poetry run ruff check --fix src\autoresearch\experiments\network.py`.
- Verification: `poetry run ruff check src tests` passed after the fix.

### P-20260611-014 - OS-level network sandbox enforcement is not implemented

- Status: Mitigated
- Severity: Medium
- Discovered: 2026-06-11 19:41:00 +08:00
- Source: Task `9.3` implementation of restricted network policy placeholder.
- Symptom: The MVP can preflight and audit network requests routed through `RestrictedNetworkPolicy`, but it does not install OS-level firewall, proxy, or socket interception rules for arbitrary generated code.
- Impact: Generated experiment code that bypasses the policy helper could still attempt network access until a later sandbox layer enforces network restrictions at the process or OS boundary.
- Evidence: `network_enforcement_note()` documents that MVP network policy is preflight/audit only; blocked-request tests verify audit logging only for calls routed through the policy.
- Root cause: Full network sandboxing requires an OS firewall, proxy, container, or process-level interception layer beyond the current MVP local subprocess executor.
- Workaround: Run generated code review before execution, route approved network operations through `RestrictedNetworkPolicy.require_allowed()`, and audit blocked requests with `AuditEventType.SANDBOX_DENIAL`.
- Next action: Later sandbox hardening should add OS/container/proxy enforcement and prove that arbitrary network calls to non-allowed domains are blocked.
- Linked tasks: `9.3`, `16.3`
- Resolution: Not fully resolved; MVP mitigation is documented and covered by tests.
- Verification: `poetry run pytest tests/unit/experiments/test_network.py tests/unit/observability/test_audit.py` passed with 18 tests.

### P-20260611-013 - Mypy rejected Unix-only runtime limit APIs on Windows

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 19:34:00 +08:00
- Source: `poetry run mypy src` while verifying task `9.2`.
- Symptom: Mypy reported missing attributes for `resource.setrlimit`, `resource.RLIMIT_CPU`, `resource.RLIMIT_AS`, `os.killpg`, and `signal.SIGKILL` in `src/autoresearch/experiments/executor.py`.
- Impact: Runtime tests passed, but the cross-platform type gate failed on Windows before task `9.2` could be marked complete.
- Evidence: Mypy returned 7 attr-defined errors for Unix-only process and resource-limit APIs.
- Root cause: The executor used Unix APIs inside runtime platform branches, but mypy still checked those attributes in the Windows environment.
- Workaround: None needed after the platform-safe attribute lookup change.
- Next action: Re-run full pytest, ruff, and mypy before marking task `9.2` complete.
- Linked tasks: `9.2`
- Resolution: Replaced direct Unix-only attribute access with `getattr`-based platform branches for resource limits, process groups, and kill signals.
- Verification: `poetry run mypy src` passed with no issues in 31 source files after the fix; executor tests also passed.

### P-20260611-012 - Candidate generator split equivalent dataset phrases

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 19:07:15 +08:00
- Source: `poetry run pytest tests/unit/research tests/smoke tests/unit` and `poetry run ruff check src tests` while verifying task `7.1`.
- Symptom: The deterministic candidate ranking test produced separate clusters for `autoresearch` and `the autoresearch`; ruff also required import ordering in the new candidate module.
- Impact: Equivalent benchmark phrases could split evidence across multiple lower-confidence candidates.
- Evidence: Pytest showed an unexpected cluster key `transformer|limited reproducibility|the autoresearch`; ruff reported one fixable import-order issue.
- Root cause: Dataset phrase extraction did not strip nested preposition phrases and leading articles after matching `with ... benchmark` text.
- Workaround: None needed after normalization fix.
- Next action: Keep deterministic tests around sample candidate ranking as candidate generation evolves.
- Linked tasks: `7.1`
- Resolution: Normalized dataset phrases by taking the trailing `on ...` segment and removing leading `the `; ran ruff auto-fix for imports.
- Verification: `poetry run pytest tests/unit/research tests/smoke tests/unit` passed with 79 tests and 1 skipped optional live smoke test; `poetry run ruff check src tests` passed.

### P-20260611-011 - Ruff import-order check failed after adding literature storage

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-11 19:02:06 +08:00
- Source: `poetry run ruff check src tests` while verifying task `6.4`.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/literature/storage.py`.
- Impact: Integration tests and mypy passed, but the quality gate required import formatting.
- Evidence: Ruff reported one fixable `I001` finding.
- Root cause: The new storage module import block did not match ruff/isort ordering.
- Workaround: None needed after applying ruff's automatic fix.
- Next action: Continue to run `ruff` before marking code tasks complete.
- Linked tasks: `6.4`
- Resolution: Ran `poetry run ruff check src tests --fix`.
- Verification: `poetry run ruff check src tests` passed after the fix.

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
