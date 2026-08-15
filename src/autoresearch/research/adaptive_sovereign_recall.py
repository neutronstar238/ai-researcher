"""Deterministic recall from the complete sovereign raw-memory history."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemoryCapture,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    ModelResearchActionDraft,
)

_ALGORITHM_SPEC = {
    "name": "sovereign-raw-recall",
    "version": 4,
    "normalization": "NFKC-lower",
    "ascii_tokens": "[a-z0-9_+.-]{2,}",
    "cjk_tokens": "overlapping-bigrams",
    "score": "smoothed-idf-overlap-plus-exact-phrase",
    "excerpt_anchor": "fewest-in-payload-occurrences-then-longest-query-token",
    "tie_break": "captured_at_then_record_id",
    "correction_closure": "selected-predecessor-and-successor",
    "fallback": "oldest-and-newest-eligible-records",
    "controller_reuse_eligibility": [
        "exact-snapshot-binding-membership",
        "adaptive-user-seed",
        "adaptive-external-turn-context",
        "adaptive-visible-model-response",
        "adaptive-visible-transition-feedback",
    ],
    "extra_bindings": "inventory-only-never-controller-visible",
    "privacy_default": "all-other-raw-sources-excluded",
}
_ALGORITHM_HASH: Final[
    Literal["c3637c5eceeb144f312c45e9d0429aeabb352ca299e5454b275b2918b72796b0"]
] = "c3637c5eceeb144f312c45e9d0429aeabb352ca299e5454b275b2918b72796b0"
if canonical_sha256(_ALGORITHM_SPEC) != _ALGORITHM_HASH:
    raise RuntimeError("sovereign recall algorithm hash constant is stale")
_ASCII_TOKEN = re.compile(r"[a-z0-9_+.-]{2,}")
_CJK_SEQUENCE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3007]+")
_MODEL_RESPONSE_REF = re.compile(
    r"^adaptive-loop:[A-Za-z0-9_.-]+:step:[0-9]+:attempt:[0-9]+:response$"
)
_TRANSITION_REF = re.compile(r"^adaptive-loop:[A-Za-z0-9_.-]+:step:[0-9]+:transition$")
_EXTERNAL_CONTEXT_REF = re.compile(
    r"^adaptive-loop:[A-Za-z0-9_.-]+:step:[0-9]+:" r"external-context:[A-Za-z0-9_.-]+$"
)
_SEED_REF = re.compile(r"^adaptive-loop:[A-Za-z0-9_.-]+:user-seed$")


class SovereignRecallExcerpt(KernelContract):
    """One bounded derived excerpt tied to exact immutable source bytes."""

    binding: RawMemoryBinding
    source_kind: RawMemorySourceKind
    source_label: str = Field(min_length=1, max_length=512)
    source_ref: str = Field(min_length=1, max_length=2_048)
    captured_at: datetime
    relevance_score: float = Field(ge=0.0)
    excerpt_text: str = Field(min_length=1, max_length=8_000)
    excerpt_sha256: Sha256
    payload_character_count: int = Field(ge=1)
    excerpt_truncated: bool
    previously_visible_to_adaptive_controller: Literal[True] = True

    @model_validator(mode="after")
    def _validate_excerpt(self) -> SovereignRecallExcerpt:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("sovereign recall timestamp must be timezone-aware")
        if hashlib.sha256(self.excerpt_text.encode("utf-8")).hexdigest() != (self.excerpt_sha256):
            raise ValueError("sovereign recall excerpt hash mismatch")
        if self.excerpt_truncated != (len(self.excerpt_text) < self.payload_character_count):
            raise ValueError("sovereign recall truncation flag mismatch")
        if not _source_was_already_controller_visible(
            source_kind=self.source_kind,
            source_ref=self.source_ref,
        ):
            raise ValueError(
                "raw source not previously visible to this controller cannot enter recall prompt"
            )
        return self


class SovereignRecallSelectionContent(KernelContract):
    """Complete, locally computed recall decision; never scientific evidence."""

    schema_version: Literal["adaptive-sovereign-recall-selection-v2"] = (
        "adaptive-sovereign-recall-selection-v2"
    )
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1)
    branch_id: StableId
    snapshot_hash: Sha256
    proposal_hash: Sha256
    query_sha256: Sha256
    selection_algorithm_hash: Literal[
        "c3637c5eceeb144f312c45e9d0429aeabb352ca299e5454b275b2918b72796b0"
    ] = _ALGORITHM_HASH
    maximum_selected_records: int = Field(ge=1, le=12)
    maximum_excerpt_characters: int = Field(ge=256, le=8_000)
    maximum_total_excerpt_characters: int = Field(ge=256, le=64_000)
    candidate_inventory_hash: Sha256
    candidate_record_count: int = Field(ge=1)
    externally_reusable_record_count: int = Field(ge=1)
    privacy_excluded_record_count: int = Field(ge=0)
    selected_excerpts: list[SovereignRecallExcerpt] = Field(min_length=1, max_length=12)
    omitted_record_ids_hash: Sha256
    omitted_record_count: int = Field(ge=0)
    correction_chain_closed: Literal[True] = True
    local_selection_only: Literal[True] = True
    contains_previously_exposed_raw_excerpts: Literal[True] = True
    reuse_scope: Literal["adaptive_controller_context_only"] = "adaptive_controller_context_only"
    public_export_authorized: Literal[False] = False
    raw_records_mutated: Literal[False] = False
    derived_and_rebuildable: Literal[True] = True
    scientific_evidence_established: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_selection(self) -> SovereignRecallSelectionContent:
        if self.maximum_total_excerpt_characters < self.maximum_excerpt_characters:
            raise ValueError("sovereign recall excerpt budgets are inconsistent")
        selected_ids = [item.binding.record_id for item in self.selected_excerpts]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("sovereign recall selected the same record twice")
        if self.externally_reusable_record_count + self.privacy_excluded_record_count != (
            self.candidate_record_count
        ):
            raise ValueError("sovereign recall candidate accounting mismatch")
        if self.omitted_record_count != (
            self.externally_reusable_record_count - len(self.selected_excerpts)
        ):
            raise ValueError("sovereign recall omission count mismatch")
        return self


class SovereignRecallSelection(SovereignRecallSelectionContent):
    selection_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> SovereignRecallSelection:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"selection_hash"}))
        if self.selection_hash != expected:
            raise ValueError("sovereign recall selection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SovereignRecallSelection:
        content = SovereignRecallSelectionContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, selection_hash=canonical_sha256(payload))


class SovereignRawRecallEngine:
    """Recall exact prior loop bytes without relying on the recent-event window."""

    def __init__(
        self,
        *,
        raw_memory_store: RawMemoryStore,
        maximum_selected_records: int = 8,
        maximum_excerpt_characters: int = 2_000,
        maximum_total_excerpt_characters: int = 12_000,
    ) -> None:
        if not 1 <= maximum_selected_records <= 12:
            raise AdaptiveResearchLoopError("sovereign recall record bound is invalid")
        if not 256 <= maximum_excerpt_characters <= 8_000:
            raise AdaptiveResearchLoopError("sovereign recall excerpt bound is invalid")
        if not (maximum_excerpt_characters <= maximum_total_excerpt_characters <= 64_000):
            raise AdaptiveResearchLoopError("sovereign recall total bound is invalid")
        self._store = raw_memory_store
        self._maximum_selected_records = maximum_selected_records
        self._maximum_excerpt_characters = maximum_excerpt_characters
        self._maximum_total_excerpt_characters = maximum_total_excerpt_characters

    def recall(
        self,
        *,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        extra_bindings: Sequence[RawMemoryBinding] = (),
        output_path: Path | str | None = None,
    ) -> SovereignRecallSelection:
        if proposal.step_index != snapshot.next_step_index:
            raise AdaptiveResearchLoopError("sovereign recall proposal step mismatch")
        if proposal.branch_id not in {branch.branch_id for branch in snapshot.branches}:
            raise AdaptiveResearchLoopError("sovereign recall proposal branch is absent")
        bindings = _snapshot_raw_bindings(snapshot, extra_bindings=extra_bindings)
        exposed_record_ids = {
            binding.record_id for binding in _snapshot_raw_bindings(snapshot, extra_bindings=())
        }
        captures = [
            self._store.load_record(
                binding.record_relative_path,
                project_id=snapshot.seed.project_id,
            )
            for binding in bindings
        ]
        for binding, capture in zip(bindings, captures, strict=True):
            _require_binding_matches_capture(
                binding,
                capture,
                vault_root=self._store.vault_root,
            )
        eligible = [
            capture
            for capture in captures
            if capture.record.record_id in exposed_record_ids
            and _capture_was_already_controller_visible(
                capture,
                loop_id=snapshot.seed.loop_id,
            )
        ]
        if not eligible:
            raise AdaptiveResearchLoopError(
                "sovereign recall has no privacy-eligible prior records"
            )
        payloads = {capture.record.record_id: _load_utf8_payload(capture) for capture in eligible}
        query = "\n".join(
            item
            for item in (
                proposal.action_title_cn,
                proposal.action_body_cn,
                proposal.working_hypothesis_cn,
            )
            if item
        )
        query_tokens = _tokens(query)
        scores = _relevance_scores(payloads, query=query, query_tokens=query_tokens)
        selected_ids = _select_record_ids(
            eligible,
            scores=scores,
            maximum_selected_records=self._maximum_selected_records,
        )
        selected_ids = _close_correction_chains(
            eligible,
            selected_ids=selected_ids,
            maximum_selected_records=self._maximum_selected_records,
        )
        eligible_by_id = {capture.record.record_id: capture for capture in eligible}
        excerpt_budget = self._maximum_total_excerpt_characters
        excerpts: list[SovereignRecallExcerpt] = []
        for record_id in selected_ids:
            capture = eligible_by_id[record_id]
            payload = payloads[record_id]
            remaining_records = len(selected_ids) - len(excerpts)
            per_record = min(
                self._maximum_excerpt_characters,
                max(256, excerpt_budget // remaining_records),
            )
            excerpt = _bounded_excerpt(payload, query_tokens, per_record)
            excerpt_budget -= len(excerpt)
            envelope = capture.record.envelope
            excerpts.append(
                SovereignRecallExcerpt(
                    binding=capture.binding(self._store.vault_root),
                    source_kind=envelope.source_kind,
                    source_label=envelope.source_label,
                    source_ref=envelope.source_ref,
                    captured_at=envelope.captured_at,
                    relevance_score=scores[record_id],
                    excerpt_text=excerpt,
                    excerpt_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                    payload_character_count=len(payload),
                    excerpt_truncated=len(excerpt) < len(payload),
                )
            )
        omitted_ids = sorted(set(eligible_by_id) - set(selected_ids))
        selection = SovereignRecallSelection.create(
            loop_id=snapshot.seed.loop_id,
            project_id=snapshot.seed.project_id,
            step_index=proposal.step_index,
            branch_id=proposal.branch_id,
            snapshot_hash=snapshot.snapshot_hash,
            proposal_hash=canonical_sha256(proposal),
            query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            maximum_selected_records=self._maximum_selected_records,
            maximum_excerpt_characters=self._maximum_excerpt_characters,
            maximum_total_excerpt_characters=(self._maximum_total_excerpt_characters),
            candidate_inventory_hash=canonical_sha256(
                [binding.model_dump(mode="json") for binding in bindings]
            ),
            candidate_record_count=len(captures),
            externally_reusable_record_count=len(eligible),
            privacy_excluded_record_count=len(captures) - len(eligible),
            selected_excerpts=excerpts,
            omitted_record_ids_hash=canonical_sha256(omitted_ids),
            omitted_record_count=len(omitted_ids),
        )
        if output_path is not None:
            _write_once(
                Path(output_path),
                (canonical_json(selection) + "\n").encode("utf-8"),
            )
        return selection


def recall_findings_cn(selection: SovereignRecallSelection) -> list[str]:
    """Return bounded controller-visible excerpts with explicit epistemic scope."""

    findings = [
        (
            f"原始记忆{index}（selection_hash={selection.selection_hash}，"
            f"record_id={excerpt.binding.record_id}，"
            f"payload_sha256={excerpt.binding.payload_sha256}，来源类型="
            f"{excerpt.source_kind.value}，excerpt_sha256={excerpt.excerpt_sha256}）："
            f"{excerpt.excerpt_text}"
        )
        for index, excerpt in enumerate(selection.selected_excerpts, start=1)
    ]
    findings.append(
        "以上是从完整只追加历史中确定性召回的派生工作片段；它们可能互相冲突或已经失效，"
        "必须结合来源与纠错链判断，不能直接作为科学证据。"
    )
    return findings


def _snapshot_raw_bindings(
    snapshot: AdaptiveResearchLoopSnapshot,
    *,
    extra_bindings: Sequence[RawMemoryBinding],
) -> list[RawMemoryBinding]:
    ordered = [snapshot.seed.raw_seed_binding]
    for event in snapshot.events:
        ordered.extend(context.raw_binding for context in event.interaction.external_turn_contexts)
        ordered.append(event.interaction.response_binding)
        ordered.extend(attempt.response_binding for attempt in event.interaction.rejected_attempts)
        ordered.append(event.event_payload_binding)
    ordered.extend(extra_bindings)
    by_id: dict[str, RawMemoryBinding] = {}
    for binding in ordered:
        existing = by_id.get(binding.record_id)
        if existing is not None and existing != binding:
            raise AdaptiveResearchLoopError("sovereign recall record ID has conflicting bindings")
        by_id.setdefault(binding.record_id, binding)
    return list(by_id.values())


def _capture_was_already_controller_visible(
    capture: RawMemoryCapture,
    *,
    loop_id: str,
) -> bool:
    envelope = capture.record.envelope
    expected_prefix = f"adaptive-loop:{loop_id}:"
    return envelope.source_ref.startswith(expected_prefix) and (
        _source_was_already_controller_visible(
            source_kind=envelope.source_kind,
            source_ref=envelope.source_ref,
        )
    )


def _source_was_already_controller_visible(
    *,
    source_kind: RawMemorySourceKind,
    source_ref: str,
) -> bool:
    if source_kind is RawMemorySourceKind.USER_TEXT:
        return _SEED_REF.fullmatch(source_ref) is not None
    if source_kind is RawMemorySourceKind.MODEL_TRANSCRIPT:
        return _MODEL_RESPONSE_REF.fullmatch(source_ref) is not None
    if source_kind is RawMemorySourceKind.TOOL_OUTPUT:
        return (
            _TRANSITION_REF.fullmatch(source_ref) is not None
            or _EXTERNAL_CONTEXT_REF.fullmatch(source_ref) is not None
        )
    return False


def _require_binding_matches_capture(
    binding: RawMemoryBinding,
    capture: RawMemoryCapture,
    *,
    vault_root: Path,
) -> None:
    expected = capture.binding(vault_root)
    if binding != expected:
        raise AdaptiveResearchLoopError("sovereign recall raw binding mismatch")


def _load_utf8_payload(capture: RawMemoryCapture) -> str:
    try:
        payload = capture.blob_path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AdaptiveResearchLoopError(
            f"sovereign recall accepts only verified UTF-8 records: {exc}"
        ) from exc
    if not text.strip():
        raise AdaptiveResearchLoopError("sovereign recall raw payload is empty")
    return text


def _tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = set(_ASCII_TOKEN.findall(normalized))
    for sequence in _CJK_SEQUENCE.findall(normalized):
        if len(sequence) == 1:
            tokens.add(sequence)
        else:
            tokens.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return tokens


def _relevance_scores(
    payloads: dict[str, str],
    *,
    query: str,
    query_tokens: set[str],
) -> dict[str, float]:
    document_tokens = {record_id: _tokens(payload) for record_id, payload in payloads.items()}
    frequencies = Counter(token for tokens in document_tokens.values() for token in tokens)
    count = len(document_tokens)
    normalized_query = unicodedata.normalize("NFKC", query).lower().strip()
    scores: dict[str, float] = {}
    for record_id, tokens in document_tokens.items():
        overlap = tokens.intersection(query_tokens)
        score = math.fsum(
            1.0 + math.log((count + 1.0) / (frequencies[token] + 1.0)) for token in sorted(overlap)
        )
        normalized_payload = unicodedata.normalize("NFKC", payloads[record_id]).lower()
        if normalized_query and normalized_query in normalized_payload:
            score += 8.0
        scores[record_id] = round(score, 12)
    return scores


def _select_record_ids(
    captures: Sequence[RawMemoryCapture],
    *,
    scores: dict[str, float],
    maximum_selected_records: int,
) -> list[str]:
    ranked = sorted(
        captures,
        key=lambda capture: (
            -scores[capture.record.record_id],
            capture.record.envelope.captured_at,
            capture.record.record_id,
        ),
    )
    positive = [
        capture.record.record_id for capture in ranked if scores[capture.record.record_id] > 0
    ]
    if positive:
        return positive[:maximum_selected_records]
    chronological = sorted(
        captures,
        key=lambda capture: (
            capture.record.envelope.captured_at,
            capture.record.record_id,
        ),
    )
    fallback = [chronological[0].record.record_id]
    if len(chronological) > 1:
        fallback.append(chronological[-1].record.record_id)
    return fallback[:maximum_selected_records]


def _close_correction_chains(
    captures: Sequence[RawMemoryCapture],
    *,
    selected_ids: Sequence[str],
    maximum_selected_records: int,
) -> list[str]:
    by_id = {capture.record.record_id: capture for capture in captures}
    neighbours: dict[str, set[str]] = {record_id: set() for record_id in by_id}
    for capture in captures:
        predecessor = capture.record.envelope.supersedes_record_id
        if predecessor in by_id:
            neighbours[capture.record.record_id].add(predecessor)
            neighbours[predecessor].add(capture.record.record_id)

    def component(record_id: str) -> list[str]:
        discovered = {record_id}
        queue = [record_id]
        while queue:
            current = queue.pop(0)
            for related_id in sorted(neighbours[current]):
                if related_id not in discovered:
                    discovered.add(related_id)
                    queue.append(related_id)
        return [record_id, *sorted(discovered - {record_id})]

    closed: list[str] = []
    visited_components: set[frozenset[str]] = set()
    for record_id in selected_ids:
        related = component(record_id)
        component_key = frozenset(related)
        if component_key in visited_components:
            continue
        visited_components.add(component_key)
        if len(component_key) > maximum_selected_records:
            raise AdaptiveResearchLoopError(
                "sovereign recall correction chain exceeds its record budget"
            )
        missing = [related_id for related_id in related if related_id not in closed]
        if len(closed) + len(missing) > maximum_selected_records:
            continue
        closed.extend(missing)
    if not closed:
        raise AdaptiveResearchLoopError(
            "sovereign recall could not close any correction chain within budget"
        )
    return closed


def _bounded_excerpt(payload: str, query_tokens: set[str], limit: int) -> str:
    if len(payload) <= limit:
        return payload
    normalized = unicodedata.normalize("NFKC", payload).lower()
    anchors = [
        (normalized.count(token), -len(token), token, normalized.find(token))
        for token in query_tokens
        if token in normalized
    ]
    center = min(anchors)[3] if anchors else 0
    start = max(0, center - limit // 3)
    end = min(len(payload), start + limit)
    start = max(0, end - limit)
    return payload[start:end]


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveResearchLoopError(
                f"immutable sovereign recall selection changed: {path}"
            ) from None


__all__ = [
    "SovereignRawRecallEngine",
    "SovereignRecallExcerpt",
    "SovereignRecallSelection",
    "recall_findings_cn",
]
