"""Pydantic configuration models for the AutoResearch local-first runtime."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Agent runtime limits used before the full multi-agent system exists."""

    max_loop_depth: int = Field(default=8, ge=1)
    max_parallel_agents: int = Field(default=4, ge=1)
    default_task_timeout_seconds: int = Field(default=1800, ge=1)
    require_human_approval_for_high_risk: bool = True


class ComputeConfig(BaseModel):
    """Local-first compute and sandbox defaults for MVP experiments."""

    prefer_local: bool = True
    sandbox_enabled: bool = True
    sandbox_root: Path = Path("runs")
    max_cpu_seconds: int = Field(default=3600, ge=1)
    max_memory_mb: int = Field(default=4096, ge=128)
    max_gpu_hours: float = Field(default=0.0, ge=0.0)
    ssh_config_path: Path = Path("~/.ssh/config")
    allowed_network_domains: list[str] = Field(
        default_factory=lambda: [
            "arxiv.org",
            "api.semanticscholar.org",
            "pypi.org",
            "files.pythonhosted.org",
        ]
    )


class KnowledgeBaseConfig(BaseModel):
    """Obsidian-compatible knowledge vault settings."""

    vault_path: Path = Path("autoresearch-vault")
    exploration_zone: str = "exploration"
    project_zone: str = "projects"
    topic_index_path: Path = Path("exploration/index.md")
    backup_interval_hours: int = Field(default=24, ge=1, le=26)
    clustering_threshold: int = Field(default=1000, ge=1)
    preserve_version_history: bool = True


class LiteratureConfig(BaseModel):
    """Literature retrieval defaults for the trusted-loop MVP."""

    databases: list[str] = Field(default_factory=lambda: ["arxiv", "semantic_scholar"])
    max_results_per_source: int = Field(default=20, ge=1)
    request_timeout_seconds: int = Field(default=30, ge=1)
    cache_ttl_hours: int = Field(default=24, ge=1)
    rate_limit_seconds: float = Field(default=1.0, ge=0.0)


class SystemConfig(BaseModel):
    """Top-level configuration for a local AutoResearch installation."""

    project_root: Path = Path(".")
    log_level: str = "INFO"
    run_id_prefix: str = "run"
    max_cost_per_run_usd: float = Field(default=10.0, ge=0.0)
    max_tokens_per_run: int = Field(default=100_000, ge=0)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    compute: ComputeConfig = Field(default_factory=ComputeConfig)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
    literature: LiteratureConfig = Field(default_factory=LiteratureConfig)
