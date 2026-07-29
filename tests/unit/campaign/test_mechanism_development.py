from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.campaign.mechanism_benchmark import (
    DevelopmentScreenDecision,
    build_task2612_panel,
    task2612_confirmatory_tasks,
    task2612_development_tasks,
)
from autoresearch.campaign.mechanism_development import (
    MechanismDevelopmentIntegrityError,
    MechanismDevelopmentStatus,
    load_mechanism_development,
    run_task2612_mechanism_development,
)
from autoresearch.campaign.mechanism_round import (
    MechanismFoundationManifest,
    ParentSprintEvidence,
    build_task2612_research_brief,
)
from autoresearch.campaign.mechanism_sandbox import (
    review_mechanism_source,
    run_generated_code_harness,
    run_generated_code_test_suites,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel import EpisodeOutcomeStatus
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult
from autoresearch.schemas import file_hash

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64

SAFE_SOURCE = '''from __future__ import annotations

import json
from pathlib import Path


def evaluate_claims(claims):
    decisions = []
    for claim in claims:
        support = float(claim["support_score"])
        contradiction = float(claim["contradiction_score"])
        uncertainty = float(claim["uncertainty"])
        count = int(claim["independent_source_count"])
        quality = float(claim["source_quality"])
        source_penalty = 1.0 if count == 0 else 1.0 / float(count + 1)
        risk = (
            0.35 * (1.0 - support)
            + 0.30 * contradiction
            + 0.20 * uncertainty
            + 0.10 * (1.0 - quality)
            + 0.05 * source_penalty
        )
        risk = max(0.0, min(1.0, risk))
        accepted = (
            support >= 0.65
            and contradiction <= 0.30
            and uncertainty <= 0.45
            and count >= 1
            and quality >= 0.70
            and risk <= 0.35
        )
        decisions.append(
            {
                "claim_id": str(claim["claim_id"]),
                "decision": "accept" if accepted else "abstain",
                "risk_score": risk,
                "reason_code": "multi_signal_accept" if accepted else "risk_abstain",
            }
        )
    return decisions


def main():
    root = Path(__file__).resolve().parent
    payload = json.loads((root / "input.json").read_text(encoding="utf-8"))
    decisions = evaluate_claims(payload["claims"])
    (root / "metrics.json").write_text(
        json.dumps(
            {"status": "success", "decisions": decisions},
            sort_keys=True,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
'''

RISK_EXPRESSION = (
    "0.35 * (1.0 - support_score) + 0.30 * contradiction_score + "
    "0.20 * uncertainty + 0.10 * (1.0 - source_quality) + "
    "0.05 * (1.0 if independent_source_count == 0 else "
    "1.0 / (independent_source_count + 1.0))"
)
ACCEPT_EXPRESSION = (
    "independent_source_count >= 1 and risk_score <= 0.35"
)
ABSTAIN_EXPRESSION = (
    "False and risk_score <= 1.0 and support_score >= 0.0 and "
    "independent_source_count >= 0"
)
UNSAFE_EXPRESSION = (
    "__import__('os').system('whoami') + support_score + "
    "contradiction_score + uncertainty + independent_source_count + "
    "source_quality"
)
ZERO_DIVISION_RISK_EXPRESSION = (
    "(support_score + source_quality) / "
    "(independent_source_count * min(uncertainty, 1.0 - uncertainty)) "
    "if independent_source_count > 0 else contradiction_score"
)


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
    def __init__(
        self,
        *,
        risk_expression: str = RISK_EXPRESSION,
        accept_expression: str = ACCEPT_EXPRESSION,
        first_invalid_risk_expression: str | None = None,
        fail: bool = False,
    ) -> None:
        self.risk_expression = risk_expression
        self.accept_expression = accept_expression
        self.first_invalid_risk_expression = first_invalid_risk_expression
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        if self.fail:
            raise LLMClientError("fixture model unavailable")
        messages = json.dumps(kwargs["messages"], sort_keys=True)
        assert "task2612-dev-" not in messages
        assert "task2612-confirm-" not in messages
        name = kwargs["response_schema_name"]
        if name == "task2612_mechanism_diagnosis":
            payload: dict[str, Any] = {
                "causal_hypotheses": [
                    "A binary gate hides the coverage and residual-risk trade-off.",
                    "A single evidence signal cannot expose conflict and uncertainty.",
                ],
                "required_mechanism_properties": [
                    "Emit accept or abstain for every claim.",
                    "Combine external support, contradiction, uncertainty, source count, and quality.",
                    "Remain deterministic, permutation-equivariant, and conservative under degradation.",
                ],
                "literature_source_ids": [
                    "source-001",
                    "source-002",
                    "source-010",
                ],
            }
        else:
            proposal_call_count = sum(
                call["response_schema_name"] == "task2612_mechanism_proposal"
                for call in self.calls
            )
            risk_expression = (
                self.first_invalid_risk_expression
                if self.first_invalid_risk_expression is not None
                and proposal_call_count == 1
                else self.risk_expression
            )
            payload = {
                "mechanism_kind": "risk_selective_gate",
                "mechanism_title": "Multi-signal residual-risk selective claim controller",
                "mechanism_delta": (
                    "Replace the binary evidence-presence gate with a deterministic "
                    "multi-signal residual-risk controller that separately accounts "
                    "for support, contradiction, uncertainty, independent-source "
                    "count, and source quality before accepting or abstaining."
                ),
                "falsification_conditions": [
                    "Development coverage is below the frozen minimum.",
                    "Accepted unsupported-claim risk exceeds the frozen ceiling.",
                ],
                "literature_source_ids": [
                    "source-001",
                    "source-002",
                    "source-010",
                ],
                "implementation_mode": "structured_expression_v1",
                "risk_expression": risk_expression,
                "accept_expression": self.accept_expression,
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


def test_panel_is_disjoint_and_confirmatory_payload_is_not_public() -> None:
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

    panel = build_task2612_panel(parent)
    development = task2612_development_tasks()
    confirmatory = task2612_confirmatory_tasks()

    assert len(development) == 3
    assert len(confirmatory) == 6
    assert not (
        {task.task_id for task in development}
        & {task.task_id for task in confirmatory}
    )
    assert all("supported" not in claim.public_payload() for task in development for claim in task.claims)
    assert panel.confirmatory_visibility == "sealed-until-code-freeze"


def test_strict_review_accepts_contract_source_and_blocks_adversaries(
    tmp_path: Path,
) -> None:
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    (safe_root / "run.py").write_bytes(SAFE_SOURCE.encode("utf-8"))

    safe = review_mechanism_source(
        safe_root,
        expected_source_sha256=file_hash(safe_root / "run.py"),
    )

    assert safe.approved is True
    adversaries = {
        "network": SAFE_SOURCE.replace("import json", "import json\nimport socket"),
        "dynamic": SAFE_SOURCE.replace(
            "def evaluate_claims(claims):",
            "eval('1 + 1')\n\n\ndef evaluate_claims(claims):",
        ),
        "secret": SAFE_SOURCE.replace(
            "import json",
            "import json\nimport os",
        ).replace(
            "def evaluate_claims(claims):",
            "os.getenv('API_KEY')\n\n\ndef evaluate_claims(claims):",
        ),
        "path": SAFE_SOURCE.replace(
            '"input.json"',
            '"../input.json"',
        ),
        "top_level_effect": SAFE_SOURCE.replace(
            'if __name__ == "__main__":\n    main()',
            "if True:\n    main()",
        ),
    }
    for name, source in adversaries.items():
        root = tmp_path / name
        root.mkdir()
        (root / "run.py").write_bytes(source.encode("utf-8"))
        report = review_mechanism_source(
            root,
            expected_source_sha256=file_hash(root / "run.py"),
        )
        assert report.approved is False, name
        assert report.findings, name


def test_sandbox_and_generated_code_test_suites_use_exact_source(
    tmp_path: Path,
) -> None:
    source_hash = file_hash(_write_source(tmp_path / "source", SAFE_SOURCE))
    unit, properties = run_generated_code_test_suites(
        output_dir=tmp_path / "tests",
        source_text=SAFE_SOURCE,
        static_review_approved=True,
    )
    spec, episode, observation, decisions = run_generated_code_harness(
        run_id="run-safe-source",
        episode_id="episode-safe-source",
        output_dir=tmp_path / "harness",
        source_text=SAFE_SOURCE,
        claims=[
            {
                "claim_id": "claim-a",
                "support_score": 0.90,
                "contradiction_score": 0.04,
                "uncertainty": 0.10,
                "independent_source_count": 4,
                "source_quality": 0.92,
            }
        ],
        preflight_approved=True,
        clock=NOW,
    )

    assert unit.passed is True
    assert properties.passed is True
    assert episode.final_outcome.status is EpisodeOutcomeStatus.SUCCEEDED
    assert observation is not None
    assert observation.source_sha256 == source_hash
    assert observation.network_used is False
    assert "AUTORESEARCH_LOCAL_OLLAMA_API_KEY" not in observation.explicit_environment_keys
    assert decisions[0].decision.value == "accept"
    assert spec.spec_hash == episode.harness_spec_hash


def test_mocked_end_to_end_development_advances_without_confirmatory_result(
    tmp_path: Path,
) -> None:
    completion = _Completion()
    foundation = _write_foundation(tmp_path / "foundation")
    output = tmp_path / "development-run"

    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=foundation,
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=completion,
        run_id="fixture-mechanism-development",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION
    assert manifest.failure_codes == []
    assert manifest.scientific_result_created is False
    assert manifest.confirmatory_payload_executed is False
    assert manifest.confirmatory_result_artifact_count == 0
    assert manifest.external_submission_authorized is False
    assert len(manifest.model_interaction_hashes) == 2
    assert len(completion.calls) == 2
    proposal_schema = completion.calls[1]["response_schema"]
    assert "maxLength" not in json.dumps(proposal_schema, sort_keys=True)
    assert "source_chunks" not in proposal_schema["properties"]
    assert proposal_schema["properties"]["implementation_mode"]["const"] == (
        "structured_expression_v1"
    )
    assert json.loads(
        (output / "model" / "proposal-response-schema.json").read_text(
            encoding="utf-8"
        )
    ) == proposal_schema
    assert (
        output / "model" / "attempts" / "proposal" / "attempt-1.json"
    ).is_file()
    assert (output / "model" / "mechanism-program.json").is_file()
    assert (output / "freeze" / "round-freeze.json").is_file()
    assert not (output / "confirmatory").exists()
    screen = json.loads(
        (output / "development" / "screen.json").read_text(encoding="utf-8")
    )
    assert screen["decision"] == DevelopmentScreenDecision.ADVANCE_TO_PREREGISTRATION.value
    assert screen["coverage"] == 0.75
    assert screen["unsupported_claim_rate"] == 0.0
    assert load_mechanism_development(output) == manifest


def test_all_abstain_mechanism_is_retained_as_negative_development(
    tmp_path: Path,
) -> None:
    manifest = run_task2612_mechanism_development(
        output_dir=tmp_path / "development-run",
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=_Completion(accept_expression=ABSTAIN_EXPRESSION),
        run_id="fixture-negative-development",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.NEGATIVE_DEVELOPMENT
    assert manifest.failure_codes == ["minimum_coverage"]
    assert manifest.development_screen_hash is not None
    assert manifest.round_freeze_hash is not None
    assert manifest.scientific_result_created is False


def test_unsafe_model_expression_blocks_without_code_fallback(
    tmp_path: Path,
) -> None:
    manifest = run_task2612_mechanism_development(
        output_dir=tmp_path / "development-run",
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=_Completion(
            risk_expression=UNSAFE_EXPRESSION
        ),
        run_id="fixture-unsafe-development",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.BLOCKED
    assert manifest.failure_codes == ["proposal_generation_schema_invalid"]
    assert manifest.generated_code_evidence_hash is None
    assert manifest.round_freeze_hash is None
    assert manifest.development_screen_hash is None
    assert manifest.fallback_scientific_result_created is False
    assert not (tmp_path / "development-run" / "generated").exists()
    assert not (tmp_path / "development-run" / "development" / "screen.json").exists()


def test_numeric_boundary_failure_blocks_before_development(
    tmp_path: Path,
) -> None:
    output = tmp_path / "development-run"
    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=_Completion(
            risk_expression=ZERO_DIVISION_RISK_EXPRESSION,
        ),
        run_id="fixture-zero-division-development",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.BLOCKED
    assert manifest.failure_codes == ["generated_code_property_tests"]
    assert manifest.generated_code_evidence_hash is not None
    property_report = json.loads(
        (output / "review" / "tests" / "property-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert property_report["checks"]["closed_numeric_boundaries_succeed"] is False
    assert not (output / "development").exists()
    assert manifest.fallback_scientific_result_created is False


def test_model_unavailable_blocks_without_synthetic_diagnosis(
    tmp_path: Path,
) -> None:
    completion = _Completion(fail=True)
    output = tmp_path / "development-run"

    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=completion,
        run_id="fixture-model-blocked",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.BLOCKED
    assert manifest.failure_codes == [
        "diagnosis_generation_model_unavailable_or_invalid"
    ]
    assert len(completion.calls) == 2
    assert (
        output / "model" / "attempts" / "diagnosis" / "attempt-2.json"
    ).is_file()
    assert manifest.diagnosis_hash is None
    assert manifest.proposal_hash is None
    assert manifest.fallback_scientific_result_created is False


def test_transport_schema_removes_grammar_cap_but_local_limit_still_blocks(
    tmp_path: Path,
) -> None:
    completion = _Completion(risk_expression="x" * 16_385)
    output = tmp_path / "development-run"

    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=completion,
        run_id="fixture-overlong-source",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.BLOCKED
    assert manifest.failure_codes == ["proposal_generation_schema_invalid"]
    assert len(completion.calls) == 3
    assert all(
        "maxLength" not in json.dumps(call["response_schema"], sort_keys=True)
        for call in completion.calls[1:]
    )
    assert manifest.proposal_hash is None
    assert not (output / "generated").exists()


def test_invalid_expression_is_retried_without_code_side_repair(
    tmp_path: Path,
) -> None:
    completion = _Completion(
        first_invalid_risk_expression=UNSAFE_EXPRESSION
    )
    output = tmp_path / "development-run"

    manifest = run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=completion,
        run_id="fixture-source-retry",
        clock=lambda: NOW,
    )

    assert manifest.status is MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION
    assert len(completion.calls) == 3
    interaction = json.loads(
        (output / "model" / "proposal-interaction.json").read_text(
            encoding="utf-8"
        )
    )
    assert interaction["attempt_count"] == 2
    first_attempt = json.loads(
        (
            output
            / "model"
            / "attempts"
            / "proposal"
            / "attempt-1.json"
        ).read_text(encoding="utf-8")
    )
    assert first_attempt["valid"] is False
    assert first_attempt["fallback_used"] is False
    assert first_attempt["parsed_json"]["risk_expression"] == UNSAFE_EXPRESSION
    generated_source = (output / "generated" / "run.py").read_text(
        encoding="utf-8"
    )
    assert RISK_EXPRESSION in generated_source
    assert ACCEPT_EXPRESSION in generated_source
    serialization = json.loads(
        (output / "model" / "source-serialization.json").read_text(
            encoding="utf-8"
        )
    )
    assert serialization["code_side_repair_applied"] is False
    assert serialization["trusted_non_scientific_wrapper_used"] is True
    assert serialization["source_sha256"] == manifest.generated_source_sha256


def test_terminal_manifest_detects_artifact_tamper(tmp_path: Path) -> None:
    output = tmp_path / "development-run"
    run_task2612_mechanism_development(
        output_dir=output,
        foundation_dir=_write_foundation(tmp_path / "foundation"),
        llm_config_path=tmp_path / "unused-config.yaml",
        completion=_Completion(),
        run_id="fixture-tamper",
        clock=lambda: NOW,
    )
    with (output / "model" / "diagnosis.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(MechanismDevelopmentIntegrityError, match="drift"):
        load_mechanism_development(output)


def _write_source(root: Path, source: str) -> Path:
    root.mkdir(parents=True)
    path = root / "run.py"
    path.write_bytes(source.encode("utf-8"))
    return path
