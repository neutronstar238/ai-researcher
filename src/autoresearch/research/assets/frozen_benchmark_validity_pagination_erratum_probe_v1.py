"""Dependency-free result-blind replay probe for Task 263.6.7.2.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

EXPECTED_PROTOCOL_HASH = "ed6088c225d5c7f7710ecb69507659003b5b97e06dc7c0ee005a81ed2712e8ed"
EXPECTED_HARNESS_REPORT_HASH = "fbb2a633bb57f0bb9f9f1471b58e8b4b8367098923f07c052d712758cbef9a10"
EXPECTED_RESOLVED_FINDINGS = [
    "crossref-last-cursor-termination-mismatch",
    "dblp-year-split-query-unspecified",
]
EXPECTED_RULES = {
    "arxiv": {
        "cap_policy": "not-applicable",
        "change_kind": "unchanged",
        "continuation_field": "start",
        "documented_year_filter_available": None,
        "initial_parameters": {"start": "0"},
        "terminal_condition": "offset-reaches-total-results",
    },
    "crossref": {
        "cap_policy": "not-applicable",
        "change_kind": "corrective-clarification",
        "continuation_field": "message.next-cursor",
        "documented_year_filter_available": None,
        "initial_parameters": {"cursor": "*"},
        "terminal_condition": "returned-item-count-less-than-requested-rows",
    },
    "dblp": {
        "cap_policy": "retain-partial-and-stop-no-documented-year-filter",
        "change_kind": "corrective-stop",
        "continuation_field": None,
        "documented_year_filter_available": False,
        "initial_parameters": {"c": "0", "f": "0", "h": "1000"},
        "terminal_condition": "single-response-below-cap-or-partial-stop",
    },
    "openalex": {
        "cap_policy": "not-applicable",
        "change_kind": "clarified-no-change",
        "continuation_field": "meta.next_cursor",
        "documented_year_filter_available": None,
        "initial_parameters": {"cursor": "*"},
        "terminal_condition": "next-cursor-null-and-results-empty",
    },
}
FORBIDDEN_KEYS = {
    "admission_card",
    "admission_cards",
    "answer",
    "benchmark_outcome",
    "benchmark_outcomes",
    "candidate_model_output",
    "candidate_model_outputs",
    "gold_answer",
    "judge_output",
    "model_output",
    "model_outputs",
    "reference_answer",
    "reserve_result",
    "screening_decision",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _walk_result_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in FORBIDDEN_KEYS and item is not None:
                raise ValueError(f"result-bearing field is forbidden: {path}.{raw_key}")
            _walk_result_keys(item, f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_result_keys(item, f"{path}[{index}]")


def _require_zero_result_projection(projection: dict[str, Any]) -> None:
    if projection.get("schema_version") != "benchmark-pagination-erratum-projection-v1":
        raise ValueError("unexpected projection schema")
    if projection.get("task_id") != "263.6.7.2.1":
        raise ValueError("unexpected task identifier")
    if projection.get("protocol_hash") != EXPECTED_PROTOCOL_HASH:
        raise ValueError("original protocol hash changed")
    if projection.get("parent_harness_report_hash") != EXPECTED_HARNESS_REPORT_HASH:
        raise ValueError("parent Harness report changed")
    if projection.get("status") != "frozen-pre-extraction-erratum":
        raise ValueError("erratum is not frozen")
    if projection.get("resolved_finding_ids") != EXPECTED_RESOLVED_FINDINGS:
        raise ValueError("resolved finding set changed")
    if projection.get("source_rules") != EXPECTED_RULES:
        raise ValueError("source pagination rules changed")
    documentation_hashes = projection.get("documentation_snapshot_hashes")
    if not isinstance(documentation_hashes, dict) or set(documentation_hashes) != {
        "crossref-cursor-guidance",
        "dblp-api-parameters",
        "dblp-query-syntax",
        "openalex-cursor-guidance",
    }:
        raise ValueError("four primary documentation snapshots are required")
    if not all(
        isinstance(value, str) and len(value) == 64 for value in documentation_hashes.values()
    ):
        raise ValueError("documentation snapshot hashes are invalid")
    amendment_hashes = projection.get("amendment_hashes")
    if not isinstance(amendment_hashes, dict) or set(amendment_hashes) != set(EXPECTED_RULES):
        raise ValueError("four amendment hashes are required")
    if projection.get("formal_search_authorized") is not True:
        raise ValueError("frozen erratum must authorize only protocol-bound retrieval")
    required_zero = (
        "formal_search_execution_count",
        "bibliographic_record_count",
        "screening_decision_count",
        "admission_card_count",
    )
    if any(projection.get(field) != 0 for field in required_zero):
        raise ValueError("erratum projection contains post-freeze research activity")
    required_false = (
        "benchmark_outcomes_accessed",
        "candidate_model_calls",
        "actual_human_identities_assigned",
        "human_coding_authorized",
        "publication_claim_authorized",
        "public_release_authorized",
        "external_submission_authorized",
    )
    if any(projection.get(field) is not False for field in required_false):
        raise ValueError("erratum projection changed a downstream permission")
    _walk_result_keys(projection)


def replay(payload: dict[str, Any]) -> dict[str, Any]:
    projection = payload.get("projection")
    if not isinstance(projection, dict):
        raise ValueError("projection must be an object")
    expected_hash = payload.get("expected_projection_sha256")
    projection_hash = _sha256(projection)
    if expected_hash != projection_hash:
        raise ValueError("projection hash mismatch")
    _require_zero_result_projection(projection)
    output = {
        "schema_version": "benchmark-pagination-erratum-replay-output-v1",
        "task_id": "263.6.7.2.1",
        "protocol_hash": EXPECTED_PROTOCOL_HASH,
        "projection_sha256": projection_hash,
        "status": "frozen-pre-extraction-erratum",
        "formal_search_execution_count": 0,
        "bibliographic_record_count": 0,
        "admission_card_count": 0,
        "benchmark_outcomes_accessed": False,
        "candidate_model_calls": False,
    }
    output["output_sha256"] = _sha256(output)
    return output


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(value))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("replay input must be an object")
    _write_atomic(args.output, replay(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
