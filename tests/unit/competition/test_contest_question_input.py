from __future__ import annotations

import hashlib
import html
import subprocess
from pathlib import Path

import pytest

from autoresearch.competition.contest_question_input import (
    ContestQuestionExtractionError,
    extract_all_science_125_questions,
    extract_first_science_125_question,
)


def _pdf_file(tmp_path: Path, content: bytes = b"%PDF-1.7\nfixture") -> Path:
    path = tmp_path / "science-125.pdf"
    path.write_bytes(content)
    return path


def _successful_text() -> bytes:
    pages = (
        "125 QUESTIONS: EXPLORATION AND DISCOVERY\n" + "front matter " * 20,
        """125 QUESTIONS
数 Mathematical Sciences
学 What makes prime numbers so special?
There are infinite prime numbers—numbers that are only divisible by one and themselves.

5
""",
    )
    return "\f".join(pages).encode()


_DISCIPLINE_COUNTS = (
    ("Mathematical Sciences", 3),
    ("Chemistry", 9),
    ("Medicine & Health", 11),
    ("Biology", 22),
    ("Astronomy", 23),
    ("Physics", 18),
    ("Engineering & Materials Science", 4),
    ("Information Science", 4),
    ("Neuroscience", 12),
    ("Ecology", 8),
    ("Energy Science", 3),
    ("Artificial Intelligence", 8),
)


def _successful_all_xml(*, omit_last: bool = False) -> bytes:
    ordinal = 0
    pages: list[str] = []
    for page_number, (discipline, count) in enumerate(_DISCIPLINE_COUNTS, start=7):
        nodes = [
            (
                f'<text top="90" left="120" width="300" height="30">'
                f"<b>{html.escape(discipline)}</b></text>"
            )
        ]
        for local_index in range(count):
            ordinal += 1
            if ordinal == 1:
                question = "What makes prime numbers so special?"
            elif ordinal == 125:
                question = "Can robots or AIs have human creativity?"
            else:
                question = f"What is deterministic fixture question {ordinal}?"
            if omit_last and ordinal == 125:
                continue
            top = 130 + local_index * 35
            nodes.append(
                f'<text top="{top}" left="120" width="600" height="24">'
                f"<b>{html.escape(question)}</b></text>"
            )
        nodes.append(
            f'<text top="1093" left="830" width="20" height="18"><b>{page_number - 2}</b></text>'
        )
        pages.append(
            f'<page number="{page_number}" position="absolute" top="0" left="0" '
            f'height="2000" width="891">{"".join(nodes)}</page>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE pdf2xml SYSTEM "pdf2xml.dtd">'
        f'<pdf2xml>{"".join(pages)}</pdf2xml>'
    ).encode()


def test_extracts_first_question_with_program_computed_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf_file(tmp_path)

    def fake_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args[0], 0, stdout=_successful_text(), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = extract_first_science_125_question(source, pdftotext_executable=source)

    expected_source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.question_en == "What makes prime numbers so special?"
    assert result.question_zh == "素数为何如此特别？"
    assert result.ordinal == 1
    assert result.discipline_zh == "数学科学"
    assert result.pdf_page_number == 2
    assert result.printed_page_number == 5
    assert result.source_file_sha256 == expected_source_hash
    assert result.question_id.startswith("science125-q001-")
    assert result.extraction_evidence == (
        "PDF第2页栏目：数 Mathematical Sciences",
        "PDF第2页首个问句：学 What makes prime numbers so special?",
    )
    assert "英文问题逐字提取自PDF文本层" in result.translation_provenance


def test_same_pdf_and_text_produce_same_question_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf_file(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=_successful_text(), stderr=b""
        ),
    )

    first = extract_first_science_125_question(source, pdftotext_executable=source)
    second = extract_first_science_125_question(source, pdftotext_executable=source)

    assert first == second


def test_extracts_all_125_questions_from_bold_coordinate_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf_file(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=_successful_all_xml(), stderr=b""
        ),
    )

    result = extract_all_science_125_questions(source, pdftohtml_executable=source)

    assert result.question_count == 125
    assert [item.ordinal for item in result.questions] == list(range(1, 126))
    assert result.questions[0].question_en == "What makes prime numbers so special?"
    assert result.questions[0].question_zh == "素数为何如此特别？"
    assert result.questions[1].question_zh is None
    assert result.questions[-1].question_en == "Can robots or AIs have human creativity?"
    assert result.questions[0].original_text_fragments == (
        "What makes prime numbers so special?",
    )
    assert result.questions[0].printed_page_number == 5
    assert len({item.question_id for item in result.questions}) == 125
    assert result.manifest_hash == extract_all_science_125_questions(
        source, pdftohtml_executable=source
    ).manifest_hash


def test_all_question_extraction_rejects_an_incomplete_title_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf_file(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=_successful_all_xml(omit_last=True), stderr=b""
        ),
    )

    with pytest.raises(ContestQuestionExtractionError, match="实际得到124题"):
        extract_all_science_125_questions(source, pdftohtml_executable=source)


def test_rejects_an_abnormal_or_image_only_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf_file(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=("image page " * 20).encode(), stderr=b""
        ),
    )

    with pytest.raises(ContestQuestionExtractionError, match="未找到"):
        extract_first_science_125_question(source, pdftotext_executable=source)


def test_reports_missing_pdftotext_without_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _pdf_file(tmp_path)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(ContestQuestionExtractionError, match="pdftotext"):
        extract_first_science_125_question(source)


def test_rejects_non_pdf_input(tmp_path: Path) -> None:
    source = _pdf_file(tmp_path, b"not a pdf")

    with pytest.raises(ContestQuestionExtractionError, match="不是可识别的PDF"):
        extract_first_science_125_question(source)
