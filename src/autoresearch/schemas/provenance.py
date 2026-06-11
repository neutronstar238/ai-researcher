"""Helpers for run identity, stable hashes, and artifact references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel


def generate_run_id(prefix: str = "run") -> str:
    """Create a unique run identifier with a stable prefix."""

    return f"{prefix}_{uuid4().hex}"


def config_hash(config: BaseModel | dict[str, Any]) -> str:
    """Hash a configuration model or mapping using canonical JSON."""

    return _sha256_text(_canonical_json(config))


def data_hash(data: bytes | str | dict[str, Any] | BaseModel) -> str:
    """Hash inline data, text, mappings, or Pydantic models."""

    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    if isinstance(data, str):
        return _sha256_text(data)
    return _sha256_text(_canonical_json(data))


def file_hash(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it fully into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_uri(run_id: str, relative_path: str | Path) -> str:
    """Build a normalized local artifact URI for a run output."""

    path = Path(relative_path).as_posix().lstrip("/")
    return f"runs/{run_id}/artifacts/{path}"


def _canonical_json(data: BaseModel | dict[str, Any]) -> str:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
