from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.campaign.mdbench import (
    MDBenchAdapterConfig,
    MDBenchCampaignAdapter,
    audit_mdbench_holdout,
    build_mdbench_campaign_matrix,
    load_mdbench_holdout_audit,
)
from autoresearch.campaign.models import (
    CampaignTrack,
    FailureKind,
    RoundDevelopmentContext,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchExperimentMatrix,
)
from autoresearch.competition.preregistration import (
    MDBenchPreregistrationError,
    validate_mdbench_preregistration,
)
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult
from autoresearch.schemas import data_hash, file_hash


def _archive(tmp_path: Path, *, unused_count: int = 14) -> Path:
    systems = ("used-a", "used-b", *tuple(f"fresh-{index:02d}" for index in range(unused_count)))
    artifacts = tuple(
        MDBenchDatasetArtifact(
            relative_path=f"processed/data/ode/{system}/{system}-{condition}.npz",
            data_type="ode",
            system_name=system,
            condition=condition,
            size_bytes=16,
            sha256=data_hash(f"{system}:{condition}"),
        )
        for system in systems
        for condition in ("clean", "snr_20")
    )
    archive_path = tmp_path / "archive-manifest.json"
    inventory_hash = canonical_model_hash(
        {
            "archive_sha256": data_hash("archive"),
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        }
    )
    manifest = MDBenchArchiveManifest(
        repository_url="https://example.invalid/mdbench",
        benchmark_revision="f81813e760325589737fe3311ac8199ecc64188a",
        dataset_doi="10.5281/zenodo.17611099",
        dataset_license="CC-BY-4.0",
        archive_path=(tmp_path / "processed.zip").as_posix(),
        archive_size_bytes=32,
        archive_md5="1" * 32,
        archive_sha256=data_hash("archive"),
        extracted_root=(tmp_path / "extracted").as_posix(),
        artifacts=artifacts,
        ode_systems=systems,
        pde_systems=(),
        noise_conditions=("clean", "snr_20"),
        inventory_hash=inventory_hash,
        output_path=archive_path.as_posix(),
    )
    write_json_model(archive_path, manifest)
    return archive_path


def _historical(tmp_path: Path) -> tuple[Path, Path]:
    first = tmp_path / "historical-first.json"
    second = tmp_path / "historical-second.json"
    first.write_text(
        json.dumps({"systems": [{"system_name": "used-a"}]}),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps({"nested": {"attempt": {"system_name": "used-b"}}}),
        encoding="utf-8",
    )
    return first, second


def test_holdout_audit_reserves_two_disjoint_panels_and_detects_tampering(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path)
    historical = _historical(tmp_path)
    output = tmp_path / "holdout-audit.json"

    audit = audit_mdbench_holdout(archive, historical, output)

    assert audit.route_decision == "route_a"
    assert len(audit.selected_panels["1"]) == 6
    assert len(audit.selected_panels["2"]) == 6
    assert not set(audit.selected_panels["1"]) & set(audit.selected_panels["2"])
    assert not {"used-a", "used-b"} & set(audit.eligible_ode_systems)
    assert audit_mdbench_holdout(archive, historical, output) == audit

    historical[0].write_text(
        json.dumps({"systems": [{"system_name": "fresh-00"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="historical metadata changed"):
        load_mdbench_holdout_audit(output)


def test_holdout_audit_requires_route_b_when_capacity_is_insufficient(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path, unused_count=5)
    audit = audit_mdbench_holdout(
        archive,
        _historical(tmp_path),
        tmp_path / "insufficient.json",
    )

    assert audit.route_decision == "route_b"
    assert audit.selected_panels == {}


def test_campaign_matrix_is_complete_and_hash_bound(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    matrix_path = tmp_path / "matrix.json"
    matrix = build_mdbench_campaign_matrix(
        archive_manifest_path=archive,
        output_path=matrix_path,
        development_systems=("used-a", "used-b"),
        unseen_systems=tuple(f"fresh-{index:02d}" for index in range(6)),
        seeds=(131, 137, 139),
        mechanism_family="noise_conditioned_ensemble_sindy",
    )

    assert matrix.schema_version == "mdbench-campaign-matrix-v1"
    assert len(matrix.systems) == 8
    assert len(matrix.methods) == 5
    assert len(matrix.attempts) == 240
    validate_mdbench_preregistration(matrix)

    tampered = MDBenchExperimentMatrix.model_validate_json(
        matrix_path.read_text(encoding="utf-8")
    ).model_copy(update={"selection_policy": "post-result cherry-pick"})
    with pytest.raises(MDBenchPreregistrationError, match="matrix hash mismatch"):
        validate_mdbench_preregistration(tampered)


def test_local_qwen_context_excludes_current_unseen_and_falls_back_deterministically(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path)
    historical = _historical(tmp_path)
    audit = audit_mdbench_holdout(
        archive,
        historical,
        tmp_path / "holdout.json",
    )
    root = tmp_path / "root-negative.json"
    root.write_text(
        json.dumps(
            {
                "decision": "negative_result",
                "negative_reasons": ["noisy bootstrap CI crossed zero"],
                "report_hash": data_hash("root-negative"),
            }
        ),
        encoding="utf-8",
    )
    llm_config = tmp_path / "ollama.yaml"
    llm_config.write_text(
        "\n".join(
            (
                "deployment:",
                "  environment: local",
                "  llm:",
                "    provider: ollama-openai-compatible",
                "    base_url: http://127.0.0.1:11434/v1",
                "    model_name: qwen3.5:9b",
                "    api_key_env: AUTORESEARCH_LOCAL_OLLAMA_API_KEY",
                "    request_timeout_seconds: 30",
            )
        ),
        encoding="utf-8",
    )
    captured: list[list[dict[str, str]]] = []

    def completion(**kwargs: object) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        captured.append(messages)
        system = messages[0]["content"]
        if "failure-diagnosis" in system:
            parsed = {
                "failure_kind": FailureKind.ROOT_NEGATIVE_RESULT.value,
                "causal_hypothesis": "noise amplified pointwise derivatives",
                "required_mechanism_change": "use coefficient ensembles",
                "observations": ["parent CI crossed zero"],
                "constraints": ["keep unseen sealed"],
            }
        else:
            parsed = {
                "title": "Noise-conditioned coefficient ensemble",
                "statement": "The mechanism should reduce noisy derivative error.",
                "mechanism_family": "noise_conditioned_ensemble_sindy",
                "mechanism_change": "replace weak support refitting",
                "repair_rationale": "reduce coefficient variance",
                "predicted_effect": "development gain above 15 percent",
                "falsification_conditions": ["unseen CI is not positive"],
            }
        return LLMJsonCompletionResult(
            provider="ollama-openai-compatible",
            base_url="http://127.0.0.1:11434/v1",
            model_name="qwen3.5:9b",
            endpoint="http://127.0.0.1:11434/v1/chat/completions",
            response_text=json.dumps(parsed),
            parsed_json=parsed,
            usage={},
            temperature=0.0,
        )

    config = MDBenchAdapterConfig(
        archive_manifest_path=archive.as_posix(),
        historical_metadata_paths=tuple(path.as_posix() for path in historical),
        root_adjudication_path=root.as_posix(),
        root_adjudication_sha256=file_hash(root),
        holdout_audit_path=Path(audit.output_path).as_posix(),
        holdout_audit_hash=audit.audit_hash or "",
        llm_config_path=llm_config.as_posix(),
        development_systems=("used-a", "used-b"),
        round_mechanisms={
            "1": "noise_conditioned_ensemble_sindy",
            "2": "spline_group_sparse_sindy",
        },
    )
    adapter = MDBenchCampaignAdapter(
        tmp_path / "evidence",
        config,
        completion=completion,
    )
    context = RoundDevelopmentContext(
        campaign_id="campaign",
        round_id="round-001",
        round_number=1,
        track=CampaignTrack.SCIENTIFIC_ML_METHOD,
        parent_result_hash=data_hash("root-negative"),
        historical_evidence_refs=(root.as_posix(),),
        development_data_refs=(
            "mdbench:ode:used-a:development",
            "mdbench:ode:used-b:development",
        ),
        seeds=(131, 137, 139),
        candidate_mechanism_families=("noise_conditioned_ensemble_sindy",),
        primary_metric="failure_aware_snr20_relative_improvement",
        deadline=datetime(2099, 8, 15, tzinfo=timezone.utc),
    )
    observation = adapter.observe(context)
    diagnosis = adapter.diagnose(context, observation)
    proposal = adapter.propose(context, diagnosis)

    assert proposal.mechanism_family == "noise_conditioned_ensemble_sindy"
    prompt_text = json.dumps(captured, ensure_ascii=False)
    for system in audit.selected_panels["1"]:
        assert f"mdbench:ode:{system}:unseen" not in prompt_text

    def failed_completion(**_kwargs: object) -> LLMJsonCompletionResult:
        raise LLMClientError("synthetic local JSON failure")

    fallback_adapter = MDBenchCampaignAdapter(
        tmp_path / "fallback-evidence",
        config,
        completion=failed_completion,
    )
    fallback_diagnosis = fallback_adapter.diagnose(
        context,
        fallback_adapter.observe(context),
    )
    assert "weak-form/support-stability" in fallback_diagnosis.causal_hypothesis or (
        "Pointwise" in fallback_diagnosis.causal_hypothesis
    )
    evidence = json.loads(
        (
            tmp_path
            / "fallback-evidence"
            / "round-001"
            / "local-qwen-diagnose.json"
        ).read_text(encoding="utf-8")
    )
    assert evidence["used_fallback"] is True
    assert "synthetic local JSON failure" in evidence["failure"]
