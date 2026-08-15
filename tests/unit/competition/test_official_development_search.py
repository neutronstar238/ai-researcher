"""Task 266.3: the official estimand and selection must be correct before any run.

This search spends real container hours and real API budget on the official panel,
so the loss convention, the paired effect direction, the failure penalty, and the
selection basis are all verified against mocked cells first.

The estimand is taken verbatim from the frozen Task 266.1 plan:
  cell loss           derivative NMSE
  paired effect       log(baseline_clipped / candidate_clipped)
  repeated measures   median over condition and seed cells within each system
  system aggregation  median over independent systems
  failed candidate    takes the frozen failure loss, never a drop
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    _FAILURE_LOSS,
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchError,
    _bootstrap_interval,
    _execute_one_cell,
    _generation_brief,
    _median,
    aggregate_paired_effects,
    compute_system_effects,
    execute_official_stage,
    generate_official_candidates,
    revise_official_candidates,
    select_official_candidate,
)
from autoresearch.competition.plan_execution_contract import (
    PlanExecutionContractError,
    audit_candidate_plan_alignment,
    build_prospective_candidate_execution_declaration,
    compile_plan_execution_contract,
)
from autoresearch.research.plan_confirmation import record_plan_decision
from autoresearch.schemas import ResearchPlan
from tests.unit.competition import test_plan_execution_contract as formal_support


def _cell(
    *,
    candidate_id: str,
    system: str,
    nmse: float | None,
    validation: float | None = None,
    status: str = "succeeded",
    method_kind: str = "candidate",
    condition: str = "snr_20",
    seed: int = 101,
    data_type: str = "ode",
) -> OfficialCellResult:
    return OfficialCellResult(
        attempt_id=f"{candidate_id}-{system}-{condition}-{seed}",
        method_kind=method_kind,  # type: ignore[arg-type]
        candidate_id=candidate_id,
        stage="full",
        system_name=system,
        data_type=data_type,  # type: ignore[arg-type]
        condition=condition,  # type: ignore[arg-type]
        seed=seed,
        status=status,  # type: ignore[arg-type]
        derivative_nmse=nmse,
        validation_nmse=validation,
        result_hash="a" * 64,
    )


def _record(candidate_id: str, *, approved: bool = True) -> OfficialCandidateRecord:
    return OfficialCandidateRecord(
        candidate_id=candidate_id,
        generation=1,
        interaction_id=f"gen-{candidate_id}",
        source_relative_path=f"candidates/{candidate_id}/candidate.py",
        source_sha256="b" * 64,
        static_review_approved=approved,
        implementation_summary="a model-authored equation-discovery method",
    )


# --------------------------------------------------------------------------
# Loss convention
# --------------------------------------------------------------------------


def test_failed_cell_takes_the_failure_loss_not_a_drop() -> None:
    """Silently dropping a failed cell would flatter a fragile candidate."""

    assert _cell(candidate_id="c1", system="s1", nmse=None, status="failed").loss == (
        _FAILURE_LOSS
    )
    assert _cell(candidate_id="c1", system="s1", nmse=None, status="timed_out").loss == (
        _FAILURE_LOSS
    )


@pytest.mark.parametrize("mode", ["timeout", "missing-result"])
def test_container_failure_retains_hash_bound_raw_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    payload: dict[str, Any] = {
        "attempt_id": f"baseline-cell-{mode}",
        "method_kind": "baseline",
        "candidate_id": "operon_or_pdefind",
        "stage": "baseline",
        "system_name": "ode-system",
        "data_type": "ode",
        "condition": "clean",
        "seed": 101,
        "data_relative_path": "ode-system/clean.npz",
        "data_sha256": "a" * 64,
        "candidate_source_sha256": None,
    }
    payload["spec_hash"] = canonical_model_hash(payload)
    spec = OfficialCellSpec.model_validate(payload)
    identity = OfficialDevelopmentIdentity.model_construct(
        data_root=tmp_path.as_posix(),
        image_id="sha256:" + "b" * 64,
    )

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd="docker", timeout=1)
        return subprocess.CompletedProcess(args=["docker"], returncode=1)

    monkeypatch.setattr(
        "autoresearch.competition.official_development_search.subprocess.run",
        fake_run,
    )
    result = _execute_one_cell(
        spec=spec,
        identity=identity,
        output_root=tmp_path,
        candidate_paths={},
        runner_path=tmp_path / "runner.py",
        baseline_runner_sha256="c" * 64,
        baseline_method={"method": "pinned"},
        timeout_seconds=60,
    )

    raw_path = tmp_path / "cells" / "baseline" / spec.attempt_id / "result.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_body = dict(raw)
    raw_hash = raw_body.pop("result_hash")
    assert raw["spec_hash"] != spec.spec_hash
    assert raw_hash == canonical_model_hash(raw_body)
    assert result.result_hash == raw_hash
    assert result.status == ("timed_out" if mode == "timeout" else "failed")


def test_nonfinite_nmse_takes_the_failure_loss() -> None:
    assert _cell(candidate_id="c1", system="s1", nmse=float("nan")).loss == _FAILURE_LOSS
    assert _cell(candidate_id="c1", system="s1", nmse=float("inf")).loss == _FAILURE_LOSS


def test_real_noisy_loss_survives_clipping() -> None:
    """The real-data regime is O(0.1..1); clipping must not touch it.

    This is the regime that makes the log ratio meaningful, unlike the synthetic
    sentinels where both arms reached machine precision (P-20260802-060).
    """

    for value in (0.1098, 0.1876, 0.5901):
        assert _cell(candidate_id="c1", system="s1", nmse=value).loss == pytest.approx(
            value
        )


# --------------------------------------------------------------------------
# Paired effect
# --------------------------------------------------------------------------


def test_positive_effect_means_the_candidate_beat_the_baseline() -> None:
    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[_cell(candidate_id="c1", system="s1", nmse=0.10)],
        baseline_results=[
            _cell(
                candidate_id="operon_or_pdefind",
                system="s1",
                nmse=0.40,
                method_kind="baseline",
            )
        ],
    )

    assert len(effects) == 1
    assert effects[0].paired_log_effect == pytest.approx(math.log(4.0))
    assert effects[0].paired_log_effect > 0.0


def test_negative_effect_means_the_baseline_won() -> None:
    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[_cell(candidate_id="c1", system="s1", nmse=0.80)],
        baseline_results=[
            _cell(
                candidate_id="operon_or_pdefind",
                system="s1",
                nmse=0.20,
                method_kind="baseline",
            )
        ],
    )

    assert effects[0].paired_log_effect == pytest.approx(math.log(0.25))


def test_repeated_measures_are_aggregated_within_system_first() -> None:
    """Condition and seed cells are repeated measures, not independent units."""

    candidate_cells = [
        _cell(candidate_id="c1", system="s1", nmse=0.10, condition="clean", seed=101),
        _cell(candidate_id="c1", system="s1", nmse=0.30, condition="snr_20", seed=101),
        _cell(candidate_id="c1", system="s1", nmse=0.20, condition="snr_20", seed=211),
    ]
    baseline_cells = [
        _cell(
            candidate_id="operon_or_pdefind",
            system="s1",
            nmse=0.40,
            method_kind="baseline",
        )
    ]

    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=candidate_cells,
        baseline_results=baseline_cells,
    )

    # Median of 0.10, 0.30, 0.20 is 0.20.
    assert effects[0].candidate_median_loss == pytest.approx(0.20)
    assert effects[0].candidate_cell_count == 3
    assert effects[0].candidate_success_count == 3


def test_one_failed_cell_drags_the_system_median() -> None:
    """A candidate that fails a cell must not look as good as one that does not."""

    solid = compute_system_effects(
        candidate_id="c1",
        candidate_results=[
            _cell(candidate_id="c1", system="s1", nmse=0.10),
            _cell(candidate_id="c1", system="s1", nmse=0.12, seed=211),
            _cell(candidate_id="c1", system="s1", nmse=0.14, seed=307),
        ],
        baseline_results=[
            _cell(
                candidate_id="b", system="s1", nmse=0.40, method_kind="baseline"
            )
        ],
    )
    fragile = compute_system_effects(
        candidate_id="c1",
        candidate_results=[
            _cell(candidate_id="c1", system="s1", nmse=0.10),
            _cell(candidate_id="c1", system="s1", nmse=None, status="failed", seed=211),
            _cell(candidate_id="c1", system="s1", nmse=None, status="failed", seed=307),
        ],
        baseline_results=[
            _cell(
                candidate_id="b", system="s1", nmse=0.40, method_kind="baseline"
            )
        ],
    )

    assert fragile[0].paired_log_effect < solid[0].paired_log_effect
    assert fragile[0].candidate_success_count == 1


def test_failed_baseline_marks_the_system_unpaired() -> None:
    """P-20260802-065: the candidate must not be credited for a baseline failure."""

    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[_cell(candidate_id="c1", system="heat_laser", nmse=157.64)],
        baseline_results=[
            _cell(
                candidate_id="b",
                system="heat_laser",
                nmse=None,
                status="failed",
                method_kind="baseline",
            )
        ],
    )

    assert len(effects) == 1
    assert effects[0].baseline_available is False
    assert effects[0].is_paired is False
    # The raw ratio still looks like a huge win, which is exactly the trap.
    assert effects[0].paired_log_effect > 20.0


def test_aggregation_excludes_unpaired_systems() -> None:
    """Replays the first full stage's PDE stratum.

    heat_laser and heat_soil_uniform_2d_p1 had no baseline and produced +22.5707 and
    +27.6553. The two real pairs were -1.2872 and -5.6029. Including the unpaired
    systems gave a PDE median of +10.641766; excluding them gives -3.445028.
    """

    candidate = [
        _cell(candidate_id="c1", system="heat_laser", nmse=157.64, data_type="pde"),
        _cell(candidate_id="c1", system="heat_soil", nmse=0.97599, data_type="pde"),
        _cell(candidate_id="c1", system="navier_stokes", nmse=0.6079, data_type="pde"),
        _cell(candidate_id="c1", system="reaction_diffusion", nmse=41.199, data_type="pde"),
    ]
    baseline = [
        _cell(
            candidate_id="b", system="heat_laser", nmse=None, status="failed",
            method_kind="baseline", data_type="pde",
        ),
        _cell(
            candidate_id="b", system="heat_soil", nmse=None, status="failed",
            method_kind="baseline", data_type="pde",
        ),
        _cell(
            candidate_id="b", system="navier_stokes", nmse=0.16781,
            method_kind="baseline", data_type="pde",
        ),
        _cell(
            candidate_id="b", system="reaction_diffusion", nmse=0.15191,
            method_kind="baseline", data_type="pde",
        ),
    ]

    effects = compute_system_effects(
        candidate_id="c1", candidate_results=candidate, baseline_results=baseline
    )
    summary = aggregate_paired_effects(effects)

    assert summary["paired_system_count"] == 2
    assert summary["baseline_coverage_gap_count"] == 2
    assert set(summary["unpaired_system_names"]) == {"heat_laser", "heat_soil"}
    # Both real pairs favour the baseline, so the honest median is negative.
    assert summary["pde_stratum_median"] < 0.0
    assert summary["candidate_win_count"] == 0


def test_aggregation_reports_none_when_nothing_is_paired() -> None:
    """A stratum with no working baseline yields no effect, not a victory."""

    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[_cell(candidate_id="c1", system="s1", nmse=1.0)],
        baseline_results=[
            _cell(
                candidate_id="b", system="s1", nmse=None, status="failed",
                method_kind="baseline",
            )
        ],
    )
    summary = aggregate_paired_effects(effects)

    assert summary["paired_system_count"] == 0
    assert summary["overall_median_log_effect"] is None
    assert summary["bootstrap_lower"] is None


def test_aggregation_keeps_a_genuine_win() -> None:
    """The fix must not suppress a real victory over a working baseline."""

    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[
            _cell(candidate_id="c1", system="binocular", nmse=0.34881),
        ],
        baseline_results=[
            _cell(
                candidate_id="b", system="binocular", nmse=38.463,
                method_kind="baseline",
            )
        ],
    )
    summary = aggregate_paired_effects(effects)

    assert summary["paired_system_count"] == 1
    assert summary["candidate_win_count"] == 1
    assert summary["overall_median_log_effect"] > 4.0


def test_system_without_a_baseline_pair_is_skipped() -> None:
    """An unpaired system cannot contribute a paired effect."""

    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[_cell(candidate_id="c1", system="s1", nmse=0.1)],
        baseline_results=[
            _cell(candidate_id="b", system="s2", nmse=0.4, method_kind="baseline")
        ],
    )

    assert effects == ()


def test_strata_are_distinguishable_in_the_effects() -> None:
    """ODE and PDE must be separable so they can be reported apart."""

    effects = compute_system_effects(
        candidate_id="c1",
        candidate_results=[
            _cell(candidate_id="c1", system="ode1", nmse=0.10, data_type="ode"),
            _cell(candidate_id="c1", system="pde1", nmse=0.50, data_type="pde"),
        ],
        baseline_results=[
            _cell(
                candidate_id="b", system="ode1", nmse=0.40,
                method_kind="baseline", data_type="ode",
            ),
            _cell(
                candidate_id="b", system="pde1", nmse=0.30,
                method_kind="baseline", data_type="pde",
            ),
        ],
    )

    assert {item.data_type for item in effects} == {"ode", "pde"}


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def test_selection_uses_validation_not_the_reported_test_loss() -> None:
    """Selecting on the reported effect would contaminate the measurement."""

    results = [
        # c1 is better on the held-out test loss but worse on validation.
        _cell(candidate_id="c1", system="s1", nmse=0.01, validation=0.90),
        _cell(candidate_id="c2", system="s1", nmse=0.90, validation=0.01),
    ]

    selected, basis = select_official_candidate(
        candidates=[_record("c1"), _record("c2")], results=results
    )

    assert selected == "c2"
    assert "validation" in basis


def test_selection_penalises_a_failed_cell() -> None:
    results = [
        _cell(candidate_id="c1", system="s1", nmse=None, status="failed"),
        _cell(candidate_id="c2", system="s1", nmse=0.50, validation=0.50),
    ]

    selected, _ = select_official_candidate(
        candidates=[_record("c1"), _record("c2")], results=results
    )

    assert selected == "c2"


def test_selection_ignores_a_candidate_that_failed_static_review() -> None:
    results = [
        _cell(candidate_id="c1", system="s1", nmse=0.01, validation=0.01),
        _cell(candidate_id="c2", system="s1", nmse=0.50, validation=0.50),
    ]

    selected, _ = select_official_candidate(
        candidates=[_record("c1", approved=False), _record("c2")], results=results
    )

    assert selected == "c2"


def test_selection_returns_none_when_nothing_is_eligible() -> None:
    selected, _ = select_official_candidate(
        candidates=[_record("c1", approved=False)], results=[]
    )

    assert selected is None


def test_selection_is_deterministic_for_replay() -> None:
    results = [
        _cell(candidate_id="c1", system="s1", nmse=0.20, validation=0.20),
        _cell(candidate_id="c2", system="s1", nmse=0.20, validation=0.20),
    ]

    first, _ = select_official_candidate(
        candidates=[_record("c1"), _record("c2")], results=results
    )
    second, _ = select_official_candidate(
        candidates=[_record("c2"), _record("c1")], results=results
    )

    assert first == second


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------


def test_bootstrap_brackets_the_median_and_is_deterministic() -> None:
    values = [0.4, -0.1, 0.9, 0.2, -0.3, 0.1]

    lower, upper = _bootstrap_interval(values)

    assert lower <= _median(values) <= upper
    assert _bootstrap_interval(values) == (lower, upper)


def test_bootstrap_requires_at_least_one_system() -> None:
    with pytest.raises(OfficialDevelopmentSearchError, match="at least one system"):
        _bootstrap_interval([])


# --------------------------------------------------------------------------
# Task 269.3: the non-empty-support contract requirement
# --------------------------------------------------------------------------


def _brief() -> dict[str, object]:
    panel = {
        "systems": [
            {"system_name": "ode-a", "data_type": "ode"},
            {"system_name": "reaction_diffusion_cylinder", "data_type": "pde"},
        ],
        "conditions": ["clean", "snr_20"],
        "seeds": [101],
    }
    budget = {
        "maximum_seconds_per_cell": 300,
        "maximum_memory_mb_per_cell": 4096,
        "maximum_cpu_cores_per_cell": 2,
    }
    return _generation_brief(panel, budget)


def test_the_non_empty_support_requirement_reaches_the_generation_brief() -> None:
    """P-20260802-068: the prior lineage's candidate returned zero terms on one system.

    The requirement must actually reach the brief a candidate is authored from,
    otherwise the repair is only documented and never delivered.
    """

    brief = _brief()
    requirement = brief["non_empty_support_requirement"]
    assert isinstance(requirement, str)
    assert "at least one concrete term" in requirement
    assert "minimal non-empty support" in requirement


def test_the_requirement_states_a_contract_not_a_method() -> None:
    """The candidate still chooses its own library, estimator, and thresholds.

    A brief that named a specific estimator or threshold would be an agent
    authoring the candidate's science instead of stating the contract.
    """

    requirement = str(_brief()["non_empty_support_requirement"]).lower()
    for method_word in ("stlsq", "lasso", "ridge", "pysindy", "threshold of"):
        assert method_word not in requirement


# --------------------------------------------------------------------------
# Bounded local-conformance repair (P-20260804-079)
# --------------------------------------------------------------------------


def _gen_identity(count: int = 1) -> OfficialDevelopmentIdentity:
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "a" * 64,
        "development_panel_hash": "b" * 64,
        "sealed_confirmation_panel_hash": "c" * 64,
        "runner_sha256": "d" * 64,
        "runtime_environment_hash": "e" * 64,
        "image_id": "sha256:" + "1" * 64,
        "data_root": "/data",
        "initial_candidate_count": count,
        "pilot_system_count": 5,
        "full_system_count": 12,
        "conditions": ["clean", "snr_20"],
        "seeds": [101, 211, 307],
        "maximum_official_cells_total": 464,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": "2026-08-04T00:00:00Z",
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _gen_panel() -> dict[str, Any]:
    return {
        "systems": [
            {"system_name": "ode-a", "data_type": "ode"},
            {"system_name": "pde-a", "data_type": "pde"},
        ],
        "conditions": ["clean", "snr_20"],
        "seeds": [101, 211, 307],
    }


def _gen_budget() -> dict[str, Any]:
    return {
        "initial_candidate_count": 1,
        "pilot_ode_system_count": 1,
        "pilot_pde_system_count": 1,
        "pilot_seed_count": 1,
        "full_finalist_count": 1,
        "maximum_terms_per_equation": 64,
        "maximum_seconds_per_cell": 300,
        "maximum_memory_mb_per_cell": 4096,
        "maximum_cpu_cores_per_cell": 2,
    }


def _source_payload() -> dict[str, Any]:
    return {
        "response_type": "scientific_contract_source",
        "observation": "The panel carries noisy measured trajectories.",
        "problem": "Sparse regression overfits the validation window under noise.",
        "hypothesis": "Selecting complexity on held-out evidence narrows the gap.",
        "intervention": "Sweep thresholds and select on a held-out split.",
        "expected_effect": "Lower held-out derivative NMSE than a single max-capacity fit.",
        "implementation_summary": "Ridge-thresholded polynomial library with a fallback.",
        "source_lines": [
            "import numpy as np",
            "",
            "",
            "def fit_equations(payload):",
            "    return {'equations': ['u0_t = 0.0'], 'scaling': {}}",
            "",
            "",
            "def predict_derivative(payload):",
            "    return {'derivative': [0.0]}",
        ],
    }


def _stub_result(payload: dict[str, Any]) -> Any:
    from autoresearch.llm.client import LLMJsonCompletionResult

    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.example/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload),
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.2,
        reasoning_text="considering the library and the fallback",
        reasoning_transport="dashscope_enable_thinking",
    )


def test_a_dropped_required_field_is_repaired_once(tmp_path: Path) -> None:
    """Regression for a real live failure that stopped the generate stage.

    Task `268.5` enables bounded reasoning on every autonomous call, which downgrades
    transport-level `json_schema` to `json_object` on DashScope-shaped providers. The
    PROVIDER therefore no longer enforces the schema, and on a 12k-token source
    payload the model dropped the required `response_type` field. Before this repair
    path the whole generate stage aborted on that single omission.
    """

    calls: list[list[dict[str, str]]] = []

    def _completion(**kwargs: Any) -> Any:
        calls.append([dict(item) for item in kwargs["messages"]])
        payload = _source_payload()
        if len(calls) == 1:
            payload.pop("response_type")
        return _stub_result(payload)

    records = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path,
        completion=_completion,
        clock=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert len(records) == 1
    # One repair attempt, re-asked with the error rather than aborting the stage.
    assert len(calls) == 2
    repair_text = calls[1][-1]["content"]
    assert "failed strict local validation" in repair_text
    assert "response_type" in repair_text
    # The repair prompt must not invite a rewrite of the method being measured.
    assert "identical" in repair_text
    # Provenance must bind the ACCEPTED repair call, not the failed first call.
    record = records[0]
    assert record.interaction_id == "official-generate-01-repair2"
    assert record.interaction_hash is not None
    from autoresearch.competition.autonomous_engine import AutonomousModelInteraction

    interaction = AutonomousModelInteraction.model_validate_json(
        (tmp_path / "interactions" / f"{record.interaction_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert interaction.interaction_hash == record.interaction_hash
    assert interaction.parsed_payload["response_type"] == "scientific_contract_source"


def test_a_persistently_nonconformant_model_fails_loudly(tmp_path: Path) -> None:
    """The repair loop is BOUNDED, so it cannot spin on the frozen budget."""

    calls: list[int] = []

    def _completion(**_kwargs: Any) -> Any:
        calls.append(1)
        payload = _source_payload()
        payload.pop("response_type")
        return _stub_result(payload)

    with pytest.raises(OfficialDevelopmentSearchError, match="schema-conformant"):
        generate_official_candidates(
            identity=_gen_identity(),
            panel=_gen_panel(),
            budget=_gen_budget(),
            output_dir=tmp_path,
            completion=_completion,
            clock=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
        )
    assert len(calls) == 3


def test_a_conformant_first_reply_costs_no_repair_call(tmp_path: Path) -> None:
    """The repair path must not add a provider request to the healthy case."""

    calls: list[int] = []

    def _completion(**_kwargs: Any) -> Any:
        calls.append(1)
        return _stub_result(_source_payload())

    generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path,
        completion=_completion,
        clock=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    assert len(calls) == 1


# --------------------------------------------------------------------------
# Formal prospective plan lifecycle (plan-execution-contract-v2)
# --------------------------------------------------------------------------


def _formal_fixture(tmp_path: Path) -> tuple[Any, Any, str]:
    artifact = formal_support._formal_plan_artifact(tmp_path)
    contract = formal_support.compile_system_authored_plan_execution_contract(artifact)
    assert contract.approved_plan == artifact.plan
    source = formal_support._prospective_source(contract)
    return artifact, contract, source


def _source_completion(source: str, calls: list[list[dict[str, str]]] | None = None) -> Any:
    def complete(**kwargs: Any) -> Any:
        if calls is not None:
            calls.append([dict(item) for item in kwargs["messages"]])
        return formal_support._completion_result(
            formal_support._source_response(source)
        )

    return complete


def test_formal_generation_receives_exact_declaration_and_authors_it_itself(
    tmp_path: Path,
) -> None:
    artifact, contract, source = _formal_fixture(tmp_path)
    output = tmp_path / "generation"
    calls: list[list[dict[str, str]]] = []

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=output,
        completion=_source_completion(source, calls),
        research_plan=artifact,
        clock=lambda: datetime(2026, 8, 9, tzinfo=timezone.utc),
    )[0]

    prompt = json.loads(calls[0][-1]["content"])
    declaration = build_prospective_candidate_execution_declaration(contract)
    assert prompt["prospective_candidate_execution_declaration"] == (
        declaration.model_dump(mode="json")
    )
    assert declaration.schema_version == "prospective-candidate-execution-declaration-v2"
    assert (
        declaration.paired_execution_binding.schema_version
        == "prospective-paired-execution-binding-v1"
    )
    exact_assignment = prompt["prospective_source_contract"]["exact_python_assignment"]
    assert exact_assignment == (
        "PROSPECTIVE_EXECUTION_DECLARATION = "
        f"{declaration.model_dump(mode='python')!r}"
    )
    system_prompt = calls[0][0]["content"]
    source_contract = prompt["prospective_source_contract"]
    assert source_contract["candidate_alignment_audit_schema_version"] == (
        "candidate-plan-alignment-audit-v3"
    )
    assert source_contract["runtime_binding_payload_key"] == (
        "prospective_execution_binding"
    )
    assert source_contract["identity_guards"] == [
        {
            "runtime_path": "prospective_execution_binding.plan_execution_contract_hash",
            "declaration_path": "plan_execution_contract_hash",
            "operator": "!=",
            "on_mismatch": "raise",
        },
        {
            "runtime_path": "prospective_execution_binding.selected_intervention_hash",
            "declaration_path": "selected_intervention_identity.intervention_hash",
            "operator": "!=",
            "on_mismatch": "raise",
        },
        {
            "runtime_path": "prospective_execution_binding.pair_contract_hash",
            "declaration_path": "paired_control_treatment.pair_hash",
            "operator": "!=",
            "on_mismatch": "raise",
        },
    ]
    assert source_contract["identity_guards_must_precede_arm_selection"] is True
    assert source_contract["runtime_configuration_selector"]["runtime_path"] == (
        "prospective_execution_binding.configuration["
        "PROSPECTIVE_EXECUTION_DECLARATION.paired_control_treatment.intervention_key]"
    )
    assert source_contract["control_helper"] != source_contract["treatment_helper"]
    assert source_contract["unknown_arm_action"] == "raise"
    assert source_contract["public_hooks_must_directly_return_dispatcher"] == list(
        contract.public_hooks
    )
    assert source_contract["orchestrator_may_inject_or_rewrite_source"] is False
    assert "exactly the two top-level functions" not in system_prompt
    assert contract.implementation_anchor in system_prompt
    assert "three identity guards" in system_prompt
    assert "prospective_execution_binding" in system_prompt
    assert "distinct control and treatment helpers" in system_prompt
    assert "raise for every unknown arm" in system_prompt
    assert "directly return the dispatcher" in system_prompt
    assert (output / candidate.source_relative_path).read_text(encoding="utf-8") == (
        "\n".join(source.splitlines())
    )
    assert candidate.plan_alignment is None
    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.passed is True
    assert candidate.static_review_approved is True


def test_formal_topology_first_failure_is_repaired_without_rewriting_method(
    tmp_path: Path,
) -> None:
    artifact, contract, valid_source = _formal_fixture(tmp_path)
    invalid_source = valid_source.replace(contract.contract_hash, "0" * 64, 1)
    assert invalid_source != valid_source
    calls: list[list[dict[str, str]]] = []
    responses = [invalid_source, valid_source]

    def completion(**kwargs: Any) -> Any:
        calls.append([dict(item) for item in kwargs["messages"]])
        return formal_support._completion_result(
            formal_support._source_response(responses[len(calls) - 1])
        )

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "topology-repair",
        completion=completion,
        research_plan=artifact,
    )[0]

    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "topology-only repair" in repair_prompt
    assert "preserve the scientific method" in repair_prompt
    assert "implementation-anchor" in repair_prompt
    assert candidate.interaction_id == "official-generate-01-repair2"
    assert candidate.static_review_approved is True
    persisted = (
        tmp_path / "topology-repair" / candidate.source_relative_path
    ).read_text(encoding="utf-8")
    assert persisted == "\n".join(valid_source.splitlines())


def test_formal_same_helper_dispatch_is_repaired_without_scientific_drift(
    tmp_path: Path,
) -> None:
    artifact, contract, valid_source = _formal_fixture(tmp_path)
    invalid_source = formal_support._prospective_source(
        contract, same_arm_helper=True
    )
    calls: list[list[dict[str, str]]] = []
    responses = [invalid_source, valid_source]

    def completion(**kwargs: Any) -> Any:
        calls.append([dict(item) for item in kwargs["messages"]])
        return formal_support._completion_result(
            formal_support._source_response(responses[len(calls) - 1])
        )

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "same-helper-repair",
        completion=completion,
        research_plan=artifact,
    )[0]

    assert len(calls) == 2
    assert candidate.static_review_approved is True
    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.schema_version == (
        "candidate-plan-alignment-audit-v3"
    )
    assert candidate.prospective_plan_alignment.distinct_arm_helpers is True
    repair_prompt = calls[1][-1]["content"]
    assert "helper bodies" in repair_prompt
    assert "runtime configuration" in repair_prompt
    assert "unknown-arm raise" in repair_prompt


@pytest.mark.parametrize(
    "source_mutation",
    [
        "dead_selector",
        "declaration_alias",
        "same_arm_helper",
        "hook_bypass",
        "unknown_arm_fallback",
    ],
)
def test_formal_generation_rejects_restricted_dispatch_bypasses(
    tmp_path: Path,
    source_mutation: str,
) -> None:
    artifact, contract, valid_source = _formal_fixture(tmp_path)
    if source_mutation == "dead_selector":
        invalid_source = formal_support._prospective_source(
            contract, dead_selector=True
        )
    elif source_mutation == "declaration_alias":
        invalid_source = formal_support._prospective_source(
            contract, declaration_alias=True
        )
    elif source_mutation == "same_arm_helper":
        invalid_source = formal_support._prospective_source(
            contract, same_arm_helper=True
        )
    elif source_mutation == "hook_bypass":
        invalid_source = formal_support._prospective_source(
            contract, bypass_hook=contract.public_hooks[0]
        )
    else:
        control_helper = f"{contract.implementation_anchor}__control"
        invalid_source = valid_source.replace(
            "    raise ValueError('unknown prospective arm')",
            f"    return {control_helper}(payload)",
            1,
        )
    calls: list[int] = []

    def completion(**_kwargs: Any) -> Any:
        calls.append(1)
        return formal_support._completion_result(
            formal_support._source_response(invalid_source)
        )

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / source_mutation,
        completion=completion,
        research_plan=artifact,
    )[0]

    assert 1 <= len(calls) <= 3
    assert candidate.static_review_approved is False
    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.schema_version == (
        "candidate-plan-alignment-audit-v3"
    )
    assert candidate.prospective_plan_alignment.passed is False


def test_formal_generation_rejects_v1_declaration_downgrade(tmp_path: Path) -> None:
    artifact, _contract, valid_source = _formal_fixture(tmp_path)
    downgraded = valid_source.replace(
        "prospective-candidate-execution-declaration-v2",
        "prospective-candidate-execution-declaration-v1",
        1,
    )

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "declaration-v1-downgrade",
        completion=_source_completion(downgraded),
        research_plan=artifact,
    )[0]

    assert candidate.static_review_approved is False
    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.declaration_exact is False


def test_formal_candidate_record_rejects_retained_v2_audit_downgrade(
    tmp_path: Path,
) -> None:
    artifact, _contract, source = _formal_fixture(tmp_path)
    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "audit-v2-downgrade",
        completion=_source_completion(source),
        research_plan=artifact,
    )[0]
    payload = candidate.model_dump(mode="json")
    payload["prospective_plan_alignment"]["schema_version"] = (
        "candidate-plan-alignment-audit-v2"
    )

    with pytest.raises(ValueError, match="candidate-plan-alignment-audit-v3"):
        OfficialCandidateRecord.model_validate(payload)


def test_topology_repair_cannot_rewrite_scientific_narrative(
    tmp_path: Path,
) -> None:
    artifact, contract, valid_source = _formal_fixture(tmp_path)
    invalid_source = formal_support._prospective_source(
        contract, same_arm_helper=True
    )
    calls: list[list[dict[str, str]]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append([dict(item) for item in kwargs["messages"]])
        source = invalid_source if len(calls) == 1 else valid_source
        payload = formal_support._source_response(source)
        if len(calls) > 1:
            payload["hypothesis"] = "A repair turn silently replaced the hypothesis."
        return formal_support._completion_result(payload)

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "narrative-drift",
        completion=completion,
        research_plan=artifact,
    )[0]

    assert len(calls) == 3
    assert candidate.static_review_approved is False
    assert any(
        "TOPOLOGY_REPAIR_METHOD_DRIFT" in item
        for item in candidate.static_review_findings
    )
    assert "all six scientific narrative fields" in calls[1][-1]["content"]


def test_schema_repair_cannot_rewrite_scientific_narrative(
    tmp_path: Path,
) -> None:
    artifact, _contract, valid_source = _formal_fixture(tmp_path)
    calls: list[list[dict[str, str]]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append([dict(item) for item in kwargs["messages"]])
        payload = formal_support._source_response(valid_source)
        if len(calls) == 1:
            payload.pop("response_type")
        else:
            payload["hypothesis"] = "Schema repair silently replaced the hypothesis."
        return formal_support._completion_result(payload)

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "schema-narrative-drift",
        completion=completion,
        research_plan=artifact,
    )[0]

    assert len(calls) == 3
    assert candidate.static_review_approved is False
    assert any(
        "REPAIR_SCIENTIFIC_NARRATIVE_DRIFT" in item
        for item in candidate.static_review_findings
    )


def test_three_topology_failures_are_retained_as_rejected_not_executable(
    tmp_path: Path,
) -> None:
    artifact, contract, valid_source = _formal_fixture(tmp_path)
    invalid_source = valid_source.replace(contract.contract_hash, "0" * 64, 1)
    assert invalid_source != valid_source
    calls: list[int] = []

    def completion(**_kwargs: Any) -> Any:
        calls.append(1)
        return formal_support._completion_result(
            formal_support._source_response(invalid_source)
        )

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "topology-three-failures",
        completion=completion,
        research_plan=artifact,
    )[0]

    assert len(calls) == 3
    assert candidate.interaction_id == "official-generate-01-repair3"
    assert candidate.static_review_approved is False
    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.passed is False
    assert any(
        "PROSPECTIVE_PLAN_NOT_IMPLEMENTED" in item
        for item in candidate.static_review_findings
    )
    logical_turns = sorted(
        (tmp_path / "topology-three-failures" / "interactions").glob(
            "*.logical-turn.json"
        )
    )
    assert len(logical_turns) == len(calls) == 3
    assert sorted(
        json.loads(path.read_text(encoding="utf-8"))["logical_attempt_index"]
        for path in logical_turns
    ) == [1, 2, 3]


def test_formal_generation_never_injects_a_missing_declaration(
    tmp_path: Path,
) -> None:
    artifact, _contract, _source = _formal_fixture(tmp_path)
    output = tmp_path / "missing-declaration"
    source = "\n".join(_source_payload()["source_lines"])

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=output,
        completion=_source_completion(source),
        research_plan=artifact,
    )[0]

    persisted = (output / candidate.source_relative_path).read_text(encoding="utf-8")
    assert "PROSPECTIVE_EXECUTION_DECLARATION" not in persisted
    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.passed is False
    assert candidate.static_review_approved is False
    assert any(
        "PROSPECTIVE_PLAN_NOT_IMPLEMENTED" in item
        for item in candidate.static_review_findings
    )


def test_formal_static_review_rejects_duplicate_implementation_anchor(
    tmp_path: Path,
) -> None:
    artifact, contract, source = _formal_fixture(tmp_path)
    anchor = contract.implementation_anchor
    duplicate_source = (
        source
        + "\n"
        + f"def {anchor}(payload):\n"
        + "    contract_hash = PROSPECTIVE_EXECUTION_DECLARATION"
        "['plan_execution_contract_hash']\n"
        + "    intervention_identity = PROSPECTIVE_EXECUTION_DECLARATION"
        "['selected_intervention_identity']\n"
        + "    paired_configuration = PROSPECTIVE_EXECUTION_DECLARATION"
        "['paired_control_treatment']\n"
        + "    return payload\n"
    )

    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=tmp_path / "duplicate-anchor",
        completion=_source_completion(duplicate_source),
        research_plan=artifact,
    )[0]

    assert candidate.prospective_plan_alignment is not None
    assert candidate.prospective_plan_alignment.passed is False
    assert candidate.static_review_approved is False
    assert any(
        "implementation anchor must have exactly one" in item
        for item in candidate.static_review_findings
    )


def test_candidate_audit_families_are_exclusive_and_legacy_shape_is_unchanged(
    tmp_path: Path,
) -> None:
    _artifact, contract, source = _formal_fixture(tmp_path)
    prospective = formal_support.audit_prospective_candidate_plan_alignment(
        candidate_id="c1", source_text=source, contract=contract
    )
    legacy_contract = compile_plan_execution_contract(formal_support._plan())
    legacy = audit_candidate_plan_alignment(
        candidate_id="c1",
        source_text=formal_support._ALIGNED_SOURCE,
        contract=legacy_contract,
    )
    with pytest.raises(OfficialDevelopmentSearchError, match="mutually exclusive"):
        OfficialCandidateRecord(
            candidate_id="c1",
            generation=1,
            interaction_id="formal-c1",
            source_relative_path="candidates/c1/candidate.py",
            source_sha256=prospective.source_sha256,
            static_review_approved=True,
            implementation_summary="model-authored formal implementation",
            approved_plan_hash=contract.approved_plan_hash,
            plan_contract_hash=contract.contract_hash,
            plan_alignment=legacy,
            prospective_plan_alignment=prospective,
        )

    retained = _record("legacy")
    expected = {
        "candidate_id": "legacy",
        "generation": 1,
        "interaction_id": "gen-legacy",
        "source_relative_path": "candidates/legacy/candidate.py",
        "source_sha256": "b" * 64,
        "static_review_approved": True,
        "static_review_findings": [],
        "implementation_summary": "a model-authored equation-discovery method",
        "authored_by_model": True,
    }
    dumped = retained.model_dump(mode="json")
    assert dumped == expected
    assert canonical_model_hash(dumped) == canonical_model_hash(expected)
    assert "prospective_plan_alignment" not in dumped


def test_formal_revision_preserves_and_reaudits_identity_with_direct_contract(
    tmp_path: Path,
) -> None:
    artifact, contract, source = _formal_fixture(tmp_path)
    output = tmp_path / "revision"
    parent = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=output,
        completion=_source_completion(source),
        research_plan=artifact,
    )[0]
    calls: list[list[dict[str, str]]] = []

    revised = revise_official_candidates(
        panel=_gen_panel(),
        budget=_gen_budget(),
        candidates=[parent],
        results=[
            _cell(
                candidate_id=parent.candidate_id,
                system="ode-a",
                nmse=0.4,
                validation=0.3,
            )
        ],
        output_dir=output,
        completion=_source_completion(source, calls),
        research_plan=contract,
    )[0]

    assert revised.plan_alignment is None
    assert revised.prospective_plan_alignment is not None
    assert revised.prospective_plan_alignment.passed is True
    assert revised.static_review_approved is True
    assert "Keep the same two top-level functions" not in calls[0][0]["content"]
    assert contract.implementation_anchor in calls[0][0]["content"]
    assert "three identity guards" in calls[0][0]["content"]
    assert "runtime prospective_execution_binding" in calls[0][0]["content"]
    assert "distinct control and treatment helpers" in calls[0][0]["content"]
    assert "unknown arm" in calls[0][0]["content"]
    revision_prompt = json.loads(calls[0][-1]["content"])
    assert revision_prompt["prospective_source_contract"]["module_constant_name"] == (
        "PROSPECTIVE_EXECUTION_DECLARATION"
    )
    assert revision_prompt["prospective_source_contract"][
        "candidate_alignment_audit_schema_version"
    ] == "candidate-plan-alignment-audit-v3"


def test_formal_revision_cannot_downgrade_to_a_declaration_free_candidate(
    tmp_path: Path,
) -> None:
    artifact, contract, source = _formal_fixture(tmp_path)
    output = tmp_path / "revision-downgrade"
    parent = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=output,
        completion=_source_completion(source),
        research_plan=artifact,
    )[0]
    downgraded = "\n".join(_source_payload()["source_lines"])

    revised = revise_official_candidates(
        panel=_gen_panel(),
        budget=_gen_budget(),
        candidates=[parent],
        results=[
            _cell(
                candidate_id=parent.candidate_id,
                system="ode-a",
                nmse=0.4,
                validation=0.3,
            )
        ],
        output_dir=output,
        completion=_source_completion(downgraded),
        research_plan=contract,
    )[0]

    assert revised.plan_alignment is None
    assert revised.prospective_plan_alignment is not None
    assert revised.prospective_plan_alignment.passed is False
    assert revised.static_review_approved is False


def test_formal_execution_reaudits_source_before_starting_any_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, contract, source = _formal_fixture(tmp_path)
    output = tmp_path / "execution"
    candidate = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=output,
        completion=_source_completion(source),
        research_plan=artifact,
    )[0]
    plan = ResearchPlan.model_validate(contract.approved_plan)
    decision = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="formal prospective scope approved",
        output_dir=tmp_path / "decisions",
    )
    source_path = output / candidate.source_relative_path
    source_path.write_text(source + "\n# post-audit mutation\n", encoding="utf-8")
    process_calls: list[int] = []

    def forbidden_run(*_args: Any, **_kwargs: Any) -> Any:
        process_calls.append(1)
        raise AssertionError("runner must not start before the formal source re-audit")

    monkeypatch.setattr(
        "autoresearch.competition.official_development_search.subprocess.run",
        forbidden_run,
    )
    spec_payload: dict[str, Any] = {
        "attempt_id": "pilot-official-01-ode-a-clean-101",
        "method_kind": "candidate",
        "candidate_id": candidate.candidate_id,
        "stage": "pilot",
        "system_name": "ode-a",
        "data_type": "ode",
        "condition": "clean",
        "seed": 101,
        "data_relative_path": "ode-a/clean.npz",
        "data_sha256": "a" * 64,
        "candidate_source_sha256": candidate.source_sha256,
    }
    spec_payload["spec_hash"] = canonical_model_hash(spec_payload)

    with pytest.raises(
        OfficialDevelopmentSearchError, match="retained prospective audit does not match"
    ):
        execute_official_stage(
            identity=_gen_identity(),
            specs=[OfficialCellSpec.model_validate(spec_payload)],
            candidates=[candidate],
            output_dir=output,
            research_plan=contract,
            plan_decision=decision,
        )
    assert process_calls == []


def test_formal_revision_rejects_a_legacy_contract_downgrade_before_model_call(
    tmp_path: Path,
) -> None:
    artifact, _contract, source = _formal_fixture(tmp_path)
    output = tmp_path / "revision-contract-downgrade"
    parent = generate_official_candidates(
        identity=_gen_identity(),
        panel=_gen_panel(),
        budget=_gen_budget(),
        output_dir=output,
        completion=_source_completion(source),
        research_plan=artifact,
    )[0]
    calls: list[int] = []

    def completion(**_kwargs: Any) -> Any:
        calls.append(1)
        return _stub_result(_source_payload())

    with pytest.raises(PlanExecutionContractError):
        revise_official_candidates(
            panel=_gen_panel(),
            budget=_gen_budget(),
            candidates=[parent],
            results=[
                _cell(
                    candidate_id=parent.candidate_id,
                    system="ode-a",
                    nmse=0.4,
                    validation=0.3,
                )
            ],
            output_dir=output,
            completion=completion,
            research_plan=formal_support._plan(),
        )
    assert calls == []
