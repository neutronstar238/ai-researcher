from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.config import SystemConfig
from autoresearch.config.models import (
    ComputeConfig,
    LiteratureConfig,
    MessagingChannelConfig,
    ModelProviderConfig,
)


def test_system_config_defaults_are_local_first() -> None:
    config = SystemConfig()

    assert config.project_root == Path(".")
    assert config.knowledge_base.vault_path == Path("autoresearch-vault")
    assert config.compute.prefer_local is True
    assert config.compute.sandbox_enabled is True
    assert "export.arxiv.org" in config.compute.allowed_network_domains
    assert "api.openalex.org" in config.compute.allowed_network_domains
    assert config.literature.databases == ["arxiv", "openalex"]
    assert config.deployment.llm.provider == "openai-compatible"
    assert config.deployment.llm.api_key_env == "AUTORESEARCH_LLM_API_KEY"
    assert config.deployment.slash_commands_dir == Path(".airesearcher/commands")


def test_config_models_validate_basic_bounds() -> None:
    with pytest.raises(ValidationError):
        ComputeConfig(max_memory_mb=64)

    with pytest.raises(ValidationError):
        LiteratureConfig(max_results_per_source=0)

    with pytest.raises(ValidationError):
        ModelProviderConfig(model_name="")


def test_deployment_channel_config_keeps_secrets_in_env_references() -> None:
    channel = MessagingChannelConfig(
        enabled=True,
        connection_mode="websocket",
        webhook_url_env="AUTORESEARCH_FEISHU_WEBHOOK_URL",
        app_secret_env="AUTORESEARCH_FEISHU_APP_SECRET",
        home_chat_id_env="AUTORESEARCH_FEISHU_HOME_CHAT_ID",
    )

    assert channel.enabled is True
    assert channel.connection_mode == "websocket"
    assert channel.webhook_url_env == "AUTORESEARCH_FEISHU_WEBHOOK_URL"
    assert channel.app_secret_env == "AUTORESEARCH_FEISHU_APP_SECRET"
    assert channel.home_chat_id_env == "AUTORESEARCH_FEISHU_HOME_CHAT_ID"
