"""Dependency-free replay probe for Task 263.6.7.2.2.

The probe accepts only the result-blind human-review handoff projection.  It
cannot receive identities, role assignments, screening/coding decisions,
benchmark outcomes, adjudication content, or publication permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PROTOCOL_HASH = "ed6088c225d5c7f7710ecb69507659003b5b97e06dc7c0ee005a81ed2712e8ed"
PARENT_ERRATUM_HASH = "f0ffc351a43eb8ac0176cca787ad53f9af4e343cc2554aca068a20215f81d571"
PARENT_ERRATUM_REPORT_HASH = "3fefa90f73c5e6990f1817c0a06f33707b8a5e553f344a321cab18451f50310b"
PARENT_ERRATUM_PROJECTION_HASH = "b36624099cdda8030548068290596c41411b8e4bbc15611e3db519b2add79e7c"
PARENT_ERRATUM_MANIFEST_HASH = "a62d742e9466369eb5e573871b413e6c71a9aee3fff1a1e44d178593facc3ffd"

REQUIRED_ROLES = ["adjudicator", "reviewer-a", "reviewer-b"]
ZERO_FIELDS = (
    "actual_human_identity_count",
    "role_assignment_count",
    "review_packet_issued_count",
    "review_lock_count",
    "adjudicator_access_count",
    "formal_search_execution_count",
    "screening_record_count",
    "critical_coding_record_count",
    "admission_card_count",
)
FALSE_FIELDS = (
    "human_roles_assigned",
    "formal_census_authorized",
    "benchmark_outcomes_accessed",
    "candidate_model_calls",
    "publication_claim_authorized",
    "public_release_authorized",
    "external_submission_authorized",
)
FORBIDDEN_NONEMPTY_KEYS = {
    "actual_identity",
    "actual_human_identity",
    "adjudication_decision",
    "admission_card",
    "benchmark_outcome",
    "candidate_model_output",
    "conflict_disclosure",
    "critical_code",
    "human_name",
    "identity_evidence",
    "model_output",
    "opaque_person_id",
    "owner_attestation",
    "person_id",
    "review_lock",
    "reviewer_decision",
    "reviewer_identity",
    "role_assignment",
    "screening_decision",
    "screening_record",
}


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_hash(value: Any, label: str) -> str:
    rendered = str(value)
    if len(rendered) != 64 or any(character not in "0123456789abcdef" for character in rendered):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return rendered


def _walk_forbidden(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in FORBIDDEN_NONEMPTY_KEYS and item not in (None, False, 0, "", [], {}):
                raise ValueError(f"result- or identity-bearing field is forbidden: {path}.{raw_key}")
            _walk_forbidden(item, path=f"{path}.{raw_key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


def _validate_projection(projection: dict[str, Any]) -> None:
    if projection.get("schema_version") != "benchmark-human-review-handoff-projection-v1":
        raise ValueError("unexpected handoff projection schema")
    if projection.get("task_id") != "263.6.7.2.2":
        raise ValueError("unexpected handoff task")
    if projection.get("status") != "frozen-result-blind-human-handoff":
        raise ValueError("handoff is not in its frozen result-blind state")
    if projection.get("protocol_hash") != PROTOCOL_HASH:
        raise ValueError("unexpected benchmark-validity protocol")
    if projection.get("parent_erratum_hash") != PARENT_ERRATUM_HASH:
        raise ValueError("unexpected parent erratum")
    if projection.get("parent_erratum_report_hash") != PARENT_ERRATUM_REPORT_HASH:
        raise ValueError("unexpected parent erratum report")
    if projection.get("parent_erratum_projection_hash") != PARENT_ERRATUM_PROJECTION_HASH:
        raise ValueError("unexpected parent erratum projection")
    if projection.get("parent_erratum_manifest_hash") != PARENT_ERRATUM_MANIFEST_HASH:
        raise ValueError("unexpected parent erratum manifest")
    if projection.get("role_ids") != REQUIRED_ROLES:
        raise ValueError("handoff must contain exactly two reviewers and one adjudicator")
    statuses = projection.get("role_slot_statuses")
    if statuses != {role: "unassigned" for role in REQUIRED_ROLES}:
        raise ValueError("all human role slots must remain unassigned in the frozen package")
    if projection.get("current_stage") != "unassigned":
        raise ValueError("handoff projection cannot advance the human ceremony")
    if projection.get("private_assignment_field_count") != 7:
        raise ValueError("private assignment field inventory changed")
    if projection.get("stage_transition_count") != 5:
        raise ValueError("human handoff state machine changed")
    for mapping_name in (
        "role_requirement_hashes",
        "packet_template_hashes",
    ):
        mapping = projection.get(mapping_name)
        if not isinstance(mapping, dict) or sorted(mapping) != REQUIRED_ROLES:
            raise ValueError(f"{mapping_name} must cover all three human roles")
        for role, digest in mapping.items():
            _require_hash(digest, f"{mapping_name}.{role}")
    for list_name in ("private_field_spec_hashes", "transition_hashes"):
        values = projection.get(list_name)
        if not isinstance(values, list) or not values:
            raise ValueError(f"{list_name} must be a non-empty list")
        if values != sorted(set(values)):
            raise ValueError(f"{list_name} must be sorted and unique")
        for digest in values:
            _require_hash(digest, list_name)
    _require_hash(projection.get("dual_lock_policy_hash"), "dual_lock_policy_hash")
    _require_hash(projection.get("handoff_hash"), "handoff_hash")
    for field in ZERO_FIELDS:
        if projection.get(field) != 0:
            raise ValueError(f"{field} must remain zero")
    for field in FALSE_FIELDS:
        if projection.get(field) is not False:
            raise ValueError(f"{field} must remain false")
    if projection.get("automation_can_establish_natural_personhood") is not False:
        raise ValueError("automation cannot establish natural-person status")
    if projection.get("next_action") != "project-owner-enrolls-three-real-humans":
        raise ValueError("unexpected next action")
    _walk_forbidden(projection)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    projection = payload.get("projection")
    if not isinstance(projection, dict):
        raise ValueError("projection must be an object")
    expected = _require_hash(payload.get("expected_projection_sha256"), "expected projection")
    actual = _sha256(_canonical_json_bytes(projection))
    if actual != expected:
        raise ValueError("handoff projection hash mismatch")
    _validate_projection(projection)

    output = {
        "schema_version": "benchmark-human-review-handoff-probe-output-v1",
        "status": "result-blind-handoff-verified",
        "projection_sha256": actual,
        "role_count": 3,
        "unassigned_role_count": 3,
        "formal_search_execution_count": 0,
        "screening_record_count": 0,
        "critical_coding_record_count": 0,
        "admission_card_count": 0,
        "formal_census_authorized": False,
        "automation_can_establish_natural_personhood": False,
    }
    output["output_sha256"] = _sha256(_canonical_json_bytes(output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_json_bytes(output) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
