"""Immutable provider-call receipts for system-authored scientific text.

The boolean ``authored_by_model=true`` is not provenance: any caller could type it.
This module preserves the exact prompt, provider identity, raw response, parsed JSON,
and their canonical hashes for research plans and result interpretations.  A later
audit can therefore prove that every scientific field is byte-for-byte derived from
the configured model response, while credentials remain outside the artifact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult


class ModelAuthorshipError(RuntimeError):
    """Raised when scientific-text authorship cannot be proved exactly."""


class ModelAuthorshipReceipt(StrictFrozenModel):
    """One credential-free, content-addressed scientific authoring interaction."""

    schema_version: Literal["model-authorship-receipt-v1"] = (
        "model-authorship-receipt-v1"
    )
    artifact_kind: Literal[
        "research_plan", "outcome_interpretation", "innovation_audit"
    ]
    interaction_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    messages: tuple[dict[str, str], ...] = Field(min_length=1)
    messages_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    response_text: str
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parsed_payload: dict[str, Any]
    parsed_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport_normalization: Literal[
        "none",
        "discarded_trailing_closing_delimiters",
        "discarded_leading_self_revision",
    ] = "none"
    normalization_suffix: str | None = Field(default=None, min_length=1)
    normalization_suffix_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    usage: dict[str, Any]
    temperature: float = Field(ge=0.0)
    reasoning_content: str | None = None
    reasoning_is_evidence: Literal[False] = False
    reasoning_transport: Literal[
        "absent",
        "dashscope_enable_thinking",
        "anthropic_thinking_block",
    ] = "absent"
    api_key_value_logged: Literal[False] = False
    created_at: datetime
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> ModelAuthorshipReceipt:
        if self.messages_sha256 != canonical_model_hash(
            {"messages": list(self.messages)}
        ):
            raise ModelAuthorshipError("model-authorship message hash mismatch")
        if self.response_sha256 != _text_hash(self.response_text):
            raise ModelAuthorshipError("model-authorship response hash mismatch")
        if self.parsed_payload_sha256 != canonical_model_hash(self.parsed_payload):
            raise ModelAuthorshipError("model-authorship parsed-payload hash mismatch")
        normalized = self.transport_normalization != "none"
        if normalized != (self.normalization_suffix is not None):
            raise ModelAuthorshipError(
                "model-authorship normalization suffix presence mismatch"
            )
        if normalized != (self.normalization_suffix_sha256 is not None):
            raise ModelAuthorshipError(
                "model-authorship normalization hash presence mismatch"
            )
        if (
            self.normalization_suffix is not None
            and self.normalization_suffix_sha256
            != _text_hash(self.normalization_suffix)
        ):
            raise ModelAuthorshipError(
                "model-authorship normalization suffix hash mismatch"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"receipt_hash", "output_path"})
        )
        if self.receipt_hash != expected:
            raise ModelAuthorshipError("model-authorship receipt hash mismatch")
        return self


def record_model_authorship_receipt(
    *,
    artifact_kind: Literal[
        "research_plan", "outcome_interpretation", "innovation_audit"
    ],
    interaction_id: str,
    attempt: int,
    messages: Sequence[Mapping[str, str]],
    completion: LLMJsonCompletionResult,
    output_dir: Path | str,
    clock: datetime | None = None,
) -> ModelAuthorshipReceipt:
    """Persist the exact provider transaction before accepting its scientific text.

    Existing bytes are immutable.  A resumed call may reuse an identical receipt,
    but a different response under the same interaction id is rejected rather than
    overwriting provenance.
    """

    root = Path(output_dir).resolve()
    path = root / "interactions" / f"{interaction_id}.json"
    normalized_messages = tuple(dict(item) for item in messages)
    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "model-authorship-receipt-v1",
        "artifact_kind": artifact_kind,
        "interaction_id": interaction_id,
        "attempt": attempt,
        "messages": normalized_messages,
        "messages_sha256": canonical_model_hash(
            {"messages": list(normalized_messages)}
        ),
        "provider": completion.provider,
        "base_url": completion.base_url,
        "model_name": completion.model_name,
        "endpoint": completion.endpoint,
        "response_text": completion.response_text,
        "response_sha256": _text_hash(completion.response_text),
        "parsed_payload": completion.parsed_json,
        "parsed_payload_sha256": canonical_model_hash(completion.parsed_json),
        "transport_normalization": completion.transport_normalization,
        "normalization_suffix": completion.normalization_suffix,
        "normalization_suffix_sha256": (
            _text_hash(completion.normalization_suffix)
            if completion.normalization_suffix is not None
            else None
        ),
        "usage": completion.usage,
        "temperature": completion.temperature,
        "reasoning_content": completion.reasoning_text,
        "reasoning_is_evidence": False,
        "reasoning_transport": completion.reasoning_transport,
        "api_key_value_logged": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    payload["output_path"] = path.as_posix()
    receipt = ModelAuthorshipReceipt.model_validate(payload)

    if path.is_file():
        existing = ModelAuthorshipReceipt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        immutable_fields = {
            "created_at",
            "receipt_hash",
            "output_path",
        }
        existing_payload = existing.model_dump(
            mode="json", exclude=immutable_fields
        )
        requested_payload = receipt.model_dump(
            mode="json", exclude=immutable_fields
        )
        if existing_payload != requested_payload:
            raise ModelAuthorshipError(
                f"refusing to overwrite different authorship bytes: {path}"
            )
        return existing

    write_json_model(path, receipt)
    return receipt


def load_bound_authorship_receipt(
    *,
    lineage_dir: Path | str,
    relative_path: str | None,
    expected_hash: str | None,
    artifact_kind: Literal[
        "research_plan", "outcome_interpretation", "innovation_audit"
    ],
    expected_model_name: str,
    expected_fields: Mapping[str, Any],
) -> ModelAuthorshipReceipt:
    """Load and prove one receipt plus exact model-to-artifact field derivation."""

    if not relative_path or not expected_hash:
        raise ModelAuthorshipError("authorship receipt path/hash is absent")
    root = Path(lineage_dir).resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ModelAuthorshipError("authorship receipt escapes the lineage") from exc
    receipt = ModelAuthorshipReceipt.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if receipt.artifact_kind != artifact_kind:
        raise ModelAuthorshipError("authorship receipt has the wrong artifact kind")
    if receipt.receipt_hash != expected_hash:
        raise ModelAuthorshipError("authorship receipt binding hash mismatch")
    if receipt.model_name != expected_model_name:
        raise ModelAuthorshipError("authorship receipt model name mismatch")
    missing = [key for key in expected_fields if key not in receipt.parsed_payload]
    if missing:
        raise ModelAuthorshipError(
            f"authorship response omitted bound scientific fields: {missing}"
        )
    changed = [
        key
        for key, value in expected_fields.items()
        if receipt.parsed_payload.get(key) != value
    ]
    if changed:
        raise ModelAuthorshipError(
            f"artifact scientific fields differ from model response: {changed}"
        )
    return receipt


def plan_authored_fields(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Project a frozen plan back to the exact fields the provider authored."""

    datasets = plan.get("datasets")
    if not isinstance(datasets, Mapping):
        datasets = {}
    return {
        "title": plan.get("title"),
        "abstract": plan.get("abstract"),
        "problem_statement": plan.get("problem_statement"),
        "rationale": plan.get("rationale"),
        "technical_details": plan.get("technical_details"),
        "dataset_source": datasets.get("source"),
        "dataset_target": datasets.get("target"),
        "methods": plan.get("methods"),
        "experiments": plan.get("experiments"),
        "baselines": plan.get("baselines"),
        "metrics": plan.get("metrics"),
        "expected_results": plan.get("expected_results"),
        "code_agent_brief": plan.get("code_agent_brief"),
        "risks_and_alternatives": plan.get("risks_and_alternatives"),
        "references": plan.get("references"),
    }


def outcome_authored_fields(interpretation: Mapping[str, Any]) -> dict[str, Any]:
    """Project an interpretation to the exact fields the provider authored."""

    return {
        key: interpretation.get(key)
        for key in (
            "verdict",
            "what_the_evidence_supports",
            "what_the_evidence_does_not_support",
            "strongest_counter_reading",
            "limitations",
            "claims_frozen_gate_passed",
        )
    }


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
