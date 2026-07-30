from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.objective_evaluators import (
    classification_balanced_accuracy,
    meets_frozen_success_threshold,
    regression_r2,
)
from autoresearch.research.objective_task_panel import (
    ObjectiveFamilyProbe,
    ObjectiveTaskFamily,
    OpenObjectiveTaskPanelReport,
    OpenObjectiveTaskUnit,
    OpenTaskPanelStatus,
    PanelPartition,
    load_open_objective_task_panel,
    open_objective_task_panel_json_schemas,
    panel_power_scenarios,
    write_open_objective_task_panel,
)
from autoresearch.research.objective_task_registry import (
    frozen_panel_partitions,
    frozen_selection_exclusions,
    frozen_source_registry_hash,
    frozen_sources,
)
from autoresearch.research.portfolio import PortfolioIntegrityError

DIAGNOSIS_HASH = "7c4d06eb82eabb250cf1b509242480bf27f079f65eaec6fbe564593c54b4aa3c"


def _sha(label: str) -> str:
    return canonical_sha256({"label": label})


def _units(
    *,
    inaccessible_task_id: int | None = None,
) -> list[OpenObjectiveTaskUnit]:
    return [
        OpenObjectiveTaskUnit.create_from_source(
            source,
            target_feature=(
                "class" if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else "target"
            ),
            estimation_procedure_id=(
                1 if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 7
            ),
            number_instances=500,
            number_features=10,
            upstream_metadata_hash=_sha(f"metadata-{source.task_id}"),
            evaluator_source_hash=_sha("objective-evaluator-source"),
            source_reference_found=True,
            anonymous_data_available=source.task_id != inaccessible_task_id,
            fixed_split_available=True,
        )
        for source in frozen_sources()
    ]


def _probes(units: list[OpenObjectiveTaskUnit]) -> list[ObjectiveFamilyProbe]:
    probes: list[ObjectiveFamilyProbe] = []
    for family in ObjectiveTaskFamily:
        representative = next(
            unit
            for unit in units
            if unit.family is family and unit.partition is PanelPartition.DEVELOPMENT
        )
        score = 0.75 if family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 0.25
        probes.append(
            ObjectiveFamilyProbe.create(
                probe_id=f"probe-{family.value}",
                family=family,
                representative_unit_id=representative.unit_id,
                data_sha256=_sha(f"data-{family.value}"),
                data_bytes=4096,
                split_sha256=_sha(f"split-{family.value}"),
                split_bytes=1024,
                license_evidence_sha256=_sha(f"license-{family.value}"),
                evaluator_source_hash=representative.evaluator_source_hash,
                evaluator_score=score,
                evaluator_replay_score=score,
                rows_evaluated=20,
                compute_seconds=0.01,
                data_md5_verified=True,
                split_verified=True,
                license_verified=True,
                task_metadata_verified=True,
            )
        )
    return probes


def _report(
    *,
    inaccessible_task_id: int | None = None,
) -> OpenObjectiveTaskPanelReport:
    units = _units(inaccessible_task_id=inaccessible_task_id)
    return OpenObjectiveTaskPanelReport.create(
        report_id="task-263.4.1-open-objective-panel",
        feasibility_diagnosis_hash=DIAGNOSIS_HASH,
        source_suite_snapshot_hashes={
            "openml-cc18": _sha("cc18-suite"),
            "openml-ctr23": _sha("ctr23-suite"),
        },
        evaluator_code_license_hash=_sha("apache-license"),
        task_units=units,
        family_probes=_probes(units),
        power_scenarios=panel_power_scenarios(),
    )


def test_frozen_registry_is_outcome_blind_independent_and_powered() -> None:
    sources = frozen_sources()
    assignments = frozen_panel_partitions()
    partitions = Counter(assignments.values())
    family_confirmatory = Counter(
        source.family
        for source in sources
        if assignments[(source.family, source.task_id)] is PanelPartition.CONFIRMATORY
    )

    assert len(sources) == 67
    assert partitions == {
        PanelPartition.DEVELOPMENT: 7,
        PanelPartition.CONFIRMATORY: 60,
    }
    assert family_confirmatory == {
        ObjectiveTaskFamily.TABULAR_CLASSIFICATION: 41,
        ObjectiveTaskFamily.TABULAR_REGRESSION: 19,
    }
    assert len({source.data_id for source in sources}) == 67
    assert len({source.source_group for source in sources}) == 67
    assert frozen_source_registry_hash() == (
        "6aa348b2014905d582b979dd35183fe9fa722abcbd41a8de9f65c720bafe780e"
    )

    exclusions = frozen_selection_exclusions()
    assert exclusions["openml-ctr23:361254"] == "ambiguous-public-license-label"
    assert exclusions["openml-ctr23:361264"] == "non-open-noncommercial-license"
    assert exclusions["openml-ctr23:361268"] == "license-version-unspecified"
    assert exclusions["openml-ctr23:361249"] == "non-independent-source-duplicate"
    assert exclusions["openml-cc18:14"] == "non-independent-source-duplicate"
    assert exclusions["openml-cc18:219"] == "no-source-specific-open-license-evidence"


def test_objective_evaluators_are_deterministic_and_model_free() -> None:
    assert classification_balanced_accuracy(
        ["a", "a", "b", "b"],
        ["a", "b", "b", "b"],
    ) == pytest.approx(0.75)
    assert regression_r2([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    assert meets_frozen_success_threshold(
        score=0.8,
        threshold=0.75,
        higher_is_better=True,
        artifact_valid=True,
        replay_valid=True,
        budget_valid=True,
    )
    assert not meets_frozen_success_threshold(
        score=0.8,
        threshold=0.75,
        higher_is_better=True,
        artifact_valid=False,
        replay_valid=True,
        budget_valid=True,
    )
    with pytest.raises(ValueError, match="aligned"):
        classification_balanced_accuracy(["a"], [])
    with pytest.raises(ValueError, match="non-constant"):
        regression_r2([1.0, 1.0], [1.0, 1.0])


def test_passing_panel_is_narrow_objective_and_ready_for_baseline() -> None:
    report = _report()

    assert report.status is OpenTaskPanelStatus.READY_FOR_CLEAN_BASELINE
    assert report.baseline_reproduction_authorized is True
    assert report.required_confirmatory_task_count == 60
    assert len(report.development_unit_ids) == 7
    assert len(report.confirmatory_unit_ids) == 60
    assert report.family_confirmatory_counts == {
        "tabular_classification": 41,
        "tabular_regression": 19,
    }
    assert not report.blockers
    assert report.confirmatory_payloads_downloaded is False
    assert report.study_outcomes_observed is False
    assert report.existing_public_runs_queried is False
    assert report.novelty_search_started is False
    assert "no claim of general autonomous scientific discovery" in report.claim_scope
    assert [scenario.required_independent_unit_count for scenario in report.power_scenarios] == [
        31,
        45,
        60,
    ]


def test_missing_anonymous_data_blocks_without_shrinking_or_replacing_panel() -> None:
    report = _report(inaccessible_task_id=3)

    assert report.status is OpenTaskPanelStatus.BLOCKED
    assert report.baseline_reproduction_authorized is False
    assert report.blockers == ["task-conjunctive-gate-failed"]
    assert len(report.confirmatory_unit_ids) == 60


def test_confirmatory_task_cannot_be_used_as_family_download_probe() -> None:
    units = _units()
    probes = _probes(units)
    confirmatory = next(
        unit
        for unit in units
        if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION
        and unit.partition is PanelPartition.CONFIRMATORY
    )
    payload = probes[0].model_dump(mode="json")
    payload["representative_unit_id"] = confirmatory.unit_id
    payload["probe_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "probe_hash"}
    )
    probes[0] = ObjectiveFamilyProbe.model_validate(payload)

    with pytest.raises(ValidationError, match="development tasks only"):
        OpenObjectiveTaskPanelReport.create(
            report_id="bad-probe-leakage",
            feasibility_diagnosis_hash=DIAGNOSIS_HASH,
            source_suite_snapshot_hashes={
                "openml-cc18": _sha("cc18-suite"),
                "openml-ctr23": _sha("ctr23-suite"),
            },
            evaluator_code_license_hash=_sha("apache-license"),
            task_units=units,
            family_probes=probes,
            power_scenarios=panel_power_scenarios(),
        )


def test_nested_tampering_and_outcome_reveal_are_rejected() -> None:
    report = _report()
    report.task_units[0].number_instances += 1
    with pytest.raises(PortfolioIntegrityError, match="unit_hash"):
        report.verify_integrity()

    payload = _report().model_dump(mode="json")
    payload["study_outcomes_observed"] = True
    with pytest.raises(ValidationError):
        OpenObjectiveTaskPanelReport.model_validate(payload)


def test_panel_round_trip_manifest_and_schemas_are_content_addressed(
    tmp_path: Path,
) -> None:
    report = _report()
    manifest = write_open_objective_task_panel(tmp_path, report)

    loaded = load_open_objective_task_panel(tmp_path / "open-objective-task-panel.json")
    assert loaded.report_hash == report.report_hash
    assert manifest.report_hash == report.report_hash
    assert set(manifest.files) == {
        "open-objective-task-panel.json",
        "open-objective-task-panel.md",
        "open-objective-task-panel-schemas.json",
    }
    assert set(open_objective_task_panel_json_schemas()) == {
        "ObjectiveFamilyProbe",
        "OpenObjectiveTaskPanelManifest",
        "OpenObjectiveTaskPanelReport",
        "OpenObjectiveTaskUnit",
    }
    schema_payload = json.loads(
        (tmp_path / "open-objective-task-panel-schemas.json").read_text(encoding="utf-8")
    )
    assert schema_payload["OpenObjectiveTaskPanelReport"]["additionalProperties"] is False

    path = tmp_path / "open-objective-task-panel.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["task_units"][0]["number_features"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((PortfolioIntegrityError, ValidationError)):
        load_open_objective_task_panel(path)
