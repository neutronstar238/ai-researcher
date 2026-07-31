from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import benchmark_validity_human_handoff as handoff_module
from autoresearch.research.benchmark_validity_human_handoff import (
    PARENT_ERRATUM_COMMIT,
    PARENT_ERRATUM_HASH,
    PARENT_ERRATUM_MANIFEST_HASH,
    PARENT_ERRATUM_PROJECTION_HASH,
    PARENT_ERRATUM_REPLAY_HASH,
    PARENT_ERRATUM_REPORT_HASH,
    PARENT_ERRATUM_SOURCE_SHA256,
    PARENT_INTEGRATED_HARNESS_SOURCE_SHA256,
    AdjudicatorAccessReceipt,
    BenchmarkHumanReviewHandoffReport,
    BlindedReviewPacketTemplate,
    DualLockBarrierReceipt,
    HumanReviewHandoffIntegrityError,
    HumanReviewRole,
    HumanRoleAssignmentReceipt,
    ParentPaginationErratumEvidence,
    PublicProjectionPolicy,
    ReviewerLockReceipt,
    build_human_review_handoff,
    build_human_review_handoff_projection,
    build_human_review_handoff_replay_payload,
    load_human_review_handoff,
    run_human_review_handoff_replay,
    validate_human_role_assignments,
    write_human_review_handoff,
)
from autoresearch.research.benchmark_validity_protocol import (
    BenchmarkValidityProtocol,
    build_benchmark_validity_protocol,
)
from autoresearch.research.workload_qualified_opportunity import InterpreterRuntime

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
PROTOCOL_RUNNER = (
    ROOT / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
HANDOFF_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_human_handoff.py"
HANDOFF_RUNNER = (
    ROOT
    / "src/autoresearch/research/assets/"
    "frozen_benchmark_validity_human_handoff_probe_v1.py"
)
FROZEN_AT = datetime(2026, 7, 31, 9, 38, 52, 843137, tzinfo=timezone.utc)
HANDOFF_AT = datetime(2026, 7, 31, 19, 30, tzinfo=timezone.utc)
PROTOCOL_PARENT_COMMIT = "b890aef4b5f254275f9edb2509fe6f1b4a0ae9f2"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol() -> BenchmarkValidityProtocol:
    return build_benchmark_validity_protocol(
        frozen_at=FROZEN_AT,
        parent_git_commit=PROTOCOL_PARENT_COMMIT,
        protocol_source_sha256=_file_hash(PROTOCOL_SOURCE),
        frozen_runner_sha256=_file_hash(PROTOCOL_RUNNER),
    )


def _parent_evidence() -> ParentPaginationErratumEvidence:
    payload = {
        "schema_version": "benchmark-human-handoff-parent-erratum-v1",
        "focused_parent_commit": PARENT_ERRATUM_COMMIT,
        "protocol_hash": _protocol().protocol_hash,
        "erratum_hash": PARENT_ERRATUM_HASH,
        "report_hash": PARENT_ERRATUM_REPORT_HASH,
        "projection_sha256": PARENT_ERRATUM_PROJECTION_HASH,
        "replay_certificate_hash": PARENT_ERRATUM_REPLAY_HASH,
        "manifest_hash": PARENT_ERRATUM_MANIFEST_HASH,
        "erratum_source_sha256": PARENT_ERRATUM_SOURCE_SHA256,
        "integrated_harness_source_sha256": PARENT_INTEGRATED_HARNESS_SOURCE_SHA256,
    }
    return ParentPaginationErratumEvidence.model_validate(
        {**payload, "evidence_hash": canonical_sha256(payload)}
    )


def _handoff():
    return build_human_review_handoff(
        protocol=_protocol(),
        parent_erratum=_parent_evidence(),
        frozen_at=HANDOFF_AT,
    )


def _runtime(role_id: str) -> InterpreterRuntime:
    suffix = "a" if role_id == "clean-runtime-a" else "b"
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=canonical_sha256(f"handoff-python-{suffix}"),
        executable_sha256=("5" if suffix == "a" else "6") * 64,
        python_version="Python 3.10.test",
    )


def _assignment(
    role: HumanReviewRole,
    person: str,
    marker: str,
    *,
    handoff=None,
) -> HumanRoleAssignmentReceipt:
    checked_handoff = handoff or _handoff()
    return HumanRoleAssignmentReceipt.create(
        handoff=checked_handoff,
        role=role,
        opaque_person_id=person,
        private_assignment_record_sha256=marker * 64,
        identity_evidence_sha256=chr(ord(marker) + 1) * 64,
        qualification_evidence_sha256=chr(ord(marker) + 2) * 64,
        conflict_disclosure_sha256=chr(ord(marker) + 3) * 64,
        role_consent_sha256=chr(ord(marker) + 4) * 64,
        owner_verification_attestation_sha256=chr(ord(marker) + 5) * 64,
        accepted_at=HANDOFF_AT,
    )


def _assignments(*, handoff=None) -> list[HumanRoleAssignmentReceipt]:
    checked_handoff = handoff or _handoff()
    return [
        _assignment(
            HumanReviewRole.REVIEWER_A,
            "person-alpha",
            "1",
            handoff=checked_handoff,
        ),
        _assignment(
            HumanReviewRole.REVIEWER_B,
            "person-beta",
            "2",
            handoff=checked_handoff,
        ),
        _assignment(
            HumanReviewRole.ADJUDICATOR,
            "person-gamma",
            "3",
            handoff=checked_handoff,
        ),
    ]


def _lock(
    *,
    handoff,
    assignment: HumanRoleAssignmentReceipt,
    candidate_set: str,
    locked_at: datetime,
    marker: str,
) -> ReviewerLockReceipt:
    assert assignment.role in {HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B}
    return ReviewerLockReceipt.create(
        handoff=handoff,
        assignment=assignment,
        candidate_set_sha256=candidate_set,
        screening_work_sha256=chr(ord(marker) + 1) * 64,
        critical_coding_work_sha256=chr(ord(marker) + 2) * 64,
        locked_at=locked_at,
    )


def test_handoff_freezes_empty_roles_private_separation_and_blinded_packets() -> None:
    handoff = _handoff()
    projection = build_human_review_handoff_projection(handoff)

    assert handoff.parent_erratum.focused_parent_commit == PARENT_ERRATUM_COMMIT
    assert handoff.actual_human_identity_count == 0
    assert handoff.role_assignment_count == 0
    assert handoff.formal_census_authorized is False
    assert {item.role for item in handoff.public_role_slots} == set(HumanReviewRole)
    assert all(item.opaque_person_id is None for item in handoff.public_role_slots)
    assert all(item.stored_in_repository is False for item in handoff.private_assignment_fields)
    assert all(
        item.automation_may_supply_value is False for item in handoff.private_assignment_fields
    )
    assert {
        item.public_projection_policy for item in handoff.private_assignment_fields
    } == {PublicProjectionPolicy.SHA256_ONLY, PublicProjectionPolicy.OPAQUE_IDENTIFIER_ONLY}

    packets = {item.role: item for item in handoff.packet_templates}
    for role in (HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B):
        packet = packets[role]
        assert packet.own_work_only_until_dual_lock
        assert "other-reviewer-codes-before-dual-lock" in packet.forbidden_artifact_classes
        assert "own-private-workspace" in packet.visible_artifact_classes
    adjudicator = packets[HumanReviewRole.ADJUDICATOR]
    assert adjudicator.conflict_only_after_dual_lock
    assert "locked-conflict-index" in adjudicator.visible_artifact_classes
    assert "non-conflict-reviewer-codes" in adjudicator.forbidden_artifact_classes

    assert projection.role_slot_statuses == {
        "adjudicator": "unassigned",
        "reviewer-a": "unassigned",
        "reviewer-b": "unassigned",
    }
    assert projection.formal_search_execution_count == 0
    assert projection.screening_record_count == 0
    assert projection.automation_can_establish_natural_personhood is False


def test_parent_binding_and_public_role_slots_fail_closed() -> None:
    payload = _parent_evidence().model_dump(mode="json")
    payload["report_hash"] = "a" * 64
    payload["evidence_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "evidence_hash"}
    )
    with pytest.raises(ValidationError, match="parent erratum binding changed"):
        ParentPaginationErratumEvidence.model_validate(payload)

    slot_payload = _handoff().public_role_slots[0].model_dump(mode="json")
    slot_payload["opaque_person_id"] = "person-in-frozen-package"
    with pytest.raises(ValidationError):
        handoff_module.PublicHumanRoleSlot.model_validate(slot_payload)


def test_assignment_validation_checks_structure_but_never_authorizes_census() -> None:
    handoff = _handoff()
    assignments = _assignments(handoff=handoff)
    validation = validate_human_role_assignments(assignments, handoff=handoff)

    assert validation.schema_hashes_valid
    assert validation.pairwise_distinct_opaque_ids
    assert validation.automation_can_establish_natural_personhood is False
    assert validation.automation_can_establish_truthfulness is False
    assert validation.formal_census_authorized is False

    duplicate = assignments[1].model_dump(mode="json")
    duplicate["opaque_person_id"] = assignments[0].opaque_person_id
    duplicate_without_hash = {
        key: value for key, value in duplicate.items() if key != "receipt_hash"
    }
    duplicate["receipt_hash"] = canonical_sha256(duplicate_without_hash)
    with pytest.raises(ValueError, match="pairwise distinct"):
        validate_human_role_assignments(
            [assignments[0], HumanRoleAssignmentReceipt.model_validate(duplicate), assignments[2]],
            handoff=handoff,
        )

    other_handoff = build_human_review_handoff(
        protocol=_protocol(),
        parent_erratum=_parent_evidence(),
        frozen_at=HANDOFF_AT + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="not bound to this handoff"):
        validate_human_role_assignments(assignments, handoff=other_handoff)

    invalid = assignments[0].model_dump(mode="json")
    invalid["automation_claims_natural_personhood"] = True
    with pytest.raises(ValidationError):
        HumanRoleAssignmentReceipt.model_validate(invalid)


def test_dual_lock_and_adjudicator_access_enforce_order_and_distinctness() -> None:
    handoff = _handoff()
    reviewer_a, reviewer_b, adjudicator = _assignments(handoff=handoff)
    candidate_set = "a" * 64
    lock_a = _lock(
        handoff=handoff,
        assignment=reviewer_a,
        candidate_set=candidate_set,
        locked_at=HANDOFF_AT + timedelta(hours=1),
        marker="4",
    )
    lock_b = _lock(
        handoff=handoff,
        assignment=reviewer_b,
        candidate_set=candidate_set,
        locked_at=HANDOFF_AT + timedelta(hours=2),
        marker="5",
    )
    barrier = DualLockBarrierReceipt.create(
        locks=[lock_b, lock_a],
        created_at=HANDOFF_AT + timedelta(hours=3),
    )
    access = AdjudicatorAccessReceipt.create(
        adjudicator_assignment=adjudicator,
        barrier=barrier,
        conflict_index_sha256="8" * 64,
        opened_at=HANDOFF_AT + timedelta(hours=4),
    )

    assert barrier.both_reviewers_locked
    assert barrier.peer_codes_remain_hidden_from_reviewers
    assert access.non_conflict_codes_visible is False
    assert access.agreement_or_coverage_failure_repair_authorized is False

    mismatched = _lock(
        handoff=handoff,
        assignment=reviewer_b,
        candidate_set="b" * 64,
        locked_at=HANDOFF_AT + timedelta(hours=2),
        marker="5",
    )
    with pytest.raises(ValueError, match="same candidate set"):
        DualLockBarrierReceipt.create(
            locks=[lock_a, mismatched],
            created_at=HANDOFF_AT + timedelta(hours=3),
        )
    with pytest.raises(ValueError, match="cannot precede"):
        DualLockBarrierReceipt.create(
            locks=[lock_a, lock_b],
            created_at=HANDOFF_AT + timedelta(minutes=30),
        )
    with pytest.raises(ValueError, match="cannot open before"):
        AdjudicatorAccessReceipt.create(
            adjudicator_assignment=adjudicator,
            barrier=barrier,
            conflict_index_sha256="8" * 64,
            opened_at=HANDOFF_AT + timedelta(hours=2),
        )
    reused_person = _assignment(
        HumanReviewRole.ADJUDICATOR,
        reviewer_a.opaque_person_id,
        "1",
        handoff=handoff,
    )
    with pytest.raises(ValueError, match="distinct"):
        AdjudicatorAccessReceipt.create(
            adjudicator_assignment=reused_person,
            barrier=barrier,
            conflict_index_sha256="8" * 64,
            opened_at=HANDOFF_AT + timedelta(hours=4),
        )


def test_frozen_runner_rejects_result_or_identity_bearing_projection(tmp_path: Path) -> None:
    projection = build_human_review_handoff_projection(_handoff())
    payload = build_human_review_handoff_replay_payload(projection)
    payload["projection"]["reviewer_identity"] = "not-allowed"
    payload["expected_projection_sha256"] = canonical_sha256(payload["projection"])
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(HANDOFF_RUNNER),
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

    assert completed.returncode != 0
    assert "result- or identity-bearing field is forbidden" in completed.stderr


def test_handoff_package_replays_loads_and_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_probe(*, role_id: str, executable: Path) -> InterpreterRuntime:
        del executable
        return _runtime(role_id)

    monkeypatch.setattr(handoff_module, "probe_interpreter_runtime", fake_probe)
    handoff = _handoff()
    projection = build_human_review_handoff_projection(handoff)
    replay = run_human_review_handoff_replay(
        projection=projection,
        runner_path=HANDOFF_RUNNER,
        interpreters={
            "clean-runtime-a": Path(sys.executable),
            "clean-runtime-b": Path(sys.executable),
        },
        work_dir=tmp_path / "replay",
    )
    report = BenchmarkHumanReviewHandoffReport.create(
        parent_git_commit=PARENT_ERRATUM_COMMIT,
        built_at=HANDOFF_AT,
        handoff_source_sha256=_file_hash(HANDOFF_SOURCE),
        frozen_runner_sha256=_file_hash(HANDOFF_RUNNER),
        handoff=handoff,
        projection=projection,
        replay_certificate=replay,
    )
    output_dir = tmp_path / "handoff"
    manifest = write_human_review_handoff(output_dir, report)
    loaded_report, loaded_manifest = load_human_review_handoff(output_dir)

    assert loaded_report.report_hash == report.report_hash
    assert loaded_manifest.manifest_hash == manifest.manifest_hash
    assert report.replay_certificate.exact_projection_match
    assert report.actual_human_identity_count == 0
    assert report.formal_census_authorized is False

    checklist = output_dir / handoff_module.HUMAN_HANDOFF_OWNER_CHECKLIST_FILENAME
    checklist.write_text(checklist.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    with pytest.raises(HumanReviewHandoffIntegrityError, match="artifact hash mismatch"):
        load_human_review_handoff(output_dir)


def test_packet_template_rejects_cross_reviewer_leakage() -> None:
    packet = BlindedReviewPacketTemplate.create(role=HumanReviewRole.REVIEWER_A)
    payload = packet.model_dump(mode="json")
    payload["visible_artifact_classes"].append("other-reviewer-codes-before-dual-lock")
    payload["visible_artifact_classes"] = sorted(payload["visible_artifact_classes"])
    payload_without_hash = {key: value for key, value in payload.items() if key != "packet_hash"}
    payload["packet_hash"] = canonical_sha256(payload_without_hash)

    with pytest.raises(ValidationError, match="visibility changed"):
        BlindedReviewPacketTemplate.model_validate(payload)
