from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    CapabilityGrant,
    CompetitionRunSpec,
    CycleOutcome,
    EvidenceGateReport,
    ExperimentProtocol,
    HypothesisProposal,
    ManifestIntegrityError,
    ResearchCycleService,
    TopicCandidate,
    load_cycle_manifest,
    validate_cycle_evidence,
)
from autoresearch.schemas import data_hash


@pytest.fixture(scope="module")
def completed_cycle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("competition-cycle")
    service = ResearchCycleService(
        output_root=root / "runs",
        vault_root=root / "vault",
    )
    result = service.run(
        CompetitionRunSpec(
            run_id="gate-a-characterization",
            project_id="competition-test",
            timeout_seconds=20,
        )
    )
    assert result.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    return Path(result.cycle_dir)


def test_unattended_gate_a_cycle_executes_and_remains_release_blocked(
    completed_cycle: Path,
) -> None:
    manifest = load_cycle_manifest(completed_cycle / "cycle-manifest.json")
    summary = json.loads((completed_cycle / "cycle-summary.json").read_text(encoding="utf-8"))
    selection = summary["selection"]
    gate = EvidenceGateReport.model_validate_json(
        (completed_cycle / "evidence-gate.json").read_text(encoding="utf-8")
    )

    assert manifest.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    assert manifest.human_intervention_count == 0
    assert manifest.access_request_ids == ()
    assert len(manifest.attempts) == 3
    assert {attempt.seed for attempt in manifest.attempts} == {11, 23, 37}
    assert all(attempt.status.value == "succeeded" for attempt in manifest.attempts)
    assert len(set(manifest.code_hashes.values())) == 1
    assert len(set(manifest.data_hashes.values())) == 3
    assert len(selection["feasibility"]) == 3
    assert all(Path(row["evidence_path"]).is_file() for row in selection["feasibility"])
    assert gate.passed is True
    assert gate.release_allowed is False
    assert manifest.release_eligible is False
    assert "characterization fixture" in " ".join(gate.warnings)
    assert Path(manifest.artifact_paths["vault_note"]).is_file()


def test_completed_cycle_resume_is_idempotent(completed_cycle: Path) -> None:
    before = load_cycle_manifest(completed_cycle / "cycle-manifest.json")
    metrics_mtimes = {
        attempt.seed: Path(attempt.metrics_path or "").stat().st_mtime_ns
        for attempt in before.attempts
    }
    service = ResearchCycleService(
        output_root=completed_cycle.parent,
        vault_root=completed_cycle.parents[1] / "vault",
    )

    result = service.resume(completed_cycle)
    after = load_cycle_manifest(completed_cycle / "cycle-manifest.json")

    assert result.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    assert [attempt.attempt_id for attempt in after.attempts] == [
        attempt.attempt_id for attempt in before.attempts
    ]
    assert metrics_mtimes == {
        attempt.seed: Path(attempt.metrics_path or "").stat().st_mtime_ns
        for attempt in after.attempts
    }


def test_evidence_gate_blocks_candidate_mismatch_and_constant_metrics(
    completed_cycle: Path,
) -> None:
    manifest = load_cycle_manifest(completed_cycle / "cycle-manifest.json")
    topic = TopicCandidate.model_validate_json(
        (completed_cycle / "selected-topic.json").read_text(encoding="utf-8")
    )
    hypothesis = HypothesisProposal.model_validate_json(
        (completed_cycle / "hypothesis.json").read_text(encoding="utf-8")
    )
    protocol = ExperimentProtocol.model_validate_json(
        (completed_cycle / "experiment-protocol.json").read_text(encoding="utf-8")
    )
    constant_metrics = dict.fromkeys(manifest.attempts[0].metrics, 1.0)
    forged_first = manifest.attempts[0].model_copy(
        update={
            "topic_id": "topic_unrelated_demo",
            "metrics": constant_metrics,
            "metrics_hash": data_hash(constant_metrics),
        }
    )
    forged_manifest = manifest.model_copy(
        update={"attempts": (forged_first, *manifest.attempts[1:])}
    )

    report = validate_cycle_evidence(
        manifest=forged_manifest,
        topic=topic,
        hypothesis=hypothesis,
        protocol=protocol,
    )

    assert report.passed is False
    assert any("candidate was not executed" in failure for failure in report.failures)
    assert any("constant metrics" in failure for failure in report.failures)
    assert any("metrics topic_id does not match" in failure for failure in report.failures)


def test_evidence_gate_blocks_persisted_metric_tampering(
    completed_cycle: Path,
    tmp_path: Path,
) -> None:
    manifest = load_cycle_manifest(completed_cycle / "cycle-manifest.json")
    topic = TopicCandidate.model_validate_json(
        (completed_cycle / "selected-topic.json").read_text(encoding="utf-8")
    )
    hypothesis = HypothesisProposal.model_validate_json(
        (completed_cycle / "hypothesis.json").read_text(encoding="utf-8")
    )
    protocol = ExperimentProtocol.model_validate_json(
        (completed_cycle / "experiment-protocol.json").read_text(encoding="utf-8")
    )
    source_dir = Path(manifest.attempts[0].metrics_path or "").parent
    forged_dir = tmp_path / "forged-attempt"
    shutil.copytree(source_dir, forged_dir)
    metrics_path = forged_dir / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["metrics"]["derivative_nmse"] = 999.0
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    forged_attempt = manifest.attempts[0].model_copy(
        update={"metrics_path": metrics_path.as_posix()}
    )
    forged_manifest = manifest.model_copy(
        update={"attempts": (forged_attempt, *manifest.attempts[1:])}
    )

    report = validate_cycle_evidence(
        manifest=forged_manifest,
        topic=topic,
        hypothesis=hypothesis,
        protocol=protocol,
    )

    assert report.passed is False
    assert any("metrics artifact hash mismatch" in item for item in report.failures)


def test_manifest_hash_detects_tampering(completed_cycle: Path, tmp_path: Path) -> None:
    payload = json.loads(
        (completed_cycle / "cycle-manifest.json").read_text(encoding="utf-8")
    )
    payload["release_eligible"] = True
    tampered = tmp_path / "cycle-manifest.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ManifestIntegrityError, match="hash mismatch"):
        load_cycle_manifest(tampered)


def test_missing_capability_grant_creates_access_request_then_resumes(tmp_path: Path) -> None:
    spec = CompetitionRunSpec(
        run_id="grant-resume",
        project_id="grant-test",
        capability_grant_id="grant_expected",
        timeout_seconds=20,
    )
    first_service = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
    )
    first = first_service.run(spec)

    assert first.outcome is CycleOutcome.ACCESS_REQUIRED
    assert first.access_request_count == 1
    assert first.human_intervention_count == 0

    first_manifest = load_cycle_manifest(Path(first.manifest_path))
    request_path = next(
        Path(path)
        for key, path in first_manifest.artifact_paths.items()
        if key.startswith("access_request_")
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert request_payload["kind"] == "capability_grant"
    repeated = first_service.resume(Path(first.cycle_dir))
    repeated_manifest = load_cycle_manifest(Path(first.manifest_path))
    assert repeated.access_request_count == 1
    assert repeated_manifest.access_request_ids == first_manifest.access_request_ids

    grant = CapabilityGrant(
        grant_id="grant_expected",
        valid_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    resumed = ResearchCycleService(
        output_root=tmp_path / "runs",
        vault_root=tmp_path / "vault",
        capability_grant=grant,
    ).resume(Path(first.cycle_dir))

    assert resumed.outcome is CycleOutcome.DEVELOPMENT_SMOKE_PASSED
    assert resumed.access_request_count == 1
    assert resumed.human_intervention_count == 0


def test_capability_grant_accepts_env_names_and_rejects_secret_values() -> None:
    grant = CapabilityGrant(
        api_env_vars=("DASHSCOPE_API_KEY",),
        valid_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert grant.api_env_vars == ("DASHSCOPE_API_KEY",)

    with pytest.raises(ValidationError, match="environment variable names only"):
        CapabilityGrant(
            api_env_vars=("DASHSCOPE_API_KEY=sk-secret",),
            valid_until=datetime.now(timezone.utc) + timedelta(days=1),
        )
