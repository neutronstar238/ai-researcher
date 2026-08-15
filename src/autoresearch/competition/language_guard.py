"""Deterministic language checks for Chinese competition deliverables.

The ratio is deliberately character based: a long unbroken English token must not
count as one unit and thereby bypass the Chinese gate.  Searchable machine identifiers
such as ``term_support_f1``, ``LARS``, paths, flags, and token-list assignments are
excluded only when they have an unambiguous identifier shape (or the trusted caller
explicitly exempts them).  Original bibliographic titles and DOI/URL values are
provenance, not authored prose, and callers therefore keep them outside this guard.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence

MIN_CHINESE_PROSE_RATIO = 0.55

_AUTOMATIC_IDENTIFIER_PATTERN = re.compile(
    r"(?:"
    r"`[^`\s]{1,128}`"
    r"|(?<![A-Za-z0-9_])"
    r"(?=[^\]\r\n]{1,256}\])"
    r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*\[\s*"
    r"[A-Za-z][A-Za-z0-9_]*"
    r"(?:\s*,\s*[A-Za-z][A-Za-z0-9_]*)*\s*\]"
    r"(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])(?:[A-Za-z]:)?[\\/]"
    r"[A-Za-z0-9_.\\/:=-]{1,255}(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])"
    r"(?=[A-Za-z0-9_.:/\\]{2,128}(?![A-Za-z0-9_]))"
    r"[A-Za-z][A-Za-z0-9]*"
    r"(?:[_.:/\\][A-Za-z0-9]+)+(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])--?[A-Za-z][A-Za-z0-9_-]{0,63}"
    r"(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])task[0-9]+(?:-[a-z0-9]+)*"
    r"(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])[A-Z][A-Z0-9]{1,15}(?![A-Za-z0-9_])"
    r")"
)


def _is_cjk_ideograph(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2EBEF
        or 0x2F800 <= codepoint <= 0x2FA1F
        or 0x30000 <= codepoint <= 0x323AF
    )


def _is_latin_letter(char: str) -> bool:
    return unicodedata.category(char).startswith("L") and "LATIN" in unicodedata.name(
        char, ""
    )


def _without_exempt_identifiers(
    text: str,
    exempt_identifiers: Sequence[str],
) -> str:
    masked = _AUTOMATIC_IDENTIFIER_PATTERN.sub(" ", text)
    for identifier in sorted(
        {str(item).strip() for item in exempt_identifiers if str(item).strip()},
        key=len,
        reverse=True,
    ):
        boundary_pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(identifier)}(?![A-Za-z0-9_])"
        )
        masked = boundary_pattern.sub(" ", masked)
    return masked


def chinese_prose_ratio(
    text: str,
    *,
    exempt_identifiers: Sequence[str] = (),
) -> float:
    """Return CJK ideographs / (CJK ideographs + non-exempt Latin letters)."""

    prose = _without_exempt_identifiers(text, exempt_identifiers)
    chinese = sum(1 for char in prose if _is_cjk_ideograph(char))
    latin = sum(1 for char in prose if _is_latin_letter(char))
    total = chinese + latin
    if total == 0:
        return 1.0
    return chinese / total


def non_chinese_prose_fields(
    fields: Mapping[str, str | Sequence[str]],
    *,
    minimum_ratio: float = MIN_CHINESE_PROSE_RATIO,
    exempt_identifiers: Sequence[str] = (),
) -> tuple[str, ...]:
    """List authored prose fields that are not predominantly Chinese.

    Each list item is checked independently.  This prevents one long Chinese section
    from masking an English-only baseline, metric, limitation, or experiment item.
    """

    failed: list[str] = []
    for name, value in fields.items():
        items = (value,) if isinstance(value, str) else tuple(value)
        for index, item in enumerate(items):
            text = str(item).strip()
            if text and chinese_prose_ratio(
                text,
                exempt_identifiers=exempt_identifiers,
            ) < minimum_ratio:
                failed.append(name if isinstance(value, str) else f"{name}[{index}]")
    return tuple(failed)
