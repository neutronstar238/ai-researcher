"""Deterministic, dependency-free profiling of public MDBench NPZ inputs.

This module does not propose a scientific explanation.  It converts the public
development arrays into hash-bound descriptive measurements that a configured
model may cite when it authors and tests its own hypotheses.  Confirmation data
is never accepted by this API.
"""

from __future__ import annotations

import ast
import hashlib
import math
import struct
import sys
from array import array
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, overload
from zipfile import BadZipFile, ZipFile

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.models import StrictFrozenModel

_PROFILE_VERSION: Literal["public-development-data-profile-v1"] = (
    "public-development-data-profile-v1"
)
_BUFFER_SIZE = 1024 * 1024
_EPSILON = 1e-15


class PublicDataProfileError(RuntimeError):
    """Raised when a public array cannot be profiled without ambiguity."""


class NumericSummary(StrictFrozenModel):
    """Finite-value descriptive statistics with no scientific interpretation."""

    count: int = Field(ge=1)
    finite_count: int = Field(ge=0)
    finite_fraction: float = Field(ge=0.0, le=1.0)
    zero_fraction: float = Field(ge=0.0, le=1.0)
    minimum: float | None
    maximum: float | None
    mean: float | None
    standard_deviation: float | None = Field(default=None, ge=0.0)
    root_mean_square: float | None = Field(default=None, ge=0.0)


class CoordinateSummary(StrictFrozenModel):
    """Exact coordinate extent plus spacing regularity."""

    name: str = Field(min_length=1)
    values: NumericSummary
    spacing: NumericSummary | None
    strictly_increasing: bool


class ChannelProfile(StrictFrozenModel):
    """Observed clean/noisy statistics for one final-axis data channel."""

    channel_index: int = Field(ge=0)
    clean_state: NumericSummary
    clean_derivative: NumericSummary
    state_derivative_correlation: float | None = Field(default=None, ge=-1.0, le=1.0)
    snr20_state_noise_relative_rms: float | None = Field(default=None, ge=0.0)
    snr20_derivative_noise_relative_rms: float | None = Field(
        default=None,
        ge=0.0,
    )
    snr20_state_empirical_snr_db: float | None
    snr20_derivative_empirical_snr_db: float | None
    boundary_to_interior_derivative_rms: float | None = Field(
        default=None,
        ge=0.0,
    )


class PublicSystemDataProfile(StrictFrozenModel):
    """Hash-bound descriptive measurements for one public development system."""

    schema_version: Literal["public-development-data-profile-v1"] = _PROFILE_VERSION
    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    conditions_profiled: tuple[str, ...] = Field(min_length=1)
    clean_relative_path: str = Field(min_length=1)
    clean_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snr20_relative_path: str | None
    snr20_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    array_shapes: dict[str, tuple[int, ...]]
    array_dtypes: dict[str, str]
    coordinates: tuple[CoordinateSummary, ...] = Field(min_length=1)
    sample_axis_count: int = Field(ge=1)
    channel_count: int = Field(ge=1)
    state_channel_max_abs_correlation: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    derivative_channel_max_abs_correlation: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    channels: tuple[ChannelProfile, ...] = Field(min_length=1)
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_profile(self) -> PublicSystemDataProfile:
        if len(self.channels) != self.channel_count:
            raise PublicDataProfileError("通道画像数量与 channel_count 不一致")
        if [item.channel_index for item in self.channels] != list(
            range(self.channel_count)
        ):
            raise PublicDataProfileError("通道画像必须按零基索引连续排列")
        if (self.snr20_relative_path is None) != (self.snr20_sha256 is None):
            raise PublicDataProfileError("snr_20 路径与哈希必须同时存在或同时缺失")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"profile_hash"})
        )
        if self.profile_hash != expected:
            raise PublicDataProfileError("公开数据画像哈希不一致")
        return self


def public_data_profile_evidence_view(
    profile: PublicSystemDataProfile,
) -> dict[str, Any]:
    """Return a compact, interpretation-free view for model evidence prompts.

    The full profile remains the hash authority.  This projection removes repeated
    moments that made the literature prompt unnecessarily large while preserving the
    observed quantities that can motivate a query.  It does not label any quantity as
    a cause, mechanism, anomaly, or research gap.
    """

    payload: dict[str, Any] = {
        "schema_version": "public-development-data-profile-evidence-view-v1",
        "system_name": profile.system_name,
        "data_type": profile.data_type,
        "profile_hash": profile.profile_hash,
        "conditions_profiled": list(profile.conditions_profiled),
        "source_arrays": {
            "clean": {
                "relative_path": profile.clean_relative_path,
                "sha256": profile.clean_sha256,
            },
            "snr_20": (
                {
                    "relative_path": profile.snr20_relative_path,
                    "sha256": profile.snr20_sha256,
                }
                if profile.snr20_relative_path is not None
                else None
            ),
        },
        "array_shapes": {
            name: list(shape) for name, shape in profile.array_shapes.items()
        },
        "sample_axis_count": profile.sample_axis_count,
        "channel_count": profile.channel_count,
        "state_channel_max_abs_correlation": (
            profile.state_channel_max_abs_correlation
        ),
        "derivative_channel_max_abs_correlation": (
            profile.derivative_channel_max_abs_correlation
        ),
        "coordinates": [
            {
                "name": coordinate.name,
                "minimum": coordinate.values.minimum,
                "maximum": coordinate.values.maximum,
                "spacing_mean": (
                    coordinate.spacing.mean if coordinate.spacing is not None else None
                ),
                "spacing_standard_deviation": (
                    coordinate.spacing.standard_deviation
                    if coordinate.spacing is not None
                    else None
                ),
                "strictly_increasing": coordinate.strictly_increasing,
            }
            for coordinate in profile.coordinates
        ],
        "channels": [
            {
                "channel_index": channel.channel_index,
                "clean_state_minimum": channel.clean_state.minimum,
                "clean_state_maximum": channel.clean_state.maximum,
                "clean_state_root_mean_square": (
                    channel.clean_state.root_mean_square
                ),
                "clean_derivative_minimum": channel.clean_derivative.minimum,
                "clean_derivative_maximum": channel.clean_derivative.maximum,
                "clean_derivative_root_mean_square": (
                    channel.clean_derivative.root_mean_square
                ),
                "state_derivative_correlation": (
                    channel.state_derivative_correlation
                ),
                "snr20_state_noise_relative_rms": (
                    channel.snr20_state_noise_relative_rms
                ),
                "snr20_derivative_noise_relative_rms": (
                    channel.snr20_derivative_noise_relative_rms
                ),
                "boundary_to_interior_derivative_rms": (
                    channel.boundary_to_interior_derivative_rms
                ),
            }
            for channel in profile.channels
        ],
    }
    payload["evidence_view_hash"] = canonical_model_hash(payload)
    return payload


def public_data_profile_feature_values(
    profile: PublicSystemDataProfile,
) -> dict[str, float]:
    """Project one profile into a fixed descriptive feature dictionary.

    All returned features are measured quantities.  The function intentionally does
    not rank, label, select, or interpret systems; downstream association code must
    expose every estimable predeclared feature to avoid cherry-picking.
    """

    features: dict[str, float] = {
        "sample_axis_count": float(profile.sample_axis_count),
        "channel_count": float(profile.channel_count),
    }

    def add_optional(name: str, value: float | None) -> None:
        if value is not None and math.isfinite(value):
            features[name] = _stable(float(value))

    add_optional(
        "state_channel_max_abs_correlation",
        profile.state_channel_max_abs_correlation,
    )
    add_optional(
        "derivative_channel_max_abs_correlation",
        profile.derivative_channel_max_abs_correlation,
    )

    channel_fields: tuple[tuple[str, tuple[float | None, ...]], ...] = (
        (
            "abs_state_derivative_correlation",
            tuple(
                abs(item.state_derivative_correlation)
                if item.state_derivative_correlation is not None
                else None
                for item in profile.channels
            ),
        ),
        (
            "clean_state_root_mean_square",
            tuple(item.clean_state.root_mean_square for item in profile.channels),
        ),
        (
            "clean_derivative_root_mean_square",
            tuple(
                item.clean_derivative.root_mean_square for item in profile.channels
            ),
        ),
        (
            "snr20_state_noise_relative_rms",
            tuple(item.snr20_state_noise_relative_rms for item in profile.channels),
        ),
        (
            "snr20_derivative_noise_relative_rms",
            tuple(
                item.snr20_derivative_noise_relative_rms
                for item in profile.channels
            ),
        ),
        (
            "boundary_to_interior_derivative_rms",
            tuple(
                item.boundary_to_interior_derivative_rms
                for item in profile.channels
            ),
        ),
    )
    for base_name, raw_values in channel_fields:
        values = sorted(
            float(value)
            for value in raw_values
            if value is not None and math.isfinite(float(value))
        )
        if not values:
            continue
        midpoint = len(values) // 2
        median = (
            values[midpoint]
            if len(values) % 2
            else (values[midpoint - 1] + values[midpoint]) / 2.0
        )
        features[f"median_{base_name}"] = _stable(median)
        features[f"maximum_{base_name}"] = _stable(values[-1])

    for coordinate in profile.coordinates:
        if coordinate.spacing is not None:
            add_optional(
                f"coordinate_{coordinate.name}_spacing_mean",
                coordinate.spacing.mean,
            )
            add_optional(
                f"coordinate_{coordinate.name}_spacing_standard_deviation",
                coordinate.spacing.standard_deviation,
            )
    return dict(sorted(features.items()))


@dataclass(frozen=True)
class _NumericArray:
    shape: tuple[int, ...]
    dtype: str
    values: array


def profile_public_development_data(
    *,
    data_root: Path | str,
    systems: Sequence[Mapping[str, Any]],
    conditions: Sequence[str],
) -> tuple[tuple[PublicSystemDataProfile, ...], tuple[Path, ...]]:
    """Profile only the named public systems and frozen development conditions."""

    normalized_conditions = tuple(dict.fromkeys(str(item) for item in conditions))
    if "clean" not in normalized_conditions:
        raise PublicDataProfileError("公开数据画像要求冻结条件包含 clean")
    root = Path(data_root).resolve()
    profiles: list[PublicSystemDataProfile] = []
    evidence_paths: list[Path] = []
    for raw_system in systems:
        system_name = str(raw_system.get("system_name") or "")
        data_type = str(raw_system.get("data_type") or "")
        if not system_name or data_type not in {"ode", "pde"}:
            raise PublicDataProfileError(f"无效的公开系统描述：{dict(raw_system)}")
        clean_path = _resolve_public_npz(
            root=root,
            data_type=data_type,
            system_name=system_name,
            condition="clean",
        )
        snr20_path = (
            _resolve_public_npz(
                root=root,
                data_type=data_type,
                system_name=system_name,
                condition="snr_20",
            )
            if "snr_20" in normalized_conditions
            else None
        )
        profile = _profile_system(
            root=root,
            system_name=system_name,
            data_type=data_type,
            conditions=normalized_conditions,
            clean_path=clean_path,
            snr20_path=snr20_path,
        )
        profiles.append(profile)
        evidence_paths.append(clean_path)
        if snr20_path is not None:
            evidence_paths.append(snr20_path)
    return tuple(profiles), tuple(dict.fromkeys(evidence_paths))


def _profile_system(
    *,
    root: Path,
    system_name: str,
    data_type: str,
    conditions: tuple[str, ...],
    clean_path: Path,
    snr20_path: Path | None,
) -> PublicSystemDataProfile:
    clean = _read_npz(clean_path)
    noisy = _read_npz(snr20_path) if snr20_path is not None else None
    required = {"t", "u", "du"}
    missing = sorted(required - set(clean))
    if missing:
        raise PublicDataProfileError(f"{clean_path} 缺少数组：{missing}")
    state = clean["u"]
    derivative = clean["du"]
    if state.shape != derivative.shape or len(state.shape) < 2:
        raise PublicDataProfileError(
            f"{system_name} 的 u/du 形状不一致或缺少通道轴"
        )
    channel_count = state.shape[-1]
    sample_axis_count = math.prod(state.shape[:-1])
    if sample_axis_count * channel_count != len(state.values):
        raise PublicDataProfileError(f"{system_name} 的数组长度与形状不一致")
    noisy_state: _NumericArray | None = None
    noisy_derivative: _NumericArray | None = None
    if noisy is not None:
        noisy_state = noisy.get("u")
        noisy_derivative = noisy.get("du")
        if (
            noisy_state is None
            or noisy_derivative is None
            or noisy_state.shape != state.shape
            or noisy_derivative.shape != derivative.shape
        ):
            raise PublicDataProfileError(
                f"{system_name} 的 snr_20 u/du 与 clean 形状不一致"
            )

    coordinates = tuple(
        _coordinate_summary(name, clean[name])
        for name in ("t", "x", "y", "z")
        if name in clean
    )
    boundary_masks = (
        _pde_boundary_masks(state.shape, clean)
        if data_type == "pde"
        else None
    )
    channels: list[ChannelProfile] = []
    for channel_index in range(channel_count):
        clean_state_values = state.values[channel_index::channel_count]
        clean_derivative_values = derivative.values[channel_index::channel_count]
        state_noise = (
            _noise_measurements(
                clean_state_values,
                noisy_state.values[channel_index::channel_count],
            )
            if noisy_state is not None
            else (None, None)
        )
        derivative_noise = (
            _noise_measurements(
                clean_derivative_values,
                noisy_derivative.values[channel_index::channel_count],
            )
            if noisy_derivative is not None
            else (None, None)
        )
        channels.append(
            ChannelProfile(
                channel_index=channel_index,
                clean_state=_numeric_summary(clean_state_values),
                clean_derivative=_numeric_summary(clean_derivative_values),
                state_derivative_correlation=_pearson(
                    clean_state_values,
                    clean_derivative_values,
                ),
                snr20_state_noise_relative_rms=state_noise[0],
                snr20_derivative_noise_relative_rms=derivative_noise[0],
                snr20_state_empirical_snr_db=state_noise[1],
                snr20_derivative_empirical_snr_db=derivative_noise[1],
                boundary_to_interior_derivative_rms=(
                    _boundary_to_interior_rms(
                        clean_derivative_values,
                        boundary_masks,
                    )
                    if boundary_masks is not None
                    else None
                ),
            )
        )

    relative_clean = clean_path.resolve().relative_to(root).as_posix()
    relative_snr20 = (
        snr20_path.resolve().relative_to(root).as_posix()
        if snr20_path is not None
        else None
    )
    payload: dict[str, Any] = {
        "schema_version": _PROFILE_VERSION,
        "system_name": system_name,
        "data_type": data_type,
        "conditions_profiled": list(conditions),
        "clean_relative_path": relative_clean,
        "clean_sha256": _sha256_file(clean_path),
        "snr20_relative_path": relative_snr20,
        "snr20_sha256": _sha256_file(snr20_path) if snr20_path else None,
        "array_shapes": {name: list(item.shape) for name, item in clean.items()},
        "array_dtypes": {name: item.dtype for name, item in clean.items()},
        "coordinates": [item.model_dump(mode="json") for item in coordinates],
        "sample_axis_count": sample_axis_count,
        "channel_count": channel_count,
        "state_channel_max_abs_correlation": _max_abs_channel_correlation(state),
        "derivative_channel_max_abs_correlation": (
            _max_abs_channel_correlation(derivative)
        ),
        "channels": [item.model_dump(mode="json") for item in channels],
    }
    payload["profile_hash"] = canonical_model_hash(payload)
    return PublicSystemDataProfile.model_validate(payload)


def _resolve_public_npz(
    *,
    root: Path,
    data_type: str,
    system_name: str,
    condition: str,
) -> Path:
    suffix = "" if condition == "clean" else f"_{condition}"
    filename = f"{system_name}{suffix}.npz"
    candidates = (
        root / "processed" / "data" / data_type / system_name / filename,
        root / "data" / data_type / system_name / filename,
        root / data_type / system_name / filename,
    )
    matches = [path.resolve() for path in candidates if path.is_file()]
    if len(matches) != 1:
        raise PublicDataProfileError(
            f"公开数据文件必须唯一存在：{data_type}/{system_name}/{filename}，"
            f"实际找到 {len(matches)} 个"
        )
    path = matches[0]
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PublicDataProfileError(f"公开数据路径越界：{path}") from exc
    return path


def _read_npz(path: Path | None) -> dict[str, _NumericArray]:
    if path is None:
        return {}
    arrays: dict[str, _NumericArray] = {}
    try:
        with ZipFile(path) as bundle:
            for member in bundle.infolist():
                if "/" in member.filename or "\\" in member.filename:
                    raise PublicDataProfileError(
                        f"NPZ 包含嵌套或不安全成员：{member.filename}"
                    )
                if not member.filename.endswith(".npy"):
                    continue
                name = member.filename.removesuffix(".npy")
                if name in arrays:
                    raise PublicDataProfileError(f"NPZ 数组名重复：{name}")
                with bundle.open(member) as handle:
                    arrays[name] = _read_npy(handle.read(), source=f"{path}:{name}")
    except BadZipFile as exc:
        raise PublicDataProfileError(f"无效 NPZ 文件：{path}") from exc
    return arrays


def _read_npy(raw: bytes, *, source: str) -> _NumericArray:
    if not raw.startswith(b"\x93NUMPY") or len(raw) < 10:
        raise PublicDataProfileError(f"无效 NPY 头：{source}")
    major, minor = raw[6], raw[7]
    if (major, minor) == (1, 0):
        header_length = struct.unpack("<H", raw[8:10])[0]
        header_start = 10
    elif major in {2, 3}:
        if len(raw) < 12:
            raise PublicDataProfileError(f"截断 NPY 头：{source}")
        header_length = struct.unpack("<I", raw[8:12])[0]
        header_start = 12
    else:
        raise PublicDataProfileError(f"不支持的 NPY 版本 {major}.{minor}：{source}")
    header_end = header_start + header_length
    try:
        header = ast.literal_eval(raw[header_start:header_end].decode("latin1").strip())
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        raise PublicDataProfileError(f"无法解析 NPY 头：{source}") from exc
    if not isinstance(header, dict):
        raise PublicDataProfileError(f"NPY 头不是字典：{source}")
    shape = header.get("shape")
    dtype = str(header.get("descr") or "")
    if (
        not isinstance(shape, tuple)
        or not shape
        or any(not isinstance(item, int) or item < 1 for item in shape)
    ):
        raise PublicDataProfileError(f"NPY shape 无效：{source}")
    fortran_order = bool(header.get("fortran_order"))
    dtype_map = {
        "<f8": ("d", 8, "little"),
        ">f8": ("d", 8, "big"),
        "=f8": ("d", 8, sys.byteorder),
        "|f8": ("d", 8, sys.byteorder),
        "<f4": ("f", 4, "little"),
        ">f4": ("f", 4, "big"),
        "=f4": ("f", 4, sys.byteorder),
        "|f4": ("f", 4, sys.byteorder),
    }
    if dtype not in dtype_map:
        raise PublicDataProfileError(f"只接受 float32/float64 NPY，实际为 {dtype}：{source}")
    typecode, item_size, byteorder = dtype_map[dtype]
    expected_bytes = math.prod(shape) * item_size
    payload = raw[header_end:]
    if len(payload) != expected_bytes:
        raise PublicDataProfileError(
            f"NPY 数据长度与 shape/dtype 不一致：{source}"
        )
    values = array(typecode)
    values.frombytes(payload)
    if byteorder != sys.byteorder:
        values.byteswap()
    if fortran_order and len(shape) > 1:
        values = _fortran_to_c(values, shape=shape, typecode=typecode)
    return _NumericArray(shape=shape, dtype=dtype, values=values)


def _fortran_to_c(
    values: array,
    *,
    shape: tuple[int, ...],
    typecode: str,
) -> array:
    """Return the same N-dimensional values in C-contiguous flat order."""

    size = math.prod(shape)
    converted = array(typecode, [0.0]) * size
    for c_flat in range(size):
        remainder = c_flat
        coordinates = [0] * len(shape)
        for axis in range(len(shape) - 1, -1, -1):
            coordinates[axis] = remainder % shape[axis]
            remainder //= shape[axis]
        f_flat = 0
        stride = 1
        for coordinate, axis_size in zip(coordinates, shape, strict=True):
            f_flat += coordinate * stride
            stride *= axis_size
        converted[c_flat] = values[f_flat]
    return converted


def _numeric_summary(values: Iterable[float]) -> NumericSummary:
    count = 0
    finite_count = 0
    zero_count = 0
    mean = 0.0
    second_moment = 0.0
    square_sum = 0.0
    minimum = math.inf
    maximum = -math.inf
    for raw in values:
        count += 1
        value = float(raw)
        if not math.isfinite(value):
            continue
        finite_count += 1
        if value == 0.0:
            zero_count += 1
        minimum = min(minimum, value)
        maximum = max(maximum, value)
        delta = value - mean
        mean += delta / finite_count
        second_moment += delta * (value - mean)
        square_sum += value * value
    if count < 1:
        raise PublicDataProfileError("不能画像空数组")
    if finite_count == 0:
        return NumericSummary(
            count=count,
            finite_count=0,
            finite_fraction=0.0,
            zero_fraction=0.0,
            minimum=None,
            maximum=None,
            mean=None,
            standard_deviation=None,
            root_mean_square=None,
        )
    return NumericSummary(
        count=count,
        finite_count=finite_count,
        finite_fraction=_stable(finite_count / count),
        zero_fraction=_stable(zero_count / finite_count),
        minimum=_stable(minimum),
        maximum=_stable(maximum),
        mean=_stable(mean),
        standard_deviation=_stable(math.sqrt(max(second_moment / finite_count, 0.0))),
        root_mean_square=_stable(math.sqrt(max(square_sum / finite_count, 0.0))),
    )


def _coordinate_summary(name: str, coordinate: _NumericArray) -> CoordinateSummary:
    values = tuple(float(item) for item in coordinate.values)
    spacing_values = tuple(
        right - left for left, right in zip(values, values[1:], strict=False)
    )
    return CoordinateSummary(
        name=name,
        values=_numeric_summary(values),
        spacing=_numeric_summary(spacing_values) if spacing_values else None,
        strictly_increasing=all(item > 0.0 for item in spacing_values),
    )


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    paired = [
        (float(a), float(b))
        for a, b in zip(left, right, strict=True)
        if math.isfinite(float(a)) and math.isfinite(float(b))
    ]
    if len(paired) < 2:
        return None
    mean_left = math.fsum(item[0] for item in paired) / len(paired)
    mean_right = math.fsum(item[1] for item in paired) / len(paired)
    covariance = math.fsum(
        (left_value - mean_left) * (right_value - mean_right)
        for left_value, right_value in paired
    )
    left_square = math.fsum(
        (left_value - mean_left) ** 2 for left_value, _ in paired
    )
    right_square = math.fsum(
        (right_value - mean_right) ** 2 for _, right_value in paired
    )
    denominator = math.sqrt(left_square * right_square)
    if denominator <= _EPSILON:
        return None
    return _stable(max(-1.0, min(1.0, covariance / denominator)))


def _max_abs_channel_correlation(values: _NumericArray) -> float | None:
    channel_count = values.shape[-1]
    if channel_count < 2:
        return None
    maximum: float | None = None
    for left_index in range(channel_count):
        left = values.values[left_index::channel_count]
        for right_index in range(left_index + 1, channel_count):
            right = values.values[right_index::channel_count]
            correlation = _pearson(left, right)
            if correlation is not None:
                maximum = max(maximum or 0.0, abs(correlation))
    return _stable(maximum) if maximum is not None else None


def _noise_measurements(
    clean: Sequence[float],
    noisy: Sequence[float],
) -> tuple[float | None, float | None]:
    if len(clean) != len(noisy) or not clean:
        return None, None
    paired = [
        (float(clean_value), float(noisy_value))
        for clean_value, noisy_value in zip(clean, noisy, strict=True)
        if math.isfinite(float(clean_value)) and math.isfinite(float(noisy_value))
    ]
    if not paired:
        return None, None
    signal_rms = math.sqrt(
        math.fsum(clean_value * clean_value for clean_value, _ in paired)
        / len(paired)
    )
    noise_rms = math.sqrt(
        math.fsum(
            (noisy_value - clean_value) ** 2
            for clean_value, noisy_value in paired
        )
        / len(paired)
    )
    relative = noise_rms / max(signal_rms, _EPSILON)
    empirical_snr = (
        20.0 * math.log10(signal_rms / noise_rms)
        if signal_rms > _EPSILON and noise_rms > _EPSILON
        else None
    )
    return _stable(relative), _stable(empirical_snr) if empirical_snr is not None else None


def _pde_boundary_masks(
    state_shape: tuple[int, ...],
    arrays: Mapping[str, _NumericArray],
) -> tuple[bool, ...]:
    spatial_sizes = tuple(
        len(arrays[name].values) for name in ("x", "y", "z") if name in arrays
    )
    if not spatial_sizes or state_shape[: len(spatial_sizes)] != spatial_sizes:
        raise PublicDataProfileError(
            "PDE u/du 前导空间轴与 x/y/z 坐标长度不一致"
        )
    non_channel_shape = state_shape[:-1]
    sample_count = math.prod(non_channel_shape)
    masks: list[bool] = []
    for flat_index in range(sample_count):
        remainder = flat_index
        indices = [0] * len(non_channel_shape)
        for axis in range(len(non_channel_shape) - 1, -1, -1):
            size = non_channel_shape[axis]
            indices[axis] = remainder % size
            remainder //= size
        masks.append(
            any(
                indices[axis] in {0, size - 1}
                for axis, size in enumerate(spatial_sizes)
            )
        )
    return tuple(masks)


def _boundary_to_interior_rms(
    values: Sequence[float],
    boundary_masks: Sequence[bool],
) -> float | None:
    if len(values) != len(boundary_masks):
        raise PublicDataProfileError("PDE 边界掩码与通道样本数不一致")
    boundary_squares: list[float] = []
    interior_squares: list[float] = []
    for value, is_boundary in zip(values, boundary_masks, strict=True):
        numeric = float(value)
        if not math.isfinite(numeric):
            continue
        target = boundary_squares if is_boundary else interior_squares
        target.append(numeric * numeric)
    if not boundary_squares or not interior_squares:
        return None
    boundary_rms = math.sqrt(math.fsum(boundary_squares) / len(boundary_squares))
    interior_rms = math.sqrt(math.fsum(interior_squares) / len(interior_squares))
    return _stable(boundary_rms / max(interior_rms, _EPSILON))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@overload
def _stable(value: None) -> None: ...


@overload
def _stable(value: float) -> float: ...


def _stable(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        raise PublicDataProfileError("画像统计不得包含非有限派生值")
    return float(format(value, ".12g"))
