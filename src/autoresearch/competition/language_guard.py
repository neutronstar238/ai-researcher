"""Deterministic language checks for Chinese competition deliverables.

The checks deliberately count Latin *tokens*, not letters.  Scientific Chinese must
retain searchable identifiers such as ``term_support_f1``, ``LARS``, paths, and
commands; treating every character in those identifiers as English would reject good
technical Chinese.  Original bibliographic titles and DOI/URL values are provenance,
not authored prose, and callers therefore keep them outside this guard.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

MIN_CHINESE_PROSE_RATIO = 0.55


def chinese_prose_ratio(text: str) -> float:
    """Return Chinese characters / (Chinese characters + Latin tokens)."""

    chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_./:-]*", text)
    total = chinese + len(latin_tokens)
    if total == 0:
        return 1.0
    return chinese / total


def non_chinese_prose_fields(
    fields: Mapping[str, str | Sequence[str]],
    *,
    minimum_ratio: float = MIN_CHINESE_PROSE_RATIO,
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
            if text and chinese_prose_ratio(text) < minimum_ratio:
                failed.append(name if isinstance(value, str) else f"{name}[{index}]")
    return tuple(failed)
