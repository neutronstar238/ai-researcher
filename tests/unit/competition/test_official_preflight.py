from __future__ import annotations

import json
from pathlib import Path

from autoresearch.competition import run_mdbench_official_preflight
from autoresearch.competition.official import (
    MDBENCH_PROCESSED_CHECKSUM,
    MDBENCH_PROCESSED_SIZE,
    MDBENCH_REVISION,
)


def _json_fetcher(*, dataset_license: str | None = None):
    def fetch(url: str):
        if "/commits/" in url:
            return {"sha": MDBENCH_REVISION}
        assert "zenodo.org" in url
        license_metadata = {"id": dataset_license} if dataset_license else None
        return {
            "access": {"right": "public"},
            "metadata": {"rights": None, "license": license_metadata},
            "files": [
                {
                    "key": "processed.zip",
                    "size": MDBENCH_PROCESSED_SIZE,
                    "checksum": MDBENCH_PROCESSED_CHECKSUM,
                    "links": {"self": "https://zenodo.test/processed.zip"},
                }
            ],
        }

    return fetch


def test_preflight_blocks_public_archive_without_explicit_license(tmp_path: Path) -> None:
    report = run_mdbench_official_preflight(
        tmp_path,
        json_fetcher=_json_fetcher(),
        text_fetcher=lambda _url: "MIT License\n",
        container_probe=lambda: (True, "29.6.1", None),
    )

    assert report.revision_available is True
    assert report.processed_metadata_matches is True
    assert report.dataset_access_right == "public"
    assert report.dataset_license is None
    assert report.ready_to_download is False
    assert report.ready_to_execute is False
    assert report.access_request_ids == ("access_mdbench_dataset_license_17611099",)
    request_path = tmp_path / "access-requests" / (
        "access_mdbench_dataset_license_17611099.json"
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "data_license"
    assert request["environment_variable_names"] == []


def test_preflight_is_ready_only_with_license_and_container(tmp_path: Path) -> None:
    report = run_mdbench_official_preflight(
        tmp_path,
        json_fetcher=_json_fetcher(dataset_license="cc-by-4.0"),
        text_fetcher=lambda _url: "MIT License\n",
        container_probe=lambda: (True, "29.6.1", None),
    )

    assert report.dataset_license == "cc-by-4.0"
    assert report.ready_to_download is True
    assert report.ready_to_execute is True
    assert report.blockers == ()
    assert report.access_request_ids == ()


def test_preflight_does_not_misclassify_network_failure_as_license_request(
    tmp_path: Path,
) -> None:
    def fetch(url: str):
        if "/commits/" in url:
            return {"sha": MDBENCH_REVISION}
        raise TimeoutError("simulated Zenodo timeout")

    report = run_mdbench_official_preflight(
        tmp_path,
        json_fetcher=fetch,
        text_fetcher=lambda _url: "MIT License\n",
        container_probe=lambda: (True, "29.6.1", None),
    )

    assert report.ready_to_download is False
    assert report.access_request_ids == ()
    assert any("metadata unavailable" in blocker for blocker in report.blockers)
    assert not (tmp_path / "access-requests").exists()


def test_versioned_container_contract_matches_pinned_source() -> None:
    root = Path(__file__).resolve().parents[3]
    container_dir = root / "deploy" / "experiments" / "mdbench"
    dockerfile = (container_dir / "Dockerfile").read_text(encoding="utf-8")
    manifest = json.loads(
        (container_dir / "container-manifest.json").read_text(encoding="utf-8")
    )

    assert "FROM python:3.9.23-slim-bookworm@sha256:" in dockerfile
    assert MDBENCH_REVISION in dockerfile
    assert "latest" not in dockerfile.casefold()
    assert manifest["benchmark_revision"] == MDBENCH_REVISION
    assert manifest["base_image_digest"] in dockerfile
    assert manifest["processed_archive"]["checksum"] == MDBENCH_PROCESSED_CHECKSUM
    requirements = (container_dir / "requirements-sindy.lock").read_text(
        encoding="utf-8"
    )
    assert all("==" in line for line in requirements.splitlines() if line.strip())
