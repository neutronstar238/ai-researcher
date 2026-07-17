"""Verified download, safe extraction, and inventory for official MDBench data."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile, ZipInfo

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchDatasetArtifact,
    MDBenchOfficialPreflight,
)
from autoresearch.competition.official import (
    MDBENCH_DATASET_DOI,
    MDBENCH_PROCESSED_CHECKSUM,
    MDBENCH_PROCESSED_SIZE,
)
from autoresearch.competition.planning import MDBENCH_REVISION, MDBENCH_SOURCE

_BUFFER_SIZE = 1024 * 1024
_MANIFEST_NAME = "archive-manifest.json"

class ReadableResponse(Protocol):
    """Small urllib response surface used by the resumable downloader."""

    status: int | None

    def __enter__(self) -> ReadableResponse: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def read(self, size: int = -1) -> bytes: ...

    def getcode(self) -> int: ...


UrlOpener = Callable[..., ReadableResponse]


class MDBenchDataError(RuntimeError):
    """Raised when official data cannot satisfy the immutable archive contract."""


def download_mdbench_processed_archive(
    destination: Path | str,
    preflight: MDBenchOfficialPreflight,
    *,
    timeout_seconds: int = 60,
    max_attempts: int = 5,
    opener: UrlOpener | None = None,
) -> Path:
    """Resume the official archive download only after the live license gate passes."""

    if not preflight.ready_to_download or preflight.processed_file is None:
        raise MDBenchDataError("official preflight has not authorized dataset download")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == preflight.processed_file.size_bytes:
        return target

    open_url = opener or urlopen
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        offset = target.stat().st_size if target.is_file() else 0
        headers = {"User-Agent": "AIResearch-MDBench-Downloader/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = Request(preflight.processed_file.content_url, headers=headers)
        try:
            with open_url(request, timeout=timeout_seconds) as response:
                raw_status = getattr(response, "status", None)
                status = int(raw_status if raw_status is not None else response.getcode())
                append = offset > 0 and status == 206
                mode = "ab" if append else "wb"
                with target.open(mode) as output:
                    shutil.copyfileobj(response, output, length=_BUFFER_SIZE)
            if target.stat().st_size == preflight.processed_file.size_bytes:
                return target
            last_error = MDBenchDataError(
                "downloaded archive size does not match live metadata: "
                f"{target.stat().st_size} != {preflight.processed_file.size_bytes}"
            )
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            last_error = exc
        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 8))
    raise MDBenchDataError(
        f"official archive download failed after {max_attempts} attempts: {last_error}"
    )


def prepare_mdbench_official_data(
    archive_path: Path | str,
    output_dir: Path | str,
    *,
    dataset_license: str,
    expected_size: int = MDBENCH_PROCESSED_SIZE,
    expected_checksum: str = MDBENCH_PROCESSED_CHECKSUM,
) -> MDBenchArchiveManifest:
    """Verify, safely extract, hash, and inventory an official processed archive."""

    archive = Path(archive_path).resolve()
    if not archive.is_file():
        raise MDBenchDataError(f"archive does not exist: {archive}")
    expected_md5 = _checksum_digest(expected_checksum, algorithm="md5")
    archive_size = archive.stat().st_size
    if archive_size != expected_size:
        raise MDBenchDataError(
            f"archive size mismatch: expected {expected_size}, got {archive_size}"
        )
    actual_md5, archive_sha256 = _hash_file_pair(archive)
    if actual_md5 != expected_md5:
        raise MDBenchDataError(
            f"archive md5 mismatch: expected {expected_md5}, got {actual_md5}"
        )

    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    extracted_root = root / f"processed-{actual_md5[:12]}"
    output_path = root / _MANIFEST_NAME
    if output_path.is_file() and extracted_root.is_dir():
        existing = MDBenchArchiveManifest.model_validate_json(
            output_path.read_text(encoding="utf-8")
        )
        if (
            existing.archive_md5 == actual_md5
            and existing.archive_sha256 == archive_sha256
            and existing.extracted_root == extracted_root.as_posix()
        ):
            _verify_inventory(extracted_root, existing.artifacts)
            return existing

    if extracted_root.exists():
        raise MDBenchDataError(
            "deterministic extraction target already exists without a reusable manifest: "
            f"{extracted_root}"
        )
    try:
        with tempfile.TemporaryDirectory(prefix=".mdbench-extract-", dir=root) as temp_dir:
            staged_root = Path(temp_dir) / extracted_root.name
            with ZipFile(archive) as bundle:
                members = bundle.infolist()
                _validate_zip_members(members)
                bundle.extractall(staged_root)
            staged_root.replace(extracted_root)
    except BadZipFile as exc:
        raise MDBenchDataError(f"invalid MDBench zip archive: {exc}") from exc

    artifacts = _inventory_npz_files(extracted_root)
    if not artifacts:
        raise MDBenchDataError("official archive contains no recognized ODE/PDE NPZ files")
    ode_systems = tuple(
        sorted({item.system_name for item in artifacts if item.data_type == "ode"})
    )
    pde_systems = tuple(
        sorted({item.system_name for item in artifacts if item.data_type == "pde"})
    )
    noise_conditions = tuple(
        sorted({item.condition for item in artifacts if item.condition != "clean"})
    )
    inventory_hash = canonical_model_hash(
        {
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "archive_sha256": archive_sha256,
        }
    )
    manifest = MDBenchArchiveManifest(
        repository_url=MDBENCH_SOURCE,
        benchmark_revision=MDBENCH_REVISION,
        dataset_doi=MDBENCH_DATASET_DOI,
        dataset_license=dataset_license,
        archive_path=archive.as_posix(),
        archive_size_bytes=archive_size,
        archive_md5=actual_md5,
        archive_sha256=archive_sha256,
        extracted_root=extracted_root.as_posix(),
        artifacts=artifacts,
        ode_systems=ode_systems,
        pde_systems=pde_systems,
        noise_conditions=noise_conditions,
        inventory_hash=inventory_hash,
        output_path=output_path.as_posix(),
    )
    write_json_model(output_path, manifest)
    return manifest


def _checksum_digest(checksum: str, *, algorithm: str) -> str:
    prefix = f"{algorithm}:"
    if not checksum.startswith(prefix):
        raise MDBenchDataError(f"expected {prefix} checksum, got {checksum}")
    return checksum.removeprefix(prefix).casefold()


def _hash_file_pair(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_BUFFER_SIZE):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_zip_members(members: list[ZipInfo]) -> None:
    for member in members:
        if "\\" in member.filename:
            raise MDBenchDataError(f"unsafe archive member path: {member.filename}")
        relative = PurePosixPath(member.filename)
        first_part = relative.parts[0] if relative.parts else ""
        if relative.is_absolute() or ".." in relative.parts or ":" in first_part:
            raise MDBenchDataError(f"unsafe archive member path: {member.filename}")
        unix_mode = member.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise MDBenchDataError(f"symbolic links are not allowed: {member.filename}")


def _inventory_npz_files(root: Path) -> tuple[MDBenchDatasetArtifact, ...]:
    artifacts: list[MDBenchDatasetArtifact] = []
    for path in sorted(root.rglob("*.npz")):
        relative = path.relative_to(root)
        data_type = _infer_data_type(relative)
        if data_type is None:
            continue
        system_name, condition = _system_and_condition(path.stem)
        artifacts.append(
            MDBenchDatasetArtifact(
                relative_path=relative.as_posix(),
                data_type=data_type,
                system_name=system_name,
                condition=condition,
                size_bytes=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    return tuple(artifacts)


def _infer_data_type(path: Path) -> Literal["ode", "pde"] | None:
    parts = {part.casefold() for part in path.parts}
    if "ode" in parts:
        return "ode"
    if "pde" in parts:
        return "pde"
    return None


def _system_and_condition(stem: str) -> tuple[str, str]:
    marker = "_snr_"
    if marker not in stem:
        return stem, "clean"
    system_name, snr = stem.rsplit(marker, maxsplit=1)
    return system_name, f"snr_{snr}"


def _verify_inventory(
    extracted_root: Path,
    artifacts: tuple[MDBenchDatasetArtifact, ...],
) -> None:
    for artifact in artifacts:
        path = extracted_root / Path(artifact.relative_path)
        if not path.is_file():
            raise MDBenchDataError(f"manifest artifact is missing: {path}")
        if path.stat().st_size != artifact.size_bytes:
            raise MDBenchDataError(f"manifest artifact size changed: {path}")
        if _sha256_file(path) != artifact.sha256:
            raise MDBenchDataError(f"manifest artifact hash changed: {path}")


def manifest_as_canonical_json(manifest: MDBenchArchiveManifest) -> str:
    """Expose deterministic JSON for downstream container manifests and tests."""

    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
