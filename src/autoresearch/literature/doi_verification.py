"""Crossref-backed DOI resolution and title-consistency verification.

A verified DOI proves the identifier exists in the Crossref registry, but not
that the local record's title/authors belong to it.  ``verify_doi`` therefore
resolves the DOI and, when an expected title is supplied, compares it against
the registry title so a hallucinated or mis-attributed citation fails before it
reaches a human-facing bibliography.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, cast

import certifi

from .models import normalize_doi, normalize_title

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
_CROSSREF_MAILTO_ENV = "CROSSREF_MAILTO"
_TITLE_MATCH_THRESHOLD = 0.9
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")

DoiVerificationStatus = Literal["resolved", "unresolved", "error"]
TitleMatch = Literal["match", "mismatch", "unknown"]

HttpGet = Callable[[str, int], str]


@dataclass(frozen=True)
class DoiVerification:
    """Result of resolving one DOI against the Crossref registry."""

    doi: str
    status: DoiVerificationStatus
    resolved_title: str | None
    title_match: TitleMatch
    resolved_authors: tuple[str, ...]
    container_title: str | None
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    @property
    def title_consistent(self) -> bool:
        """True when the DOI resolves and no title mismatch was detected."""

        return self.status == "resolved" and self.title_match != "mismatch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "status": self.status,
            "resolved_title": self.resolved_title,
            "title_match": self.title_match,
            "resolved_authors": list(self.resolved_authors),
            "container_title": self.container_title,
            "reason": self.reason,
        }


def verify_doi(
    doi: str,
    *,
    expected_title: str | None = None,
    mailto: str | None = None,
    timeout_seconds: int = 30,
    http_get: HttpGet | None = None,
) -> DoiVerification:
    """Resolve one DOI through Crossref and optionally check its title.

    ``mailto`` participates in Crossref's polite pool and is recommended for
    unattended deployments.  The value is never stored by this module beyond the
    single request.
    """

    normalized = normalize_doi(doi)
    if normalized is None or not _DOI_PATTERN.match(normalized):
        return DoiVerification(
            doi=str(doi),
            status="error",
            resolved_title=None,
            title_match="unknown",
            resolved_authors=(),
            container_title=None,
            reason="DOI could not be normalized or has an invalid format",
        )

    resolver = http_get or _http_get
    endpoint = f"{CROSSREF_WORKS_URL}/{urllib.parse.quote(normalized, safe='')}"
    effective_mailto = mailto if mailto is not None else os.getenv(_CROSSREF_MAILTO_ENV)
    if effective_mailto:
        endpoint += "?" + urllib.parse.urlencode({"mailto": effective_mailto})
    try:
        text = resolver(endpoint, timeout_seconds)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return DoiVerification(
                doi=normalized,
                status="unresolved",
                resolved_title=None,
                title_match="unknown",
                resolved_authors=(),
                container_title=None,
                reason=f"Crossref returned HTTP 404 for {normalized}",
            )
        return DoiVerification(
            doi=normalized,
            status="error",
            resolved_title=None,
            title_match="unknown",
            resolved_authors=(),
            container_title=None,
            reason=f"Crossref request failed with HTTP {exc.code}",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return DoiVerification(
            doi=normalized,
            status="error",
            resolved_title=None,
            title_match="unknown",
            resolved_authors=(),
            container_title=None,
            reason=f"Crossref request transport error: {type(exc).__name__}",
        )

    payload = _parse_crossref_payload(text)
    if payload is None:
        return DoiVerification(
            doi=normalized,
            status="unresolved",
            resolved_title=None,
            title_match="unknown",
            resolved_authors=(),
            container_title=None,
            reason=f"Crossref response for {normalized} had no work record",
        )

    resolved_title = _first_string(payload.get("title"))
    resolved_authors = tuple(_author_names(payload.get("author")))
    container = _first_string(payload.get("container-title"))
    title_match = _title_match(resolved_title, expected_title)
    return DoiVerification(
        doi=normalized,
        status="resolved",
        resolved_title=resolved_title,
        title_match=title_match,
        resolved_authors=resolved_authors,
        container_title=container,
        reason=(
            "registry title differs from the local record title"
            if title_match == "mismatch"
            else None
        ),
    )


def _http_get(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ai-researcher/0.1 (mailto: none; doi verification)"},
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
        return cast(bytes, response.read()).decode("utf-8")


def _parse_crossref_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    return message


def _first_string(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, list | tuple) and value:
        return _first_string(value[0])
    return None


def _author_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for author in value:
        if not isinstance(author, dict):
            continue
        family = author.get("family")
        given = author.get("given")
        if isinstance(family, str) and family.strip():
            names.append(f"{given} {family}".strip() if isinstance(given, str) else family.strip())
        elif isinstance(given, str) and given.strip():
            names.append(given.strip())
    return names


def _title_match(resolved_title: str | None, expected_title: str | None) -> TitleMatch:
    if resolved_title is None:
        return "unknown"
    if expected_title is None or not expected_title.strip():
        return "unknown"
    ratio = SequenceMatcher(None, normalize_title(resolved_title), normalize_title(expected_title)).ratio()
    return "match" if ratio >= _TITLE_MATCH_THRESHOLD else "mismatch"


@dataclass(frozen=True)
class ReferenceVerificationReceipt:
    """Batch DOI-verification result for a bounded reference catalog."""

    schema_version: str = "contest-reference-doi-verification-v1"
    verified: tuple[DoiVerification, ...] = ()
    skipped_count: int = 0

    @property
    def resolved_count(self) -> int:
        return sum(1 for item in self.verified if item.resolved)

    @property
    def mismatch_count(self) -> int:
        return sum(1 for item in self.verified if item.title_match == "mismatch")

    @property
    def title_consistent(self) -> bool:
        return self.mismatch_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "verified": [item.to_dict() for item in self.verified],
            "skipped_count": self.skipped_count,
            "resolved_count": self.resolved_count,
            "mismatch_count": self.mismatch_count,
        }


def verify_reference_records(
    records: Any,
    *,
    mailto: str | None = None,
    timeout_seconds: int = 30,
    http_get: HttpGet | None = None,
) -> ReferenceVerificationReceipt:
    """Verify the formal DOIs of a reference catalog against Crossref.

    Records that carry only a repository DOI (``10.48550/arXiv.…``) or no DOI at
    all are skipped: their arXiv/OpenAlex URL is the verifiable locator and is
    checked by the retrieval lineage instead.  This function is a deterministic
    projection over ``verify_doi``; it never mutates the input records.
    """

    verified: list[DoiVerification] = []
    skipped = 0
    for record in records if isinstance(records, Sequence) else ():
        if not isinstance(record, Mapping):
            skipped += 1
            continue
        doi = _formal_doi(record)
        if doi is None:
            skipped += 1
            continue
        title = record.get("title")
        expected_title = str(title) if isinstance(title, str) and title.strip() else None
        verified.append(
            verify_doi(
                doi,
                expected_title=expected_title,
                mailto=mailto,
                timeout_seconds=timeout_seconds,
                http_get=http_get,
            )
        )
    return ReferenceVerificationReceipt(verified=tuple(verified), skipped_count=skipped)


def _formal_doi(record: Mapping[str, Any]) -> str | None:
    for key in ("doi", "publication_doi"):
        value = record.get(key)
        if isinstance(value, str):
            normalized = normalize_doi(value)
            if normalized is not None and _DOI_PATTERN.match(normalized):
                return normalized
    return None


__all__ = [
    "DoiVerification",
    "ReferenceVerificationReceipt",
    "verify_doi",
    "verify_reference_records",
]
