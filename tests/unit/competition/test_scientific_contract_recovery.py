from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import autoresearch.competition.scientific_contract_recovery as recovery
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.scientific_contract_recovery import (
    ConcreteEquation,
    DomainBaselineProbe,
    EquationFactor,
    EquationTerm,
    FrozenEquationArtifact,
    ScientificContractRecoveryError,
    ScientificSentinelFixture,
    freeze_scientific_contract_recovery_plan,
    load_scientific_contract_recovery_plan,
)


def _negative_parent() -> SimpleNamespace:
    return SimpleNamespace(
        package_hash="1" * 64,
        identity=SimpleNamespace(identity_hash="2" * 64),
        development_result_set_hash="3" * 64,
        selection=SimpleNamespace(
            selected_candidate_id="branch-08",
            selected_source_sha256="4" * 64,
            decision="autonomous_development_negative_stop",
        ),
        search_freeze_receipt_created=False,
        search_freeze_receipt=None,
        confirmation_identity_read_count=0,
        confirmation_result_count=0,
        system_generated_manuscript_count=0,
    )


def _probe_result(
    baseline_id: str,
    data_type: str,
    *,
    dimensions: int | None = None,
) -> dict[str, object]:
    dependency = "pyoperon" if baseline_id == "operon_gp_ode" else "pysindy"
    dependency_version = "0.5.0" if dependency == "pyoperon" else "1.7.5"
    payload: dict[str, object] = {
        "baseline_id": baseline_id,
        "data_type": data_type,
        "dependency": dependency,
        "dependency_version": dependency_version,
        "implementation_module": f"fixture.{baseline_id}",
        "implementation_sha256": (
            "5" * 64 if dimensions is None else str(5 + dimensions) * 64
        ),
        "fit_predict_nmse": 1e-12,
        "prediction_shape": None if dimensions is None else [5] * dimensions + [9, 1],
        "equation": "u0_t = -0.5*u0",
        "model_complexity": 3,
        "synthetic_only": True,
        "passed": True,
    }
    if dimensions is not None:
        payload["spatial_dimensions"] = dimensions
    return payload


def _baseline_probe(_image: str) -> DomainBaselineProbe:
    payload: dict[str, object] = {
        "schema_version": "domain-baseline-probe-v1",
        "image": "autoresearch-mdbench:task260",
        "image_id": f"sha256:{'6' * 64}",
        "benchmark_revision": "f81813e760325589737fe3311ac8199ecc64188a",
        "probe_runner_sha256": "7" * 64,
        "python_version": "3.9.23",
        "dependencies": {
            "numpy": "1.26.4",
            "pyoperon": "0.5.0",
            "pysindy": "1.7.5",
            "scikit_learn": "1.5.2",
            "scipy": "1.13.1",
        },
        "network_used": False,
        "official_artifact_reads": 0,
        "probes": [
            _probe_result("operon_gp_ode", "ode"),
            _probe_result("pdefind_pde", "pde", dimensions=2),
            _probe_result("pdefind_pde", "pde", dimensions=3),
        ],
        "passed": True,
    }
    raw_probes = payload["probes"]
    assert isinstance(raw_probes, list)
    payload["probes"] = [
        recovery.DomainBaselineProbeResult.model_validate(item).model_dump(mode="json")
        for item in raw_probes
    ]
    payload["probe_hash"] = canonical_model_hash(payload)
    return DomainBaselineProbe.model_validate(payload)


def _source_fetcher(
    spec: recovery.ScientificContractSourceSpec,
    _timeout_seconds: int,
) -> tuple[bytes, str, int]:
    return (
        f"fixture {spec.source_id}\n{spec.required_marker}\n".encode(),
        spec.url,
        200,
    )


def _freeze(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    parent = _negative_parent()
    monkeypatch.setattr(
        recovery,
        "load_autonomous_development_search_package",
        lambda _path: parent,
    )
    return freeze_scientific_contract_recovery_plan(
        tmp_path / "negative-package.json",
        tmp_path / "plan",
        source_fetcher=_source_fetcher,
        baseline_probe=_baseline_probe,
        clock=lambda: datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
    )


def test_freeze_scientific_contract_plan_is_result_blind_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _freeze(monkeypatch, tmp_path)

    assert plan.negative_binding.package_hash == "1" * 64
    assert plan.new_official_development_result_count == 0
    assert plan.confirmation_identity_read_count == 0
    assert plan.confirmation_result_count == 0
    assert plan.candidate_answer_count == 0
    assert plan.model_interaction_count == 0
    assert plan.harness_implementation_authorized
    assert not plan.official_development_execution_authorized
    assert not plan.confirmation_authorized
    assert plan.next_required_task == "266.2"
    assert len(plan.sources) == 9
    assert len(plan.schemas) == 4
    assert len(plan.sentinels) == 6
    assert {(item.data_type, item.spatial_dimensions, item.field_count) for item in plan.sentinels} >= {
        ("ode", 0, 2),
        ("pde", 1, 1),
        ("pde", 2, 1),
        ("pde", 3, 1),
        ("pde", 1, 2),
    }
    assert [(item.data_type, item.baseline_id) for item in plan.baselines] == [
        ("ode", "operon_gp_ode"),
        ("pde", "pdefind_pde"),
    ]
    assert plan.search_budget.maximum_official_candidate_cells == 380
    assert plan.search_budget.maximum_official_cells_total == 464
    assert plan.estimand.minimum_overall_log_effect > 0.05
    assert "standalone PDE significance" in plan.power_audit.pde_limitation

    fixture_path = Path(plan.output_path).parent / plan.sentinels[-1].relative_path
    fixture = ScientificSentinelFixture.model_validate_json(
        fixture_path.read_text(encoding="utf-8")
    )
    assert len(fixture.queries) == 3
    assert fixture.train_state.shape[-1] == 2
    assert fixture.train_state.shape == fixture.alternative_train_state.shape
    assert fixture.train_state.values != fixture.alternative_train_state.values
    assert sorted(fixture.train_derivative_shuffle_order) == list(
        range(len(fixture.train_derivative_shuffle_order))
    )
    assert all(
        isinstance(term.coefficient, float)
        for equation in fixture.expected_equations
        for term in equation.terms
    )

    loaded = load_scientific_contract_recovery_plan(plan.output_path)
    assert loaded == plan

    def _unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("idempotent plan reload performed an external action")

    replay = freeze_scientific_contract_recovery_plan(
        tmp_path / "negative-package.json",
        tmp_path / "plan",
        source_fetcher=_unexpected,
        baseline_probe=_unexpected,
    )
    assert replay == plan


def test_scientific_contract_schemas_reject_free_coefficients_and_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _freeze(monkeypatch, tmp_path)
    equation = ConcreteEquation(
        target="u0_t",
        terms=(
            EquationTerm(
                coefficient=-0.5,
                factors=(EquationFactor(field="u0"),),
            ),
        ),
    )
    artifact_payload: dict[str, object] = {
        "schema_version": "frozen-equation-artifact-v1",
        "fit_id": "fit-1",
        "candidate_source_sha256": "8" * 64,
        "training_context_hash": "9" * 64,
        "data_type": "ode",
        "field_names": ["u0"],
        "equations": [equation.model_dump(mode="json")],
        "equation_coordinate_system": "physical-unscaled-v1",
        "field_scaling": [
            {
                "field": "u0",
                "state_offset": 0.0,
                "state_scale": 1.0,
                "derivative_offset": 0.0,
                "derivative_scale": 1.0,
            }
        ],
        "diagnostics": {
            "solver_id": "unit-test-solver",
            "training_sample_count": 32,
            "design_feature_count": 4,
            "selected_term_count": 1,
            "training_nmse": 0.001,
            "fit_wall_seconds": 0.01,
            "warnings": [],
        },
        "fit_call_count": 1,
        "fit_completed_before_query": True,
        "free_symbol_count": 0,
    }
    artifact_payload["artifact_hash"] = canonical_model_hash(artifact_payload)
    artifact = FrozenEquationArtifact.model_validate(artifact_payload)
    assert artifact.equations[0].terms[0].coefficient == -0.5

    invalid_equation = equation.model_dump(mode="json")
    invalid_equation["terms"][0]["coefficient"] = "a"
    invalid_payload = dict(artifact_payload)
    invalid_payload["equations"] = [invalid_equation]
    invalid_payload["artifact_hash"] = canonical_model_hash(invalid_payload)
    with pytest.raises(ValidationError):
        FrozenEquationArtifact.model_validate(invalid_payload)

    invalid_diagnostic = dict(artifact_payload)
    invalid_diagnostic["diagnostics"] = {
        **artifact_payload["diagnostics"],  # type: ignore[dict-item]
        "selected_term_count": 2,
    }
    invalid_diagnostic["artifact_hash"] = canonical_model_hash(invalid_diagnostic)
    with pytest.raises(ValidationError, match="selected-term count"):
        FrozenEquationArtifact.model_validate(invalid_diagnostic)

    sentinel_path = Path(plan.output_path).parent / plan.sentinels[0].relative_path
    payload = json.loads(sentinel_path.read_text(encoding="utf-8"))
    payload["prediction_nmse_maximum"] = 1.0
    sentinel_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScientificContractRecoveryError, match="sentinel changed"):
        load_scientific_contract_recovery_plan(plan.output_path)


def test_scientific_contract_plan_rejects_qualified_parent_and_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parent = _negative_parent()
    parent.search_freeze_receipt_created = True
    parent.search_freeze_receipt = object()
    monkeypatch.setattr(
        recovery,
        "load_autonomous_development_search_package",
        lambda _path: parent,
    )
    with pytest.raises(ScientificContractRecoveryError, match="cannot be recovered"):
        freeze_scientific_contract_recovery_plan(
            tmp_path / "parent.json",
            tmp_path / "qualified",
            source_fetcher=_source_fetcher,
            baseline_probe=_baseline_probe,
        )

    clean_parent = _negative_parent()
    monkeypatch.setattr(
        recovery,
        "load_autonomous_development_search_package",
        lambda _path: clean_parent,
    )

    def _missing_marker(
        spec: recovery.ScientificContractSourceSpec,
        _timeout_seconds: int,
    ) -> tuple[bytes, str, int]:
        return b"wrong source", spec.url, 200

    with pytest.raises(ScientificContractRecoveryError, match="marker missing"):
        freeze_scientific_contract_recovery_plan(
            tmp_path / "parent.json",
            tmp_path / "missing-marker",
            source_fetcher=_missing_marker,
            baseline_probe=_baseline_probe,
        )
