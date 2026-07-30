from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.portfolio import PortfolioIntegrityError
from autoresearch.research.search_policy_study import (
    FROZEN_ABLATIONS,
    FROZEN_ARMS,
    BaselineReproductionAttempt,
    BenchmarkTaskAudit,
    ExactPairedPowerScenario,
    SearchPolicyFeasibilityReport,
    SearchPolicyPreregistration,
    StudyFeasibilityStatus,
    TaskOutputKind,
    exact_mcnemar_power,
    exact_two_sided_sign_test_pvalue,
    load_search_policy_feasibility,
    minimum_exact_mcnemar_sample_size,
    search_policy_study_json_schemas,
    write_search_policy_feasibility,
)

BENCHMARK_ID = "scienceagentbench"
METADATA_URL = (
    "https://huggingface.co/datasets/osunlp/ScienceAgentBench/"
    "blob/main/ScienceAgentBench.csv"
)
TOURNAMENT_HASH = "d" * 64


def _sha(label: str) -> str:
    return canonical_sha256({"label": label})


def _task(
    task_id: str,
    *,
    output_kind: TaskOutputKind = TaskOutputKind.STRUCTURED,
    fully_audited: bool,
    domain: str = "Bioinformatics",
) -> BenchmarkTaskAudit:
    return BenchmarkTaskAudit.create(
        benchmark_id=BENCHMARK_ID,
        task_id=task_id,
        domain=domain,
        metadata_source_url=METADATA_URL,
        output_path=(
            f"output/{task_id}.png"
            if output_kind is TaskOutputKind.IMAGE
            else f"output/{task_id}.csv"
        ),
        evaluator_name=f"eval_{task_id}.py",
        output_kind=output_kind,
        license_id="CC-BY-4.0",
        license_clear=True,
        data_bundle_available=fully_audited,
        evaluator_source_available=fully_audited,
        deterministic_evaluator=fully_audited,
        model_judge_required=output_kind is TaskOutputKind.IMAGE,
        metadata_only=not fully_audited,
    )


def _power_scenarios(unit_count: int) -> list[ExactPairedPowerScenario]:
    return [
        ExactPairedPowerScenario.create(
            independent_unit_count=unit_count,
            alpha=0.05,
            target_power=0.80,
            minimum_effect=0.25,
            favorable_probability=0.25 + unfavorable,
            unfavorable_probability=unfavorable,
        )
        for unfavorable in (0.0, 0.05, 0.10)
    ]


def _blocked_reproduction() -> BaselineReproductionAttempt:
    return BaselineReproductionAttempt.create(
        baseline_id="scienceagentbench-verified-baseline",
        claim_hash=_sha("baseline-claim"),
        source_hashes=[_sha("paper"), _sha("metadata")],
        metric_id="objective-task-success",
        tolerance=0.0,
        attempted=False,
        blockers=[
            "full task bundle and evaluator programs are not anonymously available"
        ],
    )


def _selected_panel_report() -> SearchPolicyFeasibilityReport:
    development_ids = [f"sab-{value:03d}" for value in (1, 2, 4, 5)]
    confirmatory_ids = [f"sab-{value:03d}" for value in range(61, 73)]
    image_ids = {
        f"sab-{value:03d}"
        for value in (4, 61, 62, 63, 64, 65, 66, 68, 69, 70)
    }
    tasks = [
        _task(
            task_id,
            output_kind=(
                TaskOutputKind.IMAGE
                if task_id in image_ids
                else TaskOutputKind.STRUCTURED
            ),
            fully_audited=False,
        )
        for task_id in development_ids + confirmatory_ids
    ]
    return SearchPolicyFeasibilityReport.create(
        report_id="task-263.4.0-feasibility",
        tournament_report_hash=TOURNAMENT_HASH,
        benchmark_id=BENCHMARK_ID,
        benchmark_version="verified-2026-04-30-metadata-only",
        metadata_snapshot_hash=_sha("official-csv"),
        task_audits=tasks,
        development_task_ids=development_ids,
        confirmatory_task_ids=confirmatory_ids,
        power_scenarios=_power_scenarios(len(confirmatory_ids)),
        reproduction=_blocked_reproduction(),
    )


def _successful_reproduction() -> BaselineReproductionAttempt:
    return BaselineReproductionAttempt.create(
        baseline_id="open-objective-panel-baseline",
        claim_hash=_sha("claim"),
        source_hashes=[_sha("source"), _sha("paper")],
        code_hash=_sha("code"),
        data_hash=_sha("data"),
        environment_hash=_sha("environment"),
        command=["python", "-m", "baseline", "--frozen"],
        seeds=[3, 7, 11],
        raw_prediction_hash=_sha("raw-predictions"),
        metric_id="objective-task-success",
        expected_value=0.60,
        observed_value=0.61,
        tolerance=0.02,
        attempted=True,
        clean_environment=True,
        independent_runner=True,
        blockers=[],
    )


def _publishable_synthetic_report() -> SearchPolicyFeasibilityReport:
    development_ids = ["open-dev-001"]
    confirmatory_ids = [f"open-confirm-{index:03d}" for index in range(1, 61)]
    tasks = [
        _task(task_id, fully_audited=True)
        for task_id in development_ids + confirmatory_ids
    ]
    return SearchPolicyFeasibilityReport.create(
        report_id="synthetic-passing-fixture",
        tournament_report_hash=TOURNAMENT_HASH,
        benchmark_id=BENCHMARK_ID,
        benchmark_version="synthetic-fully-audited-v1",
        metadata_snapshot_hash=_sha("synthetic-metadata"),
        task_audits=tasks,
        development_task_ids=development_ids,
        confirmatory_task_ids=confirmatory_ids,
        power_scenarios=_power_scenarios(len(confirmatory_ids)),
        reproduction=_successful_reproduction(),
    )


def test_exact_sign_test_boundary_and_power_are_prospective() -> None:
    assert exact_two_sided_sign_test_pvalue(5, 0) == 0.0625
    assert exact_two_sided_sign_test_pvalue(6, 0) == 0.03125
    assert exact_two_sided_sign_test_pvalue(0, 0) == 1.0

    expected = [
        (0.0, 0.05440223217010498, 31),
        (0.05, 0.08015161331059904, 45),
        (0.10, 0.09561866098122412, 60),
    ]
    for scenario, (unfavorable, power, required) in zip(
        _power_scenarios(12), expected, strict=True
    ):
        assert scenario.unfavorable_probability == unfavorable
        assert scenario.achieved_power == pytest.approx(power, abs=1e-14)
        assert scenario.required_independent_unit_count == required


def test_exact_power_helpers_reject_invalid_probability_or_search() -> None:
    with pytest.raises(ValueError, match="probabilities"):
        exact_mcnemar_power(
            independent_unit_count=12,
            favorable_probability=0.8,
            unfavorable_probability=0.3,
            alpha=0.05,
        )
    with pytest.raises(ValueError, match="not reached"):
        minimum_exact_mcnemar_sample_size(
            favorable_probability=0.25,
            unfavorable_probability=0.0,
            alpha=0.05,
            target_power=0.80,
            maximum_units=12,
        )


def test_selected_panel_is_blocked_by_every_noncompensatory_gate() -> None:
    report = _selected_panel_report()

    assert report.status is StudyFeasibilityStatus.BLOCKED_REPRODUCTION_DIAGNOSIS
    assert report.baseline_reproduction_ready is False
    assert report.required_confirmatory_task_count == 60
    assert len(report.confirmatory_task_ids) == 12
    assert sum(
        task.output_kind is TaskOutputKind.IMAGE
        for task in report.task_audits
        if task.task_id in report.confirmatory_task_ids
    ) == 9
    assert {
        "benchmark-data-bundle-unavailable",
        "benchmark-evaluator-source-unavailable",
        "confirmatory-panel-underpowered",
        "deterministic-evaluator-gate-failed",
        "model-judge-independence-gate-failed",
        "objective-structured-output-gate-failed",
        "task-artifacts-unverified",
    } == set(report.blockers)
    assert report.novelty_search_started is False
    assert report.confirmatory_results_revealed is False
    assert report.external_submission_authorized is False


def test_image_cannot_be_declared_objective_without_an_audited_evaluator() -> None:
    with pytest.raises(ValidationError, match="image outputs must remain blocked"):
        BenchmarkTaskAudit.create(
            benchmark_id=BENCHMARK_ID,
            task_id="bad-image",
            domain="Psychology",
            metadata_source_url=METADATA_URL,
            output_path="figure.png",
            evaluator_name="eval_figure.py",
            output_kind=TaskOutputKind.IMAGE,
            license_id="CC-BY-4.0",
            license_clear=True,
            data_bundle_available=True,
            evaluator_source_available=True,
            deterministic_evaluator=True,
            model_judge_required=False,
            metadata_only=False,
        )


def test_development_and_confirmation_are_disjoint_and_exactly_audited() -> None:
    report = _selected_panel_report()
    values = report.model_dump(mode="python", exclude={"report_hash"})
    values["development_task_ids"] = [
        *report.development_task_ids,
        report.confirmatory_task_ids[0],
    ]
    with pytest.raises(ValidationError, match="must be disjoint"):
        SearchPolicyFeasibilityReport.create(**values)


def test_blocked_report_cannot_preregister_or_invent_result_bindings() -> None:
    report = _selected_panel_report()
    with pytest.raises(ValueError, match="reproduced clean-room baseline"):
        SearchPolicyPreregistration.create_from_report(
            report,
            preregistration_id="forbidden-preregistration",
            randomization_seed=20260730,
            within_unit_seeds=[1, 2, 3],
        )
    with pytest.raises(ValidationError, match="cannot contain unobserved bindings"):
        BaselineReproductionAttempt.create(
            baseline_id="blocked",
            claim_hash=_sha("claim"),
            source_hashes=[_sha("source")],
            code_hash=_sha("invented-code"),
            metric_id="objective-task-success",
            tolerance=0.0,
            attempted=False,
            blockers=["data unavailable"],
        )


def test_fully_audited_powered_reproduced_panel_freezes_design() -> None:
    report = _publishable_synthetic_report()
    assert report.status is StudyFeasibilityStatus.BASELINE_REPRODUCED
    assert report.baseline_reproduction_ready is True
    assert report.blockers == []

    preregistration = SearchPolicyPreregistration.create_from_report(
        report,
        preregistration_id="search-policy-causal-prereg-v1",
        randomization_seed=20260730,
        within_unit_seeds=[11, 3, 7],
    )
    assert preregistration.arms == FROZEN_ARMS
    assert preregistration.ablations == FROZEN_ABLATIONS
    assert preregistration.confirmatory_task_ids == sorted(
        report.confirmatory_task_ids
    )
    assert preregistration.within_unit_seeds == [3, 7, 11]
    assert "never independent units" in preregistration.within_unit_repeat_role
    assert preregistration.confirmatory_results_sealed is True


def test_failed_reproduction_cannot_be_weighted_away() -> None:
    successful = _publishable_synthetic_report()
    failed_attempt = BaselineReproductionAttempt.create(
        baseline_id="open-objective-panel-baseline",
        claim_hash=_sha("claim"),
        source_hashes=[_sha("source"), _sha("paper")],
        code_hash=_sha("code"),
        data_hash=_sha("data"),
        environment_hash=_sha("environment"),
        command=["python", "-m", "baseline", "--frozen"],
        seeds=[3, 7, 11],
        raw_prediction_hash=_sha("raw-predictions"),
        metric_id="objective-task-success",
        expected_value=0.60,
        observed_value=0.50,
        tolerance=0.02,
        attempted=True,
        clean_environment=True,
        independent_runner=True,
        blockers=["metric outside frozen tolerance"],
    )
    values = successful.model_dump(mode="python", exclude={"report_hash"})
    values["reproduction"] = failed_attempt
    report = SearchPolicyFeasibilityReport.create(**values)
    assert report.status is StudyFeasibilityStatus.BLOCKED_REPRODUCTION_DIAGNOSIS
    assert "baseline-reproduction-failed" in report.blockers


def test_order_is_canonical_and_nested_tampering_is_detected() -> None:
    first = _selected_panel_report()
    values = first.model_dump(mode="python", exclude={"report_hash"})
    values["task_audits"] = list(reversed(first.task_audits))
    values["development_task_ids"] = list(reversed(first.development_task_ids))
    values["confirmatory_task_ids"] = list(reversed(first.confirmatory_task_ids))
    values["power_scenarios"] = list(reversed(first.power_scenarios))
    second = SearchPolicyFeasibilityReport.create(**values)
    assert second.report_hash == first.report_hash

    object.__setattr__(second.task_audits[0], "domain", "tampered")
    with pytest.raises(PortfolioIntegrityError, match="audit_hash mismatch"):
        second.verify_integrity()


def test_writer_loader_manifest_and_schemas_are_deterministic(
    tmp_path: Path,
) -> None:
    report = _selected_panel_report()
    manifest = write_search_policy_feasibility(tmp_path, report)
    loaded = load_search_policy_feasibility(
        tmp_path / "search-policy-feasibility.json"
    )
    assert loaded == report
    assert manifest.report_hash == report.report_hash
    assert set(manifest.files) == {
        "search-policy-feasibility.json",
        "search-policy-feasibility.md",
        "search-policy-schemas.json",
    }
    markdown = (tmp_path / "search-policy-feasibility.md").read_text(
        encoding="utf-8"
    )
    assert "Required confirmatory tasks: `60`" in markdown
    assert "This artifact is a reproduction diagnosis" in markdown

    schemas = search_policy_study_json_schemas()
    assert schemas == search_policy_study_json_schemas()
    assert len(schemas) == 6
    persisted = json.loads(
        (tmp_path / "search-policy-schemas.json").read_text(encoding="utf-8")
    )
    assert persisted == schemas
