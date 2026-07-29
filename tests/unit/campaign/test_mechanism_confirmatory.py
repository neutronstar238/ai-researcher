from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.campaign.mechanism_benchmark import task2612_confirmatory_tasks
from autoresearch.campaign.mechanism_confirmatory import (
    MechanismConfirmatoryEndpoint,
    MechanismConfirmatoryIntegrityError,
    MechanismConfirmatoryStatus,
    MechanismConfirmatoryTaskResult,
    MechanismScientificOutcome,
    MechanismTaskExecutionRole,
    freeze_task2612_confirmatory,
    load_mechanism_confirmatory,
    load_mechanism_confirmatory_preregistration,
    run_task2612_confirmatory,
)
from autoresearch.campaign.mechanism_development import (
    MechanismDevelopmentStatus,
    run_task2612_mechanism_development,
)
from autoresearch.campaign.mechanism_round import (
    MechanismFoundationManifest,
    MechanismPanelSpec,
    ParentSprintEvidence,
    build_task2612_research_brief,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel import EventJournal, LoopRunSnapshot, LoopSpec, ProvenanceBundle
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.schemas import file_hash

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64

RISK_EXPRESSION = (
    "0.35 * (1.0 - support_score) + 0.30 * contradiction_score + "
    "0.20 * uncertainty + 0.10 * (1.0 - source_quality) + "
    "0.05 * (1.0 if independent_source_count == 0 else "
    "1.0 / (independent_source_count + 1.0))"
)
ACCEPT_EXPRESSION = "independent_source_count >= 1 and risk_score <= 0.35"


def _write_foundation(root: Path) -> Path:
    root.mkdir(parents=True)
    parent = ParentSprintEvidence.create(
        parent_sprint_id="fixture-negative-parent",
        manifest_file_sha256=SHA_A,
        manifest_hash=SHA_B,
        endpoint_file_sha256=SHA_C,
        endpoint_hash=SHA_D,
        autonomy_audit_file_sha256=SHA_E,
        autonomy_audit_hash=SHA_F,
        topic_selection_file_sha256=SHA_A,
        topic_selection_hash=SHA_B,
        selected_candidate_id="C003",
        selected_program_id="systems-evidence-gate-claims-task-v2",
        parent_failure_codes=["bootstrap_ci_lower_above_zero"],
        revealed_task_ids=[f"parent-task-{index:02d}" for index in range(10)],
    )
    brief = build_task2612_research_brief(parent)
    parent_path = write_json_model(root / "parent-evidence.json", parent)
    brief_path = write_json_model(root / "research-brief.json", brief)
    manifest = MechanismFoundationManifest.create(
        foundation_id="fixture-task2612-foundation",
        frozen_at=NOW,
        parent_evidence_hash=parent.evidence_hash,
        parent_evidence_file_sha256=file_hash(parent_path),
        research_brief_hash=brief.brief_hash,
        research_brief_file_sha256=file_hash(brief_path),
    )
    write_json_model(root / "foundation-manifest.json", manifest)
    return root


class _Completion:
    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        name = kwargs["response_schema_name"]
        if name == "task2612_mechanism_diagnosis":
            payload: dict[str, Any] = {
                "causal_hypotheses": [
                    "A binary gate hides the coverage and residual-risk trade-off.",
                    "A single evidence signal cannot expose conflict and uncertainty.",
                ],
                "required_mechanism_properties": [
                    "Emit accept or abstain for every claim.",
                    (
                        "Combine external support, contradiction, uncertainty, "
                        "source count, and quality."
                    ),
                    (
                        "Remain deterministic, permutation-equivariant, and "
                        "conservative under degradation."
                    ),
                ],
                "literature_source_ids": ["source-001", "source-002", "source-010"],
            }
        else:
            payload = {
                "mechanism_kind": "risk_selective_gate",
                "mechanism_title": "Multi-signal residual-risk selective claim controller",
                "mechanism_delta": (
                    "Replace the binary evidence-presence gate with a deterministic "
                    "multi-signal residual-risk controller."
                ),
                "falsification_conditions": [
                    "Development coverage is below the frozen minimum.",
                    "Accepted unsupported-claim risk exceeds the frozen ceiling.",
                ],
                "literature_source_ids": ["source-001", "source-002", "source-010"],
                "implementation_mode": "structured_expression_v1",
                "risk_expression": RISK_EXPRESSION,
                "accept_expression": ACCEPT_EXPRESSION,
                "accept_reason_code": "multi_signal_accept",
                "abstain_reason_code": "risk_abstain",
            }
        return LLMJsonCompletionResult(
            provider="fixture-openai-compatible",
            base_url="http://127.0.0.1:11434/v1",
            model_name="fixture-qwen",
            endpoint="http://127.0.0.1:11434/v1/chat/completions",
            response_text=json.dumps(payload, sort_keys=True),
            parsed_json=payload,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            temperature=float(kwargs["temperature"]),
        )


@pytest.fixture(scope="module")
def development_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("mechanism-confirmatory-development")
    output = root / "development"
    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=_write_foundation(root / "foundation"),
        llm_config_path=root / "unused-config.yaml",
        completion=_Completion(),
        run_id="fixture-mechanism-development",
        clock=lambda: NOW,
    )
    assert manifest.status is MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION
    return output


def test_preregistration_freezes_unrevealed_one_shot_contract(
    tmp_path: Path,
    development_dir: Path,
) -> None:
    root = tmp_path / "confirmatory"

    preregistration = freeze_task2612_confirmatory(
        development_dir=development_dir,
        output_dir=root,
        run_id="fixture-confirmatory-freeze",
        clock=lambda: NOW,
    )
    spec = LoopSpec.model_validate_json(
        (root / "control" / "loop-spec.json").read_text(encoding="utf-8")
    )
    panel = MechanismPanelSpec.model_validate_json(
        (root / "frozen" / "panel-spec.json").read_text(encoding="utf-8")
    )
    development_fingerprints = {
        task.source_fingerprint for task in panel.development_tasks
    }
    confirmatory_fingerprints = {
        task.source_fingerprint for task in panel.confirmatory_tasks
    }

    assert preregistration.confirmatory_results_revealed is False
    assert preregistration.confirmatory_result_artifact_count == 0
    assert preregistration.scientific_result_created is False
    assert preregistration.maximum_task_attempts == 1
    assert preregistration.continue_after_task_failure is True
    assert preregistration.post_reveal_adaptation_allowed is False
    assert preregistration.endpoint_rewrite_allowed is False
    assert preregistration.external_submission_authorized is False
    assert preregistration.minimum_coverage == 0.60
    assert preregistration.maximum_unsupported_claim_rate == 0.10
    assert preregistration.bootstrap_resamples == 20_000
    assert preregistration.bootstrap_seed == 261_203
    assert len(preregistration.confirmatory_task_hashes) == 6
    assert len(development_fingerprints) == len(panel.development_tasks)
    assert len(confirmatory_fingerprints) == len(panel.confirmatory_tasks)
    assert development_fingerprints.isdisjoint(confirmatory_fingerprints)
    assert spec.spec_hash == preregistration.control_spec_hash
    assert spec.immutable_during_run is True
    assert spec.model_graph_proposals_allowed is False
    assert spec.release_authorization_allowed is False
    assert not (root / "confirmatory").exists()
    assert not (root / "endpoint.json").exists()
    assert (
        freeze_task2612_confirmatory(
            development_dir=development_dir,
            output_dir=root,
            run_id="ignored-on-idempotent-load",
            clock=lambda: NOW,
        )
        == preregistration
    )
    assert load_mechanism_confirmatory_preregistration(root) == preregistration


def test_preregistration_and_frozen_artifact_tamper_fail_closed(
    tmp_path: Path,
    development_dir: Path,
) -> None:
    preregistration_root = tmp_path / "preregistration-tamper"
    freeze_task2612_confirmatory(
        development_dir=development_dir,
        output_dir=preregistration_root,
        clock=lambda: NOW,
    )
    preregistration_path = preregistration_root / "preregistration.json"
    payload = json.loads(preregistration_path.read_text(encoding="utf-8"))
    payload["minimum_coverage"] = 0.01
    preregistration_path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(
        (MechanismConfirmatoryIntegrityError, ValidationError),
        match="hash|mismatch",
    ):
        load_mechanism_confirmatory_preregistration(preregistration_root)

    frozen_root = tmp_path / "frozen-tamper"
    freeze_task2612_confirmatory(
        development_dir=development_dir,
        output_dir=frozen_root,
        clock=lambda: NOW,
    )
    with (frozen_root / "frozen" / "run.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# tamper\n")

    with pytest.raises(MechanismConfirmatoryIntegrityError, match="artifact index drift"):
        run_task2612_confirmatory(output_dir=frozen_root, clock=lambda: NOW)
    assert not (frozen_root / "control" / "journal").exists()
    assert not (frozen_root / "endpoint.json").exists()


def test_full_confirmatory_run_seals_endpoint_provenance_and_reproduction(
    tmp_path: Path,
    development_dir: Path,
) -> None:
    root = tmp_path / "confirmatory"
    preregistration = freeze_task2612_confirmatory(
        development_dir=development_dir,
        output_dir=root,
        run_id="fixture-confirmatory-full",
        clock=lambda: NOW,
    )

    manifest = run_task2612_confirmatory(output_dir=root, clock=lambda: NOW)
    endpoint = MechanismConfirmatoryEndpoint.model_validate_json(
        (root / "endpoint.json").read_text(encoding="utf-8")
    )
    snapshot = LoopRunSnapshot.model_validate_json(
        (root / "control" / "terminal-snapshot.json").read_text(encoding="utf-8")
    )
    provenance = ProvenanceBundle.load_json(root / "provenance" / "provenance-v2.json")
    reproduction = json.loads((root / "reproduction" / "report.json").read_text(encoding="utf-8"))
    rollback = json.loads((root / "rollback" / "report.json").read_text(encoding="utf-8"))
    evaluation = json.loads(
        (root / "evaluation" / "security-report.json").read_text(encoding="utf-8")
    )
    task_results = sorted((root / "confirmatory").glob("*/task-result.json"))

    assert manifest.status in {
        MechanismConfirmatoryStatus.POSITIVE_RESULT,
        MechanismConfirmatoryStatus.NEGATIVE_RESULT,
    }
    assert manifest.scientific_outcome is endpoint.outcome
    assert endpoint.preregistration_hash == preregistration.preregistration_hash
    assert endpoint.task_count == 6
    assert endpoint.confirmatory_result_artifact_count == 6
    assert endpoint.endpoint_rewrite_allowed is False
    assert endpoint.external_submission_authorized is False
    assert len(task_results) == 6
    assert snapshot.seal_hash == manifest.journal_seal_hash
    journal_snapshot = EventJournal.open(root / "control" / "journal").snapshot()
    assert journal_snapshot.seal is not None
    assert journal_snapshot.seal.seal_hash == manifest.journal_seal_hash
    assert provenance.require_claim_trace(f"claim.{preregistration.run_id}.endpoint").evidence_ids
    assert reproduction["passed"] is True
    assert reproduction["endpoint_mutation_allowed"] is False
    assert rollback["passed"] is True
    assert rollback["destructive_rollback_performed"] is False
    assert evaluation["passed"] is True
    assert evaluation["scientific_verdict_unchanged"] is True
    assert run_task2612_confirmatory(output_dir=root, clock=lambda: NOW) == manifest
    assert load_mechanism_confirmatory(root) == manifest

    with (root / "evaluation" / "security-report.json").open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write("\n")
    with pytest.raises(MechanismConfirmatoryIntegrityError, match="artifact index drift"):
        load_mechanism_confirmatory(root)


def test_crash_after_task_side_effect_resumes_without_second_execution(
    tmp_path: Path,
    development_dir: Path,
) -> None:
    root = tmp_path / "confirmatory"
    preregistration = freeze_task2612_confirmatory(
        development_dir=development_dir,
        output_dir=root,
        run_id="fixture-confirmatory-resume",
        clock=lambda: NOW,
    )
    first_task_id = sorted(preregistration.confirmatory_task_hashes)[0]
    first_node_id = f"execute-{first_task_id}"
    crashed = False

    def fault(phase: str, node_id: str) -> None:
        nonlocal crashed
        if phase == "after_node_execute" and node_id == first_node_id and not crashed:
            crashed = True
            raise RuntimeError("injected crash after confirmatory task side effect")

    with pytest.raises(RuntimeError, match="injected crash"):
        run_task2612_confirmatory(
            output_dir=root,
            clock=lambda: NOW,
            control_fault_injector=fault,
        )

    result_path = root / "confirmatory" / first_task_id / "task-result.json"
    receipt_path = root / "control" / "receipts" / f"{first_node_id}.json"
    result_hash_before_resume = file_hash(result_path)
    receipt_hash_before_resume = file_hash(receipt_path)

    manifest = run_task2612_confirmatory(output_dir=root, clock=lambda: NOW)
    snapshot = LoopRunSnapshot.model_validate_json(
        (root / "control" / "terminal-snapshot.json").read_text(encoding="utf-8")
    )

    assert manifest.status is not MechanismConfirmatoryStatus.VERIFICATION_FAILED
    assert file_hash(result_path) == result_hash_before_resume
    assert file_hash(receipt_path) == receipt_hash_before_resume
    assert all(
        snapshot.state.attempts_by_node[f"execute-{task_id}"] == 1
        for task_id in preregistration.confirmatory_task_hashes
    )


def test_failed_tasks_produce_a_retained_negative_endpoint(
    tmp_path: Path,
    development_dir: Path,
) -> None:
    preregistration = freeze_task2612_confirmatory(
        development_dir=development_dir,
        output_dir=tmp_path / "confirmatory",
        run_id="fixture-confirmatory-negative",
        clock=lambda: NOW,
    )
    results = [
        MechanismConfirmatoryTaskResult.create(
            execution_role=MechanismTaskExecutionRole.PRIMARY_CONFIRMATORY,
            task=task,
            generated_source_sha256=preregistration.generated_source_sha256,
            decisions=[],
            execution_succeeded=False,
            failure_codes=["fixture_execution_failure"],
            explicit_environment_keys=[],
        )
        for task in task2612_confirmatory_tasks()
    ]

    endpoint = MechanismConfirmatoryEndpoint.create(
        preregistration=preregistration,
        results=results,
        started_at=NOW,
        completed_at=NOW,
    )

    assert endpoint.outcome is MechanismScientificOutcome.NEGATIVE_RESULT
    assert endpoint.successful_task_count == 0
    assert endpoint.failed_task_count == 6
    assert endpoint.accepted_count == 0
    assert endpoint.gates["all_task_executions_succeeded"] is False
    assert endpoint.gates["minimum_coverage_met"] is False
    assert endpoint.failure_codes == [
        "all_task_executions_succeeded",
        "minimum_coverage_met",
        "unsupported_rate_ci_upper_met",
    ]
    assert endpoint.scientific_result_created is True
    assert endpoint.external_submission_authorized is False
