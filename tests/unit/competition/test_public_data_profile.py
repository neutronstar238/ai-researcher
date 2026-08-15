from __future__ import annotations

import struct
from array import array
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from autoresearch.competition.public_data_profile import (
    PublicDataProfileError,
    _read_npy,
    profile_public_development_data,
    public_data_profile_evidence_view,
    public_data_profile_feature_values,
)


def _npy_bytes(
    shape: tuple[int, ...],
    values: list[float],
    *,
    fortran_order: bool = False,
) -> bytes:
    header_text = repr(
        {"descr": "<f8", "fortran_order": fortran_order, "shape": shape}
    )
    padding = (16 - ((10 + len(header_text) + 1) % 16)) % 16
    header = (header_text + (" " * padding) + "\n").encode("latin1")
    return (
        b"\x93NUMPY"
        + bytes((1, 0))
        + struct.pack("<H", len(header))
        + header
        + array("d", values).tobytes()
    )


def _write_npz(
    path: Path,
    *,
    arrays: dict[str, tuple[tuple[int, ...], list[float]]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as bundle:
        for name, (shape, values) in arrays.items():
            bundle.writestr(f"{name}.npy", _npy_bytes(shape, values))


def test_profiles_public_clean_and_snr20_arrays_without_numpy(tmp_path: Path) -> None:
    root = tmp_path / "prepared"
    base = root / "processed" / "data" / "ode" / "system-a"
    clean = {
        "t": ((3,), [0.0, 1.0, 2.0]),
        "u": ((3, 2), [1.0, 2.0, 2.0, 4.0, 3.0, 6.0]),
        "du": ((3, 2), [0.5, 1.0, 0.5, 1.0, 0.5, 1.0]),
    }
    noisy = {
        "t": clean["t"],
        "u": ((3, 2), [1.1, 2.2, 1.9, 3.8, 3.1, 6.2]),
        "du": ((3, 2), [0.6, 0.9, 0.4, 1.1, 0.6, 0.9]),
    }
    _write_npz(base / "system-a.npz", arrays=clean)
    _write_npz(base / "system-a_snr_20.npz", arrays=noisy)

    profiles, paths = profile_public_development_data(
        data_root=root,
        systems=[{"system_name": "system-a", "data_type": "ode"}],
        conditions=["clean", "snr_20"],
    )

    profile = profiles[0]
    assert profile.channel_count == 2
    assert profile.sample_axis_count == 3
    assert profile.array_shapes["u"] == (3, 2)
    assert profile.coordinates[0].strictly_increasing is True
    assert profile.state_channel_max_abs_correlation == pytest.approx(1.0)
    assert profile.channels[0].snr20_state_noise_relative_rms is not None
    assert profile.channels[0].boundary_to_interior_derivative_rms is None
    assert len(profile.profile_hash) == 64
    assert len(paths) == 2

    view = public_data_profile_evidence_view(profile)
    assert view["profile_hash"] == profile.profile_hash
    assert view["source_arrays"]["clean"]["sha256"] == profile.clean_sha256
    assert view["channels"][0]["clean_derivative_root_mean_square"] == 0.5
    assert "mechanism" not in view
    assert len(view["evidence_view_hash"]) == 64
    features = public_data_profile_feature_values(profile)
    assert features["sample_axis_count"] == 3.0
    assert features["channel_count"] == 2.0
    assert features["median_clean_derivative_root_mean_square"] == 0.75


def test_fortran_order_payload_is_normalized_to_c_order() -> None:
    decoded = _read_npy(
        _npy_bytes(
            (2, 3),
            [1.0, 4.0, 2.0, 5.0, 3.0, 6.0],
            fortran_order=True,
        ),
        source="unit-test",
    )

    assert list(decoded.values) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_pde_profile_measures_boundary_to_interior_derivative_rms(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prepared"
    base = root / "processed" / "data" / "pde" / "system-pde"
    shape = (3, 3, 2, 1)
    state = [1.0] * 18
    derivative: list[float] = []
    for x_index in range(3):
        for y_index in range(3):
            for _ in range(2):
                boundary = x_index in {0, 2} or y_index in {0, 2}
                derivative.append(2.0 if boundary else 1.0)
    arrays = {
        "t": ((2,), [0.0, 1.0]),
        "x": ((3,), [0.0, 0.5, 1.0]),
        "y": ((3,), [0.0, 0.5, 1.0]),
        "u": (shape, state),
        "du": (shape, derivative),
    }
    _write_npz(base / "system-pde.npz", arrays=arrays)
    _write_npz(base / "system-pde_snr_20.npz", arrays=arrays)

    profiles, _ = profile_public_development_data(
        data_root=root,
        systems=[{"system_name": "system-pde", "data_type": "pde"}],
        conditions=["clean", "snr_20"],
    )

    assert profiles[0].channels[0].boundary_to_interior_derivative_rms == 2.0


def test_profile_refuses_missing_public_condition(tmp_path: Path) -> None:
    with pytest.raises(PublicDataProfileError, match="唯一存在"):
        profile_public_development_data(
            data_root=tmp_path,
            systems=[{"system_name": "missing", "data_type": "ode"}],
            conditions=["clean", "snr_20"],
        )
