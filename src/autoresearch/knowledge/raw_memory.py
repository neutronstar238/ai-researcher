"""Model-independent raw memory and rebuildable Obsidian projections.

The raw layer is deliberately boring: authorized source bytes are retained once,
addressed by SHA-256, and never rewritten.  Any summary, index, embedding, or
"Dreaming" output is a separate derived projection that can be regenerated from
verified raw bindings.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel import SensitiveContentError, validate_persistable_content
from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)

from .entries import KnowledgeEntry, KnowledgeEntryType, KnowledgeZone

_SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MEDIA_TYPE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
_SENSITIVE_FILE_MARKERS = frozenset(
    {
        ".env",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "private-key",
        "private_key",
        "secret",
        "secrets",
    }
)
_CANONICAL_SUFFIXES = {
    "application/json": ".json",
    "application/pdf": ".pdf",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


class RawMemoryError(RuntimeError):
    """Base error for sovereign raw-memory operations."""


class RawMemoryPolicyError(RawMemoryError):
    """Raised when a capture violates privacy or authorization policy."""


class RawMemoryIntegrityError(RawMemoryError):
    """Raised when persisted raw or derived memory no longer verifies."""


class RawMemorySourceKind(str, Enum):
    """Source classes accepted by the local raw-memory boundary."""

    USER_ATTACHMENT = "user_attachment"
    USER_TEXT = "user_text"
    WEB_SNAPSHOT = "web_snapshot"
    LOCAL_FILE = "local_file"
    MODEL_TRANSCRIPT = "model_transcript"
    TOOL_OUTPUT = "tool_output"


class MemoryClaimVerdict(str, Enum):
    """Epistemic status of one claim in a Dreaming projection."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    EXTRAPOLATION = "extrapolation"
    UNVERIFIED = "unverified"


class RawMemoryEnvelope(KernelContract):
    """Immutable metadata bound to exactly one captured source payload."""

    schema_version: Literal[1, 2] = 2
    project_id: StableId
    captured_at: datetime
    source_kind: RawMemorySourceKind
    source_label: str = Field(min_length=1, max_length=512)
    source_ref: str = Field(min_length=1, max_length=2048)
    original_name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=3, max_length=255)
    payload_sha256: Sha256
    payload_size: int = Field(ge=1)
    visibility: Literal["private-local"] = "private-local"
    write_policy: Literal["append-only"] = "append-only"
    raw_payload_retained: Literal[True] = True
    capture_authorized: Literal[True] = True
    sensitive_content_reviewed: Literal[True] = True
    supersedes_record_id: StableId | None = None

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        _require_safe_segment(value, label="project_id")
        return value

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("captured_at must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @field_validator("original_name")
    @classmethod
    def _validate_original_name(cls, value: str) -> str:
        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("original_name must be a basename without path components")
        _reject_sensitive_filename(value)
        return value

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _MEDIA_TYPE_PATTERN.fullmatch(normalized):
            raise ValueError("media_type must be a canonical MIME type")
        return normalized

    @model_validator(mode="after")
    def _reject_private_source_paths(self) -> RawMemoryEnvelope:
        if self.source_kind in {
            RawMemorySourceKind.LOCAL_FILE,
            RawMemorySourceKind.USER_ATTACHMENT,
        } and _looks_absolute_path(self.source_ref):
            raise ValueError("source_ref must not persist an absolute local path")
        if self.source_kind is RawMemorySourceKind.WEB_SNAPSHOT and not self.source_ref.startswith(
            ("https://", "http://")
        ):
            raise ValueError("web_snapshot source_ref must be an HTTP(S) URL")
        return self


class RawMemoryRecord(KernelContract):
    """Content-addressed record for one immutable raw-memory capture."""

    envelope: RawMemoryEnvelope
    record_id: StableId
    record_hash: Sha256
    blob_relative_path: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _verify_integrity_fields(self) -> RawMemoryRecord:
        expected_hash = canonical_sha256(self.envelope)
        expected_id = f"rawmem_{expected_hash}"
        expected_blob_path = _blob_relative_path(
            self.envelope.payload_sha256,
            self.envelope.media_type,
            schema_version=self.envelope.schema_version,
        ).as_posix()
        if self.record_hash != expected_hash:
            raise ValueError("record_hash does not match the immutable envelope")
        if self.record_id != expected_id:
            raise ValueError("record_id does not match record_hash")
        if self.blob_relative_path != expected_blob_path:
            raise ValueError("blob_relative_path is not canonical for the payload")
        return self


class RawMemoryBinding(KernelContract):
    """Minimal exact binding from a derived view back to raw memory."""

    record_id: StableId
    record_hash: Sha256
    payload_sha256: Sha256
    record_relative_path: str = Field(min_length=1, max_length=1024)

    @field_validator("record_relative_path")
    @classmethod
    def _validate_record_relative_path(cls, value: str) -> str:
        path = _safe_relative_path(value)
        if path.suffix != ".json" or "records" not in path.parts:
            raise ValueError("record_relative_path must identify a raw-memory JSON record")
        return path.as_posix()


class MemoryClaimAssessment(KernelContract):
    """Source-aware assessment stored in a rebuildable Dreaming view."""

    claim: str = Field(min_length=1, max_length=4096)
    verdict: MemoryClaimVerdict
    rationale: str = Field(min_length=1, max_length=8192)
    evidence_refs: list[str] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def _deduplicate_evidence_refs(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("evidence_refs must not contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence_refs must be unique")
        return normalized


class DreamingMemoryContent(KernelContract):
    """Derived knowledge content that never substitutes for its raw sources."""

    schema_version: Literal[1, 2] = 2
    project_id: StableId
    title: str = Field(min_length=1, max_length=512)
    generated_at: datetime
    generator_identity: StableId
    source_bindings: list[RawMemoryBinding] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=32768)
    claim_assessments: list[MemoryClaimAssessment] = Field(min_length=1)
    design_decisions: list[str] = Field(min_length=1)
    raw_records_mutated: Literal[False] = False
    derived_and_rebuildable: Literal[True] = True
    supersedes_projection_id: StableId | None = None

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        _require_safe_segment(value, label="project_id")
        return value

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("generated_at must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @field_validator("source_bindings")
    @classmethod
    def _require_unique_sources(cls, value: list[RawMemoryBinding]) -> list[RawMemoryBinding]:
        ids = [item.record_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("source_bindings must reference distinct raw records")
        return sorted(value, key=lambda item: item.record_id)

    @field_validator("design_decisions")
    @classmethod
    def _normalize_design_decisions(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("design_decisions must not contain empty values")
        return normalized

    @model_validator(mode="after")
    def _require_exact_raw_claim_bindings(self) -> DreamingMemoryContent:
        if self.schema_version == 1:
            return self
        allowed_refs = {
            f"raw:{binding.record_id}#sha256:{binding.payload_sha256}"
            for binding in self.source_bindings
        }
        for assessment in self.claim_assessments:
            if assessment.verdict not in {
                MemoryClaimVerdict.SUPPORTED,
                MemoryClaimVerdict.CONTRADICTED,
            }:
                continue
            if not allowed_refs.intersection(assessment.evidence_refs):
                raise ValueError(
                    "supported or contradicted Dreaming claims require an exact "
                    "bound raw-record and payload-hash reference"
                )
        return self


class DreamingMemoryProjection(KernelContract):
    """Content-addressed JSON/Markdown projection of derived memory."""

    content: DreamingMemoryContent
    projection_id: StableId
    projection_hash: Sha256

    @model_validator(mode="after")
    def _verify_projection_hash(self) -> DreamingMemoryProjection:
        expected_hash = canonical_sha256(self.content)
        if self.projection_hash != expected_hash:
            raise ValueError("projection_hash does not match Dreaming content")
        if self.projection_id != f"dream_{expected_hash}":
            raise ValueError("projection_id does not match projection_hash")
        return self


@dataclass(frozen=True)
class RawMemoryCapture:
    """Filesystem locations returned after a verified raw capture."""

    record: RawMemoryRecord
    record_path: Path
    blob_path: Path

    def binding(self, vault_root: Path | str) -> RawMemoryBinding:
        root = Path(vault_root).resolve()
        return RawMemoryBinding(
            record_id=self.record.record_id,
            record_hash=self.record.record_hash,
            payload_sha256=self.record.envelope.payload_sha256,
            record_relative_path=self.record_path.resolve().relative_to(root).as_posix(),
        )


@dataclass(frozen=True)
class DreamingMemoryWrite:
    """Verified JSON and Obsidian Markdown paths for one derived projection."""

    projection: DreamingMemoryProjection
    json_path: Path
    markdown_path: Path
    commit_path: Path | None = None


class RawMemoryStore:
    """Append-only, private-local source memory under an Obsidian vault."""

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.private_root = self.vault_root / "_private" / "raw-memory"
        _secure_private_directory(self.private_root)

    def capture_file(
        self,
        path: Path | str,
        *,
        project_id: str,
        source_kind: RawMemorySourceKind,
        source_label: str,
        source_ref: str,
        media_type: str,
        source_authorized: bool,
        sensitive_content_reviewed: bool,
        captured_at: datetime | None = None,
        supersedes_record_id: str | None = None,
    ) -> RawMemoryCapture:
        """Capture exact file bytes without persisting the absolute source path."""

        source_path = Path(path)
        _reject_sensitive_filename(source_path.name)
        return self.capture_bytes(
            source_path.read_bytes(),
            project_id=project_id,
            source_kind=source_kind,
            source_label=source_label,
            source_ref=source_ref,
            original_name=source_path.name,
            media_type=media_type,
            source_authorized=source_authorized,
            sensitive_content_reviewed=sensitive_content_reviewed,
            captured_at=captured_at,
            supersedes_record_id=supersedes_record_id,
        )

    def capture_text(
        self,
        text: str,
        *,
        project_id: str,
        source_kind: RawMemorySourceKind,
        source_label: str,
        source_ref: str,
        original_name: str,
        source_authorized: bool,
        sensitive_content_reviewed: bool,
        captured_at: datetime | None = None,
        supersedes_record_id: str | None = None,
    ) -> RawMemoryCapture:
        """Capture exact UTF-8 text as raw memory."""

        return self.capture_bytes(
            text.encode("utf-8"),
            project_id=project_id,
            source_kind=source_kind,
            source_label=source_label,
            source_ref=source_ref,
            original_name=original_name,
            media_type="text/plain",
            source_authorized=source_authorized,
            sensitive_content_reviewed=sensitive_content_reviewed,
            captured_at=captured_at,
            supersedes_record_id=supersedes_record_id,
        )

    def capture_bytes(
        self,
        payload: bytes,
        *,
        project_id: str,
        source_kind: RawMemorySourceKind,
        source_label: str,
        source_ref: str,
        original_name: str,
        media_type: str,
        source_authorized: bool,
        sensitive_content_reviewed: bool,
        captured_at: datetime | None = None,
        supersedes_record_id: str | None = None,
    ) -> RawMemoryCapture:
        """Persist one authorized payload once, then verify it from disk."""

        if not source_authorized:
            raise RawMemoryPolicyError("raw capture requires explicit source authorization")
        if not sensitive_content_reviewed:
            raise RawMemoryPolicyError("raw capture requires a completed sensitive-content review")
        if not payload:
            raise RawMemoryPolicyError("raw capture refuses an empty payload")

        _require_safe_segment(project_id, label="project_id")
        _reject_sensitive_filename(original_name)
        _scan_capture_content(
            payload,
            source_label=source_label,
            source_ref=source_ref,
            original_name=original_name,
        )

        captured = captured_at or datetime.now(timezone.utc)
        payload_hash = hashlib.sha256(payload).hexdigest()
        envelope = RawMemoryEnvelope(
            project_id=project_id,
            captured_at=captured,
            source_kind=source_kind,
            source_label=source_label,
            source_ref=source_ref,
            original_name=original_name,
            media_type=media_type,
            payload_sha256=payload_hash,
            payload_size=len(payload),
            capture_authorized=True,
            sensitive_content_reviewed=True,
            supersedes_record_id=supersedes_record_id,
        )
        if supersedes_record_id is not None:
            self.find_record(supersedes_record_id, project_id=project_id)

        record_hash = canonical_sha256(envelope)
        record = RawMemoryRecord(
            envelope=envelope,
            record_id=f"rawmem_{record_hash}",
            record_hash=record_hash,
            blob_relative_path=_blob_relative_path(
                payload_hash,
                envelope.media_type,
                schema_version=envelope.schema_version,
            ).as_posix(),
        )
        blob_path = self._inside_vault(record.blob_relative_path)
        record_relative_path = _record_relative_path(record)
        record_path = self._inside_vault(record_relative_path)

        _write_once(blob_path, payload)
        _write_once(record_path, (canonical_json(record) + "\n").encode("utf-8"))
        capture = RawMemoryCapture(record=record, record_path=record_path, blob_path=blob_path)
        self.verify_capture(capture)
        return capture

    def find_record(self, record_id: str, *, project_id: str) -> RawMemoryCapture:
        """Find and verify one record by its full content-addressed ID."""

        _require_safe_segment(project_id, label="project_id")
        if not re.fullmatch(r"rawmem_[0-9a-f]{64}", record_id):
            raise RawMemoryPolicyError("record_id is not a canonical raw-memory ID")
        matches = list(
            self.private_root.glob(
                f"projects/{project_id}/records/*/*/{record_id}.json"
            )
        )
        if len(matches) != 1:
            raise RawMemoryIntegrityError(
                f"expected exactly one raw-memory record for {record_id}, found {len(matches)}"
            )
        return self.load_record(
            matches[0].relative_to(self.vault_root),
            project_id=project_id,
        )

    def load_record(
        self,
        relative_path: Path | str,
        *,
        project_id: str,
    ) -> RawMemoryCapture:
        """Load a canonical record and verify its exact payload."""

        _require_safe_segment(project_id, label="project_id")
        record_path = self._inside_vault(_safe_relative_path(relative_path))
        try:
            raw = record_path.read_bytes()
            record = RawMemoryRecord.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise RawMemoryIntegrityError(f"cannot load raw-memory record: {exc}") from exc
        if raw != (canonical_json(record) + "\n").encode("utf-8"):
            raise RawMemoryIntegrityError("raw-memory record JSON is not canonical")
        if record.envelope.project_id != project_id:
            raise RawMemoryPolicyError("raw-memory record belongs to another project")
        expected_record_path = self._inside_vault(_record_relative_path(record))
        if record_path != expected_record_path:
            raise RawMemoryIntegrityError("raw-memory record is stored at a non-canonical path")
        capture = RawMemoryCapture(
            record=record,
            record_path=record_path,
            blob_path=self._inside_vault(record.blob_relative_path),
        )
        self.verify_capture(capture)
        return capture

    def verify_capture(self, capture: RawMemoryCapture) -> None:
        """Verify canonical record bytes, location, size, and source-payload hash."""

        record = capture.record
        try:
            persisted_record = capture.record_path.read_bytes()
            payload = capture.blob_path.read_bytes()
        except OSError as exc:
            raise RawMemoryIntegrityError(f"raw-memory artifact is unreadable: {exc}") from exc
        if persisted_record != (canonical_json(record) + "\n").encode("utf-8"):
            raise RawMemoryIntegrityError("persisted raw-memory record does not match its contract")
        if capture.record_path.resolve() != self._inside_vault(_record_relative_path(record)):
            raise RawMemoryIntegrityError("raw-memory record path does not match its contract")
        if capture.blob_path.resolve() != self._inside_vault(record.blob_relative_path):
            raise RawMemoryIntegrityError("raw-memory blob path does not match its contract")
        if len(payload) != record.envelope.payload_size:
            raise RawMemoryIntegrityError("raw-memory payload size changed")
        if hashlib.sha256(payload).hexdigest() != record.envelope.payload_sha256:
            raise RawMemoryIntegrityError("raw-memory payload hash changed")

    def write_dreaming_projection(
        self,
        content: DreamingMemoryContent,
    ) -> DreamingMemoryWrite:
        """Write a rebuildable JSON/Markdown view after rechecking every raw source."""

        if content.supersedes_projection_id is not None:
            self._verify_superseded_projection_chain(
                content.supersedes_projection_id,
                project_id=content.project_id,
            )
        verified_before = [
            self._verify_binding(binding, project_id=content.project_id)
            for binding in content.source_bindings
        ]
        projection_hash = canonical_sha256(content)
        projection = DreamingMemoryProjection(
            content=content,
            projection_id=f"dream_{projection_hash}",
            projection_hash=projection_hash,
        )
        output_directory = self._inside_vault(
            Path("projects")
            / content.project_id
            / "knowledge"
            / "dreaming"
        )
        json_path = output_directory / f"{projection.projection_id}.json"
        markdown_path = output_directory / f"{projection.projection_id}.md"
        commit_path = output_directory / f"{projection.projection_id}.commit"
        json_bytes = (canonical_json(projection) + "\n").encode("utf-8")
        markdown_bytes = _dreaming_markdown(projection).encode("utf-8")
        _write_once(json_path, json_bytes)
        _write_once(markdown_path, markdown_bytes)

        verified_after = [
            self._verify_binding(binding, project_id=content.project_id)
            for binding in content.source_bindings
        ]
        if verified_before != verified_after:
            raise RawMemoryIntegrityError("raw-memory sources changed during Dreaming projection")
        if content.schema_version == 2:
            _write_once(
                commit_path,
                (projection.projection_hash + "\n").encode("ascii"),
            )
        result = DreamingMemoryWrite(
            projection=projection,
            json_path=json_path,
            markdown_path=markdown_path,
            commit_path=commit_path if content.schema_version == 2 else None,
        )
        self.verify_dreaming_projection(result)
        return result

    def load_dreaming_projection(
        self,
        projection_id: str,
        *,
        project_id: str,
    ) -> DreamingMemoryWrite:
        """Load and fully verify one existing Dreaming projection."""

        _require_safe_segment(project_id, label="project_id")
        if not re.fullmatch(r"dream_[0-9a-f]{64}", projection_id):
            raise RawMemoryPolicyError("projection_id is not a canonical Dreaming ID")
        directory = self._inside_vault(
            Path("projects") / project_id / "knowledge" / "dreaming"
        )
        json_path = self._inside_vault(
            directory.relative_to(self.vault_root) / f"{projection_id}.json"
        )
        markdown_path = self._inside_vault(
            directory.relative_to(self.vault_root) / f"{projection_id}.md"
        )
        try:
            persisted_json = json_path.read_bytes()
            projection = DreamingMemoryProjection.model_validate_json(persisted_json)
        except (OSError, ValueError) as exc:
            raise RawMemoryIntegrityError(
                f"cannot load superseded Dreaming projection: {exc}"
            ) from exc
        if persisted_json != (canonical_json(projection) + "\n").encode("utf-8"):
            raise RawMemoryIntegrityError("superseded Dreaming JSON is not canonical")
        if projection.projection_id != projection_id:
            raise RawMemoryIntegrityError("superseded Dreaming projection ID mismatch")
        if projection.content.project_id != project_id:
            raise RawMemoryPolicyError(
                "superseded Dreaming projection belongs to another project"
            )
        commit_path = (
            self._inside_vault(
                directory.relative_to(self.vault_root) / f"{projection_id}.commit"
            )
            if projection.content.schema_version == 2
            else None
        )
        written = DreamingMemoryWrite(
            projection=projection,
            json_path=json_path,
            markdown_path=markdown_path,
            commit_path=commit_path,
        )
        self.verify_dreaming_projection(written)
        return written

    def verify_dreaming_projection(self, written: DreamingMemoryWrite) -> None:
        """Verify a Dreaming JSON/Markdown pair and every bound raw record."""

        try:
            persisted_json = written.json_path.read_bytes()
            persisted_markdown = written.markdown_path.read_bytes()
        except OSError as exc:
            raise RawMemoryIntegrityError(f"Dreaming projection is unreadable: {exc}") from exc
        expected_json = (canonical_json(written.projection) + "\n").encode("utf-8")
        expected_markdown = _dreaming_markdown(written.projection).encode("utf-8")
        if persisted_json != expected_json:
            raise RawMemoryIntegrityError("Dreaming JSON no longer matches its contract")
        if persisted_markdown != expected_markdown:
            raise RawMemoryIntegrityError("Dreaming Markdown no longer matches its contract")
        if written.projection.content.schema_version == 2:
            if written.commit_path is None:
                raise RawMemoryIntegrityError("Dreaming v2 projection lacks a commit marker")
            expected_commit = (written.projection.projection_hash + "\n").encode(
                "ascii"
            )
            try:
                actual_commit = written.commit_path.read_bytes()
            except OSError as exc:
                raise RawMemoryIntegrityError(
                    f"Dreaming commit marker is unreadable: {exc}"
                ) from exc
            if actual_commit != expected_commit:
                raise RawMemoryIntegrityError(
                    "Dreaming commit marker does not match its projection"
                )
        for binding in written.projection.content.source_bindings:
            self._verify_binding(
                binding,
                project_id=written.projection.content.project_id,
            )

    def _verify_binding(
        self,
        binding: RawMemoryBinding,
        *,
        project_id: str,
    ) -> tuple[str, str, str]:
        capture = self.load_record(
            binding.record_relative_path,
            project_id=project_id,
        )
        record = capture.record
        actual = (
            record.record_id,
            record.record_hash,
            record.envelope.payload_sha256,
        )
        expected = (binding.record_id, binding.record_hash, binding.payload_sha256)
        if actual != expected:
            raise RawMemoryIntegrityError("Dreaming source binding does not match raw memory")
        return actual

    def _verify_superseded_projection_chain(
        self,
        projection_id: str,
        *,
        project_id: str,
    ) -> None:
        """Require every predecessor to exist, verify, and form an acyclic chain."""

        seen: set[str] = set()
        current: str | None = projection_id
        while current is not None:
            if current in seen:
                raise RawMemoryIntegrityError("Dreaming supersession chain contains a cycle")
            seen.add(current)
            predecessor = self.load_dreaming_projection(
                current,
                project_id=project_id,
            )
            current = predecessor.projection.content.supersedes_projection_id

    def _inside_vault(self, relative_path: Path | str) -> Path:
        target = (self.vault_root / relative_path).resolve()
        if not target.is_relative_to(self.vault_root):
            raise RawMemoryPolicyError("memory path escapes the vault root")
        return target


def _blob_relative_path(
    payload_hash: str,
    media_type: str,
    *,
    schema_version: int,
) -> Path:
    # v1 retained human-readable suffixes. v2 deliberately uses an opaque suffix so
    # Obsidian and generic Markdown/media indexers never parse raw payload bytes.
    suffix = (
        _CANONICAL_SUFFIXES.get(media_type.lower(), ".bin")
        if schema_version == 1
        else ".blob"
    )
    return (
        Path("_private")
        / "raw-memory"
        / "blobs"
        / "sha256"
        / payload_hash[:2]
        / f"{payload_hash}{suffix}"
    )


def _record_relative_path(record: RawMemoryRecord) -> Path:
    captured = record.envelope.captured_at
    return (
        Path("_private")
        / "raw-memory"
        / "projects"
        / record.envelope.project_id
        / "records"
        / f"{captured.year:04d}"
        / f"{captured.month:02d}"
        / f"{record.record_id}.json"
    )


def _dreaming_markdown(projection: DreamingMemoryProjection) -> str:
    content = projection.content
    source_refs = [binding.record_id for binding in content.source_bindings]
    source_refs.extend(
        evidence_ref
        for assessment in content.claim_assessments
        for evidence_ref in assessment.evidence_refs
    )
    source_refs = list(dict.fromkeys(source_refs))
    links = [
        binding.record_relative_path.removesuffix(".json")
        for binding in content.source_bindings
    ]
    body_lines = [
        f"# {content.title}",
        "",
        "> [!evidence] 这是可重建的 Dreaming 派生视图，不是原始记忆。",
        "> 原始字节保存在本地私有只追加层；本笔记不得替代、压缩或删除原始记录。",
        "",
        "## 记忆边界",
        "",
        "- 派生状态：`derived`",
        "- 可重建：`true`",
        "- 原始记录被改写：`false`",
        f"- 投影哈希：`{projection.projection_hash}`",
        f"- 生成者：`{content.generator_identity}`",
        "",
        "## 原始记忆绑定",
        "",
    ]
    for binding in content.source_bindings:
        body_lines.extend(
            [
                f"- `{binding.record_id}`",
                f"  - 记录哈希：`{binding.record_hash}`",
                f"  - 原始载荷哈希：`{binding.payload_sha256}`",
                f"  - 本地记录：`{binding.record_relative_path}`",
            ]
        )
    body_lines.extend(["", "## 整理摘要", "", content.summary, "", "## 论断核验", ""])
    for assessment in content.claim_assessments:
        body_lines.extend(
            [
                f"### {_verdict_label(assessment.verdict)}：{assessment.claim}",
                "",
                assessment.rationale,
                "",
                "证据：",
                *[f"- {reference}" for reference in assessment.evidence_refs],
                "",
            ]
        )
    decision_heading = (
        "## 对系统的设计决策"
        if content.schema_version == 1
        else "## 候选设计建议（未授权）"
    )
    body_lines.extend([decision_heading, ""])
    body_lines.extend(
        f"{index}. {decision}" for index, decision in enumerate(content.design_decisions, start=1)
    )
    if content.supersedes_projection_id is not None:
        body_lines.extend(
            [
                "",
                "## 版本关系",
                "",
                f"- 本投影取代：`{content.supersedes_projection_id}`",
                "- 被取代投影仍保留；纠错不回写历史记录。",
            ]
        )
    entry = KnowledgeEntry(
        entry_id=projection.projection_id,
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title=content.title,
        project_id=content.project_id,
        tags=["raw-memory-sovereignty", "dreaming", "derived", "rebuildable"],
        keywords=["agent memory", "model memory", "obsidian", "raw memory"],
        source_refs=source_refs,
        links=links,
        created_at=content.generated_at,
        updated_at=content.generated_at,
        body="\n".join(body_lines).rstrip(),
    )
    return entry.to_markdown()


def _verdict_label(verdict: MemoryClaimVerdict) -> str:
    return {
        MemoryClaimVerdict.SUPPORTED: "原文支持",
        MemoryClaimVerdict.CONTRADICTED: "原文相反",
        MemoryClaimVerdict.EXTRAPOLATION: "外推观点",
        MemoryClaimVerdict.UNVERIFIED: "尚未核实",
    }[verdict]


def _scan_capture_content(
    payload: bytes,
    *,
    source_label: str,
    source_ref: str,
    original_name: str,
) -> None:
    try:
        validate_persistable_content(
            {
                "source_label": source_label,
                "source_ref": source_ref,
                "original_name": original_name,
            }
        )
    except SensitiveContentError as exc:
        raise RawMemoryPolicyError(
            "raw memory cannot persist credentials or direct identifiers; "
            "use an approved encrypted private-data connector"
        ) from exc
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        decoded = payload.decode("latin-1", errors="ignore")
    try:
        validate_persistable_content(decoded)
    except SensitiveContentError as exc:
        raise RawMemoryPolicyError(
            "raw memory cannot persist credentials or direct identifiers; "
            "use an approved encrypted private-data connector"
        ) from exc


def _reject_sensitive_filename(filename: str) -> None:
    normalized = filename.casefold()
    stem = Path(filename).stem.casefold()
    suffix = Path(filename).suffix.casefold()
    if (
        normalized.startswith(".env")
        or suffix in {".key", ".pem", ".p12", ".pfx"}
        or any(marker in normalized or marker == stem for marker in _SENSITIVE_FILE_MARKERS)
    ):
        raise RawMemoryPolicyError("secret-like files are forbidden in raw memory")


def _looks_absolute_path(value: str) -> bool:
    return value.startswith(("/", "\\")) or bool(
        _WINDOWS_ABSOLUTE_PATH_PATTERN.match(value)
    )


def _require_safe_segment(value: str, *, label: str) -> None:
    if not _SAFE_SEGMENT_PATTERN.fullmatch(value):
        raise RawMemoryPolicyError(f"{label} must be one path-safe segment")


def _safe_relative_path(value: Path | str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("memory artifact path must be safe and relative")
    return path


def _secure_private_directory(path: Path) -> None:
    """Create a local owner-only boundary, failing closed if it cannot be set."""

    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError as exc:
            raise RawMemoryPolicyError(
                f"cannot enforce owner-only raw-memory permissions: {exc}"
            ) from exc
        return

    escaped_path = str(path.resolve()).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop';"
        f"$p='{escaped_path}';"
        "$directory=[System.IO.DirectoryInfo]::new($p);"
        "$acl=$directory.GetAccessControl();"
        "$acl.SetAccessRuleProtection($true,$false);"
        "@($acl.Access)|ForEach-Object{[void]$acl.RemoveAccessRuleSpecific($_)};"
        "$user=[Security.Principal.WindowsIdentity]::GetCurrent().User;"
        "$system=New-Object Security.Principal.SecurityIdentifier('S-1-5-18');"
        "$inherit=[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor "
        "[Security.AccessControl.InheritanceFlags]::ObjectInherit;"
        "$prop=[Security.AccessControl.PropagationFlags]::None;"
        "$allow=[Security.AccessControl.AccessControlType]::Allow;"
        "foreach($sid in @($user,$system)){"
        "$rule=New-Object Security.AccessControl.FileSystemAccessRule("
        "$sid,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,$prop,$allow);"
        "[void]$acl.AddAccessRule($rule)};"
        "$directory.SetAccessControl($acl);"
        "$verify=$directory.GetAccessControl();"
        "if(-not $verify.AreAccessRulesProtected){exit 31};"
        "$allowed=@($user.Value,'S-1-5-18');"
        "foreach($rule in $verify.Access){"
        "$sid=$rule.IdentityReference.Translate("
        "[Security.Principal.SecurityIdentifier]).Value;"
        "if($allowed -notcontains $sid -or $rule.AccessControlType -ne $allow){exit 32}}"
    )
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RawMemoryPolicyError(
            f"cannot enforce owner-only Windows raw-memory ACL: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RawMemoryPolicyError(
            "cannot enforce owner-only Windows raw-memory ACL"
            + (f": {detail}" if detail else "")
        )


def _write_once(path: Path, payload: bytes) -> None:
    """Publish complete bytes once; a concurrent reader never sees a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.raw-memory-write"
    )
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RawMemoryIntegrityError(
            f"temporary append-only writer collision: {temporary}"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise RawMemoryIntegrityError(
                    f"cannot verify existing {path}: {exc}"
                ) from exc
            if existing != payload:
                raise RawMemoryIntegrityError(
                    f"append-only artifact changed: {path}"
                ) from None
    except BaseException as exc:
        if isinstance(exc, RawMemoryIntegrityError):
            raise
        raise RawMemoryIntegrityError(
            f"interrupted append-only write: {path}"
        ) from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()
