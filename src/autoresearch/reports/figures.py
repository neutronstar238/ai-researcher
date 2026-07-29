"""Generate source-backed scientific figure artifacts."""

from __future__ import annotations

import json
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIGURE_WIDTH = 720
FIGURE_HEIGHT = 460
PLOT_LEFT = 250
PLOT_RIGHT = 90
PLOT_BOTTOM = 54
PLOT_TOP = 70
BAR_COLOR = (39, 101, 162)
AXIS_COLOR = (35, 35, 35)
GRID_COLOR = (225, 225, 225)
BACKGROUND_COLOR = (255, 255, 255)
FLOW_COLORS = (
    (86, 180, 233),
    (0, 158, 115),
    (240, 228, 66),
    (230, 159, 0),
    (204, 121, 167),
    (213, 94, 0),
)
ROW_LABEL_SIZE = 10
VALUE_LABEL_SIZE = 9
KNOWN_METRIC_ORDER = (
    "accuracy",
    "baseline_accuracy",
    "zscore_centroid_accuracy",
    "macro_f1",
    "accuracy_delta_vs_baseline",
    "accuracy_delta_vs_zscore",
)
KNOWN_METRIC_LABELS = {
    "accuracy": "Accuracy",
    "baseline_accuracy": "Baseline accuracy",
    "zscore_centroid_accuracy": "Z-score centroid accuracy",
    "macro_f1": "Macro F1",
    "accuracy_delta_vs_baseline": "Delta vs baseline",
    "accuracy_delta_vs_zscore": "Delta vs z-score",
}


class FigureGenerationError(RuntimeError):
    """Raised when a figure cannot be generated from source results."""


@dataclass(frozen=True)
class FigureArtifact:
    """Paths and provenance for a generated figure."""

    title: str
    source_path: str
    pdf_path: str
    png_path: str
    metadata_path: str
    metric_names: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source_path": self.source_path,
            "pdf_path": self.pdf_path,
            "png_path": self.png_path,
            "metadata_path": self.metadata_path,
            "metric_names": list(self.metric_names),
        }


def generate_metric_bar_figure(
    metrics_source: Path | str,
    output_dir: Path | str,
    *,
    title: str = "Metric Summary",
    figure_id: str = "metric-summary",
) -> FigureArtifact:
    """Generate PDF and PNG metric figure artifacts from a metrics source file."""

    source_path = Path(metrics_source).resolve()
    metrics = _load_metrics(source_path)
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    slug = _slugify(figure_id)
    pdf_path = output_path / f"{slug}.pdf"
    png_path = output_path / f"{slug}.png"
    metadata_path = output_path / f"{slug}.metadata.json"
    ordered_metrics = _ordered_metrics(metrics)

    _write_metric_pdf(pdf_path, title, ordered_metrics)
    _write_metric_png(png_path, ordered_metrics)

    artifact = FigureArtifact(
        title=title,
        source_path=source_path.as_posix(),
        pdf_path=pdf_path.as_posix(),
        png_path=png_path.as_posix(),
        metadata_path=metadata_path.as_posix(),
        metric_names=tuple(name for name, _value in ordered_metrics),
    )
    metadata = {
        "figure": artifact.to_dict(),
        "figure_type": "metric_bar",
        "source_path": source_path.as_posix(),
        "metrics": [
            {"label": _metric_label(name), "name": name, "value": value}
            for name, value in ordered_metrics
        ],
        "style": {
            "name": "autoresearch-default",
            "orientation": "horizontal",
            "width": FIGURE_WIDTH,
            "height": FIGURE_HEIGHT,
            "bar_color_rgb": list(BAR_COLOR),
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact


def generate_flow_diagram_figure(
    diagram_source: Path | str,
    output_dir: Path | str,
    *,
    title: str = "Evidence Flow",
    figure_id: str = "evidence-flow",
) -> FigureArtifact:
    """Generate a deterministic, source-backed horizontal flow diagram."""

    source_path = Path(diagram_source).resolve()
    stages = _load_flow_stages(source_path)
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    slug = _slugify(figure_id)
    pdf_path = output_path / f"{slug}.pdf"
    png_path = output_path / f"{slug}.png"
    metadata_path = output_path / f"{slug}.metadata.json"
    _write_flow_pdf(pdf_path, title, stages)
    _write_flow_png(png_path, stages)

    artifact = FigureArtifact(
        title=title,
        source_path=source_path.as_posix(),
        pdf_path=pdf_path.as_posix(),
        png_path=png_path.as_posix(),
        metadata_path=metadata_path.as_posix(),
        metric_names=tuple(stage["id"] for stage in stages),
    )
    metadata = {
        "figure": artifact.to_dict(),
        "figure_type": "flow_diagram",
        "source_path": source_path.as_posix(),
        "stages": stages,
        "style": {
            "name": "autoresearch-flow",
            "orientation": "horizontal",
            "width": FIGURE_WIDTH,
            "height": FIGURE_HEIGHT,
            "palette": [list(color) for color in FLOW_COLORS],
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact


def _load_metrics(source_path: Path) -> dict[str, float]:
    if not source_path.exists():
        msg = f"metrics source file is missing: {source_path.as_posix()}"
        raise FigureGenerationError(msg)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"metrics source file is not valid JSON: {source_path.as_posix()}"
        raise FigureGenerationError(msg) from exc

    metric_payload = payload.get("metrics", payload) if isinstance(payload, dict) else {}
    if not isinstance(metric_payload, dict):
        msg = "metrics source must contain a JSON object"
        raise FigureGenerationError(msg)

    metrics: dict[str, float] = {}
    for name, value in metric_payload.items():
        if isinstance(name, str) and isinstance(value, int | float) and not isinstance(value, bool):
            metrics[name] = float(value)
    if not metrics:
        msg = "metrics source does not contain numeric metrics"
        raise FigureGenerationError(msg)
    return metrics


def _load_flow_stages(source_path: Path) -> list[dict[str, str]]:
    if not source_path.exists():
        msg = f"flow source file is missing: {source_path.as_posix()}"
        raise FigureGenerationError(msg)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"flow source file is not valid JSON: {source_path.as_posix()}"
        raise FigureGenerationError(msg) from exc
    stages_value = payload.get("stages") if isinstance(payload, dict) else None
    if not isinstance(stages_value, list) or not 2 <= len(stages_value) <= 6:
        raise FigureGenerationError("flow source must contain two to six stages")
    stages: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for value in stages_value:
        if not isinstance(value, dict):
            raise FigureGenerationError("flow stages must be JSON objects")
        stage_id = value.get("id")
        label = value.get("label")
        detail = value.get("detail", "")
        if (
            not isinstance(stage_id, str)
            or not stage_id.strip()
            or not isinstance(label, str)
            or not label.strip()
            or not isinstance(detail, str)
        ):
            raise FigureGenerationError("flow stages require text id, label, and detail")
        normalized_id = stage_id.strip()
        if normalized_id in seen_ids:
            raise FigureGenerationError("flow stage IDs must be unique")
        if len(label.strip()) > 48 or len(detail.strip()) > 72:
            raise FigureGenerationError("flow stage labels or details are too long")
        seen_ids.add(normalized_id)
        stages.append(
            {
                "id": normalized_id,
                "label": label.strip(),
                "detail": detail.strip(),
            }
        )
    return stages


def _write_flow_pdf(
    path: Path,
    title: str,
    stages: list[dict[str, str]],
) -> None:
    left = 28.0
    right = 28.0
    gap = 18.0
    box_width = (FIGURE_WIDTH - left - right - gap * (len(stages) - 1)) / len(stages)
    box_height = 126.0
    box_y = 156.0
    lines = [
        _pdf_fill_color(BACKGROUND_COLOR),
        f"0 0 {FIGURE_WIDTH} {FIGURE_HEIGHT} re f",
        _pdf_fill_color(AXIS_COLOR),
        _pdf_text(36, FIGURE_HEIGHT - 42, 17, title),
    ]
    for index, stage in enumerate(stages):
        x = left + index * (box_width + gap)
        color = FLOW_COLORS[index % len(FLOW_COLORS)]
        lines.extend(
            [
                _pdf_fill_color(color),
                f"{x:.3f} {box_y:.3f} {box_width:.3f} {box_height:.3f} re f",
                _pdf_stroke_color(AXIS_COLOR),
                "1 w",
                f"{x:.3f} {box_y:.3f} {box_width:.3f} {box_height:.3f} re S",
                _pdf_fill_color(AXIS_COLOR),
            ]
        )
        text_lines = [
            *_wrap_flow_text(stage["label"], width=17),
            *_wrap_flow_text(stage["detail"], width=20),
        ]
        text_y = box_y + box_height - 30
        for line_index, text_value in enumerate(text_lines[:5]):
            size = 10 if line_index < 2 else 8
            lines.append(_pdf_text(x + 8, text_y, size, text_value))
            text_y -= 19 if line_index < 2 else 15
        if index < len(stages) - 1:
            start_x = x + box_width
            end_x = start_x + gap - 4
            arrow_y = box_y + box_height / 2
            lines.extend(
                [
                    _pdf_stroke_color(AXIS_COLOR),
                    "1.5 w",
                    f"{start_x + 2:.3f} {arrow_y:.3f} m {end_x:.3f} {arrow_y:.3f} l S",
                    _pdf_fill_color(AXIS_COLOR),
                    (
                        f"{end_x:.3f} {arrow_y:.3f} m "
                        f"{end_x - 6:.3f} {arrow_y + 4:.3f} l "
                        f"{end_x - 6:.3f} {arrow_y - 4:.3f} l h f"
                    ),
                ]
            )
    _write_pdf(path, "\n".join(lines))


def _write_flow_png(path: Path, stages: list[dict[str, str]]) -> None:
    pixels = bytearray(BACKGROUND_COLOR * (FIGURE_WIDTH * FIGURE_HEIGHT))
    left = 28
    right = 28
    gap = 18
    box_width = round(
        (FIGURE_WIDTH - left - right - gap * (len(stages) - 1)) / len(stages)
    )
    box_height = 126
    box_y = _png_y(156 + box_height)
    for index, _stage in enumerate(stages):
        x = left + index * (box_width + gap)
        color = FLOW_COLORS[index % len(FLOW_COLORS)]
        _draw_rect(pixels, x, box_y, box_width, box_height, color)
        _draw_rect(pixels, x, box_y, box_width, 2, AXIS_COLOR)
        _draw_rect(pixels, x, box_y + box_height - 2, box_width, 2, AXIS_COLOR)
        _draw_rect(pixels, x, box_y, 2, box_height, AXIS_COLOR)
        _draw_rect(pixels, x + box_width - 2, box_y, 2, box_height, AXIS_COLOR)
        if index < len(stages) - 1:
            arrow_x = x + box_width + 2
            arrow_y = box_y + box_height // 2
            _draw_rect(pixels, arrow_x, arrow_y, max(gap - 5, 1), 2, AXIS_COLOR)
            _draw_rect(pixels, arrow_x + gap - 7, arrow_y - 3, 2, 8, AXIS_COLOR)
    _write_png(path, FIGURE_WIDTH, FIGURE_HEIGHT, pixels)


def _wrap_flow_text(text: str, *, width: int) -> list[str]:
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
    if current:
        lines.append(current)
    return lines


def _write_metric_pdf(
    path: Path,
    title: str,
    metrics: tuple[tuple[str, float], ...],
) -> None:
    content_lines = [
        _pdf_fill_color(BACKGROUND_COLOR),
        f"0 0 {FIGURE_WIDTH} {FIGURE_HEIGHT} re f",
        _pdf_fill_color(AXIS_COLOR),
        _pdf_text(40, FIGURE_HEIGHT - 36, 16, title),
        _pdf_stroke_color(GRID_COLOR),
        "0.5 w",
    ]
    for x in _grid_lines():
        content_lines.append(f"{x:.3f} {PLOT_BOTTOM} m {x:.3f} {_plot_top()} l S")
        content_lines.append(_pdf_text(x - 10, 28, 8, f"{_value_for_x(x, metrics):.2g}"))
    zero_x = _x_for_value(0.0, metrics)
    content_lines.extend(
        [
            _pdf_stroke_color(AXIS_COLOR),
            "1 w",
            f"{PLOT_LEFT} {PLOT_BOTTOM} m {_plot_right()} {PLOT_BOTTOM} l S",
            f"{zero_x:.3f} {PLOT_BOTTOM} m {zero_x:.3f} {_plot_top()} l S",
        ]
    )
    for name, value, x, y, width, height in _bar_layout(metrics):
        content_lines.append(_pdf_fill_color(BAR_COLOR))
        content_lines.append(f"{x:.3f} {y:.3f} {width:.3f} {height:.3f} re f")
        content_lines.append(_pdf_fill_color(AXIS_COLOR))
        label_y = y + max((height - ROW_LABEL_SIZE) / 2.0, 0.0) + 2
        content_lines.append(_pdf_text(40, label_y, ROW_LABEL_SIZE, _metric_label(name)))
        value_x = min(x + width + 6, FIGURE_WIDTH - PLOT_RIGHT + 16)
        if value < 0:
            value_x = max(x - 44, PLOT_LEFT - 50)
        content_lines.append(_pdf_text(value_x, label_y, VALUE_LABEL_SIZE, f"{value:.4g}"))

    _write_pdf(path, "\n".join(content_lines))


def _write_metric_png(
    path: Path,
    metrics: tuple[tuple[str, float], ...],
) -> None:
    pixels = bytearray(BACKGROUND_COLOR * (FIGURE_WIDTH * FIGURE_HEIGHT))
    for x in _grid_lines():
        _draw_rect(pixels, round(x), FIGURE_HEIGHT - _plot_top(), 1, _plot_height(), GRID_COLOR)
    zero_x = round(_x_for_value(0.0, metrics))
    _draw_rect(pixels, PLOT_LEFT, FIGURE_HEIGHT - PLOT_BOTTOM, _plot_width(), 2, AXIS_COLOR)
    _draw_rect(pixels, zero_x, FIGURE_HEIGHT - _plot_top(), 1, _plot_height(), AXIS_COLOR)
    for _name, _value, x, y, width, height in _bar_layout(metrics):
        _draw_rect(
            pixels,
            round(x),
            round(FIGURE_HEIGHT - y - height),
            max(round(width), 1),
            max(round(height), 1),
            BAR_COLOR,
        )
    _write_png(path, FIGURE_WIDTH, FIGURE_HEIGHT, pixels)


def _bar_layout(
    metrics: tuple[tuple[str, float], ...],
) -> list[tuple[str, float, float, float, float, float]]:
    slot_height = _plot_height() / len(metrics)
    bar_height = min(slot_height * 0.58, 28.0)
    zero_x = _x_for_value(0.0, metrics)
    bars: list[tuple[str, float, float, float, float, float]] = []
    for index, (name, value) in enumerate(metrics):
        center_y = _plot_top() - slot_height * index - slot_height / 2.0
        y = center_y - bar_height / 2.0
        value_x = _x_for_value(value, metrics)
        x = min(zero_x, value_x)
        width = abs(value_x - zero_x)
        bars.append((name, value, x, y, max(width, 1.0), bar_height))
    return bars


def _x_for_value(value: float, metrics: tuple[tuple[str, float], ...]) -> float:
    values = [metric_value for _name, metric_value in metrics]
    minimum = min(min(values), 0.0)
    maximum = max(max(values), 0.0)
    if minimum == maximum:
        maximum = minimum + 1.0
    return PLOT_LEFT + ((value - minimum) / (maximum - minimum)) * _plot_width()


def _grid_lines() -> list[float]:
    return [
        PLOT_LEFT + _plot_width() * fraction
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]


def _value_for_x(x: float, metrics: tuple[tuple[str, float], ...]) -> float:
    values = [metric_value for _name, metric_value in metrics]
    minimum = min(min(values), 0.0)
    maximum = max(max(values), 0.0)
    if minimum == maximum:
        maximum = minimum + 1.0
    return minimum + ((x - PLOT_LEFT) / _plot_width()) * (maximum - minimum)


def _plot_width() -> int:
    return FIGURE_WIDTH - PLOT_LEFT - PLOT_RIGHT


def _plot_height() -> int:
    return FIGURE_HEIGHT - PLOT_BOTTOM - PLOT_TOP


def _plot_right() -> int:
    return FIGURE_WIDTH - PLOT_RIGHT


def _plot_top() -> int:
    return FIGURE_HEIGHT - PLOT_TOP


def _draw_rect(
    pixels: bytearray,
    x: int,
    y: int,
    width: int,
    height: int,
    color: tuple[int, int, int],
) -> None:
    start_x = max(x, 0)
    end_x = min(x + width, FIGURE_WIDTH)
    start_y = max(y, 0)
    end_y = min(y + height, FIGURE_HEIGHT)
    for row in range(start_y, end_y):
        for column in range(start_x, end_x):
            offset = (row * FIGURE_WIDTH + column) * 3
            pixels[offset : offset + 3] = bytes(color)


def _png_y(pdf_y: float) -> int:
    return round(FIGURE_HEIGHT - pdf_y)


def _write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    rows = []
    stride = width * 3
    for row in range(height):
        start = row * stride
        rows.append(b"\x00" + bytes(pixels[start : start + stride]))
    payload = b"".join(
        [
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(b"".join(rows))),
            _png_chunk(b"IEND", b""),
        ]
    )
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def _write_pdf(path: Path, stream: str) -> None:
    stream_bytes = stream.encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            f"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {FIGURE_WIDTH} {FIGURE_HEIGHT}] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ).encode("ascii"),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n"
        ).encode("ascii")
        + stream_bytes
        + b"\nendstream\nendobj\n",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for item in objects:
        offsets.append(len(content))
        content.extend(item)
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(content))


def _pdf_text(x: float, y: float, size: int, text: str) -> str:
    return f"BT /F1 {size} Tf {x:.3f} {y:.3f} Td ({_pdf_escape(text)}) Tj ET"


def _pdf_escape(text: str) -> str:
    return (
        text.encode("latin-1", errors="replace")
        .decode("latin-1")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _pdf_fill_color(color: tuple[int, int, int]) -> str:
    red, green, blue = (channel / 255.0 for channel in color)
    return f"{red:.3f} {green:.3f} {blue:.3f} rg"


def _pdf_stroke_color(color: tuple[int, int, int]) -> str:
    red, green, blue = (channel / 255.0 for channel in color)
    return f"{red:.3f} {green:.3f} {blue:.3f} RG"


def _ordered_metrics(metrics: dict[str, float]) -> tuple[tuple[str, float], ...]:
    ordered_names = [name for name in KNOWN_METRIC_ORDER if name in metrics]
    ordered_names.extend(sorted(name for name in metrics if name not in KNOWN_METRIC_ORDER))
    return tuple((name, metrics[name]) for name in ordered_names)


def _metric_label(name: str) -> str:
    if name in KNOWN_METRIC_LABELS:
        return KNOWN_METRIC_LABELS[name]
    return name.replace("_", " ").strip().capitalize()


def _truncate_label(label: str) -> str:
    return label if len(label) <= 18 else f"{label[:15]}..."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "metric-summary"
