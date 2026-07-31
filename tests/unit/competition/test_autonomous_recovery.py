from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    AutonomousBranchEngineError,
    AutonomousConfirmationPanel,
    AutonomousDevelopmentEnvironment,
    AutonomousDevelopmentError,
    AutonomousOriginPolicy,
    AutonomousRecoveryError,
    DevelopmentCellInvocation,
    DevelopmentCellOutcome,
    GateADecision,
    GateAPrimaryComparison,
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchGateAReport,
    build_autonomous_branch_engine_package,
    build_autonomous_development_search_package,
    freeze_autonomous_mdbench_research_plan,
    load_autonomous_branch_engine_package,
    load_autonomous_development_search_package,
    load_autonomous_mdbench_research_plan,
    load_public_autonomous_recovery_plan,
    preregister_mdbench_gate_a,
    preregister_mdbench_gate_a_recovery,
)
from autoresearch.competition.autonomous_development import _runner_spec_payload
from autoresearch.competition.autonomous_engine import (
    review_autonomous_candidate_source,
    run_autonomous_candidate_capability_harness,
)
from autoresearch.competition.autonomous_recovery import (
    AUTONOMOUS_RECOVERY_SOURCE_SPECS,
    AutonomousRecoverySourceSpec,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.planning import MDBENCH_REVISION
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult

_PARENT_ODE_SYSTEMS = (
    "harmonic-oscillator",
    "van-der-pol-oscillator",
    "lotka-volterra-simple",
    "duffing-equation",
    "brusselator",
    "sir-infection",
    "lorenz-equations-chaotic",
    "rössler-attractor-chaotic",
    "glycolytic-oscillator",
    "autocatalytic-gene-switching",
)
_PARENT_PDE_SYSTEMS = ("advection1d", "burgers", "kdv", "kuramoto_sivishinky")
_RECOVERY_ODE_SYSTEMS = (
    "harmonic-oscillator-damping",
    "lotka-volterra-competition",
    "damped-double-well-oscillator",
    "seir-infection",
    "maxwell-bloch-equations",
    "rössler-attractor-periodic",
    "chen-lee-attractor",
    "lorenz-equations-complex-periodic",
    "apoptosis-model",
    "binocular-rivalry-adaptation",
)
_RECOVERY_PDE_SYSTEMS = (
    "advection1d",
    "burgers",
    "heat_soil_uniform_1d_p1",
    "nls",
)
_UNUSED_ODE_SYSTEMS = tuple(f"fixture-untouched-ode-{index:02d}" for index in range(43))
_UNUSED_PDE_SYSTEMS = tuple(f"fixture_untouched_pde_{index:02d}" for index in range(8))


def test_plan_freezes_autonomous_origin_and_disjoint_sealed_panel(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    output_dir = tmp_path / "autonomous-plan"

    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        output_dir,
        source_fetcher=_source_fetcher,
    )

    assert plan.model_interaction_count == 0
    assert plan.generated_candidate_count == 0
    assert plan.result_record_count == 0
    assert plan.manuscript_count == 0
    assert plan.candidate_hypotheses == ()
    assert plan.development_generation_authorized is True
    assert plan.development_execution_authorized is False
    assert plan.confirmation_access_authorized is False
    assert plan.origin_policy.fixed_candidate_catalogue_allowed is False
    assert plan.origin_policy.human_authored_candidate_code_allowed is False
    assert plan.origin_policy.model_generated_exact_code_required is True
    assert plan.origin_policy.manuscript_generated_inside_same_ledger is True
    assert plan.search_policy.minimum_mechanism_families == 3
    assert plan.search_policy.generation_count == 2
    assert len(plan.evidence_sources) == 12
    assert {source.domain for source in plan.evidence_sources} == {
        "autonomous_research",
        "equation_discovery",
    }
    assert len(plan.development_panel.systems) == 14
    assert sum(item.data_type == "ode" for item in plan.development_panel.systems) == 10
    assert sum(item.data_type == "pde" for item in plan.development_panel.systems) == 4

    confirmation = AutonomousConfirmationPanel.model_validate_json(
        Path(plan.confirmation_commitment.sealed_panel_path).read_text(encoding="utf-8")
    )
    assert confirmation.research_agent_read_allowed is False
    assert len(confirmation.systems) == 14
    assert sum(item.data_type == "ode" for item in confirmation.systems) == 10
    assert sum(item.data_type == "pde" for item in confirmation.systems) == 4
    development_keys = {
        (item.data_type, item.system_name) for item in plan.development_panel.systems
    }
    confirmation_keys = {
        (item.data_type, item.system_name) for item in confirmation.systems
    }
    prior_keys = {
        tuple(item.split("/", maxsplit=1)) for item in plan.excluded_prior_systems
    }
    assert not development_keys & confirmation_keys
    assert not (development_keys | confirmation_keys) & prior_keys
    assert {
        item.system_name
        for item in plan.development_panel.systems + confirmation.systems
        if item.data_type == "pde"
    } == set(_UNUSED_PDE_SYSTEMS)
    markdown = Path(plan.markdown_path).read_text(encoding="utf-8")
    assert all(item.system_name not in markdown for item in confirmation.systems)

    assert load_autonomous_mdbench_research_plan(plan.output_path) == plan

    def _must_not_refetch(
        _spec: AutonomousRecoverySourceSpec,
        _timeout_seconds: int,
    ) -> tuple[bytes, str, int]:
        raise AssertionError("idempotent plan load must not refetch primary sources")

    assert (
        freeze_autonomous_mdbench_research_plan(
            *inputs,
            output_dir,
            source_fetcher=_must_not_refetch,
        )
        == plan
    )


def test_plan_rejects_contract_and_snapshot_tampering(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    plan_path = Path(plan.output_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["development_execution_authorized"] = True
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AutonomousRecoveryError, match="cannot load autonomous recovery plan"):
        load_autonomous_mdbench_research_plan(plan_path)

    payload["development_execution_authorized"] = False
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    source_path = plan_path.parent / plan.evidence_sources[0].snapshot_relative_path
    source_path.write_text("tampered source", encoding="utf-8")

    with pytest.raises(AutonomousRecoveryError, match="source snapshot hash mismatch"):
        load_autonomous_mdbench_research_plan(plan_path)


def test_plan_rejects_result_markers_and_unverified_sources(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    output_dir = tmp_path / "autonomous-plan"
    (output_dir / "results").mkdir(parents=True)

    with pytest.raises(AutonomousRecoveryError, match="result or candidate marker"):
        freeze_autonomous_mdbench_research_plan(
            *inputs,
            output_dir,
            source_fetcher=_source_fetcher,
        )

    def _missing_marker(
        spec: AutonomousRecoverySourceSpec,
        _timeout_seconds: int,
    ) -> tuple[bytes, str, int]:
        return b"<html>wrong paper</html>", spec.url, 200

    with pytest.raises(AutonomousRecoveryError, match="marker/status failed"):
        freeze_autonomous_mdbench_research_plan(
            *inputs,
            tmp_path / "bad-sources",
            source_fetcher=_missing_marker,
        )


def test_origin_policy_rejects_hidden_human_research() -> None:
    with pytest.raises(ValidationError, match="forbids hidden human"):
        AutonomousOriginPolicy(fixed_candidate_catalogue_allowed=True)
    with pytest.raises(ValidationError, match="multiple families and generations"):
        AutonomousOriginPolicy(minimum_mechanism_families=1)


def test_branch_engine_generates_exact_code_and_passes_all_capabilities(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    sealed_path = Path(plan.confirmation_commitment.sealed_panel_path)
    sealed_path.unlink()
    assert load_public_autonomous_recovery_plan(plan.output_path) == plan
    completion = _ScriptedAutonomousCompletion(
        unsupported_json_schema=True,
        structured_failure_schema_name="autonomous_portfolio_frame",
        structured_failure_sequence=("empty_content", "invalid_json"),
        overlong_hypothesis_candidate="branch-07",
        trailing_normalized_candidate="branch-08",
    )
    output_dir = tmp_path / "branch-engine"

    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=completion,
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert package.generated_candidate_count == 8
    assert package.model_interaction_count == 19
    assert package.provider_request_attempt_count == 40
    assert package.mechanism_family_count >= 3
    assert package.provenance_gate_passed is True
    assert package.capability_gate_passed is True
    assert package.development_execution_authorized is True
    assert package.confirmation_identity_read_count == 0
    assert package.objective_official_development_result_count == 0
    assert package.search_freeze_receipt_created is False
    assert package.mechanism_cycle_record_count == 0
    assert package.mechanistic_research_loop.llm_self_score_is_evidence is False
    assert package.mechanistic_research_loop.prose_only_mechanism_claim_allowed is False
    assert package.capability_output_adapter_id == "row-major-flat-v1"
    assert len(package.capability_output_adapter_contract_sha256) == 64
    assert len(package.capability_runner_sha256) == 64
    assert package.next_required_task == "265.3"
    assert package.stage_budget_audit.passed is True
    assert package.contamination_audit.passed is True
    assert len(package.comparative_memory) == 8
    assert all(item.llm_self_score is None for item in package.comparative_memory)
    assert all(branch.passed for branch in package.branches)
    assert all(
        tuple(result.capability_id for result in branch.revisions[-1].sandbox_observation.capability_results)
        == ("ode", "pde_1d", "pde_2d", "pde_3d", "multi_field")
        for branch in package.branches
        if branch.revisions[-1].sandbox_observation is not None
    )
    source_hashes = {
        branch.revisions[-1].source_sha256 for branch in package.branches
    }
    assert len(source_hashes) == 8
    assert len(list((output_dir / "interactions").glob("*.json-schema-fallback.json"))) == 19
    retry_paths = sorted(
        (output_dir / "interactions").glob("*.structured-output-retry-*.json")
    )
    assert len(retry_paths) == 2
    invalid_retry = json.loads(retry_paths[1].read_text(encoding="utf-8"))
    assert invalid_retry["error_kind"] == "invalid_json"
    assert invalid_retry["response_text_logged"] is True
    assert invalid_retry["finish_reason"] == "length"
    assert package.model_interactions[0].provider_request_attempt_count == 4
    normalized_interactions = [
        item
        for item in package.model_interactions
        if item.response_transport_normalization
        == "discarded_trailing_closing_delimiters"
    ]
    assert len(normalized_interactions) == 1
    assert normalized_interactions[0].response_normalization_suffix == "]"
    assert normalized_interactions[0].response_text.endswith("]")
    assert load_autonomous_branch_engine_package(package.output_path) == package

    first_source = output_dir / package.branches[0].revisions[0].source_relative_path
    first_source.write_text("tampered", encoding="utf-8")
    with pytest.raises(AutonomousBranchEngineError, match="candidate source hash mismatch"):
        load_autonomous_branch_engine_package(package.output_path)


def test_branch_engine_closes_exhausted_structured_output_transaction(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    output_dir = tmp_path / "branch-engine"
    completion = _ScriptedAutonomousCompletion(
        unsupported_json_schema=True,
        structured_failure_schema_name="autonomous_candidate_implementation",
        structured_failure_sequence=(
            "empty_content",
            "invalid_json",
            "invalid_json",
        ),
    )

    with pytest.raises(LLMClientError, match="not valid JSON"):
        build_autonomous_branch_engine_package(
            plan.output_path,
            output_dir,
            completion=completion,
            source_fetcher=_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )

    terminal_path = output_dir / "interactions" / (
        "branch-01-revision-01.json-object.structured-output-terminal-failure.json"
    )
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    assert terminal["terminal_attempt_index"] == 3
    assert terminal["structured_retry_budget"] == 2
    assert terminal["error_kind"] == "invalid_json"
    assert terminal["response_text_logged"] is True
    assert terminal["terminal_action"] == "transaction_closed_no_automatic_retry"

    def _unexpected_provider_call(**_kwargs: object) -> LLMJsonCompletionResult:
        raise AssertionError("closed provider transaction was retried")

    with pytest.raises(
        AutonomousBranchEngineError,
        match="previously exhausted its structured-output budget",
    ):
        build_autonomous_branch_engine_package(
            plan.output_path,
            output_dir,
            completion=_unexpected_provider_call,
            source_fetcher=_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )


def test_branch_engine_closes_exhausted_transient_transport_transaction(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    output_dir = tmp_path / "branch-engine"
    call_count = 0

    def _always_timeout(**_kwargs: object) -> LLMJsonCompletionResult:
        nonlocal call_count
        call_count += 1
        raise LLMClientError("LLM API request failed: WinError 10060 timeout")

    with pytest.raises(LLMClientError, match="WinError 10060"):
        build_autonomous_branch_engine_package(
            plan.output_path,
            output_dir,
            completion=_always_timeout,
            source_fetcher=_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )

    assert call_count == 3
    retry_paths = sorted(
        (output_dir / "interactions").glob(
            "portfolio-frame-01.provider-transport-retry-*.json"
        )
    )
    assert len(retry_paths) == 2
    terminal_path = (
        output_dir
        / "interactions"
        / "portfolio-frame-01.provider-transport-terminal-failure.json"
    )
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    assert terminal["retry_index"] == 3
    assert terminal["transient_retry_budget"] == 2
    assert terminal["terminal"] is True

    def _unexpected_provider_call(**_kwargs: object) -> LLMJsonCompletionResult:
        raise AssertionError("closed transport transaction was retried")

    with pytest.raises(
        AutonomousBranchEngineError,
        match="previously exhausted its transient-transport budget",
    ):
        build_autonomous_branch_engine_package(
            plan.output_path,
            output_dir,
            completion=_unexpected_provider_call,
            source_fetcher=_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )


def test_branch_engine_retains_model_only_technical_repair(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    package = build_autonomous_branch_engine_package(
        plan.output_path,
        tmp_path / "branch-engine",
        completion=_ScriptedAutonomousCompletion(bad_first_branch=True),
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    repaired = package.branches[0]
    assert len(repaired.revisions) == 2
    assert repaired.revisions[0].passed is False
    assert "static:import_not_allowlisted" in repaired.revisions[0].failure_codes
    assert repaired.revisions[1].repair_kind == "model_technical_repair"
    assert repaired.revisions[1].code_side_repair is False
    assert repaired.passed is True
    assert package.model_interaction_count == 18
    assert len(package.comparative_memory) == 9
    assert package.comparative_memory[0].structured_failure_codes


def test_branch_engine_rejects_unchanged_repairs_and_uses_bounded_third_repair(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    output_dir = tmp_path / "branch-engine"
    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=_ScriptedAutonomousCompletion(
            bad_first_branch=True,
            unchanged_first_repair=True,
            unchanged_second_repair=True,
        ),
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    repaired = package.branches[0]
    assert len(repaired.revisions) == 4
    assert repaired.revisions[0].source_sha256 == repaired.revisions[1].source_sha256
    assert repaired.revisions[1].source_sha256 == repaired.revisions[2].source_sha256
    assert "static:unchanged_repair" in repaired.revisions[1].failure_codes
    assert "static:unchanged_repair" in repaired.revisions[2].failure_codes
    assert repaired.revisions[3].source_sha256 != repaired.revisions[2].source_sha256
    assert repaired.revisions[3].passed is True
    assert repaired.passed is True
    assert package.stage_budget_audit.maximum_revisions_per_candidate == 6
    repair_interaction = json.loads(
        (
            output_dir / "interactions" / "branch-01-revision-04.json"
        ).read_text(encoding="utf-8")
    )
    repair_context = json.loads(repair_interaction["messages"][-1]["content"])
    assert repair_context["target_revision_number"] == 4
    assert repair_context["mandatory_technical_repair_checklist"][
        "source_sha256_must_change"
    ] is True
    assert repair_context["concise_security_contract"]["zero_while_nodes"] is True
    assert any(
        "flat_values" in hint
        for hint in repair_context["generic_non_scientific_repair_hints"]
    )


def test_branch_engine_returns_granular_capability_failures_to_model(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    output_dir = tmp_path / "branch-engine"
    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=_ScriptedAutonomousCompletion(zero_complexity_first_branch=True),
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    repaired = package.branches[0]
    assert repaired.passed is True
    assert "capability:ode:positive_complexity" in repaired.revisions[0].failure_codes
    repair_interaction = json.loads(
        (
            output_dir / "interactions" / "branch-01-revision-02.json"
        ).read_text(encoding="utf-8")
    )
    repair_context = json.loads(repair_interaction["messages"][-1]["content"])
    assert "capability:ode:positive_complexity" in repair_context[
        "machine_failure_codes"
    ]
    prior_source_path = output_dir / repaired.revisions[0].source_relative_path
    assert repair_context["prior_source_text"] == prior_source_path.read_text(
        encoding="utf-8"
    )
    assert repair_context["prior_source_sha256"] == repaired.revisions[0].source_sha256
    assert repair_context["prior_sandbox_observation"]["passed"] is False
    checklist = repair_context["mandatory_technical_repair_checklist"]
    assert checklist["eliminate_every_previous_failure_code"] is True
    failed_ode = next(
        item
        for item in checklist["failed_capability_diagnostics"]
        if item["capability_id"] == "ode"
    )
    assert failed_ode["expected_output_shape"] == [7, 1]
    assert failed_ode["observed_output_shape"] == [7, 1]
    assert failed_ode["expected_equation_count"] == 1
    assert repair_context["official_benchmark_scores_visible"] is False


def test_branch_engine_retains_all_hypothesis_repair_constraints(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    completion = _ScriptedAutonomousCompletion(
        duplicate_then_overlong_hypothesis_candidate="branch-05"
    )
    output_dir = tmp_path / "branch-engine"

    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=completion,
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert package.development_execution_authorized is True
    assert package.model_interaction_count == 19
    assert completion.hypothesis_calls["branch-05"] == 3
    repair_interaction = json.loads(
        (
            output_dir
            / "interactions"
            / "portfolio-branch-05-attempt-03.json"
        ).read_text(encoding="utf-8")
    )
    assert "exactly duplicates branch-04" in repair_interaction["messages"][-1][
        "content"
    ]
    assert "hypothesis: String should have at most 1200 characters" in (
        repair_interaction["messages"][-1]["content"]
    )
    assert package.branches[4].candidate.title != package.branches[3].candidate.title


def test_branch_engine_gives_late_hypothesis_repair_exact_source_domain_contract(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    completion = _ScriptedAutonomousCompletion(
        insufficient_source_candidate="branch-07"
    )
    output_dir = tmp_path / "branch-engine"

    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=completion,
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert package.development_execution_authorized is True
    assert completion.hypothesis_calls["branch-07"] == 4
    repair_interaction = json.loads(
        (
            output_dir
            / "interactions"
            / "portfolio-branch-07-attempt-04.json"
        ).read_text(encoding="utf-8")
    )
    repair_context = json.loads(repair_interaction["messages"][-1]["content"])
    assert repair_context["prior_hypothesis"]["source_ids"] == [
        "ai-research-agents",
        "wsindy",
    ]
    assert repair_context["source_domain_contract"][
        "minimum_equation_discovery_source_count"
    ] == 2
    assert set(
        repair_context["source_domain_contract"][
            "allowed_equation_discovery_source_ids"
        ]
    ) >= {"wsindy", "ensemble-sindy"}
    assert repair_context["remaining_attempts_after_this"] == 1


def test_branch_engine_resumes_hash_bound_transactions_after_provider_failure(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    completion = _ScriptedAutonomousCompletion(
        unsupported_json_schema=True,
        transient_failure_candidate="branch-04",
    )
    output_dir = tmp_path / "branch-engine"

    with pytest.raises(LLMClientError, match="temporary provider outage"):
        build_autonomous_branch_engine_package(
            plan.output_path,
            output_dir,
            completion=completion,
            source_fetcher=_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )

    committed_before = {
        path.relative_to(output_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output_dir.rglob("*.json")
        if "branch-04" not in path.as_posix()
    }
    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=completion,
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert package.development_execution_authorized is True
    assert package.model_interaction_count == 17
    assert committed_before
    assert all(
        hashlib.sha256((output_dir / relative).read_bytes()).hexdigest() == digest
        for relative, digest in committed_before.items()
    )


def test_branch_engine_replays_transient_transport_without_scientific_revision(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    scripted = _ScriptedAutonomousCompletion()
    branch_request_hashes: list[str] = []

    def _timeout_once(**kwargs: object) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        if kwargs["response_schema_name"] == "autonomous_candidate_implementation":
            context = json.loads(messages[1]["content"])
            if context["candidate"]["candidate_id"] == "branch-04":
                branch_request_hashes.append(
                    canonical_model_hash({"messages": messages})
                )
                if len(branch_request_hashes) == 1:
                    raise LLMClientError(
                        "LLM API request failed: timed out while connecting"
                    )
        return scripted(**kwargs)

    output_dir = tmp_path / "branch-engine"
    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=_timeout_once,
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert package.development_execution_authorized is True
    assert branch_request_hashes[0] == branch_request_hashes[1]
    interaction = next(
        item
        for item in package.model_interactions
        if item.interaction_id == "branch-04-revision-01"
    )
    assert interaction.provider_request_attempt_count == 2
    assert len(interaction.provider_transport_retry_relative_paths) == 1
    assert interaction.provider_retry_relative_paths == ()
    retry_path = output_dir / interaction.provider_transport_retry_relative_paths[0]
    retry = json.loads(retry_path.read_text(encoding="utf-8"))
    assert retry["error_kind"] == "timeout"
    assert retry["retry_strategy"] == (
        "replay_identical_request_without_scientific_revision"
    )
    assert retry["terminal"] is False
    assert package.provider_request_attempt_count == 18
    assert load_autonomous_branch_engine_package(package.output_path) == package


def test_branch_engine_resumes_committed_revision_before_branch_commit(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    output_dir = tmp_path / "branch-engine"

    def _clock() -> datetime:
        return datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    original = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=_ScriptedAutonomousCompletion(),
        source_fetcher=_source_fetcher,
        clock=_clock,
    )
    branch_path = output_dir / "branches" / "branch-01" / "branch.json"
    package_path = output_dir / "autonomous-branch-engine-package.json"
    revision_root = output_dir / "branches" / "branch-01" / "revision-01"
    committed_before = {
        path.relative_to(output_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in revision_root.rglob("*")
        if path.is_file()
    }
    branch_path.unlink()
    package_path.unlink()

    def _unexpected_provider_call(**_kwargs: object) -> LLMJsonCompletionResult:
        raise AssertionError("committed revision resume called the model provider")

    resumed = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=_unexpected_provider_call,
        source_fetcher=_source_fetcher,
        clock=_clock,
    )

    assert resumed.package_hash == original.package_hash
    assert branch_path.is_file()
    assert committed_before
    assert all(
        hashlib.sha256((output_dir / relative).read_bytes()).hexdigest() == digest
        for relative, digest in committed_before.items()
    )


def test_branch_engine_resumes_hash_bound_literature_after_source_failure(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    output_dir = tmp_path / "branch-engine"
    failing_source_id = AUTONOMOUS_RECOVERY_SOURCE_SPECS[3].source_id
    calls: list[str] = []
    failure_pending = True

    def _flaky_source_fetcher(
        spec: AutonomousRecoverySourceSpec,
        timeout_seconds: int,
    ) -> tuple[bytes, str, int]:
        nonlocal failure_pending
        calls.append(spec.source_id)
        if spec.source_id == failing_source_id and failure_pending:
            failure_pending = False
            raise AutonomousBranchEngineError("temporary source outage")
        return _source_fetcher(spec, timeout_seconds)

    with pytest.raises(AutonomousBranchEngineError, match="temporary source outage"):
        build_autonomous_branch_engine_package(
            plan.output_path,
            output_dir,
            completion=_ScriptedAutonomousCompletion(),
            source_fetcher=_flaky_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )

    committed_before = {
        path.relative_to(output_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (output_dir / "literature").iterdir()
        if path.stem.split(".", maxsplit=1)[0]
        in {item.source_id for item in AUTONOMOUS_RECOVERY_SOURCE_SPECS[:3]}
    }
    package = build_autonomous_branch_engine_package(
        plan.output_path,
        output_dir,
        completion=_ScriptedAutonomousCompletion(),
        source_fetcher=_flaky_source_fetcher,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert package.development_execution_authorized is True
    assert committed_before
    assert calls.count(AUTONOMOUS_RECOVERY_SOURCE_SPECS[0].source_id) == 1
    assert calls.count(failing_source_id) == 2
    assert all(
        hashlib.sha256((output_dir / relative).read_bytes()).hexdigest() == digest
        for relative, digest in committed_before.items()
    )


def test_branch_engine_rejects_fixed_or_untraceable_portfolio(tmp_path: Path) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )

    with pytest.raises(AutonomousBranchEngineError, match="valid autonomous portfolio"):
        build_autonomous_branch_engine_package(
            plan.output_path,
            tmp_path / "branch-engine",
            completion=_ScriptedAutonomousCompletion(invalid_portfolio=True),
            source_fetcher=_source_fetcher,
            clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )


def test_candidate_security_and_multidimensional_harness(tmp_path: Path) -> None:
    unsafe = review_autonomous_candidate_source(
        "import requests\ndef discover_equations(payload):\n    return {}\n"
    )
    assert unsafe.approved is False
    assert "import_not_allowlisted" in {item.code for item in unsafe.findings}
    oversized_source = (
        "def discover_equations(payload):\n"
        + "".join(f"    value_{index} = {index}\n" for index in range(1_500))
        + "    return {'status': 'ok'}\n"
    )
    oversized_review = review_autonomous_candidate_source(oversized_source)
    assert oversized_review.approved is False
    assert "ast_size" in {item.code for item in oversized_review.findings}
    bounded_while = review_autonomous_candidate_source(
        '''def discover_equations(payload):
    n = len(payload["values"])
    m = 1
    while m < n:
        m *= 2
    bit = m >> 1
    j = m - 1
    while j & bit:
        bit >>= 1
    length = 2
    while length <= m:
        length *= 2
    shifted = 1
    while shifted <= m:
        shifted <<= 1
    nested = payload["values"]
    while isinstance(nested, list):
        nested = nested[0]
    equations = []
    field_count = int(payload["field_count"])
    while len(equations) < field_count:
        equations.append("du/dt = 0")
    return {"status": "ok", "m": m, "bit": bit, "length": length, "shifted": shifted, "nested": nested, "equations": equations}
'''
    )
    assert bounded_while.approved is True
    unbounded_while = review_autonomous_candidate_source(
        '''def discover_equations(payload):
    value = []
    while isinstance(value, list):
        value = value[0] if value else []
    return {"status": "ok"}
'''
    )
    assert unbounded_while.approved is False
    assert "unbounded_loop" in {item.code for item in unbounded_while.findings}
    safe_locals_membership = review_autonomous_candidate_source(
        '''def discover_equations(payload):
    value = 1.0
    return {"status": "ok", "value": value if "value" in locals() else 0.0}
'''
    )
    assert safe_locals_membership.approved is True
    exposed_locals_mapping = review_autonomous_candidate_source(
        '''def discover_equations(payload):
    return {"status": "ok", "value": locals().get("value", 0.0)}
'''
    )
    assert exposed_locals_mapping.approved is False
    assert "dynamic_execution" in {
        item.code for item in exposed_locals_mapping.findings
    }
    source = _candidate_source("branch-99")
    review = review_autonomous_candidate_source(source)
    assert review.approved is True

    _spec, episode, observation = run_autonomous_candidate_capability_harness(
        run_id="task2652-unit",
        episode_id="branch-99-unit",
        output_dir=tmp_path / "harness",
        source_text=source,
        static_review=review,
        clock=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert episode.final_outcome.status.value == "succeeded"
    assert observation is not None and observation.passed
    assert all(result.derivative_nmse is not None for result in observation.capability_results)
    assert observation.output_adapter_id == "row-major-flat-v1"
    assert observation.candidate_source_modified_by_adapter is False
    assert observation.scientific_numeric_transform_count == 0
    assert all(
        result.output_adapter_id == "row-major-flat-v1"
        and result.candidate_output_layout == "row_major_flat"
        and result.adapter_reconstructed
        for result in observation.capability_results
    )
    input_payload = json.loads(
        (tmp_path / "harness" / "process" / "input.json").read_text(
            encoding="utf-8"
        )
    )
    for fixture in input_payload["fixtures"]:
        expected_count = math.prod(fixture["shape"])
        assert fixture["payload"]["value_shape"] == fixture["shape"]
        assert len(fixture["payload"]["flat_values"]) == expected_count
        assert len(fixture["perturbed_payload"]["flat_values"]) == expected_count
        assert all(
            len(axis) >= 3
            for axis_name, axis in fixture["payload"]["coordinate_axes"].items()
            if axis_name != "t"
        )

    exception_source = '''def discover_equations(payload):
    raise ValueError("model-authored fixture failure")
'''
    exception_review = review_autonomous_candidate_source(exception_source)
    assert exception_review.approved is True
    _, exception_episode, exception_observation = (
        run_autonomous_candidate_capability_harness(
            run_id="task2652-unit-exception",
            episode_id="branch-98-unit",
            output_dir=tmp_path / "exception-harness",
            source_text=exception_source,
            static_review=exception_review,
            clock=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )
    )
    assert exception_episode.final_outcome.status.value == "failed"
    assert exception_observation is not None and not exception_observation.passed
    assert all(
        result.error_type == "ValueError"
        and result.error_message == "model-authored fixture failure"
        and result.observed_output_shape is None
        and result.expected_output_shape
        and result.expected_equation_count == result.field_count
        and result.traceback_excerpt is not None
        and "candidate.py" in result.traceback_excerpt
        and 'raise ValueError("model-authored fixture failure")'
        in result.traceback_excerpt
        for result in exception_observation.capability_results
    )

    wrong_length_source = '''def discover_equations(payload):
    return {
        "status": "ok",
        "derivative_prediction_flat": list(payload["flat_values"][:-1]),
        "equations": ["du/dt = 0"] * int(payload["field_count"]),
        "complexity": 1,
        "diagnostics": {},
    }
'''
    wrong_length_review = review_autonomous_candidate_source(wrong_length_source)
    assert wrong_length_review.approved is True
    _, wrong_length_episode, wrong_length_observation = (
        run_autonomous_candidate_capability_harness(
            run_id="task2652-unit-adapter-mismatch",
            episode_id="branch-97-unit",
            output_dir=tmp_path / "adapter-mismatch-harness",
            source_text=wrong_length_source,
            static_review=wrong_length_review,
            clock=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )
    )
    assert wrong_length_episode.final_outcome.status.value == "failed"
    assert wrong_length_observation is not None and not wrong_length_observation.passed
    assert all(
        result.error_type == "CapabilityOutputAdapterError"
        and "does not match fixture-owned element count" in (result.error_message or "")
        and result.candidate_output_layout == "invalid"
        and not result.adapter_reconstructed
        for result in wrong_length_observation.capability_results
    )


def test_autonomous_development_runs_complete_mocked_ophis_search(
    tmp_path: Path,
) -> None:
    inputs = _formal_negative_cycles(tmp_path)
    plan = freeze_autonomous_mdbench_research_plan(
        *inputs,
        tmp_path / "autonomous-plan",
        source_fetcher=_source_fetcher,
    )
    Path(plan.confirmation_commitment.sealed_panel_path).unlink()
    completion = _ScriptedAutonomousCompletion()
    branch_engine = build_autonomous_branch_engine_package(
        plan.output_path,
        tmp_path / "branch-engine",
        completion=completion,
        source_fetcher=_source_fetcher,
        clock=lambda: datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
    )
    manifest = MDBenchArchiveManifest.model_validate_json(
        Path(plan.lineage.archive_manifest_path).read_text(encoding="utf-8")
    )
    _materialize_manifest_artifacts(manifest)
    environment = _development_environment_fixture()
    output_dir = tmp_path / "autonomous-development"
    package = build_autonomous_development_search_package(
        plan.output_path,
        branch_engine.output_path,
        output_dir,
        completion=completion,
        environment_probe=lambda _image: environment,
        cell_executor=_development_cell_executor_fixture,
        clock=lambda: datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert package.identity.numeric_payload_read_count_before_identity == 0
    assert package.identity.confirmation_identity_read_count == 0
    assert len(package.identity.pilot_units) == 9
    assert len(package.identity.mechanism_units) == 6
    assert len(package.identity.full_units) == 84
    assert len(package.candidates) == 12
    assert package.model_interaction_count == 4
    assert package.official_development_result_count == 348
    assert package.baseline_result_count == 84
    assert sum(
        result.method_kind == "candidate" and result.stage == "pilot"
        for result in package.results
    ) == 72
    assert sum(
        result.method_kind == "candidate" and result.stage == "mechanism"
        for result in package.results
    ) == 24
    assert sum(
        result.method_kind == "candidate" and result.stage == "full"
        for result in package.results
    ) == 252
    assert all(result.status == "succeeded" for result in package.results)
    assert package.executed_mechanism_cycle_count == 4
    assert package.supported_mechanism_cycle_count == 4
    assert all(cycle.frozen_before_execution for cycle in package.prospective_cycles)
    assert all(
        cycle.child_official_result_count_at_freeze == 0
        for cycle in package.prospective_cycles
    )
    assert all(
        outcome.unsupported_mechanism_claim_count == 0
        for outcome in package.cycle_outcomes
    )
    assert package.selection.selected_candidate_id == "branch-09"
    assert package.selection.qualified_for_confirmation is True
    assert package.selection.decision == "search_frozen"
    assert package.search_freeze_receipt_created is True
    assert package.search_freeze_receipt is not None
    assert package.confirmation_identity_read_count == 0
    assert package.confirmation_result_count == 0
    assert package.post_start_human_scientific_decision_count == 0
    assert package.publication_ready is False
    assert package.next_required_task == "265.4"
    assert load_autonomous_development_search_package(package.output_path) == package

    def _must_not_execute(**_kwargs: object) -> object:
        raise AssertionError("terminal development replay must not call a model")

    assert (
        build_autonomous_development_search_package(
            plan.output_path,
            branch_engine.output_path,
            output_dir,
            completion=_must_not_execute,
            environment_probe=lambda _image: (_ for _ in ()).throw(
                AssertionError("terminal replay must not probe Docker")
            ),
            cell_executor=lambda _invocation: (_ for _ in ()).throw(
                AssertionError("terminal replay must not execute a cell")
            ),
        )
        == package
    )

    first_result = package.results[0]
    Path(first_result.stdout_path).write_text("tampered", encoding="utf-8")
    with pytest.raises(AutonomousDevelopmentError, match="log hash mismatch"):
        load_autonomous_development_search_package(package.output_path)


class _ScriptedAutonomousCompletion:
    def __init__(
        self,
        *,
        bad_first_branch: bool = False,
        unchanged_first_repair: bool = False,
        unchanged_second_repair: bool = False,
        invalid_portfolio: bool = False,
        unsupported_json_schema: bool = False,
        transient_failure_candidate: str | None = None,
        structured_failure_schema_name: str | None = None,
        structured_failure_sequence: tuple[Literal["empty_content", "invalid_json"], ...] = (),
        overlong_hypothesis_candidate: str | None = None,
        duplicate_first_hypothesis_candidate: str | None = None,
        duplicate_then_overlong_hypothesis_candidate: str | None = None,
        insufficient_source_candidate: str | None = None,
        zero_complexity_first_branch: bool = False,
        trailing_normalized_candidate: str | None = None,
    ) -> None:
        self.bad_first_branch = bad_first_branch
        self.unchanged_first_repair = unchanged_first_repair
        self.unchanged_second_repair = unchanged_second_repair
        self.invalid_portfolio = invalid_portfolio
        self.unsupported_json_schema = unsupported_json_schema
        self.transient_failure_candidate = transient_failure_candidate
        self.structured_failure_schema_name = structured_failure_schema_name
        self.structured_failure_sequence = structured_failure_sequence
        self.structured_failure_index = 0
        self.overlong_hypothesis_candidate = overlong_hypothesis_candidate
        self.duplicate_first_hypothesis_candidate = (
            duplicate_first_hypothesis_candidate
        )
        self.duplicate_then_overlong_hypothesis_candidate = (
            duplicate_then_overlong_hypothesis_candidate
        )
        self.insufficient_source_candidate = insufficient_source_candidate
        self.zero_complexity_first_branch = zero_complexity_first_branch
        self.trailing_normalized_candidate = trailing_normalized_candidate
        self.hypothesis_calls: dict[str, int] = {}
        self.implementation_calls: dict[str, int] = {}

    def __call__(self, **kwargs: object) -> LLMJsonCompletionResult:
        if self.unsupported_json_schema and kwargs.get("response_schema") is not None:
            raise LLMClientError("LLM API HTTP 400: response_format type is unavailable")
        schema_name = str(kwargs["response_schema_name"])
        if kwargs.get("response_schema") is None and (
            schema_name == self.structured_failure_schema_name
            and self.structured_failure_index < len(self.structured_failure_sequence)
        ):
            failure_kind = self.structured_failure_sequence[
                self.structured_failure_index
            ]
            self.structured_failure_index += 1
            if failure_kind == "empty_content":
                raise LLMClientError(
                    "LLM API message content is empty",
                    response_text="",
                    response_usage={"completion_tokens": 4000},
                    finish_reason="length",
                )
            raise LLMClientError(
                "LLM JSON completion was not valid JSON: Unterminated string",
                response_text='{"candidate": "truncated',
                response_usage={"completion_tokens": 8000},
                finish_reason="length",
            )
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        if schema_name == "autonomous_portfolio_frame":
            payload = _portfolio_frame_payload(invalid=self.invalid_portfolio)
        elif schema_name == "autonomous_candidate_hypothesis":
            context = json.loads(messages[1]["content"])
            candidate_id = str(context["candidate_slot"])
            hypothesis_count = self.hypothesis_calls.get(candidate_id, 0) + 1
            self.hypothesis_calls[candidate_id] = hypothesis_count
            payload = _candidate_hypothesis_payload(
                candidate_id,
                invalid=self.invalid_portfolio,
            )
            if (
                candidate_id
                in {
                    self.duplicate_first_hypothesis_candidate,
                    self.duplicate_then_overlong_hypothesis_candidate,
                }
                and hypothesis_count == 1
            ):
                payload = _candidate_hypothesis_payload(
                    "branch-04",
                    invalid=self.invalid_portfolio,
                )
                payload["candidate_id"] = candidate_id
            if (
                candidate_id == self.duplicate_then_overlong_hypothesis_candidate
                and hypothesis_count == 2
            ):
                payload["hypothesis"] = "x" * 1213
            if (
                candidate_id == self.overlong_hypothesis_candidate
                and hypothesis_count <= 2
            ):
                payload["hypothesis"] = "x" * 1213
            if (
                candidate_id == self.insufficient_source_candidate
                and hypothesis_count <= 3
            ):
                payload["source_ids"] = ["ai-research-agents", "wsindy"]
        elif schema_name == "autonomous_mechanism_intervention":
            context = json.loads(messages[1]["content"])
            cycle_id = str(context["cycle_id"])
            parent_id = str(context["parent_candidate_id"])
            candidate_id = str(context["child_candidate_id"])
            payload = {
                "cycle_id": cycle_id,
                "parent_candidate_id": parent_id,
                "child_candidate_id": candidate_id,
                "mechanism_family": "train-context residual operator",
                "mechanism_hypothesis": (
                    "A train-context residual term should make the derivative estimate "
                    "responsive to training evidence and reduce paired derivative NMSE."
                ),
                "predicted_directional_effects": [
                    "Paired failure-aware derivative NMSE will decrease."
                ],
                "alternative_explanations": [
                    "The apparent gain may instead arise from scale regularization."
                ],
                "falsification_conditions": [
                    "The paired system median does not improve over the parent.",
                    "Training-context perturbation leaves every prediction unchanged.",
                ],
                "source_ids": ["wsindy", "ensemble-sindy"],
                "intervention_summary": (
                    "Add a bounded train-context residual while retaining a capability-safe fallback."
                ),
                "source_text": _mechanism_candidate_source(candidate_id),
            }
        else:
            context = json.loads(messages[1]["content"])
            candidate_id = str(context["candidate"]["candidate_id"])
            count = self.implementation_calls.get(candidate_id, 0) + 1
            self.implementation_calls[candidate_id] = count
            if self.transient_failure_candidate == candidate_id and count == 1:
                raise LLMClientError("temporary provider outage")
            source = _candidate_source(candidate_id)
            if (
                self.bad_first_branch
                and candidate_id == "branch-01"
                and (
                    count == 1
                    or (self.unchanged_first_repair and count == 2)
                    or (self.unchanged_second_repair and count == 3)
                )
            ):
                source = "import os\n" + source
            if (
                self.zero_complexity_first_branch
                and candidate_id == "branch-01"
                and count == 1
            ):
                source = source.replace('"complexity": 3', '"complexity": 0')
            payload = {
                "candidate_id": candidate_id,
                "implementation_summary": (
                    "Model-authored dependency-neutral recursive estimator for capability preflight."
                ),
                "source_text": source,
            }
        response_text = json.dumps(payload, sort_keys=True)
        transport_normalization: Literal[
            "none", "discarded_trailing_closing_delimiters"
        ] = "none"
        normalization_suffix = None
        if (
            schema_name == "autonomous_candidate_implementation"
            and payload["candidate_id"] == self.trailing_normalized_candidate
        ):
            response_text += "]"
            transport_normalization = "discarded_trailing_closing_delimiters"
            normalization_suffix = "]"
        return LLMJsonCompletionResult(
            provider="fixture-openai-compatible",
            base_url="https://provider.example/v1",
            model_name="fixture-research-model",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=response_text,
            parsed_json=payload,
            usage={"prompt_tokens": 10, "completion_tokens": 10},
            temperature=float(kwargs["temperature"]),
            transport_normalization=transport_normalization,
            normalization_suffix=normalization_suffix,
        )


def _portfolio_frame_payload(*, invalid: bool = False) -> dict[str, object]:
    return {
        "schema_version": "autonomous-portfolio-frame-v1",
        "research_gap": (
            "Existing robust discovery operators remain insufficiently compared as composable, "
            "execution-grounded mechanisms across ODE and multidimensional PDE regimes."
        ),
        "architecture_source_ids": [
            "ai-scientist-v2",
            "mlrc-bench",
            "execution-grounded-ai-research",
        ],
        "mechanism_slots": [
            {
                "candidate_id": candidate_id,
                "mechanism_family": _candidate_mechanism_family(
                    candidate_id,
                    invalid=invalid,
                ),
                "primary_operator": (
                    f"Fixture primary computational operator {candidate_id}"
                    if not invalid
                    else "one repeated fixture operator"
                ),
                "differentiation": (
                    f"Slot {candidate_id} commits to an independently testable operator path "
                    "before the full hypothesis and exact implementation are generated."
                ),
                "source_ids": ["wsindy", "ensemble-sindy"],
            }
            for candidate_id in (
                f"branch-{index:02d}" for index in range(1, 9)
            )
        ],
        "fixed_catalogue_used": False,
        "human_authored_candidate_count": 0,
    }


def _candidate_hypothesis_payload(
    candidate_id: str,
    *,
    invalid: bool,
) -> dict[str, object]:
    index = int(candidate_id.rsplit("-", maxsplit=1)[1])
    return {
        "candidate_id": candidate_id,
        "title": f"Autonomous mechanism hypothesis {index:02d}",
        "mechanism_family": _candidate_mechanism_family(
            candidate_id,
            invalid=invalid,
        ),
        "hypothesis": (
            f"A data-adaptive operator variant {index:02d} should reduce derivative instability "
            "while preserving equation sparsity across heterogeneous dynamical systems."
        ),
        "novelty_rationale": (
            f"Branch {index:02d} composes source-grounded operators under one falsifiable "
            "execution contract instead of selecting a pre-authored catalogue entry."
        ),
        "falsification_conditions": [
            "No improvement in noisy derivative NMSE on development systems.",
            "Instability across seeds or excessive equation complexity.",
        ],
        "source_ids": ["wsindy", "ensemble-sindy"],
        "generation": 1,
        "parent_candidate_id": None,
        "authored_by_model": True,
    }


def _candidate_mechanism_family(candidate_id: str, *, invalid: bool) -> str:
    families = (
        "weak covariance regression",
        "ensemble stability selection",
        "constrained sparse relaxation",
        "surrogate derivative regularization",
    )
    index = int(candidate_id.rsplit("-", maxsplit=1)[1])
    if invalid:
        return "one fixed family"
    return f"{families[(index - 1) % len(families)]} operator path {index:02d}"


def _candidate_source(candidate_id: str) -> str:
    return f'''BRANCH_TAG = "{candidate_id}"

def discover_equations(payload):
    prediction = [float(value) * 0.1 for value in payload["flat_values"]]
    equations = ["du/dt = adaptive_data_operator_" + BRANCH_TAG] * int(payload["field_count"])
    return {{
        "status": "ok",
        "derivative_prediction_flat": prediction,
        "equations": equations,
        "complexity": 3,
        "diagnostics": {{"branch": BRANCH_TAG, "seed": int(payload["seed"])}},
    }}
'''


def _mechanism_candidate_source(candidate_id: str) -> str:
    return f'''BRANCH_TAG = "{candidate_id}"

def discover_equations(payload):
    train = [float(value) for value in payload.get("train_flat_values", [])]
    train_residual = (sum(train) / len(train) * 0.001) if train else 0.0
    prediction = [float(value) * 0.1 + train_residual for value in payload["flat_values"]]
    equations = ["du/dt = train_context_residual_" + BRANCH_TAG] * int(payload["field_count"])
    return {{
        "status": "ok",
        "derivative_prediction_flat": prediction,
        "equations": equations,
        "complexity": 4,
        "diagnostics": {{"branch": BRANCH_TAG, "seed": int(payload["seed"])}},
    }}
'''


def _development_environment_fixture() -> AutonomousDevelopmentEnvironment:
    payload: dict[str, object] = {
        "image": "fixture-mdbench:task2653",
        "image_id": f"sha256:{'1' * 64}",
        "benchmark_revision": MDBENCH_REVISION,
        "pinned_environment_hash": "2" * 64,
        "pinned_baseline_runner_sha256": "3" * 64,
        "formal_baseline_runner_sha256": "4" * 64,
        "baseline_algorithm_subset_sha256": "5" * 64,
        "autonomous_runner_sha256": "6" * 64,
        "adapter_id": "official-single-time-query-v1",
        "adapter_contract_sha256": "7" * 64,
        "network_default_deny": True,
        "maximum_parallel_cells": 4,
    }
    payload["environment_hash"] = canonical_model_hash(payload)
    return AutonomousDevelopmentEnvironment.model_validate(payload)


def _development_cell_executor_fixture(
    invocation: DevelopmentCellInvocation,
) -> DevelopmentCellOutcome:
    candidate_id = invocation.spec.candidate_id
    if invocation.spec.method_kind == "operon_gp":
        derivative_nmse = 1.0
        sensitivity = 0.0
    elif candidate_id.startswith("branch-0") and int(candidate_id[-2:]) <= 8:
        derivative_nmse = 0.90 + int(candidate_id[-2:]) * 0.01
        sensitivity = 0.0
    else:
        derivative_nmse = {
            "branch-09": 0.45,
            "branch-10": 0.50,
            "branch-11": 0.55,
            "branch-12": 0.60,
        }[candidate_id]
        sensitivity = 0.01
    payload = {
        "schema_version": "autonomous-development-runner-payload-v1",
        "status": "succeeded",
        "failure_reason": None,
        "derivative_nmse": derivative_nmse,
        "validation_nmse": derivative_nmse * 1.01,
        "trajectory_extrapolation_nmse_ode": (
            derivative_nmse if invocation.spec.unit.data_type == "ode" else None
        ),
        "model_complexity": 4,
        "training_context_sensitivity_max_abs": sensitivity,
        "validation_query_count": 4,
        "test_query_count": 8,
        "wall_time_seconds": 0.01,
        "peak_rss_mb": 32.0,
        "discovered_equation": "du/dt = fixture_operator(u)",
        "split_indices": {
            "time_axis_size": 10,
            "train_start": 0,
            "train_end": 6,
            "validation_start": 6,
            "validation_end": 8,
            "test_start": 8,
            "test_end": 10,
        },
        "spec_hash": _runner_spec_payload(
            invocation.spec,
            invocation.environment,
        )["spec_hash"],
        "true_derivative_exposed_to_candidate": False,
        "query_temporal_context_count": 1,
        "candidate_output_numeric_transform_count": 0,
    }
    return DevelopmentCellOutcome(
        return_code=0,
        stdout="fixture stdout",
        stderr="",
        elapsed_seconds=0.01,
        payload=payload,
    )


def _materialize_manifest_artifacts(manifest: MDBenchArchiveManifest) -> None:
    extracted_root = Path(manifest.extracted_root)
    for artifact in manifest.artifacts:
        payload = (
            f"{artifact.data_type}/{artifact.system_name}/{artifact.condition}"
        ).encode()
        assert hashlib.sha256(payload).hexdigest() == artifact.sha256
        path = extracted_root / artifact.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _source_fetcher(
    spec: AutonomousRecoverySourceSpec,
    _timeout_seconds: int,
) -> tuple[bytes, str, int]:
    body = (
        f"<html><title>{spec.title}</title><body>{spec.required_marker} "
        f"{spec.source_id}</body></html>"
    ).encode()
    return body, spec.url, 200


def _formal_negative_cycles(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    manifest_path = tmp_path / "official" / "archive-manifest.json"
    manifest = _write_manifest(manifest_path)
    parent_matrix_path = tmp_path / "parent" / "gate-a-preregistration.json"
    preregister_mdbench_gate_a(manifest, parent_matrix_path)
    parent_report_path = _write_negative_report(
        parent_matrix_path,
        tmp_path / "parent" / "gate-a",
        candidate_method_id="stability_sindy",
    )
    recovery_dir = tmp_path / "recovery"
    recovery_preregistration, recovery_matrix = preregister_mdbench_gate_a_recovery(
        manifest,
        parent_matrix_path,
        parent_report_path,
        recovery_dir,
    )
    recovery_report_path = _write_negative_report(
        Path(recovery_matrix.output_path),
        tmp_path / "recovery" / "gate-a",
        candidate_method_id="weak_stability_sindy",
    )
    return (
        manifest_path,
        parent_matrix_path,
        parent_report_path,
        Path(recovery_preregistration.output_path),
        Path(recovery_matrix.output_path),
        recovery_report_path,
    )


def _write_manifest(path: Path) -> MDBenchArchiveManifest:
    ode_systems = tuple(
        dict.fromkeys(_PARENT_ODE_SYSTEMS + _RECOVERY_ODE_SYSTEMS + _UNUSED_ODE_SYSTEMS)
    )
    pde_systems = tuple(
        dict.fromkeys(_PARENT_PDE_SYSTEMS + _RECOVERY_PDE_SYSTEMS + _UNUSED_PDE_SYSTEMS)
    )
    artifacts: list[MDBenchDatasetArtifact] = []
    inventories: tuple[tuple[Literal["ode", "pde"], tuple[str, ...]], ...] = (
        ("ode", ode_systems),
        ("pde", pde_systems),
    )
    for data_type, systems in inventories:
        for system_name in systems:
            for condition in ("clean", "snr_20"):
                payload = f"{data_type}/{system_name}/{condition}".encode()
                artifacts.append(
                    MDBenchDatasetArtifact(
                        relative_path=(
                            f"processed/data/{data_type}/{system_name}/"
                            f"{system_name}{'' if condition == 'clean' else '_snr_20'}.npz"
                        ),
                        data_type=data_type,
                        system_name=system_name,
                        condition=condition,
                        size_bytes=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(),
                    )
                )
    archive_sha256 = "1" * 64
    inventory_hash = canonical_model_hash(
        {
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "archive_sha256": archive_sha256,
        }
    )
    manifest = MDBenchArchiveManifest(
        repository_url="https://github.com/gryaklab/mdbench",
        benchmark_revision=MDBENCH_REVISION,
        dataset_doi="10.5281/zenodo.17611099",
        dataset_license="mit-license",
        archive_path=(path.parent / "processed.zip").resolve().as_posix(),
        archive_size_bytes=1,
        archive_md5="0" * 32,
        archive_sha256=archive_sha256,
        extracted_root=(path.parent / "processed").resolve().as_posix(),
        artifacts=tuple(artifacts),
        ode_systems=ode_systems,
        pde_systems=pde_systems,
        noise_conditions=("snr_20",),
        inventory_hash=inventory_hash,
        output_path=path.resolve().as_posix(),
    )
    write_json_model(path, manifest)
    return manifest


def _write_negative_report(
    matrix_path: Path,
    output_dir: Path,
    *,
    candidate_method_id: str,
) -> Path:
    matrix_payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    output_path = (output_dir / "gate-a-adjudication.json").resolve()
    markdown_path = (output_dir / "gate-a-report.md").resolve()
    comparison = GateAPrimaryComparison(
        candidate_method_id=candidate_method_id,
        baseline_method_id="operon_gp",
        candidate_success_count=18,
        baseline_success_count=17,
        failure_aware_system_median_relative_improvement=-0.31,
        bootstrap_ci95_lower=-0.80,
        bootstrap_ci95_upper=0.12,
        system_effects=(),
        missing_cell_policy="failed cells receive zero improvement",
    )
    unstamped = MDBenchGateAReport(
        decision=GateADecision.NEGATIVE_RESULT,
        gate_b_allowed=False,
        matrix_path=matrix_path.resolve().as_posix(),
        matrix_hash=matrix_payload["matrix_hash"],
        execution_report_path=(output_dir / "execution-report.json").resolve().as_posix(),
        execution_report_hash="3" * 64,
        execution_environment_hash="4" * 64,
        result_set_hash="5" * 64,
        adjudicator_sha256="6" * 64,
        analysis_policy_hash="7" * 64,
        truth_registry_hash="8" * 64,
        truth_source_revision=MDBENCH_REVISION,
        truth_source_files={"fixture": "9" * 64},
        total_attempt_count=252,
        succeeded_count=240,
        failed_count=12,
        timed_out_count=0,
        human_intervention_count=0,
        access_request_count=0,
        candidate_method_id=candidate_method_id,
        selected_baseline_method_id="operon_gp",
        baseline_selection_rule="frozen fixture rule",
        baseline_selection_scores=(),
        method_summaries=(),
        primary_comparison=comparison,
        checks=(),
        negative_reasons=("fixture negative result",),
        limitations=(),
        generated_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        analysis_hash="a" * 64,
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    report_hash = canonical_model_hash(
        unstamped.model_dump(
            mode="json",
            exclude={"report_hash", "output_path", "markdown_path"},
        )
    )
    report = unstamped.model_copy(update={"report_hash": report_hash})
    write_json_model(output_path, report)
    return output_path
