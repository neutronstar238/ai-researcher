"""PDF 分块纯函数单元测试（spec §13.x）。"""

from __future__ import annotations

from app.domains.literature.service import LiteratureService


def test_chunk_empty_returns_empty() -> None:
    assert LiteratureService._chunk_text("") == []
    assert LiteratureService._chunk_text("   ") == []


def test_chunk_splits_by_words() -> None:
    text = " ".join([f"word{i}" for i in range(300)])
    chunks = LiteratureService._chunk_text(text, chunk_size=500)
    assert len(chunks) > 1
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_short_text_single_chunk() -> None:
    chunks = LiteratureService._chunk_text("hello world", chunk_size=500)
    assert chunks == ["hello world"]
