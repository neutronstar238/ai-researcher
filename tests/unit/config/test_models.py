from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.config import SystemConfig
from autoresearch.config.models import ComputeConfig, LiteratureConfig


def test_system_config_defaults_are_local_first() -> None:
    config = SystemConfig()

    assert config.project_root == Path(".")
    assert config.knowledge_base.vault_path == Path("autoresearch-vault")
    assert config.compute.prefer_local is True
    assert config.compute.sandbox_enabled is True
    assert config.literature.databases == ["arxiv", "semantic_scholar"]


def test_config_models_validate_basic_bounds() -> None:
    with pytest.raises(ValidationError):
        ComputeConfig(max_memory_mb=64)

    with pytest.raises(ValidationError):
        LiteratureConfig(max_results_per_source=0)
