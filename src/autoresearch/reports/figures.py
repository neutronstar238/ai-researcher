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
FIGURE_HEIGHT = 420
PLOT_LEFT = 70
PLOT_RIGHT = 40
PLOT_BOTTOM = 70
PLOT_TOP = 70
BAR_COLOR = (39, 101, 162)
AXIS_COLOR = (35, 35, 35)
GRID_COLOR = (225, 225, 225)
BACKGROUND_COLOR = (255, 255, 255)


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
    ordered_metrics = tuple(sorted(metrics.items()))

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
            {"name": name, "value": value}
            for name, value in ordered_metrics
        ],
        "style": {
            "name": "autoresearch-default",
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


def _write_metric_pdf(
    path: Path,
    title: str,
    metrics: tuple[tuple[str, float], ...],
) -> None:
    content_lines = [
        _pdf_fill_color(BACKGROUND_COLOR),
        f"0 0 {FIGURE_WIDTH} {FIGURE_HEIGHT} re f",
        _pdf_text(40, FIGURE_HEIGHT - 36, 16, title),
        _pdf_stroke_color(GRID_COLOR),
        "0.5 w",
    ]
    for y in _grid_lines():
        content_lines.append(f"{PLOT_LEFT} {y:.3f} m {_plot_right()} {y:.3f} l S")
    zero_y = _y_for_value(0.0, metrics)
    content_lines.extend(
        [
            _pdf_stroke_color(AXIS_COLOR),
            "1 w",
            f"{PLOT_LEFT} {PLOT_BOTTOM} m {PLOT_LEFT} {_plot_top()} l S",
            f"{PLOT_LEFT} {zero_y:.3f} m {_plot_right()} {zero_y:.3f} l S",
            _pdf_fill_color(BAR_COLOR),
        ]
    )
    for name, value, x, width, bottom, height in _bar_layout(metrics):
        content_lines.append(f"{x:.3f} {bottom:.3f} {width:.3f} {height:.3f} re f")
        content_lines.append(_pdf_text(x, 32, 8, _truncate_label(name)))
        content_lines.append(_pdf_text(x, bottom + height + 8, 8, f"{value:.4g}"))

    _write_pdf(path, "\n".join(content_lines))


def _write_metric_png(
    path: Path,
    metrics: tuple[tuple[str, float], ...],
) -> None:
    pixels = bytearray(BACKGROUND_COLOR * (FIGURE_WIDTH * FIGURE_HEIGHT))
    for y in _grid_lines():
        _draw_rect(pixels, PLOT_LEFT, _png_y(y), _plot_width(), 1, GRID_COLOR)
    zero_y = _png_y(_y_for_value(0.0, metrics))
    _draw_rect(pixels, PLOT_LEFT, FIGURE_HEIGHT - _plot_top(), 1, _plot_height(), AXIS_COLOR)
    _draw_rect(pixels, PLOT_LEFT, zero_y, _plot_width(), 2, AXIS_COLOR)
    for _name, _value, x, _width, bottom, height in _bar_layout(metrics):
        _draw_rect(
            pixels,
            round(x),
            round(FIGURE_HEIGHT - bottom - height),
            round(_width),
            max(round(height), 1),
            BAR_COLOR,
        )
    _write_png(path, FIGURE_WIDTH, FIGURE_HEIGHT, pixels)


def _bar_layout(
    metrics: tuple[tuple[str, float], ...],
) -> list[tuple[str, float, float, float, float, float]]:
    slot_width = _plot_width() / len(metrics)
    bar_width = min(slot_width * 0.62, 72.0)
    zero_y = _y_for_value(0.0, metrics)
    bars: list[tuple[str, float, float, float, float, float]] = []
    for index, (name, value) in enumerate(metrics):
        center = PLOT_LEFT + slot_width * index + slot_width / 2.0
        x = center - bar_width / 2.0
        value_y = _y_for_value(value, metrics)
        bottom = min(zero_y, value_y)
        height = abs(value_y - zero_y)
        bars.append((name, value, x, bar_width, bottom, max(height, 1.0)))
    return bars


def _y_for_value(value: float, metrics: tuple[tuple[str, float], ...]) -> float:
    values = [metric_value for _name, metric_value in metrics]
    minimum = min(min(values), 0.0)
    maximum = max(max(values), 0.0)
    if minimum == maximum:
        maximum = minimum + 1.0
    return PLOT_BOTTOM + ((value - minimum) / (maximum - minimum)) * _plot_height()


def _grid_lines() -> list[float]:
    return [
        PLOT_BOTTOM + _plot_height() * fraction
        for fraction in (0.25, 0.5, 0.75, 1.0)
    ]


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


def _truncate_label(label: str) -> str:
    return label if len(label) <= 18 else f"{label[:15]}..."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "metric-summary"
