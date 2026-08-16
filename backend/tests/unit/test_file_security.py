"""File-security unit tests (spec §19.4)."""

from __future__ import annotations

from app.core.file_security import magic_bytes_matches


def test_pdf_signature_matches() -> None:
    assert magic_bytes_matches("application/pdf", b"%PDF-1.7\n...") is True


def test_pdf_signature_mismatch_rejected() -> None:
    assert magic_bytes_matches("application/pdf", b"just text, not a pdf") is False


def test_png_and_jpeg_signatures() -> None:
    assert magic_bytes_matches("image/png", b"\x89PNG\r\n\x1a\n....") is True
    assert magic_bytes_matches("image/jpeg", b"\xff\xd8\xff\xe0....") is True
    assert magic_bytes_matches("image/png", b"\xff\xd8\xff\xe0....") is False


def test_no_signature_types_pass_through() -> None:
    assert magic_bytes_matches("text/plain", b"anything") is True
    assert magic_bytes_matches("application/octet-stream", b"\x00\x01") is True
    assert magic_bytes_matches(None, b"") is True
