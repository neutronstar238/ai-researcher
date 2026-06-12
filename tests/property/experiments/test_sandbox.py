from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autoresearch.experiments import SandboxAccessMode, SandboxPathPolicy

SAFE_NAMES = st.from_regex(r"[a-z][a-z0-9_-]{0,16}", fullmatch=True)


@given(filename=SAFE_NAMES)
def test_sandbox_allows_experiment_directory_access(filename: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        experiment_dir = tmp_path / "experiments" / "task-1"
        experiment_dir.mkdir(parents=True)
        policy = SandboxPathPolicy(experiment_dir)

        resolved = policy.require_access(
            Path("artifacts") / f"{filename}.json",
            SandboxAccessMode.WRITE,
        )

        assert resolved == experiment_dir / "artifacts" / f"{filename}.json"


@given(filename=SAFE_NAMES)
def test_sandbox_blocks_relative_traversal_outside_experiment(filename: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        experiment_dir = tmp_path / "experiments" / "task-1"
        experiment_dir.mkdir(parents=True)
        policy = SandboxPathPolicy(experiment_dir)

        with pytest.raises(PermissionError):
            policy.require_access(Path("..") / f"{filename}.txt")


@given(filename=SAFE_NAMES)
def test_sandbox_blocks_absolute_paths_outside_allowlist(filename: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        experiment_dir = tmp_path / "experiments" / "task-1"
        outside_dir = tmp_path / "outside"
        experiment_dir.mkdir(parents=True)
        outside_dir.mkdir()
        policy = SandboxPathPolicy(experiment_dir)

        with pytest.raises(PermissionError):
            policy.require_access(outside_dir / f"{filename}.txt")


@settings(deadline=None)
@given(filename=SAFE_NAMES)
def test_sandbox_allows_configured_cache_and_output_dirs(filename: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        experiment_dir = tmp_path / "experiments" / "task-1"
        cache_dir = tmp_path / "cache"
        output_dir = tmp_path / "outputs"
        experiment_dir.mkdir(parents=True)
        cache_dir.mkdir()
        output_dir.mkdir()
        policy = SandboxPathPolicy(
            experiment_dir,
            cache_dirs=[cache_dir],
            output_dirs=[output_dir],
        )

        assert policy.can_access(cache_dir / f"{filename}.cache")
        assert policy.can_access(output_dir / f"{filename}.json", SandboxAccessMode.WRITE)


def test_sandbox_blocks_project_root_secret() -> None:
    with TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        experiment_dir = project_root / "experiments" / "task-1"
        experiment_dir.mkdir(parents=True)
        secret_path = project_root / ".env"
        policy = SandboxPathPolicy(experiment_dir, project_root=project_root)

        decision = policy.check_access(secret_path)

        assert not decision.allowed
        assert decision.reason == "project or user-home secret paths are blocked"


def test_sandbox_blocks_user_home_secret_even_when_home_is_not_project_root() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        experiment_dir = tmp_path / "project" / "experiments" / "task-1"
        fake_home = tmp_path / "home"
        experiment_dir.mkdir(parents=True)
        fake_home.mkdir()
        policy = SandboxPathPolicy(experiment_dir, home_dir=fake_home)

        decision = policy.check_access(fake_home / ".ssh" / "id_rsa")

        assert not decision.allowed
        assert decision.reason == "project or user-home secret paths are blocked"


def test_sandbox_rejects_unsafe_allowed_roots() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        experiment_dir = tmp_path / "experiments" / "task-1"
        fake_home = tmp_path / "home"
        experiment_dir.mkdir(parents=True)
        fake_home.mkdir()

        with pytest.raises(ValueError):
            SandboxPathPolicy(experiment_dir, cache_dirs=[fake_home], home_dir=fake_home)
