"""Local sandbox path restrictions for experiment execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SandboxAccessMode(str, Enum):
    """Filesystem access mode checked by the sandbox policy."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class SandboxPathDecision:
    """Decision returned by the sandbox path policy."""

    allowed: bool
    mode: SandboxAccessMode
    requested_path: str
    resolved_path: Path
    reason: str | None = None


class SandboxPathPolicy:
    """Allow experiment I/O only inside explicitly configured roots."""

    def __init__(
        self,
        experiment_dir: Path | str,
        *,
        cache_dirs: list[Path | str] | None = None,
        output_dirs: list[Path | str] | None = None,
        project_root: Path | str | None = None,
        home_dir: Path | str | None = None,
    ) -> None:
        self.experiment_dir = _resolve_root(experiment_dir)
        self.cache_dirs = tuple(_resolve_root(path) for path in cache_dirs or [])
        self.output_dirs = tuple(_resolve_root(path) for path in output_dirs or [])
        self.allowed_roots = (self.experiment_dir, *self.cache_dirs, *self.output_dirs)
        self.project_root = _resolve_root(project_root) if project_root is not None else None
        self.home_dir = _resolve_root(home_dir) if home_dir is not None else Path.home().resolve()
        self._reject_unsafe_allowed_roots()

    def check_access(
        self,
        path: Path | str,
        mode: SandboxAccessMode = SandboxAccessMode.READ,
    ) -> SandboxPathDecision:
        """Check whether a path is allowed in sandbox mode."""

        requested = Path(path)
        target = _resolve_target(requested, self.experiment_dir)

        if not _is_relative_to_any(target, self.allowed_roots):
            reason = "path is outside experiment, cache, and output directories"
            if _is_secret_path(target, self.project_root, self.home_dir):
                reason = "project or user-home secret paths are blocked"
            return SandboxPathDecision(
                allowed=False,
                mode=mode,
                requested_path=requested.as_posix(),
                resolved_path=target,
                reason=reason,
            )

        return SandboxPathDecision(
            allowed=True,
            mode=mode,
            requested_path=requested.as_posix(),
            resolved_path=target,
        )

    def can_access(
        self,
        path: Path | str,
        mode: SandboxAccessMode = SandboxAccessMode.READ,
    ) -> bool:
        """Return whether sandbox access is allowed."""

        return self.check_access(path, mode).allowed

    def require_access(
        self,
        path: Path | str,
        mode: SandboxAccessMode = SandboxAccessMode.READ,
    ) -> Path:
        """Return the resolved path or raise an access-denied error."""

        decision = self.check_access(path, mode)
        if not decision.allowed:
            msg = (
                f"sandbox denied {mode.value} access to "
                f"{decision.requested_path}: {decision.reason}"
            )
            raise PermissionError(msg)
        return decision.resolved_path

    def _reject_unsafe_allowed_roots(self) -> None:
        for root in self.allowed_roots:
            if root == self.home_dir:
                msg = "sandbox allowed root cannot be the user home directory"
                raise ValueError(msg)
            if self.project_root is not None and root == self.project_root:
                msg = "sandbox allowed root cannot be the project root"
                raise ValueError(msg)
            if _looks_secret_like(root):
                msg = f"sandbox allowed root cannot be secret-like: {root}"
                raise ValueError(msg)


SECRET_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
SECRET_MARKERS = ("api_key", "apikey", "credential", "secret", "token")


def _resolve_root(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _resolve_target(path: Path, experiment_dir: Path) -> Path:
    if path.is_absolute():
        return path.expanduser().resolve()
    return (experiment_dir / path).expanduser().resolve()


def _is_relative_to_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except ValueError:
        return False


def _is_secret_path(
    path: Path,
    project_root: Path | None,
    home_dir: Path,
) -> bool:
    if not _looks_secret_like(path):
        return False
    if project_root is not None and _is_relative_to(path, project_root):
        return True
    return _is_relative_to(path, home_dir)


def _looks_secret_like(path: Path) -> bool:
    lowered_parts = [part.casefold() for part in path.parts]
    if any(part in SECRET_FILENAMES for part in lowered_parts):
        return True
    return any(marker in part for marker in SECRET_MARKERS for part in lowered_parts)
