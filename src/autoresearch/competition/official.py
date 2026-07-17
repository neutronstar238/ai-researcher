"""Live preflight for the pinned official MDBench source and dataset.

Public access to an archive is not treated as a data license. The preflight
writes a stable ``AccessRequest`` and refuses to download when Zenodo does not
publish an explicit rights identifier.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from autoresearch.competition.manifest import write_json_model
from autoresearch.competition.models import (
    AccessKind,
    AccessRequest,
    MDBenchDatasetFile,
    MDBenchOfficialPreflight,
)
from autoresearch.competition.planning import MDBENCH_REVISION, MDBENCH_SOURCE

MDBENCH_DATASET_DOI = "10.5281/zenodo.17611099"
MDBENCH_DATASET_RECORD_ID = 17611099
MDBENCH_ZENODO_API = f"https://zenodo.org/api/records/{MDBENCH_DATASET_RECORD_ID}"
MDBENCH_GITHUB_API = "https://api.github.com/repos/gryaklab/mdbench"
MDBENCH_LICENSE_URL = (
    "https://raw.githubusercontent.com/gryaklab/mdbench/"
    f"{MDBENCH_REVISION}/LICENSE"
)
MDBENCH_PROCESSED_KEY = "processed.zip"
MDBENCH_PROCESSED_SIZE = 475_908_142
MDBENCH_PROCESSED_CHECKSUM = "md5:9fe483c64ad6e67a07153b00a4665d26"

JsonFetcher = Callable[[str], Mapping[str, Any]]
TextFetcher = Callable[[str], str]
ContainerProbe = Callable[[], tuple[bool, str | None, str | None]]


def run_mdbench_official_preflight(
    output_dir: Path | str,
    *,
    timeout_seconds: int = 20,
    json_fetcher: JsonFetcher | None = None,
    text_fetcher: TextFetcher | None = None,
    container_probe: ContainerProbe | None = None,
) -> MDBenchOfficialPreflight:
    """Inspect official sources and emit only minimal access requests when blocked."""

    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fetch_json = json_fetcher or (
        lambda url: _fetch_json(url, timeout_seconds=timeout_seconds)
    )
    fetch_text = text_fetcher or (
        lambda url: _fetch_text(url, timeout_seconds=timeout_seconds)
    )
    probe_container = container_probe or (
        lambda: _probe_container(timeout_seconds=timeout_seconds)
    )
    blockers: list[str] = []

    resolved_revision: str | None = None
    head_revision: str | None = None
    try:
        resolved_revision = str(
            fetch_json(f"{MDBENCH_GITHUB_API}/commits/{MDBENCH_REVISION}").get("sha")
            or ""
        ) or None
        head_revision = str(
            fetch_json(f"{MDBENCH_GITHUB_API}/commits/main").get("sha") or ""
        ) or None
    except Exception as exc:
        blockers.append(
            f"official repository metadata unavailable: {type(exc).__name__}: {exc}"
        )
    revision_available = resolved_revision == MDBENCH_REVISION
    if not revision_available:
        blockers.append("pinned MDBench revision is not verifiably available")

    code_license: str | None = None
    try:
        first_line = fetch_text(MDBENCH_LICENSE_URL).splitlines()[0].strip()
        code_license = first_line or None
    except Exception as exc:
        blockers.append(f"code license unavailable: {type(exc).__name__}: {exc}")
    if code_license != "MIT License":
        blockers.append("pinned MDBench code license did not resolve to MIT License")

    record: Mapping[str, Any] = {}
    record_available = False
    try:
        record = fetch_json(MDBENCH_ZENODO_API)
        record_available = True
    except Exception as exc:
        blockers.append(f"Zenodo dataset metadata unavailable: {type(exc).__name__}: {exc}")
    metadata = _mapping(record.get("metadata"))
    access = _mapping(record.get("access"))
    dataset_license = _license_identifier(metadata.get("rights")) or _license_identifier(
        metadata.get("license")
    )
    if record_available and dataset_license is None:
        blockers.append(
            "Zenodo record is publicly accessible but has no explicit dataset rights/license"
        )

    processed_file = _processed_file(record)
    processed_metadata_matches = bool(
        processed_file is not None
        and processed_file.size_bytes == MDBENCH_PROCESSED_SIZE
        and processed_file.checksum == MDBENCH_PROCESSED_CHECKSUM
    )
    if not processed_metadata_matches:
        blockers.append("processed.zip size/checksum metadata does not match the pinned contract")

    container_available, container_runtime, container_error = probe_container()
    if not container_available:
        blockers.append(
            "versioned container runtime unavailable"
            + (f": {container_error}" if container_error else "")
        )

    access_requests: list[AccessRequest] = []
    if record_available and dataset_license is None:
        access_requests.append(
            AccessRequest(
                request_id="access_mdbench_dataset_license_17611099",
                run_id="mdbench-official-preflight",
                kind=AccessKind.DATA_LICENSE,
                reason=(
                    "Zenodo record 17611099 exposes public files but its rights/license "
                    "metadata is empty; public access is not sufficient for the license gate."
                ),
                minimum_scope=(
                    "An explicit dataset license identifier or written authorization covering "
                    "processed.zip for benchmark research and competition artifacts."
                ),
            )
        )
    if not container_available:
        access_requests.append(
            AccessRequest(
                request_id="access_mdbench_container_runtime",
                run_id="mdbench-official-preflight",
                kind=AccessKind.CONTAINER_RUNTIME,
                reason=(
                    "The pinned scientific environment cannot execute without a container "
                    "daemon."
                ),
                minimum_scope="Permission to start and use the local Docker Linux engine.",
            )
        )
    for request in access_requests:
        write_json_model(
            root / "access-requests" / f"{request.request_id}.json",
            request,
        )

    ready_to_download = bool(
        revision_available
        and code_license == "MIT License"
        and dataset_license is not None
        and processed_metadata_matches
    )
    output_path = root / "official-preflight.json"
    report = MDBenchOfficialPreflight(
        repository_url=MDBENCH_SOURCE,
        expected_revision=MDBENCH_REVISION,
        resolved_revision=resolved_revision,
        head_revision=head_revision,
        revision_available=revision_available,
        head_matches_pin=head_revision == MDBENCH_REVISION,
        code_license=code_license,
        dataset_doi=MDBENCH_DATASET_DOI,
        dataset_record_id=MDBENCH_DATASET_RECORD_ID,
        dataset_access_right=str(access.get("right") or "") or None,
        dataset_license=dataset_license,
        processed_file=processed_file,
        processed_metadata_matches=processed_metadata_matches,
        container_runtime=container_runtime,
        container_available=container_available,
        ready_to_download=ready_to_download,
        ready_to_execute=ready_to_download and container_available,
        blockers=tuple(dict.fromkeys(blockers)),
        access_request_ids=tuple(request.request_id for request in access_requests),
        output_path=output_path.as_posix(),
    )
    write_json_model(output_path, report)
    return report


def _fetch_json(url: str, *, timeout_seconds: int) -> Mapping[str, Any]:
    payload = _fetch_bytes(url, timeout_seconds=timeout_seconds)
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"expected JSON object from {url}")
    return decoded


def _fetch_text(url: str, *, timeout_seconds: int) -> str:
    return _fetch_bytes(url, timeout_seconds=timeout_seconds).decode("utf-8")


def _fetch_bytes(url: str, *, timeout_seconds: int) -> bytes:
    request = Request(url, headers={"User-Agent": "AIResearch-MDBench-Preflight/1.0"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = response.read()
    if not isinstance(payload, bytes):
        raise TypeError(f"expected bytes response from {url}")
    return payload


def _probe_container(*, timeout_seconds: int) -> tuple[bool, str | None, str | None]:
    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    runtime = completed.stdout.strip() or None
    error = completed.stderr.strip() or None
    return completed.returncode == 0 and runtime is not None, runtime, error


def _processed_file(record: Mapping[str, Any]) -> MDBenchDatasetFile | None:
    raw_files = record.get("files")
    if not isinstance(raw_files, list):
        return None
    for raw_file in raw_files:
        file_data = _mapping(raw_file)
        if file_data.get("key") != MDBENCH_PROCESSED_KEY:
            continue
        links = _mapping(file_data.get("links"))
        content_url = str(links.get("self") or links.get("content") or "")
        raw_size = file_data.get("size")
        if not isinstance(raw_size, (int, str)) or isinstance(raw_size, bool):
            return None
        try:
            size_bytes = int(raw_size)
        except ValueError:
            return None
        return MDBenchDatasetFile(
            key=MDBENCH_PROCESSED_KEY,
            size_bytes=size_bytes,
            checksum=str(file_data.get("checksum") or ""),
            content_url=content_url,
        )
    return None


def _license_identifier(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("id", "identifier", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None
    if isinstance(value, list):
        identifiers = [
            identifier
            for item in value
            if (identifier := _license_identifier(item))
        ]
        return ",".join(identifiers) if identifiers else None
    return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}
