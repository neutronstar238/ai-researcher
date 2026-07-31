from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import benchmark_validity_protocol as protocol_module
from autoresearch.research.benchmark_validity_protocol import (
    BENCHMARK_VALIDITY_MARKDOWN_FILENAME,
    BENCHMARK_VALIDITY_PROTOCOL_FILENAME,
    AdmissionGate,
    BenchmarkValidityIntegrityError,
    BenchmarkValidityProtocol,
    BenchmarkValidityProtocolFreezeReport,
    BenchmarkValidityProtocolProjection,
    ConstructStratum,
    EvidenceState,
    ProtocolReplayCertificate,
    ProtocolReplayObservation,
    SearchLens,
    SearchSourceId,
    benchmark_validity_protocol_json_schemas,
    build_benchmark_validity_protocol,
    build_protocol_replay_payload,
    load_benchmark_validity_protocol_freeze,
    render_benchmark_validity_protocol_markdown,
    run_benchmark_validity_protocol_replay,
    write_benchmark_validity_protocol_freeze,
)
from autoresearch.research.workload_qualified_opportunity import InterpreterRuntime

FROZEN_AT = datetime(2026, 7, 31, 4, 0, tzinfo=timezone.utc)
PARENT_COMMIT = "b890aef"
ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATH = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
RUNNER_PATH = (
    ROOT
    / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol() -> BenchmarkValidityProtocol:
    return build_benchmark_validity_protocol(
        frozen_at=FROZEN_AT,
        parent_git_commit=PARENT_COMMIT,
        protocol_source_sha256=_file_hash(SOURCE_PATH),
        frozen_runner_sha256=_file_hash(RUNNER_PATH),
    )


def _runtime(role_id: str, locator: str) -> InterpreterRuntime:
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=canonical_sha256(locator),
        executable_sha256="1" * 64 if role_id == "reviewer-a" else "2" * 64,
        python_version="Python 3.10.test",
    )


def _certificate(
    protocol: BenchmarkValidityProtocol,
    projection: BenchmarkValidityProtocolProjection,
) -> ProtocolReplayCertificate:
    output_contract_hash = "3" * 64
    observations = [
        ProtocolReplayObservation.create(
            runtime=_runtime("reviewer-a", "clean-interpreter-a"),
            projection_sha256=projection.projection_sha256,
            output_file_sha256="4" * 64,
            output_contract_sha256=output_contract_hash,
        ),
        ProtocolReplayObservation.create(
            runtime=_runtime("reviewer-b", "clean-interpreter-b"),
            projection_sha256=projection.projection_sha256,
            output_file_sha256="4" * 64,
            output_contract_sha256=output_contract_hash,
        ),
    ]
    return ProtocolReplayCertificate.create(
        protocol_hash=protocol.protocol_hash,
        projection_sha256=projection.projection_sha256,
        replay_input_sha256="5" * 64,
        frozen_runner_sha256=protocol.freeze_anchor.frozen_runner_sha256,
        observations=observations,
    )


def _report() -> BenchmarkValidityProtocolFreezeReport:
    protocol = _protocol()
    projection = BenchmarkValidityProtocolProjection.create(protocol)
    return BenchmarkValidityProtocolFreezeReport.create(
        protocol=protocol,
        projection=projection,
        replay_certificate=_certificate(protocol, projection),
    )


def test_protocol_is_deterministic_result_free_and_excludes_all_pilots() -> None:
    first = _protocol()
    second = _protocol()

    assert first.protocol_hash == second.protocol_hash
    assert first.canonical_json() == second.canonical_json()
    assert len(first.query_bindings) == len(SearchSourceId) * len(SearchLens) == 28
    assert {item.source_id for item in first.search_sources} == set(SearchSourceId)
    assert {item.lens for item in first.query_bindings} == set(SearchLens)
    assert set(first.construct_strata) == set(ConstructStratum)
    assert first.release_unit_plan.primary_non_pilot_release_target == 20
    assert first.release_unit_plan.study_unit == "fixed-revision benchmark release"
    assert first.release_unit_plan.independence_unit == "unique benchmark family"
    assert all(not item.primary_cohort_eligible for item in first.pilot_boundaries)
    assert {item.release_id for item in first.pilot_boundaries} == {
        "autosdt-5k",
        "scienceagentbench",
        "core-bench",
        "qrdata",
    }
    assert first.search_execution_started is False
    assert first.extracted_record_count == 0
    assert first.benchmark_outcomes_accessed is False
    assert first.candidate_model_calls is False
    assert first.research_question_issued is False
    assert first.confirmation_panel_created is False
    assert first.public_release_authorized is False
    assert first.external_submission_authorized is False


def test_protocol_freezes_unknown_semantics_human_coding_and_descriptive_endpoints() -> None:
    protocol = _protocol()
    definitions = {item.state: item for item in protocol.evidence_code_definitions}

    assert set(definitions) == set(EvidenceState)
    assert definitions[EvidenceState.VERIFIED_PASS].counts_as_admission_pass
    assert not any(
        item.counts_as_admission_pass
        for state, item in definitions.items()
        if state is not EvidenceState.VERIFIED_PASS
    )
    assert {
        state
        for state, item in definitions.items()
        if item.counts_as_determinate_coverage
    } == {EvidenceState.VERIFIED_PASS, EvidenceState.VERIFIED_FAIL}
    assert len(protocol.human_coding_plan.reviewer_roles) == 2
    assert protocol.human_coding_plan.adjudicator_role not in (
        protocol.human_coding_plan.reviewer_roles
    )
    assert protocol.human_coding_plan.actual_human_identities_assigned is False
    assert protocol.human_coding_plan.execution_blocked_until_humans_assigned
    assert protocol.human_coding_plan.exact_agreement_threshold == 0.9
    assert protocol.human_coding_plan.cohen_kappa_threshold_when_estimable == 0.8
    assert protocol.human_coding_plan.llm_screening_decision_allowed is False
    assert len(protocol.human_coding_plan.critical_dual_code_field_ids) >= 8
    assert {item.endpoint_id for item in protocol.primary_endpoints} == {
        "per-gate-pass-rates",
        "complete-conjunction-pass-rate",
        "task-to-independent-unit-compression",
        "critical-missing-evidence-rate",
    }
    assert all(not item.causal_interpretation_allowed for item in protocol.primary_endpoints)
    assert all(not item.mechanism_effect_claim_allowed for item in protocol.stop_rules)


def test_protocol_requires_every_source_lens_pair_and_rejects_pilot_leakage() -> None:
    protocol = _protocol()
    payload = protocol.model_dump(mode="json")
    payload["query_bindings"] = payload["query_bindings"][:-1]
    payload["protocol_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "protocol_hash"}
    )
    with pytest.raises(ValidationError, match="at least 28 items"):
        BenchmarkValidityProtocol.model_validate(payload)

    payload = protocol.model_dump(mode="json")
    payload["pilot_boundaries"][0]["primary_cohort_eligible"] = True
    payload["protocol_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "protocol_hash"}
    )
    with pytest.raises(ValidationError, match="Input should be False"):
        BenchmarkValidityProtocol.model_validate(payload)


def test_dependency_free_probe_accepts_only_the_result_free_projection(
    tmp_path: Path,
) -> None:
    protocol = _protocol()
    projection = BenchmarkValidityProtocolProjection.create(protocol)
    replay_payload = build_protocol_replay_payload(projection)
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(replay_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["projection_sha256"] == projection.projection_sha256
    assert output["extracted_record_count"] == 0
    assert output["candidate_model_calls"] is False

    replay_payload["projection"]["extracted_record_count"] = 1
    replay_payload["expected_projection_sha256"] = canonical_sha256(
        replay_payload["projection"]
    )
    input_path.write_text(json.dumps(replay_payload), encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert rejected.returncode != 0
    assert "cannot contain extracted benchmark records" in rejected.stderr


def test_two_interpreter_replay_certificate_requires_exact_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    protocol = _protocol()

    def fake_probe(*, role_id: str, executable: Path) -> InterpreterRuntime:
        return _runtime(role_id, str(executable))

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--output") + 1])
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        projection = payload["projection"]
        output = {
            "schema_version": "frozen-benchmark-validity-protocol-probe-v1",
            "protocol_id": projection["protocol_id"],
            "protocol_hash": projection["protocol_hash"],
            "projection_sha256": payload["expected_projection_sha256"],
            "query_binding_count": projection["query_binding_count"],
            "extracted_record_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
        }
        output["output_sha256"] = canonical_sha256(output)
        output_path.write_text(
            json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(protocol_module, "probe_interpreter_runtime", fake_probe)
    monkeypatch.setattr(protocol_module.subprocess, "run", fake_run)
    projection, certificate = run_benchmark_validity_protocol_replay(
        protocol=protocol,
        runner_path=RUNNER_PATH,
        interpreters={
            "reviewer-a": tmp_path / "python-a.exe",
            "reviewer-b": tmp_path / "python-b.exe",
        },
        work_dir=tmp_path / "replay",
    )

    assert certificate.projection_sha256 == projection.projection_sha256
    assert certificate.exact_projection_match
    assert certificate.distinct_interpreter_installations
    assert len(certificate.observations) == 2
    assert certificate.extracted_record_count == 0
    assert certificate.benchmark_outcomes_accessed is False


def test_persistence_schema_markdown_and_tamper_detection(tmp_path: Path) -> None:
    report = _report()
    output_dir = tmp_path / "freeze"
    manifest = write_benchmark_validity_protocol_freeze(output_dir, report)
    loaded_report, loaded_manifest = load_benchmark_validity_protocol_freeze(output_dir)

    assert loaded_report.report_hash == report.report_hash
    assert loaded_manifest.manifest_hash == manifest.manifest_hash
    schemas = benchmark_validity_protocol_json_schemas()
    assert "BenchmarkAdmissionCard" in schemas
    assert "SearchExecutionLogEntry" in schemas
    assert "ScreeningRecord" in schemas
    assert schemas == benchmark_validity_protocol_json_schemas()
    markdown = render_benchmark_validity_protocol_markdown(report)
    assert "pre-extraction protocol" in markdown
    assert "Current four releases" in markdown
    assert "Candidate model calls: `false`" in markdown
    assert (output_dir / BENCHMARK_VALIDITY_MARKDOWN_FILENAME).is_file()

    protocol_path = output_dir / BENCHMARK_VALIDITY_PROTOCOL_FILENAME
    protocol_path.write_text(
        protocol_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(BenchmarkValidityIntegrityError, match="artifact hash mismatch"):
        load_benchmark_validity_protocol_freeze(output_dir)


def test_protocol_exposes_all_admission_gates_and_no_causal_shortcut() -> None:
    report = _report()
    schema = benchmark_validity_protocol_json_schemas()["BenchmarkAdmissionCard"]
    gate_enum = schema["$defs"]["AdmissionGate"]["enum"]

    assert set(gate_enum) == {item.value for item in AdmissionGate}
    assert len(gate_enum) == 12
    assert report.mechanism_effect_claim_authorized is False
    assert report.next_action == "assign-humans-then-execute-frozen-census"
    assert "causal critic" not in " ".join(
        endpoint.estimand for endpoint in report.protocol.primary_endpoints
    ).lower()
