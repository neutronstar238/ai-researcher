"""Privacy normalization at the untrusted scholarly-metadata boundary.

Public paper metadata can legitimately contain author contact addresses.  It can
also carry copied credentials.  Those bytes are not scientific evidence, must
not reach a provider prompt, and are forbidden by the sovereign raw-memory
policy.  This module removes only literals already rejected by that policy,
records non-reversible field/category counts, and then invokes the unchanged
fail-closed validator.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.kernel import (
    SENSITIVE_TEXT_CATEGORIES,
    SensitiveContentError,
    SensitiveTextCategory,
    SensitiveTextRedactionError,
    redact_sensitive_text,
    validate_persistable_content,
)
from autoresearch.kernel.contracts import KernelContract, Sha256, canonical_sha256
from autoresearch.literature.models import AcademicPaper

SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION = "scholarly-metadata-privacy-v2"

PrivacyCategory = SensitiveTextCategory
_PRIVACY_CATEGORIES: tuple[PrivacyCategory, ...] = SENSITIVE_TEXT_CATEGORIES
_SAFE_FIELD_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?" r"(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?)*$"
)


class ScholarlyMetadataPrivacyReceipt(KernelContract):
    """Hash-bound counts only; no original literal or per-literal digest."""

    schema_version: Literal[
        "scholarly-metadata-privacy-receipt-v1",
        "scholarly-metadata-privacy-receipt-v2",
    ] = "scholarly-metadata-privacy-receipt-v2"
    policy_version: Literal[
        "scholarly-metadata-privacy-v1",
        "scholarly-metadata-privacy-v2",
    ] = "scholarly-metadata-privacy-v2"
    redaction_counts: dict[PrivacyCategory, int]
    field_redaction_counts: dict[str, dict[PrivacyCategory, int]]
    total_redactions: int = Field(ge=0)
    receipt_hash: Sha256

    @classmethod
    def create(
        cls,
        *,
        redaction_counts: Mapping[PrivacyCategory, int],
        field_redaction_counts: Mapping[str, Mapping[PrivacyCategory, int]],
    ) -> ScholarlyMetadataPrivacyReceipt:
        payload: dict[str, Any] = {
            "schema_version": "scholarly-metadata-privacy-receipt-v2",
            "policy_version": SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION,
            "redaction_counts": {
                category: int(redaction_counts.get(category, 0)) for category in _PRIVACY_CATEGORIES
            },
            "field_redaction_counts": {
                field: {category: int(count) for category, count in counts.items()}
                for field, counts in field_redaction_counts.items()
            },
            "total_redactions": sum(int(value) for value in redaction_counts.values()),
        }
        payload["receipt_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    @model_validator(mode="after")
    def _verify_receipt(self) -> ScholarlyMetadataPrivacyReceipt:
        if (self.schema_version, self.policy_version) not in {
            (
                "scholarly-metadata-privacy-receipt-v1",
                "scholarly-metadata-privacy-v1",
            ),
            (
                "scholarly-metadata-privacy-receipt-v2",
                "scholarly-metadata-privacy-v2",
            ),
        }:
            raise ValueError("privacy receipt schema/policy version mismatch")
        if set(self.redaction_counts) != set(_PRIVACY_CATEGORIES):
            raise ValueError("privacy receipt category set changed")
        if any(count < 0 for count in self.redaction_counts.values()):
            raise ValueError("privacy receipt counts must be nonnegative")
        aggregate = {category: 0 for category in _PRIVACY_CATEGORIES}
        for field, counts in self.field_redaction_counts.items():
            _validate_field_path(field)
            if not counts:
                raise ValueError("privacy receipt field entries must be nonempty")
            if any(category not in aggregate or count < 1 for category, count in counts.items()):
                raise ValueError("privacy receipt field counts are invalid")
            for category, count in counts.items():
                aggregate[category] += count
        if aggregate != self.redaction_counts:
            raise ValueError("privacy receipt field/category counts disagree")
        if self.total_redactions != sum(self.redaction_counts.values()):
            raise ValueError("privacy receipt total disagrees with category counts")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ValueError("privacy receipt hash mismatch")
        return self


class ScholarlyMetadataPrivacyError(ValueError):
    """Raised when safe redaction would require silently dropping trailing evidence."""

    def __init__(self, receipt: ScholarlyMetadataPrivacyReceipt) -> None:
        super().__init__("scholarly metadata privacy normalization failed")
        self.receipt = receipt


def normalize_untrusted_scholarly_papers(
    values: Sequence[AcademicPaper | Mapping[str, object]],
) -> tuple[tuple[AcademicPaper, ...], ScholarlyMetadataPrivacyReceipt]:
    """Normalize every free-text paper field before persistence or prompt use."""

    category_counts = _empty_category_counts()
    field_counts: dict[str, dict[PrivacyCategory, int]] = {}
    normalized: list[AcademicPaper] = []
    for index, value in enumerate(values):
        paper = value if isinstance(value, AcademicPaper) else AcademicPaper.model_validate(value)
        payload = _normalize_value(
            paper.model_dump(mode="python"),
            path=f"papers[{index}]",
            category_counts=category_counts,
            field_counts=field_counts,
        )
        normalized_paper = AcademicPaper.model_validate(payload)
        validate_persistable_content(normalized_paper.model_dump(mode="json"))
        normalized.append(normalized_paper)
    receipt = ScholarlyMetadataPrivacyReceipt.create(
        redaction_counts=category_counts,
        field_redaction_counts=field_counts,
    )
    return tuple(normalized), receipt


def normalize_untrusted_scholarly_text(
    value: str,
    *,
    field_path: str,
) -> tuple[str, ScholarlyMetadataPrivacyReceipt]:
    """Normalize one untrusted source string and return a count-only receipt."""

    _validate_field_path(field_path)
    category_counts = _empty_category_counts()
    field_counts: dict[str, dict[PrivacyCategory, int]] = {}
    normalized = _normalize_text(
        value,
        path=field_path,
        category_counts=category_counts,
        field_counts=field_counts,
    )
    validate_persistable_content(normalized)
    receipt = ScholarlyMetadataPrivacyReceipt.create(
        redaction_counts=category_counts,
        field_redaction_counts=field_counts,
    )
    return normalized, receipt


def _normalize_value(
    value: Any,
    *,
    path: str,
    category_counts: dict[PrivacyCategory, int],
    field_counts: dict[str, dict[PrivacyCategory, int]],
) -> Any:
    if isinstance(value, str):
        return _normalize_text(
            value,
            path=path,
            category_counts=category_counts,
            field_counts=field_counts,
        )
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                path=f"{path}[{index}]",
                category_counts=category_counts,
                field_counts=field_counts,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            _normalize_value(
                item,
                path=f"{path}[{index}]",
                category_counts=category_counts,
                field_counts=field_counts,
            )
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        return {
            key: _normalize_value(
                item,
                path=f"{path}.{key}",
                category_counts=category_counts,
                field_counts=field_counts,
            )
            for key, item in value.items()
        }
    return value


def _normalize_text(
    value: str,
    *,
    path: str,
    category_counts: dict[PrivacyCategory, int],
    field_counts: dict[str, dict[PrivacyCategory, int]],
) -> str:
    try:
        normalized, redaction_counts = redact_sensitive_text(value)
    except SensitiveTextRedactionError as exc:
        for category, count in exc.redaction_counts.items():
            if not count:
                continue
            category_counts[category] += count
            per_field = field_counts.setdefault(path, {})
            per_field[category] = per_field.get(category, 0) + count
        raise ScholarlyMetadataPrivacyError(
            ScholarlyMetadataPrivacyReceipt.create(
                redaction_counts=category_counts,
                field_redaction_counts=field_counts,
            )
        ) from exc
    for category, count in redaction_counts.items():
        if not count:
            continue
        category_counts[category] += count
        per_field = field_counts.setdefault(path, {})
        per_field[category] = per_field.get(category, 0) + count
    return normalized


def _validate_field_path(value: str) -> None:
    if not _SAFE_FIELD_PATH.fullmatch(value):
        raise ValueError("field_path must use a safe structural field path")
    try:
        validate_persistable_content(value)
    except SensitiveContentError as exc:
        raise ValueError("field_path must use a safe structural field path") from exc


def _empty_category_counts() -> dict[PrivacyCategory, int]:
    return {category: 0 for category in _PRIVACY_CATEGORIES}


__all__ = [
    "SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION",
    "ScholarlyMetadataPrivacyError",
    "ScholarlyMetadataPrivacyReceipt",
    "normalize_untrusted_scholarly_papers",
    "normalize_untrusted_scholarly_text",
]
