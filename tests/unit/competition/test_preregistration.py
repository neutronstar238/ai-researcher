from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from autoresearch.competition import (
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchPreregistrationError,
    MDBenchTemporalSplit,
    preregister_mdbench_gate_a,
    validate_mdbench_preregistration,
)
from autoresearch.competition.planning import MDBENCH_REVISION

_ODE_SYSTEMS = (
    "harmonic-oscillator",
    "van-der-pol-oscillator",
    "lotka-volterra-simple",
    "duffing-equation",
    "brusselator",
    "sir-infection",
    "lorenz-equations-chaotic",
    "rössler-attractor-chaotic",
    "glycolytic-oscillator",
    "autocatalytic-gene-switching",
)
_PDE_SYSTEMS = ("advection1d", "burgers", "kdv", "kuramoto_sivishinky")


def _manifest(*, omit: tuple[str, str, str] | None = None) -> MDBenchArchiveManifest:
    artifacts = []
    panels: tuple[
        tuple[Literal["ode", "pde"], tuple[str, ...]],
        ...,
    ] = (("ode", _ODE_SYSTEMS), ("pde", _PDE_SYSTEMS))
    for data_type, systems in panels:
        for system_name in systems:
            for condition in ("clean", "snr_20"):
                if (data_type, system_name, condition) == omit:
                    continue
                payload = f"{data_type}/{system_name}/{condition}".encode()
                artifacts.append(
                    MDBenchDatasetArtifact(
                        relative_path=(
                            f"processed/data/{data_type}/{system_name}/"
                            f"{system_name}{'' if condition == 'clean' else '_snr_20'}.npz"
                        ),
                        data_type=data_type,
                        system_name=system_name,
                        condition=condition,
                        size_bytes=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(),
                    )
                )
    return MDBenchArchiveManifest(
        repository_url="https://github.com/gryaklab/mdbench",
        benchmark_revision=MDBENCH_REVISION,
        dataset_doi="10.5281/zenodo.17611099",
        dataset_license="mit-license",
        archive_path="C:/fixture/processed.zip",
        archive_size_bytes=1,
        archive_md5="0" * 32,
        archive_sha256="1" * 64,
        extracted_root="C:/fixture/processed",
        artifacts=tuple(artifacts),
        ode_systems=_ODE_SYSTEMS,
        pde_systems=_PDE_SYSTEMS,
        noise_conditions=("snr_20",),
        inventory_hash="2" * 64,
        output_path="C:/fixture/archive-manifest.json",
    )


def test_preregistration_freezes_complete_result_blind_matrix(tmp_path: Path) -> None:
    output = tmp_path / "gate-a-preregistration.json"
    matrix = preregister_mdbench_gate_a(_manifest(), output)

    assert output.is_file()
    assert matrix.created_before_results is True
    assert matrix.conditions == ("clean", "snr_20")
    assert matrix.seeds == (11, 23, 37)
    assert len(matrix.systems) == 14
    assert sum(case.data_type == "ode" for case in matrix.systems) == 10
    assert sum(case.data_type == "pde" for case in matrix.systems) == 4
    assert sum(case.evaluation_split == "development" for case in matrix.systems) == 8
    assert sum(case.evaluation_split == "unseen_test" for case in matrix.systems) == 6
    assert len(matrix.attempts) == 252
    assert {method.method_id for method in matrix.methods} == {
        "sindy_or_pdefind",
        "operon_gp",
        "stability_sindy",
    }
    assert matrix.split_policy.train[1] == matrix.split_policy.validation[0]
    assert matrix.split_policy.validation[1] == matrix.split_policy.test[0]
    assert len(matrix.matrix_hash) == 64


def test_preregistration_is_idempotent_but_refuses_changed_frozen_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "gate-a-preregistration.json"
    first = preregister_mdbench_gate_a(_manifest(), output)
    second = preregister_mdbench_gate_a(_manifest(), output)
    assert first == second

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["matrix_hash"] = "f" * 64
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MDBenchPreregistrationError, match="matrix hash mismatch"):
        preregister_mdbench_gate_a(_manifest(), output)


def test_preregistration_recomputes_hash_and_rejects_content_tampering(
    tmp_path: Path,
) -> None:
    output = tmp_path / "gate-a-preregistration.json"
    matrix = preregister_mdbench_gate_a(_manifest(), output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["selection_policy"] = "post-hoc tampered policy"
    output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MDBenchPreregistrationError, match="matrix hash mismatch"):
        preregister_mdbench_gate_a(_manifest(), output)
    validate_mdbench_preregistration(matrix)


def test_preregistration_blocks_missing_selected_artifact(tmp_path: Path) -> None:
    manifest = _manifest(omit=("pde", "kdv", "snr_20"))

    with pytest.raises(MDBenchPreregistrationError, match="pde/kdv/snr_20"):
        preregister_mdbench_gate_a(manifest, tmp_path / "matrix.json")


def test_temporal_split_rejects_overlap() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        MDBenchTemporalSplit(
            train=(0.0, 0.7),
            validation=(0.6, 0.8),
            test=(0.8, 1.0),
        )
