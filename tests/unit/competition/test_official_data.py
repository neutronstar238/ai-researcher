from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from autoresearch.competition import (
    MDBenchDataError,
    prepare_mdbench_official_data,
)


def _write_archive(path: Path, members: dict[str, bytes]) -> tuple[int, str]:
    with ZipFile(path, "w") as bundle:
        for name, payload in members.items():
            bundle.writestr(name, payload)
    content = path.read_bytes()
    return len(content), hashlib.md5(content, usedforsecurity=False).hexdigest()


def test_prepare_official_archive_is_hashed_inventoried_and_idempotent(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "processed.zip"
    size, md5 = _write_archive(
        archive,
        {
            "processed/ode/lotka_volterra.npz": b"ode-clean",
            "processed/ode/lotka_volterra_snr_20.npz": b"ode-noisy",
            "processed/pde/burgers.npz": b"pde-clean",
        },
    )

    manifest = prepare_mdbench_official_data(
        archive,
        tmp_path / "prepared",
        dataset_license="mit-license",
        expected_size=size,
        expected_checksum=f"md5:{md5}",
    )
    repeated = prepare_mdbench_official_data(
        archive,
        tmp_path / "prepared",
        dataset_license="mit-license",
        expected_size=size,
        expected_checksum=f"md5:{md5}",
    )

    assert manifest == repeated
    assert manifest.ode_systems == ("lotka_volterra",)
    assert manifest.pde_systems == ("burgers",)
    assert manifest.noise_conditions == ("snr_20",)
    assert len(manifest.artifacts) == 3
    assert len(manifest.inventory_hash) == 64
    assert Path(manifest.output_path).is_file()


def test_prepare_detects_extracted_artifact_tampering(tmp_path: Path) -> None:
    archive = tmp_path / "processed.zip"
    size, md5 = _write_archive(
        archive,
        {"processed/ode/harmonic_oscillator.npz": b"original"},
    )
    manifest = prepare_mdbench_official_data(
        archive,
        tmp_path / "prepared",
        dataset_license="mit-license",
        expected_size=size,
        expected_checksum=f"md5:{md5}",
    )
    artifact = Path(manifest.extracted_root) / manifest.artifacts[0].relative_path
    artifact.write_bytes(b"tampered-and-longer")

    with pytest.raises(MDBenchDataError, match="artifact size changed"):
        prepare_mdbench_official_data(
            archive,
            tmp_path / "prepared",
            dataset_license="mit-license",
            expected_size=size,
            expected_checksum=f"md5:{md5}",
        )


@pytest.mark.parametrize(
    "unsafe_name",
    ("../escape.npz", "C:/escape.npz"),
)
def test_prepare_rejects_unsafe_zip_paths(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    archive = tmp_path / "processed.zip"
    size, md5 = _write_archive(archive, {unsafe_name: b"unsafe"})

    with pytest.raises(MDBenchDataError, match="unsafe archive member path"):
        prepare_mdbench_official_data(
            archive,
            tmp_path / "prepared",
            dataset_license="mit-license",
            expected_size=size,
            expected_checksum=f"md5:{md5}",
        )
    assert not list((tmp_path / "prepared").glob("processed-*"))


def test_prepare_rejects_archive_checksum_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "processed.zip"
    size, _md5 = _write_archive(
        archive,
        {"processed/ode/harmonic_oscillator.npz": b"content"},
    )

    with pytest.raises(MDBenchDataError, match="archive md5 mismatch"):
        prepare_mdbench_official_data(
            archive,
            tmp_path / "prepared",
            dataset_license="mit-license",
            expected_size=size,
            expected_checksum="md5:00000000000000000000000000000000",
        )
