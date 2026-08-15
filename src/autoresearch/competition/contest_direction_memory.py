"""Best-effort sovereign memory for the lightweight direction research loop.

The research loop remains evidence-first.  This module only mirrors completed
stage artifacts into the existing append-only :class:`RawMemoryStore` and builds
an optional, rebuildable Dreaming navigation view over the exact raw bindings.
Neither a Dreaming summary nor a recall receipt is scientific evidence, and a
memory failure never changes or blocks the stage artifact being delivered.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    DreamingMemoryContent,
    MemoryClaimAssessment,
    MemoryClaimVerdict,
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
)

_SAFE_STAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MEMORY_SCHEMA = "contest-direction-stage-memory-v1"
_RECALL_SCHEMA = "contest-direction-memory-recall-v1"
_BOUNDARY_ZH = (
    "Dreaming 只是可删除、可重建的导航上下文，不是文献、实验结果或科学证据；"
    "任何科学陈述仍须读取并核验所绑定的原始制品。"
)


class ContestDirectionMemoryError(RuntimeError):
    """Raised by strict loading; best-effort public methods degrade instead."""


class StageRawArtifactBinding(KernelContract):
    """One completed run artifact bound to an immutable raw-memory record."""

    artifact_relative_path: str = Field(min_length=1, max_length=2048)
    artifact_sha256: Sha256
    artifact_bytes: int = Field(ge=1)
    media_type: str = Field(min_length=3, max_length=255)
    source_kind: RawMemorySourceKind
    raw_binding: RawMemoryBinding

    @field_validator("artifact_relative_path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("stage-memory artifact path must be safe and relative")
        return path.as_posix()

    @model_validator(mode="after")
    def _bind_exact_payload(self) -> StageRawArtifactBinding:
        if self.artifact_sha256 != self.raw_binding.payload_sha256:
            raise ValueError("stage artifact hash differs from raw-memory payload hash")
        return self


class StageMemoryReceipt(KernelContract):
    """Non-blocking receipt for raw capture plus an optional Dreaming view."""

    schema_version: Literal["contest-direction-stage-memory-v1"] = (
        "contest-direction-stage-memory-v1"
    )
    project_id: StableId
    stage: StableId
    recorded_at: datetime
    status: Literal["complete", "degraded", "unavailable"]
    artifacts: tuple[StageRawArtifactBinding, ...] = ()
    dreaming_projection_id: StableId | None = None
    dreaming_projection_hash: Sha256 | None = None
    dreaming_json_relative_path: str | None = None
    dreaming_markdown_relative_path: str | None = None
    errors: tuple[str, ...] = ()
    raw_artifacts_mutated: Literal[False] = False
    derived_context_is_evidence: Literal[False] = False
    delivery_blocked_by_memory: Literal[False] = False
    epistemic_boundary_zh: str = _BOUNDARY_ZH
    receipt_hash: Sha256

    @field_validator("stage")
    @classmethod
    def _safe_stage(cls, value: str) -> str:
        if not _SAFE_STAGE.fullmatch(value):
            raise ValueError("memory stage must be one safe path segment")
        return value

    @model_validator(mode="after")
    def _verify_receipt(self) -> StageMemoryReceipt:
        projection_fields = (
            self.dreaming_projection_id,
            self.dreaming_projection_hash,
            self.dreaming_json_relative_path,
            self.dreaming_markdown_relative_path,
        )
        if any(item is None for item in projection_fields) != all(
            item is None for item in projection_fields
        ):
            raise ValueError("Dreaming receipt fields must be all present or all absent")
        if self.status == "complete" and (
            not self.artifacts or all(item is None for item in projection_fields)
        ):
            raise ValueError("complete stage memory requires raw artifacts and Dreaming")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ValueError("stage-memory receipt hash mismatch")
        return self


class RecalledDreamingProjection(KernelContract):
    """Verified derived view selected for optional downstream navigation."""

    source_stage: StableId
    stage_receipt_hash: Sha256
    projection_id: StableId
    projection_hash: Sha256
    summary: str = Field(min_length=1, max_length=32768)
    raw_bindings: tuple[RawMemoryBinding, ...] = Field(min_length=1)


class MemoryRecallReceipt(KernelContract):
    """Separates recall selection from any later model consumption claim."""

    schema_version: Literal["contest-direction-memory-recall-v1"] = (
        "contest-direction-memory-recall-v1"
    )
    project_id: StableId
    consumer_stage: StableId
    requested: bool
    requested_source_stages: tuple[StableId, ...] = ()
    recorded_at: datetime
    status: Literal["not_requested", "available", "degraded", "unavailable"]
    selected: tuple[RecalledDreamingProjection, ...] = ()
    errors: tuple[str, ...] = ()
    derived_context_is_evidence: Literal[False] = False
    model_consumption_proven: Literal[False] = False
    delivery_blocked_by_memory: Literal[False] = False
    epistemic_boundary_zh: str = _BOUNDARY_ZH
    recall_hash: Sha256

    @field_validator("consumer_stage")
    @classmethod
    def _safe_stage(cls, value: str) -> str:
        if not _SAFE_STAGE.fullmatch(value):
            raise ValueError("memory consumer stage must be one safe path segment")
        return value

    @field_validator("requested_source_stages")
    @classmethod
    def _unique_source_stages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for stage in value:
            if not _SAFE_STAGE.fullmatch(stage):
                raise ValueError("memory source stage must be one safe path segment")
        if len(value) != len(set(value)):
            raise ValueError("memory source stages must be unique")
        return value

    @model_validator(mode="after")
    def _verify_receipt(self) -> MemoryRecallReceipt:
        if not self.requested and (self.status != "not_requested" or self.selected):
            raise ValueError("unrequested memory cannot select Dreaming projections")
        if not self.requested and self.requested_source_stages:
            raise ValueError("unrequested memory cannot name source stages")
        if self.status == "available" and not self.selected:
            raise ValueError("available memory recall requires a selected projection")
        if self.status == "unavailable" and self.selected:
            raise ValueError("unavailable memory recall cannot contain a selection")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"recall_hash"}))
        if self.recall_hash != expected:
            raise ValueError("memory recall hash mismatch")
        return self

    def optional_context(self) -> dict[str, Any] | None:
        """Return a clearly labelled prompt projection, or no context at all."""

        if not self.requested or not self.selected:
            return None
        return {
            "context_kind": "optional_rebuildable_dreaming_navigation",
            "recall_hash": self.recall_hash,
            "epistemic_boundary_zh": self.epistemic_boundary_zh,
            "derived_context_is_evidence": False,
            "model_consumption_proven_by_this_receipt": False,
            "projections": [item.model_dump(mode="json") for item in self.selected],
        }


@dataclass(frozen=True)
class StageMemoryResult:
    """Stage receipt and its persisted path, if best-effort persistence worked."""

    receipt: StageMemoryReceipt
    receipt_path: Path | None


@dataclass(frozen=True)
class MemoryRecallResult:
    """Optional recall receipt and the context a caller may explicitly inject."""

    receipt: MemoryRecallReceipt
    receipt_path: Path | None

    @property
    def context(self) -> dict[str, Any] | None:
        return self.receipt.optional_context()


class ContestDirectionMemoryBridge:
    """Mirror completed lightweight-loop stages without governing the loop."""

    def __init__(
        self,
        *,
        output_root: Path | str,
        project_id: str,
        vault_root: Path | str = Path("autoresearch-vault"),
        raw_memory_store: RawMemoryStore | None = None,
        enabled: bool = True,
        clock: Any | None = None,
    ) -> None:
        self.output_root = Path(output_root).expanduser().resolve()
        self.project_id = project_id
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.memory_root = self.output_root / "memory"
        self.enabled = enabled
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._store: RawMemoryStore | None = None
        self._startup_error: str | None = None
        if not enabled:
            return
        try:
            self._store = raw_memory_store or RawMemoryStore(self.vault_root)
        except Exception as exc:  # memory is explicitly a non-blocking sidecar
            self._startup_error = _safe_error("raw-memory startup", exc)

    def capture_completed_stage(
        self,
        *,
        stage: str,
        artifact_paths: tuple[Path | str, ...] | list[Path | str],
    ) -> StageMemoryResult:
        """Capture exact completed-stage files and build one derived index."""

        _require_safe_stage(stage)
        receipt_path = self.memory_root / "stages" / f"{stage}.json"
        if receipt_path.is_file():
            try:
                return StageMemoryResult(
                    receipt=self.load_stage_receipt(stage),
                    receipt_path=receipt_path,
                )
            except Exception as exc:
                return StageMemoryResult(
                    receipt=self._degraded_stage_receipt(
                        stage,
                        errors=(_safe_error("existing stage-memory receipt", exc),),
                    ),
                    receipt_path=None,
                )

        errors: list[str] = []
        bindings: list[StageRawArtifactBinding] = []
        if not self.enabled:
            errors.append("memory disabled by caller")
        elif self._startup_error is not None or self._store is None:
            errors.append(self._startup_error or "raw-memory store unavailable")
        else:
            for source in self._discover_artifacts(artifact_paths, errors=errors):
                relative = source.relative_to(self.output_root).as_posix()
                try:
                    capture = self._store.capture_file(
                        source,
                        project_id=self.project_id,
                        source_kind=_source_kind(source),
                        source_label=f"轻量科研链已完成阶段制品：{stage}",
                        source_ref=(
                            f"contest-direction-loop:{self.project_id}:stage:{stage}:"
                            f"artifact:{relative}"
                        ),
                        media_type=_media_type(source),
                        source_authorized=True,
                        sensitive_content_reviewed=True,
                        captured_at=self._now(),
                    )
                    binding = capture.binding(self._store.vault_root)
                    if _sha256_file(source) != binding.payload_sha256:
                        raise ContestDirectionMemoryError(
                            "completed-stage artifact changed during raw capture"
                        )
                    bindings.append(
                        StageRawArtifactBinding(
                            artifact_relative_path=relative,
                            artifact_sha256=binding.payload_sha256,
                            artifact_bytes=capture.record.envelope.payload_size,
                            media_type=capture.record.envelope.media_type,
                            source_kind=capture.record.envelope.source_kind,
                            raw_binding=binding,
                        )
                    )
                except Exception as exc:  # one bad sidecar must not hide valid artifacts
                    errors.append(_safe_error(f"capture {relative}", exc))

        projection_fields: dict[str, str | None] = {
            "dreaming_projection_id": None,
            "dreaming_projection_hash": None,
            "dreaming_json_relative_path": None,
            "dreaming_markdown_relative_path": None,
        }
        if bindings and self._store is not None:
            try:
                dreaming = self._store.write_dreaming_projection(
                    _stage_dreaming_content(
                        project_id=self.project_id,
                        stage=stage,
                        artifacts=tuple(bindings),
                        generated_at=self._now(),
                    )
                )
                projection_fields = {
                    "dreaming_projection_id": dreaming.projection.projection_id,
                    "dreaming_projection_hash": dreaming.projection.projection_hash,
                    "dreaming_json_relative_path": dreaming.json_path.relative_to(
                        self._store.vault_root
                    ).as_posix(),
                    "dreaming_markdown_relative_path": dreaming.markdown_path.relative_to(
                        self._store.vault_root
                    ).as_posix(),
                }
            except Exception as exc:
                errors.append(_safe_error("Dreaming projection", exc))

        status: Literal["complete", "degraded", "unavailable"]
        if bindings and projection_fields["dreaming_projection_id"] is not None and not errors:
            status = "complete"
        elif bindings:
            status = "degraded"
        else:
            status = "unavailable"
        receipt = _make_stage_receipt(
            project_id=self.project_id,
            stage=stage,
            recorded_at=self._now(),
            status=status,
            artifacts=tuple(bindings),
            errors=tuple(errors),
            **projection_fields,
        )
        persisted = _persist_best_effort(receipt_path, receipt)
        return StageMemoryResult(receipt=receipt, receipt_path=receipt_path if persisted else None)

    def load_stage_receipt(self, stage: str) -> StageMemoryReceipt:
        """Strictly reload a receipt, raw files, sources, and Dreaming projection."""

        _require_safe_stage(stage)
        path = self.memory_root / "stages" / f"{stage}.json"
        try:
            receipt = StageMemoryReceipt.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ContestDirectionMemoryError(
                f"cannot load stage-memory receipt: {type(exc).__name__}"
            ) from exc
        if receipt.project_id != self.project_id or receipt.stage != stage:
            raise ContestDirectionMemoryError("stage-memory receipt identity mismatch")
        if self._store is None:
            raise ContestDirectionMemoryError("raw-memory store unavailable during receipt replay")
        for artifact in receipt.artifacts:
            source = (self.output_root / artifact.artifact_relative_path).resolve()
            if not source.is_relative_to(self.output_root) or not source.is_file():
                raise ContestDirectionMemoryError("bound stage artifact is missing")
            if _sha256_file(source) != artifact.artifact_sha256:
                raise ContestDirectionMemoryError("bound stage artifact changed after capture")
            capture = self._store.load_record(
                artifact.raw_binding.record_relative_path,
                project_id=self.project_id,
            )
            if capture.binding(self._store.vault_root) != artifact.raw_binding:
                raise ContestDirectionMemoryError("raw-memory binding changed after capture")
        if receipt.dreaming_projection_id is not None:
            dreaming = self._store.load_dreaming_projection(
                receipt.dreaming_projection_id,
                project_id=self.project_id,
            )
            if dreaming.projection.projection_hash != receipt.dreaming_projection_hash:
                raise ContestDirectionMemoryError("Dreaming projection hash mismatch")
        return receipt

    def recall_optional_context(
        self,
        *,
        consumer_stage: str,
        source_stages: tuple[str, ...] | list[str],
        requested: bool,
        max_projections: int = 8,
    ) -> MemoryRecallResult:
        """Select verified derived views; never claim that the model consumed them."""

        _require_safe_stage(consumer_stage)
        if max_projections < 1:
            raise ValueError("max_projections must be positive")
        normalized_sources = tuple(dict.fromkeys(source_stages)) if requested else ()
        for stage in normalized_sources:
            _require_safe_stage(stage)
        receipt_path = self.memory_root / "recalls" / f"{consumer_stage}.json"
        if receipt_path.is_file():
            try:
                receipt = MemoryRecallReceipt.model_validate_json(receipt_path.read_bytes())
                if (
                    receipt.project_id != self.project_id
                    or receipt.consumer_stage != consumer_stage
                    or receipt.requested != requested
                    or receipt.requested_source_stages != normalized_sources
                ):
                    raise ContestDirectionMemoryError("memory recall identity mismatch")
                self._verify_recall_receipt(receipt)
                return MemoryRecallResult(receipt=receipt, receipt_path=receipt_path)
            except Exception as exc:
                fallback = _make_recall_receipt(
                    project_id=self.project_id,
                    consumer_stage=consumer_stage,
                    requested=requested,
                    requested_source_stages=normalized_sources,
                    recorded_at=self._now(),
                    status="unavailable" if requested else "not_requested",
                    selected=(),
                    errors=(_safe_error("existing recall receipt", exc),),
                )
                return MemoryRecallResult(receipt=fallback, receipt_path=None)

        errors: list[str] = []
        selected: list[RecalledDreamingProjection] = []
        if requested and self.enabled and self._store is not None:
            for stage in normalized_sources[-max_projections:]:
                try:
                    stage_receipt = self.load_stage_receipt(stage)
                    projection_id = stage_receipt.dreaming_projection_id
                    if projection_id is None:
                        raise ContestDirectionMemoryError(
                            "stage has no verified Dreaming projection"
                        )
                    dreaming = self._store.load_dreaming_projection(
                        projection_id,
                        project_id=self.project_id,
                    )
                    selected.append(
                        RecalledDreamingProjection(
                            source_stage=stage,
                            stage_receipt_hash=stage_receipt.receipt_hash,
                            projection_id=dreaming.projection.projection_id,
                            projection_hash=dreaming.projection.projection_hash,
                            summary=dreaming.projection.content.summary,
                            raw_bindings=tuple(dreaming.projection.content.source_bindings),
                        )
                    )
                except Exception as exc:
                    errors.append(_safe_error(f"recall {stage}", exc))
        elif requested:
            errors.append(self._startup_error or "raw-memory store unavailable")

        status: Literal["not_requested", "available", "degraded", "unavailable"]
        if not requested:
            status = "not_requested"
        elif selected and not errors:
            status = "available"
        elif selected:
            status = "degraded"
        else:
            status = "unavailable"
        receipt = _make_recall_receipt(
            project_id=self.project_id,
            consumer_stage=consumer_stage,
            requested=requested,
            requested_source_stages=normalized_sources,
            recorded_at=self._now(),
            status=status,
            selected=tuple(selected),
            errors=tuple(errors),
        )
        persisted = _persist_best_effort(receipt_path, receipt)
        return MemoryRecallResult(receipt=receipt, receipt_path=receipt_path if persisted else None)

    def _verify_recall_receipt(self, receipt: MemoryRecallReceipt) -> None:
        if self._store is None and receipt.selected:
            raise ContestDirectionMemoryError("raw-memory store unavailable during recall replay")
        for selected in receipt.selected:
            stage_receipt = self.load_stage_receipt(selected.source_stage)
            if stage_receipt.receipt_hash != selected.stage_receipt_hash:
                raise ContestDirectionMemoryError("recalled stage receipt hash mismatch")
            if stage_receipt.dreaming_projection_id != selected.projection_id:
                raise ContestDirectionMemoryError("recalled Dreaming projection ID mismatch")
            assert self._store is not None
            dreaming = self._store.load_dreaming_projection(
                selected.projection_id,
                project_id=self.project_id,
            )
            if (
                dreaming.projection.projection_hash != selected.projection_hash
                or dreaming.projection.content.summary != selected.summary
                or tuple(dreaming.projection.content.source_bindings) != selected.raw_bindings
            ):
                raise ContestDirectionMemoryError(
                    "recalled Dreaming projection no longer matches its selection"
                )

    def _discover_artifacts(
        self,
        paths: tuple[Path | str, ...] | list[Path | str],
        *,
        errors: list[str],
    ) -> tuple[Path, ...]:
        discovered: dict[str, Path] = {}
        for raw_path in paths:
            candidate = Path(raw_path).expanduser().resolve()
            if not candidate.is_relative_to(self.output_root):
                errors.append("artifact path outside the research-loop output root")
                continue
            if candidate == self.memory_root or self.memory_root in candidate.parents:
                continue
            if candidate.is_file():
                discovered[candidate.as_posix()] = candidate
            elif candidate.is_dir():
                for item in candidate.rglob("*"):
                    resolved = item.resolve()
                    if (
                        resolved.is_file()
                        and resolved.is_relative_to(self.output_root)
                        and self.memory_root not in resolved.parents
                    ):
                        discovered[resolved.as_posix()] = resolved
            else:
                try:
                    label = candidate.relative_to(self.output_root).as_posix()
                except ValueError:
                    label = "outside-output-root"
                errors.append(f"artifact missing: {label}")
        return tuple(discovered[key] for key in sorted(discovered))

    def _degraded_stage_receipt(
        self,
        stage: str,
        *,
        errors: tuple[str, ...],
    ) -> StageMemoryReceipt:
        return _make_stage_receipt(
            project_id=self.project_id,
            stage=stage,
            recorded_at=self._now(),
            status="unavailable",
            artifacts=(),
            errors=errors,
            dreaming_projection_id=None,
            dreaming_projection_hash=None,
            dreaming_json_relative_path=None,
            dreaming_markdown_relative_path=None,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ContestDirectionMemoryError("memory clock must be timezone-aware")
        return value.astimezone(timezone.utc)


def _stage_dreaming_content(
    *,
    project_id: str,
    stage: str,
    artifacts: tuple[StageRawArtifactBinding, ...],
    generated_at: datetime,
) -> DreamingMemoryContent:
    bindings = tuple(item.raw_binding for item in artifacts)
    displayed = artifacts[:80]
    lines = [
        f"阶段 `{stage}` 已有 {len(artifacts)} 个完成制品进入原始记忆。",
        "本摘要只列导航元数据，不复述或推断科学结论：",
        *(
            f"- `{item.artifact_relative_path}`；bytes={item.artifact_bytes}；"
            f"sha256={item.artifact_sha256}"
            for item in displayed
        ),
    ]
    if len(artifacts) > len(displayed):
        lines.append(f"- 其余 {len(artifacts) - len(displayed)} 个制品仅保留精确绑定。")
    evidence_refs = [
        f"raw:{binding.record_id}#sha256:{binding.payload_sha256}" for binding in bindings
    ]
    return DreamingMemoryContent(
        project_id=project_id,
        title=f"轻量科研链阶段记忆：{stage}",
        generated_at=generated_at,
        generator_identity="contest-direction-memory-bridge-v1",
        source_bindings=list(bindings),
        summary="\n".join(lines),
        claim_assessments=[
            MemoryClaimAssessment(
                claim=f"阶段 {stage} 的这些制品可能有助于后续阶段定位上下文。",
                verdict=MemoryClaimVerdict.UNVERIFIED,
                rationale=(
                    "这只是确定性导航索引。被保存或被召回不证明内容正确、相关、"
                    "新颖，也不证明后续模型实际使用了它。"
                ),
                evidence_refs=evidence_refs,
            )
        ],
        design_decisions=[
            "仅在后续阶段明确请求时暴露本派生导航上下文。",
            "科学数字和结论必须回到绑定的原始制品核验，禁止引用本摘要作为证据。",
        ],
    )


def normalize_optional_dreaming_context(
    value: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate the only derived-memory shape allowed into model messages."""

    if value is None:
        return None
    context = dict(value)
    if (
        context.get("context_kind") != "optional_rebuildable_dreaming_navigation"
        or context.get("derived_context_is_evidence") is not False
        or context.get("model_consumption_proven_by_this_receipt") is not False
        or context.get("epistemic_boundary_zh") != _BOUNDARY_ZH
    ):
        raise ContestDirectionMemoryError("invalid optional Dreaming context boundary")
    recall_hash = context.get("recall_hash")
    projections = context.get("projections")
    if not isinstance(recall_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", recall_hash):
        raise ContestDirectionMemoryError("optional Dreaming context lacks recall hash")
    if not isinstance(projections, list) or not projections:
        raise ContestDirectionMemoryError("optional Dreaming context lacks projections")
    # Round-trip through JSON so no mutable model/object sneaks into a provider request.
    return cast(
        dict[str, Any],
        json.loads(json.dumps(context, ensure_ascii=False, sort_keys=True)),
    )


def optional_dreaming_context_hash(value: dict[str, Any] | None) -> str | None:
    """Hash the exact validated derived context independently of evidence hashes."""

    normalized = normalize_optional_dreaming_context(value)
    return canonical_sha256(normalized) if normalized is not None else None


def optional_dreaming_context_message(value: dict[str, Any]) -> dict[str, str]:
    """Render one independent navigation-only user message."""

    normalized = normalize_optional_dreaming_context(value)
    if normalized is None:  # pragma: no cover - non-null public contract
        raise ContestDirectionMemoryError("Dreaming context message requires context")
    return {
        "role": "user",
        "content": json.dumps(
            {
                **normalized,
                "navigation_only": True,
                "summary_may_support_scientific_claims": False,
                "scientific_claims_require_exact_source_artifact": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _make_stage_receipt(**values: Any) -> StageMemoryReceipt:
    payload = {"schema_version": _MEMORY_SCHEMA, **values}
    json_payload = StageMemoryReceipt.model_construct(
        **payload,
        receipt_hash="0" * 64,
    ).model_dump(mode="json", exclude={"receipt_hash"})
    json_payload["receipt_hash"] = canonical_sha256(json_payload)
    return StageMemoryReceipt.model_validate(json_payload)


def _make_recall_receipt(**values: Any) -> MemoryRecallReceipt:
    payload = {"schema_version": _RECALL_SCHEMA, **values}
    json_payload = MemoryRecallReceipt.model_construct(
        **payload,
        recall_hash="0" * 64,
    ).model_dump(mode="json", exclude={"recall_hash"})
    json_payload["recall_hash"] = canonical_sha256(json_payload)
    return MemoryRecallReceipt.model_validate(json_payload)


def _persist_best_effort(path: Path, model: KernelContract) -> bool:
    payload = (canonical_json(model) + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except FileExistsError:
        try:
            return path.read_bytes() == payload
        except OSError:
            return False
    except OSError:
        return False


def _require_safe_stage(stage: str) -> None:
    if not _SAFE_STAGE.fullmatch(stage):
        raise ValueError("memory stage must be one safe path segment")


def _source_kind(path: Path) -> RawMemorySourceKind:
    labels = {item.casefold() for item in path.parts}
    name = path.name.casefold()
    if labels.intersection({"interactions", "responses"}) or any(
        marker in name for marker in ("interaction", "response", "authorship")
    ):
        return RawMemorySourceKind.MODEL_TRANSCRIPT
    return RawMemorySourceKind.TOOL_OUTPUT


def _media_type(path: Path) -> str:
    return {
        ".csv": "text/csv",
        ".json": "application/json",
        ".log": "text/plain",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".tex": "application/x-tex",
        ".txt": "text/plain",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
    }.get(path.suffix.casefold(), "application/octet-stream")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_error(label: str, exc: BaseException) -> str:
    # Do not persist absolute paths or arbitrary provider text in a sidecar error.
    return f"{label} failed ({type(exc).__name__})"
