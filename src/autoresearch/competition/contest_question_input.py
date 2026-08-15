"""Deterministic input adapter for the first Science 125 question.

The competition plan can use this module to bind a user-supplied copy of the
2021 ``125 Questions: Exploration and Discovery`` booklet to one exact seed
question.  Scientific prose is not generated here: the English question is
read from the PDF text layer, the Chinese rendering is a frozen repository
translation, and every identifier/hash is computed by the program.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SOURCE_TITLE = "125 Questions: Exploration and Discovery"
_EXPECTED_FIRST_QUESTION_EN = "What makes prime numbers so special?"
_FIRST_QUESTION_ZH = "素数为何如此特别？"
_DISCIPLINE_EN = "Mathematical Sciences"
_DISCIPLINE_ZH = "数学科学"
_QUESTION_LINE = re.compile(r"^[^A-Za-z]*(?P<question>[A-Z][^?]{3,200}\?)\s*$")
_PRINTED_PAGE_LINE = re.compile(r"^\s*(?P<number>[1-9][0-9]{0,2})\s*$")
_QUESTION_STARTS = (
    "What ",
    "Is ",
    "Will ",
    "Are ",
    "How ",
    "Why ",
    "Can ",
    "Did ",
    "Where ",
    "When ",
    "Could ",
    "Do ",
    "Does ",
    "Who ",
)
_DISCIPLINE_TRANSLATIONS = {
    "Mathematical Sciences": "数学科学",
    "Chemistry": "化学",
    "Medicine & Health": "医学与健康",
    "Biology": "生物学",
    "Astronomy": "天文学",
    "Physics": "物理学",
    "Engineering & Materials Science": "工程与材料科学",
    "Information Science": "信息科学",
    "Neuroscience": "神经科学",
    "Ecology": "生态学",
    "Energy Science": "能源科学",
    "Artificial Intelligence": "人工智能",
}
_EXPECTED_DISCIPLINE_COUNTS = {
    "Mathematical Sciences": 3,
    "Chemistry": 9,
    "Medicine & Health": 11,
    "Biology": 22,
    "Astronomy": 23,
    "Physics": 18,
    "Engineering & Materials Science": 4,
    "Information Science": 4,
    "Neuroscience": 12,
    "Ecology": 8,
    "Energy Science": 3,
    "Artificial Intelligence": 8,
}
_EXPECTED_LAST_QUESTION_EN = "Can robots or AIs have human creativity?"
_PDF2HTML_DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>")


class ContestQuestionExtractionError(RuntimeError):
    """Raised when the supplied PDF cannot provide trustworthy question text."""


class ContestQuestionInput(BaseModel):
    """Stable, source-bound representation of the first booklet question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["contest-question-input-v1"] = "contest-question-input-v1"
    question_id: str = Field(pattern=r"^science125-q001-[0-9a-f]{16}$")
    ordinal: Literal[1] = 1
    question_en: str
    question_zh: str
    discipline_en: str
    discipline_zh: str
    source_title: str
    source_year: Literal[2021] = 2021
    pdf_page_number: int = Field(ge=1)
    printed_page_number: int | None = Field(default=None, ge=1)
    source_pdf_path: str
    source_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extracted_page_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_backend: Literal["poppler-pdftotext-layout"] = "poppler-pdftotext-layout"
    extraction_evidence: tuple[str, ...] = Field(min_length=2)
    translation_provenance: Literal["仓库内冻结的确定性中文翻译；英文问题逐字提取自PDF文本层"] = (
        "仓库内冻结的确定性中文翻译；英文问题逐字提取自PDF文本层"
    )


class Science125QuestionInput(BaseModel):
    """One source-bound question extracted from the booklet's title layer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["science125-question-input-v2"] = "science125-question-input-v2"
    question_id: str = Field(pattern=r"^science125-q[0-9]{3}-[0-9a-f]{16}$")
    ordinal: int = Field(ge=1, le=125)
    question_en: str
    question_zh: str | None = None
    discipline_en: str
    discipline_zh: str
    source_title: Literal["125 Questions: Exploration and Discovery"] = (
        "125 Questions: Exploration and Discovery"
    )
    source_year: Literal[2021] = 2021
    pdf_page_number: int = Field(ge=1)
    printed_page_number: int | None = Field(default=None, ge=1)
    source_pdf_path: str
    source_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_text_layer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_backend: Literal["poppler-pdftohtml-xml"] = "poppler-pdftohtml-xml"
    original_text_fragments: tuple[str, ...] = Field(min_length=1)
    extraction_evidence: tuple[str, ...] = Field(min_length=2)
    translation_provenance: str

    @model_validator(mode="after")
    def _validate_program_projection(self) -> Science125QuestionInput:
        if self.discipline_en not in _DISCIPLINE_TRANSLATIONS:
            raise ValueError("unknown Science 125 discipline")
        if self.discipline_zh != _DISCIPLINE_TRANSLATIONS[self.discipline_en]:
            raise ValueError("discipline translation does not match frozen mapping")
        if self.question_text_sha256 != _sha256_text(self.question_en):
            raise ValueError("question text hash mismatch")
        expected_id = _science125_question_id(
            ordinal=self.ordinal,
            source_hash=self.source_file_sha256,
            page_number=self.pdf_page_number,
            question_en=self.question_en,
        )
        if self.question_id != expected_id:
            raise ValueError("question ID does not match source-bound program projection")
        if self.ordinal == 1:
            if self.question_en != _EXPECTED_FIRST_QUESTION_EN or self.question_zh != _FIRST_QUESTION_ZH:
                raise ValueError("question 1 does not match the frozen bilingual seed")
        elif self.question_zh is not None:
            raise ValueError("unverified Chinese translations are not stored for questions 2-125")
        return self


class Science125QuestionSet(BaseModel):
    """The complete, program-addressed 125-question extraction manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["science125-question-set-v1"] = "science125-question-set-v1"
    source_title: Literal["125 Questions: Exploration and Discovery"] = (
        "125 Questions: Exploration and Discovery"
    )
    source_year: Literal[2021] = 2021
    source_pdf_path: str
    source_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_backend: Literal["poppler-pdftohtml-xml"] = "poppler-pdftohtml-xml"
    question_count: Literal[125] = 125
    questions: tuple[Science125QuestionInput, ...] = Field(min_length=125, max_length=125)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_complete_set(self) -> Science125QuestionSet:
        if tuple(item.ordinal for item in self.questions) != tuple(range(1, 126)):
            raise ValueError("Science 125 ordinals must be contiguous and source ordered")
        if len({item.question_id for item in self.questions}) != 125:
            raise ValueError("Science 125 question IDs must be unique")
        if any(
            item.source_file_sha256 != self.source_file_sha256
            or item.source_pdf_path != self.source_pdf_path
            for item in self.questions
        ):
            raise ValueError("question source bindings differ from the manifest")
        counts = Counter(item.discipline_en for item in self.questions)
        if dict(counts) != _EXPECTED_DISCIPLINE_COUNTS:
            raise ValueError("Science 125 discipline counts differ from the 2021 booklet")
        if self.questions[0].question_en != _EXPECTED_FIRST_QUESTION_EN:
            raise ValueError("Science 125 first-question fingerprint mismatch")
        if self.questions[-1].question_en != _EXPECTED_LAST_QUESTION_EN:
            raise ValueError("Science 125 last-question fingerprint mismatch")
        expected_hash = _canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )
        if self.manifest_hash != expected_hash:
            raise ValueError("Science 125 manifest hash mismatch")
        return self


def extract_first_science_125_question(
    pdf_path: Path | str,
    *,
    pdftotext_executable: Path | str | None = None,
) -> ContestQuestionInput:
    """Extract and bind the first question from an explicit local PDF path.

    The function intentionally fails instead of guessing when Poppler is not
    available, the PDF has no usable text layer, or the detected first question
    differs from the known 2021 booklet ordering.
    """

    source = Path(pdf_path).expanduser().resolve()
    _validate_source_pdf(source)
    executable = _resolve_pdftotext(pdftotext_executable)
    pages = _extract_layout_pages(source, executable)
    page_number, question_en, evidence, page_text = _locate_first_question(pages)
    if question_en != _EXPECTED_FIRST_QUESTION_EN:
        raise ContestQuestionExtractionError(
            "PDF文本层中定位到的首题与2021版《125 Questions》不一致：" f"{question_en!r}"
        )

    source_hash = _sha256_file(source)
    page_hash = _sha256_text(page_text)
    question_digest = _sha256_text(f"{source_hash}\n{page_number}\n{question_en}")
    return ContestQuestionInput(
        question_id=f"science125-q001-{question_digest[:16]}",
        question_en=question_en,
        question_zh=_FIRST_QUESTION_ZH,
        discipline_en=_DISCIPLINE_EN,
        discipline_zh=_DISCIPLINE_ZH,
        source_title=_SOURCE_TITLE,
        pdf_page_number=page_number,
        printed_page_number=_printed_page_number(page_text),
        source_pdf_path=source.as_posix(),
        source_file_sha256=source_hash,
        extracted_page_sha256=page_hash,
        extraction_evidence=evidence,
    )


def extract_all_science_125_questions(
    pdf_path: Path | str,
    *,
    pdftohtml_executable: Path | str | None = None,
) -> Science125QuestionSet:
    """Extract all 125 title questions without asking a model to invent or rewrite them.

    The 2021 booklet uses two columns and wraps many bold question headings over
    multiple lines.  Plain ``pdftotext`` question-mark matching silently returns
    only 103 lines.  This extractor instead consumes Poppler's XML coordinates,
    joins adjacent bold fragments within the same column, tracks discipline
    headings (including mid-page transitions), and then fails closed unless the
    complete source-order and discipline-count fingerprints match the booklet.
    """

    source = Path(pdf_path).expanduser().resolve()
    _validate_source_pdf(source)
    executable = _resolve_pdftohtml(pdftohtml_executable)
    xml_text = _extract_layout_xml(source, executable)
    pages = _parse_layout_xml_pages(xml_text)
    source_hash = _sha256_file(source)
    extracted = _extract_question_rows(pages)
    if len(extracted) != 125:
        raise ContestQuestionExtractionError(
            f"PDF标题层应确定性提取125题，实际得到{len(extracted)}题；拒绝猜测或补写"
        )

    questions: list[Science125QuestionInput] = []
    for ordinal, row in enumerate(extracted, start=1):
        question_en = row["question_en"]
        page_number = row["page_number"]
        questions.append(
            Science125QuestionInput(
                question_id=_science125_question_id(
                    ordinal=ordinal,
                    source_hash=source_hash,
                    page_number=page_number,
                    question_en=question_en,
                ),
                ordinal=ordinal,
                question_en=question_en,
                question_zh=_FIRST_QUESTION_ZH if ordinal == 1 else None,
                discipline_en=row["discipline_en"],
                discipline_zh=_DISCIPLINE_TRANSLATIONS[row["discipline_en"]],
                pdf_page_number=page_number,
                printed_page_number=row["printed_page_number"],
                source_pdf_path=source.as_posix(),
                source_file_sha256=source_hash,
                page_text_layer_sha256=row["page_text_layer_sha256"],
                question_text_sha256=_sha256_text(question_en),
                original_text_fragments=tuple(row["fragments"]),
                extraction_evidence=(
                    f"PDF第{page_number}页栏目：{row['discipline_en']}",
                    "PDF加粗标题原文片段：" + " | ".join(row["fragments"]),
                ),
                translation_provenance=(
                    "仓库内冻结的确定性中文翻译；英文问题逐字提取自PDF标题层"
                    if ordinal == 1
                    else "未提供未经核验的中文翻译；英文问题逐字提取自PDF标题层"
                ),
            )
        )
    payload: dict[str, Any] = {
        "schema_version": "science125-question-set-v1",
        "source_title": _SOURCE_TITLE,
        "source_year": 2021,
        "source_pdf_path": source.as_posix(),
        "source_file_sha256": source_hash,
        "extraction_backend": "poppler-pdftohtml-xml",
        "question_count": 125,
        "questions": [item.model_dump(mode="json") for item in questions],
    }
    return Science125QuestionSet(
        **payload,
        manifest_hash=_canonical_sha256(payload),
    )


def _resolve_pdftohtml(explicit: Path | str | None) -> str:
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise ContestQuestionExtractionError(
                f"指定的pdftohtml可执行文件不存在：{candidate}"
            )
        return str(candidate)
    discovered = shutil.which("pdftohtml")
    if discovered is None:
        raise ContestQuestionExtractionError(
            "无法提取125题标题坐标：未找到Poppler的pdftohtml。"
            "请安装Poppler或显式传入pdftohtml_executable。"
        )
    return discovered


def _extract_layout_xml(source: Path, executable: str) -> str:
    command = [
        executable,
        "-xml",
        "-i",
        "-stdout",
        "-hidden",
        "-nodrm",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContestQuestionExtractionError(f"pdftohtml执行失败：{exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise ContestQuestionExtractionError(
            f"pdftohtml无法读取PDF（退出码{completed.returncode}）：{detail}"
        )
    try:
        xml_text = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContestQuestionExtractionError(
            "PDF XML标题层不是有效UTF-8，无法可靠提取125题"
        ) from exc
    if len(xml_text.strip()) < 100:
        raise ContestQuestionExtractionError("PDF XML标题层为空或内容过少")
    return xml_text


def _parse_layout_xml_pages(xml_text: str) -> tuple[ET.Element, ...]:
    sanitized = _PDF2HTML_DOCTYPE.sub("", xml_text)
    try:
        root = ET.fromstring(sanitized)
    except ET.ParseError as exc:
        raise ContestQuestionExtractionError(f"PDF XML标题层无法解析：{exc}") from exc
    pages = tuple(root.findall("page"))
    if not pages:
        raise ContestQuestionExtractionError("PDF XML标题层没有页面")
    return pages


def _extract_question_rows(pages: tuple[ET.Element, ...]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    current_discipline: str | None = None
    for page in pages:
        page_number = int(page.attrib["number"])
        elements: list[dict[str, Any]] = []
        page_projection: list[dict[str, Any]] = []
        for order, node in enumerate(page.findall("text")):
            text = " ".join("".join(node.itertext()).split())
            if not text:
                continue
            item = {
                "text": text,
                "top": int(node.attrib["top"]),
                "left": int(node.attrib["left"]),
                "width": int(node.attrib["width"]),
                "order": order,
                "bold": node.find(".//b") is not None,
            }
            page_projection.append(item)
            if item["bold"]:
                elements.append(item)
        page_hash = _canonical_sha256(
            {"page_number": page_number, "text_layer": page_projection}
        )
        discipline_markers = sorted(
            (
                (item["top"], item["left"], item["text"])
                for item in elements
                if item["text"] in _DISCIPLINE_TRANSLATIONS
            ),
            key=lambda value: (value[0], value[1]),
        )
        page_questions = _extract_page_question_headings(elements)
        for question in page_questions:
            eligible_markers = [
                marker for marker in discipline_markers if marker[0] <= question["top"]
            ]
            discipline = eligible_markers[-1][2] if eligible_markers else current_discipline
            if discipline is None:
                raise ContestQuestionExtractionError(
                    f"PDF第{page_number}页问题缺少可追溯学科栏目：{question['question_en']}"
                )
            question.update(
                {
                    "discipline_en": discipline,
                    "page_number": page_number,
                    "printed_page_number": _printed_page_number_from_elements(elements),
                    "page_text_layer_sha256": page_hash,
                }
            )
            rows.append(question)
        if discipline_markers:
            current_discipline = discipline_markers[-1][2]
    return tuple(rows)


def _extract_page_question_headings(
    elements: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    questions: list[dict[str, Any]] = []
    active: dict[int, dict[str, Any] | None] = {0: None, 1: None}
    for item in sorted(elements, key=lambda value: (value["top"], value["left"], value["order"])):
        text = item["text"]
        column = 0 if item["left"] < 350 else 1
        if (
            text in _DISCIPLINE_TRANSLATIONS
            or text.isdigit()
            or "125 QUESTIONS" in text
            or len(text) <= 2
        ):
            continue
        current = active[column]
        if (
            current is not None
            and item["top"] - current["last_top"] <= 35
            and not current["question_en"].endswith("?")
        ):
            current["question_en"] += " " + text
            current["last_top"] = item["top"]
            current["fragments"].append(text)
            if current["question_en"].endswith("?"):
                questions.append(current)
                active[column] = None
            continue
        if text.startswith(_QUESTION_STARTS):
            current = {
                "top": item["top"],
                "left": item["left"],
                "last_top": item["top"],
                "question_en": text,
                "fragments": [text],
            }
            if text.endswith("?"):
                questions.append(current)
                active[column] = None
            else:
                active[column] = current
    unfinished = [item for item in active.values() if item is not None]
    if unfinished:
        detail = "; ".join(item["question_en"] for item in unfinished)
        raise ContestQuestionExtractionError(
            f"PDF页存在未闭合的加粗问题标题，拒绝静默丢弃：{detail}"
        )
    return tuple(sorted(questions, key=lambda value: (value["top"], value["left"])))


def _printed_page_number_from_elements(elements: list[dict[str, Any]]) -> int | None:
    candidates = [
        int(item["text"])
        for item in elements
        if item["text"].isdigit()
        and 1 <= int(item["text"]) <= 999
        and item["top"] >= 1_050
    ]
    return candidates[-1] if candidates else None


def _science125_question_id(
    *,
    ordinal: int,
    source_hash: str,
    page_number: int,
    question_en: str,
) -> str:
    digest = _sha256_text(f"{source_hash}\n{page_number}\n{question_en}")
    return f"science125-q{ordinal:03d}-{digest[:16]}"


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source_pdf(source: Path) -> None:
    if not source.is_file():
        raise ContestQuestionExtractionError(f"PDF文件不存在：{source}")
    try:
        with source.open("rb") as handle:
            header = handle.read(5)
    except OSError as exc:
        raise ContestQuestionExtractionError(f"无法读取PDF文件：{source}: {exc}") from exc
    if header != b"%PDF-":
        raise ContestQuestionExtractionError(f"文件不是可识别的PDF：{source}")


def _resolve_pdftotext(explicit: Path | str | None) -> str:
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise ContestQuestionExtractionError(f"指定的pdftotext可执行文件不存在：{candidate}")
        return str(candidate)
    discovered = shutil.which("pdftotext")
    if discovered is None:
        raise ContestQuestionExtractionError(
            "无法提取PDF文本层：未找到Poppler的pdftotext。"
            "请安装Poppler或显式传入pdftotext_executable。"
        )
    return discovered


def _extract_layout_pages(source: Path, executable: str) -> tuple[str, ...]:
    command = [
        executable,
        "-layout",
        "-enc",
        "UTF-8",
        str(source),
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContestQuestionExtractionError(f"pdftotext执行失败：{exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise ContestQuestionExtractionError(
            f"pdftotext无法读取PDF（退出码{completed.returncode}）：{detail}"
        )
    try:
        text = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContestQuestionExtractionError(
            "PDF文本层不是有效UTF-8输出，无法可靠定位首题"
        ) from exc
    if len(text.strip()) < 100:
        raise ContestQuestionExtractionError(
            "PDF文本层为空或内容过少，无法可靠定位《Science》125个问题"
        )
    pages = tuple(text.split("\f"))
    if not any(page.strip() for page in pages):
        raise ContestQuestionExtractionError("PDF文本层没有可用页面文本")
    return pages


def _locate_first_question(
    pages: tuple[str, ...],
) -> tuple[int, str, tuple[str, ...], str]:
    for page_number, page_text in enumerate(pages, start=1):
        lines = tuple(line.rstrip() for line in page_text.splitlines())
        heading_index = next(
            (
                index
                for index, line in enumerate(lines)
                if _DISCIPLINE_EN.casefold() in line.casefold()
            ),
            None,
        )
        if heading_index is None:
            continue
        for line in lines[heading_index + 1 :]:
            match = _QUESTION_LINE.fullmatch(line.strip())
            if match is None:
                continue
            question = " ".join(match.group("question").split())
            heading = " ".join(lines[heading_index].split())
            raw_question_line = " ".join(line.split())
            evidence = (
                f"PDF第{page_number}页栏目：{heading}",
                f"PDF第{page_number}页首个问句：{raw_question_line}",
            )
            return page_number, question, evidence, page_text
    raise ContestQuestionExtractionError(
        "PDF文本层中未找到‘Mathematical Sciences’栏目后的首个科学问题；"
        "文件可能不是2021版125问题手册，或文本层/阅读顺序异常"
    )


def _printed_page_number(page_text: str) -> int | None:
    matches = [
        int(match.group("number"))
        for line in page_text.splitlines()
        if (match := _PRINTED_PAGE_LINE.fullmatch(line)) is not None
    ]
    return matches[-1] if matches else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
