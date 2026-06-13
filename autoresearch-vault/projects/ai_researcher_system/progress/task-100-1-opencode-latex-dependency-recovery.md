# Task 100.1 - OpenCode Smoke And LaTeX Dependency Recovery

## Status

- Task: `100.1`
- Status: completed
- Completed at: 2026-06-13 17:16:00 +08:00

## Summary

This task verified that local OpenCode is installed and can execute a bounded disposable write task, then hardened LaTeX template compatibility and final paper builds so missing external class files trigger recorded recovery instead of a silent unavailable state.

## Evidence

- OpenCode CLI: `opencode --version` returned `1.17.4`.
- OpenCode model smoke: `opencode/deepseek-v4-flash-free` wrote `runs/manual-live/task100-opencode-smoke/opencode-smoke.txt` with exactly `opencode smoke ok`.
- Springer template compatibility: `runs/manual-live/task100-latex-dependency-rerun/latex-template-compatibility.json` recorded `source_http=200`, `dependency_status=downloaded`, and `status=compiled`.
- Springer class artifact: `runs/manual-live/task100-latex-dependency-rerun/springer-nature-sn-jnl/sn-jnl.cls`.
- Springer compatibility PDF: `runs/manual-live/task100-latex-dependency-rerun/springer-nature-sn-jnl/main.pdf`.
- Springer paper-build over the prior real Pendigits report: `runs/manual-live/task100-springer-paper-build-timeout/paper-build.json`.

## Quality Result

The Springer paper-build compiled a PDF, but it correctly remained `compiled_with_quality_issues` because the existing Pendigits manuscript is still too thin for publication:

- Pages: `3 / 6`
- Words: `314 / 2500`
- Overfull hbox: `5 / 0`
- Failures: `page_count`, `word_count`, `section_depth`, `layout_overflow`

This means dependency recovery is now implemented and visible, but the generated manuscript is not yet directly publishable at the CCF-B/Q3 target.

## Linked Problems

- [[P-20260613-032]] resolved by local OpenCode smoke.
- [[P-20260613-035]] resolved by adding the Springer `amsmath` preamble and rerunning a live compile.

## Next

- Run a fresh full autonomous cycle with real online search, LLM review, publication audit, evidence gate, and self-evolution checks.
- Do not lower publication thresholds to make the current thin paper pass.
