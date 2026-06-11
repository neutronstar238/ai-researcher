"""MVP acceptance runs over available local demo tasks."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.experiments.demo_workflow import (
    DemoWorkflowResult,
    run_scientistbench_demo,
)
from autoresearch.experiments.demos import (
    TABULAR_BASELINE_TASK_ID,
    TEXT_CLASSIFIER_STUB_TASK_ID,
)

AVAILABLE_MVP_DEMOS = (
    TABULAR_BASELINE_TASK_ID,
    TEXT_CLASSIFIER_STUB_TASK_ID,
)
FULL_LOOP_SUCCESS_TARGET = 0.60
RERUN_SUCCESS_TARGET = 0.80


@dataclass(frozen=True)
class AcceptanceDemoResult:
    """Acceptance outcome for one demo and its rerun."""

    demo: str
    success: bool
    run_id: str | None
    rerun_success: bool
    rerun_id: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "demo": self.demo,
            "success": self.success,
            "run_id": self.run_id,
            "rerun_success": self.rerun_success,
            "rerun_id": self.rerun_id,
            "error": self.error,
        }


@dataclass(frozen=True)
class AcceptanceRunResult:
    """Persisted MVP acceptance run summary."""

    report_path: Path
    json_path: Path
    failure_dir: Path
    results: tuple[AcceptanceDemoResult, ...]
    success_rate: float
    rerun_success_rate: float
    passed: bool


def run_mvp_acceptance(
    *,
    output_dir: Path | str = Path("runs/acceptance"),
    vault_root: Path | str = Path("autoresearch-vault"),
    demos: tuple[str, ...] = AVAILABLE_MVP_DEMOS,
    timeout_seconds: int = 30,
) -> AcceptanceRunResult:
    """Run available MVP demos and persist acceptance JSON and Markdown reports."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    failure_dir = Path(vault_root) / "exploration" / "failure_patterns"
    results = tuple(
        _run_demo_with_rerun(
            demo,
            output_path=output_path,
            failure_dir=failure_dir,
            timeout_seconds=timeout_seconds,
        )
        for demo in demos
    )
    success_rate = _rate(result.success for result in results)
    rerun_success_rate = _rate(
        result.rerun_success
        for result in results
        if result.success
    )
    passed = (
        success_rate >= FULL_LOOP_SUCCESS_TARGET
        and rerun_success_rate >= RERUN_SUCCESS_TARGET
    )
    json_path = output_path / "acceptance-report.json"
    report_path = output_path / "acceptance-report.md"
    payload = _payload(results, success_rate, rerun_success_rate, passed)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(_markdown(payload), encoding="utf-8")
    return AcceptanceRunResult(
        report_path=report_path,
        json_path=json_path,
        failure_dir=failure_dir,
        results=results,
        success_rate=success_rate,
        rerun_success_rate=rerun_success_rate,
        passed=passed,
    )


def _run_demo_with_rerun(
    demo: str,
    *,
    output_path: Path,
    failure_dir: Path,
    timeout_seconds: int,
) -> AcceptanceDemoResult:
    try:
        first = run_scientistbench_demo(
            demo,
            output_dir=output_path / demo / "initial",
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        _write_failure_note(failure_dir, demo, "initial", exc)
        return AcceptanceDemoResult(
            demo=demo,
            success=False,
            run_id=None,
            rerun_success=False,
            rerun_id=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    try:
        rerun = run_scientistbench_demo(
            demo,
            output_dir=output_path / demo / "rerun",
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        _write_failure_note(failure_dir, demo, "rerun", exc)
        return AcceptanceDemoResult(
            demo=demo,
            success=True,
            run_id=first.run_id,
            rerun_success=False,
            rerun_id=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    return _success_result(demo, first, rerun)


def _success_result(
    demo: str,
    first: DemoWorkflowResult,
    rerun: DemoWorkflowResult,
) -> AcceptanceDemoResult:
    return AcceptanceDemoResult(
        demo=demo,
        success=True,
        run_id=first.run_id,
        rerun_success=True,
        rerun_id=rerun.run_id,
    )


def _write_failure_note(
    failure_dir: Path,
    demo: str,
    phase: str,
    exc: Exception,
) -> None:
    failure_dir.mkdir(parents=True, exist_ok=True)
    path = failure_dir / f"acceptance-{demo}-{phase}.md"
    path.write_text(
        "\n".join(
            [
                f"# Acceptance Failure: {demo}",
                "",
                f"- Demo: `{demo}`",
                f"- Phase: `{phase}`",
                f"- Error type: `{type(exc).__name__}`",
                f"- Error: {exc}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _rate(values: Iterable[object]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if item) / len(items)


def _payload(
    results: tuple[AcceptanceDemoResult, ...],
    success_rate: float,
    rerun_success_rate: float,
    passed: bool,
) -> dict[str, Any]:
    return {
        "available_demo_count": len(results),
        "target_task_count_note": "Run 5 to 10 small tasks when available.",
        "full_loop_success_target": FULL_LOOP_SUCCESS_TARGET,
        "rerun_success_target": RERUN_SUCCESS_TARGET,
        "success_rate": success_rate,
        "rerun_success_rate": rerun_success_rate,
        "passed": passed,
        "results": [result.to_dict() for result in results],
    }


def _markdown(payload: dict[str, Any]) -> str:
    result_rows = [
        "| Demo | Run ID | Success | Rerun ID | Rerun Success | Error |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in payload["results"]:
        assert isinstance(result, dict)
        result_rows.append(
            "| {demo} | {run_id} | {success} | {rerun_id} | {rerun_success} | {error} |".format(
                demo=result["demo"],
                run_id=result["run_id"] or "",
                success=result["success"],
                rerun_id=result["rerun_id"] or "",
                rerun_success=result["rerun_success"],
                error=result["error"] or "",
            )
        )
    return "\n".join(
        [
            "# MVP Acceptance Run",
            "",
            f"- Available demos: `{payload['available_demo_count']}`",
            f"- Success rate: `{payload['success_rate']}`",
            f"- Rerun success rate: `{payload['rerun_success_rate']}`",
            f"- Passed: `{payload['passed']}`",
            "- Target task count: run 5 to 10 small tasks when available.",
            "",
            "## Run Outcomes",
            "",
            *result_rows,
            "",
        ]
    )
