from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.campaign.mechanism_confirmatory import (
    MechanismScientificOutcome,
    freeze_task2612_confirmatory,
    run_task2612_confirmatory,
)
from autoresearch.campaign.mechanism_development import (
    MechanismDevelopmentStatus,
    run_task2612_mechanism_development,
)
from autoresearch.campaign.mechanism_paper import (
    MechanismCitationAudit,
    MechanismClaimEntailmentReport,
    MechanismFigureTableAudit,
    MechanismPaperAudit,
    MechanismPaperClaimRecord,
    MechanismPaperIntegrityError,
    MechanismPaperReproductionReport,
    build_task2612_child_paper,
    load_task2612_child_paper,
)
from autoresearch.campaign.mechanism_round import (
    ClaimKind,
    MechanismFoundationManifest,
    ParentSprintEvidence,
    build_task2612_research_brief,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel.contracts import canonical_sha256
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
    "(support_score * source_quality + independent_source_count) / "
    "(contradiction_score + uncertainty + max(independent_source_count, 1e-6)) "
    "- min(abs(support_score - contradiction_score), 1.0)"
)
ACCEPT_EXPRESSION = "risk_score < 0.5 and independent_source_count >= 2"


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
        foundation_id="fixture-task2612-paper-foundation",
        frozen_at=NOW,
        parent_evidence_hash=parent.evidence_hash,
        parent_evidence_file_sha256=file_hash(parent_path),
        research_brief_hash=brief.brief_hash,
        research_brief_file_sha256=file_hash(brief_path),
    )
    write_json_model(root / "foundation-manifest.json", manifest)
    (root / "source-reachability.json").write_text(
        json.dumps(
            {
                "schema_version": "mechanism-source-reachability-v1",
                "research_brief_hash": brief.brief_hash,
                "checked_at": NOW.isoformat(),
                "observations": [
                    {
                        "source_id": source.source_id,
                        "requested_url": source.source_url,
                        "resolved_url": source.source_url,
                        "status_code": 200,
                        "content_bytes": 1_000,
                    }
                    for source in brief.sources
                ],
                "external_submission_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope="module")
def paper_inputs(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("mechanism-paper-inputs")
    foundation = _write_foundation(root / "foundation")
    development = root / "development"
    development_manifest = run_task2612_mechanism_development(
        output_dir=development,
        foundation_dir=foundation,
        llm_config_path=root / "unused-config.yaml",
        completion=_Completion(),
        run_id="fixture-mechanism-paper-development",
        clock=lambda: NOW,
    )
    assert (
        development_manifest.status
        is MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION
    )
    confirmatory = root / "confirmatory"
    freeze_task2612_confirmatory(
        development_dir=development,
        output_dir=confirmatory,
        run_id="fixture-mechanism-paper-confirmatory",
        clock=lambda: NOW,
    )
    confirmatory_manifest = run_task2612_confirmatory(
        output_dir=confirmatory,
        clock=lambda: NOW,
    )
    assert (
        confirmatory_manifest.scientific_outcome
        is MechanismScientificOutcome.NEGATIVE_RESULT
    )
    return foundation, confirmatory


def test_child_paper_binds_every_claim_citation_and_display(
    tmp_path: Path,
    paper_inputs: tuple[Path, Path],
) -> None:
    foundation, confirmatory = paper_inputs
    output = tmp_path / "paper"
    reproduction = tmp_path / "paper-reproduction"

    result = build_task2612_child_paper(
        foundation_dir=foundation,
        confirmatory_dir=confirmatory,
        output_dir=output,
        reproduction_dir=reproduction,
        compile_pdf=False,
    )
    entailment = MechanismClaimEntailmentReport.model_validate_json(
        (output / "manuscript" / "evidence" / "entailment-audit.json").read_text(
            encoding="utf-8"
        )
    )
    citation = MechanismCitationAudit.model_validate_json(
        (output / "manuscript" / "audit" / "citation-audit.json").read_text(
            encoding="utf-8"
        )
    )
    display = MechanismFigureTableAudit.model_validate_json(
        (output / "manuscript" / "audit" / "figure-table-audit.json").read_text(
            encoding="utf-8"
        )
    )
    paper_audit = MechanismPaperAudit.model_validate_json(
        (output / "audit" / "paper-audit.json").read_text(encoding="utf-8")
    )
    paper_reproduction = MechanismPaperReproductionReport.model_validate_json(
        (output / "reproduction" / "paper-reproduction.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.claim_coverage_complete is True
    assert result.paper_quality_passed is False
    assert entailment.passed is True
    assert entailment.registered_claim_count == 51
    assert entailment.rendered_material_paragraph_count == 51
    assert citation.passed is True
    assert citation.source_count == 14
    assert citation.live_source_check_performed is False
    assert set(citation.area_source_counts) == {
        "claim_evidence_alignment",
        "generated_code_security",
        "scientific_agent_evaluation",
        "selective_factuality",
    }
    assert display.passed is True
    assert display.figure_count == 5
    assert display.table_count == 1
    assert display.checks["every_figure_has_description_claim"] is True
    assert display.checks["endpoint_counts_match_table"] is True
    assert paper_reproduction.passed is True
    assert paper_reproduction.mismatched_source_files == []
    assert paper_audit.faithful_negative_result_reported is True
    assert paper_audit.positive_contribution_supported is False
    assert paper_audit.submission_readiness_granted is False
    assert paper_audit.external_submission_authorized is False


def test_child_paper_status_is_idempotent_and_tamper_fails_closed(
    tmp_path: Path,
    paper_inputs: tuple[Path, Path],
) -> None:
    foundation, confirmatory = paper_inputs
    output = tmp_path / "paper"
    result = build_task2612_child_paper(
        foundation_dir=foundation,
        confirmatory_dir=confirmatory,
        output_dir=output,
        reproduction_dir=tmp_path / "paper-reproduction",
        compile_pdf=False,
    )
    before = {
        path.relative_to(output).as_posix(): file_hash(path)
        for path in output.rglob("*")
        if path.is_file()
    }

    loaded = load_task2612_child_paper(output)
    rebuilt = build_task2612_child_paper(
        foundation_dir=foundation,
        confirmatory_dir=confirmatory,
        output_dir=output,
        reproduction_dir=tmp_path / "ignored-reproduction",
        compile_pdf=True,
        live_source_check=True,
    )
    after = {
        path.relative_to(output).as_posix(): file_hash(path)
        for path in output.rglob("*")
        if path.is_file()
    }
    assert loaded.manifest_hash == result.manifest_hash
    assert rebuilt.manifest_hash == result.manifest_hash
    assert before == after

    with (output / "manuscript" / "manuscript.md").open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write("\nUnsupported positive result.\n")
    with pytest.raises(MechanismPaperIntegrityError, match="artifact index"):
        load_task2612_child_paper(output)


def test_named_work_claim_requires_an_inline_source_token() -> None:
    with pytest.raises(ValidationError, match="source token"):
        MechanismPaperClaimRecord(
            claim_id="missing-source-token",
            claim_kind=ClaimKind.NAMED_PRIOR_WORK,
            section="Related Work",
            claim_text="A named paper reports an adjacent result.",
            evidence_ids=["literature-source-001"],
            citation_source_ids=["source-001"],
        )


def test_loader_revalidates_reindexed_frozen_endpoint(
    tmp_path: Path,
    paper_inputs: tuple[Path, Path],
) -> None:
    foundation, confirmatory = paper_inputs
    output = tmp_path / "paper"
    build_task2612_child_paper(
        foundation_dir=foundation,
        confirmatory_dir=confirmatory,
        output_dir=output,
        reproduction_dir=tmp_path / "paper-reproduction",
        compile_pdf=False,
    )
    endpoint_path = output / "frozen" / "endpoint.json"
    endpoint_payload = json.loads(endpoint_path.read_text(encoding="utf-8"))
    endpoint_payload["failure_codes"] = []
    endpoint_path.write_text(
        json.dumps(endpoint_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = output / "paper-manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["artifact_file_sha256s"]["frozen/endpoint.json"] = file_hash(
        endpoint_path
    )
    manifest_payload["manifest_hash"] = canonical_sha256(
        {
            key: value
            for key, value in manifest_payload.items()
            if key != "manifest_hash"
        }
    )
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="endpoint failure codes"):
        load_task2612_child_paper(output)
