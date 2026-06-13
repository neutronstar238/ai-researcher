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

### P-20260613-041 - Publication stability gate initially read a stale paper-build path from the cycle summary

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 20:37:00 +08:00
- Source: Task `105.1` real `publication-stability` run over `runs/manual-live/task104-similarity-classification/cycle-summary.json`.
- Symptom: The first stability matrix run reported `paper_quality_all_releases=fail` even though the task `104.1` evidence gate released against the corrected task `103.1` paper build with `paper_quality.passed=true`.
- Impact: A stability gate could misclassify paper quality when a cycle summary retained older inline `paper_build.json_path` fields while the evidence gate correctly referenced the artifact used for release.
- Evidence: `runs/manual-live/task104-similarity-classification/cycle-summary.json` still contained the old task `101.1` paper-build path, while `runs/manual-live/task104-similarity-classification/evidence-gate/evidence-gate.json` recorded `paper_build_path=runs/manual-live/task103-manuscript-quality/paper-build/paper-build.json`.
- Root cause: The initial stability auditor loaded `cycle_summary.paper_build.json_path` before considering the artifact path recorded by the evidence gate.
- Workaround: None needed after the fix; the auditor now prefers the evidence-gate-reviewed paper-build artifact when present.
- Next action: Keep release/stability gates anchored to the artifact paths used by upstream gates, not duplicated inline summaries.
- Linked tasks: `105.1`
- Resolution: Added evidence-gate artifact-path precedence for paper build loading and a regression test with a stale summary paper-build path.
- Verification: Focused stability tests passed with 4 report tests; real rerun wrote `runs/manual-live/task105-stability-matrix/publication-stability.json` with `paper_quality_passed=true`, `paper_quality_all_releases=pass`, `verdict=blocked`, and `score=0.500`.

### P-20260613-040 - Single-cycle release pass does not prove stable cross-topic publication output

- Status: Mitigated
- Severity: High
- Discovered: 2026-06-13 19:45:00 +08:00
- Source: Task `104.1` real CCF-B publication-audit and evidence-gate rerun over the task `101.1` Pendigits cycle.
- Symptom: One real Pendigits cycle can now pass publication audit and the physical evidence gate after similarity classification, optional-source policy, and manuscript generation fixes, but this does not yet prove stable CCF-B/Q3-level output across topics, datasets, templates, or multiple autonomous cycles.
- Impact: The system could overstate general readiness if a single benchmark success is treated as a stable publication pipeline. Task `105.1` now blocks that claim, but the underlying cross-topic stability evidence is still missing.
- Evidence: `runs/manual-live/task104-similarity-classification/publication-audit/publication-audit.json` passed with score `0.9615` and `runs/manual-live/task104-similarity-classification/evidence-gate/evidence-gate.json` passed with `release_allowed=true`; `runs/manual-live/task105-stability-matrix/publication-stability.json` correctly blocked stable CCF-B/Q3 claims because the matrix has 1 cycle, 1 release-allowed cycle, 1 distinct real dataset, and 1 LaTeX template.
- Root cause: Current evidence covers one controlled Pendigits method-candidate cycle and a generic LaTeX template build, not a statistically meaningful portfolio of cycles, datasets, or venue templates.
- Workaround: Run `airesearcher publication-stability ... --target ccf-b-matrix` before any stable-output claim; it now fails closed when the matrix is too small.
- Next action: Run a multi-cycle benchmark matrix with at least two additional public datasets/tasks, source diversity checks, related-work positioning checks, and venue-template compatibility before claiming stable CCF-B/Q3 generation.
- Linked tasks: `104.1`, `105.1`
- Resolution: Mitigated by task `105.1`, not resolved. Stable output still requires additional real cycles and template diversity.
- Verification: `poetry run airesearcher publication-stability runs\manual-live\task104-similarity-classification\cycle-summary.json --target ccf-b-matrix --output-dir runs\manual-live\task105-stability-matrix --vault runs\manual-live\task105-stability-vault --project-id task105_stability_matrix --no-fail-on-unstable` returned `verdict=blocked`, `stable=false`, and `score=0.500`.

### P-20260613-039 - Similarity classifier overclassified broad method-family word matches during breadth repair

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 19:35:00 +08:00
- Source: Live task `104.1` similarity classification rerun over the task `101.1` Pendigits candidate.
- Symptom: An initial query-backed method-family classifier improved classified breadth but incorrectly counted broad word matches such as crystallographic prototypes, centroid bodies, portfolio variance shrinkage, and generic Gaussian/variance papers as adjacent or supporting prior work.
- Impact: Publication audit could pass `similarity_classified_finding_breadth` using weakly related evidence, weakening the novelty and CCF-B/Q3 quality bar.
- Evidence: The first task `104.1` live similarity-check over `runs/manual-live/task101-full-cycle/cycle-20260613T091517Z/candidate.json` classified 30/57 findings, including visibly unrelated prototype/centroid/variance titles. After tightening method-family context and method-anchor token overlap, the final run classified 18/57 findings concentrated in prototype/centroid, Mahalanobis metric, clustering/prototype classification, and pattern-analysis work.
- Root cause: The first method-family rules allowed broad `prototype`, `centroid`, `gaussian`, `variance`, and `shrinkage` matches without requiring classification, recognition, learning, metric, or method-anchor evidence in the source metadata.
- Workaround: None needed after tightening the classifier.
- Next action: Keep adding negative fixtures whenever real live search reveals another false adjacent-work class.
- Linked tasks: `104.1`
- Resolution: Added query-aware method-family matching with required classification/recognition/learning/metric context, removed broad Gaussian/variance-shrinkage families, and required core method anchors for conservative token-overlap classification.
- Verification: `poetry run pytest tests\unit\research\test_similarity.py -q` passed 11 tests, including weak-overlap and variance-shrinkage unknown regressions. Final real similarity-check wrote `runs/manual-live/task104d-similarity-vault/exploration/topics/similarity_check_autopilot_task101_full_cycle_20260613091517.md` with 57 findings, 18 non-unknown classifications, and no broad prototype/centroid/Gaussian/variance false positives observed in the sampled classified list.

### P-20260613-038 - Autopilot paper build used the thin experiment report instead of an evidence-bound manuscript

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 19:05:00 +08:00
- Source: Follow-up to task `101.1` and the user's review that the generated LaTeX paper had too few pages, insufficient technical detail, and layout issues.
- Symptom: The autonomous cycle built LaTeX directly from the demo experiment report. That report contained useful run evidence, but it was not a full paper manuscript and produced a thin PDF that failed publication-level paper-quality checks.
- Impact: A real cycle could have all experiment artifacts present while still producing a paper artifact that was far below CCF-B/Q3 writing and technical-depth expectations.
- Evidence: The task `101.1` paper build produced 3 pages / 314 words with layout warnings. The task `103.1` rerun over the same cycle evidence produced `runs/manual-live/task103-manuscript-quality/paper-manuscript/manuscript.md` with 2856 words and a compiled 9-page PDF with 0 overfull hbox warnings.
- Root cause: `autopilot` passed `demo.report_path` directly to `build_latex_paper_from_markdown`; publication audit also inspected that demo report instead of a dedicated paper-level manuscript.
- Workaround: Before this fix, operators could manually write a longer Markdown file and pass it to `paper-build`, but that bypassed the autonomous evidence-bound cycle.
- Next action: Improve similarity classification breadth and richer novelty positioning; do not treat the now-compilable manuscript as publication-ready while publication audit remains blocked.
- Linked tasks: `103.1`
- Resolution: Added `compose_publication_manuscript(...)`, wired `autopilot`/`serve` to write `paper-manuscript/manuscript.md` before audit/build, and made publication audit prefer `cycle_summary.paper_manuscript.markdown_path`.
- Verification: Focused manuscript/publication-audit/autopilot tests passed with 14 tests. Focused ruff and mypy passed. Real manuscript compose from task `101.1` evidence produced 2856 words with Method 561 words and Related Work 635 words. Real `paper-build` compiled a 9-page PDF with `paper_quality.passed=true`, words `2856/2500`, pages `9/6`, and `overfull_hbox=0/0`. Real `publication-audit` scored `0.9062` but correctly stayed `fail` because `similarity_classified_finding_breadth=1/10`. Real `evidence-gate` passed `paper_quality_gate` and blocked release on `publication_release_gate`.

### P-20260613-037 - Semantic Scholar was treated as a required default source despite 429-prone access

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 18:35:00 +08:00
- Source: User requested README optimization and asked to lower Semantic Scholar priority because HTTP 429s are common; default retrieval should prefer free APIs first.
- Symptom: Default literature refresh, similarity checks, autopilot source clients, and publication-audit source-error gates treated Semantic Scholar like a required source. A Semantic Scholar 429 could therefore appear as a high-severity source failure even when ArXiv/OpenAlex core coverage was sufficient.
- Impact: The system could over-block otherwise useful cycles on an optional metadata source and make README/deployment guidance imply Semantic Scholar is required.
- Evidence: `src/autoresearch/literature/refresh.py`, `src/autoresearch/research/similarity.py`, and `src/autoresearch/cli/main.py` created Semantic Scholar clients by default; `publication_audit.py` marked every source error as `FAIL`.
- Root cause: Earlier source-breadth work added OpenAlex as fallback but did not demote Semantic Scholar from default required coverage after repeated 429 evidence.
- Workaround: Before this fix, operators could avoid Semantic Scholar only by passing custom source clients in code paths that exposed that hook.
- Next action: Continue adding more stable public metadata sources and keep optional-source warnings separate from core source-breadth blockers.
- Linked tasks: `102.1`
- Resolution: Default source clients now use ArXiv and OpenAlex; Semantic Scholar is included only when `AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR=1` or `SEMANTIC_SCHOLAR_API_KEY` is present. Optional Semantic Scholar source errors are publication-audit warnings when core source breadth passes, and source preflight records optional degradation without blocking the cycle.
- Verification: Focused literature/similarity/publication-audit/CLI tests passed with 66 tests; full `poetry run ruff check src tests`, `poetry run mypy src`, and `poetry run pytest tests\smoke tests\unit -q` passed with 420 passed and 4 skipped. Real `literature-refresh` with Semantic Scholar env cleared fetched ArXiv/OpenAlex only and wrote 2 documents; real `similarity-check` with Semantic Scholar env cleared fetched ArXiv/OpenAlex only and wrote 2 findings.

### P-20260613-036 - Real task101 full cycle is functional but not directly publishable

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 17:25:00 +08:00
- Source: Task `101.1` real full-cycle and self-evolution acceptance audit.
- Symptom: `airesearcher serve --once` completed a real end-to-end cycle with source preflight, online search, UCI Pendigits execution, live LLM review, reproduction rerun, paper build, and evidence gate, but publication audit failed and evidence gate blocked release.
- Impact: The system can run the autonomous loop and self-evolution support path, but the current research output must not be claimed as CCF-B/Q3 publication-ready or directly publishable.
- Evidence: `runs/manual-live/task101-full-cycle/cycle-20260613T091517Z/cycle-summary.json` recorded `source_preflight=pass`, `review_status=passed`, `publication_audit=fail`, `evidence_gate=blocked`; `publication-audit.json` scored `0.8485` but failed source-error and similarity-classification gates; `paper-build.json` recorded `compiled_with_quality_issues`. Tasks `102.1`, `103.1`, and `104.1` resolved those blockers for this cycle: optional Semantic Scholar failures are warnings, the manuscript compiles to 9 pages / 2856 words with `paper_quality.passed=true`, and the final task `104.1` similarity-check classified 18/57 source-backed findings.
- Root cause: The original failure combined three blockers: Semantic Scholar 429/circuit-breaker errors, insufficient evidence-classified similar-work breadth, and a thin 3-page / 314-word PDF. Tasks `102.1`, `103.1`, and `104.1` resolved these blockers for the task `101.1` Pendigits cycle.
- Workaround: The generated issue notes and scheduler follow-up tasks preserve the blockers for another cycle; the self-evolution candidate remains in shadow evaluation.
- Next action: Treat this as one cycle's release-gate pass; continue with `P-20260613-040` before making a stable cross-topic publication-readiness claim.
- Linked tasks: `101.1`, `102.1`, `103.1`, `104.1`
- Resolution: Resolved for the task `101.1` Pendigits cycle. The updated cycle summary at `runs/manual-live/task104-similarity-classification/cycle-summary.json` passes CCF-B publication audit and the physical evidence gate, while leaving broader stability tracked separately.
- Verification: `poetry run airesearcher publication-audit runs\manual-live\task104-similarity-classification\cycle-summary.json --target ccf-b --output-dir runs\manual-live\task104-similarity-classification\publication-audit --vault runs\manual-live\task104d-similarity-vault --project-id task104_similarity_classification --no-fail-on-not-publishable` passed with score `0.9615`, `publishable=true`, and `similarity_classified_finding_breadth=18/10`. `poetry run airesearcher evidence-gate runs\manual-live\task104-similarity-classification\cycle-summary.json --output-dir runs\manual-live\task104-similarity-classification\evidence-gate --publication-audit runs\manual-live\task104-similarity-classification\publication-audit\publication-audit.json --paper-build-json runs\manual-live\task103-manuscript-quality\paper-build\paper-build.json --vault runs\manual-live\task104d-similarity-vault --project-id task104_similarity_classification --no-fail-on-blocked` passed with `release_allowed=true` and 0 failed checks.

### P-20260613-035 - Springer template dependency recovery needed template-specific amsmath preamble

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 17:01:00 +08:00
- Source: Task `100.1` live Springer Nature LaTeX template compatibility verification.
- Symptom: After `sn-jnl.cls` was downloaded from the official Springer Nature archive, `pdflatex` still failed with `Undefined control sequence` at `\allowdisplaybreaks` during `\begin{document}`.
- Impact: The dependency recovery layer was working, but the Springer smoke manuscript could not prove end-to-end template compatibility until the template-specific preamble loaded the expected math package.
- Evidence: `runs/manual-live/task100-latex-dependency/springer-nature-sn-jnl/compile.log` showed the undefined `\allowdisplaybreaks` error while `dependency_status=downloaded`.
- Root cause: The official `sn-jnl.cls` class uses `\allowdisplaybreaks`, which requires `amsmath`; the generated smoke document did not load it.
- Workaround: None needed after the template registry fix.
- Next action: Keep venue/publisher template specs allowed to carry minimal template-specific preamble lines, and verify each real template with a live compile rather than assuming generic smoke manuscripts are enough.
- Linked tasks: `100.1`
- Resolution: Added `\usepackage{amsmath}` to the Springer Nature template spec while still avoiding vendoring the upstream template file.
- Verification: `runs/manual-live/task100-latex-dependency-rerun/latex-template-compatibility.json` recorded `source_http=200`, `dependency_status=downloaded`, `status=compiled`, and a PDF at `runs/manual-live/task100-latex-dependency-rerun/springer-nature-sn-jnl/main.pdf`.

### P-20260613-034 - Inspiration focused gate initially failed on Python 3.10 import and brittle test assertion

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 14:10:00 +08:00
- Source: Focused verification for task `99.1`.
- Symptom: `poetry run pytest tests\unit\test_inspiration.py tests\unit\cli\test_main.py tests\unit\compliance\test_licenses.py -q` first failed during collection because `Protocol` was imported from `collections.abc`, then failed once more because the autopilot unit test expected an exact candidate query string that did not match the generated candidate title.
- Impact: The new inspiration module and autopilot wiring could not be marked complete until Python 3.10 import compatibility and the unit-test contract were fixed.
- Evidence: Pytest reported `ImportError: cannot import name 'Protocol' from 'collections.abc'`; mypy reported `Module "collections.abc" has no attribute "Protocol"`; the autopilot test reported an assertion mismatch over the generated inspiration query tuple.
- Root cause: `Protocol` belongs in `typing` for this supported Python version, and the first autopilot test assertion coupled to an exact string instead of the core generated research-topic phrase.
- Workaround: None needed after the code and test fixes.
- Next action: Keep Python 3.10 compatibility checks in focused tests and prefer robust contract assertions for generated prompts/queries.
- Linked tasks: `99.1`
- Resolution: Moved `Protocol` to `typing`, tightened the default client typing, used test parameters explicitly, and changed the autopilot test to assert that at least one inspiration query contains the core generated research-topic phrase.
- Verification: Focused inspiration/CLI/compliance tests passed with 46 tests; targeted ruff and mypy passed; full `poetry run pytest tests\smoke tests\unit -q` passed with 413 passed and 4 skipped.

### P-20260613-033 - Local shell lacks `gh` for CI polling

- Status: Mitigated
- Severity: Low
- Discovered: 2026-06-13 13:56:00 +08:00
- Source: CI verification after pushing task `97.1` and before task `98.1`.
- Symptom: `gh run list --limit 5 --json databaseId,headSha,status,conclusion,workflowName,url,createdAt` failed because `gh` was not recognized in the active PowerShell session.
- Impact: Local verification cannot rely on GitHub CLI for CI status in this shell, but CI can still be checked through the public GitHub Actions REST API.
- Evidence: PowerShell returned `CommandNotFoundException` for `gh`.
- Root cause: GitHub CLI is not installed or not on PATH in the current environment.
- Workaround: Use `Invoke-RestMethod https://api.github.com/repos/neutronstar238/ai-researcher/actions/runs?...` to inspect Actions runs.
- Next action: Install GitHub CLI or keep the REST API fallback in future CI checks.
- Linked tasks: `97.1`, `98.1`
- Resolution: Mitigated with the REST API fallback.
- Verification: `Invoke-RestMethod -Uri "https://api.github.com/repos/neutronstar238/ai-researcher/actions/runs?branch=main&per_page=3" | ConvertTo-Json -Depth 6` returned run `27458374281` for commit `7038f4b7de4b263899d398b729ae0fea6eac57fa`.

### P-20260613-032 - Local environment lacks OpenCode CLI for live code-agent execution smoke

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 14:42:00 +08:00
- Source: Task `97.1` verification while replacing the cc-switch-first code-agent plan with a direct OpenCode backend contract.
- Symptom: `Get-Command opencode -ErrorAction SilentlyContinue | Format-List Source,Version` exited with code 1 and no detected command, so this workstation cannot launch `opencode run`, `opencode serve`, or `opencode acp` for a live execution smoke.
- Impact: The repository can generate and test the OpenCode integration manifest, but it must not claim that OpenCode itself was executed end-to-end on this machine during task `97.1`.
- Evidence: Official OpenCode docs reviewed during task `97.1` describe CLI `run`, `serve`, ACP, permission config, and project skills. `npm view opencode-ai version license repository --json` returned version `1.17.4` and `license=MIT`, but no local `opencode` binary was found.
- Root cause: OpenCode is not installed on the local verification environment.
- Workaround: Not needed after the operator installed OpenCode locally.
- Next action: Keep future code-agent acceptance tests bounded to disposable worktrees and keep AI-Researcher as the validation/merge owner.
- Linked tasks: `97.1`
- Resolution: Task `100.1` verified the installed local `opencode` CLI with a disposable bounded live smoke.
- Verification: `opencode --version` returned `1.17.4`; `opencode models` listed `opencode/deepseek-v4-flash-free`; `opencode run --model opencode/deepseek-v4-flash-free --format json --dir runs\manual-live\task100-opencode-smoke --dangerously-skip-permissions "Create a file named opencode-smoke.txt in the current directory containing exactly: opencode smoke ok"` exited 0 and wrote `runs\manual-live\task100-opencode-smoke\opencode-smoke.txt` with exactly `opencode smoke ok`.

### P-20260613-031 - Compiled LaTeX PDFs could pass despite thin content and layout overflow

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 13:36:00 +08:00
- Source: User review of the generated LaTeX paper artifact after the real task `95.1` autopilot cycle.
- Symptom: `paper-build.json` reported `status=compiled` as soon as LaTeX produced a PDF, even when the manuscript was only 3 pages, all core sections were shallow, and the compile log contained visible `Overfull \hbox` layout warnings.
- Impact: A paper-level release gate could mistake a syntactically compiled PDF for a technically adequate manuscript, weakening the CCF-B/Q3-style output-quality bar.
- Evidence: Real artifact `runs/manual-live/autopilot-task95-structured-queries/cycle-20260613T044908Z/paper-build/main.pdf` had `Pages: 3`; its compile log contained overfull boxes up to `225.47295pt`. After task `96.1`, rerun artifact `runs/manual-live/paper-build-task96-quality/paper-build.json` records `status=compiled_with_quality_issues`, `page_count=3/6`, `word_count=314/2500`, `overfull_hbox_count=11/0`, and failures `page_count`, `word_count`, `section_depth`, `layout_overflow`.
- Root cause: The original paper build gate checked required sections and LaTeX process success, but did not inspect PDF page count, manuscript depth, or LaTeX layout warnings.
- Workaround: None needed after task `96.1`.
- Next action: Expand the manuscript generator itself so future cycles can produce longer evidence-backed technical sections, not merely fail the quality gate.
- Linked tasks: `96.1`
- Resolution: Added deterministic `paper_quality` reporting to `paper-build`, downgraded thin/overflowing compiled PDFs to `compiled_with_quality_issues`, and added `paper_quality_gate` to `evidence-gate`.
- Verification: Focused paper-build/evidence-gate tests, focused ruff, and focused mypy passed. Real `paper-build` over the task `95.1` report exited 0 with `--no-fail-on-not-compiled`, wrote `compiled_with_quality_issues`, and exposed page/word/section/layout failures. Real `evidence-gate` over the same cycle and new paper-build JSON exited 0 with `--no-fail-on-blocked`, wrote `release_allowed=false`, and reported `paper_quality_gate=fail`.

### P-20260613-030 - Real publication cycle still lacks enough classified similar-work evidence

- Status: Mitigated
- Severity: High
- Discovered: 2026-06-13 12:47:00 +08:00
- Source: Real `.env` autopilot verification for task `95.1`.
- Symptom: A full real `pendigits_variance_calibrated_prototypes` autopilot cycle completed live literature search, live LLM review, publication audit, paper build, and evidence gate, but publication audit stayed `fail` and evidence gate stayed `blocked`.
- Impact: The system can run a real end-to-end cycle, but it must not claim CCF-B/Q3-level publishability because external novelty positioning is still too weak.
- Evidence: Baseline real run `runs/manual-live/autopilot-task95-real-cycle/cycle-20260613T044400Z/cycle-summary.json` produced 36 similarity findings, all `unknown`. After task `95.1`, `runs/manual-live/autopilot-task95-structured-queries/cycle-20260613T044908Z/cycle-summary.json` used structured queries, produced 57 similarity findings, and reduced `similarity_classification_coverage` from fail to pass with 1 non-unknown finding, but `similarity_classified_finding_breadth` still failed with 1/10 classified findings.
- Root cause: Long paragraph-like research-gap queries produced weak live search matches; task `95.1` mitigated that by prioritizing concise method/baseline/risk benchmark queries. Semantic Scholar also returned HTTP 429/circuit-breaker errors in both literature and similarity phases, keeping source-error risk visible.
- Workaround: Use the structured query generator from task `95.1`; do not lower the publication audit threshold.
- Next action: Improve evidence-backed similarity classification and source recovery: add richer metadata/abstract inspection, broaden adjacent-work query templates, and configure Semantic Scholar API key/rate limits before treating publication novelty as sufficient.
- Linked tasks: `95.1`
- Resolution: Partial mitigation only. Query prompt quality improved, but publication readiness remains blocked by `similarity_classified_finding_breadth` and Semantic Scholar source errors.
- Verification: Focused similarity tests, ruff, and mypy passed. Real patched autopilot cycle passed source preflight and LLM review, wrote structured queries in the similarity summary, improved findings from 36 to 57 and classified findings from 0 to 1, but still wrote `publication_audit=fail` and `evidence_gate=blocked`.

### P-20260613-029 - LLM review repair test initially expected empty findings to pass

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 12:01:00 +08:00
- Source: Focused LLM/CLI tests for task `91.1`.
- Symptom: `poetry run pytest tests\unit\llm\test_client.py tests\unit\cli\test_main.py -q` failed because the new review-repair test expected a repaired response with empty `findings` to score `1.0`.
- Impact: The implementation correctly kept `findings_present` as a hard review-structure gate, but the test fixture was weaker than the intended publication-review behavior.
- Evidence: Pytest reported `assert 0.5 == 1.0` for `test_run_llm_review_retries_once_on_critical_quality_failure`.
- Root cause: The first repaired fixture moved the invalid claim to `unsupported_claims` but left no cited finding, triggering the existing `findings_present` hard check.
- Workaround: None needed after task `91.1`.
- Next action: Keep review fixtures strict: repaired passing outputs must contain at least one valid finding with an allowed outer evidence ID.
- Linked tasks: `91.1`
- Resolution: Updated the repaired fixture to cite `evidence_1` in a valid finding.
- Verification: Reran the focused LLM/CLI tests; they passed with 45 tests.

### P-20260613-028 - Live LLM smoke produced malformed or weak structured JSON under strict gates

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 11:55:00 +08:00
- Source: Real DeepSeek `llm-smoke` verification for task `90.1`.
- Symptom: After hardening structured-output checks, a real `llm-smoke` run failed with malformed JSON and earlier live output encoded `next_steps` as a quoted JSON string instead of an array.
- Impact: Prompt wording alone was not enough to guarantee provider-compliant JSON, so accepting the first response could have let weak structured evidence pass or fail without a recovery artifact.
- Evidence: `poetry run airesearcher llm-smoke --env-path .env --output runs\manual-live\llm-smoke-task90-strict.json --max-tokens 1000 --min-quality-score 0.85` exited 1 with quality score `0.333`; the repaired task run wrote `runs\manual-live\llm-smoke-task90-retry.json` with `attempts=2` and quality score `1.000`.
- Root cause: The live model sometimes returned syntactically invalid JSON or stringified arrays despite JSON-mode and explicit prompt constraints.
- Workaround: None needed after task `90.1`.
- Next action: Keep the one-shot repair path bounded; do not add unbounded retries. Apply the same hard-cap principle to future model-producing gates.
- Linked tasks: `90.1`
- Resolution: Added critical-check score caps, stricter prompts, and a single deterministic repair retry for `llm-smoke`; review quality now also treats missing core structure as hard failure.
- Verification: Focused LLM/CLI tests passed with 44 tests; full `ruff`, full `mypy`, full smoke/unit tests passed with 392 passed and 4 skipped; the real DeepSeek retry run passed with `attempts=2` and quality score `1.000`.

### P-20260613-027 - Evidence lifecycle stage export import order failed ruff

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 11:48:00 +08:00
- Source: Focused ruff verification for task `89.1`.
- Symptom: `poetry run ruff check src\autoresearch\reports\evidence_gate.py src\autoresearch\reports\__init__.py tests\unit\reports\test_evidence_gate.py` failed with `I001 Import block is un-sorted or un-formatted` in `src/autoresearch/reports/__init__.py`.
- Impact: The lifecycle trace implementation and focused tests were valid, but the lint gate blocked completion until the public export order matched ruff/isort expectations.
- Evidence: Ruff reported one fixable `I001` error after exporting `EvidenceLifecycleStage`.
- Root cause: `EvidenceLifecycleStage` was inserted between `EvidenceGateCheckStatus` and `EvidenceGateReport` instead of the sorted import/export order.
- Workaround: None needed after task `89.1`.
- Next action: Keep ruff focused checks in the task verification loop after changing package exports.
- Linked tasks: `89.1`
- Resolution: Reordered the `evidence_gate` import and `__all__` entries in `src/autoresearch/reports/__init__.py`.
- Verification: Reran the focused ruff command; it passed.

### P-20260613-026 - Classified similarity breadth changed audit verdict severity

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 11:35:00 +08:00
- Source: Focused publication-audit verification for task `88.1`.
- Symptom: After adding `similarity_classified_finding_breadth`, four publication-audit tests expected `needs_revision` but received `fail`.
- Impact: The implementation was intentionally stricter, but existing tests had to distinguish cases that should isolate manuscript/method gates from cases that should fail because classified similar-work breadth is below target.
- Evidence: `poetry run pytest tests\unit\reports\test_publication_audit.py -q` initially failed four assertions where `report.verdict` became `PublicationAuditVerdict.FAIL`.
- Root cause: The new check is blocking for CCF-B/Q3-style targets. Fixtures with unknown-only or sparse-classified similarity findings now correctly fail instead of merely needing revision.
- Workaround: None needed after task `88.1`.
- Next action: Keep publication-audit fixtures explicit about whether similarity classifications are part of the behavior under test.
- Linked tasks: `88.1`
- Resolution: Updated tests that isolate manuscript/method gates to provide sufficient `adjacent_work` classifications, and updated unknown-only/sparse-classified tests to expect `fail`.
- Verification: Reran `poetry run pytest tests\unit\reports\test_publication_audit.py -q`, `poetry run ruff check src\autoresearch\reports\publication_audit.py tests\unit\reports\test_publication_audit.py`, and `poetry run mypy src\autoresearch\reports\publication_audit.py`; all passed.

### P-20260613-025 - Similarity token-overlap classifier initially lost to benchmark-gap priority

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 11:30:00 +08:00
- Source: Focused test verification for task `87.1`.
- Symptom: `test_project_similarity_classifies_conservative_token_overlap` expected a source-backed method+dataset token match to classify as `adjacent_work`, but the classifier returned `benchmark_gap`.
- Impact: The new evidence-backed adjacent-work path was implemented, but an earlier dataset/benchmark branch masked the more specific method+dataset evidence.
- Evidence: `poetry run pytest tests\unit\research\test_similarity.py -q` failed with `AssertionError: assert 'benchmark_gap' == 'adjacent_work'`.
- Root cause: Classification priority checked the generic dataset benchmark rule before the new conservative method+dataset token-overlap rule.
- Workaround: None needed after task `87.1`.
- Next action: Keep focused tests around classification priority whenever similarity categories are changed.
- Linked tasks: `87.1`
- Resolution: Moved method+dataset token-overlap classification ahead of the generic benchmark-gap rule while keeping weak-overlap findings as `unknown`.
- Verification: Reran `poetry run pytest tests\unit\research\test_similarity.py -q`, `poetry run ruff check src\autoresearch\research\similarity.py tests\unit\research\test_similarity.py`, and `poetry run mypy src\autoresearch\research\similarity.py`; all passed.

### P-20260613-024 - Unknown-only similarity findings could satisfy novelty coverage

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 11:19:51 +08:00
- Source: User requested strict CCF-B/Q3-level innovation quality control and warned against prompt-only self-discipline after reviewing SCALE-style physical gates.
- Symptom: A publication audit could have enough raw similarity findings while every finding classification remained `unknown`, letting a positive benchmark fixture appear publishable without evidence-backed duplicate/adjacent-work positioning.
- Impact: The system could overstate novelty by treating unclassified online search hits as cross-check evidence, weakening the core promise that publication claims are evidence-bound and non-fabricated.
- Evidence: Before task `86.1`, the positive publication-audit fixture for a method candidate wrote `Classification: unknown` for all similarity findings. A real audit over `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/cycle-summary.json` now writes `similarity_classification_coverage.status=fail` with `unknown=2, classified=0`.
- Root cause: Similarity breadth and duplicate checks counted findings and recognized direct duplicates, but did not separately require at least one non-unknown classification for targets that require a novel contribution.
- Workaround: None needed after task `86.1`.
- Next action: Continue improving the similarity summarizer so it resolves `unknown` findings into direct duplicate, adjacent work, or another evidence-backed category when source abstracts and metadata are sufficient.
- Linked tasks: `86.1`
- Resolution: Task `86.1` adds a high-severity `similarity_classification_coverage` publication-audit check. For CCF-B/Q3-style targets, any nonzero similarity findings that are all `unknown` now block publishability and generate JSON/Markdown plus Obsidian review/issue evidence.
- Verification: `poetry run pytest tests\unit\reports\test_publication_audit.py -q`, `poetry run ruff check src\autoresearch\reports\publication_audit.py tests\unit\reports\test_publication_audit.py`, and `poetry run mypy src\autoresearch\reports\publication_audit.py` passed. A real CLI run `poetry run airesearcher publication-audit runs\manual-live\autopilot-atomic-source-state-task84\cycle-20260613T030125Z\cycle-summary.json --target ccf-b --output-dir runs\manual-live\publication-audit-task86 --vault autoresearch-vault --project-id task86_similarity_classification` wrote `runs/manual-live/publication-audit-task86/publication-audit.json` with `similarity_classification_coverage.status=fail`, `publishable=false`, score `0.523`, plus Obsidian review and issue notes under `autoresearch-vault/projects/task86_similarity_classification/`.

### P-20260613-023 - Source cooldown state updates were not serialized across processes

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 11:09:51 +08:00
- Source: Follow-up after task `84.1` made writes atomic but still left read-modify-write updates vulnerable to last-writer-wins races when multiple workers share one cache root.
- Symptom: Two long-running processes could read the same `source-circuit-breakers.json`, update different source keys, and atomically replace the target in sequence, with the later writer dropping the earlier writer's cooldown entry.
- Impact: A 24h deployment with multiple workers could lose source cooldown evidence and accidentally retry an API that another worker had just rate-limited, weakening source-politeness and publication novelty coverage gates.
- Evidence: Before task `85.1`, `_set_persistent_open()` and `_clear_persistent_open()` performed read-modify-write without an inter-process lock. The first focused pytest run for task `85.1` also failed because the new lock tests called `mkdir(parents=True)` on an existing `tmp_path`; this was a test fixture issue, fixed by adding `exist_ok=True`.
- Root cause: Task `84.1` guarded the final file replacement but not the larger read-modify-write critical section.
- Workaround: None needed after task `85.1`.
- Next action: Monitor whether active source-state locks appear in real deployments. If they persist, investigate stuck workers before increasing lock timeouts.
- Linked tasks: `85.1`
- Resolution: Task `85.1` adds a local exclusive `.lock` around persisted source-state mutations, clears stale locks before writing, raises `SourceCircuitStateLockError` on active lock timeout, and maps active locks to `state_locked` source-preflight blockers in `autopilot`/`serve`.
- Verification: The initial `poetry run pytest tests\unit\literature\test_clients.py -q` failed on the test fixture directory setup and was fixed. `poetry run pytest tests\unit\literature\test_clients.py tests\unit\cli\test_main.py -q`, `poetry run ruff check src\autoresearch\literature\clients.py src\autoresearch\literature\__init__.py src\autoresearch\cli\main.py tests\unit\literature\test_clients.py tests\unit\cli\test_main.py`, and `poetry run mypy src\autoresearch\literature\clients.py src\autoresearch\literature\__init__.py src\autoresearch\cli\main.py` passed. `poetry run ruff check src tests`, `poetry run mypy src`, `git diff --check`, and `poetry run pytest tests\smoke tests\unit -q` also passed; pytest reported 384 passed and 4 skipped, and `git diff --check` only emitted LF-to-CRLF warnings. A real CLI run `poetry run airesearcher autopilot --vault runs\manual-live\task85-locked-state-vault --cache runs\manual-live\task85-locked-state-cache --output-dir runs\manual-live\autopilot-locked-source-state-task85 --state runs\manual-live\autopilot-locked-source-state-task85\scheduler-state.json --project-id task85_locked_state --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 1 --timeout-seconds 60 --no-review` with an active `source-circuit-breakers.json.lock` printed `[BLOCKED] source_preflight: blocked`, wrote `runs/manual-live/autopilot-locked-source-state-task85/cycle-20260613T030942Z/cycle-summary.json`, recorded `state_locked` for Semantic Scholar and OpenAlex, skipped review, queued one follow-up, and wrote an Obsidian issue note with related task `85.1`.

### P-20260613-022 - Source cooldown writes could leave partial state files

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 11:02:03 +08:00
- Source: Follow-up after tasks `82.1` and `83.1` made source preflight depend on persisted `source-circuit-breakers.json` evidence.
- Symptom: `RateLimitCircuitBreaker._write_state()` wrote `source-circuit-breakers.json` directly. A process interruption, failed filesystem write, or concurrent deployment sharing a cache root could leave a partial JSON file.
- Impact: Task `83.1` would correctly fail closed on the next cycle, but the system could still manufacture its own malformed state file and force unnecessary blocked cycles or manual cleanup.
- Evidence: Before task `84.1`, `_write_state()` called `self.state_path.write_text(...)` directly. The new focused test simulates an atomic replacement failure and confirms the previous valid JSON state remains unchanged.
- Root cause: The first persisted-state implementation optimized for simple durable cooldowns and did not yet use same-directory temporary writes plus replace.
- Workaround: None needed after task `84.1`.
- Next action: Done in task `85.1`; monitor real deployments for repeated `state_locked` blockers.
- Linked tasks: `84.1`, `85.1`
- Resolution: Task `84.1` writes state to a same-directory temporary file, atomically replaces the target, and removes temporary files after both successful and failed replacement attempts. Task `85.1` adds a lock around the read-modify-write critical section.
- Verification: `poetry run pytest tests\unit\literature\test_clients.py -q`, `poetry run ruff check src\autoresearch\literature\clients.py tests\unit\literature\test_clients.py`, and `poetry run mypy src\autoresearch\literature\clients.py` passed. `poetry run ruff check src tests`, `poetry run mypy src`, `git diff --check`, and `poetry run pytest tests\smoke tests\unit -q` also passed; pytest reported 381 passed and 4 skipped, and `git diff --check` only emitted LF-to-CRLF warnings. A real CLI run `poetry run airesearcher autopilot --vault runs\manual-live\task84-atomic-vault --cache runs\manual-live\task84-atomic-cache --output-dir runs\manual-live\autopilot-atomic-source-state-task84 --state runs\manual-live\autopilot-atomic-source-state-task84\scheduler-state.json --project-id task84_atomic_state --demo pendigits_variance_calibrated_prototypes --max-queries 1 --max-results-per-source 1 --timeout-seconds 60 --no-review` wrote `runs/manual-live/autopilot-atomic-source-state-task84/cycle-20260613T030125Z/cycle-summary.json`, kept source preflight at `pass`, left `source-circuit-breakers.json` as valid JSON, and left no `.source-circuit-breakers.json.*.tmp` files in the cache directory.

### P-20260613-021 - Malformed source cooldown state would have failed open after BOM fix

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 10:46:00 +08:00
- Source: Follow-up hardening after task `82.1` added source preflight and BOM-tolerant state reads.
- Symptom: A syntactically invalid or structurally invalid `source-circuit-breakers.json` could still leave source cooldowns unverifiable. Treating that as empty state would let a 24h deployment continue into costly work with unknown source safety.
- Impact: Operator-edited state files or partial writes could make the system fail open, weakening the SCALE-lite physical gate and source-politeness guarantees.
- Evidence: A real CLI run with `runs\manual-live\task83-malformed-state-cache\source-circuit-breakers.json` containing `{not-json` was used to exercise the new fail-closed behavior. The verified run at `runs/manual-live/autopilot-malformed-source-state-task83-v2/cycle-20260613T024745Z/cycle-summary.json` recorded `state_error` for Semantic Scholar and OpenAlex and skipped review.
- Root cause: Task `82.1` made valid BOM-bearing JSON readable, but preflight still needed an explicit validation step that treats malformed cooldown state as blocking evidence.
- Workaround: None needed after task `83.1`.
- Next action: Atomic writes were added in task `84.1`; inter-process locking remains a future option only if multiple deployments intentionally share one cache root.
- Linked tasks: `83.1`, `84.1`
- Resolution: Task `83.1` validates persisted source cooldown state in preflight and blocks on unreadable JSON, non-object payloads, or non-numeric expiry values. Task `84.1` reduces self-created malformed-state risk by writing persisted state atomically.
- Verification: `poetry run pytest tests\unit\cli\test_main.py -q`, `poetry run ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py`, and `poetry run mypy src\autoresearch\cli\main.py` passed. The real CLI run `poetry run airesearcher autopilot --vault runs\manual-live\task83-malformed-state-vault-v2 --cache runs\manual-live\task83-malformed-state-cache-v2 --output-dir runs\manual-live\autopilot-malformed-source-state-task83-v2 --state runs\manual-live\autopilot-malformed-source-state-task83-v2\scheduler-state.json --project-id task83_malformed_state_v2 --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 1 --timeout-seconds 60 --no-review` printed `[BLOCKED] source_preflight: blocked` and generated an Obsidian issue with related task IDs `82.1` and `83.1`.

### P-20260613-020 - Source cooldown preflight could be bypassed by operator-written BOM state

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 10:37:00 +08:00
- Source: Task `82.1` real CLI verification using a PowerShell-written `source-circuit-breakers.json` file.
- Symptom: The first real `autopilot` verification for task `82.1` wrote a future Semantic Scholar cooldown with PowerShell `Set-Content -Encoding UTF8`, but the preflight reported `pass` and continued into literature refresh, publication audit, and evidence gate.
- Impact: A human/operator-edited cooldown file could fail open, causing a 24h deployment to run costly work and potentially hit a source while it should be respecting an existing cooldown.
- Evidence: `poetry run airesearcher autopilot --vault runs\manual-live\task82-preflight-vault --cache runs\manual-live\task82-preflight-cache --output-dir runs\manual-live\autopilot-source-preflight-task82 --state runs\manual-live\autopilot-source-preflight-task82\scheduler-state.json --project-id task82_source_preflight --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 1 --timeout-seconds 60 --no-review` printed `[OK] source_preflight: pass` even though `source-circuit-breakers.json` contained a future `semantic_scholar` expiry.
- Root cause: `RateLimitCircuitBreaker._read_state()` used `encoding="utf-8"` and silently treated a UTF-8 BOM JSON file as unreadable, returning an empty state.
- Workaround: None needed after task `82.1`; source state is now read with `utf-8-sig`.
- Next action: Done in task `83.1`; malformed state files now block source preflight.
- Linked tasks: `82.1`, `83.1`
- Resolution: Task `82.1` changes source cooldown reads to `utf-8-sig` and adds a BOM-state regression test. Task `83.1` makes malformed persisted source state fail closed during source preflight.
- Verification: `poetry run pytest tests\unit\literature\test_clients.py tests\unit\cli\test_main.py -q` passed, including the BOM-state test. A second real CLI run with a BOM-bearing Semantic Scholar cooldown at `runs/manual-live/autopilot-source-preflight-task82-bom/cycle-20260613T023832Z/cycle-summary.json` printed `[BLOCKED] source_preflight: blocked`, skipped review, wrote `source-preflight.json`/`.md`, and queued one Obsidian issue follow-up.

### P-20260613-019 - Source cooldowns did not survive process or cycle boundaries

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 10:25:00 +08:00
- Source: Follow-up after task `80.1` showed in-cycle sharing worked but a later process/cycle could still start with an empty circuit breaker.
- Symptom: A long-running or restarted deployment could hit Semantic Scholar 429 in one cycle, then retry the same source immediately in a later cycle because the circuit state only lived in memory.
- Impact: The system was less polite to public literature APIs than required for 24h operation and could repeatedly generate source-error evidence instead of respecting cooldowns.
- Evidence: Before task `81.1`, `RateLimitCircuitBreaker` stored `_opened_until` only in memory. There was no source cooldown file under the literature cache root.
- Root cause: Circuit breaker state used monotonic process time only, which is correct inside one process but cannot survive restarts or separate cycles.
- Workaround: None needed after task `81.1`; autopilot/serve clients now persist source circuit state under the selected cache root.
- Next action: Monitor whether persistent cooldown plus optional API keys are enough for full-width review-enabled runs; if not, add per-source query budgeting or source scheduling.
- Linked tasks: `81.1`, `82.1`
- Resolution: Task `81.1` adds optional wall-clock state-file support to `RateLimitCircuitBreaker` and wires Semantic Scholar/OpenAlex clients in autopilot/serve to `<cache-root>/source-circuit-breakers.json`. Task `82.1` adds a preflight gate that reads that persisted state before costly cycle work.
- Verification: Two consecutive real no-review cycles sharing `runs/manual-live/task81-persistent-cache` showed the first cycle recorded `SourceRateLimitError: Semantic Scholar HTTP 429...`, while the second cycle's first Semantic Scholar literature fetch was `CircuitBreakerOpenError: rate-limit circuit is open...`. Task `82.1` real preflight run at `runs/manual-live/autopilot-source-preflight-task82-bom/cycle-20260613T023832Z/cycle-summary.json` blocked before literature refresh when the persisted state was already cooling down.

### P-20260613-018 - Autopilot rebuilt source clients after a source circuit opened

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 10:16:00 +08:00
- Source: Follow-up review after task `79.1` real aligned cycle.
- Symptom: Literature refresh and similarity checking each created their own ArXiv/Semantic Scholar/OpenAlex clients when `autopilot` did not pass an explicit client mapping. If Semantic Scholar opened a 429 circuit during literature refresh, similarity checking could create a fresh Semantic Scholar client and try the same source again in the same cycle.
- Impact: The system preserved errors correctly, but source politeness and evidence integrity were weaker than needed for a long-running 24h research loop.
- Evidence: Task `79.1` showed repeated Semantic Scholar source failures across both retrieval phases in one cycle. The code path called `run_daily_literature_refresh()` and `run_project_similarity_check()` without shared clients.
- Root cause: Source clients were owned by each retrieval function rather than by the enclosing autopilot cycle.
- Workaround: None needed after task `80.1`; the enclosing cycle now creates and passes one shared client mapping to both phases.
- Next action: Add a durable on-disk source cooldown only if future multi-process or multi-cycle runs keep hitting 429 even with shared in-cycle clients.
- Linked tasks: `80.1`
- Resolution: Task `80.1` adds `_autopilot_literature_clients()` and passes the same mapping into literature refresh and similarity checking.
- Verification: A real task `80.1` cycle at `runs/manual-live/autopilot-shared-sources-task80/cycle-20260613T021650Z/cycle-summary.json` showed one `SourceRateLimitError` in literature refresh followed by `CircuitBreakerOpenError` entries in later literature and similarity Semantic Scholar fetches.

### P-20260613-017 - Autopilot novelty search could drift away from the executed demo

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 10:04:00 +08:00
- Source: Full-width task `79` review-enabled autopilot cycle over `pendigits_variance_calibrated_prototypes`.
- Symptom: The cycle executed the UCI Pendigits variance-calibrated prototype experiment, but the generated candidate remained a generic "evidence-bound self-evolving research loop" topic. Literature and similarity search could therefore evaluate a different research object from the actual method script.
- Impact: Publication-level novelty checks could look broad while failing to cross-check the specific method, dataset, benchmark, and baseline behind the experiment result.
- Evidence: `runs/manual-live/autopilot-variance-full-task79/cycle-20260613T020221Z/cycle-summary.json` recorded `demo.demo=pendigits_variance_calibrated_prototypes`, but the candidate title was generic and `literature.query_count=1`.
- Root cause: `autopilot` generated the literature refresh first from sparse vault context and then generated a generic candidate from the first retrieved document; the selected demo did not seed either step.
- Workaround: None needed after task `79.1`; known demos now inject deterministic literature seed queries and demo-aligned candidate metadata.
- Next action: Add similar seed-query/candidate contracts whenever new real benchmark demos are introduced.
- Linked tasks: `79.1`
- Resolution: Task `79.1` adds a literature query floor, optional seed queries, demo-specific seed lists, and Pendigits-aligned candidate metadata for known Pendigits demos.
- Verification: Focused literature/CLI tests passed. A real `autopilot --demo pendigits_variance_calibrated_prototypes --max-queries 4 --max-results-per-source 3 --no-review` cycle at `runs/manual-live/autopilot-aligned-task79/cycle-20260613T020855Z/cycle-summary.json` reported `literature.query_count=4`, `candidate.title=Variance-calibrated prototype classifiers for UCI Pendigits`, method metadata `diagonal variance-calibrated prototypes with variance shrinkage`, dataset metadata `UCI Pen-Based Recognition of Handwritten Digits`, and `similarity.finding_count=14`.

### P-20260613-016 - Positive method-effect demo is not yet a publishable novelty claim

- Status: Open
- Severity: High
- Discovered: 2026-06-13 09:50:34 +08:00
- Source: Real task `78.1` UCI Pendigits variance-calibrated prototype run and autopilot cycle.
- Symptom: The new method candidate has a positive measured effect over the nearest-centroid baseline, but the full publication audit still fails when literature breadth is smoke-sized and LLM evidence review is skipped.
- Impact: The system now has a real positive-effect method path, but must not present it as a CCF-B/Q3-ready paper until novelty search, related-work breadth, review, and manuscript gates all pass.
- Evidence: `runs/manual-live/pendigits-variance-task78/pendigits-variance-calibrated-prototypes/metrics.json` reported `accuracy=0.823327615780446`, `baseline_accuracy=0.7775871926815323`, and `accuracy_delta_vs_baseline=0.045740423098913685`. The task `78.1` real autopilot cycle reported `method_innovation_evidence.status=pass` and `method_effect_evidence.status=pass`, but overall `verdict=fail` and `publishable=false`. A later review-enabled full-width cycle at `runs/manual-live/autopilot-variance-full-task79/cycle-20260613T020221Z/cycle-summary.json` reported `review.status=passed`, `paper_build.status=compiled`, and `publication_audit.score=0.8361`, but still failed because literature query breadth collapsed to one and Semantic Scholar returned 429. After task `79.1`, `runs/manual-live/autopilot-aligned-task79/cycle-20260613T020855Z/cycle-summary.json` fixed query breadth and demo alignment but still recorded Semantic Scholar 429 source errors and skipped review. Tasks `80.1` and `81.1` improved in-cycle and cross-cycle source politeness. Task `82.1` now stops cycles early when a persisted cooldown is active, but it intentionally does not make the Semantic Scholar source coverage pass.
- Root cause: Positive method effect is necessary but not sufficient; the method still needs broad cross-literature novelty checks without source failures, plus a passing review-enabled cycle on the aligned candidate. The remaining source failure likely requires an API key or longer cooldown beyond an individual cycle.
- Workaround: Keep the result as a positive method-candidate evidence note, not as a publication-ready claim.
- Next action: Provide or configure a Semantic Scholar API key/cooldown that avoids 429, then rerun a review-enabled aligned cycle and compare against adjacent Gaussian/prototype/nearest-centroid calibration literature.
- Linked tasks: `78.1`, `79.1`, `80.1`, `81.1`, `82.1`
- Resolution: Not resolved; task `78.1` creates the positive-effect candidate path and leaves publication readiness blocked by the broader gates.
- Verification: Real `run-demo`, review-enabled `autopilot`, and aligned no-review `autopilot --demo pendigits_variance_calibrated_prototypes --max-queries 4` completed. The aligned cycle reported `literature.query_count=4`, `reproduction_check.status=passed`, `publication_audit.verdict=needs_revision`, and `evidence_gate.verdict=blocked`.

### P-20260613-015 - Method innovation artifacts could pass without positive method-effect evidence

- Status: Resolved
- Severity: High
- Discovered: 2026-06-13 09:33:00 +08:00
- Source: Follow-up review after task `76.1` showed `method_innovation_evidence` can pass when `innovation_evidence.json` exists, even if the candidate underperforms the baseline.
- Symptom: A cycle with a real innovation artifact and all other publication gates satisfied could potentially pass as publication-ready without a positive baseline-vs-candidate effect delta.
- Impact: A method artifact could prove that a mechanism was implemented, but not that empirical-gain claims are supported. This left room for a paper-shaped output to smooth over a neutral or negative result.
- Evidence: The real task `76.1` cycle at `runs/manual-live/autopilot-shrinkage-task76/cycle-20260613T012402Z/` had file-backed innovation evidence, but `accuracy_delta_vs_baseline=-0.0011435105774728616`.
- Root cause: Task `75.1` checked whether file-backed innovation evidence exists, but did not parse the innovation artifact for effect direction or require a positive method delta.
- Workaround: None needed after task `77.1`; publication audit now emits `method_effect_evidence`.
- Next action: For future negative-result papers, add a separate target or review mode that explicitly evaluates negative-result contribution criteria instead of reusing empirical-gain gates.
- Linked tasks: `77.1`
- Resolution: Task `77.1` adds `method_effect_evidence`, which reads innovation artifacts, extracts a numeric baseline-vs-candidate delta, passes positive deltas, and fails neutral, negative, or missing effect evidence for targets requiring novel contribution.
- Verification: Focused publication-audit tests passed, including a negative-delta fixture. A real `publication-audit` over `runs/manual-live/autopilot-shrinkage-task76/cycle-20260613T012402Z/cycle-summary.json` wrote `method_innovation_evidence.status=pass` and `method_effect_evidence.status=fail` with message `Method candidate underperformed the baseline with recorded delta=-0.001144.`

### P-20260613-014 - First method-candidate demo underperformed the Pendigits baseline

- Status: Open
- Severity: High
- Discovered: 2026-06-13 09:24:02 +08:00
- Source: Real `pendigits_prototype_shrinkage` run and task `76.1` autopilot cycle.
- Symptom: The first non-baseline method-candidate demo produced a valid file-backed innovation artifact, but the measured candidate accuracy was lower than the nearest-centroid baseline.
- Impact: The system can now prove that a method candidate was actually implemented and evaluated, but it must not claim empirical improvement or paper-level novelty from this candidate. The self-loop should treat this as a real negative result and search for stronger mechanisms or additional datasets.
- Evidence: `runs/manual-live/pendigits-shrinkage-task76/pendigits-prototype-shrinkage/metrics.json` reported `accuracy=0.7764436821040595`, `baseline_accuracy=0.7775871926815323`, and `accuracy_delta_vs_baseline=-0.0011435105774728616`. `artifacts/innovation_evidence.json` recorded the interpretation `The method candidate underperformed the baseline in this run.`
- Root cause: The implemented shrinkage mechanism is intentionally simple and interpretable; on the official UCI Pendigits split, shrinking class centroids toward the global mean did not improve nearest-centroid classification.
- Workaround: Keep the artifact as negative evidence. After task `77.1`, `method_effect_evidence` blocks empirical-gain claims when the recorded candidate delta is neutral or negative.
- Next action: Use broader similarity search and method exploration to identify a stronger, defensible method candidate, then validate it on at least one real public benchmark plus ablations and reruns.
- Linked tasks: `76.1`
- Resolution: Not resolved; task `76.1` intentionally preserves the negative result instead of hiding it.
- Verification: A real `run-demo --demo pendigits_prototype_shrinkage` completed with validation status `passed`. A real `autopilot --demo pendigits_prototype_shrinkage --no-review` cycle wrote `method_innovation_evidence.status=pass`, `reproduction_check.status=passed`, and `evidence_gate.verdict=blocked` because review was skipped and the broader publication audit still failed.

### P-20260613-013 - Baseline-only paper-style reports could pass publication audit when other gates passed

- Status: Mitigated
- Severity: High
- Discovered: 2026-06-13 09:18:00 +08:00
- Source: Continuation review of publication-audit tests after the user required strict innovation and evidence checks at roughly CCF-B/Q3 quality.
- Symptom: Before task `75.1`, a real-benchmark baseline fixture could pass `ccf-b` publication audit if literature, similarity, data size, ablation, statistics, review, and manuscript-section checks all passed.
- Impact: A future cycle could package a baseline benchmark run as a paper-style PDF without file-backed evidence of a proposed mechanism or method contribution.
- Evidence: `tests/unit/reports/test_publication_audit.py::test_publication_audit_passes_manuscript_gate_for_paper_style_report` expected a baseline-style real benchmark cycle to be publishable after adding paper sections.
- Root cause: The audit checked evidence breadth and manuscript structure but did not distinguish baseline reproduction evidence from an actual method innovation artifact.
- Workaround: None needed after task `75.1`; publication targets now require `method_innovation_evidence` unless the target is `mvp-demo`.
- Next action: Teach future experiment generators to create honest method-contribution metadata and innovation/mechanism artifacts only when a real method change was implemented and validated.
- Linked tasks: `75.1`
- Resolution: Task `75.1` adds `require_novel_contribution` to publication targets, blocks `baseline_only=true` or baseline-named tasks, and requires both proposed mechanism/contribution metadata and an existing innovation/mechanism/contribution artifact.
- Verification: Focused publication-audit tests passed. A real audit over `runs/manual-live/autopilot-reproduction-gate-task74/cycle-20260613T010218Z/cycle-summary.json` wrote `runs/manual-live/publication-audit-task75/publication-audit.json` with `method_innovation_evidence.status=fail`, message `File-backed method innovation evidence is missing or baseline-only.`, and a concrete next action.

### P-20260613-012 - Cycle release evidence proved first execution but not a fresh rerun

- Status: Mitigated
- Severity: Medium
- Discovered: 2026-06-13 09:24:00 +08:00
- Source: User emphasized that the system must verify scripts really execute and must not rely on AI self-reporting tests or research runs.
- Symptom: Before task `74.1`, `autopilot`/`serve` cycle summaries contained the first experiment run record and validation report, but the physical release gate did not require a fresh command-line rerun inside the completed cycle.
- Impact: A future release claim could prove that one experiment ran once, but not that the chosen experiment can be rerun from the CLI and regenerate validation artifacts.
- Evidence: Task `73.1` wrote `paper_build` and `evidence_gate` into `cycle-summary.json`, but `run_evidence_gate()` only checked the first `demo.run_record_path` plus validation artifacts.
- Root cause: Reproduction proof existed inside individual run records, but the always-on cycle did not run a second command-line check after the first run and before release gating.
- Workaround: None needed after task `74.1`; older cycle summaries without `reproduction_check` will now fail the stricter release gate instead of being treated as release-ready.
- Next action: For heavier benchmarks, monitor runtime cost of the automatic rerun and consider an explicit evidence-preserving cache only if it still proves a fresh command invocation and data hash.
- Linked tasks: `74.1`
- Resolution: Task `74.1` adds `_run_cycle_reproduction_check()` to rerun the selected demo via `python -m autoresearch.cli.main run-demo`, records command/exit code/stdout/stderr tails plus fresh run-record and validation paths, and makes `reproduction_rerun_gate` a blocking evidence-gate check.
- Verification: Focused CLI/evidence-gate tests passed. A real `autopilot --no-review` single-cycle run wrote `runs/manual-live/autopilot-reproduction-gate-task74/cycle-20260613T010218Z/cycle-summary.json` with `reproduction_check.status=passed`, `exit_code=0`, one fresh rerun run record, one fresh rerun validation report, and `reproduction_rerun_gate` passed inside `evidence-gate.json`.

### P-20260613-011 - Always-on loop still required manual paper-build and evidence-gate chaining

- Status: Mitigated
- Severity: Medium
- Discovered: 2026-06-13 09:02:00 +08:00
- Source: Continuation review against the user requirement for a one-command 24h system that performs real research, paper-level output, and strict quality gating without manual step-by-step operation.
- Symptom: Before task `73.1`, `autopilot` and `serve` ran literature refresh, similarity search, experiment execution, optional review, and publication audit, but operators still had to manually run `paper-build` and then `evidence-gate` to produce a PDF-level artifact and physical release verdict.
- Impact: A long-running deployment could stop at a Markdown report and publication audit, leaving the strict PDF/evidence gate outside the automatic loop.
- Evidence: `_run_autopilot_cycle()` wrote `publication_audit` into `cycle-summary.json` but did not write `paper_build` or `evidence_gate`.
- Root cause: Paper-build and evidence-gate started as standalone commands and had not yet been wired back into the always-on cycle.
- Workaround: Operators could run `airesearcher paper-build` and `airesearcher evidence-gate` manually over a completed cycle.
- Next action: Continue to improve the quality of the actual research method and external-source stability; automatic gates now expose blockers but do not make baseline experiments publishable.
- Linked tasks: `73.1`
- Resolution: Task `73.1` wires automatic LaTeX paper build and physical evidence gate execution into each `autopilot`/`serve` cycle, records both artifacts in `cycle-summary.json`, and echoes the gate verdict.
- Verification: Focused autopilot CLI test passed. A real local `autopilot --no-review` single-cycle run wrote `paper_build.status=compiled` and `evidence_gate.verdict=blocked` into `runs/manual-live/autopilot-cycle-gate-task73/cycle-20260613T004916Z/cycle-summary.json`; the compiled PDF and evidence-gate JSON existed, and the gate correctly blocked release because review was skipped and publication audit failed.

### P-20260613-010 - Ruff flagged lock-file cleanup as SIM105

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 08:38:00 +08:00
- Source: `poetry run ruff check src\autoresearch\runtime\sessions.py src\autoresearch\runtime\__init__.py src\autoresearch\cli\main.py tests\unit\runtime\test_agent_sessions.py tests\unit\cli\test_main.py` while verifying task `72.3`.
- Symptom: Ruff reported `SIM105 Use contextlib.suppress(FileNotFoundError)` for two lock-file cleanup blocks.
- Impact: The lock implementation worked in tests, but the focused lint gate blocked task completion.
- Evidence: Ruff reported `SIM105` at `src\autoresearch\runtime\sessions.py:322:17` and `src\autoresearch\runtime\sessions.py:335:9`.
- Root cause: The first lock implementation used explicit `try`/`except FileNotFoundError: pass` cleanup blocks.
- Workaround: None needed after replacing the cleanup blocks with `contextlib.suppress(FileNotFoundError)`.
- Next action: Continue running focused ruff before broad tests for runtime hardening tasks.
- Linked tasks: `72.3`
- Resolution: Imported `suppress` from `contextlib` and used it for stale-lock and release cleanup.
- Verification: Focused ruff passed after the fix; full `poetry run ruff check src tests` also passed.

### P-20260613-008 - Prompt-only release discipline is insufficient for autonomous research claims

- Status: Mitigated
- Severity: High
- Discovered: 2026-06-13 03:12:00 +08:00
- Source: User requested SCALE-style physical gates after warning that AI agents can claim tests passed, overwrite each other, or skip review when governance is only prompt-based.
- Symptom: Before task `72.1`, AI-Researcher had strong publication-audit and paper-build artifacts, but no single physical release gate that checked required evidence files, review status, publication audit verdict, and compiled PDF together with a release-blocking exit code.
- Impact: A future operator or agent could treat a non-publishable cycle as releasable by reading only a successful local experiment or compiled PDF while ignoring source errors or audit blockers.
- Evidence: The latest real cycle at `runs/manual-live/serve-paper-structure/cycle-20260612T180330Z/` has a compiled PDF through task `71.1`, but its publication audit remains `needs_revision` because Semantic Scholar source errors still reduce novelty confidence.
- Root cause: The project relied on separate evidence-producing commands and documentation discipline rather than one release decision command that fails closed.
- Workaround: Use `airesearcher evidence-gate` before any release or paper-ready claim.
- Next action: Use `evidence-gate` for release claims and `sessions claim` before concurrent agents edit overlapping file scopes.
- Linked tasks: `72.1`, `72.2`
- Resolution: Task `72.1` added `airesearcher evidence-gate`, `/research:evidence-gate`, JSON/Markdown gate reports, Obsidian review/issue writing, README guidance, and SCALE Engine notice boundaries.
- Verification: Focused evidence-gate tests, CLI tests, compliance tests, ruff, mypy, full smoke/unit tests, and a real evidence-gate command over the latest live cycle and paper build were run for task `72.1`.

### P-20260613-009 - Concurrent agents can overlap file edits without a local claim gate

- Status: Mitigated
- Severity: Medium
- Discovered: 2026-06-13 08:28:00 +08:00
- Source: User asked to borrow SCALE Engine's multi-agent traffic-control idea while keeping the small-team prototype lightweight.
- Symptom: Before task `72.2`, AI-Researcher documented commit and evidence discipline, but there was no executable local check that prevented two active agents from claiming the same file or parent/child directory scope. Before task `72.3`, the new JSON state gate also needed a local mutation lock to avoid simultaneous read/write races.
- Impact: Concurrent coding or research agents could overwrite each other's work, confuse `Agent.md` ownership, or make verification evidence ambiguous.
- Evidence: A real task `72.2` CLI demo wrote `runs/manual-live/session-gate-task72/agent-sessions.json`; `task72-a` claimed `src/autoresearch/runtime`, `task72-b` was blocked when claiming `src/autoresearch/runtime/sessions.py`, and after `task72-a` was released, `task72-b` was allowed. Task `72.3` added a local `.lock` file around claim/release mutations and a fail-fast locked-state CLI demo.
- Root cause: The repository relied on human/agent prompt discipline for workspace coordination instead of a local state file and mutation lock that active agents can check before editing.
- Workaround: Agents should run `airesearcher sessions claim --task-id <task> --agent-name <agent> --path <scope>` before editing shared code or docs, then `airesearcher sessions release <session-id>` when finished.
- Next action: If multiple long-running workers are later spawned, integrate `sessions claim` into worker launch scripts or slash-command wrappers so the locked gate is automatic.
- Linked tasks: `72.2`, `72.3`
- Resolution: Task `72.2` added the local session coordinator, CLI commands, slash template, docs, and focused tests. Task `72.3` added local lock-file serialization with configurable CLI timeout.
- Verification: Focused runtime/CLI tests, a real claim/block/release/claim/list CLI demo, and a real fail-fast locked-state CLI demo were run; broader verification is recorded in `Agent.md`.

### P-20260613-007 - cc-switch code-agent integration must not bypass AI-Researcher validation

- Status: Mitigated
- Severity: Medium
- Discovered: 2026-06-13 01:53:55 +08:00
- Source: User asked whether the coding agent could combine cc-switch provider sharing with Claude Code CLI while AI-Researcher keeps code acceptance.
- Symptom: Directly merging large cc-switch code paths into AI-Researcher would mix a Tauri/Rust/TypeScript desktop provider manager with the Python research runtime, and could blur who owns secrets, provider sync, command approval, validation, merge, and rollback.
- Impact: A future contributor could accidentally give an external code-writing CLI authority to run dangerous commands, accept its own diffs, or write provider secrets into repository artifacts.
- Evidence: Reviewed `https://github.com/farion1231/cc-switch`, its top-level MIT license, provider-management documentation for Universal Provider/model fetching, and Claude Code model configuration docs that distinguish endpoint routing from model selection.
- Root cause: cc-switch is useful provider-routing infrastructure, but it is not the same trust boundary as AI-Researcher's evidence, approval, and publication gates.
- Workaround: Treat cc-switch and Claude Code as an external code-generation backend only. AI-Researcher must capture generated diffs, run local validation, require runtime approval for dangerous actions, own merge/rollback, and write Obsidian plus `Agent.md` records.
- Next action: If a future task executes Claude Code directly, run it in an isolated worktree, add command transcript capture, and require explicit approval before full-permission shell or provider-profile writes.
- Linked tasks: `68.1`
- Resolution: Added `airesearcher code-agents cc-switch init|list`, a repository manifest contract, README guidance, and third-party notice boundaries that keep AI-Researcher as validator.
- Verification: Web review confirmed the current cc-switch repository is public, exposes a top-level MIT license, documents provider management/Universal Provider behavior, and Claude Code docs distinguish endpoint routing from model selection. `poetry run pytest tests/unit/integrations/test_cc_switch.py tests/unit/integrations/test_openclaw.py tests/unit/compliance/test_licenses.py -q`, focused CLI tests, `poetry run ruff check src tests`, `poetry run mypy src`, `git diff --check`, `poetry run airesearcher code-agents cc-switch init --output integrations\cc-switch\code-agent.json`, `poetry run airesearcher code-agents cc-switch list`, `rg` text checks, and `poetry run pytest tests/smoke tests/unit -q` passed during task `68.1`.

### P-20260613-006 - HKUDS AI-Researcher license text is not explicit enough for code reuse

- Status: Open
- Severity: Medium
- Discovered: 2026-06-13 00:52:01 +08:00
- Source: Web review for task `62.1` after the user asked whether HKUDS AI-Researcher is open-source and how it differs from this project.
- Symptom: The upstream repository is public and its `setup.cfg` package metadata declares `license = MIT`, but the repository file list did not expose a top-level `LICENSE` file during review. GitHub issue #94, opened on 2026-06-02, also asks the maintainers to add explicit license clarification.
- Impact: A future contributor could mistakenly treat public source visibility as enough permission to copy code, prompts, benchmark data, or generated examples into AI-Researcher.
- Evidence: Reviewed `https://github.com/HKUDS/AI-Researcher`, raw upstream `README.md`, raw `setup.cfg`, and `https://github.com/HKUDS/AI-Researcher/issues/94`.
- Root cause: Upstream source and package metadata are not accompanied by an explicit repository license text in the reviewed state.
- Workaround: Treat HKUDS AI-Researcher as a conceptual/paper reference only. Do not copy or adapt repository code, prompts, benchmark data, generated examples, or assets unless upstream adds explicit license text or written permission is obtained.
- Next action: Re-check upstream license status before any future incorporation or derivative implementation that uses their repository material.
- Linked tasks: `62.1`
- Resolution: Not resolved upstream; `THIRD_PARTY_NOTICES.md` and README now record the conservative boundary.
- Verification: Updated repository notices and README differentiation notes; focused text search and compliance tests were run for task `62.1`.

### P-20260613-005 - Live DeepSeek reviewer can truncate JSON at 2400 completion tokens

- Status: Resolved
- Severity: Medium
- Discovered: 2026-06-13 00:35:04 +08:00
- Source: Real `airesearcher serve --once --permission-mode allow-all --review --max-tokens 2400` publication-quality verification for task `61.1`.
- Symptom: The LLM evidence review returned `below_threshold` with quality score `0.273` because the response was cut off mid-JSON.
- Impact: The deterministic quality gate correctly rejected the review, but the default token budget was not robust enough for reasoning-token models in the full-loop reviewer prompt.
- Evidence: `runs/manual-live/serve-quality/cycle-20260612T163504Z/llm-review.json` reported `valid_json=false`, missing verdict/summary/findings checks, and `completion_tokens=2400` with `reasoning_tokens=2239`.
- Root cause: The configured DeepSeek reasoning-style model consumed most of the 2400 completion-token budget before emitting complete final JSON.
- Workaround: Pass a larger `--max-tokens` value when running review-heavy commands.
- Next action: Continue monitoring live review outputs; if 4096 also proves unstable on larger reports, add response-repair retry or shorter evidence excerpts.
- Linked tasks: `61.1`
- Resolution: Raised the default LLM reviewer completion budget from 2400 to 4096 in the client and CLI examples.
- Verification: A follow-up real `airesearcher serve --once --permission-mode allow-all --review` run using the new default wrote `runs/manual-live/serve-quality-4096/cycle-20260612T163703Z/llm-review.json` with `quality_score=1.0`, `valid_json=true`, and verdict `pass`.

### P-20260613-004 - Live full-loop outputs are evidence-backed but not publication-ready

- Status: Open
- Severity: High
- Discovered: 2026-06-13 00:34:44 +08:00
- Source: CCF-B publication audit over real `airesearcher serve` full-loop outputs for task `61.1`.
- Symptom: The system can run live literature retrieval, similarity checking, local experiment execution, and LLM evidence review, but the produced report does not meet CCF-B/Q3-style publication standards.
- Impact: The project must not describe current ScientistBench-Lite outputs as publishable papers. The loop is a verified research-automation scaffold, not a finished paper generator.
- Evidence: `runs/manual-live/serve-quality-4096/cycle-20260612T163703Z/publication-audit.md` reports verdict `fail`, score `0.350`, 11 literature documents vs 20 required, only ArXiv successful due Semantic Scholar 429, 4 validated test rows vs 1000 required, synthetic dataset, missing ablation/statistical sanity, and missing paper sections.
- Additional evidence: Task `63.1` live `pendigits_centroid_baseline` runs moved the data-side checks forward. `runs/manual-live/serve-pendigits/cycle-20260612T165932Z/publication-audit.json` and `runs/manual-live/serve-pendigits-sha/cycle-20260612T170946Z/publication-audit.json` show `script_data_verification`, `data_strength`, `dataset_realism`, `baseline_reproduction`, `ablation_coverage`, `statistical_sanity`, and `llm_evidence_review` all passed. The latest run also recorded UCI train/test source URLs, byte counts, and SHA-256 hashes in `runs/manual-live/serve-pendigits-sha/cycle-20260612T170946Z/demo/pendigits-centroid-baseline/artifacts/dataset_sources.json`. The same audit still failed with score `0.5614` due 10 literature documents vs 20 required, only ArXiv successful because Semantic Scholar returned 429/circuit-breaker errors, similarity query breadth 3 vs 4, and missing manuscript sections.
- Additional evidence: Task `64.1` added OpenAlex as a default source. Live `literature-refresh` in `runs/manual-live/task64-vault/exploration/topics/literature_refresh_20260612.md` fetched ArXiv and OpenAlex results while Semantic Scholar still returned HTTP 429. Live `similarity-check` in `runs/manual-live/task64-vault/exploration/topics/similarity_check_autopilot_live_pendigits_sha_20260613_20260612170946.md` showed OpenAlex participating in project-start cross-search.
- Additional evidence: Task `65.1` added sparse-candidate query expansion and low-value topic filtering. A live Pendigits candidate query-generation check produced four distinct scholarly queries. Live `similarity-check` wrote `runs/manual-live/task65-vault/exploration/topics/similarity_check_autopilot_live_pendigits_sha_20260613_20260612170946.md` with 4 queries and 4 findings. Live `serve --once --demo pendigits_centroid_baseline --review` wrote `runs/manual-live/serve-query-floor/cycle-20260612T172905Z/publication-audit.json`; similarity query breadth passed at 4/4 and the total publication score rose to `0.7018`, but the audit still failed because literature documents were 6/20, similarity findings were 8/10, Semantic Scholar returned 429/circuit errors, and manuscript sections were missing.
- Additional evidence: Task `67.1` changed `autopilot` and `serve` defaults to 4 generated queries and up to 10 papers per source/query. A live default-width run at `runs/manual-live/serve-publication-defaults/cycle-20260612T174020Z/publication-audit.json` reported score `0.8421`, literature query breadth 4/4, literature documents 30/20, similarity query breadth 4/4, similarity findings 33/10, and passing data/script/baseline/ablation/statistical/LLM-review gates. The audit still returned `needs_revision` because Semantic Scholar 429/circuit errors remained high-severity source failures and the generated report still lacked paper-style sections.
- Additional evidence: Task `69.1` changed generated Markdown reports to include evidence-backed manuscript sections. A live `serve --once --permission-mode allow-all --demo pendigits_centroid_baseline --review` run wrote `runs/manual-live/serve-paper-structure/cycle-20260612T180330Z/publication-audit.json` with score `0.8909`; `manuscript_structure` passed, literature documents passed at 30/20, similarity findings passed at 33/10, and data/script/baseline/ablation/statistical/LLM-review gates passed. The audit still returned `needs_revision` because Semantic Scholar 429/circuit errors remained high-severity literature and similarity source failures.
- Additional evidence: Task `70.1` added generic LaTeX template compatibility smoke tests. A local real run wrote `runs/manual-live/latex-template-compatibility-task70/latex-template-compatibility.json`, compiled both `generic-article-one-column/main.pdf` and `generic-article-two-column/main.pdf` with `pdflatex`, and wrote an Obsidian Markdown compatibility report to `autoresearch-vault/projects/ai_researcher_system/paper/latex-template-compatibility.md`.
- Additional evidence: Task `70.2` added an external LaTeX template compatibility matrix with source metadata fetches. A real run wrote `runs/manual-live/latex-template-compatibility-task70-external/latex-template-compatibility.json`; IEEEtran and ACM `acmart` source pages returned HTTP 200 and compiled to PDF with local TeX Live, while the Springer Nature source page returned HTTP 200 but `sn-jnl.cls` was not installed locally, so it was recorded as `source_unavailable` instead of being treated as compatible.
- Additional evidence: Task `71.1` added `airesearcher paper-build` and ran it against the live `serve-paper-structure` Markdown report. The command compiled `runs/manual-live/paper-build-task71/main.pdf`, wrote `runs/manual-live/paper-build-task71/paper-build.json`, and mirrored the human-readable summary to `autoresearch-vault/projects/ai_researcher_system/paper/paper-build.md` with no missing sections.
- Additional evidence: Task `72.1` added `airesearcher evidence-gate` as a physical release gate. A real gate run over `runs/manual-live/serve-paper-structure/cycle-20260612T180330Z/cycle-summary.json` plus `runs/manual-live/paper-build-task71/paper-build.json` correctly reported `blocked`: the compiled PDF existed, but `publication_release_gate` failed because the publication audit remained `needs_revision`/`publishable=false`.
- Additional evidence: Task `73.1` moved paper-build and evidence-gate execution into every `autopilot`/`serve` cycle. A real `autopilot --no-review` run at `runs/manual-live/autopilot-cycle-gate-task73/cycle-20260613T004916Z/cycle-summary.json` recorded `paper_build.status=compiled` and `evidence_gate.verdict=blocked`, confirming the PDF path exists while release remains blocked when review/publication gates fail.
- Additional evidence: Task `74.1` adds a fresh command-line reproduction rerun before release gating. New cycle summaries include `reproduction_check` with command, exit code, fresh run-record paths, and fresh validation-report paths; the release gate now blocks cycles that lack this rerun evidence. This improves reproducibility proof but does not resolve publication novelty or source-stability gaps.
- Additional evidence: Task `75.1` adds `method_innovation_evidence` to publication audit. A real audit over the task `74.1` cycle wrote `runs/manual-live/publication-audit-task75/publication-audit.json` with `method_innovation_evidence.status=fail`, explicitly blocking baseline-only publication claims.
- Additional evidence: Task `76.1` adds the first non-baseline Pendigits method candidate with file-backed `artifacts/innovation_evidence.json`. A real run at `runs/manual-live/pendigits-shrinkage-task76/pendigits-prototype-shrinkage/metrics.json` reported `accuracy_delta_vs_baseline=-0.0011435105774728616`, so the artifact is honest negative evidence rather than a publishable empirical gain. A real autopilot cycle at `runs/manual-live/autopilot-shrinkage-task76/cycle-20260613T012402Z/publication-audit.json` passed `method_innovation_evidence` and `script_data_verification`, but failed publication audit because literature/similarity breadth was intentionally smoke-sized, Semantic Scholar returned 429/circuit errors, and LLM review was skipped.
- Additional evidence: Task `77.1` adds `method_effect_evidence` to publication audit. A real audit over the task `76.1` cycle wrote `runs/manual-live/publication-audit-task77/publication-audit.json` with `method_innovation_evidence.status=pass` and `method_effect_evidence.status=fail`, explicitly blocking empirical-gain claims from the negative-result candidate.
- Additional evidence: Task `78.1` adds a positive-effect Pendigits method candidate. A real run at `runs/manual-live/pendigits-variance-task78/pendigits-variance-calibrated-prototypes/metrics.json` reported `accuracy_delta_vs_baseline=0.045740423098913685`; a real autopilot cycle at `runs/manual-live/autopilot-variance-task78/cycle-20260613T015034Z/publication-audit.json` passed `script_data_verification`, `method_innovation_evidence`, and `method_effect_evidence`, but still failed overall because literature/similarity breadth was smoke-sized and review was skipped.
- Root cause: The MVP originally used tiny synthetic ScientistBench-Lite fixtures; task `63.1` added a real benchmark path, task `64.1` added OpenAlex source fallback, task `65.1` fixed sparse query breadth, task `67.1` aligned the default runtime with publication-width search, task `69.1` added paper-structured Markdown drafting, task `70.1` added generic LaTeX PDF compatibility smoke, task `70.2` added partial external template compatibility, task `71.1` added final Markdown-to-LaTeX/PDF artifact building, task `74.1` added a real rerun gate, task `75.1` blocks baseline-only publication claims, task `76.1` adds honest method-candidate evidence, task `77.1` blocks neutral/negative method-effect evidence from passing empirical-gain gates, and task `78.1` adds a real positive-effect method-candidate path. The full system still lacks Semantic Scholar API stability, locally available Springer Nature `sn-jnl` class support, and broad novelty/review evidence for the positive candidate.
- Workaround: Treat `publication-audit` issue notes as self-loop tasks and keep generated reports labeled as demo evidence until stronger experiments exist.
- Next action: Stabilize or key Semantic Scholar access, decide how source-error severity should interact with OpenAlex/ArXiv fallback, add/verify Springer Nature `sn-jnl` class support when license terms and local installation are clear, and search for a stronger method candidate whose improvement survives real benchmark reruns and cross-literature novelty checks.
- Linked tasks: `61.1`, `63.1`, `64.1`, `65.1`, `67.1`, `69.1`, `70.1`, `70.2`, `71.1`, `72.1`, `73.1`, `74.1`, `75.1`, `76.1`, `77.1`, `78.1`
- Resolution: Not resolved; the new publication audit blocks publishable claims and writes Obsidian `review_note`/`issue_note` records for follow-up.
- Verification: Real `airesearcher publication-audit` and real `airesearcher serve` runs wrote failed or needs-revision publication audits under `runs/manual-live/serve-full/`, `runs/manual-live/serve-quality/`, `runs/manual-live/serve-quality-4096/`, `runs/manual-live/serve-pendigits/`, `runs/manual-live/serve-pendigits-sha/`, `runs/manual-live/serve-query-floor/`, `runs/manual-live/serve-publication-defaults/`, and Obsidian project issue notes under `autoresearch-vault/projects/live_quality_4096_20260613/issues/`, `autoresearch-vault/projects/live_pendigits_20260613/issues/`, `autoresearch-vault/projects/live_pendigits_sha_20260613/issues/`, and `autoresearch-vault/projects/live_publication_defaults_20260613/issues/`.

### P-20260613-003 - Live full-loop run hit Semantic Scholar HTTP 429 while ArXiv succeeded

- Status: Mitigated
- Severity: Medium
- Discovered: 2026-06-13 00:15:32 +08:00
- Source: Real `airesearcher serve --once --permission-mode allow-all --review` full-loop verification for task `60.1`.
- Symptom: The literature refresh and similarity-check stages both retrieved one ArXiv result, but Semantic Scholar returned `SourceRateLimitError: Semantic Scholar HTTP 429 rate limited; circuit open for 60.0s`.
- Impact: The full loop still completed with source-backed ArXiv evidence and passed the live LLM evidence review, but cross-source novelty coverage was reduced for this run.
- Evidence: `runs/manual-live/serve-full/cycle-20260612T161532Z/cycle-summary.json` recorded ArXiv success, Semantic Scholar 429 errors, `review.status = passed`, `review.quality_score = 1.0`, and `review.verdict = pass`.
- Mitigation evidence: Task `64.1` added OpenAlex as a default fallback. A live OpenAlex query returned a real `openalex` result with DOI `https://doi.org/10.1017/s0140525x12000477`; live `literature-refresh` then fetched ArXiv plus OpenAlex while preserving the Semantic Scholar 429 error; live `similarity-check` also returned OpenAlex evidence for the Pendigits candidate.
- Root cause: The live Semantic Scholar endpoint rate-limited the unauthenticated or current deployment request window.
- Workaround: The existing Semantic Scholar circuit breaker prevents retry spam and preserves the rate-limit error in the run summary instead of fabricating missing source results. OpenAlex now provides an additional no-key default source when Semantic Scholar is unavailable.
- Next action: For stronger full-loop novelty checks, configure `SEMANTIC_SCHOLAR_API_KEY`, optionally configure `OPENALEX_API_KEY`/`OPENALEX_MAILTO` for larger deployments, and rerun delayed audits after source circuit reset windows.
- Linked tasks: `60.1`, `64.1`
- Resolution: Not fully resolved; mitigated by visible source-level error recording and successful ArXiv-backed loop completion.
- Verification: Live DeepSeek evidence review passed with quality score `1.0`, all findings cited known local evidence IDs, and no unsupported claims were reported.

### P-20260613-002 - Runtime approval test filename collided with existing approval test module

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 00:13:00 +08:00
- Source: `poetry run pytest tests/smoke tests/unit -q` during task `60.1` verification.
- Symptom: Pytest reported an import file mismatch because `tests/unit/research/test_approval.py` and `tests/unit/runtime/test_approval.py` shared the same module basename.
- Impact: Focused runtime tests passed, but the full smoke/unit suite could not collect tests.
- Evidence: Pytest reported imported module `test_approval` came from `tests/unit/research/test_approval.py` instead of `tests/unit/runtime/test_approval.py`.
- Root cause: Test directories are not Python packages, so duplicate test basenames collide in pytest import mode.
- Workaround: None needed after renaming the runtime test file.
- Next action: Use domain-specific test filenames for new test modules.
- Linked tasks: `60.1`
- Resolution: Renamed `tests/unit/runtime/test_approval.py` to `tests/unit/runtime/test_runtime_approval.py`.
- Verification: `poetry run pytest tests/smoke tests/unit -q` passed with 324 tests and 4 skipped after the rename.

### P-20260613-001 - Runtime/channel task quality gates caught import and type issues

- Status: Resolved
- Severity: Low
- Discovered: 2026-06-13 00:05:00 +08:00
- Source: `poetry run ruff check src tests` and `poetry run mypy src` during task `60.1` verification.
- Symptom: Ruff reported `I001 Import block is un-sorted or un-formatted` in `tests/unit/runtime/test_approval.py`; mypy reported an incompatible tuple assignment in `src/autoresearch/cli/main.py` for the OpenClaw channel list command.
- Impact: Focused tests passed, but the repository quality gates blocked task completion.
- Evidence: Ruff found one fixable import-order issue; mypy reported `Incompatible types in assignment (expression has type "tuple[OpenClawChannelPlugin, ...]", variable has type "tuple[OpenClawChannelPlugin]")`.
- Root cause: The new test file import order did not match ruff/isort, and the CLI branch for a single channel let mypy infer a one-item tuple before the all-channel branch assigned a variable-length tuple.
- Workaround: None needed after formatting and annotation fixes.
- Next action: Keep running ruff and mypy after adding CLI commands with branch-dependent collection shapes.
- Linked tasks: `60.1`
- Resolution: Reordered the test imports and annotated the CLI `plugins` variable as `tuple[OpenClawChannelPlugin, ...]`.
- Verification: `poetry run ruff check src tests` and `poetry run mypy src` passed after the fix.

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
