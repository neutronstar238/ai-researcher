"""Single-call model boundary for evidence-bound literature query repair.

The model may select only literal terms from a frozen focus/broad evidence
catalog.  Deterministic contracts diagnose the gap and project the resulting
four-query plan; this module only preserves the exact provider interaction that
proposed those terms.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.contest_planning_literature_gap_repair import (
    PlanningLiteratureGapDiagnosisReceipt,
    PlanningLiteratureGapRepairEvidenceInput,
    PlanningLiteratureGapRepairProjection,
    PlanningLiteratureRoleQueryRepair,
    project_planning_literature_query_repair,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_SHA256 = r"^[0-9a-f]{64}$"
_GAP_REPAIR_RESPONSE_SCHEMA_NAME = "contest_planning_literature_gap_repair"


def _gap_repair_response_schema() -> dict[str, Any]:
    """Return the provider transport shape; semantic checks remain local."""

    return {
        "type": "object",
        "properties": {
            "repairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "replacement_terms": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "term": {"type": "string"},
                                    "evidence_hash": {"type": "string"},
                                    "matched_field": {"type": "string"},
                                },
                                "required": [
                                    "term",
                                    "evidence_hash",
                                    "matched_field",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["role", "replacement_terms"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["repairs"],
        "additionalProperties": False,
    }


class PlanningLiteratureGapRepairResponseError(RuntimeError):
    """Raised when the one allowed query-repair response is unusable."""


class _PlanningLiteratureGapRepairModelOutput(StrictFrozenModel):
    repairs: tuple[PlanningLiteratureRoleQueryRepair, ...] = Field(
        min_length=1,
        max_length=4,
    )


class PlanningLiteratureGapRepairResponseReceipt(StrictFrozenModel):
    """Exact provider response and its deterministic query-plan projection.

    A receipt whose ``revision_failure_reason`` is set was produced by the one
    bounded revision attempt and carries the deterministic revision message.
    """

    schema_version: Literal["contest-planning-literature-gap-response-v1"] = (
        "contest-planning-literature-gap-response-v1"
    )
    stage_name: Literal["planning-literature-gap-repair-query"] = (
        "planning-literature-gap-repair-query"
    )
    stage_input_hash: str = Field(pattern=_SHA256)
    messages: tuple[dict[str, str], ...] = Field(min_length=3, max_length=4)
    messages_hash: str = Field(pattern=_SHA256)
    completion: dict[str, Any]
    completion_hash: str = Field(pattern=_SHA256)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    response_text_sha256: str = Field(pattern=_SHA256)
    projection: PlanningLiteratureGapRepairProjection
    projection_hash: str = Field(pattern=_SHA256)
    model_calls: Literal[1] = 1
    revision_failure_reason: str | None = Field(default=None, max_length=2_000)
    response_scope: Literal["evidence_terms_only_not_scientific_answer"] = (
        "evidence_terms_only_not_scientific_answer"
    )
    receipt_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _replay_receipt(self) -> PlanningLiteratureGapRepairResponseReceipt:
        base_messages = build_planning_literature_gap_repair_messages(
            self.projection.diagnosis,
            self.projection.evidence_inputs,
        )
        expected_messages = (
            (*base_messages, build_gap_repair_revision_message(self.revision_failure_reason))
            if self.revision_failure_reason is not None
            else base_messages
        )
        if self.messages != expected_messages:
            raise ValueError("gap-repair response messages do not replay")
        if self.messages_hash != canonical_model_hash({"messages": list(self.messages)}):
            raise ValueError("gap-repair response messages hash mismatch")
        expected_stage_input_hash = planning_literature_gap_repair_stage_input_hash(
            self.projection.diagnosis,
            self.projection.evidence_inputs,
            revision_failure_reason=self.revision_failure_reason,
        )
        if self.stage_input_hash != expected_stage_input_hash:
            raise ValueError("gap-repair response stage-input hash mismatch")
        if self.completion_hash != canonical_model_hash(self.completion):
            raise ValueError("gap-repair response completion hash mismatch")
        completion = LLMJsonCompletionResult.model_validate(self.completion)
        if completion.provider != self.provider or completion.model_name != self.model_name:
            raise ValueError("gap-repair response provider identity mismatch")
        if (
            self.response_text_sha256
            != hashlib.sha256(completion.response_text.encode("utf-8")).hexdigest()
        ):
            raise ValueError("gap-repair raw response hash mismatch")
        model_output = _parse_model_output(completion.parsed_json)
        replayed = project_planning_literature_query_repair(
            self.projection.diagnosis,
            evidence_inputs=self.projection.evidence_inputs,
            repairs=model_output.repairs,
        )
        if replayed != self.projection:
            raise ValueError("gap-repair response projection does not replay")
        if self.projection_hash != self.projection.projection_hash:
            raise ValueError("gap-repair response projection hash mismatch")
        expected_receipt_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"receipt_hash"})
        )
        if self.receipt_hash != expected_receipt_hash:
            raise ValueError("gap-repair response receipt hash mismatch")
        return self

    def completion_result(self) -> LLMJsonCompletionResult:
        """Reconstruct the exact completion without a second provider request."""

        return LLMJsonCompletionResult.model_validate(self.completion)


def build_planning_literature_gap_repair_messages(
    diagnosis: PlanningLiteratureGapDiagnosisReceipt,
    evidence_inputs: Sequence[PlanningLiteratureGapRepairEvidenceInput],
) -> tuple[dict[str, str], ...]:
    """Build the fixed prompt for one bounded, evidence-copying repair decision."""

    evidence = _canonical_evidence(evidence_inputs)
    role_diagnostics = [
        item.model_dump(mode="json")
        for item in diagnosis.role_diagnostics
        if item.role in diagnosis.repairable_roles
    ]
    return (
        {
            "role": "system",
            "content": (
                "你是学术检索缺口修复智能体。不得回答研究问题、提出科学结论、生成文献"
                "或改写非缺口查询。你只能为每个已诊断缺口角色选择2至4个短检索术语；"
                "每个术语必须从给定证据的 candidate_terms 列表中逐字选择，且 term、"
                "matched_field、evidence_hash 三者必须与该候选条目的三个字段完全一致、"
                "一字不改；禁止把 title 条目标成 abstract 或把 abstract 条目标成 title，"
                "禁止使用列表之外的任何词、同义词、缩写或你自己的领域知识，即使你认为"
                "那些词检索效果更好。只输出JSON对象，唯一顶层字段为repairs。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "failed_planning_literature_coverage_gap",
                    "diagnosis_hash": diagnosis.diagnosis_hash,
                    "coverage_receipt_hash": diagnosis.coverage_receipt_hash,
                    "repairable_roles": [item.value for item in diagnosis.repairable_roles],
                    "role_diagnostics": role_diagnostics,
                    "r1_role_queries": [
                        item.model_dump(mode="json")
                        for item in diagnosis.coverage_receipt.role_queries
                    ],
                    "boundary": (
                        "每个角色仅替换其查询的第二个OR概念组；程序会机械重建完整R2查询。"
                    ),
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json_text(
                {
                    "context_kind": "hash_bound_focus_or_broad_evidence",
                    "evidence_inputs": [
                        {
                            **item.model_dump(mode="json"),
                            "candidate_terms": _candidate_terms(item.title, item.abstract),
                        }
                        for item in evidence
                    ],
                    "output_contract": {
                        "repairs": [
                            {
                                "role": "one diagnosed role value",
                                "replacement_terms": [
                                    {
                                        "term": "literal phrase copied from evidence",
                                        "evidence_hash": "the exact 64-hex evidence hash",
                                        "matched_field": "title or abstract",
                                    }
                                ],
                            }
                        ],
                        "replacement_terms_per_role": {"minimum": 2, "maximum": 4},
                        "extra_fields_allowed": False,
                    },
                }
            ),
        },
    )


def build_gap_repair_revision_message(failure_reason: str) -> dict[str, str]:
    """One deterministic revision instruction after a failed v4 projection."""

    reason = str(failure_reason or "").strip() or "counterevidence gap"
    return {
        "role": "user",
        "content": _canonical_json_text(
            {
                "context_kind": "program_rejected_gap_repair_projection",
                "rejection_reason": reason,
                "boundary": (
                    "上一次修复投影被程序校验拒绝。请重选替换术语：counterevidence 角色"
                    "的 replacement_terms 中必须包含至少一个表达证伪/反证概念的证据短语"
                    "（例如证据中出现的 limitation、artifact、negative result、alternative "
                    "explanation、bias、confounder、false positive、spurious effect 等强反证词）。"
                    "术语仍必须逐字来自给定证据的 candidate_terms，其余规则不变。"
                ),
            }
        ),
    }


def gap_repair_failure_is_revisable(exc: Exception) -> bool:
    """True when one bounded revision attempt may fix the projection rejection."""

    message = str(exc).casefold()
    return "counterevidence" in message and (
        "missing a falsifying concept" in message or "weak-only group" in message
    )


def _canonical_json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def run_planning_literature_gap_repair_query(
    *,
    diagnosis: PlanningLiteratureGapDiagnosisReceipt,
    evidence_inputs: Sequence[PlanningLiteratureGapRepairEvidenceInput],
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int = 768,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    output_path: Path | str | None = None,
    revision_failure_reason: str | None = None,
) -> PlanningLiteratureGapRepairResponseReceipt:
    """Make at most one provider call, or replay an exact persisted response.

    ``revision_failure_reason`` marks the single bounded revision attempt: the
    deterministic revision message is appended so the model must re-propose
    replacement terms that satisfy the v4 counterevidence gate.
    """

    evidence = _canonical_evidence(evidence_inputs)
    destination = Path(output_path) if output_path is not None else None
    if destination is not None and destination.is_file():
        persisted = load_planning_literature_gap_repair_response(destination)
        if (
            persisted.projection.diagnosis != diagnosis
            or persisted.projection.evidence_inputs != evidence
        ):
            raise PlanningLiteratureGapRepairResponseError(
                "persisted gap-repair response belongs to different inputs"
            )
        if persisted.revision_failure_reason != revision_failure_reason:
            raise PlanningLiteratureGapRepairResponseError(
                "persisted gap-repair response belongs to a different revision attempt"
            )
        return persisted
    if max_tokens < 1:
        raise PlanningLiteratureGapRepairResponseError("gap-repair max_tokens must be positive")
    base_messages = build_planning_literature_gap_repair_messages(diagnosis, evidence)
    messages = (
        (*base_messages, build_gap_repair_revision_message(revision_failure_reason))
        if revision_failure_reason is not None
        else base_messages
    )
    try:
        result = completion(
            messages=list(messages),
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=0.2 if revision_failure_reason is None else 0.4,
            thinking_mode="disabled",
            thinking_budget=None,
            response_schema=_gap_repair_response_schema(),
            response_schema_name=_GAP_REPAIR_RESPONSE_SCHEMA_NAME,
        )
        validated_completion = LLMJsonCompletionResult.model_validate(result)
        model_output = _parse_model_output(validated_completion.parsed_json)
        projection = project_planning_literature_query_repair(
            diagnosis,
            evidence_inputs=evidence,
            repairs=model_output.repairs,
        )
    except Exception as exc:
        raise PlanningLiteratureGapRepairResponseError(str(exc)) from exc
    completion_payload = validated_completion.model_dump(mode="json")
    payload: dict[str, Any] = {
        "schema_version": "contest-planning-literature-gap-response-v1",
        "stage_name": "planning-literature-gap-repair-query",
        "stage_input_hash": planning_literature_gap_repair_stage_input_hash(
            diagnosis,
            evidence,
            revision_failure_reason=revision_failure_reason,
        ),
        "messages": list(messages),
        "messages_hash": canonical_model_hash({"messages": list(messages)}),
        "completion": completion_payload,
        "completion_hash": canonical_model_hash(completion_payload),
        "provider": validated_completion.provider,
        "model_name": validated_completion.model_name,
        "response_text_sha256": hashlib.sha256(
            validated_completion.response_text.encode("utf-8")
        ).hexdigest(),
        "projection": projection.model_dump(mode="json"),
        "projection_hash": projection.projection_hash,
        "model_calls": 1,
        "revision_failure_reason": revision_failure_reason,
        "response_scope": "evidence_terms_only_not_scientific_answer",
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    receipt = PlanningLiteratureGapRepairResponseReceipt.model_validate(payload)
    if destination is not None:
        write_json_model(destination, receipt)
    return receipt


def load_planning_literature_gap_repair_response(
    path: Path | str,
) -> PlanningLiteratureGapRepairResponseReceipt:
    """Load and replay every message, provider, response, and projection hash."""

    return PlanningLiteratureGapRepairResponseReceipt.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _candidate_terms(
    title: str,
    abstract: str | None,
    *,
    cap_per_field: int = 24,
) -> list[dict[str, str]]:
    """Extract bounded 2-3 token n-grams the model may copy verbatim.

    These candidates are exact substrings of the evidence, so a term the model
    copies from this catalog always passes ``_term_occurs_in_evidence``.
    """

    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for field, text in (("title", title), ("abstract", abstract or "")):
        tokens = text.split()
        if not tokens:
            continue
        field_candidates: list[dict[str, str]] = []
        for width in (3, 2):
            for index in range(len(tokens) - width + 1):
                term = " ".join(tokens[index : index + width])
                key = term.casefold()
                if key in seen or len(term) > 72:
                    continue
                if any(character in term for character in ('"', "\\", "(", ")", "*", "?")):
                    continue
                if term.casefold().split()[0] in {"no", "zero", "without", "not"}:
                    continue
                seen.add(key)
                field_candidates.append({"term": term, "matched_field": field})
        candidates.extend(field_candidates[:cap_per_field])
    return candidates


def _canonical_evidence(
    evidence_inputs: Sequence[PlanningLiteratureGapRepairEvidenceInput],
) -> tuple[PlanningLiteratureGapRepairEvidenceInput, ...]:
    evidence = tuple(
        sorted(
            (
                PlanningLiteratureGapRepairEvidenceInput.model_validate(
                    item.model_dump(mode="json")
                )
                for item in evidence_inputs
            ),
            key=lambda item: (item.source_scope, item.record_id.casefold(), item.evidence_hash),
        )
    )
    if not evidence:
        raise PlanningLiteratureGapRepairResponseError(
            "gap-repair response requires hash-bound focus or broad evidence"
        )
    identities = tuple((item.source_scope, item.record_id) for item in evidence)
    hashes = tuple(item.evidence_hash for item in evidence)
    if len(identities) != len(set(identities)) or len(hashes) != len(set(hashes)):
        raise PlanningLiteratureGapRepairResponseError(
            "gap-repair response evidence must be unique"
        )
    return evidence


def _parse_model_output(
    payload: Mapping[str, Any] | Any,
) -> _PlanningLiteratureGapRepairModelOutput:
    try:
        if not isinstance(payload, Mapping):
            raise TypeError("response must be a JSON object")
        return _PlanningLiteratureGapRepairModelOutput.model_validate(dict(payload))
    except Exception as exc:
        raise PlanningLiteratureGapRepairResponseError(
            f"gap-repair model response contract is invalid: {exc}"
        ) from exc


def planning_literature_gap_repair_stage_input_hash(
    diagnosis: PlanningLiteratureGapDiagnosisReceipt,
    evidence: Sequence[PlanningLiteratureGapRepairEvidenceInput],
    *,
    revision_failure_reason: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "stage": "planning-literature-gap-repair-query",
        "diagnosis_hash": diagnosis.diagnosis_hash,
        "coverage_receipt_hash": diagnosis.coverage_receipt_hash,
        "evidence_inputs": [item.model_dump(mode="json") for item in evidence],
    }
    if revision_failure_reason is not None:
        # Legacy checkpoints (primary attempts) must keep their exact hash shape.
        payload["revision_failure_reason"] = revision_failure_reason
    return canonical_model_hash(payload)


__all__ = [
    "PlanningLiteratureGapRepairResponseError",
    "PlanningLiteratureGapRepairResponseReceipt",
    "build_gap_repair_revision_message",
    "build_planning_literature_gap_repair_messages",
    "gap_repair_failure_is_revisable",
    "load_planning_literature_gap_repair_response",
    "planning_literature_gap_repair_stage_input_hash",
    "run_planning_literature_gap_repair_query",
]
