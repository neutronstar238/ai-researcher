"""Minimal Typer CLI for the AI-Researcher Phase 0 scaffold."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from dotenv import load_dotenv

from autoresearch import __version__
from autoresearch.agents import (
    DEFAULT_AGENT_PROFILE_SET_REQUIRED_STAGES,
    DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS,
    AgentProfile,
    AgentThinkingMode,
    McpInvocationStatus,
    append_mcp_invocation_evidence,
    build_agent_profile_from_bundle,
    build_mcp_invocation_evidence,
    evaluate_agent_profile_readiness,
    evaluate_agent_profile_set,
    load_agent_profile,
    load_agent_profile_bundle,
    load_mcp_invocation_evidence,
    parse_mcp_approval_policy_specs,
    parse_mcp_env_key_specs,
    parse_mcp_spec,
    parse_server_tool_specs,
    parse_skill_policy_specs,
    parse_skill_spec,
    profile_contexts_by_stage,
    validate_mcp_invocation_evidence,
    write_agent_profile,
    write_agent_profile_note,
    write_mcp_invocation_validation_report,
)
from autoresearch.config import (
    ConfigFormat,
    ConfigParser,
    DeploymentConfig,
    MessagingChannelConfig,
    ModelProviderConfig,
    SystemConfig,
)
from autoresearch.experiments import (
    build_closed_loop_campaign,
    create_loop_iteration_from_cycle_summary,
    run_scientistbench_demo,
    select_loop_candidate,
    write_loop_report_artifact,
)
from autoresearch.inspiration import (
    InspirationItem,
    InspirationRefreshConfig,
    InspirationRefreshReport,
    run_inspiration_refresh,
)
from autoresearch.integrations import (
    CCSwitchCodeAgentBackend,
    OpenClawChannelPlugin,
    OpenCodeCodeAgentBackend,
    ScanSciPdfIntegration,
    get_ccswitch_code_agent_backend,
    get_openclaw_channel_plugin,
    get_opencode_code_agent_backend,
    get_scansci_pdf_integration,
    iter_ccswitch_code_agent_backends,
    iter_openclaw_channel_plugins,
    iter_opencode_code_agent_backends,
    iter_scansci_pdf_integrations,
    write_ccswitch_code_agent_manifest,
    write_channel_adapter_manifest,
    write_openclaw_channel_manifest,
    write_opencode_code_agent_manifest,
    write_scansci_pdf_manifest,
)
from autoresearch.knowledge import (
    AgentRole,
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    audit_skill_polish_candidate,
    create_obsidian_vault_assets,
    create_skill_evolution_candidate,
    default_external_research_skill_candidates,
    write_external_skill_watchlist,
)
from autoresearch.literature import (
    OPTIONAL_LITERATURE_SOURCES,
    ArxivClient,
    LiteratureRefreshConfig,
    LiteratureSearchClient,
    OpenAlexClient,
    SemanticScholarClient,
    SourceCircuitStateLockError,
    run_daily_literature_refresh,
    semantic_scholar_enabled,
)
from autoresearch.llm import (
    LLMClientError,
    run_llm_evidence_review,
    run_llm_smoke_test,
    write_llm_review_issue_notes,
    write_llm_review_note,
)
from autoresearch.notifications import NotificationSendRecord, send_inspiration_digest
from autoresearch.observability import diagnose_requests_dependency_set
from autoresearch.process import windows_no_window_kwargs
from autoresearch.reports import (
    EvidenceGateVerdict,
    LatexPaperBuildStatus,
    audit_publication_quality,
    audit_publication_stability,
    build_latex_paper_from_markdown,
    compose_publication_manuscript,
    generate_bibtex,
    inspect_related_work,
    run_evidence_gate,
    validate_reproducibility_package,
)
from autoresearch.research import (
    SimilarityCheckConfig,
    audit_research_plan,
    generate_research_plan,
    link_similarity_report_to_project,
    run_project_similarity_check,
)
from autoresearch.runtime import (
    DEFAULT_HEARTBEAT_STALE_AFTER_SECONDS,
    DEFAULT_HEARTBEAT_STALL_REPETITIONS,
    AgentSession,
    AgentSessionError,
    RuntimeActionRisk,
    RuntimeApprovalDecision,
    RuntimeApprovalError,
    RuntimeHeartbeatReport,
    RuntimePermissionMode,
    approve_runtime_request,
    claim_agent_session,
    ensure_runtime_approval,
    evaluate_runtime_heartbeats,
    list_agent_sessions,
    list_runtime_approval_requests,
    network_approval_metadata_from_decision,
    release_agent_session,
    write_runtime_heartbeat,
    write_runtime_heartbeat_report,
)
from autoresearch.scheduler import queued_issue_followups_from_vault
from autoresearch.schemas import CandidateStatus, ResearchCandidate, ResearchPlan, ValidationStatus

app = typer.Typer(
    help="AI-Researcher command line interface.",
    no_args_is_help=True,
)
agents_app = typer.Typer(help="Manage runtime agent profiles and capabilities.")
agent_profiles_app = typer.Typer(help="Bind custom skills and MCP servers to one agent.")
agent_mcp_evidence_app = typer.Typer(help="Record and validate MCP tool invocation evidence.")
slash_app = typer.Typer(help="Manage project slash command templates.")
scheduler_state_app = typer.Typer(help="Manage local scheduler state records.")
runtime_app = typer.Typer(help="Manage always-on runtime approvals.")
runtime_heartbeat_app = typer.Typer(help="Record and check long-running loop heartbeats.")
sessions_app = typer.Typer(help="Coordinate concurrent agent file claims.")
channels_app = typer.Typer(help="Manage communication channel integration manifests.")
channel_adapters_app = typer.Typer(help="Manage optional messaging channel adapter runbooks.")
openclaw_channels_app = typer.Typer(help="Manage optional upstream OpenClaw plugin runbooks.")
code_agents_app = typer.Typer(help="Manage external code-agent integration manifests.")
ccswitch_code_agents_app = typer.Typer(help="Manage cc-switch / Claude Code backend manifests.")
opencode_code_agents_app = typer.Typer(help="Manage OpenCode direct backend manifests.")
pdf_sources_app = typer.Typer(help="Manage optional PDF retrieval integration manifests.")
scansci_pdf_app = typer.Typer(help="Manage ScanSci PDF source metadata.")
app.add_typer(agents_app, name="agents")
app.add_typer(slash_app, name="slash-commands")
app.add_typer(scheduler_state_app, name="scheduler-state")
app.add_typer(runtime_app, name="runtime")
app.add_typer(sessions_app, name="sessions")
app.add_typer(channels_app, name="channels")
app.add_typer(code_agents_app, name="code-agents")
app.add_typer(pdf_sources_app, name="pdf-sources")
channels_app.add_typer(channel_adapters_app, name="adapters")
channels_app.add_typer(openclaw_channels_app, name="openclaw")
code_agents_app.add_typer(ccswitch_code_agents_app, name="cc-switch")
code_agents_app.add_typer(opencode_code_agents_app, name="opencode")
pdf_sources_app.add_typer(scansci_pdf_app, name="scansci-pdf")
runtime_app.add_typer(runtime_heartbeat_app, name="heartbeat")
agents_app.add_typer(agent_profiles_app, name="profile")
agents_app.add_typer(agent_mcp_evidence_app, name="mcp-evidence")

DEFAULT_SCHEDULER_STATE_PATH = Path(".airesearcher/scheduler-state.json")
DEFAULT_RUNTIME_APPROVALS_PATH = Path(".airesearcher/runtime-approvals.json")
DEFAULT_RUNTIME_HEARTBEATS_PATH = Path(".airesearcher/runtime-heartbeats.json")
DEFAULT_AGENT_SESSIONS_PATH = Path(".airesearcher/agent-sessions.json")
PUBLICATION_SEARCH_QUERIES = 4
PUBLICATION_RESULTS_PER_SOURCE = 10
DEFAULT_RESEARCH_DEMO = "pendigits_variance_calibrated_prototypes"
METHOD_ALIGNED_SEED_NOT_FOUND_REF = "literature_refresh:method_aligned_seed_not_found"
AGENT_PROFILE_ASSIGNABLE_STAGES = (
    "source",
    "literature",
    "similarity",
    "research_plan",
    "loop_campaign",
    "inspiration",
    "experiment",
    "reproduction",
    "citations",
    "related_work",
    "paper_manuscript",
    "paper_build",
    "review",
    "publication_audit",
    "evidence_gate",
    "followups",
    "deliverables",
)
SERVE_NETWORK_APPROVED_DOMAINS = (
    "api.openalex.org",
    "api.semanticscholar.org",
    "archive.ics.uci.edu",
    "export.arxiv.org",
    "huggingface.co",
)
SERVE_NETWORK_SOURCE_URLS = (
    "https://export.arxiv.org/api/query",
    "https://api.openalex.org/works",
    "https://api.semanticscholar.org/graph/v1/paper/search",
    "https://huggingface.co/datasets",
    "https://archive.ics.uci.edu/",
)
LLM_PROVIDER_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-chat",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "openai/gpt-4o-mini",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model_name": "gpt-4o-mini",
    },
    {
        "id": "qwen-dashscope",
        "label": "Alibaba Cloud DashScope / Qwen compatible mode",
        "provider": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen-plus",
    },
    {
        "id": "siliconflow",
        "label": "SiliconFlow",
        "provider": "siliconflow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "Qwen/Qwen2.5-72B-Instruct",
    },
    {
        "id": "custom",
        "label": "Custom OpenAI-compatible endpoint",
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1",
        "model_name": "model-name",
    },
)
WECHAT_QR_SETUP_COMMAND = "npx -y @tencent-weixin/openclaw-weixin-cli install"
WECHAT_QR_LOGIN_COMMAND = "openclaw channels login --channel openclaw-weixin"
WECHAT_OPENCLAW_CHANNEL = "openclaw-weixin"
OPENCLAW_MESSAGE_SEND_COMMAND = "openclaw message send"
WECHAT_QR_SESSION_PATH = ".airesearcher/channels/wechat/session.json"
WECHAT_QR_SETUP_STATUS_PATH = ".airesearcher/channels/wechat/setup-status.json"
FEISHU_DEFAULT_BASE_URL = "https://open.feishu.cn"

DEFAULT_SLASH_COMMANDS = {
    "research/refresh-literature.toml": (
        "Fetch real literature sources and write a guarded Obsidian summary.",
        "Run `airesearcher literature-refresh --vault autoresearch-vault --cache .cache/literature` "
        "and summarize source-backed new papers only. Do not infer paper results, code "
        "availability, or benchmark scores unless the fetched source explicitly provides them.",
    ),
    "research/inspiration-refresh.toml": (
        "Search broad non-scholarly inspiration sources without treating them as paper evidence.",
        "Run `airesearcher inspiration-refresh --query \"{{args}}\" --vault autoresearch-vault "
        "--output runs/inspiration/latest.json --push`. Results from Hugging Face datasets and Hacker News "
        "are dataset/community signals only; validate them separately before using them as research evidence. "
        "Use `--push-channel feishu` or `--push-channel wechat` to target a setup-configured channel.",
    ),
    "research/similarity-check.toml": (
        "Cross-check a candidate against adjacent online work before project approval.",
        "Run `airesearcher similarity-check --candidate-file <candidate.json>` for {{args}}. "
        "Use source URLs and DOI evidence only; unsupported outcomes must remain pending verification.",
    ),
    "research/research-plan.toml": (
        "Generate the execution-ready research plan after the user confirms a direction.",
        "Run `airesearcher research-plan --candidate-file <candidate.json> --project-id <project>` "
        "after similarity checking. The command writes the archival Markdown plan into the "
        "Obsidian vault and the LaTeX/PDF plan under outputs/<project>/research-plan/. "
        "Do not start code-agent experiments until this gate passes.",
    ),
    "research/run-demo.toml": (
        "Run a local demo or public benchmark and inspect evidence outputs.",
        "Run `airesearcher run-demo --demo {{args}}` or default to tabular_baseline. "
        "Review the validation report, evidence map, and Markdown report before making claims.",
    ),
    "research/autopilot.toml": (
        "Start the local autonomous research loop with evidence and review gates.",
        "Run `airesearcher autopilot --watch --cycles 0 --interval-seconds 86400 --push-inspiration` "
        "after deploy-setup. The loop performs live literature refresh, similarity "
        "checking, local experiment execution, evidence review, and Obsidian issue "
        "follow-up discovery using publication-grade default search breadth, and pushes "
        "the broad-inspiration digest when a delivery channel is configured; inspect "
        "cycle-summary.json before claiming publication quality. Use "
        "`--paper-template-id <template>` to collect venue-template compatibility evidence.",
    ),
    "research/serve.toml": (
        "Start the always-on operator service with dangerous-action approval gates.",
        "Run `airesearcher serve --permission-mode approve-dangerous --push-inspiration` after deploy-setup. "
        "This is the preferred 24h runtime entry point; it runs the research loop only "
        "after dangerous actions are approved through `airesearcher runtime approve` or "
        "a future WeChat/Feishu `/approve` adapter.",
    ),
    "research/publication-audit.toml": (
        "Audit whether a completed cycle meets CCF-B/Q3 publication-readiness gates.",
        "Run `airesearcher publication-audit <cycle-summary.json> --target ccf-b "
        "[--review-json runs/llm-review/latest.json]` before claiming the output is publishable. "
        "A standalone review can satisfy review checks only; treat `fail` or `needs_revision` "
        "as blockers, not cosmetic polish.",
    ),
    "research/publication-stability.toml": (
        "Gate stable publication-output claims across multiple completed cycles.",
        "Run `airesearcher publication-stability <cycle-summary.json> ... --target ccf-b-matrix` "
        "after several complete cycles. The matrix requires multiple release-allowed cycles, "
        "distinct real public datasets, LaTeX template diversity, and at least one fetched "
        "external conference template plus one fetched external journal template before stable "
        "CCF-B/Q3 claims are allowed.",
    ),
    "research/approve.toml": (
        "Approve the latest pending dangerous runtime action.",
        "Run `airesearcher runtime approve {{args}} --state .airesearcher/runtime-approvals.json "
        "--approved-by operator`. Use `latest` when approving the newest pending request "
        "from a WeChat/Feishu `/approve` message.",
    ),
    "research/channel-adapters.toml": (
        "Write the optional messaging channel adapter runbook.",
        "Run `airesearcher channels adapters init --output integrations/channels/adapters.json` "
        "to create the repository runbook for optional Lark/Feishu, Weixin, WeCom, "
        "Telegram, Discord, Slack, WhatsApp, Teams, QQ, Signal, and Zalo channel plugins. "
        "Review upstream licenses, platform permissions, and secrets before installing any "
        "adapter outside AI-Researcher.",
    ),
    "research/channel-test.toml": (
        "Send a setup-channel self-test message through the configured notification path.",
        "Run `airesearcher channels test --channel {{args}} --require-sent` after setup. "
        "Use `wechat`, `feishu`, or repeat `--channel` for several channels. A skipped "
        "or failed result means the channel is not ready for unattended inspiration pushes.",
    ),
    "research/readiness.toml": (
        "Check whether the local deployment is ready for the daily unattended research loop.",
        "Run `airesearcher readiness --push-inspiration --require-channel-config "
        "--require-channel-sent` after setup and channel testing. Inspect "
        "`.airesearcher/readiness/report.json` before leaving the service running "
        "for 24h operation.",
    ),
    "research/scansci-pdf.toml": (
        "Write the optional ScanSci PDF integration manifest with OA/legal-first defaults.",
        "Run `airesearcher pdf-sources scansci-pdf init --output integrations/scansci-pdf/pdf-source.json` "
        "before enabling any PDF fetch backend. Keep publisher-direct, arXiv, PMC, Unpaywall, "
        "OpenAlex, DOAJ, CORE, and Europe PMC as default sources; require human approval and "
        "license review for Sci-Hub, LibGen, WebVPN, CARSI, Tor, or bypass-oriented sources.",
    ),
    "research/code-agent-backends.toml": (
        "Write external code-agent backend contracts.",
        "Prefer `airesearcher code-agents opencode init --output integrations/opencode/code-agent.json` "
        "to record direct OpenCode run/serve/acp integration while AI-Researcher keeps validation, "
        "approval, merge, rollback, and Obsidian logging authority. Use "
        "`airesearcher code-agents cc-switch init --output integrations/cc-switch/code-agent.json` "
        "only when Claude Code provider routing through cc-switch is explicitly needed.",
    ),
    "research/obsidian-setup.toml": (
        "Structure and style the Obsidian vault for readable research operations.",
        "Run `airesearcher obsidian-setup --vault autoresearch-vault --project-id {{args}}` "
        "to create Home.md, dashboards, templates, plugin recommendations, and CSS snippet assets. "
        "Use `--write-local-snippet` only on your own machine.",
    ),
    "research/skill-evolve.toml": (
        "Create a bounded skill evolution candidate from vault issue and failure evidence.",
        "Run `airesearcher skill-evolve --parent-skill-id <skill_id> --issue-ref <issue> "
        "--change-summary \"...\" --proposed-action \"...\" --validation-check \"...\"`. "
        "Do not promote the candidate until held-out validation passes.",
    ),
    "research/skill-polish-audit.toml": (
        "Audit whether a skill candidate is ready to promote or publish.",
        "Run `airesearcher skill-polish-audit --skill-id <candidate_skill_id> "
        "--peer-ref <url> --live-evidence-ref <artifact> --install-ref <asset> "
        "--release-ref <observation>`. The Luban-inspired gate blocks promotion when "
        "the skill lacks peer positioning, real validation evidence, rollback/rejected-edit "
        "boundaries, installable/shareable assets, or follow-up observation refs.",
    ),
    "research/skill-watchlist.toml": (
        "Write the external research-skill watchlist into the Obsidian vault.",
        "Run `airesearcher skill-watchlist --vault autoresearch-vault` after external skill "
        "discovery. This records candidate directions, source refs, license status, risks, "
        "and validation gates without installing or copying third-party skill content.",
    ),
    "research/agent-profile.toml": (
        "Bind custom skills and MCP tools to one named research agent.",
        "Run `airesearcher agents profile write --agent-id <agent> --role project_agent "
        "--skill <skill_id>=<path-or-note> --mcp <server_id>=\"<command>\" "
        "--mcp-tool <server_id>:<tool> --skill-policy <skill_id>:read_only_context "
        "--mcp-approval <server_id>:approve_dangerous --mcp-env-key <server_id>:ENV_KEY "
        "--vault autoresearch-vault --project-id <project>` to create a bounded profile. "
        "MCP tools must be explicitly allowlisted; env-key flags store names only, not "
        "secret values; the profile does not change safety, license, approval, or "
        "publication gates.",
    ),
    "research/paper-build.toml": (
        "Build the final LaTeX/PDF paper artifact from an evidence-bound Markdown report.",
        "Run `airesearcher paper-build <report.md> --template-id {{args}} --vault autoresearch-vault "
        "--project-id <project_id>`. Use `generic-article-one-column` when no target venue is chosen. "
        "Missing paper sections must block compilation rather than being filled with invented content.",
    ),
    "research/evidence-gate.toml": (
        "Run the physical evidence gate before release or paper-ready claims.",
        "Run `airesearcher evidence-gate <cycle-summary.json> --publication-audit <publication-audit.json> "
        "--paper-build-json <paper-build.json> --vault autoresearch-vault --project-id <project_id>`. "
        "Blocked gates are release blockers; do not override them with prompt-only assurances.",
    ),
    "research/session-claim.toml": (
        "Claim file paths before a concurrent agent starts editing.",
        "Run `airesearcher sessions claim --task-id <task_id> --agent-name <agent> --path {{args}}` "
        "before starting a coding/research subtask. A blocked claim means another active session owns an "
        "overlapping file or directory and the agent should wait, release, or narrow its path scope.",
    ),
    "research/status.toml": (
        "Check local installation and release-readiness gates.",
        "Run `airesearcher doctor`, then inspect `Problem.md`, `Agent.md`, and the latest git status. "
        "Report blockers before proposing more automation.",
    ),
    "research/issue-followups.toml": (
        "List self-loop follow-up tasks from open Obsidian project issue notes.",
        "Run `airesearcher issue-followups --vault autoresearch-vault --project-id {{args}} "
        "--output runs/issue-followups/latest.json --state .airesearcher/scheduler-state.json`. "
        "Review the generated task IDs and issue paths before executing follow-up work.",
    ),
}

ENV_EXAMPLE_TEXT = """# Local deployment secrets for AI-Researcher.
# Generated by `airesearcher deploy-setup` when the template is missing.
# Copy this file to .env or rerun the setup command to write real local values.
# Never commit real API keys, webhook URLs, app secrets, or tokens.

AUTORESEARCH_LLM_PROVIDER=openai-compatible
AUTORESEARCH_LLM_BASE_URL=
AUTORESEARCH_LLM_MODEL_NAME=
AUTORESEARCH_LLM_API_KEY=

# Optional Semantic Scholar Graph API source.
# AI-Researcher defaults to ArXiv + OpenAlex; set this flag or an API key
# only when you want Semantic Scholar as an extra metadata source.
AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR=
SEMANTIC_SCHOLAR_API_KEY=
SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS=
SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS=

# Optional OpenAlex key/contact for the default free/public metadata source.
OPENALEX_API_KEY=
OPENALEX_MAILTO=
OPENALEX_MIN_INTERVAL_SECONDS=
OPENALEX_CIRCUIT_RESET_SECONDS=

# Optional WeChat channel. The setup wizard defaults to QR adapter onboarding.
AUTORESEARCH_WECHAT_CONNECTION_MODE=
AUTORESEARCH_WECHAT_WEBHOOK_URL=
AUTORESEARCH_WECHAT_APP_ID=
AUTORESEARCH_WECHAT_APP_SECRET=
AUTORESEARCH_WECHAT_QR_SETUP_COMMAND=
AUTORESEARCH_WECHAT_QR_LOGIN_COMMAND=
AUTORESEARCH_WECHAT_SESSION_PATH=
AUTORESEARCH_WECHAT_SETUP_STATUS_PATH=
AUTORESEARCH_WECHAT_OPENCLAW_CHANNEL=
AUTORESEARCH_WECHAT_OPENCLAW_TARGET=
AUTORESEARCH_WECHAT_OPENCLAW_MESSAGE_COMMAND=

# Optional Feishu/Lark channel. The setup wizard defaults to App ID/App Secret.
AUTORESEARCH_FEISHU_CONNECTION_MODE=
AUTORESEARCH_FEISHU_BASE_URL=
AUTORESEARCH_FEISHU_WEBHOOK_URL=
AUTORESEARCH_FEISHU_APP_ID=
AUTORESEARCH_FEISHU_APP_SECRET=
AUTORESEARCH_FEISHU_HOME_CHAT_ID=
AUTORESEARCH_FEISHU_ALLOWED_USERS=
"""


@app.command()
def version() -> None:
    """Print the installed AI-Researcher version."""

    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check local scaffold health without contacting external services."""

    config = SystemConfig()
    checks = [
        (
            "python >= 3.10",
            sys.version_info >= (3, 10),
            sys.version.split()[0],
        ),
        (
            "import autoresearch",
            _can_import("autoresearch"),
            "package import",
        ),
        (
            "import autoresearch.config",
            _can_import("autoresearch.config"),
            "config import",
        ),
        (
            "config parser",
            _parser_available(),
            "JSON/YAML/TOML parser",
        ),
        (
            "project root",
            config.project_root.exists(),
            str(config.project_root),
        ),
        (
            "knowledge vault",
            config.knowledge_base.vault_path.exists(),
            str(config.knowledge_base.vault_path),
        ),
    ]
    dependency_check = diagnose_requests_dependency_set()

    failed = False
    for name, ok, detail in checks:
        label = "OK" if ok else "FAIL"
        typer.echo(f"[{label}] {name}: {detail}")
        failed = failed or not ok
    typer.echo(
        f"[{dependency_check.status.value}] "
        f"{dependency_check.name}: {dependency_check.detail}"
    )
    failed = failed or dependency_check.blocks_doctor

    if failed:
        raise typer.Exit(code=1)


@app.command("init-demo")
def init_demo(
    path: Path = typer.Option(
        Path("examples/demo"),
        "--path",
        "-p",
        help="Directory where the local demo scaffold should be created.",
    ),
) -> None:
    """Create a local demo scaffold without running a research workflow."""

    path.mkdir(parents=True, exist_ok=True)
    config = SystemConfig(project_root=path)
    parser = ConfigParser()

    readme_path = path / "README.md"
    config_path = path / "config.yaml"

    if not readme_path.exists():
        readme_path.write_text(
            "# AI-Researcher Demo\n\n"
            "This scaffold is created by `airesearcher init-demo`.\n"
            "It does not run the research workflow yet.\n",
            encoding="utf-8",
        )
    if not config_path.exists():
        parser.write_file(config, config_path, ConfigFormat.YAML)

    typer.echo(f"Demo scaffold ready at {path}")


@app.command("obsidian-setup")
def obsidian_setup(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to structure."),
    ] = Path("autoresearch-vault"),
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID under the vault `projects/` directory."),
    ] = "autoresearch-system",
    write_local_snippet: Annotated[
        bool,
        typer.Option(
            "--write-local-snippet/--no-write-local-snippet",
            help="Also write and enable a local `.obsidian/snippets/ai-researcher.css` file.",
        ),
    ] = False,
) -> None:
    """Create Obsidian dashboards, templates, plugin notes, and styling assets."""

    try:
        assets = create_obsidian_vault_assets(
            vault,
            project_id,
            write_local_snippet=write_local_snippet,
        )
    except ValueError as exc:
        typer.echo(f"[FAIL] obsidian_setup: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"[OK] vault_home: {assets.home_path}")
    typer.echo(f"[OK] dashboard: {assets.dashboard_path}")
    typer.echo(f"[OK] plugin_recommendations: {assets.plugin_recommendations_path}")
    typer.echo(f"[OK] templates: {len(assets.template_paths)}")
    typer.echo(f"[OK] snippet: {assets.snippet_path}")
    if assets.local_snippet_path is not None:
        typer.echo(f"[OK] local_snippet: {assets.local_snippet_path}")


@agent_profiles_app.command("write")
def write_agent_profile_command(
    agent_id: Annotated[
        str,
        typer.Option("--agent-id", help="Agent ID that will receive this profile."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Profile JSON artifact path."),
    ] = Path(".airesearcher/agents/profile.json"),
    role: Annotated[
        AgentRole,
        typer.Option("--role", help="Agent role used by vault permissions."),
    ] = AgentRole.PROJECT_AGENT,
    thinking_mode: Annotated[
        AgentThinkingMode,
        typer.Option("--thinking-mode", help="Scientific reasoning contract to attach."),
    ] = AgentThinkingMode.SCIENTIFIC,
    publication_target: Annotated[
        str,
        typer.Option("--publication-target", help="Publication-quality target for this agent."),
    ] = "ccf-b-or-sci-q2",
    description: Annotated[
        str | None,
        typer.Option("--description", help="Optional human-readable profile purpose."),
    ] = None,
    stage: Annotated[
        list[str] | None,
        typer.Option(
            "--stage",
            help="Research-loop stage assigned to this agent. Repeat for multiple stages.",
        ),
    ] = None,
    skill: Annotated[
        list[str] | None,
        typer.Option(
            "--skill",
            help="Custom skill binding as skill_id=source. Repeat for multiple skills.",
        ),
    ] = None,
    skill_policy: Annotated[
        list[str] | None,
        typer.Option(
            "--skill-policy",
            help=(
                "Skill import policy as skill_id:policy. Policies: read_only_context, "
                "shadow_evaluation, approved_runtime."
            ),
        ),
    ] = None,
    mcp: Annotated[
        list[str] | None,
        typer.Option(
            "--mcp",
            help="MCP binding as server_id=\"command args\". Repeat for multiple servers.",
        ),
    ] = None,
    mcp_tool: Annotated[
        list[str] | None,
        typer.Option(
            "--mcp-tool",
            help="Allowed MCP tool as server_id:tool_name. Repeat for multiple tools.",
        ),
    ] = None,
    mcp_approval: Annotated[
        list[str] | None,
        typer.Option(
            "--mcp-approval",
            help=(
                "MCP approval policy as server_id:policy. Policies: read_only, "
                "approve_dangerous, allow_all."
            ),
        ),
    ] = None,
    mcp_env_key: Annotated[
        list[str] | None,
        typer.Option(
            "--mcp-env-key",
            help=(
                "MCP required environment variable name as server_id:ENV_KEY. "
                "Repeat for multiple keys; secret values are never stored."
            ),
        ),
    ] = None,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Optional Obsidian vault root for a profile note."),
    ] = None,
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for the optional vault note."),
    ] = "ai_researcher_system",
) -> None:
    """Write a bounded custom skill/MCP profile for one agent."""

    try:
        skill_bindings = tuple(parse_skill_spec(spec) for spec in (skill or ()))
        skill_policies = parse_skill_policy_specs(tuple(skill_policy or ()))
        bound_skill_ids = {binding.skill_id for binding in skill_bindings}
        unused_skill_policies = sorted(set(skill_policies) - bound_skill_ids)
        if unused_skill_policies:
            msg = (
                "--skill-policy references missing --skill binding(s): "
                f"{', '.join(unused_skill_policies)}"
            )
            raise ValueError(msg)
        skill_bindings = tuple(
            binding.model_copy(
                update={"import_policy": skill_policies.get(binding.skill_id, binding.import_policy)}
            )
            for binding in skill_bindings
        )
        tools_by_server = parse_server_tool_specs(tuple(mcp_tool or ()))
        mcp_approval_policies = parse_mcp_approval_policy_specs(tuple(mcp_approval or ()))
        mcp_env_keys_by_server = parse_mcp_env_key_specs(tuple(mcp_env_key or ()))
        mcp_servers = tuple(parse_mcp_spec(spec, tools_by_server=tools_by_server) for spec in (mcp or ()))
        bound_server_ids = {server.server_id for server in mcp_servers}
        unused_tool_servers = sorted(set(tools_by_server) - bound_server_ids)
        if unused_tool_servers:
            msg = f"--mcp-tool references missing --mcp server(s): {', '.join(unused_tool_servers)}"
            raise ValueError(msg)
        unused_mcp_policy_servers = sorted(set(mcp_approval_policies) - bound_server_ids)
        if unused_mcp_policy_servers:
            msg = (
                "--mcp-approval references missing --mcp server(s): "
                f"{', '.join(unused_mcp_policy_servers)}"
            )
            raise ValueError(msg)
        unused_mcp_env_servers = sorted(set(mcp_env_keys_by_server) - bound_server_ids)
        if unused_mcp_env_servers:
            msg = (
                "--mcp-env-key references missing --mcp server(s): "
                f"{', '.join(unused_mcp_env_servers)}"
            )
            raise ValueError(msg)
        mcp_servers = tuple(
            server.model_copy(
                update={
                    "approval_policy": mcp_approval_policies.get(
                        server.server_id,
                        server.approval_policy,
                    ),
                    "env_keys": tuple(
                        dict.fromkeys(
                            (
                                *server.env_keys,
                                *mcp_env_keys_by_server.get(server.server_id, ()),
                            )
                        )
                    ),
                }
            )
            for server in mcp_servers
        )
        assigned_stages = _validated_agent_profile_stages(tuple(stage or ()))
        profile = AgentProfile(
            agent_id=agent_id,
            role=role,
            thinking_mode=thinking_mode,
            publication_target=publication_target,
            description=description,
            assigned_stages=assigned_stages,
            skills=skill_bindings,
            mcp_servers=mcp_servers,
        )
    except ValueError as exc:
        typer.echo(f"[FAIL] agent_profile: {exc}", err=True)
        raise typer.Exit(1) from exc

    profile_path = write_agent_profile(profile, output)
    typer.echo(f"[OK] agent_profile: {profile.agent_id}")
    typer.echo(f"[OK] role: {profile.role.value}")
    typer.echo(f"[OK] thinking_mode: {profile.thinking_mode.value}")
    if profile.assigned_stages:
        typer.echo(f"[OK] assigned_stages: {', '.join(profile.assigned_stages)}")
    else:
        typer.echo("[OK] assigned_stages: unassigned")
    typer.echo(f"[OK] skills: {len(profile.skills)}")
    typer.echo(f"[OK] mcp_servers: {len(profile.mcp_servers)}")
    typer.echo(f"[OK] profile: {profile_path}")
    if vault is not None:
        note_path = write_agent_profile_note(profile, vault_root=vault, project_id=project_id)
        typer.echo(f"[OK] vault_note: {note_path}")


@agent_profiles_app.command("import")
def import_agent_profile_command(
    bundle_path: Annotated[
        Path,
        typer.Argument(help="Declarative Agent profile bundle (.json, .yaml, .yml, or .toml)."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Profile JSON artifact path."),
    ] = Path(".airesearcher/agents/profile.json"),
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Optional Obsidian vault root for a profile note."),
    ] = None,
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for the optional vault note."),
    ] = "ai_researcher_system",
) -> None:
    """Import a reusable JSON/YAML/TOML Agent profile bundle."""

    try:
        bundle = load_agent_profile_bundle(bundle_path)
        profile = build_agent_profile_from_bundle(bundle)
    except ValueError as exc:
        typer.echo(f"[FAIL] agent_profile_import: {exc}", err=True)
        raise typer.Exit(1) from exc

    profile_path = write_agent_profile(profile, output)
    typer.echo(f"[OK] agent_profile_import: {profile.agent_id}")
    typer.echo(f"[OK] source_bundle: {bundle_path}")
    typer.echo(f"[OK] role: {profile.role.value}")
    typer.echo(f"[OK] thinking_mode: {profile.thinking_mode.value}")
    if profile.assigned_stages:
        typer.echo(f"[OK] assigned_stages: {', '.join(profile.assigned_stages)}")
    else:
        typer.echo("[OK] assigned_stages: unassigned")
    typer.echo(f"[OK] skills: {len(profile.skills)}")
    typer.echo(f"[OK] mcp_servers: {len(profile.mcp_servers)}")
    typer.echo(f"[OK] profile: {profile_path}")
    if vault is not None:
        note_path = write_agent_profile_note(profile, vault_root=vault, project_id=project_id)
        typer.echo(f"[OK] vault_note: {note_path}")


@agent_profiles_app.command("inspect")
def inspect_agent_profile_command(
    profile_path: Annotated[
        Path,
        typer.Argument(help="Profile JSON artifact to inspect."),
    ],
    materialize_skills: Annotated[
        bool,
        typer.Option(
            "--materialize-skills/--no-materialize-skills",
            help="Attach bounded local skill content with hashes and truncation metadata.",
        ),
    ] = False,
    base_dir: Annotated[
        Path,
        typer.Option("--base-dir", help="Base directory for relative local skill sources."),
    ] = Path("."),
    max_skill_chars: Annotated[
        int,
        typer.Option(
            "--max-skill-chars",
            min=0,
            help="Maximum characters to attach per local skill when materializing.",
        ),
    ] = DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS,
) -> None:
    """Print the runtime context for a custom skill/MCP agent profile."""

    try:
        profile = load_agent_profile(profile_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"[FAIL] agent_profile_inspect: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        json.dumps(
            profile.to_runtime_context(
                base_dir=base_dir,
                materialize_skills=materialize_skills,
                max_skill_chars=max_skill_chars,
            ),
            indent=2,
            sort_keys=True,
        )
    )


@agent_profiles_app.command("validate")
def validate_agent_profile_command(
    profile_path: Annotated[
        Path,
        typer.Argument(help="Profile JSON artifact to validate."),
    ],
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Environment file containing required MCP env names."),
    ] = Path(".env"),
    base_dir: Annotated[
        Path,
        typer.Option("--base-dir", help="Base directory for relative local skill sources."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional profile readiness JSON path."),
    ] = None,
) -> None:
    """Validate local readiness for one custom skill/MCP profile."""

    try:
        profile = load_agent_profile(profile_path)
        report = evaluate_agent_profile_readiness(
            profile,
            profile_path=profile_path,
            base_dir=base_dir,
            env=_merged_optional_env(env_path),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"[FAIL] agent_profile_validate: {exc}", err=True)
        raise typer.Exit(1) from exc

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        typer.echo(f"[OK] readiness_report: {output}")
    verdict = "passed" if report.passed else "failed"
    typer.echo(f"[OK] agent_profile_readiness: {verdict}")
    typer.echo(
        f"[OK] readiness_checks: {report.check_count}; "
        f"failed={report.failed_check_count}; warnings={report.warning_count}"
    )
    for check in report.checks:
        typer.echo(f"[CHECK] {check.check_id}: {check.status.value} - {check.message}")
    if not report.passed:
        raise typer.Exit(1)


@agent_profiles_app.command("set-validate")
def validate_agent_profile_set_command(
    profile_paths: Annotated[
        list[Path],
        typer.Argument(help="One or more Agent profile JSON artifacts to validate as a set."),
    ],
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Environment file containing required MCP env names."),
    ] = Path(".env"),
    base_dir: Annotated[
        Path,
        typer.Option("--base-dir", help="Base directory for relative local skill sources."),
    ] = Path("."),
    required_stage: Annotated[
        list[str] | None,
        typer.Option(
            "--required-stage",
            help=(
                "Research-loop stage that must have at least one assigned Agent. "
                "Repeat to override the default CCF-B/Q2-oriented stage set."
            ),
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional profile-set validation JSON path."),
    ] = None,
) -> None:
    """Validate a stage-scoped team of custom skill/MCP Agent profiles."""

    env = _merged_optional_env(env_path)
    profiles: list[AgentProfile] = []
    readiness_reports = []
    try:
        for profile_path in profile_paths:
            profile = load_agent_profile(profile_path)
            profiles.append(profile)
            readiness_reports.append(
                evaluate_agent_profile_readiness(
                    profile,
                    profile_path=profile_path,
                    base_dir=base_dir,
                    env=env,
                )
            )
        validation = evaluate_agent_profile_set(
            profiles,
            required_stages=required_stage or DEFAULT_AGENT_PROFILE_SET_REQUIRED_STAGES,
            readiness_reports=readiness_reports,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"[FAIL] agent_profile_set_validate: {exc}", err=True)
        raise typer.Exit(1) from exc

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(validation.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"[OK] profile_set_report: {output}")

    verdict = "passed" if validation.passed else "failed"
    typer.echo(f"[OK] agent_profile_set: {verdict}")
    typer.echo(
        f"[OK] stage_coverage: {validation.covered_stage_count}/"
        f"{len(validation.required_stages)}; profiles={validation.profile_count}"
    )
    for row in validation.stage_coverage:
        status = "covered" if row.covered else "missing"
        agents = ", ".join(row.agent_ids) if row.agent_ids else "-"
        typer.echo(f"[STAGE] {row.stage}: {status}; agents={agents}")
    for failure in validation.failures:
        typer.echo(f"[FAIL] {failure}")
    for warning in validation.warnings:
        typer.echo(f"[WARN] {warning}")
    if not validation.passed:
        raise typer.Exit(1)


@agent_mcp_evidence_app.command("add")
def add_agent_mcp_invocation_evidence_command(
    profile_path: Annotated[
        Path,
        typer.Option("--profile", help="Agent profile JSON that owns this MCP binding."),
    ],
    ledger: Annotated[
        Path,
        typer.Option("--ledger", help="JSONL ledger path to append invocation evidence."),
    ],
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for the invocation evidence."),
    ],
    cycle_id: Annotated[
        str,
        typer.Option("--cycle-id", help="Cycle or run ID for the invocation evidence."),
    ],
    server_id: Annotated[
        str,
        typer.Option("--server-id", help="MCP server ID from the agent profile."),
    ],
    tool_name: Annotated[
        str,
        typer.Option("--tool-name", help="Allowed MCP tool name that was invoked."),
    ],
    request_artifact: Annotated[
        Path,
        typer.Option(
            "--request-artifact",
            help="File containing the sanitized request envelope to hash.",
        ),
    ],
    response_artifact: Annotated[
        Path | None,
        typer.Option(
            "--response-artifact",
            help="File containing the sanitized response/result envelope to hash.",
        ),
    ] = None,
    status: Annotated[
        McpInvocationStatus,
        typer.Option("--status", help="Invocation status."),
    ] = McpInvocationStatus.SUCCESS,
    base_dir: Annotated[
        Path,
        typer.Option("--base-dir", help="Base directory for relative artifact refs."),
    ] = Path("."),
    runtime_approval_request_id: Annotated[
        str | None,
        typer.Option("--runtime-approval-request-id", help="Linked runtime approval request ID."),
    ] = None,
    approved_by: Annotated[
        str | None,
        typer.Option("--approved-by", help="Operator identity for allow_all/approved actions."),
    ] = None,
    result_summary: Annotated[
        str,
        typer.Option("--result-summary", help="Short non-secret result summary."),
    ] = "MCP tool invocation recorded.",
    error_type: Annotated[
        str | None,
        typer.Option("--error-type", help="Error type for failed invocations."),
    ] = None,
    artifact_ref: Annotated[
        list[str] | None,
        typer.Option("--artifact-ref", help="Additional evidence artifact ref. Repeatable."),
    ] = None,
) -> None:
    """Append hashed MCP invocation evidence for one assigned agent."""

    try:
        profile = load_agent_profile(profile_path)
        evidence = build_mcp_invocation_evidence(
            profile=profile,
            project_id=project_id,
            cycle_id=cycle_id,
            server_id=server_id,
            tool_name=tool_name,
            status=status,
            request_artifact=request_artifact,
            response_artifact=response_artifact,
            base_dir=base_dir,
            runtime_approval_request_id=runtime_approval_request_id,
            approved_by=approved_by,
            result_summary=result_summary,
            error_type=error_type,
            artifact_refs=tuple(artifact_ref or ()),
        )
        append_mcp_invocation_evidence(ledger, evidence)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"[FAIL] mcp_invocation_evidence_add: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"[OK] mcp_invocation_evidence: {evidence.evidence_id}")
    typer.echo(f"[OK] agent_id: {evidence.agent_id}")
    typer.echo(f"[OK] server_tool: {evidence.server_id}:{evidence.tool_name}")
    typer.echo(f"[OK] ledger: {ledger}")
    typer.echo(f"[OK] request_sha256: {evidence.request_sha256}")
    if evidence.response_sha256:
        typer.echo(f"[OK] response_sha256: {evidence.response_sha256}")


@agent_mcp_evidence_app.command("list")
def list_agent_mcp_invocation_evidence_command(
    ledger: Annotated[
        Path,
        typer.Argument(help="JSONL MCP invocation evidence ledger to inspect."),
    ],
) -> None:
    """List MCP invocation evidence records."""

    try:
        records = load_mcp_invocation_evidence(ledger)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"[FAIL] mcp_invocation_evidence_list: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"[OK] mcp_invocation_evidence_records: {len(records)}")
    for record in records:
        typer.echo(
            f"[MCP] evidence_id={record.evidence_id} status={record.status.value} "
            f"agent={record.agent_id} tool={record.server_id}:{record.tool_name}"
        )


@agent_mcp_evidence_app.command("validate")
def validate_agent_mcp_invocation_evidence_command(
    profile_path: Annotated[
        Path,
        typer.Option("--profile", help="Agent profile JSON that owns these MCP bindings."),
    ],
    ledger: Annotated[
        Path,
        typer.Argument(help="JSONL MCP invocation evidence ledger to validate."),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional validation JSON output path."),
    ] = None,
) -> None:
    """Validate MCP invocation evidence against an agent profile."""

    try:
        profile = load_agent_profile(profile_path)
        records = load_mcp_invocation_evidence(ledger)
        validations = tuple(
            validate_mcp_invocation_evidence(record, profile) for record in records
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"[FAIL] mcp_invocation_evidence_validate: {exc}", err=True)
        raise typer.Exit(1) from exc
    if output is not None:
        report_path = write_mcp_invocation_validation_report(output, validations)
        typer.echo(f"[OK] mcp_invocation_evidence_report: {report_path}")
    passed = all(validation.passed for validation in validations)
    typer.echo(f"[OK] mcp_invocation_evidence_validation: {'passed' if passed else 'failed'}")
    typer.echo(f"[OK] records: {len(validations)}")
    for validation in validations:
        status_text = "pass" if validation.passed else "fail"
        typer.echo(
            f"[CHECK] {validation.evidence_id}: {status_text}; "
            f"issues={len(validation.issues)}; warnings={len(validation.warnings)}"
        )
    if not passed:
        raise typer.Exit(1)


def _normalise_agent_profile_stage(stage: str) -> str:
    return stage.strip().lower().replace("-", "_")


def _validated_agent_profile_stages(stages: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(_normalise_agent_profile_stage(stage) for stage in stages if stage.strip())
    if len(normalized) != len(set(normalized)):
        msg = "duplicate --stage values are not allowed"
        raise ValueError(msg)
    allowed = set(AGENT_PROFILE_ASSIGNABLE_STAGES)
    unknown = sorted(set(normalized) - allowed)
    if unknown:
        msg = (
            f"unknown agent profile stage(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(AGENT_PROFILE_ASSIGNABLE_STAGES)}"
        )
        raise ValueError(msg)
    return normalized


def _load_agent_profile_contexts(
    profile_paths: Iterable[Path],
    *,
    env: Mapping[str, str] | None = None,
    base_dir: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    contexts: list[dict[str, Any]] = []
    seen_agent_ids: set[str] = set()
    readiness_env = env or {}
    readiness_base_dir = base_dir or Path.cwd()
    for profile_path in profile_paths:
        try:
            profile = load_agent_profile(profile_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            msg = f"failed to load agent profile {profile_path}: {exc}"
            raise RuntimeError(msg) from exc
        if profile.agent_id in seen_agent_ids:
            msg = f"duplicate agent profile for agent_id {profile.agent_id}"
            raise RuntimeError(msg)
        try:
            _validated_agent_profile_stages(profile.assigned_stages)
        except ValueError as exc:
            msg = f"invalid stage assignment in profile {profile_path}: {exc}"
            raise RuntimeError(msg) from exc
        seen_agent_ids.add(profile.agent_id)
        context = profile.to_runtime_context(
            base_dir=readiness_base_dir,
            materialize_skills=True,
        )
        context["profile_path"] = profile_path.as_posix()
        readiness = evaluate_agent_profile_readiness(
            profile,
            profile_path=profile_path,
            base_dir=readiness_base_dir,
            env=readiness_env,
        )
        context["readiness"] = readiness.model_dump(mode="json")
        contexts.append(context)
    return tuple(contexts)


def _agent_profiles_summary(profile_contexts: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    for context in profile_contexts:
        skills = _mapping_list(context.get("skills"))
        materialized_skills = _mapping_list(context.get("materialized_skills"))
        mcp_servers = _mapping_list(context.get("mcp_servers"))
        mcp_runtime_contracts = _mapping_list(context.get("mcp_runtime_contracts"))
        profiles.append(
            {
                "agent_id": str(context.get("agent_id", "")),
                "role": str(context.get("role", "")),
                "thinking_mode": str(context.get("thinking_mode", "")),
                "publication_target": str(context.get("publication_target", "")),
                "assigned_stages": _string_list(context.get("assigned_stages")),
                "profile_path": str(context.get("profile_path", "")),
                "readiness": context.get("readiness") if isinstance(
                    context.get("readiness"),
                    Mapping,
                ) else {},
                "skill_ids": [str(skill.get("skill_id", "")) for skill in skills],
                "materialized_skills": [
                    {
                        "skill_id": str(skill.get("skill_id", "")),
                        "status": str(skill.get("status", "")),
                        "sha256": skill.get("sha256"),
                        "byte_count": skill.get("byte_count"),
                        "char_count": skill.get("char_count"),
                        "truncated": bool(skill.get("truncated", False)),
                        "resolved_path": skill.get("resolved_path"),
                    }
                    for skill in materialized_skills
                ],
                "mcp_servers": [
                    {
                        "server_id": str(server.get("server_id", "")),
                        "allowed_tools": _string_list(server.get("allowed_tools")),
                        "approval_policy": str(server.get("approval_policy", "")),
                    }
                    for server in mcp_servers
                ],
                "mcp_runtime_contracts": [
                    {
                        "server_id": str(contract.get("server_id", "")),
                        "contract_kind": str(contract.get("contract_kind", "")),
                        "command_sha256": contract.get("command_sha256"),
                        "allowed_tools": _string_list(contract.get("allowed_tools")),
                        "approval_policy": str(contract.get("approval_policy", "")),
                        "runtime_approval_required": bool(
                            contract.get("runtime_approval_required", False)
                        ),
                        "operator_isolation_required": bool(
                            contract.get("operator_isolation_required", False)
                        ),
                        "tool_invocation_evidence_required": bool(
                            contract.get("tool_invocation_evidence_required", True)
                        ),
                    }
                    for contract in mcp_runtime_contracts
                ],
            }
        )
    readiness_values = [
        value
        for value in (profile.get("readiness") for profile in profiles)
        if isinstance(value, Mapping)
    ]
    failed_checks = sum(int(value.get("failed_check_count", 0) or 0) for value in readiness_values)
    warning_checks = sum(int(value.get("warning_count", 0) or 0) for value in readiness_values)
    return {
        "count": len(profiles),
        "profiles": profiles,
        "runtime_contexts": list(profile_contexts),
        "readiness": {
            "passed": failed_checks == 0,
            "failed_check_count": failed_checks,
            "warning_count": warning_checks,
        },
        "stage_assignments": _agent_profile_stage_assignments(profile_contexts),
        "stage_runtime_contexts": profile_contexts_by_stage(
            profile_contexts,
            AGENT_PROFILE_ASSIGNABLE_STAGES,
        ),
        "evidence_policy": (
            "Agent profiles provide bounded skill/MCP context only; publication claims still "
            "require loop, review, audit, evidence, and reproduction gates."
        ),
    }


def _agent_profile_stage_assignments(
    profile_contexts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    stage_rows: list[dict[str, Any]] = []
    unassigned_agent_ids: list[str] = []
    for stage in AGENT_PROFILE_ASSIGNABLE_STAGES:
        agent_ids = [
            str(context.get("agent_id", ""))
            for context in profile_contexts
            if stage in _string_list(context.get("assigned_stages"))
        ]
        if agent_ids:
            stage_rows.append({"stage": stage, "agent_ids": agent_ids})
    for context in profile_contexts:
        if not _string_list(context.get("assigned_stages")):
            unassigned_agent_ids.append(str(context.get("agent_id", "")))
    return {
        "stages": stage_rows,
        "unassigned_agent_ids": unassigned_agent_ids,
        "policy": (
            "Stage assignments define responsibility/context boundaries; they do not grant "
            "permission to bypass scientific evidence gates."
        ),
    }


@app.command("skill-evolve")
def skill_evolve(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root containing skill cards."),
    ] = Path("autoresearch-vault"),
    parent_skill_id: Annotated[
        str,
        typer.Option("--parent-skill-id", help="Existing skill card ID to evolve."),
    ] = "",
    change_summary: Annotated[
        str,
        typer.Option("--change-summary", help="Bounded edit summary."),
    ] = "",
    issue_ref: Annotated[
        list[str] | None,
        typer.Option("--issue-ref", help="Issue evidence ref. Repeat for multiple issues."),
    ] = None,
    failure_ref: Annotated[
        list[str] | None,
        typer.Option("--failure-ref", help="Failure-pattern evidence ref. Repeat as needed."),
    ] = None,
    proposed_action: Annotated[
        list[str] | None,
        typer.Option("--proposed-action", help="Candidate action. Repeat for multiple actions."),
    ] = None,
    validation_check: Annotated[
        list[str] | None,
        typer.Option("--validation-check", help="Held-out validation check. Repeat as needed."),
    ] = None,
    candidate_skill_id: Annotated[
        str | None,
        typer.Option("--candidate-skill-id", help="Optional explicit candidate skill ID."),
    ] = None,
) -> None:
    """Create a bounded skill evolution candidate from local evidence."""

    try:
        candidate = create_skill_evolution_candidate(
            vault_root=vault,
            parent_skill_id=parent_skill_id,
            candidate_skill_id=candidate_skill_id,
            change_summary=change_summary,
            issue_refs=tuple(issue_ref or ()),
            failure_pattern_refs=tuple(failure_ref or ()),
            proposed_actions=tuple(proposed_action or ()),
            validation_checks=tuple(validation_check or ()),
        )
    except ValueError as exc:
        typer.echo(f"[FAIL] skill_evolve: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"[OK] candidate_skill_id: {candidate.candidate_skill_id}")
    typer.echo(f"[OK] candidate_path: {candidate.path}")
    typer.echo(f"[OK] parent_skill_id: {candidate.parent_skill_id}")
    typer.echo(f"[OK] validation_checks: {len(candidate.validation_checks)}")
    typer.echo(f"[OK] rejected_edit_buffer: {candidate.rejected_edit_buffer_path}")


@app.command("skill-polish-audit")
def skill_polish_audit(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root containing skill cards."),
    ] = Path("autoresearch-vault"),
    skill_id: Annotated[
        str,
        typer.Option("--skill-id", help="Skill or candidate skill ID to audit."),
    ] = "",
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Skill polish JSON report output path."),
    ] = Path("runs/skill-polish/latest.json"),
    peer_ref: Annotated[
        list[str] | None,
        typer.Option("--peer-ref", help="Peer skill or comparable project URL/ref. Repeat as needed."),
    ] = None,
    live_evidence_ref: Annotated[
        list[str] | None,
        typer.Option(
            "--live-evidence-ref",
            help="Real validation, backtest, or live artifact ref. Repeat as needed.",
        ),
    ] = None,
    install_ref: Annotated[
        list[str] | None,
        typer.Option("--install-ref", help="Install/export/shareable asset ref. Repeat as needed."),
    ] = None,
    release_ref: Annotated[
        list[str] | None,
        typer.Option("--release-ref", help="Release observation or follow-up ref. Repeat as needed."),
    ] = None,
    min_score: Annotated[
        float,
        typer.Option("--min-score", help="Minimum score ratio between 0 and 1."),
    ] = 0.8,
    fail_on_blocked: Annotated[
        bool,
        typer.Option(
            "--fail-on-blocked/--no-fail-on-blocked",
            help="Exit non-zero when the audit blocks promotion.",
        ),
    ] = True,
) -> None:
    """Run a Luban-inspired polish gate over an Obsidian skill card."""

    try:
        report = audit_skill_polish_candidate(
            vault_root=vault,
            skill_id=skill_id,
            peer_refs=tuple(peer_ref or ()),
            live_evidence_refs=tuple(live_evidence_ref or ()),
            install_refs=tuple(install_ref or ()),
            release_refs=tuple(release_ref or ()),
            min_score=min_score,
        )
    except ValueError as exc:
        typer.echo(f"[FAIL] skill_polish_audit: {exc}", err=True)
        raise typer.Exit(1) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_json_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_output = output.with_suffix(".md")
    markdown_output.write_text(report.to_markdown(), encoding="utf-8")
    status = "passed" if report.passed else "blocked"
    typer.echo(f"[OK] skill_polish_audit: {status}")
    typer.echo(f"[OK] score: {report.score:.1f}/{report.max_score:.1f}")
    typer.echo(f"[OK] report: {output}")
    typer.echo(f"[OK] markdown: {markdown_output}")
    if not report.passed:
        failed_checks = ", ".join(check.check_id for check in report.checks if not check.passed)
        typer.echo(f"[FAIL] blocked_checks: {failed_checks}")
        if fail_on_blocked:
            raise typer.Exit(1)


@app.command("skill-watchlist")
def skill_watchlist(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to receive the watchlist."),
    ] = Path("autoresearch-vault"),
    source_note: Annotated[
        str,
        typer.Option(
            "--source-note",
            help="Short note describing where this external-skill scouting batch came from.",
        ),
    ] = (
        "User-provided 2026-06-15 research-skill screenshots plus live web review of "
        "SimpleMem, SkillClaw, AERS, paper-craft-skills, citation-management, and "
        "Deep-Research-skills references."
    ),
) -> None:
    """Write external research-skill candidates into the Obsidian quarantine watchlist."""

    try:
        watchlist = write_external_skill_watchlist(
            vault_root=vault,
            candidates=default_external_research_skill_candidates(),
            source_note=source_note,
        )
    except ValueError as exc:
        typer.echo(f"[FAIL] skill_watchlist: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo("[OK] skill_watchlist: written")
    typer.echo(f"[OK] watchlist_path: {watchlist.path}")
    typer.echo(f"[OK] candidate_count: {len(watchlist.candidate_ids)}")
    typer.echo("[OK] status: quarantine")


@app.command("deploy-setup")
def deploy_setup(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Configuration file to create or update.",
        ),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option(
            "--env-path",
            help="Local .env file for secrets and channel credentials.",
        ),
    ] = Path(".env"),
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider label, for example openai-compatible."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="OpenAI-compatible API base URL."),
    ] = None,
    model_name: Annotated[
        str | None,
        typer.Option("--model-name", help="Model name to use for first deployment."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="LLM API key. Stored only in .env."),
    ] = None,
    wechat: Annotated[
        bool | None,
        typer.Option("--wechat/--no-wechat", help="Configure the WeChat channel."),
    ] = None,
    wechat_webhook_url: Annotated[
        str | None,
        typer.Option("--wechat-webhook-url", help="WeChat webhook URL stored in .env."),
    ] = None,
    wechat_app_id: Annotated[
        str | None,
        typer.Option("--wechat-app-id", help="WeChat app ID stored in .env."),
    ] = None,
    wechat_app_secret: Annotated[
        str | None,
        typer.Option("--wechat-app-secret", help="WeChat app secret stored in .env."),
    ] = None,
    wechat_qr: Annotated[
        bool,
        typer.Option(
            "--wechat-qr/--no-wechat-qr",
            help="Configure WeChat through QR adapter onboarding instead of requiring a webhook.",
        ),
    ] = False,
    wechat_openclaw_target: Annotated[
        str | None,
        typer.Option(
            "--wechat-openclaw-target",
            help="Optional OpenClaw WeChat target for outbound self-tests and digests.",
        ),
    ] = None,
    run_wechat_qr_setup: Annotated[
        bool | None,
        typer.Option(
            "--run-wechat-qr-setup/--skip-wechat-qr-setup",
            help="Run the upstream WeChat QR setup command after writing AI-Researcher config.",
        ),
    ] = None,
    feishu: Annotated[
        bool | None,
        typer.Option("--feishu/--no-feishu", help="Configure the Feishu channel."),
    ] = None,
    feishu_webhook_url: Annotated[
        str | None,
        typer.Option("--feishu-webhook-url", help="Feishu webhook URL stored in .env."),
    ] = None,
    feishu_app_id: Annotated[
        str | None,
        typer.Option("--feishu-app-id", help="Feishu app ID stored in .env."),
    ] = None,
    feishu_app_secret: Annotated[
        str | None,
        typer.Option("--feishu-app-secret", help="Feishu app secret stored in .env."),
    ] = None,
    feishu_connection_mode: Annotated[
        str | None,
        typer.Option(
            "--feishu-connection-mode",
            help="Feishu mode: websocket/app credentials by default, or webhook fallback.",
        ),
    ] = None,
    feishu_home_chat_id: Annotated[
        str | None,
        typer.Option(
            "--feishu-home-chat-id",
            help="Optional Feishu/Lark chat_id for direct app-credential digest delivery.",
        ),
    ] = None,
    feishu_allowed_users: Annotated[
        str | None,
        typer.Option("--feishu-allowed-users", help="Optional comma-separated Feishu operator IDs."),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Fail on missing required inputs instead of prompting."),
    ] = False,
    run_channel_test: Annotated[
        bool | None,
        typer.Option(
            "--run-channel-test/--skip-channel-test",
            help="Send a real setup channel self-test after writing channel config.",
        ),
    ] = None,
    channel_test_output: Annotated[
        Path,
        typer.Option(
            "--channel-test-output",
            help="JSON result path for the setup channel self-test.",
        ),
    ] = Path(".airesearcher/channels/test-result.json"),
    channel_test_timeout_seconds: Annotated[
        float,
        typer.Option("--channel-test-timeout-seconds", min=1.0, help="Channel test timeout."),
    ] = 10.0,
) -> None:
    """Run first-deploy setup for model API credentials and chat channels."""

    existing_config = _load_or_default_config(config_path)
    existing_env = _read_env_file(env_path)
    llm_defaults = existing_config.deployment.llm
    provider_value = _required_value(
        provider,
        prompt="LLM provider label",
        default=existing_env.get("AUTORESEARCH_LLM_PROVIDER") or llm_defaults.provider,
        non_interactive=non_interactive,
    )
    base_url_value = _required_value(
        base_url,
        prompt="LLM API base URL",
        default=existing_env.get("AUTORESEARCH_LLM_BASE_URL") or llm_defaults.base_url,
        non_interactive=non_interactive,
    )
    model_name_value = _required_value(
        model_name,
        prompt="LLM model name",
        default=existing_env.get("AUTORESEARCH_LLM_MODEL_NAME") or llm_defaults.model_name,
        non_interactive=non_interactive,
    )
    api_key_value = _required_value(
        api_key,
        prompt="LLM API key",
        default=existing_env.get("AUTORESEARCH_LLM_API_KEY"),
        hide_input=True,
        non_interactive=non_interactive,
    )

    wechat_enabled = _confirm_if_missing(
        wechat if wechat is not None else existing_config.deployment.wechat.enabled,
        prompt="Configure WeChat channel?",
        non_interactive=non_interactive,
    )
    feishu_enabled = _confirm_if_missing(
        feishu if feishu is not None else existing_config.deployment.feishu.enabled,
        prompt="Configure Feishu channel?",
        non_interactive=non_interactive,
    )

    wechat_values = _channel_values(
        enabled=wechat_enabled,
        channel_name="WeChat",
        webhook_url=wechat_webhook_url or existing_env.get("AUTORESEARCH_WECHAT_WEBHOOK_URL"),
        app_id=wechat_app_id or existing_env.get("AUTORESEARCH_WECHAT_APP_ID"),
        app_secret=wechat_app_secret or existing_env.get("AUTORESEARCH_WECHAT_APP_SECRET"),
        qr_setup=wechat_qr
        or existing_env.get("AUTORESEARCH_WECHAT_CONNECTION_MODE", "").casefold() == "qr",
        home_chat_id=wechat_openclaw_target
        or existing_env.get("AUTORESEARCH_WECHAT_OPENCLAW_TARGET"),
        non_interactive=non_interactive,
    )
    feishu_values = _channel_values(
        enabled=feishu_enabled,
        channel_name="Feishu",
        webhook_url=feishu_webhook_url or existing_env.get("AUTORESEARCH_FEISHU_WEBHOOK_URL"),
        app_id=feishu_app_id or existing_env.get("AUTORESEARCH_FEISHU_APP_ID"),
        app_secret=feishu_app_secret or existing_env.get("AUTORESEARCH_FEISHU_APP_SECRET"),
        connection_mode=(
            feishu_connection_mode
            or existing_env.get("AUTORESEARCH_FEISHU_CONNECTION_MODE")
            or existing_config.deployment.feishu.connection_mode
        ),
        home_chat_id=feishu_home_chat_id
        or existing_env.get("AUTORESEARCH_FEISHU_HOME_CHAT_ID"),
        allowed_users=feishu_allowed_users or existing_env.get("AUTORESEARCH_FEISHU_ALLOWED_USERS"),
        non_interactive=non_interactive,
    )
    channels_to_test = _setup_channels_to_test(
        wechat_enabled=wechat_enabled,
        feishu_enabled=feishu_enabled,
    )
    if run_channel_test and not channels_to_test:
        raise typer.BadParameter("--run-channel-test requires at least one enabled channel")

    config = existing_config
    config = config.model_copy(
        update={
            "deployment": DeploymentConfig(
                llm=ModelProviderConfig(
                    provider=provider_value,
                    base_url=base_url_value,
                    model_name=model_name_value,
                    api_key_env="AUTORESEARCH_LLM_API_KEY",
                ),
                wechat=MessagingChannelConfig(
                    enabled=wechat_enabled,
                    connection_mode=str(wechat_values["connection_mode"])
                    if wechat_values["connection_mode"]
                    else None,
                    webhook_url_env="AUTORESEARCH_WECHAT_WEBHOOK_URL"
                    if wechat_values["webhook_url"]
                    else None,
                    app_id_env="AUTORESEARCH_WECHAT_APP_ID" if wechat_values["app_id"] else None,
                    app_secret_env=(
                        "AUTORESEARCH_WECHAT_APP_SECRET"
                        if wechat_values["app_secret"]
                        else None
                    ),
                    qr_setup_command_env=(
                        "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND"
                        if wechat_values["connection_mode"] == "qr"
                        else None
                    ),
                    session_path_env=(
                        "AUTORESEARCH_WECHAT_SESSION_PATH"
                        if wechat_values["connection_mode"] == "qr"
                        else None
                    ),
                    home_chat_id_env=(
                        "AUTORESEARCH_WECHAT_OPENCLAW_TARGET"
                        if wechat_values["home_chat_id"]
                        else None
                    ),
                ),
                feishu=MessagingChannelConfig(
                    enabled=feishu_enabled,
                    connection_mode=str(feishu_values["connection_mode"])
                    if feishu_values["connection_mode"]
                    else None,
                    webhook_url_env="AUTORESEARCH_FEISHU_WEBHOOK_URL"
                    if feishu_values["webhook_url"]
                    else None,
                    app_id_env="AUTORESEARCH_FEISHU_APP_ID" if feishu_values["app_id"] else None,
                    app_secret_env=(
                        "AUTORESEARCH_FEISHU_APP_SECRET"
                        if feishu_values["app_secret"]
                        else None
                    ),
                    home_chat_id_env=(
                        "AUTORESEARCH_FEISHU_HOME_CHAT_ID"
                        if feishu_values["home_chat_id"]
                        else None
                    ),
                    allowed_users_env=(
                        "AUTORESEARCH_FEISHU_ALLOWED_USERS"
                        if feishu_values["allowed_users"]
                        else None
                    ),
                ),
            )
        }
    )

    parser = ConfigParser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    parser.write_file(config, config_path)

    env_values = {
        "AUTORESEARCH_LLM_PROVIDER": provider_value,
        "AUTORESEARCH_LLM_BASE_URL": base_url_value,
        "AUTORESEARCH_LLM_MODEL_NAME": model_name_value,
        "AUTORESEARCH_LLM_API_KEY": api_key_value,
        "AUTORESEARCH_WECHAT_CONNECTION_MODE": str(wechat_values["connection_mode"])
        if wechat_values["connection_mode"]
        else None,
        "AUTORESEARCH_WECHAT_WEBHOOK_URL": wechat_values["webhook_url"],
        "AUTORESEARCH_WECHAT_APP_ID": wechat_values["app_id"],
        "AUTORESEARCH_WECHAT_APP_SECRET": wechat_values["app_secret"],
        "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND": WECHAT_QR_SETUP_COMMAND
        if wechat_values["connection_mode"] == "qr"
        else None,
        "AUTORESEARCH_WECHAT_QR_LOGIN_COMMAND": WECHAT_QR_LOGIN_COMMAND
        if wechat_values["connection_mode"] == "qr"
        else None,
        "AUTORESEARCH_WECHAT_SESSION_PATH": WECHAT_QR_SESSION_PATH
        if wechat_values["connection_mode"] == "qr"
        else None,
        "AUTORESEARCH_WECHAT_SETUP_STATUS_PATH": WECHAT_QR_SETUP_STATUS_PATH
        if wechat_values["connection_mode"] == "qr"
        else None,
        "AUTORESEARCH_WECHAT_OPENCLAW_CHANNEL": WECHAT_OPENCLAW_CHANNEL
        if wechat_values["connection_mode"] == "qr"
        else None,
        "AUTORESEARCH_WECHAT_OPENCLAW_TARGET": wechat_values["home_chat_id"],
        "AUTORESEARCH_WECHAT_OPENCLAW_MESSAGE_COMMAND": OPENCLAW_MESSAGE_SEND_COMMAND
        if wechat_values["connection_mode"] == "qr"
        else None,
        "AUTORESEARCH_FEISHU_CONNECTION_MODE": str(feishu_values["connection_mode"])
        if feishu_values["connection_mode"]
        else None,
        "AUTORESEARCH_FEISHU_BASE_URL": FEISHU_DEFAULT_BASE_URL
        if feishu_values["connection_mode"] and feishu_values["connection_mode"] != "webhook"
        else None,
        "AUTORESEARCH_FEISHU_WEBHOOK_URL": feishu_values["webhook_url"],
        "AUTORESEARCH_FEISHU_APP_ID": feishu_values["app_id"],
        "AUTORESEARCH_FEISHU_APP_SECRET": feishu_values["app_secret"],
        "AUTORESEARCH_FEISHU_HOME_CHAT_ID": feishu_values["home_chat_id"],
        "AUTORESEARCH_FEISHU_ALLOWED_USERS": feishu_values["allowed_users"],
    }
    env_example_path, env_example_created = _ensure_env_example(env_path)
    _merge_env_file(env_path, env_values)

    typer.echo(f"[OK] config written: {config_path}")
    typer.echo(f"[OK] env written: {env_path}")
    typer.echo(
        f"[OK] env template {'created' if env_example_created else 'ready'}: {env_example_path}"
    )
    typer.echo(f"[OK] model: {provider_value} / {model_name_value}")
    typer.echo(f"[OK] wechat: {_channel_summary(wechat_enabled, wechat_values)}")
    typer.echo(f"[OK] feishu: {_channel_summary(feishu_enabled, feishu_values)}")
    if wechat_enabled and wechat_values["connection_mode"] == "qr":
        typer.echo(f"[NEXT] wechat_qr_setup: {WECHAT_QR_SETUP_COMMAND}")
        if run_wechat_qr_setup:
            typer.echo("[RUN] wechat_qr_setup: starting QR adapter setup now")
            _run_wechat_qr_setup(status_path=env_path.parent / WECHAT_QR_SETUP_STATUS_PATH)
    if run_channel_test and channels_to_test:
        channel_test_path = _setup_relative_path(env_path, channel_test_output)
        typer.echo("[RUN] channel_test: sending setup delivery self-test now")
        records = _run_channel_delivery_self_test(
            env_path=env_path,
            output=channel_test_path,
            channels=channels_to_test,
            timeout_seconds=channel_test_timeout_seconds,
            message="AI-Researcher setup channel self-test",
            require_sent=True,
        )
        for record in records:
            typer.echo(
                f"[PUSH] channel={record.channel} status={record.status} "
                f"detail={record.detail}"
            )
        typer.echo(f"[OK] channel_test: {channel_test_path}")
        if any(record.status != "sent" for record in records):
            _echo_channel_test_next_actions(records, env_path=env_path)
            typer.echo("[FAIL] channel_test: at least one channel was not sent", err=True)
            raise typer.Exit(code=1)
    _echo_post_setup_next_steps(
        wechat_enabled=wechat_enabled,
        feishu_enabled=feishu_enabled,
    )


@app.command("setup")
def setup(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Configuration file to create or update.",
        ),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file for secrets and channel credentials."),
    ] = Path(".env"),
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider label, for example openai-compatible."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="OpenAI-compatible API base URL."),
    ] = None,
    model_name: Annotated[
        str | None,
        typer.Option("--model-name", help="Model name to use for first deployment."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="LLM API key. Stored only in .env."),
    ] = None,
    wechat: Annotated[
        bool | None,
        typer.Option("--wechat/--no-wechat", help="Configure the WeChat channel."),
    ] = None,
    wechat_webhook_url: Annotated[
        str | None,
        typer.Option("--wechat-webhook-url", help="WeChat webhook URL stored in .env."),
    ] = None,
    wechat_app_id: Annotated[
        str | None,
        typer.Option("--wechat-app-id", help="WeChat app ID stored in .env."),
    ] = None,
    wechat_app_secret: Annotated[
        str | None,
        typer.Option("--wechat-app-secret", help="WeChat app secret stored in .env."),
    ] = None,
    wechat_qr: Annotated[
        bool,
        typer.Option(
            "--wechat-qr/--no-wechat-qr",
            help="Configure WeChat through QR adapter onboarding instead of requiring a webhook.",
        ),
    ] = False,
    wechat_openclaw_target: Annotated[
        str | None,
        typer.Option(
            "--wechat-openclaw-target",
            help="Optional OpenClaw WeChat target for outbound self-tests and digests.",
        ),
    ] = None,
    run_wechat_qr_setup: Annotated[
        bool | None,
        typer.Option(
            "--run-wechat-qr-setup/--skip-wechat-qr-setup",
            help="Run the upstream WeChat QR setup command after writing AI-Researcher config.",
        ),
    ] = None,
    feishu: Annotated[
        bool | None,
        typer.Option("--feishu/--no-feishu", help="Configure the Feishu channel."),
    ] = None,
    feishu_webhook_url: Annotated[
        str | None,
        typer.Option("--feishu-webhook-url", help="Feishu webhook URL stored in .env."),
    ] = None,
    feishu_app_id: Annotated[
        str | None,
        typer.Option("--feishu-app-id", help="Feishu app ID stored in .env."),
    ] = None,
    feishu_app_secret: Annotated[
        str | None,
        typer.Option("--feishu-app-secret", help="Feishu app secret stored in .env."),
    ] = None,
    feishu_connection_mode: Annotated[
        str | None,
        typer.Option(
            "--feishu-connection-mode",
            help="Feishu mode: websocket/app credentials by default, or webhook fallback.",
        ),
    ] = None,
    feishu_home_chat_id: Annotated[
        str | None,
        typer.Option(
            "--feishu-home-chat-id",
            help="Optional Feishu/Lark chat_id for direct app-credential digest delivery.",
        ),
    ] = None,
    feishu_allowed_users: Annotated[
        str | None,
        typer.Option("--feishu-allowed-users", help="Optional comma-separated Feishu operator IDs."),
    ] = None,
    run_channel_test: Annotated[
        bool | None,
        typer.Option(
            "--run-channel-test/--skip-channel-test",
            help="Send a real setup channel self-test after writing channel config.",
        ),
    ] = None,
    channel_test_output: Annotated[
        Path,
        typer.Option(
            "--channel-test-output",
            help="JSON result path for the setup channel self-test.",
        ),
    ] = Path(".airesearcher/channels/test-result.json"),
    channel_test_timeout_seconds: Annotated[
        float,
        typer.Option("--channel-test-timeout-seconds", min=1.0, help="Channel test timeout."),
    ] = 10.0,
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to initialize."),
    ] = Path("autoresearch-vault"),
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for vault setup and runtime examples."),
    ] = "ai_researcher_system",
    integrations_dir: Annotated[
        Path,
        typer.Option("--integrations-dir", help="Directory for generated integration manifests."),
    ] = Path("integrations"),
    commands_dir: Annotated[
        Path,
        typer.Option("--commands-dir", help="Directory for slash command templates."),
    ] = Path(".airesearcher/commands"),
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Fail on missing required inputs instead of prompting."),
    ] = False,
    init_obsidian: Annotated[
        bool,
        typer.Option(
            "--init-obsidian/--skip-obsidian",
            help="Create or refresh safe Obsidian vault assets.",
        ),
    ] = True,
    init_integrations: Annotated[
        bool,
        typer.Option(
            "--init-integrations/--skip-integrations",
            help="Write channel adapter, OpenCode, and ScanSci PDF manifests.",
        ),
    ] = True,
    init_slash: Annotated[
        bool,
        typer.Option(
            "--init-slash/--skip-slash",
            help="Write local slash command templates.",
        ),
    ] = True,
) -> None:
    """Run the guided first-deploy configuration wizard."""

    if not non_interactive:
        wizard = _collect_setup_wizard_values(
            config_path=config_path,
            env_path=env_path,
            provider=provider,
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            wechat=wechat,
            wechat_webhook_url=wechat_webhook_url,
            wechat_app_id=wechat_app_id,
            wechat_app_secret=wechat_app_secret,
            wechat_qr=wechat_qr,
            wechat_openclaw_target=wechat_openclaw_target,
            run_wechat_qr_setup=run_wechat_qr_setup,
            feishu=feishu,
            feishu_webhook_url=feishu_webhook_url,
            feishu_app_id=feishu_app_id,
            feishu_app_secret=feishu_app_secret,
            feishu_connection_mode=feishu_connection_mode,
            feishu_home_chat_id=feishu_home_chat_id,
            feishu_allowed_users=feishu_allowed_users,
            run_channel_test=run_channel_test,
        )
        provider = wizard["provider"]
        base_url = wizard["base_url"]
        model_name = wizard["model_name"]
        api_key = wizard["api_key"]
        wechat = wizard["wechat"]
        wechat_webhook_url = wizard["wechat_webhook_url"]
        wechat_app_id = wizard["wechat_app_id"]
        wechat_app_secret = wizard["wechat_app_secret"]
        wechat_qr = bool(wizard["wechat_qr"])
        wechat_openclaw_target = wizard["wechat_openclaw_target"]
        run_wechat_qr_setup = bool(wizard["run_wechat_qr_setup"])
        feishu = wizard["feishu"]
        feishu_webhook_url = wizard["feishu_webhook_url"]
        feishu_app_id = wizard["feishu_app_id"]
        feishu_app_secret = wizard["feishu_app_secret"]
        feishu_connection_mode = str(wizard["feishu_connection_mode"] or "")
        feishu_home_chat_id = wizard["feishu_home_chat_id"]
        feishu_allowed_users = wizard["feishu_allowed_users"]
        run_channel_test = bool(wizard["run_channel_test"])
        non_interactive = True

    deploy_setup(
        config_path=config_path,
        env_path=env_path,
        provider=provider,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        wechat=wechat,
        wechat_webhook_url=wechat_webhook_url,
        wechat_app_id=wechat_app_id,
        wechat_app_secret=wechat_app_secret,
        wechat_qr=wechat_qr,
        wechat_openclaw_target=wechat_openclaw_target,
        run_wechat_qr_setup=run_wechat_qr_setup,
        feishu=feishu,
        feishu_webhook_url=feishu_webhook_url,
        feishu_app_id=feishu_app_id,
        feishu_app_secret=feishu_app_secret,
        feishu_connection_mode=feishu_connection_mode,
        feishu_home_chat_id=feishu_home_chat_id,
        feishu_allowed_users=feishu_allowed_users,
        non_interactive=non_interactive,
        run_channel_test=run_channel_test,
        channel_test_output=channel_test_output,
        channel_test_timeout_seconds=channel_test_timeout_seconds,
    )
    if init_obsidian:
        create_obsidian_vault_assets(
            vault_root=vault,
            project_id=project_id,
            write_local_snippet=False,
        )
        typer.echo(f"[OK] obsidian_vault: {vault}")
    if init_integrations:
        channel_adapters_manifest = write_channel_adapter_manifest(
            integrations_dir / "channels" / "adapters.json"
        )
        opencode_manifest = write_opencode_code_agent_manifest(
            integrations_dir / "opencode" / "code-agent.json"
        )
        scansci_manifest = write_scansci_pdf_manifest(
            integrations_dir / "scansci-pdf" / "pdf-source.json"
        )
        typer.echo(f"[OK] channel_adapters_manifest: {channel_adapters_manifest}")
        typer.echo(f"[OK] opencode_manifest: {opencode_manifest}")
        typer.echo(f"[OK] scansci_pdf_manifest: {scansci_manifest}")
    if init_slash:
        written, skipped = _write_slash_command_templates(commands_dir, force=False)
        typer.echo(f"[OK] slash commands written: {written}")
        typer.echo(f"[OK] slash commands skipped: {skipped}")
        typer.echo(f"[OK] slash_commands_dir: {commands_dir}")
    _echo_setup_next_steps(
        permission_mode=RuntimePermissionMode.APPROVE_DANGEROUS,
        deliverables_dir=Path("outputs"),
    )


@app.command("monitor")
def monitor(
    agent_log: Annotated[
        Path,
        typer.Option("--agent-log", help="Agent change log to summarize."),
    ] = Path("Agent.md"),
    sessions_state: Annotated[
        Path,
        typer.Option("--sessions-state", help="Agent session coordination state file."),
    ] = DEFAULT_AGENT_SESSIONS_PATH,
    runtime_state: Annotated[
        Path,
        typer.Option("--runtime-state", help="Runtime approval queue state file."),
    ] = DEFAULT_RUNTIME_APPROVALS_PATH,
    scheduler_state: Annotated[
        Path,
        typer.Option("--scheduler-state", help="Scheduler task state file."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    outputs_dir: Annotated[
        Path,
        typer.Option("--outputs-dir", help="Root output bundle directory to preview."),
    ] = Path("outputs"),
    cycle_summary: Annotated[
        Path | None,
        typer.Option("--cycle-summary", help="Optional cycle-summary.json to inspect."),
    ] = None,
    max_agent_entries: Annotated[
        int,
        typer.Option("--max-agent-entries", min=1, help="Recent Agent.md entries to show."),
    ] = 4,
    max_diff_lines: Annotated[
        int,
        typer.Option("--max-diff-lines", min=0, help="Maximum git diff preview lines."),
    ] = 80,
    show_diff: Annotated[
        bool,
        typer.Option("--show-diff/--no-diff", help="Show git status and diff preview."),
    ] = True,
    watch: Annotated[
        bool,
        typer.Option("--watch/--no-watch", help="Refresh the dashboard until interrupted."),
    ] = False,
    refresh_seconds: Annotated[
        float,
        typer.Option("--refresh-seconds", min=0.5, help="Refresh interval for --watch."),
    ] = 5.0,
) -> None:
    """Render the operator console for agent flow, changes, and output previews."""

    if watch:
        try:
            while True:
                _render_operator_monitor(
                    agent_log=agent_log,
                    sessions_state=sessions_state,
                    runtime_state=runtime_state,
                    scheduler_state=scheduler_state,
                    outputs_dir=outputs_dir,
                    cycle_summary=cycle_summary,
                    max_agent_entries=max_agent_entries,
                    max_diff_lines=max_diff_lines,
                    show_diff=show_diff,
                    clear=True,
                )
                time.sleep(refresh_seconds)
        except KeyboardInterrupt:
            typer.echo("\n[OK] monitor stopped")
        return

    _render_operator_monitor(
        agent_log=agent_log,
        sessions_state=sessions_state,
        runtime_state=runtime_state,
        scheduler_state=scheduler_state,
        outputs_dir=outputs_dir,
        cycle_summary=cycle_summary,
        max_agent_entries=max_agent_entries,
        max_diff_lines=max_diff_lines,
        show_diff=show_diff,
        clear=False,
    )


@app.command("literature-refresh")
def literature_refresh(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to read and update."),
    ] = Path("autoresearch-vault"),
    cache: Annotated[
        Path,
        typer.Option("--cache", help="Retrieval cache directory."),
    ] = Path(".cache/literature"),
    max_queries: Annotated[
        int,
        typer.Option("--max-queries", min=1, help="Maximum optimized queries to run."),
    ] = 5,
    max_results_per_source: Annotated[
        int,
        typer.Option("--max-results-per-source", min=1, help="Maximum papers per source/query."),
    ] = 20,
    cache_ttl_hours: Annotated[
        int,
        typer.Option("--cache-ttl-hours", min=1, help="Cache TTL for source responses."),
    ] = 24,
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Optional .env file for literature API keys."),
    ] = Path(".env"),
) -> None:
    """Run real online literature refresh and write an Obsidian summary."""

    try:
        _load_optional_env(env_path)
        report = run_daily_literature_refresh(
            vault_root=vault,
            cache_root=cache,
            config=LiteratureRefreshConfig(
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
                cache_ttl_hours=cache_ttl_hours,
            ),
        )
    except Exception as exc:
        typer.echo(f"[FAIL] literature refresh failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _echo_fetches(report.fetches)
    if not report.documents:
        typer.echo("[FAIL] literature refresh returned no source-backed documents", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"[OK] queries: {len(report.queries)}")
    typer.echo(f"[OK] documents: {len(report.documents)}")
    if report.summary_path is not None:
        typer.echo(f"[OK] summary: {report.summary_path}")


@app.command("inspiration-refresh")
def inspiration_refresh(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to update."),
    ] = Path("autoresearch-vault"),
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="JSON report output path."),
    ] = Path("runs/inspiration/latest.json"),
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file written by setup for channel credentials."),
    ] = Path(".env"),
    query: Annotated[
        list[str] | None,
        typer.Option("--query", "-q", help="Inspiration query. Repeat for multiple queries."),
    ] = None,
    max_queries: Annotated[
        int,
        typer.Option("--max-queries", min=1, help="Maximum broad-source queries to run."),
    ] = 3,
    max_results_per_source: Annotated[
        int,
        typer.Option("--max-results-per-source", min=1, help="Maximum items per source/query."),
    ] = 5,
    push: Annotated[
        bool,
        typer.Option("--push/--no-push", help="Send the digest to configured operator channels."),
    ] = False,
    push_channel: Annotated[
        list[str] | None,
        typer.Option("--push-channel", help="Operator channel to notify. Repeat for multiple channels."),
    ] = None,
    push_timeout_seconds: Annotated[
        float,
        typer.Option("--push-timeout-seconds", min=1.0, help="Channel delivery timeout."),
    ] = 10.0,
) -> None:
    """Search broad dataset/community sources and write an Obsidian-safe summary."""

    try:
        _load_optional_env(env_path)
        report = run_inspiration_refresh(
            vault_root=vault,
            queries=tuple(query or ()),
            config=InspirationRefreshConfig(
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
            ),
        )
    except Exception as exc:
        typer.echo(f"[FAIL] inspiration refresh failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    push_records: tuple[NotificationSendRecord, ...] = ()
    if push:
        push_records = send_inspiration_digest(
            report,
            channels=tuple(push_channel or ("wechat", "feishu")),
            timeout_seconds=push_timeout_seconds,
        )
    payload = report.to_json_dict()
    if push:
        payload["pushes"] = [record.to_json_dict() for record in push_records]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    for fetch in report.fetches:
        error = f" error={fetch.error}" if fetch.error else ""
        typer.echo(
            f"[FETCH] source={fetch.source} type={fetch.source_type} query={fetch.query!r} "
            f"items={fetch.result_count}{error}"
        )
    typer.echo(f"[OK] queries: {len(report.queries)}")
    typer.echo(f"[OK] inspiration_items: {len(report.items)}")
    typer.echo(f"[OK] report: {output}")
    if report.summary_path is not None:
        typer.echo(f"[OK] summary: {report.summary_path}")
    for record in push_records:
        typer.echo(
            f"[PUSH] channel={record.channel} status={record.status} "
            f"detail={record.detail}"
        )
    if not report.items:
        typer.echo("[FAIL] inspiration refresh returned no source-backed items", err=True)
        raise typer.Exit(code=1)


@channels_app.command("test")
def channel_test(
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file written by setup for channel credentials."),
    ] = Path(".env"),
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="JSON self-test result output path."),
    ] = Path(".airesearcher/channels/test-result.json"),
    channel: Annotated[
        list[str] | None,
        typer.Option("--channel", help="Operator channel to test. Repeat for multiple channels."),
    ] = None,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0, help="Channel delivery timeout."),
    ] = 10.0,
    message: Annotated[
        str,
        typer.Option("--message", help="Self-test message body."),
    ] = "AI-Researcher channel self-test",
    require_sent: Annotated[
        bool,
        typer.Option(
            "--require-sent/--allow-skipped",
            help="Exit non-zero unless every selected channel reports sent.",
        ),
    ] = False,
) -> None:
    """Send a setup-channel self-test through the same notification path used by pushes."""

    selected_channels = tuple(channel or ("wechat", "feishu"))
    records = _run_channel_delivery_self_test(
        env_path=env_path,
        output=output,
        channels=selected_channels,
        timeout_seconds=timeout_seconds,
        message=message,
        require_sent=require_sent,
    )
    for record in records:
        typer.echo(
            f"[PUSH] channel={record.channel} status={record.status} "
            f"detail={record.detail}"
        )
    typer.echo(f"[OK] channel_test: {output}")
    if require_sent and any(record.status != "sent" for record in records):
        _echo_channel_test_next_actions(records, env_path=env_path)
        typer.echo("[FAIL] channel_test: at least one channel was not sent", err=True)
        raise typer.Exit(code=1)


@channels_app.command("bind-target")
def channel_bind_target(
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file written by setup for channel credentials."),
    ] = Path(".env"),
    channel: Annotated[
        str,
        typer.Option("--channel", help="Channel to bind: wechat or feishu."),
    ] = "wechat",
    target: Annotated[
        str | None,
        typer.Option("--target", help="OpenClaw target or Feishu/Lark home chat ID."),
    ] = None,
) -> None:
    """Bind a post-pairing channel target without hand-editing `.env`."""

    normalized = channel.casefold().strip()
    target_value = (target or typer.prompt("Channel target")).strip()
    if not target_value:
        raise typer.BadParameter("--target is required")
    if normalized in {"wechat", "weixin", "openclaw-weixin"}:
        _merge_env_file(
            env_path,
            {
                "AUTORESEARCH_WECHAT_CONNECTION_MODE": "qr",
                "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND": WECHAT_QR_SETUP_COMMAND,
                "AUTORESEARCH_WECHAT_QR_LOGIN_COMMAND": WECHAT_QR_LOGIN_COMMAND,
                "AUTORESEARCH_WECHAT_SESSION_PATH": WECHAT_QR_SESSION_PATH,
                "AUTORESEARCH_WECHAT_SETUP_STATUS_PATH": WECHAT_QR_SETUP_STATUS_PATH,
                "AUTORESEARCH_WECHAT_OPENCLAW_CHANNEL": WECHAT_OPENCLAW_CHANNEL,
                "AUTORESEARCH_WECHAT_OPENCLAW_TARGET": target_value,
                "AUTORESEARCH_WECHAT_OPENCLAW_MESSAGE_COMMAND": OPENCLAW_MESSAGE_SEND_COMMAND,
            },
        )
        typer.echo(f"[OK] channel_target: wechat -> {target_value}")
        typer.echo("[NEXT] channel_test: airesearcher channels test --channel wechat --require-sent")
        return
    if normalized in {"feishu", "lark"}:
        _merge_env_file(env_path, {"AUTORESEARCH_FEISHU_HOME_CHAT_ID": target_value})
        typer.echo(f"[OK] channel_target: feishu -> {target_value}")
        typer.echo("[NEXT] channel_test: airesearcher channels test --channel feishu --require-sent")
        return
    msg = f"unsupported channel for target binding: {channel}"
    raise typer.BadParameter(msg)


def _channel_test_report(message: str) -> InspirationRefreshReport:
    timestamp = datetime.now(timezone.utc)
    return InspirationRefreshReport(
        queries=("channel self-test",),
        fetches=(),
        items=(
            InspirationItem(
                source="operator_self_test",
                source_type="channel_test",
                title=message,
                url="",
                query="channel self-test",
                summary="Operator channel delivery self-test.",
                score=1.0,
                retrieved_at=timestamp,
            ),
        ),
        summary_path=None,
    )


def _run_channel_delivery_self_test(
    *,
    env_path: Path,
    output: Path,
    channels: tuple[str, ...],
    timeout_seconds: float,
    message: str,
    require_sent: bool,
) -> tuple[NotificationSendRecord, ...]:
    environment = _merged_optional_env(env_path)
    report = _channel_test_report(message)
    records = send_inspiration_digest(
        report,
        channels=channels,
        env=environment,
        timeout_seconds=timeout_seconds,
    )
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
        "require_sent": require_sent,
        "records": [record.to_json_dict() for record in records],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return records


def _echo_channel_test_next_actions(
    records: Iterable[NotificationSendRecord],
    *,
    env_path: Path,
) -> None:
    emitted: set[str] = set()
    env_arg = _command_path(env_path)
    for record in records:
        channel = record.channel.casefold()
        detail = record.detail.casefold()
        if (
            channel in {"wechat", "weixin", "wecom"}
            and "autoresearch_wechat_openclaw_target" in detail
            and "bind_wechat_target" not in emitted
        ):
            typer.echo(
                "[NEXT] bind_wechat_target: "
                f"airesearcher channels bind-target --channel wechat --env-path {env_arg}"
            )
            emitted.add("bind_wechat_target")
        if (
            channel in {"feishu", "lark"}
            and "autoresearch_feishu_home_chat_id" in detail
            and "bind_feishu_target" not in emitted
        ):
            typer.echo(
                "[NEXT] bind_feishu_target: "
                f"airesearcher channels bind-target --channel feishu --env-path {env_arg}"
            )
            emitted.add("bind_feishu_target")


@app.command("readiness")
def readiness(
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file written by setup."),
    ] = Path(".env"),
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Configuration file written by setup."),
    ] = Path("config.yaml"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root expected by the daily loop."),
    ] = Path("autoresearch-vault"),
    outputs_dir: Annotated[
        Path,
        typer.Option("--outputs-dir", help="Directory where publication artifacts are written."),
    ] = Path("outputs"),
    scheduler_state: Annotated[
        Path,
        typer.Option("--scheduler-state", help="Local scheduler follow-up state file."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    channel_test_result: Annotated[
        Path,
        typer.Option(
            "--channel-test-result",
            help="Latest `airesearcher channels test` JSON result file.",
        ),
    ] = Path(".airesearcher/channels/test-result.json"),
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="JSON readiness report path."),
    ] = Path(".airesearcher/readiness/report.json"),
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=60, help="Planned unattended loop interval."),
    ] = 86400,
    push_inspiration: Annotated[
        bool,
        typer.Option(
            "--push-inspiration/--no-push-inspiration",
            help="Check operator-channel readiness for inspiration pushes.",
        ),
    ] = True,
    require_channel_config: Annotated[
        bool,
        typer.Option(
            "--require-channel-config/--allow-missing-channel",
            help="Fail readiness when push is enabled but no WeChat/Feishu channel is configured.",
        ),
    ] = False,
    require_channel_sent: Annotated[
        bool,
        typer.Option(
            "--require-channel-sent/--allow-untested-channel",
            help="Fail readiness unless the latest channel self-test includes a sent record.",
        ),
    ] = False,
) -> None:
    """Write a preflight report for the 24h unattended research loop."""

    env_values = _read_env_file(env_path)
    checks: list[dict[str, object]] = []

    _add_readiness_check(
        checks,
        check_id="env_file",
        status="pass" if env_path.exists() else "fail",
        detail=f"env file found at {env_path}" if env_path.exists() else f"missing env file: {env_path}",
        evidence={"path": env_path.as_posix()},
    )
    _add_readiness_result(checks, "llm_credentials", _llm_readiness(env_values))
    _add_readiness_result(checks, "config_file", _config_file_readiness(config_path))
    _add_readiness_check(
        checks,
        check_id="vault",
        status="pass" if vault.is_dir() else "fail",
        detail=f"vault directory found at {vault}" if vault.is_dir() else f"missing vault directory: {vault}",
        evidence={"path": vault.as_posix()},
    )
    _add_readiness_result(checks, "outputs_dir", _writable_directory_readiness(outputs_dir))
    _add_readiness_result(
        checks,
        "daily_loop",
        _daily_loop_readiness(
            interval_seconds=interval_seconds,
            push_inspiration=push_inspiration,
        ),
    )
    _add_readiness_result(
        checks,
        "operator_channels",
        _operator_channel_readiness(
            env_values,
            push_inspiration=push_inspiration,
            require_channel_config=require_channel_config,
        ),
    )
    _add_readiness_result(
        checks,
        "channel_delivery_test",
        _channel_delivery_test_readiness(
            channel_test_result,
            push_inspiration=push_inspiration,
            require_channel_sent=require_channel_sent,
        ),
    )
    _add_readiness_result(checks, "scheduler_state", _scheduler_state_readiness(scheduler_state))

    failure_count = sum(1 for check in checks if check["status"] == "fail")
    warning_count = sum(1 for check in checks if check["status"] == "warn")
    planned_command = _readiness_daily_command(
        interval_seconds=interval_seconds,
        push_inspiration=push_inspiration,
    )
    next_actions = _readiness_next_actions(
        checks,
        planned_command=planned_command,
        config_path=config_path,
        env_path=env_path,
        channel_test_result=channel_test_result,
    )
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if failure_count == 0 else "blocked",
        "failure_count": failure_count,
        "warning_count": warning_count,
        "planned_daily_command": planned_command,
        "next_actions": next_actions,
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    for check in checks:
        status = str(check["status"])
        prefix = {"pass": "[OK]", "warn": "[WARN]", "fail": "[FAIL]"}.get(status, "[INFO]")
        typer.echo(
            f"{prefix} readiness.{check['id']}: {check['detail']}",
            err=status == "fail",
        )
    typer.echo(f"[OK] readiness_report: {output}")
    typer.echo(f"[OK] planned_daily_command: {planned_command}")
    for action in next_actions:
        typer.echo(f"[NEXT] readiness_action.{action['id']}: {action['command']}")
    if failure_count:
        typer.echo("[FAIL] readiness: blocked", err=True)
        raise typer.Exit(code=1)
    typer.echo("[OK] readiness: ready")


def _add_readiness_check(
    checks: list[dict[str, object]],
    *,
    check_id: str,
    status: str,
    detail: str,
    evidence: Mapping[str, object] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "status": status,
            "detail": detail,
            "evidence": dict(evidence or {}),
        }
    )


def _add_readiness_result(
    checks: list[dict[str, object]],
    check_id: str,
    result: Mapping[str, object],
) -> None:
    evidence = result.get("evidence")
    _add_readiness_check(
        checks,
        check_id=check_id,
        status=str(result.get("status") or "fail"),
        detail=str(result.get("detail") or "missing readiness detail"),
        evidence=evidence if isinstance(evidence, Mapping) else {},
    )


def _llm_readiness(env_values: Mapping[str, str]) -> dict[str, object]:
    required = {
        "AUTORESEARCH_LLM_BASE_URL": _env_or_os(env_values, "AUTORESEARCH_LLM_BASE_URL"),
        "AUTORESEARCH_LLM_MODEL_NAME": _env_or_os(env_values, "AUTORESEARCH_LLM_MODEL_NAME"),
        "AUTORESEARCH_LLM_API_KEY": _env_or_os(env_values, "AUTORESEARCH_LLM_API_KEY"),
    }
    missing = [key for key, value in required.items() if not value]
    provider = _env_or_os(env_values, "AUTORESEARCH_LLM_PROVIDER") or "openai-compatible"
    if missing:
        return {
            "status": "fail",
            "detail": "missing model API values: " + ", ".join(missing),
            "evidence": {"provider": provider, "missing": missing},
        }
    return {
        "status": "pass",
        "detail": "model API base URL, model name, and API key are configured",
        "evidence": {
            "provider": provider,
            "base_url": required["AUTORESEARCH_LLM_BASE_URL"],
            "model_name": required["AUTORESEARCH_LLM_MODEL_NAME"],
            "api_key_present": True,
        },
    }


def _config_file_readiness(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {
            "status": "fail",
            "detail": f"missing config file: {config_path}",
            "evidence": {"path": config_path.as_posix()},
        }
    try:
        ConfigParser().parse_file(config_path, model_type=SystemConfig)
    except ValueError as exc:
        return {
            "status": "fail",
            "detail": f"config file is not valid: {exc}",
            "evidence": {"path": config_path.as_posix()},
        }
    return {
        "status": "pass",
        "detail": f"config file parsed as SystemConfig: {config_path}",
        "evidence": {"path": config_path.as_posix()},
    }


def _writable_directory_readiness(directory: Path) -> dict[str, object]:
    try:
        was_present = directory.exists()
        if was_present and not directory.is_dir():
            return {
                "status": "fail",
                "detail": f"output path is not a directory: {directory}",
                "evidence": {"path": directory.as_posix()},
            }
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".airesearcher-readiness.tmp"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return {
            "status": "fail",
            "detail": f"output directory is not writable: {exc}",
            "evidence": {"path": directory.as_posix()},
        }
    created_suffix = " (created)" if not was_present else ""
    return {
        "status": "pass",
        "detail": f"output directory is writable{created_suffix}: {directory}",
        "evidence": {"path": directory.as_posix(), "created": not was_present},
    }


def _daily_loop_readiness(*, interval_seconds: int, push_inspiration: bool) -> dict[str, object]:
    command = _readiness_daily_command(
        interval_seconds=interval_seconds,
        push_inspiration=push_inspiration,
    )
    if interval_seconds < 3600:
        return {
            "status": "warn",
            "detail": "planned interval is below one hour; unattended daily runs usually use 86400 seconds",
            "evidence": {"interval_seconds": interval_seconds, "command": command},
        }
    return {
        "status": "pass",
        "detail": f"planned unattended loop interval is {interval_seconds} seconds",
        "evidence": {"interval_seconds": interval_seconds, "command": command},
    }


def _operator_channel_readiness(
    env_values: Mapping[str, str],
    *,
    push_inspiration: bool,
    require_channel_config: bool,
) -> dict[str, object]:
    if not push_inspiration:
        return {
            "status": "pass",
            "detail": "inspiration push is disabled for the planned daily command",
            "evidence": {"push_inspiration": False},
        }

    wechat_mode = _env_or_os(env_values, "AUTORESEARCH_WECHAT_CONNECTION_MODE").casefold()
    wechat_webhook = bool(_env_or_os(env_values, "AUTORESEARCH_WECHAT_WEBHOOK_URL"))
    wechat_app_credentials = bool(
        _env_or_os(env_values, "AUTORESEARCH_WECHAT_APP_ID")
        and _env_or_os(env_values, "AUTORESEARCH_WECHAT_APP_SECRET")
    )
    wechat_status_path = Path(
        _env_or_os(env_values, "AUTORESEARCH_WECHAT_SETUP_STATUS_PATH")
        or WECHAT_QR_SETUP_STATUS_PATH
    )
    wechat_openclaw_target = bool(_env_or_os(env_values, "AUTORESEARCH_WECHAT_OPENCLAW_TARGET"))
    wechat_qr_status = _wechat_qr_setup_status(wechat_status_path) if wechat_mode == "qr" else ""
    wechat_qr_ready = (
        wechat_mode == "qr" and wechat_qr_status == "completed" and wechat_openclaw_target
    )

    feishu_mode = _env_or_os(env_values, "AUTORESEARCH_FEISHU_CONNECTION_MODE").casefold()
    feishu_webhook = bool(_env_or_os(env_values, "AUTORESEARCH_FEISHU_WEBHOOK_URL"))
    feishu_app_credentials = bool(
        _env_or_os(env_values, "AUTORESEARCH_FEISHU_APP_ID")
        and _env_or_os(env_values, "AUTORESEARCH_FEISHU_APP_SECRET")
    )
    feishu_home_chat = bool(_env_or_os(env_values, "AUTORESEARCH_FEISHU_HOME_CHAT_ID"))

    ready_channels: list[str] = []
    if wechat_webhook or wechat_app_credentials or wechat_qr_ready:
        ready_channels.append("wechat")
    if feishu_webhook or (feishu_app_credentials and feishu_home_chat):
        ready_channels.append("feishu")

    evidence = {
        "push_inspiration": True,
        "wechat_mode": wechat_mode or None,
        "wechat_webhook_configured": wechat_webhook,
        "wechat_app_credentials_configured": wechat_app_credentials,
        "wechat_qr_status": wechat_qr_status or None,
        "wechat_openclaw_target_configured": wechat_openclaw_target,
        "feishu_mode": feishu_mode or None,
        "feishu_webhook_configured": feishu_webhook,
        "feishu_app_credentials_configured": feishu_app_credentials,
        "feishu_home_chat_configured": feishu_home_chat,
        "ready_channels": ready_channels,
    }
    if ready_channels:
        return {
            "status": "pass",
            "detail": "operator channel configured: " + ", ".join(ready_channels),
            "evidence": evidence,
        }
    status = "fail" if require_channel_config else "warn"
    return {
        "status": status,
        "detail": "push is enabled but no WeChat/Feishu channel is configured or QR-ready",
        "evidence": evidence,
    }


def _scheduler_state_readiness(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {
            "status": "warn",
            "detail": f"scheduler follow-up state does not exist yet: {state_path}",
            "evidence": {"path": state_path.as_posix(), "task_count": 0},
        }
    payload = _read_json_mapping(state_path)
    tasks = _mapping_list(payload.get("tasks"))
    return {
        "status": "pass",
        "detail": f"scheduler follow-up state is readable with {len(tasks)} task(s)",
        "evidence": {"path": state_path.as_posix(), "task_count": len(tasks)},
    }


def _channel_delivery_test_readiness(
    result_path: Path,
    *,
    push_inspiration: bool,
    require_channel_sent: bool,
) -> dict[str, object]:
    if not push_inspiration:
        return {
            "status": "pass",
            "detail": "inspiration push is disabled, so channel delivery self-test is not required",
            "evidence": {"push_inspiration": False, "path": result_path.as_posix()},
        }
    if not result_path.exists():
        status = "fail" if require_channel_sent else "warn"
        return {
            "status": status,
            "detail": f"no channel self-test result found at {result_path}",
            "evidence": {
                "path": result_path.as_posix(),
                "require_channel_sent": require_channel_sent,
                "sent_channels": [],
            },
        }

    payload = _read_json_mapping(result_path)
    records = _mapping_list(payload.get("records"))
    sent_channels = sorted(
        {
            str(record.get("channel"))
            for record in records
            if record.get("status") == "sent" and record.get("channel")
        }
    )
    evidence = {
        "path": result_path.as_posix(),
        "checked_at": payload.get("checked_at"),
        "record_count": len(records),
        "sent_channels": sent_channels,
        "require_channel_sent": require_channel_sent,
    }
    if sent_channels:
        return {
            "status": "pass",
            "detail": "latest channel self-test has sent delivery: " + ", ".join(sent_channels),
            "evidence": evidence,
        }
    status = "fail" if require_channel_sent else "warn"
    return {
        "status": status,
        "detail": "latest channel self-test has no sent records",
        "evidence": evidence,
    }


def _readiness_daily_command(*, interval_seconds: int, push_inspiration: bool) -> str:
    push_flag = "--push-inspiration" if push_inspiration else "--no-push-inspiration"
    return (
        "airesearcher serve --permission-mode approve-dangerous --watch --cycles 0 "
        f"--interval-seconds {interval_seconds} {push_flag}"
    )


def _readiness_next_actions(
    checks: list[dict[str, object]],
    *,
    planned_command: str,
    config_path: Path,
    env_path: Path,
    channel_test_result: Path,
) -> list[dict[str, str]]:
    checks_by_id = {str(check.get("id")): check for check in checks}
    actions: list[dict[str, str]] = []
    action_ids: set[str] = set()

    def add(action_id: str, *, severity: str, command: str, reason: str) -> None:
        if action_id in action_ids:
            return
        action_ids.add(action_id)
        actions.append(
            {
                "id": action_id,
                "severity": severity,
                "command": command,
                "reason": reason,
            }
        )

    setup_command = (
        "airesearcher setup "
        f"--config {_command_path(config_path)} --env-path {_command_path(env_path)}"
    )
    channel_setup_command = setup_command + " --wechat --wechat-qr --run-wechat-qr-setup"
    channel_setup_with_test_command = (
        channel_setup_command
        + f" --run-channel-test --channel-test-output {_command_path(channel_test_result)}"
    )
    bind_wechat_target_command = (
        "airesearcher channels bind-target "
        f"--channel wechat --env-path {_command_path(env_path)}"
    )
    bind_feishu_target_command = (
        "airesearcher channels bind-target "
        f"--channel feishu --env-path {_command_path(env_path)}"
    )
    delivery_check = checks_by_id.get("channel_delivery_test")
    should_run_setup_channel_test = bool(
        delivery_check and delivery_check.get("status") == "fail"
    )
    channel_setup_repair_command = (
        channel_setup_with_test_command if should_run_setup_channel_test else channel_setup_command
    )

    for check_id in ("env_file", "llm_credentials", "config_file", "vault"):
        check = checks_by_id.get(check_id)
        if check and check.get("status") == "fail":
            add(
                "run_setup",
                severity="required",
                command=setup_command,
                reason="Create or repair first-deploy configuration before starting the loop.",
            )
            break

    operator_check = checks_by_id.get("operator_channels")
    if operator_check and operator_check.get("status") in {"warn", "fail"}:
        missing_wechat_target = _readiness_missing_wechat_qr_target(operator_check)
        missing_feishu_target = _readiness_missing_feishu_home_chat(operator_check)
        if missing_wechat_target:
            add(
                "bind_wechat_target",
                severity="required" if operator_check.get("status") == "fail" else "recommended",
                command=bind_wechat_target_command,
                reason="Bind the OpenClaw WeChat target discovered after QR pairing.",
            )
        if missing_feishu_target:
            add(
                "bind_feishu_target",
                severity="required" if operator_check.get("status") == "fail" else "recommended",
                command=bind_feishu_target_command,
                reason="Bind the Feishu/Lark home chat discovered after bot pairing.",
            )
        if not (missing_wechat_target or missing_feishu_target):
            add(
                "configure_operator_channel",
                severity="required" if operator_check.get("status") == "fail" else "recommended",
                command=channel_setup_repair_command,
                reason="Configure at least one WeChat or Feishu channel before push delivery.",
            )

    if delivery_check and delivery_check.get("status") in {"warn", "fail"}:
        ready_channels = _readiness_ready_channels(operator_check)
        if ready_channels:
            channel_flags = " ".join(f"--channel {channel}" for channel in ready_channels)
            add(
                "run_channel_self_test",
                severity="required" if delivery_check.get("status") == "fail" else "recommended",
                command=(
                    "airesearcher channels test "
                    f"{channel_flags} --output {_command_path(channel_test_result)} --require-sent"
                ),
                reason="Produce real sent-delivery evidence before treating push readiness as proven.",
            )
        else:
            missing_wechat_target = _readiness_missing_wechat_qr_target(operator_check)
            missing_feishu_target = _readiness_missing_feishu_home_chat(operator_check)
            if missing_wechat_target:
                add(
                    "bind_wechat_target",
                    severity="required",
                    command=bind_wechat_target_command,
                    reason="Bind the OpenClaw WeChat target before running the channel self-test.",
                )
            if missing_feishu_target:
                add(
                    "bind_feishu_target",
                    severity="required",
                    command=bind_feishu_target_command,
                    reason="Bind the Feishu/Lark home chat before running the channel self-test.",
                )
            if not (missing_wechat_target or missing_feishu_target):
                add(
                    "configure_operator_channel",
                    severity="required",
                    command=channel_setup_repair_command,
                    reason="Configure a delivery channel before running the channel self-test.",
                )
            if delivery_check.get("status") == "fail":
                post_bind_channels = []
                if missing_wechat_target:
                    post_bind_channels.append("wechat")
                if missing_feishu_target:
                    post_bind_channels.append("feishu")
                if not post_bind_channels:
                    post_bind_channels.append("wechat")
                channel_flags = " ".join(f"--channel {channel}" for channel in post_bind_channels)
                add(
                    "run_channel_self_test",
                    severity="required",
                    command=(
                        "airesearcher channels test "
                        f"{channel_flags} --output {_command_path(channel_test_result)} "
                        "--require-sent"
                    ),
                    reason=(
                        "After channel setup and target binding succeed, produce real sent-delivery "
                        "evidence before treating push readiness as proven."
                    ),
                )

    if not any(check.get("status") in {"fail", "warn"} for check in checks):
        add(
            "start_daily_loop",
            severity="next",
            command=planned_command,
            reason="All hard readiness checks passed; start the unattended daily loop when ready.",
        )
    return actions


def _readiness_ready_channels(check: Mapping[str, object] | None) -> list[str]:
    if not check:
        return []
    evidence = check.get("evidence")
    if not isinstance(evidence, Mapping):
        return []
    return _string_list(evidence.get("ready_channels"))


def _readiness_missing_wechat_qr_target(check: Mapping[str, object] | None) -> bool:
    if not check:
        return False
    evidence = check.get("evidence")
    if not isinstance(evidence, Mapping):
        return False
    return (
        str(evidence.get("wechat_mode") or "").casefold() == "qr"
        and str(evidence.get("wechat_qr_status") or "").casefold() == "completed"
        and evidence.get("wechat_openclaw_target_configured") is False
    )


def _readiness_missing_feishu_home_chat(check: Mapping[str, object] | None) -> bool:
    if not isinstance(check, Mapping):
        return False
    evidence = check.get("evidence")
    if not isinstance(evidence, Mapping):
        return False
    return (
        evidence.get("feishu_app_credentials_configured") is True
        and evidence.get("feishu_home_chat_configured") is False
        and evidence.get("feishu_webhook_configured") is False
    )


def _command_path(path: Path) -> str:
    return shlex.quote(path.as_posix())


def _env_or_os(env_values: Mapping[str, str], key: str) -> str:
    return (env_values.get(key) or os.getenv(key) or "").strip()


def _wechat_qr_setup_status(status_path: Path) -> str:
    payload = _read_json_mapping(status_path)
    return str(payload.get("status") or "").strip().casefold()


@app.command("similarity-check")
def similarity_check(
    candidate_file: Annotated[
        Path,
        typer.Option(
            "--candidate-file",
            "-f",
            help="JSON file containing a ResearchCandidate payload.",
        ),
    ],
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to read and update."),
    ] = Path("autoresearch-vault"),
    cache: Annotated[
        Path,
        typer.Option("--cache", help="Retrieval cache directory."),
    ] = Path(".cache/literature"),
    max_queries: Annotated[
        int,
        typer.Option("--max-queries", min=1, help="Maximum optimized queries to run."),
    ] = 6,
    max_results_per_source: Annotated[
        int,
        typer.Option("--max-results-per-source", min=1, help="Maximum papers per source/query."),
    ] = 10,
    cache_ttl_hours: Annotated[
        int,
        typer.Option("--cache-ttl-hours", min=1, help="Cache TTL for source responses."),
    ] = 24,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Optional project ID to link the report into project knowledge."),
    ] = None,
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Optional .env file for literature API keys."),
    ] = Path(".env"),
) -> None:
    """Run real online project-start similar-work checking for one candidate."""

    try:
        _load_optional_env(env_path)
        candidate = _load_candidate(candidate_file)
        report = run_project_similarity_check(
            candidate=candidate,
            vault_root=vault,
            cache_root=cache,
            config=SimilarityCheckConfig(
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
                cache_ttl_hours=cache_ttl_hours,
            ),
        )
        project_link = (
            link_similarity_report_to_project(
                report=report,
                vault_root=vault,
                project_id=project_id,
            )
            if project_id
            else None
        )
    except Exception as exc:
        typer.echo(f"[FAIL] similarity check failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _echo_fetches(report.fetches)
    if not report.findings:
        typer.echo("[FAIL] similarity check returned no source-backed findings", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"[OK] candidate: {candidate.id}")
    typer.echo(f"[OK] queries: {len(report.queries)}")
    typer.echo(f"[OK] findings: {len(report.findings)}")
    if report.summary_path is not None:
        typer.echo(f"[OK] summary: {report.summary_path}")
    if project_link is not None:
        typer.echo(f"[OK] project_link: {project_link}")


@app.command("research-plan")
def research_plan(
    candidate_file: Annotated[
        Path,
        typer.Option(
            "--candidate-file",
            "-f",
            help="JSON file containing a user-confirmed ResearchCandidate payload.",
        ),
    ],
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID used for vault and outputs paths."),
    ],
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root to write the Markdown plan."),
    ] = Path("autoresearch-vault"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Root directory for JSON, TeX, and PDF outputs."),
    ] = Path("outputs"),
    similarity_summary: Annotated[
        Path | None,
        typer.Option("--similarity-summary", help="Optional local similarity-check summary path."),
    ] = None,
    literature_summary: Annotated[
        Path | None,
        typer.Option("--literature-summary", help="Optional local literature-refresh summary path."),
    ] = None,
    inspiration_summary: Annotated[
        Path | None,
        typer.Option("--inspiration-summary", help="Optional local broad-inspiration summary path."),
    ] = None,
    compile_pdf: Annotated[
        bool,
        typer.Option("--compile-pdf/--no-compile-pdf", help="Compile the LaTeX plan into PDF."),
    ] = True,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="LaTeX compile timeout."),
    ] = 120,
) -> None:
    """Generate the post-direction research-plan gate and artifacts."""

    try:
        candidate = _load_candidate(candidate_file)
        artifact = generate_research_plan(
            candidate=candidate,
            project_id=project_id,
            vault_root=vault,
            output_dir=output_dir,
            compile_pdf=compile_pdf,
            similarity_summary=similarity_summary,
            literature_summary=literature_summary,
            inspiration_summary=inspiration_summary,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        typer.echo(f"[FAIL] research plan generation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[OK] research_plan: {artifact.audit.verdict.value}")
    typer.echo(f"[OK] score: {artifact.audit.score}")
    typer.echo(f"[OK] markdown: {artifact.markdown_path}")
    typer.echo(f"[OK] json: {artifact.json_path}")
    typer.echo(f"[OK] tex: {artifact.tex_path}")
    typer.echo(f"[OK] compile_status: {artifact.compile_status}")
    if artifact.pdf_path is not None:
        typer.echo(f"[OK] pdf: {artifact.pdf_path}")
    if artifact.page_count is not None:
        typer.echo(f"[OK] pages: {artifact.page_count}")
    for issue in artifact.audit.issues:
        typer.echo(f"[ISSUE] {issue}")
    for warning in artifact.audit.warnings:
        typer.echo(f"[WARN] {warning}")
    if not artifact.audit.passed:
        raise typer.Exit(code=1)
    if compile_pdf and artifact.compile_status != "compiled":
        if artifact.compile_reason:
            typer.echo(f"[FAIL] pdf: {artifact.compile_reason}", err=True)
        raise typer.Exit(code=1)


@app.command("research-plan-audit")
def research_plan_audit(
    plan_json: Annotated[
        Path,
        typer.Argument(help="research-plan.json or a raw ResearchPlan JSON file."),
    ],
) -> None:
    """Re-run the deterministic research-plan quality gate."""

    try:
        payload = json.loads(plan_json.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and isinstance(payload.get("plan"), dict):
            plan_payload = payload["plan"]
        else:
            plan_payload = payload
        plan = ResearchPlan.model_validate(plan_payload)
        markdown = _read_optional_artifact_text(payload, "markdown_path", base_dir=plan_json.parent)
        tex = _read_optional_artifact_text(payload, "tex_path", base_dir=plan_json.parent)
        audit = audit_research_plan(plan, rendered_markdown=markdown, rendered_tex=tex)
    except Exception as exc:
        typer.echo(f"[FAIL] research plan audit failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[OK] research_plan_audit: {audit.verdict.value}")
    typer.echo(f"[OK] score: {audit.score}")
    for issue in audit.issues:
        typer.echo(f"[ISSUE] {issue}")
    for warning in audit.warnings:
        typer.echo(f"[WARN] {warning}")
    if not audit.passed:
        raise typer.Exit(code=1)


@app.command("run-demo")
def run_demo(
    demo: str = typer.Option(
        "tabular_baseline",
        "--demo",
        "-d",
        help="Demo or public benchmark task to run.",
    ),
    output_dir: Path = typer.Option(
        Path("runs/demo"),
        "--output-dir",
        "-o",
        help="Directory where demo outputs should be persisted.",
    ),
    timeout_seconds: int = typer.Option(
        30,
        "--timeout-seconds",
        help="Local execution timeout for the generated demo runner.",
    ),
) -> None:
    """Run one local demo or public benchmark from code to evidence-backed report."""

    try:
        result = run_scientistbench_demo(
            demo,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except Exception as exc:
        typer.echo(f"[FAIL] demo run failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[OK] demo: {result.demo}")
    typer.echo(f"[OK] experiment_dir: {_relative_path_text(result.experiment_dir)}")
    typer.echo(f"[OK] run_id: {result.run_id}")
    typer.echo(f"[OK] validation: {_relative_path_text(result.validation_json_path)}")
    typer.echo(f"[OK] evidence_map: {_relative_path_text(result.evidence_map_path)}")
    typer.echo(f"[OK] report: {_relative_path_text(result.report_path)}")


@app.command("validate-package")
def validate_package(
    manifest: Path = typer.Option(
        Path("manifest.json"),
        "--manifest",
        "-m",
        help="Path to a reproducibility package manifest.json file.",
    ),
) -> None:
    """Validate a reproducibility package manifest and included artifacts."""

    report = validate_reproducibility_package(manifest)
    if report.status is ValidationStatus.PASSED:
        typer.echo(f"[OK] package validation passed: {report.checked_artifacts} artifacts")
        return

    typer.echo(f"[FAIL] package validation failed: {report.checked_artifacts} artifacts")
    for issue in report.issues:
        target = f" ({issue.package_path})" if issue.package_path else ""
        typer.echo(f"[{issue.severity.value.upper()}] {issue.check}{target}: {issue.message}")
    raise typer.Exit(code=1)


@app.command("llm-smoke")
def llm_smoke(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Configuration file written by deploy-setup."),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file containing the configured API key."),
    ] = Path(".env"),
    output: Annotated[
        Path,
        typer.Option("--output", help="JSON quality report output path under ignored run artifacts."),
    ] = Path("runs/llm-smoke/latest.json"),
    min_quality_score: Annotated[
        float,
        typer.Option("--min-quality-score", min=0.0, max=1.0, help="Fail below this score."),
    ] = 0.85,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            help="Optional output token limit. Omit by default for long-context models.",
        ),
    ] = None,
) -> None:
    """Call the configured live LLM API and run a structured output quality gate."""

    try:
        result = run_llm_smoke_test(
            config_path=config_path,
            env_path=env_path,
            max_tokens=_validate_optional_max_tokens(max_tokens, minimum=128),
        )
    except LLMClientError as exc:
        typer.echo(f"[FAIL] LLM smoke request failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"[OK] provider: {result.provider}")
    typer.echo(f"[OK] model: {result.model_name}")
    typer.echo(f"[OK] endpoint: {result.endpoint}")
    typer.echo(f"[OK] attempts: {result.attempts}")
    typer.echo(f"[OK] quality_score: {result.quality.score:.3f}")
    for check, passed in result.quality.checks.items():
        typer.echo(f"[CHECK] {check}: {'pass' if passed else 'fail'}")

    parsed = result.quality.parsed_output or {}
    summary = parsed.get("summary")
    evidence_policy = parsed.get("evidence_policy")
    if isinstance(summary, str):
        typer.echo(f"[SUMMARY] {summary}")
    if isinstance(evidence_policy, str):
        typer.echo(f"[EVIDENCE] {evidence_policy}")
    typer.echo(f"[OK] report written: {output}")
    if result.quality.score < min_quality_score:
        typer.echo("[FAIL] LLM output quality score below threshold", err=True)
        raise typer.Exit(1)


@app.command("llm-review")
def llm_review(
    subject: Annotated[
        Path,
        typer.Option("--subject", help="Local output file to review."),
    ],
    evidence: Annotated[
        list[Path],
        typer.Option(
            "--evidence",
            "-e",
            help="Local evidence file. Repeat this option for multiple files.",
        ),
    ],
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Configuration file written by deploy-setup."),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file containing the configured API key."),
    ] = Path(".env"),
    output: Annotated[
        Path,
        typer.Option("--output", help="JSON reviewer report output path under ignored run artifacts."),
    ] = Path("runs/llm-review/latest.json"),
    min_quality_score: Annotated[
        float,
        typer.Option("--min-quality-score", min=0.0, max=1.0, help="Fail below this score."),
    ] = 0.85,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            help="Optional output token limit. Omit by default for long-context models.",
        ),
    ] = None,
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root for optional project review memory."),
    ] = Path("autoresearch-vault"),
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Optional project ID that receives an Obsidian review note."),
    ] = None,
    source_task_id: Annotated[
        str | None,
        typer.Option("--source-task-id", help="Optional task ID to attach to the review note."),
    ] = None,
    write_issues: Annotated[
        bool,
        typer.Option(
            "--write-issues/--no-write-issues",
            help="Write actionable review findings into project issue notes.",
        ),
    ] = True,
) -> None:
    """Run an LLM-as-reviewer pass constrained to local evidence files."""

    try:
        result = run_llm_evidence_review(
            subject_path=subject,
            evidence_paths=list(evidence),
            config_path=config_path,
            env_path=env_path,
            max_tokens=_validate_optional_max_tokens(max_tokens, minimum=256),
        )
    except LLMClientError as exc:
        typer.echo(f"[FAIL] LLM review request failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"[OK] provider: {result.provider}")
    typer.echo(f"[OK] model: {result.model_name}")
    typer.echo(f"[OK] subject: {result.subject_path}")
    typer.echo(f"[OK] evidence_files: {len(result.evidence)}")
    typer.echo(f"[OK] attempts: {result.attempts}")
    typer.echo(f"[OK] review_quality_score: {result.quality.score:.3f}")
    for check, passed in result.quality.checks.items():
        typer.echo(f"[CHECK] {check}: {'pass' if passed else 'fail'}")

    parsed = result.quality.parsed_output or {}
    verdict = parsed.get("verdict")
    summary = parsed.get("summary")
    if isinstance(verdict, str):
        typer.echo(f"[VERDICT] {verdict}")
    if isinstance(summary, str):
        typer.echo(f"[SUMMARY] {summary}")
    typer.echo(f"[OK] review report written: {output}")
    if result.quality.score < min_quality_score:
        typer.echo("[FAIL] LLM review quality score below threshold", err=True)
        raise typer.Exit(1)
    if project_id:
        review_note = write_llm_review_note(
            result=result,
            vault_root=vault,
            project_id=project_id,
            source_task_id=source_task_id,
        )
        typer.echo(f"[OK] vault_review: {review_note}")
        if write_issues:
            issue_notes = write_llm_review_issue_notes(
                result=result,
                vault_root=vault,
                project_id=project_id,
                source_task_id=source_task_id,
                review_note_path=review_note,
            )
            typer.echo(f"[OK] vault_issues: {len(issue_notes)}")


@app.command("publication-audit")
def publication_audit(
    cycle_summary_path: Annotated[
        Path,
        typer.Argument(help="Path to a cycle-summary.json produced by autopilot or serve."),
    ],
    target: Annotated[
        str,
        typer.Option("--target", help="Publication quality target: ccf-b, q3-journal, or mvp-demo."),
    ] = "ccf-b",
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for publication-audit.json and .md."),
    ] = None,
    review_path: Annotated[
        Path | None,
        typer.Option(
            "--review-json",
            help="Optional standalone llm-review.json overriding cycle_summary.review.",
        ),
    ] = None,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Optional Obsidian vault root for audit review/issue notes."),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Project ID for optional Obsidian audit notes."),
    ] = None,
    fail_on_not_publishable: Annotated[
        bool,
        typer.Option(
            "--fail-on-not-publishable/--no-fail-on-not-publishable",
            help="Exit with code 1 when the audit is not publishable.",
        ),
    ] = True,
) -> None:
    """Audit whether a completed autonomous cycle is publication-ready."""

    report = audit_publication_quality(
        cycle_summary_path=cycle_summary_path,
        target=target,
        review_path=review_path,
        output_dir=output_dir,
        vault_root=vault,
        project_id=project_id,
    )
    typer.echo(f"[OK] publication_audit: {report.verdict.value}")
    typer.echo(f"[OK] publishable: {str(report.publishable).lower()}")
    typer.echo(f"[OK] score: {report.score:.3f}")
    typer.echo(f"[OK] report: {report.markdown_path}")
    typer.echo(f"[OK] json: {report.output_path}")
    if report.review_path:
        typer.echo(f"[OK] review: {report.review_path}")
    if report.vault_review_path:
        typer.echo(f"[OK] vault_review: {report.vault_review_path}")
    if report.vault_issue_path:
        typer.echo(f"[OK] vault_issue: {report.vault_issue_path}")
    if fail_on_not_publishable and not report.publishable:
        typer.echo("[FAIL] cycle is not publication-ready for the selected target", err=True)
        raise typer.Exit(1)


@app.command("paper-build")
def paper_build(
    report_path: Annotated[
        Path,
        typer.Argument(help="Evidence-bound Markdown report to convert into a LaTeX paper artifact."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for paper-build.json, .md, .tex, .log, and .pdf."),
    ] = Path("runs/paper-build/latest"),
    template_id: Annotated[
        str,
        typer.Option("--template-id", help="Registered LaTeX template id."),
    ] = "generic-article-one-column",
    title: Annotated[
        str | None,
        typer.Option("--title", help="Override the Markdown H1 title."),
    ] = None,
    authors: Annotated[
        list[str] | None,
        typer.Option("--author", help="Paper author. Repeat for multiple authors."),
    ] = None,
    compile_pdf: Annotated[
        bool,
        typer.Option("--compile-pdf/--no-compile-pdf", help="Compile the generated TeX into PDF."),
    ] = True,
    timeout_seconds: Annotated[
        int,
        typer.Option(
            "--timeout-seconds",
            min=1,
            help="Timeout for LaTeX dependency recovery and PDF compilation.",
        ),
    ] = 60,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Optional Obsidian vault root for paper-build summary."),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Project ID for optional Obsidian paper-build summary."),
    ] = None,
    fail_on_not_compiled: Annotated[
        bool,
        typer.Option(
            "--fail-on-not-compiled/--no-fail-on-not-compiled",
            help="Exit with code 1 unless the paper PDF compiled successfully.",
        ),
    ] = True,
) -> None:
    """Build a LaTeX/PDF paper artifact from an evidence-bound Markdown report."""

    artifact = build_latex_paper_from_markdown(
        markdown_path=report_path,
        output_dir=output_dir,
        template_id=template_id,
        title=title,
        authors=tuple(authors or ("AI-Researcher",)),
        compile_pdf=compile_pdf,
        vault_root=vault,
        project_id=project_id,
        timeout_seconds=timeout_seconds,
    )
    typer.echo(f"[OK] paper_build: {artifact.status.value}")
    typer.echo(f"[OK] template: {artifact.template.id}")
    typer.echo(f"[OK] tex: {artifact.tex_path}")
    typer.echo(f"[OK] pdf: {artifact.pdf_path or 'none'}")
    typer.echo(f"[OK] report: {artifact.markdown_path}")
    typer.echo(f"[OK] json: {artifact.json_path}")
    dependency = getattr(artifact, "dependency_resolution", None)
    if dependency is not None:
        dependency_status = getattr(dependency.status, "value", str(dependency.status))
        typer.echo(
            "[OK] latex_dependency: "
            f"status={dependency_status}, "
            f"class={dependency.class_file or 'none'}, "
            f"artifact={dependency.artifact_path or 'none'}"
        )
        typer.echo(f"[OK] latex_dependency_message: {dependency.message}")
    quality = getattr(artifact, "quality", None)
    if quality is not None:
        typer.echo(
            "[OK] paper_quality: "
            f"passed={str(quality.passed).lower()}, "
            f"pages={quality.page_count or 'unknown'}/{quality.min_pages}, "
            f"words={quality.word_count}/{quality.min_word_count}, "
            f"overfull_hbox={quality.overfull_hbox_count}/{quality.max_overfull_hbox_count}"
        )
        if not quality.passed:
            typer.echo("[FAIL] paper_quality: " + ", ".join(quality.failures), err=True)
    if artifact.vault_markdown_path:
        typer.echo(f"[OK] vault_paper: {artifact.vault_markdown_path}")
    if artifact.missing_sections:
        typer.echo("[FAIL] missing_sections: " + ", ".join(artifact.missing_sections), err=True)
    if fail_on_not_compiled and artifact.status is not LatexPaperBuildStatus.COMPILED:
        typer.echo("[FAIL] paper PDF did not compile", err=True)
        raise typer.Exit(1)


@app.command("evidence-gate")
def evidence_gate(
    cycle_summary_path: Annotated[
        Path,
        typer.Argument(help="Path to a cycle-summary.json produced by autopilot or serve."),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for evidence-gate.json and .md."),
    ] = None,
    review_path: Annotated[
        Path | None,
        typer.Option(
            "--review-json",
            help="Optional llm-review.json path overriding cycle_summary.review.",
        ),
    ] = None,
    publication_audit_path: Annotated[
        Path | None,
        typer.Option(
            "--publication-audit",
            help="publication-audit.json path. Defaults to cycle_summary.publication_audit.output_path.",
        ),
    ] = None,
    paper_build_path: Annotated[
        Path | None,
        typer.Option(
            "--paper-build-json",
            help="paper-build.json path for the compiled LaTeX/PDF artifact gate.",
        ),
    ] = None,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Optional Obsidian vault root for gate review/issue notes."),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Project ID for optional Obsidian gate notes."),
    ] = None,
    require_review_pass: Annotated[
        bool,
        typer.Option(
            "--require-review-pass/--no-require-review-pass",
            help="Require the evidence-constrained review status and verdict to pass.",
        ),
    ] = True,
    require_publication_pass: Annotated[
        bool,
        typer.Option(
            "--require-publication-pass/--no-require-publication-pass",
            help="Require publication-audit publishable=true and verdict=pass.",
        ),
    ] = True,
    require_paper_build: Annotated[
        bool,
        typer.Option(
            "--require-paper-build/--no-require-paper-build",
            help="Require a compiled paper-build PDF artifact.",
        ),
    ] = True,
    fail_on_blocked: Annotated[
        bool,
        typer.Option(
            "--fail-on-blocked/--no-fail-on-blocked",
            help="Exit with code 1 when the physical evidence gate blocks release.",
        ),
    ] = True,
) -> None:
    """Run the physical release gate over a completed research cycle."""

    report = run_evidence_gate(
        cycle_summary_path=cycle_summary_path,
        output_dir=output_dir,
        review_path=review_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
        vault_root=vault,
        project_id=project_id,
        require_review_pass=require_review_pass,
        require_publication_pass=require_publication_pass,
        require_paper_build=require_paper_build,
    )
    typer.echo(f"[OK] evidence_gate: {report.verdict.value}")
    typer.echo(f"[OK] release_allowed: {str(report.release_allowed).lower()}")
    typer.echo(f"[OK] failed_checks: {report.failed_check_count}")
    typer.echo(f"[OK] report: {report.markdown_path}")
    typer.echo(f"[OK] json: {report.output_path}")
    if report.vault_review_path:
        typer.echo(f"[OK] vault_review: {report.vault_review_path}")
    if report.vault_issue_path:
        typer.echo(f"[OK] vault_issue: {report.vault_issue_path}")
    if fail_on_blocked and report.verdict is EvidenceGateVerdict.BLOCKED:
        typer.echo("[FAIL] physical evidence gate blocked release", err=True)
        raise typer.Exit(1)


@app.command("publication-stability")
def publication_stability(
    cycle_summary_paths: Annotated[
        list[Path],
        typer.Argument(help="One or more completed cycle-summary.json paths to evaluate."),
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Stability target: ccf-b-matrix or mvp-matrix.",
        ),
    ] = "ccf-b-matrix",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for publication-stability.json and .md."),
    ] = Path("runs/publication-stability/latest"),
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Optional Obsidian vault root for stability review/issue notes."),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Project ID for optional Obsidian stability notes."),
    ] = None,
    fail_on_unstable: Annotated[
        bool,
        typer.Option(
            "--fail-on-unstable/--no-fail-on-unstable",
            help="Exit with code 1 when the matrix does not support stable output claims.",
        ),
    ] = True,
) -> None:
    """Gate stable CCF-B/Q3 output claims across multiple completed cycles."""

    report = audit_publication_stability(
        cycle_summary_paths=tuple(cycle_summary_paths),
        target=target,
        output_dir=output_dir,
        vault_root=vault,
        project_id=project_id,
    )
    typer.echo(f"[OK] publication_stability: {report.verdict.value}")
    typer.echo(f"[OK] stable: {str(report.stable).lower()}")
    typer.echo(f"[OK] score: {report.score:.3f}")
    typer.echo(f"[OK] cycles: {len(report.cycles)}")
    typer.echo(f"[OK] report: {report.markdown_path}")
    typer.echo(f"[OK] json: {report.output_path}")
    if report.vault_review_path:
        typer.echo(f"[OK] vault_review: {report.vault_review_path}")
    if report.vault_issue_path:
        typer.echo(f"[OK] vault_issue: {report.vault_issue_path}")
    if fail_on_unstable and not report.stable:
        typer.echo("[FAIL] publication stability matrix blocked stable output claims", err=True)
        raise typer.Exit(1)


@app.command("autopilot")
def autopilot(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Configuration file written by deploy-setup."),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file with provider credentials."),
    ] = Path(".env"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root for loop memory."),
    ] = Path("autoresearch-vault"),
    cache: Annotated[
        Path,
        typer.Option("--cache", help="Literature retrieval cache root."),
    ] = Path(".cache/literature"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Autopilot run output directory."),
    ] = Path("runs/autopilot"),
    deliverables_dir: Annotated[
        Path,
        typer.Option("--deliverables-dir", help="Root directory for published PDF and manifest outputs."),
    ] = Path("outputs"),
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    heartbeat_state: Annotated[
        Path | None,
        typer.Option("--heartbeat-state", help="Local runtime heartbeat JSON state file."),
    ] = None,
    sessions_state: Annotated[
        Path | None,
        typer.Option("--sessions-state", help="Local agent session coordination JSON file."),
    ] = None,
    claim_session: Annotated[
        bool,
        typer.Option(
            "--claim-session/--no-claim-session",
            help="Automatically claim runtime write paths before starting the loop.",
        ),
    ] = True,
    agent_name: Annotated[
        str,
        typer.Option("--agent-name", help="Agent identity recorded in the runtime session claim."),
    ] = "AI-Researcher Runtime",
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for Obsidian review and issue notes."),
    ] = "autopilot-demo",
    demo: Annotated[
        str,
        typer.Option("--demo", help="Demo or public benchmark to execute in each cycle."),
    ] = DEFAULT_RESEARCH_DEMO,
    max_queries: Annotated[
        int,
        typer.Option(
            "--max-queries",
            min=1,
            help="Maximum generated literature/similarity queries; lower only for smoke runs.",
        ),
    ] = PUBLICATION_SEARCH_QUERIES,
    max_results_per_source: Annotated[
        int,
        typer.Option(
            "--max-results-per-source",
            min=1,
            help="Maximum papers per source/query; lower only for smoke runs.",
        ),
    ] = PUBLICATION_RESULTS_PER_SOURCE,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Experiment execution timeout."),
    ] = 30,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            help="Optional LLM reviewer output token limit. Omit by default for long-context models.",
        ),
    ] = None,
    min_quality_score: Annotated[
        float,
        typer.Option("--min-quality-score", min=0.0, max=1.0, help="Minimum LLM review score."),
    ] = 0.85,
    review: Annotated[
        bool,
        typer.Option("--review/--no-review", help="Run the live LLM evidence reviewer."),
    ] = True,
    paper_template_id: Annotated[
        str,
        typer.Option(
            "--paper-template-id",
            help="Registered LaTeX template ID for the autonomous paper build.",
        ),
    ] = "generic-article-one-column",
    agent_profile: Annotated[
        list[Path] | None,
        typer.Option(
            "--agent-profile",
            help="Agent profile JSON to load into this cycle. Repeat for multiple agents.",
        ),
    ] = None,
    push_inspiration: Annotated[
        bool,
        typer.Option(
            "--push-inspiration/--no-push-inspiration",
            help="Push the broad-inspiration digest to configured operator channels.",
        ),
    ] = False,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Keep running cycles after the first one."),
    ] = False,
    cycles: Annotated[
        int,
        typer.Option("--cycles", min=0, help="Cycle count; use 0 with --watch to run forever."),
    ] = 1,
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=1, help="Delay between watch cycles."),
    ] = 86400,
) -> None:
    """Run the trusted research loop from one operator command."""

    _load_optional_env(env_path)
    _echo_loop_plan(
        command_name="autopilot",
        watch=watch,
        cycles=cycles,
        interval_seconds=interval_seconds,
        push_inspiration=push_inspiration,
    )
    completed = 0
    resolved_sessions_state = _resolve_runtime_sessions_state(sessions_state, state)
    resolved_heartbeat_state = _resolve_runtime_heartbeat_state(heartbeat_state, state)
    session = _claim_runtime_session(
        enabled=claim_session,
        sessions_state=resolved_sessions_state,
        agent_name=agent_name,
        task_id=f"autopilot:{project_id}",
        claimed_paths=_runtime_claimed_paths(
            vault=vault,
            cache=cache,
            output_dir=output_dir,
            deliverables_dir=deliverables_dir,
            state=state,
            extra_paths=(resolved_heartbeat_state,),
        ),
    )
    try:
        while True:
            completed += 1
            try:
                summary = _run_autopilot_cycle(
                    config_path=config_path,
                    env_path=env_path,
                    vault=vault,
                    cache=cache,
                    output_dir=output_dir,
                    deliverables_dir=deliverables_dir,
                    state=state,
                    heartbeat_state=resolved_heartbeat_state,
                    project_id=project_id,
                    demo=demo,
                    max_queries=max_queries,
                    max_results_per_source=max_results_per_source,
                    timeout_seconds=timeout_seconds,
                    max_tokens=_validate_optional_max_tokens(max_tokens, minimum=256),
                    min_quality_score=min_quality_score,
                    review=review,
                    paper_template_id=paper_template_id,
                    agent_profile_paths=tuple(agent_profile or ()),
                    push_inspiration=push_inspiration,
                )
            except RuntimeError as exc:
                typer.echo(f"[FAIL] autopilot_cycle: {exc}", err=True)
                raise typer.Exit(1) from exc
            typer.echo(f"[OK] autopilot_cycle: {summary['cycle_id']}")
            typer.echo(f"[OK] summary: {summary['summary_path']}")
            if "source_preflight" in summary:
                preflight = summary["source_preflight"]
                prefix = "[BLOCKED]" if preflight["verdict"] == "blocked" else "[OK]"
                typer.echo(f"{prefix} source_preflight: {preflight['verdict']}")
            _echo_agent_profiles_status(summary)
            _echo_research_plan_status(summary)
            _echo_loop_campaign_status(summary)
            _echo_runtime_heartbeat_status(summary)
            review_prefix, review_status = _review_status_display(summary.get("review"))
            typer.echo(f"{review_prefix} review_status: {review_status}")
            if "publication_audit" in summary:
                typer.echo(
                    "[OK] publication_audit: "
                    f"{summary['publication_audit']['verdict']}"
                )
            if "evidence_gate" in summary:
                typer.echo(f"[OK] evidence_gate: {summary['evidence_gate']['verdict']}")
            typer.echo(f"[OK] followup_tasks: {summary['followups']['task_count']}")
            if "deliverables" in summary:
                deliverables = summary["deliverables"]
                typer.echo(f"[OK] deliverables: {deliverables.get('manifest_path')}")
                if deliverables.get("pdf_path"):
                    typer.echo(f"[OK] pdf_output: {deliverables.get('pdf_path')}")
            _echo_inspiration_pushes(summary)
            if not watch:
                break
            if cycles > 0 and completed >= cycles:
                break
            time.sleep(interval_seconds)
    finally:
        _release_runtime_session(resolved_sessions_state, session)


@app.command("serve")
def serve(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Configuration file written by deploy-setup."),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env-path", help="Local .env file with provider credentials."),
    ] = Path(".env"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root for loop memory."),
    ] = Path("autoresearch-vault"),
    cache: Annotated[
        Path,
        typer.Option("--cache", help="Literature retrieval cache root."),
    ] = Path(".cache/literature"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Runtime autopilot output directory."),
    ] = Path("runs/autopilot"),
    deliverables_dir: Annotated[
        Path,
        typer.Option("--deliverables-dir", help="Root directory for published PDF and manifest outputs."),
    ] = Path("outputs"),
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    heartbeat_state: Annotated[
        Path | None,
        typer.Option("--heartbeat-state", help="Local runtime heartbeat JSON state file."),
    ] = None,
    approvals_state: Annotated[
        Path,
        typer.Option("--approvals-state", help="Local runtime approval queue JSON file."),
    ] = DEFAULT_RUNTIME_APPROVALS_PATH,
    sessions_state: Annotated[
        Path | None,
        typer.Option("--sessions-state", help="Local agent session coordination JSON file."),
    ] = None,
    claim_session: Annotated[
        bool,
        typer.Option(
            "--claim-session/--no-claim-session",
            help="Automatically claim runtime write paths before starting the service.",
        ),
    ] = True,
    agent_name: Annotated[
        str,
        typer.Option("--agent-name", help="Agent identity recorded in the runtime session claim."),
    ] = "AI-Researcher Runtime",
    permission_mode: Annotated[
        RuntimePermissionMode,
        typer.Option("--permission-mode", help="Runtime permission mode."),
    ] = RuntimePermissionMode.APPROVE_DANGEROUS,
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for Obsidian review and issue notes."),
    ] = "autopilot-demo",
    demo: Annotated[
        str,
        typer.Option("--demo", help="Demo or public benchmark to execute in each cycle."),
    ] = DEFAULT_RESEARCH_DEMO,
    max_queries: Annotated[
        int,
        typer.Option(
            "--max-queries",
            min=1,
            help="Maximum generated literature/similarity queries; lower only for smoke runs.",
        ),
    ] = PUBLICATION_SEARCH_QUERIES,
    max_results_per_source: Annotated[
        int,
        typer.Option(
            "--max-results-per-source",
            min=1,
            help="Maximum papers per source/query; lower only for smoke runs.",
        ),
    ] = PUBLICATION_RESULTS_PER_SOURCE,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Experiment execution timeout."),
    ] = 30,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            help="Optional LLM reviewer output token limit. Omit by default for long-context models.",
        ),
    ] = None,
    min_quality_score: Annotated[
        float,
        typer.Option("--min-quality-score", min=0.0, max=1.0, help="Minimum LLM review score."),
    ] = 0.85,
    review: Annotated[
        bool,
        typer.Option("--review/--no-review", help="Run the live LLM evidence reviewer."),
    ] = True,
    paper_template_id: Annotated[
        str,
        typer.Option(
            "--paper-template-id",
            help="Registered LaTeX template ID for the autonomous paper build.",
        ),
    ] = "generic-article-one-column",
    agent_profile: Annotated[
        list[Path] | None,
        typer.Option(
            "--agent-profile",
            help="Agent profile JSON to load into this runtime. Repeat for multiple agents.",
        ),
    ] = None,
    push_inspiration: Annotated[
        bool,
        typer.Option(
            "--push-inspiration/--no-push-inspiration",
            help="Push the broad-inspiration digest to configured operator channels.",
        ),
    ] = False,
    watch: Annotated[
        bool,
        typer.Option("--watch/--once", help="Keep the runtime alive after one cycle."),
    ] = True,
    cycles: Annotated[
        int,
        typer.Option("--cycles", min=0, help="Approved cycle count; use 0 with --watch forever."),
    ] = 0,
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=1, help="Delay between runtime checks or cycles."),
    ] = 86400,
    approval_poll_seconds: Annotated[
        int,
        typer.Option(
            "--approval-poll-seconds",
            min=1,
            help="Delay between approval queue checks while waiting for /approve.",
        ),
    ] = 30,
) -> None:
    """Run AI-Researcher as an always-on local/server operator service."""

    _load_optional_env(env_path)
    completed = 0
    command_text = _serve_command_text(
        project_id=project_id,
        demo=demo,
        permission_mode=permission_mode,
        review=review,
        paper_template_id=paper_template_id,
        push_inspiration=push_inspiration,
    )
    typer.echo(f"[OK] runtime_mode: {permission_mode.value}")
    _echo_loop_plan(
        command_name="serve",
        watch=watch,
        cycles=cycles,
        interval_seconds=interval_seconds,
        push_inspiration=push_inspiration,
        approval_poll_seconds=approval_poll_seconds,
    )
    resolved_sessions_state = _resolve_runtime_sessions_state(
        sessions_state,
        state,
        approvals_state,
    )
    resolved_heartbeat_state = _resolve_runtime_heartbeat_state(
        heartbeat_state,
        state,
        approvals_state,
    )
    session = _claim_runtime_session(
        enabled=claim_session,
        sessions_state=resolved_sessions_state,
        agent_name=agent_name,
        task_id=f"serve:{project_id}",
        claimed_paths=_runtime_claimed_paths(
            vault=vault,
            cache=cache,
            output_dir=output_dir,
            deliverables_dir=deliverables_dir,
            state=state,
            extra_paths=(approvals_state, resolved_heartbeat_state),
        ),
    )
    try:
        while True:
            action_id = _serve_cycle_action_id(
                project_id=project_id,
                demo=demo,
                cycle_number=completed + 1,
            )
            decision = ensure_runtime_approval(
                state_path=approvals_state,
                mode=permission_mode,
                action_id=action_id,
                command=command_text,
                risk=RuntimeActionRisk.DANGEROUS,
                reason=(
                    "Runs online literature discovery, source-backed similarity checks, "
                    "local experiment execution, optional live LLM review, and vault/state writes."
                ),
            )
            if not decision.allowed:
                request = decision.request
                request_id = request.request_id if request is not None else "unknown"
                _echo_runtime_approval_waiting(
                    request_id=request_id,
                    state=approvals_state,
                    watch=watch,
                    interval_seconds=approval_poll_seconds,
                    action_id=request.action_id if request is not None else action_id,
                )
                if not watch:
                    raise typer.Exit(code=2)
                time.sleep(approval_poll_seconds)
                continue

            completed += 1
            runtime_network_metadata = _serve_network_approval_metadata(decision)
            try:
                summary = _run_autopilot_cycle(
                    config_path=config_path,
                    env_path=env_path,
                    vault=vault,
                    cache=cache,
                    output_dir=output_dir,
                    deliverables_dir=deliverables_dir,
                    state=state,
                    heartbeat_state=resolved_heartbeat_state,
                    project_id=project_id,
                    demo=demo,
                    max_queries=max_queries,
                    max_results_per_source=max_results_per_source,
                    timeout_seconds=timeout_seconds,
                    max_tokens=_validate_optional_max_tokens(max_tokens, minimum=256),
                    min_quality_score=min_quality_score,
                    review=review,
                    paper_template_id=paper_template_id,
                    agent_profile_paths=tuple(agent_profile or ()),
                    push_inspiration=push_inspiration,
                    runtime_network_metadata=runtime_network_metadata,
                )
            except RuntimeError as exc:
                typer.echo(f"[FAIL] serve_cycle: {exc}", err=True)
                raise typer.Exit(1) from exc
            typer.echo(f"[OK] serve_cycle: {summary['cycle_id']}")
            typer.echo(f"[OK] summary: {summary['summary_path']}")
            if "source_preflight" in summary:
                preflight = summary["source_preflight"]
                prefix = "[BLOCKED]" if preflight["verdict"] == "blocked" else "[OK]"
                typer.echo(f"{prefix} source_preflight: {preflight['verdict']}")
            _echo_agent_profiles_status(summary)
            _echo_research_plan_status(summary)
            _echo_loop_campaign_status(summary)
            _echo_runtime_heartbeat_status(summary)
            review_prefix, review_status = _review_status_display(summary.get("review"))
            typer.echo(f"{review_prefix} review_status: {review_status}")
            if "publication_audit" in summary:
                typer.echo(
                    "[OK] publication_audit: "
                    f"{summary['publication_audit']['verdict']}"
                )
            if "evidence_gate" in summary:
                typer.echo(f"[OK] evidence_gate: {summary['evidence_gate']['verdict']}")
            typer.echo(f"[OK] followup_tasks: {summary['followups']['task_count']}")
            if "deliverables" in summary:
                deliverables = summary["deliverables"]
                typer.echo(f"[OK] deliverables: {deliverables.get('manifest_path')}")
                if deliverables.get("pdf_path"):
                    typer.echo(f"[OK] pdf_output: {deliverables.get('pdf_path')}")
            _echo_inspiration_pushes(summary)
            if not watch:
                break
            if cycles > 0 and completed >= cycles:
                break
            time.sleep(interval_seconds)
    finally:
        _release_runtime_session(resolved_sessions_state, session)


@app.command("issue-followups")
def issue_followups(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root containing project issue notes."),
    ] = Path("autoresearch-vault"),
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID under the vault `projects/` directory."),
    ] = "current-project",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON file for the generated follow-up task list."),
    ] = None,
    state: Annotated[
        Path | None,
        typer.Option("--state", help="Optional scheduler state JSON file to merge generated tasks into."),
    ] = None,
) -> None:
    """List scheduler follow-up tasks derived from open project issue notes."""

    tasks = queued_issue_followups_from_vault(
        vault_root=vault,
        project_id=project_id,
        queued_at=datetime.now(timezone.utc),
    )
    records: list[dict[str, object]] = [
        {
            "task_id": task.task_id,
            "name": task.name,
            "queued_at": task.next_run_at.isoformat(),
            "status": "open",
            "metadata": task.action(),
        }
        for task in tasks
    ]
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"tasks": records}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        typer.echo(f"[OK] output: {output}")

    if state is not None:
        _merge_scheduler_state(state, records)
        typer.echo(f"[OK] state: {state}")

    typer.echo(f"[OK] issue_followups: {len(records)}")
    for record in records:
        metadata = record["metadata"]
        issue_path = metadata.get("issue_path") if isinstance(metadata, dict) else "unknown"
        typer.echo(f"[TASK] task_id={record['task_id']} issue_path={issue_path}")


@scheduler_state_app.command("list")
def list_scheduler_state(
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file to inspect."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    include_completed: Annotated[
        bool,
        typer.Option("--include-completed", help="Include tasks already marked completed."),
    ] = False,
) -> None:
    """List persisted local scheduler state records."""

    tasks = _read_scheduler_state_tasks(state)
    visible_tasks = [
        task
        for task in tasks
        if include_completed or str(task.get("status", "open")) != "completed"
    ]
    typer.echo(f"[OK] scheduler_state_tasks: {len(visible_tasks)}")
    for task in visible_tasks:
        metadata = task.get("metadata")
        issue_path = metadata.get("issue_path") if isinstance(metadata, dict) else "unknown"
        typer.echo(
            f"[TASK] status={task.get('status', 'open')} "
            f"task_id={task.get('task_id')} issue_path={issue_path}"
        )


@scheduler_state_app.command("complete")
def complete_scheduler_state_task(
    task_id: Annotated[str, typer.Argument(help="Task ID to mark completed.")],
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file to update."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
) -> None:
    """Mark one persisted scheduler task completed."""

    if not _set_scheduler_state_task_status(state, task_id, status="completed"):
        typer.echo(f"[FAIL] task not found: {task_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"[OK] completed: {task_id}")


@scheduler_state_app.command("remove")
def remove_scheduler_state_task(
    task_id: Annotated[str, typer.Argument(help="Task ID to remove.")],
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file to update."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
) -> None:
    """Remove one persisted scheduler task."""

    if not _remove_scheduler_state_task(state, task_id):
        typer.echo(f"[FAIL] task not found: {task_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"[OK] removed: {task_id}")


@runtime_app.command("list")
def list_runtime_approvals(
    state: Annotated[
        Path,
        typer.Option("--state", help="Local runtime approval queue JSON file to inspect."),
    ] = DEFAULT_RUNTIME_APPROVALS_PATH,
    include_completed: Annotated[
        bool,
        typer.Option("--include-completed", help="Include approved or rejected requests."),
    ] = False,
) -> None:
    """List pending runtime approval requests."""

    requests = list_runtime_approval_requests(state, include_completed=include_completed)
    typer.echo(f"[OK] runtime_approval_requests: {len(requests)}")
    for request in requests:
        typer.echo(
            f"[REQUEST] status={request.status.value} request_id={request.request_id} "
            f"risk={request.risk.value} action_id={request.action_id}"
        )


@runtime_app.command("approve")
def approve_runtime(
    request_id: Annotated[
        str,
        typer.Argument(help="Runtime approval request ID, or `latest` for newest pending."),
    ] = "latest",
    state: Annotated[
        Path,
        typer.Option("--state", help="Local runtime approval queue JSON file to update."),
    ] = DEFAULT_RUNTIME_APPROVALS_PATH,
    approved_by: Annotated[
        str,
        typer.Option("--approved-by", help="Operator identity recorded on the approval."),
    ] = "operator",
) -> None:
    """Approve a pending dangerous runtime action."""

    try:
        request = approve_runtime_request(
            state,
            request_id,
            approved_by=approved_by,
        )
    except RuntimeApprovalError as exc:
        typer.echo(f"[FAIL] runtime approval failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"[OK] approved: {request.request_id}")
    typer.echo(f"[OK] action_id: {request.action_id}")


@runtime_heartbeat_app.command("write")
def write_runtime_heartbeat_command(
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Loop run or cycle ID emitting this heartbeat."),
    ],
    stage: Annotated[
        str,
        typer.Option("--stage", help="Research-loop stage emitting this heartbeat."),
    ],
    progress: Annotated[
        str,
        typer.Option("--progress", help="Compact progress signature for stall detection."),
    ],
    message: Annotated[
        str | None,
        typer.Option("--message", help="Optional operator-readable progress note."),
    ] = None,
    artifact_ref: Annotated[
        list[str] | None,
        typer.Option("--artifact-ref", help="Evidence artifact path or URI. Repeat as needed."),
    ] = None,
    state: Annotated[
        Path,
        typer.Option("--state", help="Local runtime heartbeat JSON state file."),
    ] = DEFAULT_RUNTIME_HEARTBEATS_PATH,
) -> None:
    """Append one long-running loop heartbeat event."""

    try:
        event = write_runtime_heartbeat(
            state_path=state,
            run_id=run_id,
            stage=stage,
            progress=progress,
            message=message,
            artifact_refs=artifact_ref or (),
        )
    except ValueError as exc:
        typer.echo(f"[FAIL] runtime heartbeat failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"[OK] heartbeat: {event.run_id}/{event.stage}")
    typer.echo(f"[OK] progress_sha256: {event.progress_sha256}")
    typer.echo(f"[OK] state: {state}")


@runtime_heartbeat_app.command("check")
def check_runtime_heartbeats(
    state: Annotated[
        Path,
        typer.Option("--state", help="Local runtime heartbeat JSON state file to inspect."),
    ] = DEFAULT_RUNTIME_HEARTBEATS_PATH,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Optional run or cycle ID to check in isolation."),
    ] = None,
    stale_after_seconds: Annotated[
        int,
        typer.Option(
            "--stale-after-seconds",
            help="Seconds after which a stage heartbeat is stale.",
        ),
    ] = DEFAULT_HEARTBEAT_STALE_AFTER_SECONDS,
    stall_repetition_threshold: Annotated[
        int,
        typer.Option(
            "--stall-repetition-threshold",
            help="Repeated identical progress signatures before a stage is stalled.",
        ),
    ] = DEFAULT_HEARTBEAT_STALL_REPETITIONS,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON watchdog report path."),
    ] = None,
) -> None:
    """Check runtime heartbeats for stale or repeated progress."""

    report = evaluate_runtime_heartbeats(
        state_path=state,
        run_id=run_id,
        stale_after_seconds=stale_after_seconds,
        stall_repetition_threshold=stall_repetition_threshold,
    )
    if output is not None:
        write_runtime_heartbeat_report(report, output)
    status = "passed" if report.passed else "failed"
    typer.echo(f"[OK] heartbeat_watchdog: {status}")
    typer.echo(
        f"[OK] stages: {report.stage_count}; stale={report.stale_count}; "
        f"stalled={report.stalled_count}; events={report.event_count}"
    )
    for stage_report in report.stages:
        typer.echo(
            f"[HEARTBEAT] {stage_report.run_id}/{stage_report.stage}: "
            f"{stage_report.status.value}; action={stage_report.action.value}; "
            f"repeated={stage_report.repeated_progress_count}; "
            f"age_seconds={stage_report.age_seconds:.0f}"
        )
    if output is not None:
        typer.echo(f"[OK] report: {output}")
    if not report.passed:
        raise typer.Exit(code=1)


@sessions_app.command("claim")
def claim_session(
    task_id: Annotated[
        str,
        typer.Option("--task-id", help="Task or subtask ID this agent is starting."),
    ],
    path: Annotated[
        list[str] | None,
        typer.Option("--path", help="File or directory path to claim. Repeat as needed."),
    ] = None,
    state: Annotated[
        Path,
        typer.Option("--state", help="Local agent session coordination JSON file."),
    ] = DEFAULT_AGENT_SESSIONS_PATH,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Optional stable session ID to update or reuse."),
    ] = None,
    agent_name: Annotated[
        str,
        typer.Option("--agent-name", help="Agent identity recorded in the session claim."),
    ] = "Codex",
    fail_on_conflict: Annotated[
        bool,
        typer.Option(
            "--fail-on-conflict/--no-fail-on-conflict",
            help="Exit with code 1 when another active session overlaps the claimed paths.",
        ),
    ] = True,
    lock_timeout_seconds: Annotated[
        float,
        typer.Option(
            "--lock-timeout-seconds",
            min=0.0,
            help="Seconds to wait for the local session state lock.",
        ),
    ] = 10.0,
) -> None:
    """Claim file paths for a concurrent agent session."""

    try:
        result = claim_agent_session(
            state_path=state,
            session_id=session_id,
            agent_name=agent_name,
            task_id=task_id,
            claimed_paths=tuple(path or ()),
            lock_timeout_seconds=lock_timeout_seconds,
        )
    except AgentSessionError as exc:
        typer.echo(f"[FAIL] session claim failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    status = "allowed" if result.allowed else "blocked"
    typer.echo(f"[OK] session_claim: {status}")
    if result.session is not None:
        typer.echo(f"[OK] session_id: {result.session.session_id}")
        typer.echo(f"[OK] claimed_paths: {', '.join(result.session.claimed_paths)}")
    typer.echo(f"[OK] conflicts: {len(result.conflicts)}")
    for conflict in result.conflicts:
        typer.echo(
            f"[CONFLICT] session_id={conflict.session_id} task_id={conflict.task_id} "
            f"agent={conflict.agent_name} claimed={conflict.claimed_path} "
            f"existing={conflict.conflicting_path}"
        )
    if fail_on_conflict and not result.allowed:
        typer.echo("[FAIL] session claim overlaps an active agent session", err=True)
        raise typer.Exit(code=1)


@sessions_app.command("list")
def list_sessions(
    state: Annotated[
        Path,
        typer.Option("--state", help="Local agent session coordination JSON file."),
    ] = DEFAULT_AGENT_SESSIONS_PATH,
    include_released: Annotated[
        bool,
        typer.Option("--include-released", help="Include released sessions."),
    ] = False,
) -> None:
    """List active agent sessions."""

    sessions = list_agent_sessions(state, include_released=include_released)
    typer.echo(f"[OK] agent_sessions: {len(sessions)}")
    for session in sessions:
        typer.echo(
            f"[SESSION] status={session.status.value} session_id={session.session_id} "
            f"agent={session.agent_name} task_id={session.task_id} "
            f"paths={','.join(session.claimed_paths)}"
        )


@sessions_app.command("release")
def release_session(
    session_id: Annotated[
        str,
        typer.Argument(help="Agent session ID to release."),
    ],
    state: Annotated[
        Path,
        typer.Option("--state", help="Local agent session coordination JSON file."),
    ] = DEFAULT_AGENT_SESSIONS_PATH,
    lock_timeout_seconds: Annotated[
        float,
        typer.Option(
            "--lock-timeout-seconds",
            min=0.0,
            help="Seconds to wait for the local session state lock.",
        ),
    ] = 10.0,
) -> None:
    """Release a session claim so other agents may edit its paths."""

    try:
        session = release_agent_session(
            state,
            session_id,
            lock_timeout_seconds=lock_timeout_seconds,
        )
    except AgentSessionError as exc:
        typer.echo(f"[FAIL] session release failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"[OK] released: {session.session_id}")
    typer.echo(f"[OK] status: {session.status.value}")


@channel_adapters_app.command("init")
def init_channel_adapters(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Messaging adapter runbook output path."),
    ] = Path("integrations/channels/adapters.json"),
) -> None:
    """Write optional messaging adapter runbook metadata for AI-Researcher."""

    manifest_path = write_channel_adapter_manifest(output)
    channel_count = len(iter_openclaw_channel_plugins())
    typer.echo(f"[OK] channel_adapters: {channel_count}")
    typer.echo(f"[OK] manifest: {manifest_path}")
    typer.echo(
        "[OK] approval_bridge: airesearcher runtime approve latest "
        f"--state {DEFAULT_RUNTIME_APPROVALS_PATH}"
    )


@channel_adapters_app.command("list")
def list_channel_adapters(
    channel: Annotated[
        str | None,
        typer.Option("--channel", help="Optional channel or upstream plugin ID to show."),
    ] = None,
) -> None:
    """List optional upstream messaging adapter metadata."""

    plugins: tuple[OpenClawChannelPlugin, ...]
    if channel:
        try:
            plugins = (get_openclaw_channel_plugin(channel),)
        except KeyError as exc:
            typer.echo(f"[FAIL] {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        plugins = iter_openclaw_channel_plugins()
    typer.echo(f"[OK] channel_adapters: {len(plugins)}")
    for plugin in plugins:
        typer.echo(
            f"[CHANNEL] channel={plugin.channel_id} upstream_plugin={plugin.plugin_id} "
            f"package={plugin.package_name} route={plugin.install_route}"
        )


@openclaw_channels_app.command("init")
def init_openclaw_channels(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="OpenClaw channel manifest output path."),
    ] = Path("integrations/openclaw/channels.json"),
) -> None:
    """Write OpenClaw channel plugin install metadata for AI-Researcher."""

    manifest_path = write_openclaw_channel_manifest(output)
    channel_count = len(iter_openclaw_channel_plugins())
    typer.echo(f"[OK] openclaw_channels: {channel_count}")
    typer.echo(f"[OK] manifest: {manifest_path}")
    typer.echo(
        "[OK] approval_bridge: airesearcher runtime approve latest "
        f"--state {DEFAULT_RUNTIME_APPROVALS_PATH}"
    )


@openclaw_channels_app.command("list")
def list_openclaw_channels(
    channel: Annotated[
        str | None,
        typer.Option("--channel", help="Optional channel or plugin ID to show."),
    ] = None,
) -> None:
    """List official/common OpenClaw channel plugin metadata."""

    plugins: tuple[OpenClawChannelPlugin, ...]
    if channel:
        try:
            plugins = (get_openclaw_channel_plugin(channel),)
        except KeyError as exc:
            typer.echo(f"[FAIL] {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        plugins = iter_openclaw_channel_plugins()
    typer.echo(f"[OK] openclaw_channels: {len(plugins)}")
    for plugin in plugins:
        package = plugin.package_name or "bundled"
        typer.echo(
            f"[CHANNEL] channel={plugin.channel_id} plugin={plugin.plugin_id} "
            f"package={package} route={plugin.install_route}"
        )


@ccswitch_code_agents_app.command("init")
def init_ccswitch_code_agents(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="cc-switch code-agent manifest output path."),
    ] = Path("integrations/cc-switch/code-agent.json"),
) -> None:
    """Write cc-switch / Claude Code backend metadata for AI-Researcher."""

    manifest_path = write_ccswitch_code_agent_manifest(output)
    backend_count = len(iter_ccswitch_code_agent_backends())
    typer.echo(f"[OK] ccswitch_code_agent_backends: {backend_count}")
    typer.echo(f"[OK] manifest: {manifest_path}")
    typer.echo("[OK] validation_owner: AI-Researcher")


@ccswitch_code_agents_app.command("list")
def list_ccswitch_code_agents(
    backend: Annotated[
        str | None,
        typer.Option("--backend", help="Optional cc-switch backend ID to show."),
    ] = None,
) -> None:
    """List cc-switch / Claude Code code-agent backend metadata."""

    backends: tuple[CCSwitchCodeAgentBackend, ...]
    if backend:
        try:
            backends = (get_ccswitch_code_agent_backend(backend),)
        except KeyError as exc:
            typer.echo(f"[FAIL] {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        backends = iter_ccswitch_code_agent_backends()
    typer.echo(f"[OK] ccswitch_code_agent_backends: {len(backends)}")
    for code_backend in backends:
        typer.echo(
            f"[BACKEND] backend={code_backend.backend_id} runner={code_backend.runner_command} "
            f"provider={code_backend.provider_mode} validator=AI-Researcher"
        )


@opencode_code_agents_app.command("init")
def init_opencode_code_agents(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="OpenCode code-agent manifest output path."),
    ] = Path("integrations/opencode/code-agent.json"),
) -> None:
    """Write OpenCode direct backend metadata for AI-Researcher."""

    manifest_path = write_opencode_code_agent_manifest(output)
    backend_count = len(iter_opencode_code_agent_backends())
    typer.echo(f"[OK] opencode_code_agent_backends: {backend_count}")
    typer.echo(f"[OK] manifest: {manifest_path}")
    typer.echo("[OK] validation_owner: AI-Researcher")


@opencode_code_agents_app.command("list")
def list_opencode_code_agents(
    backend: Annotated[
        str | None,
        typer.Option("--backend", help="Optional OpenCode backend ID to show."),
    ] = None,
) -> None:
    """List OpenCode direct code-agent backend metadata."""

    backends: tuple[OpenCodeCodeAgentBackend, ...]
    if backend:
        try:
            backends = (get_opencode_code_agent_backend(backend),)
        except KeyError as exc:
            typer.echo(f"[FAIL] {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        backends = iter_opencode_code_agent_backends()
    typer.echo(f"[OK] opencode_code_agent_backends: {len(backends)}")
    for code_backend in backends:
        modes = ",".join(code_backend.execution_modes)
        typer.echo(
            f"[BACKEND] backend={code_backend.backend_id} runner={code_backend.runner_command} "
            f"provider={code_backend.provider_mode} modes={modes} validator=AI-Researcher"
        )


@scansci_pdf_app.command("init")
def init_scansci_pdf_sources(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="ScanSci PDF integration manifest output path."),
    ] = Path("integrations/scansci-pdf/pdf-source.json"),
) -> None:
    """Write ScanSci PDF integration metadata for AI-Researcher."""

    manifest_path = write_scansci_pdf_manifest(output)
    integration_count = len(iter_scansci_pdf_integrations())
    typer.echo(f"[OK] scansci_pdf_integrations: {integration_count}")
    typer.echo(f"[OK] manifest: {manifest_path}")
    typer.echo("[OK] default_policy: oa_first_legal_only")


@scansci_pdf_app.command("list")
def list_scansci_pdf_sources(
    integration: Annotated[
        str | None,
        typer.Option("--integration", help="Optional ScanSci PDF integration ID to show."),
    ] = None,
) -> None:
    """List ScanSci PDF integration metadata."""

    integrations: tuple[ScanSciPdfIntegration, ...]
    if integration:
        try:
            integrations = (get_scansci_pdf_integration(integration),)
        except KeyError as exc:
            typer.echo(f"[FAIL] {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        integrations = iter_scansci_pdf_integrations()
    typer.echo(f"[OK] scansci_pdf_integrations: {len(integrations)}")
    for pdf_integration in integrations:
        allowed = ",".join(pdf_integration.allowed_default_sources)
        gated = ",".join(pdf_integration.approval_required_sources)
        typer.echo(
            f"[PDF] integration={pdf_integration.integration_id} "
            f"runner={pdf_integration.runner_command} license={pdf_integration.license} "
            f"default_sources={allowed} approval_required={gated}"
        )


@slash_app.command("init")
def init_slash_commands(
    directory: Annotated[
        Path,
        typer.Option(
            "--directory",
            "-d",
            help="Project slash command directory to create.",
        ),
    ] = Path(".airesearcher/commands"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing command definitions."),
    ] = False,
) -> None:
    """Create project-scoped slash command templates."""

    written, skipped = _write_slash_command_templates(directory, force=force)
    typer.echo(f"[OK] slash commands written: {written}")
    typer.echo(f"[OK] slash commands skipped: {skipped}")
    typer.echo(f"[OK] directory: {directory}")


@slash_app.command("list")
def list_slash_commands(
    directory: Annotated[
        Path,
        typer.Option(
            "--directory",
            "-d",
            help="Project slash command directory to inspect.",
        ),
    ] = Path(".airesearcher/commands"),
) -> None:
    """List project-scoped slash command templates."""

    if not directory.exists():
        typer.echo(f"[FAIL] slash command directory does not exist: {directory}", err=True)
        raise typer.Exit(code=1)
    commands = sorted(directory.rglob("*.toml"))
    for command in commands:
        name = command.relative_to(directory).with_suffix("").as_posix().replace("/", ":")
        typer.echo(f"/{name}")


def _write_slash_command_templates(directory: Path, *, force: bool) -> tuple[int, int]:
    written = 0
    skipped = 0
    for relative_path, (description, prompt) in DEFAULT_SLASH_COMMANDS.items():
        target = directory / relative_path
        if target.exists() and not force:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_slash_command_toml(description, prompt), encoding="utf-8")
        written += 1
    return written, skipped


def _autopilot_literature_clients(cache_root: Path) -> dict[str, LiteratureSearchClient]:
    circuit_state_path = cache_root / "source-circuit-breakers.json"
    clients: dict[str, LiteratureSearchClient] = {
        "arxiv": ArxivClient(),
        "openalex": OpenAlexClient(circuit_state_path=circuit_state_path),
    }
    if semantic_scholar_enabled():
        clients["semantic_scholar"] = SemanticScholarClient(circuit_state_path=circuit_state_path)
    return clients


def _run_autopilot_cycle(
    *,
    config_path: Path,
    env_path: Path,
    vault: Path,
    cache: Path,
    output_dir: Path,
    deliverables_dir: Path,
    state: Path,
    heartbeat_state: Path,
    project_id: str,
    demo: str,
    max_queries: int,
    max_results_per_source: int,
    timeout_seconds: int,
    max_tokens: int | None,
    min_quality_score: float,
    review: bool,
    paper_template_id: str,
    agent_profile_paths: tuple[Path, ...],
    push_inspiration: bool,
    runtime_network_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cycle_id = f"cycle-{now.strftime('%Y%m%dT%H%M%SZ')}"
    cycle_dir = output_dir / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)
    heartbeat_report_path = cycle_dir / "runtime-heartbeat-report.json"
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="cycle-start",
        progress=f"cycle_dir={cycle_dir.as_posix()}",
        report_path=heartbeat_report_path,
        message="Autopilot cycle directory initialized.",
        artifact_refs=(cycle_dir,),
    )
    _load_optional_env(env_path)
    agent_profile_contexts = _load_agent_profile_contexts(
        agent_profile_paths,
        env=_merged_optional_env(env_path),
        base_dir=Path.cwd(),
    )
    agent_profiles = _agent_profiles_summary(agent_profile_contexts)
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="agent-profiles",
        progress=f"profile_count={len(agent_profile_contexts)}",
        report_path=heartbeat_report_path,
        message="Agent profile context loaded for this cycle.",
        artifact_refs=(
            profile.get("profile_path")
            for profile in _mapping_list(agent_profiles.get("profiles"))
        ),
    )
    literature_clients = _autopilot_literature_clients(cache)
    source_preflight = _run_source_preflight_gate(
        clients=literature_clients,
        cycle_dir=cycle_dir,
        vault=vault,
        project_id=project_id,
        cycle_id=cycle_id,
    )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="source-preflight",
        progress=(
            f"verdict={source_preflight['verdict']};"
            f"blocked={len(source_preflight['blocked_sources'])};"
            f"optional={len(source_preflight['optional_degraded_sources'])}"
        ),
        report_path=heartbeat_report_path,
        message="External literature source preflight completed.",
        artifact_refs=(
            source_preflight.get("output_path"),
            source_preflight.get("markdown_path"),
            source_preflight.get("issue_path"),
        ),
    )
    if bool(source_preflight["blocked"]):
        followup_records = _issue_followup_records(vault, project_id)
        _merge_scheduler_state(state, followup_records)
        runtime_heartbeat = _write_cycle_runtime_heartbeat(
            heartbeat_state=heartbeat_state,
            cycle_id=cycle_id,
            stage="source-preflight-blocked",
            progress=f"followups={len(followup_records)}",
            report_path=heartbeat_report_path,
            message="Cycle blocked before costly work because a required source is unsafe.",
            artifact_refs=(
                source_preflight.get("output_path"),
                source_preflight.get("markdown_path"),
                source_preflight.get("issue_path"),
                state,
            ),
        )
        blocked_summary: dict[str, Any] = {
            "cycle_id": cycle_id,
            "status": "blocked",
            "started_at": now.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "vault": vault.as_posix(),
            "cache": cache.as_posix(),
            "agent_profiles": agent_profiles,
            "source_preflight": source_preflight,
            "runtime_heartbeat": runtime_heartbeat,
            "review": {"status": "skipped_source_preflight"},
            "followups": {
                "state_path": state.as_posix(),
                "task_count": len(followup_records),
                "tasks": followup_records,
            },
        }
        summary_path = cycle_dir / "cycle-summary.json"
        blocked_summary["summary_path"] = summary_path.as_posix()
        summary_path.write_text(
            json.dumps(blocked_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return blocked_summary

    literature_report = run_daily_literature_refresh(
        vault_root=vault,
        cache_root=cache,
        clients=literature_clients,
        now=now,
        config=LiteratureRefreshConfig(
            max_queries=max_queries,
            max_results_per_source=max_results_per_source,
            seed_queries=_autopilot_literature_seed_queries(demo),
        ),
    )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="literature-refresh",
        progress=(
            f"queries={len(getattr(literature_report, 'queries', ()))},"
            f"documents={len(getattr(literature_report, 'documents', ()))},"
            f"fetches={len(getattr(literature_report, 'fetches', ()))}"
        ),
        report_path=heartbeat_report_path,
        message="Daily literature refresh completed from configured online sources.",
        artifact_refs=(getattr(literature_report, "summary_path", None),),
    )
    candidate = _autopilot_candidate_from_literature(
        literature_report,
        project_id=project_id,
        demo=demo,
        now=now,
    )
    candidate_path = cycle_dir / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="candidate",
        progress=f"candidate={candidate.id};status={candidate.status.value}",
        report_path=heartbeat_report_path,
        message="Research candidate derived from retrieved literature.",
        artifact_refs=(candidate_path,),
    )

    similarity_report = run_project_similarity_check(
        candidate=candidate,
        vault_root=vault,
        cache_root=cache,
        clients=literature_clients,
        now=now,
        config=SimilarityCheckConfig(
            max_queries=max_queries,
            max_results_per_source=max_results_per_source,
        ),
    )
    similarity_project_path = None
    if getattr(similarity_report, "findings", ()):
        similarity_project_path = link_similarity_report_to_project(
            report=similarity_report,
            vault_root=vault,
            project_id=project_id,
        )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="similarity-check",
        progress=(
            f"findings={len(getattr(similarity_report, 'findings', ()))},"
            f"fetches={len(getattr(similarity_report, 'fetches', ()))}"
        ),
        report_path=heartbeat_report_path,
        message="Adjacent-work similarity check completed.",
        artifact_refs=(
            getattr(similarity_report, "summary_path", None),
            similarity_project_path,
        ),
    )

    research_plan_artifact = generate_research_plan(
        candidate=candidate,
        project_id=project_id,
        vault_root=vault,
        output_dir=cycle_dir,
        compile_pdf=True,
        similarity_summary=getattr(similarity_report, "summary_path", None),
        literature_summary=getattr(literature_report, "summary_path", None),
        timeout_seconds=max(timeout_seconds, 60),
    )
    research_plan_payload = research_plan_artifact.to_dict()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="research-plan",
        progress=(
            f"audit_passed={research_plan_artifact.audit.passed};"
            f"compile_status={research_plan_artifact.compile_status}"
        ),
        report_path=heartbeat_report_path,
        message="Executable research plan generated before experiment execution.",
        artifact_refs=(
            research_plan_payload.get("markdown_path"),
            research_plan_payload.get("json_path"),
            research_plan_payload.get("tex_path"),
            research_plan_payload.get("pdf_path"),
        ),
    )
    if (
        not research_plan_artifact.audit.passed
        or research_plan_artifact.compile_status != "compiled"
    ):
        followup_records = _issue_followup_records(vault, project_id)
        _merge_scheduler_state(state, followup_records)
        runtime_heartbeat = _write_cycle_runtime_heartbeat(
            heartbeat_state=heartbeat_state,
            cycle_id=cycle_id,
            stage="research-plan-blocked",
            progress=f"followups={len(followup_records)}",
            report_path=heartbeat_report_path,
            message="Cycle blocked because the research plan gate did not pass.",
            artifact_refs=(
                research_plan_payload.get("markdown_path"),
                research_plan_payload.get("json_path"),
                research_plan_payload.get("tex_path"),
                research_plan_payload.get("pdf_path"),
                state,
            ),
        )
        blocked_summary = {
            "cycle_id": cycle_id,
            "status": "blocked",
            "blocked_reason": "research_plan_gate",
            "started_at": now.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "vault": vault.as_posix(),
            "cache": cache.as_posix(),
            "agent_profiles": agent_profiles,
            "source_preflight": source_preflight,
            "candidate_path": candidate_path.as_posix(),
            "literature": {
                "query_count": len(getattr(literature_report, "queries", ())),
                "fetches": _serialise_fetches(getattr(literature_report, "fetches", ())),
                "document_count": len(getattr(literature_report, "documents", ())),
                "summary_path": _path_text(getattr(literature_report, "summary_path", None)),
            },
            "candidate": candidate.model_dump(mode="json"),
            "similarity": {
                "fetches": _serialise_fetches(getattr(similarity_report, "fetches", ())),
                "finding_count": len(getattr(similarity_report, "findings", ())),
                "summary_path": _path_text(getattr(similarity_report, "summary_path", None)),
                "project_path": _path_text(similarity_project_path),
            },
            "research_plan": research_plan_payload,
            "runtime_heartbeat": runtime_heartbeat,
            "review": {"status": "skipped_research_plan_gate"},
            "followups": {
                "state_path": state.as_posix(),
                "task_count": len(followup_records),
                "tasks": followup_records,
            },
        }
        summary_path = cycle_dir / "cycle-summary.json"
        blocked_summary["summary_path"] = summary_path.as_posix()
        summary_path.write_text(
            json.dumps(blocked_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return blocked_summary

    loop_campaign = build_closed_loop_campaign(
        candidate=candidate,
        project_id=project_id,
        cycle_id=cycle_id,
        research_plan=research_plan_payload,
    )
    loop_selection = select_loop_candidate(loop_campaign)
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="loop-campaign",
        progress=(
            f"campaign={loop_campaign.campaign_id};"
            f"selected={loop_selection.selected_candidate_id}"
        ),
        report_path=heartbeat_report_path,
        message="Closed-loop campaign initialized and optimizer selected a candidate.",
    )

    inspiration_report = run_inspiration_refresh(
        vault_root=vault,
        queries=_autopilot_inspiration_queries(candidate, demo=demo),
        config=InspirationRefreshConfig(
            max_queries=max_queries,
            max_results_per_source=max_results_per_source,
        ),
    )
    inspiration_pushes: tuple[NotificationSendRecord, ...] = ()
    if push_inspiration:
        inspiration_pushes = send_inspiration_digest(inspiration_report)
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="inspiration-refresh",
        progress=(
            f"items={len(getattr(inspiration_report, 'items', ()))},"
            f"pushes={len(inspiration_pushes)}"
        ),
        report_path=heartbeat_report_path,
        message="Broad inspiration refresh completed; community signals remain non-scholarly evidence.",
        artifact_refs=(getattr(inspiration_report, "summary_path", None),),
    )

    demo_result = run_scientistbench_demo(
        demo=demo,
        output_dir=cycle_dir / "demo",
        timeout_seconds=timeout_seconds,
        task_metadata=runtime_network_metadata,
    )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="experiment",
        progress=f"demo={demo_result.demo};run_id={demo_result.run_id}",
        report_path=heartbeat_report_path,
        message="Controlled benchmark experiment completed.",
        artifact_refs=(
            demo_result.report_path,
            demo_result.run_record_path,
            demo_result.validation_json_path,
            demo_result.evidence_map_path,
        ),
    )
    reproduction_check = _run_cycle_reproduction_check(
        cycle_dir=cycle_dir,
        demo=demo,
        timeout_seconds=timeout_seconds,
    )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="reproduction-check",
        progress=f"status={reproduction_check.get('status')};exit={reproduction_check.get('exit_code')}",
        report_path=heartbeat_report_path,
        message="Best-result reproduction check completed.",
        artifact_refs=(
            reproduction_check.get("json_path"),
            reproduction_check.get("markdown_path"),
            *(reproduction_check.get("run_record_paths") or ()),
            *(reproduction_check.get("validation_json_paths") or ()),
        ),
    )
    citations = _generate_cycle_citations(
        literature_report=literature_report,
        cycle_dir=cycle_dir,
    )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="citation-package",
        progress=(
            f"status={citations.get('status')};"
            f"verified={citations.get('verified_count')};"
            f"blocked={citations.get('blocked_count')}"
        ),
        report_path=heartbeat_report_path,
        message="Citation package generated or explicitly skipped with reason.",
        artifact_refs=(citations.get("metadata_path"), citations.get("bib_path")),
    )

    summary: dict[str, Any] = {
        "cycle_id": cycle_id,
        "started_at": now.isoformat(),
        "completed_at": None,
        "project_id": project_id,
        "vault": vault.as_posix(),
        "cache": cache.as_posix(),
        "agent_profiles": agent_profiles,
        "source_preflight": source_preflight,
        "candidate_path": candidate_path.as_posix(),
        "literature": {
            "query_count": len(getattr(literature_report, "queries", ())),
            "fetches": _serialise_fetches(getattr(literature_report, "fetches", ())),
            "document_count": len(getattr(literature_report, "documents", ())),
            "summary_path": _path_text(getattr(literature_report, "summary_path", None)),
        },
        "candidate": candidate.model_dump(mode="json"),
        "similarity": {
            "fetches": _serialise_fetches(getattr(similarity_report, "fetches", ())),
            "finding_count": len(getattr(similarity_report, "findings", ())),
            "summary_path": _path_text(getattr(similarity_report, "summary_path", None)),
            "project_path": _path_text(similarity_project_path),
        },
        "research_plan": research_plan_payload,
        "inspiration": {
            "query_count": len(getattr(inspiration_report, "queries", ())),
            "fetches": _serialise_inspiration_fetches(
                getattr(inspiration_report, "fetches", ())
            ),
            "item_count": len(getattr(inspiration_report, "items", ())),
            "summary_path": _path_text(getattr(inspiration_report, "summary_path", None)),
            "evidence_policy": "dataset/community/news signals only; not scholarly evidence",
            "pushes": [record.to_json_dict() for record in inspiration_pushes],
        },
        "citations": citations,
        "demo": {
            "demo": demo_result.demo,
            "run_id": demo_result.run_id,
            "experiment_dir": _relative_path_text(demo_result.experiment_dir),
            "report_path": _relative_path_text(demo_result.report_path),
            "run_record_path": _relative_path_text(demo_result.run_record_path),
            "validation_json_path": _relative_path_text(demo_result.validation_json_path),
            "evidence_map_path": _relative_path_text(demo_result.evidence_map_path),
        },
        "review": {"status": "pending_manuscript_review" if review else "skipped"},
        "reproduction_check": reproduction_check,
        "followups": {
            "state_path": state.as_posix(),
            "task_count": 0,
            "tasks": [],
        },
    }
    network_approval = _autopilot_demo_network_summary(demo_result.run_record_path)
    if network_approval:
        summary["demo"]["network_approval"] = network_approval
    loop_iteration = create_loop_iteration_from_cycle_summary(
        campaign=loop_campaign,
        decision=loop_selection,
        summary=summary,
        base_dir=cycle_dir,
    )
    loop_artifact = write_loop_report_artifact(
        campaign=loop_campaign,
        iterations=(loop_iteration,),
        output_dir=cycle_dir / "loop-campaign",
        vault_root=vault,
        project_id=project_id,
    )
    loop_artifact_summary = loop_artifact.to_summary()
    summary["loop_campaign"] = {
        "campaign_id": loop_campaign.campaign_id,
        "selected_candidate_id": loop_selection.selected_candidate_id,
        "decision_policy": loop_selection.decision_policy.value,
        **loop_artifact_summary,
    }
    summary["loop_report"] = {
        "json_path": loop_artifact_summary["json_path"],
        "markdown_path": loop_artifact_summary["markdown_path"],
        "vault_path": loop_artifact_summary["vault_path"],
    }
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="loop-report",
        progress=f"loop_report={loop_artifact_summary['json_path']}",
        report_path=heartbeat_report_path,
        message="Closed-loop report written to artifacts and Obsidian memory.",
        artifact_refs=(
            loop_artifact_summary.get("json_path"),
            loop_artifact_summary.get("markdown_path"),
            loop_artifact_summary.get("vault_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path = cycle_dir / "cycle-summary.json"
    summary["summary_path"] = summary_path.as_posix()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    related_work_inspection = inspect_related_work(
        cycle_summary_path=summary_path,
        output_dir=cycle_dir / "related-work",
    )
    summary["related_work_inspection"] = related_work_inspection.to_dict()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="related-work-inspection",
        progress=f"status={summary['related_work_inspection'].get('status', 'completed')}",
        report_path=heartbeat_report_path,
        message="Related-work overlap inspection completed.",
        artifact_refs=(
            summary["related_work_inspection"].get("json_path"),
            summary["related_work_inspection"].get("markdown_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    paper_manuscript = compose_publication_manuscript(
        cycle_summary_path=summary_path,
        output_dir=cycle_dir / "paper-manuscript",
        vault_root=vault,
        project_id=project_id,
    )
    summary["paper_manuscript"] = paper_manuscript.to_dict()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="paper-manuscript",
        progress=f"markdown={paper_manuscript.markdown_path}",
        report_path=heartbeat_report_path,
        message="Publication manuscript markdown produced.",
        artifact_refs=(
            paper_manuscript.markdown_path,
            *_review_text_artifact_paths(getattr(paper_manuscript, "analysis_artifact_paths", ())),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    paper_build = build_latex_paper_from_markdown(
        markdown_path=Path(paper_manuscript.markdown_path),
        output_dir=cycle_dir / "paper-build",
        template_id=paper_template_id,
        vault_root=vault,
        project_id=project_id,
    )
    summary["paper_build"] = paper_build.to_dict()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="paper-build",
        progress=f"status={summary['paper_build'].get('status')}",
        report_path=heartbeat_report_path,
        message="LaTeX paper build completed.",
        artifact_refs=(
            summary["paper_build"].get("json_path"),
            summary["paper_build"].get("markdown_path"),
            summary["paper_build"].get("tex_path"),
            summary["paper_build"].get("pdf_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    review_context_path = cycle_dir / "review-evidence-context.json"
    review_audit_summary = _autopilot_review_audit_summary(
        summary=summary,
        reproduction_check=reproduction_check,
        paper_build=paper_build.to_dict(),
    )
    review_context = {
        "audit_summary": review_audit_summary,
        "cycle_id": cycle_id,
        "project_id": project_id,
        "agent_profiles": summary["agent_profiles"],
        "stage_agent_contexts": summary["agent_profiles"].get("stage_runtime_contexts", {}),
        "candidate": summary["candidate"],
        "literature": summary["literature"],
        "similarity": summary["similarity"],
        "research_plan": summary["research_plan"],
        "loop_campaign": summary["loop_campaign"],
        "citations": summary["citations"],
        "related_work_inspection": summary["related_work_inspection"],
        "demo": summary["demo"],
        "reproduction_check": reproduction_check,
        "paper_manuscript": paper_manuscript.to_dict(),
    }
    review_context_path.write_text(
        json.dumps(review_context, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    summary["review_context_path"] = review_context_path.as_posix()
    reference_evidence_path = _write_autopilot_reference_evidence(
        cycle_dir=cycle_dir,
        audit_summary=review_audit_summary,
    )
    summary["formal_reference_evidence_path"] = reference_evidence_path.as_posix()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="review-evidence",
        progress=f"context={review_context_path.as_posix()}",
        report_path=heartbeat_report_path,
        message="Review evidence context and formal reference proof written.",
        artifact_refs=(review_context_path, reference_evidence_path),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    review_evidence_paths: list[Path | str] = [
        summary_path,
        review_context_path,
        reference_evidence_path,
        Path(demo_result.report_path),
        Path(demo_result.run_record_path),
        Path(demo_result.validation_json_path),
        Path(demo_result.evidence_map_path),
    ]
    for optional_path in (
        getattr(literature_report, "summary_path", None),
        research_plan_payload.get("markdown_path"),
        research_plan_payload.get("json_path"),
        research_plan_payload.get("tex_path"),
        citations.get("metadata_path"),
        citations.get("bib_path"),
        summary["related_work_inspection"].get("json_path"),
        summary["related_work_inspection"].get("markdown_path"),
        getattr(similarity_report, "summary_path", None),
        similarity_project_path,
        reproduction_check.get("json_path"),
        summary["loop_report"].get("json_path"),
        summary["loop_report"].get("markdown_path"),
        summary["runtime_heartbeat"].get("report_path"),
        paper_build.to_dict().get("json_path"),
        paper_build.to_dict().get("markdown_path"),
        *[
            profile.get("profile_path")
            for profile in _mapping_list(summary["agent_profiles"].get("profiles"))
        ],
        *_review_text_artifact_paths(getattr(paper_manuscript, "analysis_artifact_paths", ())),
    ):
        if isinstance(optional_path, str | Path):
            review_evidence_paths.append(optional_path)
    review_result = _run_autopilot_review(
        enabled=review,
        config_path=config_path,
        env_path=env_path,
        vault=vault,
        project_id=project_id,
        source_task_id="autopilot",
        cycle_dir=cycle_dir,
        report_path=Path(paper_manuscript.markdown_path),
        evidence_paths=review_evidence_paths,
        max_tokens=max_tokens,
        min_quality_score=min_quality_score,
    )
    summary["review"] = review_result
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="review",
        progress=f"status={review_result.get('status')}",
        report_path=heartbeat_report_path,
        message="LLM evidence review completed or was explicitly skipped.",
        artifact_refs=(
            review_result.get("output_path"),
            review_result.get("review_path"),
            review_result.get("vault_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    publication_audit = audit_publication_quality(
        cycle_summary_path=summary_path,
        target="ccf-b",
        output_dir=cycle_dir,
        vault_root=vault,
        project_id=project_id,
    )
    summary["publication_audit"] = publication_audit.to_dict()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="publication-audit",
        progress=(
            f"verdict={summary['publication_audit'].get('verdict')};"
            f"publishable={summary['publication_audit'].get('publishable')}"
        ),
        report_path=heartbeat_report_path,
        message="Publication-readiness gate completed.",
        artifact_refs=(
            summary["publication_audit"].get("output_path"),
            summary["publication_audit"].get("markdown_path"),
            summary["publication_audit"].get("vault_review_path"),
            summary["publication_audit"].get("vault_issue_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    evidence_gate = run_evidence_gate(
        cycle_summary_path=summary_path,
        output_dir=cycle_dir / "evidence-gate",
        vault_root=vault,
        project_id=project_id,
    )
    summary["evidence_gate"] = evidence_gate.to_dict()
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="evidence-gate",
        progress=(
            f"verdict={summary['evidence_gate'].get('verdict')};"
            f"release_allowed={summary['evidence_gate'].get('release_allowed')}"
        ),
        report_path=heartbeat_report_path,
        message="Evidence coverage gate completed.",
        artifact_refs=(
            summary["evidence_gate"].get("output_path"),
            summary["evidence_gate"].get("markdown_path"),
            summary["evidence_gate"].get("vault_review_path"),
            summary["evidence_gate"].get("vault_issue_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat

    followup_records = _issue_followup_records(vault, project_id)
    _merge_scheduler_state(state, followup_records)
    summary["followups"] = {
        "state_path": state.as_posix(),
        "task_count": len(followup_records),
        "tasks": followup_records,
    }
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="followups",
        progress=f"task_count={len(followup_records)}",
        report_path=heartbeat_report_path,
        message="Scheduler follow-up tasks merged.",
        artifact_refs=(state,),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary["deliverables"] = _export_cycle_deliverables(
        summary=summary,
        summary_path=summary_path,
        output_root=deliverables_dir,
        project_id=project_id,
    )
    runtime_heartbeat = _write_cycle_runtime_heartbeat(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        stage="deliverables",
        progress=f"status={summary['deliverables'].get('status')}",
        report_path=heartbeat_report_path,
        message="Cycle deliverables exported.",
        artifact_refs=(
            summary["deliverables"].get("manifest_path"),
            summary["deliverables"].get("pdf_path"),
            summary["deliverables"].get("markdown_path"),
        ),
    )
    summary["runtime_heartbeat"] = runtime_heartbeat
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _generate_cycle_citations(*, literature_report: object, cycle_dir: Path) -> dict[str, object]:
    documents = list(getattr(literature_report, "documents", ()) or ())
    if not documents:
        return {
            "status": "skipped",
            "reason": "no_literature_documents",
            "verified_count": 0,
            "blocked_count": 0,
        }
    artifact = generate_bibtex(documents, cycle_dir / "citations")
    payload = artifact.to_dict()
    return {
        "status": "generated",
        "verified_count": len(documents) - len(artifact.blocked_document_ids),
        "blocked_count": len(artifact.blocked_document_ids),
        **payload,
    }


def _review_text_artifact_paths(paths: object) -> tuple[str | Path, ...]:
    if not isinstance(paths, list | tuple):
        return ()
    text_suffixes = {".json", ".md", ".txt", ".tex", ".yaml", ".yml", ".csv"}
    return tuple(
        path
        for path in paths
        if isinstance(path, str | Path) and Path(path).suffix.casefold() in text_suffixes
    )


def _write_autopilot_reference_evidence(
    *,
    cycle_dir: Path,
    audit_summary: dict[str, Any],
) -> Path:
    """Write a compact reference-key proof so LLM review is not misled by truncation."""

    citations = audit_summary.get("citations")
    citation_summary = citations if isinstance(citations, dict) else {}
    formal_refs = citation_summary.get("formal_references")
    formal_summary = formal_refs if isinstance(formal_refs, dict) else {}
    displayed = formal_summary.get("displayed_references")
    displayed_refs = displayed if isinstance(displayed, list) else []
    lines = [
        "# Formal Reference Evidence",
        "",
        "This compact file records the exact references rendered in the manuscript and "
        "their citation metadata lookup status. Use it with the full BibTeX and metadata "
        "files when checking citation consistency.",
        "",
        f"- Metadata path: `{citation_summary.get('metadata_path') or 'unknown'}`",
        f"- BibTeX path: `{citation_summary.get('bib_path') or 'unknown'}`",
        f"- Displayed reference count: `{formal_summary.get('displayed_count', 0)}`",
        (
            "- Citation metadata key count: "
            f"`{formal_summary.get('citation_metadata_key_count', 0)}`"
        ),
        (
            "- Citation metadata status: "
            f"`{formal_summary.get('citation_metadata_status') or 'unknown'}`"
        ),
        "",
        "| Key | Metadata status | Metadata locator | Manuscript locator | Title |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in displayed_refs:
        row = item if isinstance(item, dict) else {}
        lines.append(
            "| "
            f"`{_markdown_table_cell(row.get('key'))}` | "
            f"`{_markdown_table_cell(row.get('citation_metadata_status'))}` | "
            f"`{_markdown_table_cell(row.get('citation_metadata_locator'))}` | "
            f"`{_markdown_table_cell(row.get('doi_or_url_evidence'))}` | "
            f"{_markdown_table_cell(row.get('title'))} |"
        )
    path = cycle_dir / "formal-reference-evidence.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _markdown_table_cell(value: object) -> str:
    text = str(value or "unknown")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _autopilot_review_audit_summary(
    *,
    summary: dict[str, Any],
    reproduction_check: dict[str, Any],
    paper_build: dict[str, Any],
) -> dict[str, Any]:
    def mapping(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    literature = mapping(summary.get("literature"))
    similarity = mapping(summary.get("similarity"))
    research_plan = mapping(summary.get("research_plan"))
    research_plan_audit = mapping(research_plan.get("audit"))
    citations = mapping(summary.get("citations"))
    related_work = mapping(summary.get("related_work_inspection"))
    paper_manuscript = mapping(summary.get("paper_manuscript"))
    paper_quality = mapping(paper_build.get("paper_quality"))
    formal_references = _autopilot_formal_reference_summary(
        paper_manuscript.get("markdown_path"),
        citation_metadata_path=citations.get("metadata_path"),
    )
    return {
        "agent_profiles": mapping(summary.get("agent_profiles")),
        "candidate": _autopilot_candidate_review_summary(summary),
        "literature": {
            "query_count": literature.get("query_count"),
            "document_count": literature.get("document_count"),
            "summary_path": literature.get("summary_path"),
        },
        "similarity": {
            "finding_count": similarity.get("finding_count"),
            "summary_path": similarity.get("summary_path"),
            "project_path": similarity.get("project_path"),
        },
        "research_plan": {
            "verdict": research_plan_audit.get("verdict"),
            "passed": research_plan_audit.get("passed"),
            "score": research_plan_audit.get("score"),
            "issues": research_plan_audit.get("issues", []),
            "warnings": research_plan_audit.get("warnings", []),
            "compile_status": research_plan.get("compile_status"),
            "page_count": research_plan.get("page_count"),
            "markdown_path": research_plan.get("markdown_path"),
            "json_path": research_plan.get("json_path"),
            "tex_path": research_plan.get("tex_path"),
            "pdf_path": research_plan.get("pdf_path"),
        },
        "citations": {
            "additional_verified_record_count": formal_references.get("omitted_verified_count"),
            "verified_count": citations.get("verified_count"),
            "blocked_count": citations.get("blocked_count"),
            "metadata_path": citations.get("metadata_path"),
            "bib_path": citations.get("bib_path"),
            "formal_references": formal_references,
        },
        "related_work_inspection": {
            "json_path": related_work.get("json_path"),
            "markdown_path": related_work.get("markdown_path"),
            "inspected_count": related_work.get("inspected_count"),
            "source_backed_count": related_work.get("source_backed_count"),
            "abstract_backed_count": related_work.get("abstract_backed_count"),
            "direct_method_count": related_work.get("direct_method_count"),
            "contextual_count": related_work.get("contextual_count"),
        },
        "reproduction_check": {
            "status": reproduction_check.get("status"),
            "exit_code": reproduction_check.get("exit_code"),
            "json_path": reproduction_check.get("json_path"),
            "run_record_paths": reproduction_check.get("run_record_paths", []),
            "validation_json_paths": reproduction_check.get("validation_json_paths", []),
        },
        "paper_build": {
            "status": paper_build.get("status"),
            "json_path": paper_build.get("json_path"),
            "pdf_path": paper_build.get("pdf_path"),
            "paper_quality": {
                "passed": paper_quality.get("passed"),
                "page_count": paper_quality.get("page_count"),
                "word_count": paper_quality.get("word_count"),
                "overfull_hbox_count": paper_quality.get("overfull_hbox_count"),
                "failures": paper_quality.get("failures", []),
            },
        },
    }


def _autopilot_candidate_review_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Keep manuscript candidate claims near the start of review evidence."""

    def mapping(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    candidate = mapping(summary.get("candidate"))
    metadata = mapping(candidate.get("metadata"))
    run_record = _autopilot_read_run_record(summary)
    task_metadata = mapping(run_record.get("task_metadata"))
    metrics = mapping(mapping(run_record.get("metrics")).get("values"))
    metric_keys = (
        "accuracy",
        "baseline_accuracy",
        "accuracy_delta_vs_baseline",
        "zscore_centroid_accuracy",
        "accuracy_delta_vs_zscore",
        "macro_f1",
        "test_rows",
        "train_rows",
        "dataset_rows",
        "class_count",
        "feature_count",
        "accuracy_standard_error",
        "variance_shrinkage",
    )
    metadata_keys = (
        "method",
        "benchmark",
        "dataset",
        "baseline",
        "limitation",
        "demo",
    )
    task_metadata_keys = (
        "proposed_method",
        "method_contribution",
        "dataset",
        "baseline",
        "split_policy",
        "feature_count",
        "real_dataset",
        "network_access_approved",
        "network_access_scope",
        "network_approval_mode",
        "network_approval_id",
        "network_approved_by",
        "approved_network_domains",
        "network_source_urls",
    )
    return {
        "title": candidate.get("title"),
        "description": candidate.get("description"),
        "research_gap": candidate.get("research_gap"),
        "metadata": _autopilot_selected_mapping(metadata, metadata_keys),
        "task_metadata": _autopilot_selected_mapping(task_metadata, task_metadata_keys),
        "recorded_metrics": _autopilot_selected_mapping(metrics, metric_keys),
        "run_record_path": mapping(summary.get("demo")).get("run_record_path"),
    }


def _autopilot_demo_network_summary(run_record_path: Path | str) -> dict[str, Any]:
    def mapping(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    path = Path(run_record_path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    task_metadata = mapping(payload.get("task_metadata"))
    run_metadata = mapping(mapping(payload.get("run")).get("metadata"))
    network_preflight = mapping(run_metadata.get("network_preflight"))
    keys = (
        "network_access_approved",
        "network_access_scope",
        "network_approval_mode",
        "network_approval_id",
        "network_approved_by",
        "approved_network_domains",
        "network_source_urls",
    )
    summary = _autopilot_selected_mapping(task_metadata, keys)
    if network_preflight:
        summary["preflight"] = _autopilot_selected_mapping(
            network_preflight,
            (
                "approved",
                "finding_count",
                "network_access_scope",
                "network_approval_mode",
                "network_approval_id",
                "network_approved_by",
                "approved_network_domains",
                "network_source_urls",
            ),
        )
    return summary


def _autopilot_selected_mapping(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _autopilot_read_run_record(summary: dict[str, Any]) -> dict[str, Any]:
    def mapping(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    run_record_path = mapping(summary.get("demo")).get("run_record_path")
    path = _autopilot_existing_path(run_record_path, summary)
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _autopilot_existing_path(path_value: object, summary: dict[str, Any]) -> Path | None:
    if not isinstance(path_value, str | Path):
        return None
    path = Path(path_value)
    candidates = [path]
    summary_path = summary.get("summary_path")
    if isinstance(summary_path, str | Path):
        summary_parent = Path(summary_path).parent
        if not path.is_absolute():
            candidates.append(summary_parent / path)
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _autopilot_formal_reference_summary(
    manuscript_path: object,
    *,
    citation_metadata_path: object = None,
) -> dict[str, Any]:
    """Return the exact verified references rendered in the final manuscript."""

    citation_metadata = _autopilot_citation_metadata_by_key(citation_metadata_path)
    path = Path(manuscript_path) if isinstance(manuscript_path, str | Path) else None
    if path is None or not path.exists():
        return {
            "status": "missing",
            "displayed_count": 0,
            "displayed_references": [],
            "citation_metadata_key_count": 0,
            "citation_metadata_keys": [],
            "omitted_verified_count": None,
        }

    displayed: list[dict[str, Any]] = []
    omitted_verified_count: int | None = None
    in_references = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "## References":
            in_references = True
            continue
        if in_references and line.startswith("## "):
            break
        if not in_references:
            continue
        if line.startswith("- [Citation package note]"):
            omitted_verified_count = _first_integer(line)
            continue
        if not line.startswith("- [") or "] " not in line:
            continue
        key, tail = line[3:].split("] ", 1)
        clean_key = key.strip()
        title, locator = _autopilot_reference_title_and_locator(tail)
        metadata_row = citation_metadata.get(clean_key, {})
        displayed.append(
            {
                "key": clean_key,
                "title": title.strip(),
                "doi_or_url_evidence": locator.rstrip(".").strip(),
                "manuscript_line": line,
                "citation_metadata_status": metadata_row.get("status"),
                "citation_metadata_document_id": metadata_row.get("document_id"),
                "citation_metadata_locator": (
                    metadata_row.get("doi")
                    or metadata_row.get("url")
                    or metadata_row.get("source_uri")
                ),
            }
        )
    citation_metadata_keys = [
        row["key"] for row in displayed if row["key"] in citation_metadata
    ]
    return {
        "status": "present",
        "displayed_count": len(displayed),
        "citation_metadata_key_count": len(citation_metadata_keys),
        "citation_metadata_keys": citation_metadata_keys,
        "citation_metadata_status": (
            "all_displayed_keys_present"
            if len(citation_metadata_keys) == len(displayed)
            else "some_displayed_keys_missing"
        ),
        "displayed_references": displayed,
        "omitted_verified_count": omitted_verified_count,
    }


def _autopilot_reference_title_and_locator(tail: str) -> tuple[str, str]:
    old_marker = ". DOI/URL evidence: "
    if old_marker in tail:
        title, locator = tail.split(old_marker, 1)
        return title.strip(), locator.rstrip(".").strip()
    locator = ""
    locator_pattern = r"(doi:\S+|https?://\S+|source URL recorded in artifact)"
    locator_matches = list(re.finditer(locator_pattern, tail))
    title = tail
    if locator_matches:
        locator = locator_matches[0].group(1).rstrip(".,;)")
        for match in reversed(locator_matches):
            title = f"{title[:match.start()]}{title[match.end():]}"
    title = re.sub(r"\s+", " ", title).rstrip(" .").strip()
    return title, locator


def _autopilot_citation_metadata_by_key(path_value: object) -> dict[str, dict[str, Any]]:
    path = Path(path_value) if isinstance(path_value, str | Path) else None
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    citations = payload.get("citations") if isinstance(payload, dict) else None
    if not isinstance(citations, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        key = citation.get("bibtex_key")
        if isinstance(key, str) and key:
            rows[key] = citation
    return rows


def _first_integer(text: str) -> int | None:
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            return int(digits)
    return int(digits) if digits else None


def _autopilot_inspiration_queries(candidate: ResearchCandidate, *, demo: str) -> tuple[str, ...]:
    """Seed broad inspiration search without making it publication evidence."""

    return (
        candidate.title,
        candidate.research_gap,
        f"{demo} open datasets and research tools",
    )


def _run_source_preflight_gate(
    *,
    clients: Mapping[str, LiteratureSearchClient],
    cycle_dir: Path,
    vault: Path,
    project_id: str,
    cycle_id: str,
) -> dict[str, Any]:
    """Write a no-network source health gate before costly cycle work."""

    output_path = cycle_dir / "source-preflight.json"
    markdown_path = cycle_dir / "source-preflight.md"
    checks = [_source_preflight_check(source, client) for source, client in clients.items()]
    blocking_statuses = {"cooling_down", "state_error", "state_locked"}
    blocked_sources = [
        str(check["source"])
        for check in checks
        if str(check["status"]) in blocking_statuses
        and str(check["source"]) not in OPTIONAL_LITERATURE_SOURCES
    ]
    optional_degraded_sources = [
        str(check["source"])
        for check in checks
        if str(check["status"]) in blocking_statuses
        and str(check["source"]) in OPTIONAL_LITERATURE_SOURCES
    ]
    blocked = bool(blocked_sources)
    report: dict[str, Any] = {
        "verdict": "blocked" if blocked else "pass",
        "blocked": blocked,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "blocked_sources": blocked_sources,
        "optional_degraded_sources": optional_degraded_sources,
        "output_path": output_path.as_posix(),
        "markdown_path": markdown_path.as_posix(),
        "issue_path": None,
    }
    if blocked:
        issue_path = _write_source_preflight_issue(
            report=report,
            vault=vault,
            project_id=project_id,
            cycle_id=cycle_id,
        )
        report["issue_path"] = issue_path.as_posix()

    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_source_preflight_markdown(report), encoding="utf-8")
    return report


def _source_preflight_check(source: str, client: LiteratureSearchClient) -> dict[str, object]:
    breaker = getattr(client, "circuit_breaker", None)
    if breaker is None:
        return {
            "source": source,
            "status": "ready",
            "remaining_seconds": 0.0,
            "state_path": None,
            "message": "No persisted rate-limit circuit is active for this source.",
        }
    raw_state_path = getattr(breaker, "state_path", None)
    state_path = _path_text(raw_state_path)
    lock_error = _source_state_lock_error(raw_state_path, breaker)
    if lock_error is not None:
        return {
            "source": source,
            "status": "state_locked",
            "remaining_seconds": 0.0,
            "state_path": state_path,
            "message": f"Persisted source cooldown state is locked: {lock_error}",
        }
    state_error = _source_state_file_error(raw_state_path)
    if state_error is not None:
        return {
            "source": source,
            "status": "state_error",
            "remaining_seconds": 0.0,
            "state_path": state_path,
            "message": f"Persisted source cooldown state is unreadable: {state_error}",
        }
    remaining_seconds = 0.0
    remaining = getattr(breaker, "remaining_seconds", None)
    if callable(remaining):
        try:
            remaining_seconds = max(0.0, float(remaining()))
        except SourceCircuitStateLockError as exc:
            return {
                "source": source,
                "status": "state_locked",
                "remaining_seconds": 0.0,
                "state_path": state_path,
                "message": f"Persisted source cooldown state is locked: {exc}",
            }
    status = "cooling_down" if remaining_seconds > 0 else "ready"
    return {
        "source": source,
        "status": status,
        "remaining_seconds": round(remaining_seconds, 1),
        "state_path": state_path,
        "message": (
            f"Source cooldown is still active for {remaining_seconds:.1f}s."
            if status == "cooling_down"
            else "Source cooldown gate is clear."
        ),
    }


def _write_source_preflight_issue(
    *,
    report: dict[str, Any],
    vault: Path,
    project_id: str,
    cycle_id: str,
) -> Path:
    blocked_sources = [str(source) for source in report.get("blocked_sources", [])]
    source_slug = _source_preflight_slug(blocked_sources)
    relative_path = Path("projects") / project_id / "issues" / f"source-preflight-{source_slug}.md"
    source_lines = [
        f"- `{check['source']}`: {check['message']}"
        for check in report["checks"]
        if str(check["status"]) in {"cooling_down", "state_error", "state_locked"}
    ]
    related_task_ids = ["82.1"]
    if any(str(check["status"]) == "state_error" for check in report["checks"]):
        related_task_ids.append("83.1")
    if any(str(check["status"]) == "state_locked" for check in report["checks"]):
        related_task_ids.append("85.1")
    body = "\n".join(
        [
            "# Source Preflight Blocker",
            "",
            "- Status: open",
            f"- Issue fingerprint: `source-preflight:{project_id}:{source_slug}`",
            f"- Cycle: `{cycle_id}`",
            f"- Blocked sources: `{', '.join(blocked_sources)}`",
            f"- Evidence JSON: `{report['output_path']}`",
            f"- Evidence Markdown: `{report['markdown_path']}`",
            "",
            "## Reason",
            "",
            "The cycle was stopped before literature refresh, experiment execution, live review, and paper build because at least one required online source has an active persisted rate-limit cooldown, a locked cooldown state file, or an unreadable cooldown state file.",
            "",
            "## Source Status",
            "",
            *(source_lines or ["- No blocked sources were listed."]),
            "",
            "## Next Action",
            "",
            "Wait for the cooldown or state lock to clear, fix or remove malformed cooldown state, configure an appropriate source API key if available, or reduce/schedule source usage before rerunning publication-level novelty checks.",
        ]
    )
    entry = KnowledgeEntry(
        entry_id=f"source_preflight_issue_{project_id}_{source_slug}",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=project_id,
        title=f"Source preflight blocked for {', '.join(blocked_sources)}",
        tags=["open", "source-preflight", "rate-limit", "evidence-gate"],
        keywords=["source-preflight", "rate-limit", *blocked_sources],
        source_refs=[str(report["output_path"]), str(report["markdown_path"])],
        related_task_ids=related_task_ids,
        related_run_ids=[cycle_id],
        body=body,
    )
    return MarkdownKnowledgeStore(vault).write_entry(relative_path, entry)


def _source_preflight_slug(sources: list[str]) -> str:
    if not sources:
        return "none"
    return "-".join(source.replace("_", "-") for source in sorted(sources))


def _source_state_file_error(path_value: object) -> str | None:
    if path_value is None:
        return None
    if not isinstance(path_value, str | Path):
        return "state path is not a filesystem path"
    path = Path(path_value)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return str(exc)
    if not isinstance(payload, dict):
        return "state file must contain a JSON object"
    for key, value in payload.items():
        if not isinstance(value, int | float):
            return f"state entry {key!r} must be a numeric epoch timestamp"
    return None


def _source_state_lock_error(path_value: object, breaker: object) -> str | None:
    if path_value is None or not isinstance(path_value, str | Path):
        return None
    path = Path(path_value)
    lock_path = path.with_name(f"{path.name}.lock")
    if not lock_path.exists():
        return None
    stale_after = float(getattr(breaker, "state_stale_lock_seconds", 300.0))
    if stale_after > 0:
        try:
            if time.time() - lock_path.stat().st_mtime > stale_after:
                return None
        except FileNotFoundError:
            return None
    return lock_path.as_posix()


def _render_source_preflight_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Source Preflight Gate",
        "",
        f"- Verdict: `{report['verdict']}`",
        f"- Blocked: `{report['blocked']}`",
        f"- Optional degraded sources: `{', '.join(report.get('optional_degraded_sources', [])) or 'none'}`",
        f"- Checked at: `{report['checked_at']}`",
        f"- Issue path: `{report.get('issue_path') or 'none'}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(
            f"- `{check['source']}`: `{check['status']}` "
            f"({check['remaining_seconds']}s remaining) - {check['message']}"
        )
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "A publication-level cycle cannot spend experiment, review, or paper-build work while a required online source is already in a persisted cooldown window, while its cooldown state is locked by another process, or while its cooldown state cannot be verified.",
            "Optional enhancement sources such as Semantic Scholar may be skipped or degraded without stopping the cycle when core free/public sources still run.",
            "",
        ]
    )
    return "\n".join(lines)


def _autopilot_literature_seed_queries(demo: str) -> tuple[str, ...]:
    if demo == "letter_variance_calibrated_prototypes":
        return (
            "UCI Letter Recognition variance calibrated prototype classifier",
            "Letter Recognition nearest centroid classifier",
            "diagonal Gaussian prototype classification letter recognition",
            "prototype classifier variance normalization character recognition",
        )
    if demo == "spambase_variance_calibrated_prototypes":
        return (
            "UCI Spambase variance calibrated prototype classifier",
            "Spambase nearest centroid spam classification",
            "diagonal Gaussian prototype classification spam filtering",
            "prototype classifier variance normalization email classification",
        )
    if demo == "skin_variance_calibrated_prototypes":
        return (
            "UCI Skin Segmentation variance calibrated prototype classifier",
            "Skin Segmentation nearest centroid RGB classifier",
            "diagonal Gaussian prototype classification skin detection",
            "Bayesian Gaussian skin color segmentation variance normalization",
        )
    if demo == "pendigits_variance_calibrated_prototypes":
        return (
            "UCI Pendigits variance calibrated prototype classifier",
            "Pen-Based Recognition of Handwritten Digits nearest centroid classifier",
            "diagonal Gaussian prototype classification variance shrinkage",
            "prototype classifier variance normalization handwritten digit recognition",
        )
    if demo == "pendigits_prototype_shrinkage":
        return (
            "UCI Pendigits prototype shrinkage classifier",
            "nearest centroid prototype shrinkage handwritten digit recognition",
            "class centroid shrinkage classification public benchmark",
            "prototype classifier regularization Pen-Based Recognition Digits",
        )
    if demo == "pendigits_centroid_baseline":
        return (
            "UCI Pendigits nearest centroid baseline",
            "Pen-Based Recognition of Handwritten Digits classification benchmark",
            "nearest centroid classifier handwritten digit recognition",
            "prototype based classification UCI Pendigits",
        )
    return (
        "automated research agents evidence graph reproducibility",
        "self evolving research agents validation gates",
        "research automation literature retrieval experiment validation",
        "knowledge base memory for autonomous scientific agents",
    )


def _autopilot_seed_document(documents: list[object], demo: str) -> object | None:
    weighted_terms = _autopilot_seed_terms(demo)
    if not weighted_terms:
        return documents[0]
    required_terms = _autopilot_required_seed_terms(demo)
    best_score = -1
    best_index = len(documents)
    best_document: object | None = None
    for index, document in enumerate(documents):
        text = _autopilot_document_text(document)
        if required_terms and not any(term in text for term in required_terms):
            continue
        score = sum(weight for term, weight in weighted_terms if term in text)
        if score < 2:
            continue
        if best_document is None or score > best_score or (
            score == best_score and index < best_index
        ):
            best_score = score
            best_index = index
            best_document = document
    return best_document


def _autopilot_required_seed_terms(demo: str) -> tuple[str, ...]:
    if demo in {
        "letter_variance_calibrated_prototypes",
        "spambase_variance_calibrated_prototypes",
        "skin_variance_calibrated_prototypes",
        "pendigits_variance_calibrated_prototypes",
        "pendigits_prototype_shrinkage",
        "pendigits_centroid_baseline",
    }:
        return (
            "prototype",
            "centroid",
            "nearest class mean",
            "nearest-class-mean",
            "mahalanobis",
            "metric learning",
        )
    return ()


def _autopilot_seed_terms(demo: str) -> tuple[tuple[str, int], ...]:
    if demo == "letter_variance_calibrated_prototypes":
        return (
            ("letter recognition", 3),
            ("character recognition", 3),
            ("letter", 2),
            ("prototype", 1),
            ("centroid", 1),
            ("classifier", 1),
            ("gaussian", 1),
            ("mahalanobis", 1),
        )
    if demo == "spambase_variance_calibrated_prototypes":
        return (
            ("spambase", 3),
            ("spam", 3),
            ("email", 2),
            ("prototype", 1),
            ("centroid", 1),
            ("classifier", 1),
            ("gaussian", 1),
        )
    if demo == "skin_variance_calibrated_prototypes":
        return (
            ("skin segmentation", 3),
            ("skin", 3),
            ("rgb", 2),
            ("segmentation", 2),
            ("bayesian", 1),
            ("gaussian", 1),
            ("classifier", 1),
        )
    if demo in {
        "pendigits_variance_calibrated_prototypes",
        "pendigits_prototype_shrinkage",
        "pendigits_centroid_baseline",
    }:
        return (
            ("pendigits", 3),
            ("pen-based", 3),
            ("handwritten digit", 3),
            ("digit recognition", 3),
            ("prototype", 1),
            ("centroid", 1),
            ("nearest centroid", 2),
            ("classifier", 1),
            ("mahalanobis", 1),
            ("metric learning", 1),
        )
    return ()


def _autopilot_document_text(document: object) -> str:
    parts = (
        getattr(document, "title", ""),
        getattr(document, "abstract", ""),
        getattr(document, "venue", ""),
        getattr(document, "source_uri", ""),
    )
    return " ".join(str(part) for part in parts if part).casefold()


def _autopilot_candidate_from_literature(
    literature_report: object,
    *,
    project_id: str,
    demo: str,
    now: datetime,
) -> ResearchCandidate:
    documents = list(getattr(literature_report, "documents", ()))
    if not documents:
        msg = "autopilot requires at least one retrieved literature document"
        raise RuntimeError(msg)
    seed = _autopilot_seed_document(documents, demo)
    seed_title = str(getattr(seed, "title", "no method-aligned seed selected")).strip()
    seed_uri = str(getattr(seed, "source_uri", "")).strip()
    seed_id = str(getattr(seed, "id", seed_uri)).strip()
    seed_refs = [value for value in (seed_id, seed_uri) if value]
    related_seed_ids = [seed_id] if seed_id else []
    if not seed_refs:
        seed_refs = [METHOD_ALIGNED_SEED_NOT_FOUND_REF]
    candidate_id = f"autopilot_{project_id}_{now.strftime('%Y%m%d%H%M%S')}"
    if demo == "letter_variance_calibrated_prototypes":
        return ResearchCandidate(
            id=candidate_id,
            title="Variance-calibrated prototype classifiers for UCI Letter Recognition",
            description=(
                "Evaluate whether diagonal per-class variance calibration improves a "
                "z-score nearest-prototype classifier on the UCI Letter Recognition split."
            ),
            research_gap=(
                "Letter Recognition gives a second real public benchmark for the same "
                "prototype-family mechanism, but publication claims still require checking "
                "Gaussian, Mahalanobis, nearest-centroid, and character-recognition prior work."
            ),
            novelty_score=0.45,
            feasibility_score=0.85,
            impact_score=0.55,
            evidence_refs=seed_refs,
            related_document_ids=related_seed_ids,
            status=CandidateStatus.READY_FOR_REVIEW,
            validation_status=ValidationStatus.PENDING,
            metadata={
                "generated_by": "airesearcher autopilot",
                "project_id": project_id,
                "demo": demo,
                "seed_document_title": seed_title,
                "seed_source_uri": seed_uri,
                "method": "diagonal variance-calibrated prototypes with variance shrinkage",
                "dataset": "UCI Letter Recognition",
                "benchmark": "UCI Letter Recognition",
                "baseline": "z-score nearest centroid classifier",
                "limitation": (
                    "single public character-recognition benchmark; adjacent Gaussian, "
                    "Mahalanobis, and prototype classifiers may already cover the mechanism"
                ),
            },
        )
    if demo == "spambase_variance_calibrated_prototypes":
        return ResearchCandidate(
            id=candidate_id,
            title="Variance-calibrated prototype classifiers for UCI Spambase",
            description=(
                "Evaluate whether diagonal per-class variance calibration improves a "
                "z-score nearest-prototype spam classifier on a deterministic UCI Spambase split."
            ),
            research_gap=(
                "Spambase adds a non-image public benchmark for the same interpretable "
                "prototype mechanism, but the expected effect is small and must be audited "
                "against spam-filtering and Gaussian classifier prior work."
            ),
            novelty_score=0.4,
            feasibility_score=0.85,
            impact_score=0.5,
            evidence_refs=seed_refs,
            related_document_ids=related_seed_ids,
            status=CandidateStatus.READY_FOR_REVIEW,
            validation_status=ValidationStatus.PENDING,
            metadata={
                "generated_by": "airesearcher autopilot",
                "project_id": project_id,
                "demo": demo,
                "seed_document_title": seed_title,
                "seed_source_uri": seed_uri,
                "method": "diagonal variance-calibrated prototypes with variance shrinkage",
                "dataset": "UCI Spambase",
                "benchmark": "UCI Spambase",
                "baseline": "z-score nearest centroid classifier",
                "limitation": (
                    "single public email benchmark and small effect size; claims require "
                    "statistical caution plus spam-filtering related-work checks"
                ),
            },
        )
    if demo == "skin_variance_calibrated_prototypes":
        return ResearchCandidate(
            id=candidate_id,
            title="Variance-calibrated prototype classifiers for UCI Skin Segmentation",
            description=(
                "Evaluate whether diagonal per-class RGB variance calibration improves a "
                "z-score nearest-prototype skin/non-skin classifier on the UCI Skin "
                "Segmentation benchmark."
            ),
            research_gap=(
                "Skin Segmentation adds a large real pixel-level benchmark for the same "
                "interpretable prototype mechanism, but publication claims require checking "
                "classic skin-color, Bayesian, Gaussian, and illumination-robust segmentation "
                "prior work."
            ),
            novelty_score=0.4,
            feasibility_score=0.9,
            impact_score=0.5,
            evidence_refs=seed_refs,
            related_document_ids=related_seed_ids,
            status=CandidateStatus.READY_FOR_REVIEW,
            validation_status=ValidationStatus.PENDING,
            metadata={
                "generated_by": "airesearcher autopilot",
                "project_id": project_id,
                "demo": demo,
                "seed_document_title": seed_title,
                "seed_source_uri": seed_uri,
                "method": "diagonal variance-calibrated prototypes with variance shrinkage",
                "dataset": "UCI Skin Segmentation",
                "benchmark": "UCI Skin Segmentation",
                "baseline": "z-score nearest centroid classifier over RGB color features",
                "limitation": (
                    "single public color segmentation benchmark; adjacent Bayesian, "
                    "Gaussian, skin-color, and illumination-robust segmentation methods "
                    "may already cover the mechanism"
                ),
            },
        )
    if demo == "pendigits_variance_calibrated_prototypes":
        return ResearchCandidate(
            id=candidate_id,
            title="Variance-calibrated prototype classifiers for UCI Pendigits",
            description=(
                "Evaluate whether diagonal per-class variance calibration improves a "
                "nearest-prototype classifier on the official UCI Pendigits train/test split."
            ),
            research_gap=(
                "Nearest-centroid baselines are reproducible and interpretable, but a "
                "publication claim requires checking whether variance-calibrated prototype "
                "distance has already been covered by Gaussian, Mahalanobis, or metric-learning "
                "classifiers on handwritten digit benchmarks."
            ),
            novelty_score=0.45,
            feasibility_score=0.85,
            impact_score=0.55,
            evidence_refs=seed_refs,
            related_document_ids=related_seed_ids,
            status=CandidateStatus.READY_FOR_REVIEW,
            validation_status=ValidationStatus.PENDING,
            metadata={
                "generated_by": "airesearcher autopilot",
                "project_id": project_id,
                "demo": demo,
                "seed_document_title": seed_title,
                "seed_source_uri": seed_uri,
                "method": "diagonal variance-calibrated prototypes with variance shrinkage",
                "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
                "benchmark": "UCI Pendigits",
                "baseline": "nearest centroid classifier and z-score centroid ablation",
                "limitation": (
                    "single public benchmark; adjacent Gaussian, Mahalanobis, and "
                    "distance-metric classifiers may already cover the mechanism"
                ),
            },
        )
    if demo == "pendigits_prototype_shrinkage":
        return ResearchCandidate(
            id=candidate_id,
            title="Prototype-shrinkage classifiers for UCI Pendigits",
            description=(
                "Evaluate class-prototype shrinkage against a nearest-centroid baseline on "
                "the official UCI Pendigits split."
            ),
            research_gap=(
                "Prototype shrinkage is easy to implement and audit, but negative or neutral "
                "deltas must be preserved as failed method evidence rather than rewritten as "
                "innovation."
            ),
            novelty_score=0.35,
            feasibility_score=0.85,
            impact_score=0.45,
            evidence_refs=seed_refs,
            related_document_ids=related_seed_ids,
            status=CandidateStatus.READY_FOR_REVIEW,
            validation_status=ValidationStatus.PENDING,
            metadata={
                "generated_by": "airesearcher autopilot",
                "project_id": project_id,
                "demo": demo,
                "seed_document_title": seed_title,
                "seed_source_uri": seed_uri,
                "method": "class prototype shrinkage toward the global feature mean",
                "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
                "benchmark": "UCI Pendigits",
                "baseline": "nearest centroid classifier",
                "limitation": "candidate underperformed in the first real run",
            },
        )
    if demo == "pendigits_centroid_baseline":
        return ResearchCandidate(
            id=candidate_id,
            title="Nearest-centroid reproducibility baseline for UCI Pendigits",
            description=(
                "Use the official UCI Pendigits split to test whether the system can produce "
                "real data, metrics, validation, and reproducibility evidence for a baseline."
            ),
            research_gap=(
                "This is a reproducibility and evidence-pipeline baseline, not a method "
                "innovation claim."
            ),
            novelty_score=0.2,
            feasibility_score=0.9,
            impact_score=0.35,
            evidence_refs=seed_refs,
            related_document_ids=related_seed_ids,
            status=CandidateStatus.READY_FOR_REVIEW,
            validation_status=ValidationStatus.PENDING,
            metadata={
                "generated_by": "airesearcher autopilot",
                "project_id": project_id,
                "demo": demo,
                "seed_document_title": seed_title,
                "seed_source_uri": seed_uri,
                "method": "nearest centroid classifier",
                "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
                "benchmark": "UCI Pendigits",
                "baseline_only": "true",
                "limitation": "baseline-only reproducibility run",
            },
        )
    return ResearchCandidate(
        id=candidate_id,
        title=f"Evidence-bound self-evolving research loop from {seed_title[:80]}",
        description=(
            "Autopilot-generated candidate for improving evidence-bound automated "
            "research loops by combining live literature discovery, local validation, "
            "Obsidian memory, and review-driven follow-up tasks."
        ),
        research_gap=(
            "Automated research agents often jump from retrieval to writing without a "
            "durable evidence memory, validation-gated self-loop, or auditable skill "
            "evolution path."
        ),
        novelty_score=0.55,
        feasibility_score=0.75,
        impact_score=0.65,
        evidence_refs=seed_refs,
        related_document_ids=related_seed_ids,
        status=CandidateStatus.READY_FOR_REVIEW,
        validation_status=ValidationStatus.PENDING,
        metadata={
            "generated_by": "airesearcher autopilot",
            "project_id": project_id,
            "demo": demo,
            "seed_document_title": seed_title,
            "seed_source_uri": seed_uri,
            "method": "evidence-bound autonomous research loop",
            "dataset": "local run records and source-backed literature metadata",
            "baseline": "manual prompt-only research-agent operation",
            "limitation": "system-level candidate must be validated across multiple real research cycles",
        },
    )


def _run_autopilot_review(
    *,
    enabled: bool,
    config_path: Path,
    env_path: Path,
    vault: Path,
    project_id: str,
    source_task_id: str,
    cycle_dir: Path,
    report_path: Path,
    evidence_paths: list[Path | str],
    max_tokens: int | None,
    min_quality_score: float,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "skipped"}
    try:
        result = run_llm_evidence_review(
            subject_path=report_path,
            evidence_paths=evidence_paths,
            config_path=config_path,
            env_path=env_path,
            max_tokens=max_tokens,
        )
    except LLMClientError as exc:
        return {"status": "failed", "error": str(exc)}

    review_output = cycle_dir / "llm-review.json"
    review_output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    review_info: dict[str, Any] = {
        "status": "passed" if result.quality.score >= min_quality_score else "below_threshold",
        "output_path": review_output.as_posix(),
        "provider": result.provider,
        "model_name": result.model_name,
        "quality_score": result.quality.score,
        "verdict": (result.quality.parsed_output or {}).get("verdict"),
    }
    if result.quality.score < min_quality_score:
        return review_info

    review_note = write_llm_review_note(
        result=result,
        vault_root=vault,
        project_id=project_id,
        source_task_id=source_task_id,
    )
    issue_notes = write_llm_review_issue_notes(
        result=result,
        vault_root=vault,
        project_id=project_id,
        source_task_id=source_task_id,
        review_note_path=review_note,
    )
    review_info["vault_review"] = review_note.as_posix()
    review_info["vault_issues"] = [path.as_posix() for path in issue_notes]
    return review_info


def _run_cycle_reproduction_check(
    *,
    cycle_dir: Path,
    demo: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    check_dir = cycle_dir / "reproduction-check"
    reproduction_output_dir = check_dir / "rerun"
    check_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "autoresearch.cli.main",
        "run-demo",
        "--demo",
        demo,
        "--output-dir",
        str(reproduction_output_dir),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    started_at = datetime.now(timezone.utc)
    timeout = max(timeout_seconds + 60, 60)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            **windows_no_window_kwargs(),
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        error = None
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        error = f"reproduction command timed out after {timeout} seconds"

    completed_at = datetime.now(timezone.utc)
    run_records = sorted(reproduction_output_dir.rglob("run-record.json"))
    validation_reports = sorted(reproduction_output_dir.rglob("validation-report.json"))
    passed = exit_code == 0 and bool(run_records) and bool(validation_reports)
    recorded_command = ["python", *command[1:]]
    result: dict[str, Any] = {
        "status": "passed" if passed else "failed",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "command": recorded_command,
        "timeout_seconds": timeout,
        "exit_code": exit_code,
        "output_dir": _relative_path_text(reproduction_output_dir),
        "run_record_paths": [_relative_path_text(path) for path in run_records],
        "validation_json_paths": [_relative_path_text(path) for path in validation_reports],
        "stdout_tail": _sanitize_output_paths(stdout[-4000:]),
        "stderr_tail": _sanitize_output_paths(stderr[-4000:]),
        "error": error,
    }
    json_path = check_dir / "reproduction-check.json"
    markdown_path = check_dir / "reproduction-check.md"
    result["json_path"] = _relative_path_text(json_path)
    result["markdown_path"] = _relative_path_text(markdown_path)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_reproduction_check_markdown(result), encoding="utf-8")
    return result


def _render_reproduction_check_markdown(result: dict[str, Any]) -> str:
    command = " ".join(str(part) for part in result["command"])
    return "\n".join(
        [
            "# Cycle Reproduction Check",
            "",
            f"- Status: `{result['status']}`",
            f"- Exit code: `{result['exit_code']}`",
            f"- Command: `{command}`",
            f"- Output directory: `{result['output_dir']}`",
            f"- Run records: `{len(result['run_record_paths'])}`",
            f"- Validation reports: `{len(result['validation_json_paths'])}`",
            f"- JSON: `{result['json_path']}`",
            "",
            "## Policy",
            "",
            "A cycle is not release-ready unless its experiment can be rerun from a command-line entry point and produces a fresh run record plus validation report.",
            "",
        ]
    )


def _issue_followup_records(vault: Path, project_id: str) -> list[dict[str, object]]:
    tasks = queued_issue_followups_from_vault(
        vault_root=vault,
        project_id=project_id,
        queued_at=datetime.now(timezone.utc),
    )
    return [
        {
            "task_id": task.task_id,
            "name": task.name,
            "queued_at": task.next_run_at.isoformat(),
            "status": "open",
            "metadata": task.action(),
        }
        for task in tasks
    ]


def _serialise_fetches(fetches: Iterable[object]) -> list[dict[str, object]]:
    return [
        {
            "source": getattr(fetch, "source", "unknown"),
            "query": getattr(fetch, "query", "unknown"),
            "paper_count": getattr(fetch, "paper_count", 0),
            "cache_hit": getattr(fetch, "cache_hit", False),
            "rate_limit_seconds": getattr(fetch, "rate_limit_seconds", 0.0),
            "error": getattr(fetch, "error", None),
        }
        for fetch in fetches
    ]


def _serialise_inspiration_fetches(fetches: Iterable[object]) -> list[dict[str, object]]:
    return [
        {
            "source": getattr(fetch, "source", "unknown"),
            "source_type": getattr(fetch, "source_type", "unknown"),
            "query": getattr(fetch, "query", "unknown"),
            "result_count": getattr(fetch, "result_count", 0),
            "rate_limit_seconds": getattr(fetch, "rate_limit_seconds", 0.0),
            "error": getattr(fetch, "error", None),
        }
        for fetch in fetches
    ]


def _path_text(path: object) -> str | None:
    if path is None:
        return None
    if isinstance(path, Path):
        return _relative_path_text(path)
    if isinstance(path, str):
        return _relative_path_text(path)
    return str(path)


def _runtime_heartbeat_stage_payload(report: RuntimeHeartbeatReport) -> list[dict[str, object]]:
    return [
        {
            "run_id": stage.run_id,
            "stage": stage.stage,
            "status": stage.status.value,
            "action": stage.action.value,
            "latest_at": stage.latest_at.isoformat(),
            "age_seconds": stage.age_seconds,
            "repeated_progress_count": stage.repeated_progress_count,
            "latest_progress_sha256": stage.latest_progress_sha256,
            "latest_message": stage.latest_message,
            "artifact_refs": list(stage.artifact_refs),
            "reason": stage.reason,
        }
        for stage in report.stages
    ]


def _cycle_runtime_heartbeat_summary(
    *,
    heartbeat_state: Path,
    cycle_id: str,
    report_path: Path,
) -> dict[str, object]:
    report = evaluate_runtime_heartbeats(
        state_path=heartbeat_state,
        run_id=cycle_id,
    )
    write_runtime_heartbeat_report(report, report_path)
    return {
        "state_path": heartbeat_state.as_posix(),
        "report_path": report_path.as_posix(),
        "passed": report.passed,
        "event_count": report.event_count,
        "stage_count": report.stage_count,
        "stale_count": report.stale_count,
        "stalled_count": report.stalled_count,
        "stages": _runtime_heartbeat_stage_payload(report),
        "evidence_policy": report.evidence_policy,
    }


def _write_cycle_runtime_heartbeat(
    *,
    heartbeat_state: Path,
    cycle_id: str,
    stage: str,
    progress: str,
    report_path: Path,
    message: str | None = None,
    artifact_refs: Iterable[object] = (),
) -> dict[str, object]:
    clean_refs = tuple(
        ref_text
        for ref in artifact_refs
        if (ref_text := _path_text(ref)) is not None
    )
    write_runtime_heartbeat(
        state_path=heartbeat_state,
        run_id=cycle_id,
        stage=stage,
        progress=progress,
        message=message,
        artifact_refs=clean_refs,
    )
    return _cycle_runtime_heartbeat_summary(
        heartbeat_state=heartbeat_state,
        cycle_id=cycle_id,
        report_path=report_path,
    )


def _validate_optional_max_tokens(value: int | None, *, minimum: int) -> int | None:
    if value is None:
        return None
    if value < minimum:
        msg = f"--max-tokens must be at least {minimum} when provided"
        raise typer.BadParameter(msg)
    return value


def _resolve_runtime_sessions_state(
    sessions_state: Path | None,
    *related_paths: Path,
) -> Path:
    if sessions_state is not None:
        return sessions_state
    for path in related_paths:
        parent = Path(path).parent
        if parent != Path(".airesearcher") and parent != Path("."):
            return parent / "agent-sessions.json"
    return DEFAULT_AGENT_SESSIONS_PATH


def _resolve_runtime_heartbeat_state(
    heartbeat_state: Path | None,
    *related_paths: Path,
) -> Path:
    if heartbeat_state is not None:
        return heartbeat_state
    for path in related_paths:
        parent = Path(path).parent
        if parent != Path(".airesearcher") and parent != Path("."):
            return parent / "runtime-heartbeats.json"
    return DEFAULT_RUNTIME_HEARTBEATS_PATH


def _runtime_claimed_paths(
    *,
    vault: Path,
    cache: Path,
    output_dir: Path,
    deliverables_dir: Path,
    state: Path,
    extra_paths: tuple[Path, ...] = (),
) -> tuple[str, ...]:
    paths = (vault, cache, output_dir, deliverables_dir, state, *extra_paths)
    return tuple(str(path) for path in paths)


def _claim_runtime_session(
    *,
    enabled: bool,
    sessions_state: Path,
    agent_name: str,
    task_id: str,
    claimed_paths: tuple[str, ...],
) -> AgentSession | None:
    if not enabled:
        typer.echo("[OK] session_claim: disabled")
        return None
    try:
        result = claim_agent_session(
            state_path=sessions_state,
            agent_name=agent_name,
            task_id=task_id,
            claimed_paths=claimed_paths,
        )
    except AgentSessionError as exc:
        typer.echo(f"[FAIL] session claim failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    status = "allowed" if result.allowed else "blocked"
    typer.echo(f"[OK] session_claim: {status}")
    typer.echo(f"[OK] sessions_state: {sessions_state}")
    if result.session is not None:
        typer.echo(f"[OK] session_id: {result.session.session_id}")
        typer.echo(f"[OK] claimed_paths: {', '.join(result.session.claimed_paths)}")
        return result.session
    for conflict in result.conflicts:
        typer.echo(
            f"[CONFLICT] session_id={conflict.session_id} task_id={conflict.task_id} "
            f"agent={conflict.agent_name} claimed={conflict.claimed_path} "
            f"existing={conflict.conflicting_path}"
        )
    typer.echo("[FAIL] runtime session claim overlaps an active agent session", err=True)
    raise typer.Exit(code=1)


def _release_runtime_session(sessions_state: Path, session: AgentSession | None) -> None:
    if session is None:
        return
    try:
        released = release_agent_session(sessions_state, session.session_id)
    except AgentSessionError as exc:
        typer.echo(f"[WARN] session_release_failed: {exc}", err=True)
        return
    typer.echo(f"[OK] session_release: {released.session_id}")


def _export_cycle_deliverables(
    *,
    summary: dict[str, Any],
    summary_path: Path,
    output_root: Path,
    project_id: str,
) -> dict[str, Any]:
    cycle_id = str(summary["cycle_id"])
    project_slug = _safe_path_segment(project_id)
    target_dir = output_root / project_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}

    def copy_artifact(label: str, source_value: object, filename: str) -> None:
        source = _existing_path_from_value(source_value)
        if source is None:
            return
        target = target_dir / filename
        shutil.copy2(source, target)
        copied[label] = _relative_path_text(target)

    paper_build = summary.get("paper_build")
    if not isinstance(paper_build, dict):
        paper_build = {}
    research_plan = summary.get("research_plan")
    if not isinstance(research_plan, dict):
        research_plan = {}
    paper_manuscript = summary.get("paper_manuscript")
    if not isinstance(paper_manuscript, dict):
        paper_manuscript = {}
    publication_audit = summary.get("publication_audit")
    if not isinstance(publication_audit, dict):
        publication_audit = {}
    evidence_gate = summary.get("evidence_gate")
    if not isinstance(evidence_gate, dict):
        evidence_gate = {}
    related_work = summary.get("related_work_inspection")
    if not isinstance(related_work, dict):
        related_work = {}
    review = summary.get("review")
    if not isinstance(review, dict):
        review = {}

    copy_artifact("paper_pdf", paper_build.get("pdf_path"), f"{project_slug}-{cycle_id}.pdf")
    copy_artifact(
        "paper_tex",
        paper_build.get("tex_path"),
        f"{project_slug}-{cycle_id}.tex",
    )
    copy_artifact(
        "paper_build_json",
        paper_build.get("json_path"),
        f"{project_slug}-{cycle_id}-paper-build.json",
    )
    copy_artifact(
        "paper_build_markdown",
        paper_build.get("markdown_path"),
        f"{project_slug}-{cycle_id}-paper-build.md",
    )
    copy_artifact(
        "manuscript_markdown",
        paper_manuscript.get("markdown_path"),
        f"{project_slug}-{cycle_id}-manuscript.md",
    )
    copy_artifact(
        "publication_audit_json",
        publication_audit.get("output_path"),
        f"{project_slug}-{cycle_id}-publication-audit.json",
    )
    copy_artifact(
        "evidence_gate_json",
        evidence_gate.get("output_path"),
        f"{project_slug}-{cycle_id}-evidence-gate.json",
    )
    copy_artifact(
        "related_work_json",
        related_work.get("json_path"),
        f"{project_slug}-{cycle_id}-related-work.json",
    )
    copy_artifact(
        "related_work_markdown",
        related_work.get("markdown_path"),
        f"{project_slug}-{cycle_id}-related-work.md",
    )
    copy_artifact(
        "llm_review_json",
        review.get("output_path"),
        f"{project_slug}-{cycle_id}-llm-review.json",
    )
    copy_artifact(
        "research_plan_pdf",
        research_plan.get("pdf_path"),
        f"{project_slug}-{cycle_id}-research-plan.pdf",
    )
    copy_artifact(
        "research_plan_tex",
        research_plan.get("tex_path"),
        f"{project_slug}-{cycle_id}-research-plan.tex",
    )
    copy_artifact(
        "research_plan_json",
        research_plan.get("json_path"),
        f"{project_slug}-{cycle_id}-research-plan.json",
    )
    copy_artifact(
        "research_plan_markdown",
        research_plan.get("markdown_path"),
        f"{project_slug}-{cycle_id}-research-plan.md",
    )
    copy_artifact("cycle_summary_json", summary_path, f"{project_slug}-{cycle_id}-summary.json")

    manifest_path = target_dir / f"{project_slug}-{cycle_id}-manifest.json"
    markdown_path = target_dir / f"{project_slug}-{cycle_id}-manifest.md"
    manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "cycle_id": cycle_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": _relative_path_text(target_dir),
        "source_cycle_summary": _relative_path_text(summary_path),
        "paths": copied,
        "path_policy": "Paths are written relative to the current project root when possible.",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_deliverables_markdown(manifest), encoding="utf-8")
    return {
        "output_dir": _relative_path_text(target_dir),
        "manifest_path": _relative_path_text(manifest_path),
        "markdown_path": _relative_path_text(markdown_path),
        "pdf_path": copied.get("paper_pdf"),
        "paths": copied,
    }


def _existing_path_from_value(value: object) -> Path | None:
    if not isinstance(value, str | Path):
        return None
    path = Path(value)
    candidates = (path, Path.cwd() / path) if not path.is_absolute() else (path,)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _relative_path_text(path: Path | str) -> str:
    resolved = Path(path).resolve()
    try:
        return Path(os.path.relpath(resolved, start=Path.cwd().resolve())).as_posix()
    except ValueError:
        return resolved.as_posix()


def _sanitize_output_paths(text: str) -> str:
    if not text:
        return text
    root = str(Path.cwd().resolve())
    normalized_root = Path.cwd().resolve().as_posix()
    return (
        text.replace(root + "\\", "")
        .replace(root + "/", "")
        .replace(normalized_root + "/", "")
    )


def _safe_path_segment(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug or "ai-researcher"


def _render_deliverables_markdown(manifest: dict[str, Any]) -> str:
    paths = manifest.get("paths")
    path_lines: list[str] = []
    if isinstance(paths, dict):
        path_lines = [
            f"- {label}: `{path}`"
            for label, path in sorted(paths.items())
        ]
    return "\n".join(
        [
            "# AI-Researcher Deliverables",
            "",
            f"- Project: `{manifest['project_id']}`",
            f"- Cycle: `{manifest['cycle_id']}`",
            f"- Generated at: `{manifest['generated_at']}`",
            f"- Source cycle summary: `{manifest['source_cycle_summary']}`",
            "",
            "## Files",
            "",
            *(path_lines or ["- No copyable artifacts were present."]),
            "",
            "## Policy",
            "",
            "This bundle is a convenience publication surface. Release or paper claims still depend on the attached publication audit, evidence gate, and source-backed review artifacts.",
            "",
        ]
    )


def _serve_command_text(
    *,
    project_id: str,
    demo: str,
    permission_mode: RuntimePermissionMode,
    review: bool,
    paper_template_id: str,
    push_inspiration: bool,
) -> str:
    review_flag = "--review" if review else "--no-review"
    push_flag = "--push-inspiration" if push_inspiration else "--no-push-inspiration"
    return (
        "airesearcher serve "
        f"--permission-mode {permission_mode.value} "
        f"--project-id {project_id} "
        f"--demo {demo} "
        f"--paper-template-id {paper_template_id} "
        f"{review_flag} "
        f"{push_flag}"
    )

def _echo_setup_next_steps(
    *,
    permission_mode: RuntimePermissionMode,
    deliverables_dir: Path,
    approvals_state: Path = DEFAULT_RUNTIME_APPROVALS_PATH,
) -> None:
    typer.echo("[NEXT] 1. Check install: npm run doctor")
    typer.echo(
        "[NEXT] 2. Start runtime: "
        f"airesearcher serve --permission-mode {permission_mode.value}"
    )
    typer.echo(
        "[NEXT] 3. When approval is requested, run: "
        f"airesearcher runtime approve latest --state {approvals_state}"
    )
    typer.echo("[NEXT] Optional dashboard: airesearcher monitor --watch")
    typer.echo(f"[OK] deliverables: {deliverables_dir.as_posix()}/<project-id>/")


def _echo_runtime_approval_waiting(
    *,
    request_id: str,
    state: Path,
    watch: bool,
    interval_seconds: int,
    action_id: str | None = None,
) -> None:
    typer.echo("[WAITING] runtime approval required")
    typer.echo(f"[WAITING] request_id: {request_id}")
    if action_id is not None:
        typer.echo(f"[WAITING] action_id: {action_id}")
    typer.echo(f"[WAITING] state: {state}")
    typer.echo(f"[NEXT] approve latest: airesearcher runtime approve latest --state {state}")
    typer.echo(f"[NEXT] approve exact: airesearcher runtime approve {request_id} --state {state}")
    if watch:
        typer.echo(f"[WAITING] will check again in {interval_seconds}s")
    else:
        typer.echo("[WAITING] run serve again after approval")


def _serve_cycle_action_id(*, project_id: str, demo: str, cycle_number: int) -> str:
    """Return the approval action ID for one serve cycle attempt."""

    return f"serve:autopilot-cycle:{project_id}:{demo}:cycle-{cycle_number}"


def _serve_network_approval_metadata(
    decision: RuntimeApprovalDecision,
) -> dict[str, Any]:
    return network_approval_metadata_from_decision(
        decision,
        scope=(
            "serve cycle online literature retrieval, source-backed similarity "
            "checking, inspiration refresh, and approved public benchmark data "
            "fallback downloads"
        ),
        approved_network_domains=SERVE_NETWORK_APPROVED_DOMAINS,
        network_source_urls=SERVE_NETWORK_SOURCE_URLS,
    )


def _can_import(module_name: str) -> bool:
    try:
        import_module(module_name)
    except Exception:
        return False
    return True


def _load_or_default_config(config_path: Path) -> SystemConfig:
    if not config_path.exists():
        return SystemConfig()
    parser = ConfigParser()
    config = parser.parse_file(config_path)
    if not isinstance(config, SystemConfig):
        msg = f"{config_path} did not parse as SystemConfig"
        raise typer.BadParameter(msg)
    return config


def _load_candidate(candidate_file: Path) -> ResearchCandidate:
    try:
        text = candidate_file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        msg = f"Could not read candidate file {candidate_file}: {exc}"
        raise typer.BadParameter(msg) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"Invalid candidate JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        raise typer.BadParameter(msg) from exc
    try:
        return ResearchCandidate.model_validate(data)
    except Exception as exc:
        msg = f"Invalid ResearchCandidate payload: {exc}"
        raise typer.BadParameter(msg) from exc


def _read_optional_artifact_text(
    payload: object,
    key: str,
    *,
    base_dir: Path | None = None,
) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    path = Path(value)
    candidate_paths = [path]
    if base_dir is not None and not path.is_absolute():
        candidate_paths.append(base_dir / path)
    for candidate_path in candidate_paths:
        if candidate_path.is_file():
            try:
                return candidate_path.read_text(encoding="utf-8-sig")
            except OSError:
                return None
    return None


def _echo_fetches(fetches: Iterable[object]) -> None:
    for fetch in fetches:
        source = getattr(fetch, "source", "unknown")
        query = getattr(fetch, "query", "unknown")
        paper_count = getattr(fetch, "paper_count", 0)
        cache_hit = getattr(fetch, "cache_hit", False)
        error = getattr(fetch, "error", None)
        cache_status = "hit" if cache_hit else "miss"
        error_text = f", error={error}" if error else ""
        typer.echo(
            f"[FETCH] source={source} papers={paper_count} cache={cache_status} "
            f"query={query}{error_text}"
        )


def _echo_inspiration_pushes(summary: Mapping[str, object]) -> None:
    inspiration = summary.get("inspiration")
    if not isinstance(inspiration, Mapping):
        return
    pushes = inspiration.get("pushes")
    if not isinstance(pushes, list):
        return
    for push in pushes:
        if not isinstance(push, Mapping):
            continue
        typer.echo(
            "[PUSH] inspiration "
            f"channel={push.get('channel', 'unknown')} "
            f"status={push.get('status', 'unknown')} "
            f"detail={push.get('detail', '')}"
        )


def _echo_loop_plan(
    *,
    command_name: str,
    watch: bool,
    cycles: int,
    interval_seconds: int,
    push_inspiration: bool,
    approval_poll_seconds: int | None = None,
) -> None:
    if not watch:
        mode = "single-cycle"
        cycle_detail = "1"
    elif cycles == 0:
        mode = "watch-forever"
        cycle_detail = "unbounded"
    else:
        mode = "watch-limited"
        cycle_detail = str(cycles)
    approval_text = (
        f", approval_poll_seconds={approval_poll_seconds}"
        if approval_poll_seconds is not None
        else ""
    )
    typer.echo(
        "[OK] loop_plan: "
        f"command={command_name}, mode={mode}, cycles={cycle_detail}, "
        f"interval_seconds={interval_seconds}, "
        f"push_inspiration={str(push_inspiration).lower()}"
        f"{approval_text}"
    )


def _echo_research_plan_status(summary: Mapping[str, object]) -> None:
    research_plan = summary.get("research_plan")
    if not isinstance(research_plan, Mapping):
        return
    plan_audit = research_plan.get("audit")
    verdict = plan_audit.get("verdict") if isinstance(plan_audit, Mapping) else "unknown"
    prefix = "[OK]" if verdict == "passed" else "[BLOCKED]"
    typer.echo(f"{prefix} research_plan: {verdict}")


def _echo_loop_campaign_status(summary: Mapping[str, object]) -> None:
    loop_campaign = summary.get("loop_campaign")
    if not isinstance(loop_campaign, Mapping):
        return
    quality_gate = loop_campaign.get("quality_gate")
    metrics = loop_campaign.get("metrics")
    passed = quality_gate.get("passed") if isinstance(quality_gate, Mapping) else False
    prefix = "[OK]" if passed is True else "[BLOCKED]"
    metric_text = ""
    if isinstance(metrics, Mapping):
        metric_text = (
            f"; metadata={metrics.get('metadata_completeness', 'unknown')}; "
            f"evidence={metrics.get('evidence_coverage', 'unknown')}; "
            f"repro_delta={metrics.get('reproduction_delta', 'unknown')}"
        )
    typer.echo(f"{prefix} loop_campaign: {str(passed).lower()}{metric_text}")


def _echo_runtime_heartbeat_status(summary: Mapping[str, object]) -> None:
    heartbeat = summary.get("runtime_heartbeat")
    if not isinstance(heartbeat, Mapping):
        return
    passed = heartbeat.get("passed")
    prefix = "[OK]" if passed is True else "[BLOCKED]"
    typer.echo(
        f"{prefix} runtime_heartbeat: {str(passed).lower()}; "
        f"stages={heartbeat.get('stage_count', 'unknown')}; "
        f"stale={heartbeat.get('stale_count', 'unknown')}; "
        f"stalled={heartbeat.get('stalled_count', 'unknown')}"
    )


def _echo_agent_profiles_status(summary: Mapping[str, object]) -> None:
    agent_profiles = summary.get("agent_profiles")
    if not isinstance(agent_profiles, Mapping):
        return
    count = int(agent_profiles.get("count", 0) or 0)
    if count <= 0:
        return
    profile_ids = [
        str(profile.get("agent_id", "unknown"))
        for profile in _mapping_list(agent_profiles.get("profiles"))
    ]
    assignments = agent_profiles.get("stage_assignments")
    stage_count = 0
    if isinstance(assignments, Mapping):
        stage_count = len(_mapping_list(assignments.get("stages")))
    readiness_text = ""
    readiness = agent_profiles.get("readiness")
    if isinstance(readiness, Mapping):
        failed = int(readiness.get("failed_check_count", 0) or 0)
        readiness_text = "; readiness=pass" if failed == 0 else f"; readiness=fail:{failed}"
    typer.echo(
        f"[OK] agent_profiles: {count}; agents={', '.join(profile_ids)}; "
        f"assigned_stages={stage_count}{readiness_text}"
    )


def _review_status_display(review: object) -> tuple[str, str]:
    if not isinstance(review, Mapping):
        return "[BLOCKED]", "missing"

    status = str(review.get("status", "unknown"))
    parts = [status]
    verdict = review.get("verdict")
    if isinstance(verdict, str) and verdict:
        parts.append(f"verdict={verdict}")
    score = review.get("quality_score")
    if isinstance(score, int | float) and not isinstance(score, bool):
        parts.append(f"quality={score:.3f}")

    failed_statuses = {"failed", "below_threshold"}
    pass_verdicts = {"pass", "passed"}
    review_blocks_release = (
        status in failed_statuses
        or (status == "passed" and isinstance(verdict, str) and verdict not in pass_verdicts)
    )
    prefix = "[BLOCKED]" if review_blocks_release else "[OK]"
    return prefix, "; ".join(parts)


def _collect_setup_wizard_values(
    *,
    config_path: Path,
    env_path: Path,
    provider: str | None,
    base_url: str | None,
    model_name: str | None,
    api_key: str | None,
    wechat: bool | None,
    wechat_webhook_url: str | None,
    wechat_app_id: str | None,
    wechat_app_secret: str | None,
    wechat_qr: bool,
    wechat_openclaw_target: str | None,
    run_wechat_qr_setup: bool | None,
    feishu: bool | None,
    feishu_webhook_url: str | None,
    feishu_app_id: str | None,
    feishu_app_secret: str | None,
    feishu_connection_mode: str | None,
    feishu_home_chat_id: str | None,
    feishu_allowed_users: str | None,
    run_channel_test: bool | None,
) -> dict[str, Any]:
    existing_config = _load_or_default_config(config_path)
    existing_env = _read_env_file(env_path)
    llm_defaults = existing_config.deployment.llm
    typer.echo("AI-Researcher setup wizard")
    typer.echo("Step 1/4: choose the model provider.")
    stored_provider = existing_env.get("AUTORESEARCH_LLM_PROVIDER")
    if not stored_provider and config_path.exists():
        stored_provider = llm_defaults.provider
    preset = _prompt_provider_preset(
        existing_provider=provider
        or stored_provider
        or LLM_PROVIDER_PRESETS[0]["provider"],
    )
    provider_value = provider or preset["provider"]
    config_matches_preset = (
        config_path.exists()
        and llm_defaults.provider.casefold() == provider_value.casefold()
    )
    base_url_value = base_url or _prompt_text(
        "API base URL",
        default=existing_env.get("AUTORESEARCH_LLM_BASE_URL")
        or (llm_defaults.base_url if config_matches_preset else None)
        or preset["base_url"],
    )
    model_name_value = model_name or _prompt_text(
        "Model name",
        default=existing_env.get("AUTORESEARCH_LLM_MODEL_NAME")
        or (llm_defaults.model_name if config_matches_preset else None)
        or preset["model_name"],
    )

    typer.echo("Step 2/4: configure the API key.")
    api_key_value = api_key or _prompt_api_key(existing_env.get("AUTORESEARCH_LLM_API_KEY"))

    typer.echo("Step 3/4: configure operator channels.")
    channel_flags = _prompt_channel_flags(
        wechat=wechat,
        feishu=feishu,
        existing_wechat=existing_config.deployment.wechat.enabled,
        existing_feishu=existing_config.deployment.feishu.enabled,
    )
    wechat_enabled = channel_flags["wechat"]
    feishu_enabled = channel_flags["feishu"]
    wechat_values = _prompt_setup_channel_values(
        enabled=wechat_enabled,
        channel_name="WeChat",
        webhook_url=wechat_webhook_url or existing_env.get("AUTORESEARCH_WECHAT_WEBHOOK_URL"),
        app_id=wechat_app_id or existing_env.get("AUTORESEARCH_WECHAT_APP_ID"),
        app_secret=wechat_app_secret or existing_env.get("AUTORESEARCH_WECHAT_APP_SECRET"),
        connection_mode=(
            "qr"
            if wechat_qr
            else existing_env.get("AUTORESEARCH_WECHAT_CONNECTION_MODE")
            or existing_config.deployment.wechat.connection_mode
        ),
        home_chat_id=wechat_openclaw_target
        or existing_env.get("AUTORESEARCH_WECHAT_OPENCLAW_TARGET"),
        allowed_users=None,
        run_qr_setup=run_wechat_qr_setup,
    )
    feishu_values = _prompt_setup_channel_values(
        enabled=feishu_enabled,
        channel_name="Feishu",
        webhook_url=feishu_webhook_url or existing_env.get("AUTORESEARCH_FEISHU_WEBHOOK_URL"),
        app_id=feishu_app_id or existing_env.get("AUTORESEARCH_FEISHU_APP_ID"),
        app_secret=feishu_app_secret or existing_env.get("AUTORESEARCH_FEISHU_APP_SECRET"),
        connection_mode=(
            feishu_connection_mode
            or existing_env.get("AUTORESEARCH_FEISHU_CONNECTION_MODE")
            or existing_config.deployment.feishu.connection_mode
        ),
        home_chat_id=feishu_home_chat_id
        or existing_env.get("AUTORESEARCH_FEISHU_HOME_CHAT_ID"),
        allowed_users=feishu_allowed_users or existing_env.get("AUTORESEARCH_FEISHU_ALLOWED_USERS"),
        run_qr_setup=False,
    )
    channel_test_value = _prompt_setup_channel_test(
        wechat_enabled=bool(wechat_values["enabled"]),
        feishu_enabled=bool(feishu_values["enabled"]),
        run_channel_test=run_channel_test,
    )

    typer.echo("Step 4/4: write local AI-Researcher assets.")
    typer.echo("The wizard will write config.yaml, .env, integration manifests, and slash commands.")
    return {
        "provider": provider_value,
        "base_url": base_url_value,
        "model_name": model_name_value,
        "api_key": api_key_value,
        "wechat": wechat_values["enabled"],
        "wechat_webhook_url": wechat_values["webhook_url"],
        "wechat_app_id": wechat_values["app_id"],
        "wechat_app_secret": wechat_values["app_secret"],
        "wechat_qr": wechat_values["connection_mode"] == "qr",
        "wechat_openclaw_target": wechat_values["home_chat_id"],
        "run_wechat_qr_setup": wechat_values["run_qr_setup"],
        "feishu": feishu_values["enabled"],
        "feishu_webhook_url": feishu_values["webhook_url"],
        "feishu_app_id": feishu_values["app_id"],
        "feishu_app_secret": feishu_values["app_secret"],
        "feishu_connection_mode": feishu_values["connection_mode"],
        "feishu_home_chat_id": feishu_values["home_chat_id"],
        "feishu_allowed_users": feishu_values["allowed_users"],
        "run_channel_test": channel_test_value,
    }


def _prompt_provider_preset(*, existing_provider: str) -> dict[str, str]:
    default_index = 1
    normalized_existing = existing_provider.casefold()
    for index, preset in enumerate(LLM_PROVIDER_PRESETS, start=1):
        if normalized_existing in {preset["id"].casefold(), preset["provider"].casefold()}:
            default_index = index
            break
    labels = [
        f"{preset['label']} ({preset['base_url']}, default model {preset['model_name']})"
        for preset in LLM_PROVIDER_PRESETS
    ]
    index = _prompt_choice_index(
        "Provider",
        labels,
        default_index=default_index,
    )
    return LLM_PROVIDER_PRESETS[index - 1]


def _prompt_channel_flags(
    *,
    wechat: bool | None,
    feishu: bool | None,
    existing_wechat: bool,
    existing_feishu: bool,
) -> dict[str, bool]:
    if wechat is not None or feishu is not None:
        return {
            "wechat": bool(wechat) if wechat is not None else existing_wechat,
            "feishu": bool(feishu) if feishu is not None else existing_feishu,
        }
    default_index = 1
    if existing_wechat and existing_feishu:
        default_index = 4
    elif existing_wechat:
        default_index = 2
    elif existing_feishu:
        default_index = 3
    index = _prompt_choice_index(
        "Channels",
        (
            "Skip channels for now",
            "Configure WeChat",
            "Configure Feishu",
            "Configure both WeChat and Feishu",
        ),
        default_index=default_index,
    )
    return {
        "wechat": index in {2, 4},
        "feishu": index in {3, 4},
    }


def _prompt_setup_channel_values(
    *,
    enabled: bool,
    channel_name: str,
    webhook_url: str | None,
    app_id: str | None,
    app_secret: str | None,
    connection_mode: str | None,
    home_chat_id: str | None,
    allowed_users: str | None,
    run_qr_setup: bool | None,
) -> dict[str, str | bool | None]:
    if not enabled:
        return _empty_channel_values(enabled=False)
    existing_mode = _default_channel_mode(
        channel_name=channel_name,
        webhook_url=webhook_url,
        app_id=app_id,
        app_secret=app_secret,
        requested_mode=connection_mode,
        qr_setup=False,
    )
    if (existing_mode == "qr" or webhook_url or (app_id and app_secret)) and typer.confirm(
        f"Reuse existing {channel_name} channel credentials?",
        default=True,
    ):
        return {
            "enabled": True,
            "connection_mode": existing_mode,
            "webhook_url": webhook_url,
            "app_id": app_id,
            "app_secret": app_secret,
            "home_chat_id": home_chat_id,
            "allowed_users": allowed_users,
            "run_qr_setup": run_qr_setup,
        }
    if channel_name.casefold() == "wechat":
        mode = _prompt_choice_index(
            "WeChat setup mode",
            (
                "QR login through the upstream Weixin adapter (recommended)",
                "Webhook URL fallback",
                "App ID + app secret",
                "Skip this channel for now",
            ),
            default_index=1,
        )
        if mode == 1:
            return {
                "enabled": True,
                "connection_mode": "qr",
                "webhook_url": None,
                "app_id": None,
                "app_secret": None,
                "home_chat_id": typer.prompt(
                    "WeChat OpenClaw target (optional; can be set after pairing)",
                    default=home_chat_id or "",
                ).strip()
                or None,
                "allowed_users": None,
                "run_qr_setup": True if run_qr_setup is None else run_qr_setup,
            }
        if mode == 2:
            return {
                "enabled": True,
                "connection_mode": "webhook",
                "webhook_url": _prompt_text("WeChat webhook URL", default=webhook_url),
                "app_id": None,
                "app_secret": None,
                "home_chat_id": None,
                "allowed_users": None,
                "run_qr_setup": False,
            }
        if mode == 3:
            return {
                "enabled": True,
                "connection_mode": "app_credentials",
                "webhook_url": None,
                "app_id": _prompt_text("WeChat app ID", default=app_id),
                "app_secret": _prompt_secret("WeChat app secret", default=app_secret),
                "home_chat_id": None,
                "allowed_users": None,
                "run_qr_setup": False,
            }
        return _empty_channel_values(enabled=False)

    mode = _prompt_choice_index(
        "Feishu setup mode",
        (
            "App ID + app secret using Feishu/Lark app gateway (recommended)",
            "Webhook URL fallback",
            "Skip this channel for now",
        ),
        default_index=1,
    )
    if mode == 1:
        return {
            "enabled": True,
            "connection_mode": "websocket",
            "webhook_url": None,
            "app_id": _prompt_text("Feishu App ID", default=app_id),
            "app_secret": _prompt_secret("Feishu App Secret", default=app_secret),
            "home_chat_id": typer.prompt(
                "Feishu home chat ID (optional; can be set later)",
                default=home_chat_id or "",
            ).strip()
            or None,
            "allowed_users": typer.prompt(
                "Feishu allowed users (optional comma-separated)",
                default=allowed_users or "",
            ).strip()
            or None,
            "run_qr_setup": False,
        }
    if mode == 2:
        return {
            "enabled": True,
            "connection_mode": "webhook",
            "webhook_url": _prompt_text("Feishu webhook URL", default=webhook_url),
            "app_id": None,
            "app_secret": None,
            "home_chat_id": None,
            "allowed_users": None,
            "run_qr_setup": False,
        }
    return _empty_channel_values(enabled=False)


def _prompt_setup_channel_test(
    *,
    wechat_enabled: bool,
    feishu_enabled: bool,
    run_channel_test: bool | None,
) -> bool:
    if not (wechat_enabled or feishu_enabled):
        return False
    if run_channel_test is not None:
        return run_channel_test
    return typer.confirm(
        "Send a real channel delivery self-test now?",
        default=True,
    )


def _prompt_choice_index(
    prompt: str,
    choices: Iterable[str],
    *,
    default_index: int,
) -> int:
    options = list(choices)
    for index, label in enumerate(options, start=1):
        default_marker = " [default]" if index == default_index else ""
        typer.echo(f"  {index}. {label}{default_marker}")
    while True:
        raw = typer.prompt(prompt, default=str(default_index)).strip()
        try:
            selected = int(raw)
        except ValueError:
            typer.echo(f"[WARN] Enter a number from 1 to {len(options)}.")
            continue
        if 1 <= selected <= len(options):
            return selected
        typer.echo(f"[WARN] Enter a number from 1 to {len(options)}.")


def _prompt_text(prompt: str, *, default: str | None) -> str:
    value = str(typer.prompt(prompt, default=default or "")).strip()
    if value:
        return value
    raise typer.BadParameter(f"{prompt} is required")


def _prompt_api_key(existing_key: str | None) -> str:
    if existing_key and typer.confirm("Reuse existing API key from .env?", default=True):
        return existing_key
    return _prompt_secret("LLM API key", default=None)


def _prompt_secret(prompt: str, *, default: str | None) -> str:
    if default and typer.confirm(f"Reuse existing {prompt}?", default=True):
        return default
    value = str(typer.prompt(prompt, hide_input=sys.stdin.isatty())).strip()
    if value:
        return value
    raise typer.BadParameter(f"{prompt} is required")


def _render_operator_monitor(
    *,
    agent_log: Path,
    sessions_state: Path,
    runtime_state: Path,
    scheduler_state: Path,
    outputs_dir: Path,
    cycle_summary: Path | None,
    max_agent_entries: int,
    max_diff_lines: int,
    show_diff: bool,
    clear: bool,
) -> None:
    from rich import box
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel

    console = Console(color_system=None, force_terminal=False)
    if clear:
        console.clear()
    summary_path = cycle_summary or _latest_output_summary(outputs_dir)
    console.rule("[bold]AI-Researcher Operator Console")
    console.print(
        Columns(
            (
                Panel(
                    _recent_agent_entries_text(agent_log, max_entries=max_agent_entries),
                    title="Agent Messages",
                    border_style="cyan",
                    box=box.ASCII,
                ),
                Panel(
                    _state_table(
                        title="Agent Sessions",
                        rows=_agent_session_rows(sessions_state),
                        columns=("agent", "task", "status", "paths"),
                    ),
                    title="Active Agents",
                    border_style="green",
                    box=box.ASCII,
                ),
                Panel(
                    _state_table(
                        title="Agent Profiles",
                        rows=_agent_profile_rows(summary_path),
                        columns=("agent", "role/stages", "skills", "mcp"),
                    ),
                    title="Agent Profiles",
                    border_style="blue",
                    box=box.ASCII,
                ),
            ),
            equal=True,
            expand=True,
        )
    )
    console.print(
        Columns(
            (
                Panel(
                    _flow_table(summary_path),
                    title="Information Flow",
                    border_style="magenta",
                    box=box.ASCII,
                ),
                Panel(
                    _state_table(
                        title="Queue",
                        rows=_approval_and_task_rows(runtime_state, scheduler_state),
                        columns=("kind", "id", "status", "detail"),
                    ),
                    title="Approvals and Tasks",
                    border_style="yellow",
                    box=box.ASCII,
                ),
            ),
            equal=True,
            expand=True,
        )
    )
    console.print(
        Columns(
            (
                Panel(
                    _git_changes_text(max_diff_lines=max_diff_lines)
                    if show_diff
                    else "Diff preview disabled with --no-diff.",
                    title="Changes",
                    border_style="red",
                    box=box.ASCII,
                ),
                Panel(
                    _output_preview_text(outputs_dir, summary_path=summary_path),
                    title="Preview Results",
                    border_style="blue",
                    box=box.ASCII,
                ),
            ),
            equal=True,
            expand=True,
        )
    )


def _recent_agent_entries_text(agent_log: Path, *, max_entries: int) -> str:
    if not agent_log.exists():
        return f"No agent log found at {_relative_path_text(agent_log)}."
    entries: list[list[str]] = []
    current: list[str] = []
    capture_detail = False
    captured_detail = False
    for line in agent_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^### \d{4}-\d{2}-\d{2}", line):
            if current:
                entries.append(current)
            current = [line.removeprefix("### ").strip()]
            capture_detail = False
            captured_detail = False
            continue
        stripped = line.strip()
        if current and (
            line.startswith("- Request:")
            or line.startswith("- Summary:")
            or line.startswith("- Verification:")
            or line.startswith("- Problems:")
            or line.startswith("- Follow-up:")
        ):
            current.append(_truncate_cell(stripped, limit=180))
            capture_detail = stripped in {
                "- Summary:",
                "- Verification:",
                "- Problems:",
                "- Follow-up:",
            }
            captured_detail = False
            continue
        if current and capture_detail and not captured_detail and line.startswith("  - "):
            current.append(_truncate_cell(stripped, limit=180))
            captured_detail = True
    if current:
        entries.append(current)
    if not entries:
        return "Agent.md exists, but no change-log entries were found."
    rendered: list[str] = []
    for entry in reversed(entries[-max_entries:]):
        rendered.append("\n".join(entry[:12]))
    return "\n\n".join(rendered)


def _state_table(
    *,
    title: str,
    rows: list[tuple[str, str, str, str]],
    columns: tuple[str, str, str, str],
) -> Any:
    from rich import box
    from rich.table import Table

    table = Table(title=title, expand=True, box=box.ASCII)
    for column in columns:
        table.add_column(column, overflow="fold")
    if not rows:
        table.add_row("-", "-", "-", "none")
        return table
    for row in rows:
        table.add_row(*(_truncate_cell(value) for value in row))
    return table


def _agent_session_rows(sessions_state: Path) -> list[tuple[str, str, str, str]]:
    payload = _read_json_mapping(sessions_state)
    rows: list[tuple[str, str, str, str]] = []
    for session in _mapping_list(payload.get("sessions")):
        status = str(session.get("status", "unknown"))
        if status != "active":
            continue
        rows.append(
            (
                str(session.get("agent_name", "unknown")),
                str(session.get("task_id", "unknown")),
                status,
                ", ".join(str(path) for path in _string_list(session.get("claimed_paths"))),
            )
        )
    return rows


def _agent_profile_rows(summary_path: Path | None) -> list[tuple[str, str, str, str]]:
    if summary_path is None:
        return []
    summary = _read_json_mapping(summary_path)
    agent_profiles_value = summary.get("agent_profiles")
    agent_profiles = (
        agent_profiles_value if isinstance(agent_profiles_value, Mapping) else {}
    )
    rows: list[tuple[str, str, str, str]] = []
    for profile in _mapping_list(agent_profiles.get("profiles")):
        skill_ids = _string_list(profile.get("skill_ids"))
        assigned_stages = _string_list(profile.get("assigned_stages"))
        role_stages = (
            f"{profile.get('role', 'unknown')}; {','.join(assigned_stages)}"
            if assigned_stages
            else f"{profile.get('role', 'unknown')}; unassigned"
        )
        readiness = profile.get("readiness")
        if isinstance(readiness, Mapping):
            failed = int(readiness.get("failed_check_count", 0) or 0)
            warnings = int(readiness.get("warning_count", 0) or 0)
            readiness_label = "ready=pass" if failed == 0 else f"ready=fail:{failed}"
            if warnings:
                readiness_label = f"{readiness_label},warn:{warnings}"
            role_stages = f"{role_stages}; {readiness_label}"
        mcp_parts: list[str] = []
        for server in _mapping_list(profile.get("mcp_servers")):
            server_id = str(server.get("server_id", "unknown"))
            tools = ",".join(_string_list(server.get("allowed_tools"))) or "none"
            mcp_parts.append(f"{server_id}:{tools}")
        rows.append(
            (
                str(profile.get("agent_id", "unknown")),
                role_stages,
                ", ".join(skill_ids) or "none",
                ", ".join(mcp_parts) or "none",
            )
        )
    return rows


def _approval_and_task_rows(
    runtime_state: Path,
    scheduler_state: Path,
) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    approvals = _read_json_mapping(runtime_state)
    for request in _mapping_list(approvals.get("requests")):
        status = str(request.get("status", "unknown"))
        if status not in {"pending", "approved"}:
            continue
        rows.append(
            (
                "approval",
                str(request.get("request_id", "unknown")),
                status,
                str(request.get("action_id") or request.get("command") or "no detail"),
            )
        )
    scheduler = _read_json_mapping(scheduler_state)
    for task in _mapping_list(scheduler.get("tasks")):
        status = str(task.get("status", "unknown"))
        if status == "completed":
            continue
        rows.append(
            (
                "task",
                str(task.get("task_id", "unknown")),
                status,
                str(task.get("name") or task.get("metadata", {}).get("issue_path") or "no detail"),
            )
        )
    return rows


def _flow_table(summary_path: Path | None) -> Any:
    from rich import box
    from rich.table import Table

    table = Table(title="Research Loop", expand=True, box=box.ASCII)
    table.add_column("stage", no_wrap=True)
    table.add_column("status", overflow="fold")
    table.add_column("evidence", overflow="fold")
    if summary_path is None or not summary_path.exists():
        for stage in (
            "source discovery",
            "similarity check",
            "experiment",
            "review",
            "paper build",
            "evidence gate",
            "vault follow-up",
        ):
            table.add_row(stage, "waiting", "no cycle summary selected")
        return table

    payload = _read_json_mapping(summary_path)
    for stage, status, evidence in _cycle_stage_rows(payload, summary_path=summary_path):
        table.add_row(stage, status, evidence)
    return table


def _cycle_stage_rows(
    payload: Mapping[str, Any],
    *,
    summary_path: Path,
) -> list[tuple[str, str, str]]:
    return [
        (
            "source",
            _nested_status(payload, "source_preflight"),
            _cycle_evidence(payload, "source_preflight", ("markdown_path", "output_path"), summary_path),
        ),
        (
            "literature",
            _literature_status(payload),
            _cycle_evidence(payload, "literature", ("markdown_path", "summary_path", "output_path"), summary_path),
        ),
        (
            "plan",
            _research_plan_status(payload),
            _cycle_evidence(payload, "research_plan", ("pdf_path", "markdown_path", "json_path"), summary_path),
        ),
        (
            "novelty",
            _nested_status(payload, "similarity"),
            _cycle_evidence(payload, "similarity", ("markdown_path", "summary_path", "output_path"), summary_path),
        ),
        (
            "related work",
            _related_work_status(payload),
            _cycle_evidence(
                payload,
                "related_work_inspection",
                ("markdown_path", "json_path", "citation_metadata_path"),
                summary_path,
            ),
        ),
        (
            "citations",
            _citation_status(payload),
            _cycle_evidence(payload, "citations", ("bib_path", "metadata_path", "output_path"), summary_path),
        ),
        (
            "experiment",
            _experiment_status(payload),
            _cycle_evidence(payload, "demo", ("report_path", "validation_json_path", "run_record_path"), summary_path),
        ),
        (
            "reproduction",
            _nested_status(payload, "reproduction_check"),
            _cycle_evidence(payload, "reproduction_check", ("markdown_path", "json_path"), summary_path),
        ),
        (
            "review",
            _nested_status(payload, "review"),
            _cycle_evidence(payload, "review", ("vault_review", "output_path"), summary_path),
        ),
        (
            "publication",
            _publication_audit_status(payload),
            _gate_evidence(
                payload,
                "publication_audit",
                ("markdown_path", "json_path", "output_path"),
                summary_path,
                issue_label="issue",
            ),
        ),
        (
            "paper",
            _paper_build_status(payload),
            _cycle_evidence(
                payload,
                "paper_build",
                ("pdf_path", "output_pdf_path", "markdown_path", "json_path"),
                summary_path,
            ),
        ),
        (
            "evidence",
            _evidence_gate_status(payload),
            _gate_evidence(payload, "evidence_gate", ("markdown_path", "json_path", "output_path"), summary_path),
        ),
        (
            "follow-ups",
            _followup_status(payload),
            _followup_evidence(payload, summary_path),
        ),
        (
            "deliverables",
            _deliverables_status(payload),
            _deliverables_evidence(payload, summary_path),
        ),
    ]


def _nested_status(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, Mapping):
        for status_key in ("status", "verdict", "review_status", "result"):
            status = value.get(status_key)
            if status is not None:
                return str(status)
        if key == "similarity" and value.get("finding_count") is not None:
            return f"findings={value['finding_count']}"
        if key == "demo" and value.get("demo") is not None:
            return str(value["demo"])
        if key == "evidence_gate" and value.get("release_allowed") is not None:
            return f"release_allowed={str(value['release_allowed']).lower()}"
        return "recorded"
    if value is not None:
        return str(value)
    direct = payload.get(f"{key}_status")
    if direct is not None:
        return str(direct)
    return "unknown"


def _literature_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("literature")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "literature")
    document_count = value.get("document_count")
    fetches = _mapping_list(value.get("fetches"))
    sources = sorted({str(fetch.get("source")) for fetch in fetches if fetch.get("source")})
    if document_count is not None and sources:
        return f"documents={document_count}; sources={len(sources)}"
    if document_count is not None:
        return f"documents={document_count}"
    return _nested_status(payload, "literature")


def _research_plan_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("research_plan")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "research_plan")
    status = str(value.get("compile_status") or _nested_status(payload, "research_plan"))
    audit = value.get("audit")
    if isinstance(audit, Mapping) and audit.get("verdict") is not None:
        status = f"{status}; audit={audit['verdict']}"
    page_count = value.get("page_count")
    if page_count is not None:
        status = f"{status}; pages={page_count}"
    return status


def _related_work_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("related_work_inspection")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "related_work_inspection")
    inspected = value.get("inspected_count")
    direct = value.get("direct_method_count")
    if inspected is not None and direct is not None:
        return f"inspected={inspected}; direct={direct}"
    if inspected is not None:
        return f"inspected={inspected}"
    return _nested_status(payload, "related_work_inspection")


def _citation_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("citations")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "citations")
    blocked_count = value.get("blocked_count")
    citations = _mapping_list(value.get("citations"))
    if blocked_count is not None:
        return f"verified={len(citations)}; blocked={blocked_count}"
    if citations:
        return f"verified={len(citations)}"
    return _nested_status(payload, "citations")


def _experiment_status(payload: Mapping[str, Any]) -> str:
    status = _nested_status(payload, "demo")
    value = payload.get("demo")
    if not isinstance(value, Mapping):
        return status
    network = value.get("network_approval")
    if not isinstance(network, Mapping):
        return status
    details: list[str] = []
    mode = network.get("network_approval_mode")
    if mode is not None:
        details.append(f"network={mode}")
    approval_id = network.get("network_approval_id")
    if approval_id is not None:
        details.append(f"approval={_short_file_name(str(approval_id), limit=24)}")
    domains = network.get("approved_network_domains")
    if isinstance(domains, list | tuple) and domains:
        details.append(f"domains={len(domains)}")
    preflight = network.get("preflight")
    if isinstance(preflight, Mapping):
        approved = preflight.get("approved")
        if approved is not None:
            details.append(f"preflight={'pass' if approved else 'blocked'}")
        finding_count = preflight.get("finding_count")
        if finding_count is not None:
            details.append(f"findings={finding_count}")
    if not details:
        return status
    return f"{status}; {'; '.join(details)}"


def _paper_build_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("paper_build")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "paper_build")
    status = _nested_status(payload, "paper_build")
    quality = value.get("paper_quality")
    if isinstance(quality, Mapping):
        passed = quality.get("passed")
        if passed is not None:
            status = f"{status}; quality={'pass' if passed else 'fail'}"
        page_count = quality.get("page_count")
        if page_count is not None:
            status = f"{status}; pages={page_count}"
        figure_issues = quality.get("figure_readability_issue_count")
        if figure_issues is not None:
            status = f"{status}; fig_issues={figure_issues}"
    return status


def _publication_audit_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("publication_audit")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "publication_audit")
    status = _nested_status(payload, "publication_audit")
    score = value.get("score")
    if isinstance(score, int | float):
        status = f"{status}; score={score:.3f}"
    target = value.get("target")
    if isinstance(target, Mapping) and target.get("name"):
        status = f"{status}; target={target['name']}"
    blockers = _blocking_gate_checks(value)
    if blockers:
        first_id = str(blockers[0].get("check_id") or "unnamed_check")
        status = f"{status}; blockers={len(blockers)}; first={_truncate_cell(first_id, limit=32)}"
        return status
    warnings = _failed_gate_checks(value)
    if warnings:
        first_id = str(warnings[0].get("check_id") or "unnamed_check")
        status = f"{status}; warnings={len(warnings)}; first={_truncate_cell(first_id, limit=32)}"
    return status


def _evidence_gate_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("evidence_gate")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "evidence_gate")
    status = _nested_status(payload, "evidence_gate")
    failed_count = value.get("failed_check_count")
    blockers = _failed_gate_checks(value)
    if failed_count is None and blockers:
        failed_count = len(blockers)
    if failed_count is not None:
        status = f"{status}; failed={failed_count}"
    if value.get("release_allowed") is not None:
        status = f"{status}; release_allowed={str(value['release_allowed']).lower()}"
    if blockers:
        first_id = str(blockers[0].get("check_id") or "unnamed_check")
        status = f"{status}; first={_truncate_cell(first_id, limit=32)}"
    return status


def _followup_status(payload: Mapping[str, Any]) -> str:
    tasks = _summary_followup_tasks(payload)
    if not tasks:
        return "none"
    statuses = [str(task.get("status", "open")) for task in tasks]
    open_count = sum(1 for status in statuses if status not in {"completed", "closed", "done"})
    return f"{open_count} open / {len(tasks)} total"


def _deliverables_status(payload: Mapping[str, Any]) -> str:
    value = payload.get("deliverables")
    if not isinstance(value, Mapping):
        return _nested_status(payload, "deliverables")
    paths = value.get("paths")
    if isinstance(paths, Mapping) and paths:
        return f"exported={len(paths)}"
    if value.get("manifest_path") or value.get("output_dir"):
        return "exported"
    return "unknown"


def _cycle_evidence(
    payload: Mapping[str, Any],
    key: str,
    fields: tuple[str, ...],
    summary_path: Path,
) -> str:
    value = payload.get(key)
    paths: list[str] = []
    if isinstance(value, Mapping):
        for field in fields:
            field_value = value.get(field)
            if isinstance(field_value, str) and field_value.strip():
                paths.append(field_value)
    return _format_evidence_paths(paths, fallback=summary_path.name)


def _gate_evidence(
    payload: Mapping[str, Any],
    key: str,
    fields: tuple[str, ...],
    summary_path: Path,
    *,
    issue_label: str = "blocker",
) -> str:
    evidence = _cycle_evidence(payload, key, fields, summary_path)
    value = payload.get(key)
    if not isinstance(value, Mapping):
        return evidence
    blockers = _failed_gate_checks(value)
    if not blockers:
        return evidence
    blocker = blockers[0]
    parts: list[str] = []
    message = blocker.get("message")
    if isinstance(message, str) and message.strip():
        parts.append(f"{issue_label}: {message.strip()}")
    next_action = blocker.get("next_action")
    if isinstance(next_action, str) and next_action.strip():
        parts.append(f"next: {next_action.strip()}")
    if not parts:
        check_id = blocker.get("check_id")
        if check_id is not None:
            parts.append(f"{issue_label}: {check_id}")
    if not parts:
        return evidence
    detail = _truncate_cell("; ".join(parts), limit=160)
    return f"{evidence}; {detail}"


def _failed_gate_checks(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    failed: list[Mapping[str, Any]] = []
    for check in _mapping_list(value.get("checks")):
        status = str(check.get("status", "")).casefold()
        if status and status not in {"pass", "passed", "ok", "success"}:
            failed.append(check)
    return failed


def _blocking_gate_checks(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    blocking: list[Mapping[str, Any]] = []
    for check in _failed_gate_checks(value):
        status = str(check.get("status") or "").casefold()
        severity = str(check.get("severity") or "").casefold()
        if status in {"fail", "failed", "blocked", "error"} or severity == "blocking":
            blocking.append(check)
    return blocking


def _summary_followup_tasks(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    tasks = _mapping_list(payload.get("followup_tasks"))
    if tasks:
        return tasks
    followups = payload.get("followups")
    if isinstance(followups, Mapping):
        return _mapping_list(followups.get("tasks"))
    return []


def _followup_evidence(payload: Mapping[str, Any], summary_path: Path) -> str:
    tasks = _summary_followup_tasks(payload)
    paths: list[str] = []
    for task in tasks[:3]:
        for field in ("issue_path", "markdown_path", "path"):
            field_value = task.get(field)
            if isinstance(field_value, str) and field_value.strip():
                paths.append(field_value)
                break
        metadata = task.get("metadata")
        if isinstance(metadata, Mapping):
            field_value = metadata.get("issue_path")
            if isinstance(field_value, str) and field_value.strip():
                paths.append(field_value)
    return _format_evidence_paths(paths, fallback=summary_path.name if tasks else "no queued follow-ups")


def _deliverables_evidence(payload: Mapping[str, Any], summary_path: Path) -> str:
    value = payload.get("deliverables")
    paths: list[str] = []
    if isinstance(value, Mapping):
        for field in ("manifest_path", "markdown_path"):
            field_value = value.get(field)
            if isinstance(field_value, str) and field_value.strip():
                paths.append(field_value)
        nested_paths = value.get("paths")
        if isinstance(nested_paths, Mapping):
            for key in ("paper_pdf", "research_plan_pdf", "manuscript_markdown"):
                nested_value = nested_paths.get(key)
                if isinstance(nested_value, str) and nested_value.strip():
                    paths.append(nested_value)
    return _format_evidence_paths(paths, fallback=summary_path.name)


def _format_evidence_paths(paths: list[str], *, fallback: str) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = _short_evidence_path(path)
        if text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    if not cleaned:
        return fallback
    if len(cleaned) > 2:
        return f"{cleaned[0]}, {cleaned[1]} (+{len(cleaned) - 2} more)"
    return ", ".join(cleaned)


def _short_evidence_path(path: str) -> str:
    text = _relative_path_text(path).replace("\\", "/")
    if len(text) <= 48:
        return text
    parts = [part for part in text.split("/") if part]
    if len(parts) >= 2:
        file_label = _short_file_name(parts[-1], limit=32)
        tail = f".../{parts[-2]}/{file_label}"
        if len(tail) <= 48:
            return tail
        return f".../{_short_file_name(parts[-1], limit=44)}"
    if parts:
        return _short_file_name(parts[-1], limit=48)
    return text


def _short_file_name(name: str, *, limit: int = 48) -> str:
    if len(name) <= limit:
        return name
    suffix = Path(name).suffix
    head_limit = max(limit - len(suffix) - 3, 8)
    return f"{name[:head_limit]}...{suffix}"


def _git_changes_text(*, max_diff_lines: int) -> str:
    status = _run_git_text(("status", "--short"))
    diff_stat = _run_git_text(("diff", "--stat"))
    diff = _run_git_text(("diff", "--"), max_lines=max_diff_lines)
    sections = [
        "status:",
        status or "(clean)",
        "",
        "stat:",
        diff_stat or "(no unstaged diff stat)",
    ]
    if max_diff_lines:
        sections.extend(("", f"diff preview ({max_diff_lines} lines):", diff or "(no diff preview)"))
    return "\n".join(sections)


def _run_git_text(args: tuple[str, ...], *, max_lines: int | None = None) -> str:
    try:
        result = cast(
            subprocess.CompletedProcess[str],
            subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                **windows_no_window_kwargs(),
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git {' '.join(args)} failed: {exc}"
    text = (result.stdout or result.stderr).strip()
    if max_lines is None:
        return text
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines] + [f"... truncated {len(lines) - max_lines} lines"])


def _output_preview_text(outputs_dir: Path, *, summary_path: Path | None) -> str:
    lines: list[str] = []
    if summary_path is not None:
        lines.append(f"cycle summary: {_relative_path_text(summary_path)}")
    if not outputs_dir.exists():
        lines.append(f"No outputs directory found at {_relative_path_text(outputs_dir)}.")
        return "\n".join(lines)
    files = sorted(
        (path for path in outputs_dir.rglob("*") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        lines.append("No output files yet.")
        return "\n".join(lines)
    for path in files[:10]:
        size = path.stat().st_size
        marker = "PDF" if path.suffix.casefold() == ".pdf" else path.suffix.lstrip(".") or "file"
        lines.append(f"{_short_file_name(path.name)} [{marker}]: {_short_evidence_path(str(path))} ({size} bytes)")
    return "\n".join(lines)


def _latest_output_summary(outputs_dir: Path) -> Path | None:
    if not outputs_dir.exists():
        return None
    candidates = sorted(
        outputs_dir.rglob("*-summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _read_json_mapping(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, Mapping):
        return data
    return {}


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value]


def _truncate_cell(value: str, *, limit: int = 72) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _required_value(
    value: str | None,
    *,
    prompt: str,
    default: str | None,
    non_interactive: bool,
    hide_input: bool = False,
) -> str:
    if value:
        return value
    if non_interactive:
        if default:
            return default
        msg = f"{prompt} is required in --non-interactive mode"
        raise typer.BadParameter(msg)
    prompted = typer.prompt(prompt, default=default, hide_input=hide_input)
    if not isinstance(prompted, str) or not prompted.strip():
        msg = f"{prompt} is required"
        raise typer.BadParameter(msg)
    return prompted.strip()


def _confirm_if_missing(
    value: bool | None,
    *,
    prompt: str,
    non_interactive: bool,
) -> bool:
    if value is not None:
        return value
    if non_interactive:
        return False
    return typer.confirm(prompt, default=False)


def _empty_channel_values(*, enabled: bool) -> dict[str, str | bool | None]:
    return {
        "enabled": enabled,
        "connection_mode": None,
        "webhook_url": None,
        "app_id": None,
        "app_secret": None,
        "home_chat_id": None,
        "allowed_users": None,
        "run_qr_setup": False,
    }


def _channel_values(
    *,
    enabled: bool,
    channel_name: str,
    webhook_url: str | None,
    app_id: str | None,
    app_secret: str | None,
    qr_setup: bool = False,
    connection_mode: str | None = None,
    home_chat_id: str | None = None,
    allowed_users: str | None = None,
    non_interactive: bool,
) -> dict[str, str | bool | None]:
    if not enabled:
        return _empty_channel_values(enabled=False)
    values = {
        "enabled": True,
        "connection_mode": _default_channel_mode(
            channel_name=channel_name,
            webhook_url=webhook_url,
            app_id=app_id,
            app_secret=app_secret,
            requested_mode=connection_mode,
            qr_setup=qr_setup,
        ),
        "webhook_url": webhook_url,
        "app_id": app_id,
        "app_secret": app_secret,
        "home_chat_id": home_chat_id,
        "allowed_users": allowed_users,
        "run_qr_setup": False,
    }
    if non_interactive:
        if values["connection_mode"] == "qr":
            return values
        if not values["webhook_url"] and not (values["app_id"] and values["app_secret"]):
            msg = (
                f"{channel_name} requires --{channel_name.lower()}-webhook-url or both "
                f"--{channel_name.lower()}-app-id and --{channel_name.lower()}-app-secret"
            )
            if channel_name.casefold() == "wechat":
                msg += " or --wechat-qr"
            raise typer.BadParameter(msg)
        return values

    if values["webhook_url"] is None:
        values["webhook_url"] = typer.prompt(
            f"{channel_name} webhook URL (optional)",
            default="",
        ).strip() or None
    if values["app_id"] is None:
        values["app_id"] = typer.prompt(f"{channel_name} app ID (optional)", default="").strip() or None
    if values["app_secret"] is None:
        values["app_secret"] = (
            typer.prompt(f"{channel_name} app secret (optional)", default="", hide_input=True).strip()
            or None
        )
    values["connection_mode"] = _default_channel_mode(
        channel_name=channel_name,
        webhook_url=str(values["webhook_url"]) if values["webhook_url"] else None,
        app_id=str(values["app_id"]) if values["app_id"] else None,
        app_secret=str(values["app_secret"]) if values["app_secret"] else None,
        requested_mode=connection_mode,
        qr_setup=qr_setup,
    )
    if not values["webhook_url"] and not (values["app_id"] and values["app_secret"]):
        msg = f"{channel_name} channel needs a webhook URL or app ID plus app secret"
        raise typer.BadParameter(msg)
    return values


def _default_channel_mode(
    *,
    channel_name: str,
    webhook_url: str | None,
    app_id: str | None,
    app_secret: str | None,
    requested_mode: str | None,
    qr_setup: bool,
) -> str | None:
    if qr_setup:
        return "qr"
    requested = (requested_mode or "").strip().casefold()
    if requested:
        if requested in {"websocket", "webhook", "qr", "app", "app_credentials"}:
            return "app_credentials" if requested == "app" else requested
        msg = f"Unsupported {channel_name} connection mode: {requested_mode}"
        raise typer.BadParameter(msg)
    if webhook_url:
        return "webhook"
    if app_id and app_secret:
        return "websocket" if channel_name.casefold() == "feishu" else "app_credentials"
    return None


def _channel_summary(enabled: bool, values: Mapping[str, object]) -> str:
    if not enabled:
        return "disabled"
    mode = values.get("connection_mode") or "configured"
    return f"enabled ({mode})"


def _run_wechat_qr_setup(
    *,
    command: str = WECHAT_QR_SETUP_COMMAND,
    session_path: str = WECHAT_QR_SESSION_PATH,
    status_path: Path = Path(WECHAT_QR_SETUP_STATUS_PATH),
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    args = shlex.split(command)
    if not args:
        typer.echo("[FAIL] wechat_qr_setup: empty command", err=True)
        raise typer.Exit(1)
    _write_wechat_qr_setup_status(
        status_path,
        {
            "status": "running",
            "command": command,
            "session_path": session_path,
            "started_at": started_at,
        },
    )
    typer.echo("[WAIT] wechat_qr_setup: waiting for QR display and scan confirmation")
    typer.echo(f"[OK] wechat_qr_status: {status_path}")
    run = runner or subprocess.run
    try:
        result = run(args, check=False, **windows_no_window_kwargs())
    except OSError as exc:
        _write_wechat_qr_setup_status(
            status_path,
            {
                "status": "failed",
                "command": command,
                "session_path": session_path,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
        )
        typer.echo(f"[FAIL] wechat_qr_setup: {exc}", err=True)
        raise typer.Exit(1) from exc
    payload = {
        "status": "completed" if result.returncode == 0 else "failed",
        "command": command,
        "session_path": session_path,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "return_code": result.returncode,
    }
    _write_wechat_qr_setup_status(status_path, payload)
    if result.returncode != 0:
        typer.echo(f"[FAIL] wechat_qr_setup exited {result.returncode}", err=True)
        typer.echo(f"[FAIL] wechat_qr_status: {status_path}", err=True)
        raise typer.Exit(result.returncode)
    typer.echo("[OK] wechat_qr_setup: completed")
    typer.echo(f"[OK] wechat_qr_status: {status_path}")


def _write_wechat_qr_setup_status(status_path: Path, payload: Mapping[str, object]) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _echo_post_setup_next_steps(*, wechat_enabled: bool, feishu_enabled: bool) -> None:
    channels = []
    if wechat_enabled:
        channels.append("wechat")
    if feishu_enabled:
        channels.append("feishu")
    if channels:
        channel_flags = " ".join(f"--channel {channel}" for channel in channels)
        typer.echo(f"[NEXT] channel_test: airesearcher channels test {channel_flags} --require-sent")
        typer.echo(
            "[NEXT] readiness: airesearcher readiness --push-inspiration "
            "--require-channel-config --require-channel-sent"
        )
        return
    typer.echo("[NEXT] readiness: airesearcher readiness --no-push-inspiration")


def _setup_channels_to_test(*, wechat_enabled: bool, feishu_enabled: bool) -> tuple[str, ...]:
    channels: list[str] = []
    if wechat_enabled:
        channels.append("wechat")
    if feishu_enabled:
        channels.append("feishu")
    return tuple(channels)


def _setup_relative_path(env_path: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return env_path.parent / path


def _merge_env_file(env_path: Path, values: Mapping[str, object | None]) -> None:
    existing = _read_env_file(env_path)
    for key, value in values.items():
        if value is not None:
            existing[key] = str(value)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by airesearcher deploy-setup"]
    lines.extend(f"{key}={value}" for key, value in sorted(existing.items()))
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _ensure_env_example(env_path: Path) -> tuple[Path, bool]:
    env_example_path = env_path.with_name(".env.example")
    if env_example_path.exists():
        return env_example_path, False
    env_example_path.parent.mkdir(parents=True, exist_ok=True)
    env_example_path.write_text(ENV_EXAMPLE_TEXT, encoding="utf-8")
    return env_example_path, True


def _load_optional_env(env_path: Path) -> None:
    if env_path.exists():
        load_dotenv(env_path, override=True)


def _merged_optional_env(env_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(_read_env_file(env_path))
    return environment


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _merge_scheduler_state(state_path: Path, records: list[dict[str, object]]) -> None:
    existing_tasks = _read_scheduler_state_tasks(state_path)
    merged = {str(task.get("task_id")): task for task in existing_tasks if task.get("task_id")}
    for record in records:
        task_id = str(record["task_id"])
        previous = merged.get(task_id, {})
        merged_record = {**record}
        if previous.get("status") == "completed":
            merged_record["status"] = "completed"
            if "completed_at" in previous:
                merged_record["completed_at"] = previous["completed_at"]
        merged[task_id] = merged_record
    _write_scheduler_state_tasks(state_path, list(merged.values()))


def _read_scheduler_state_tasks(state_path: Path) -> list[dict[str, object]]:
    if not state_path.exists():
        return []
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def _write_scheduler_state_tasks(state_path: Path, tasks: list[dict[str, object]]) -> None:
    sorted_tasks = sorted(tasks, key=lambda task: str(task.get("task_id", "")))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"tasks": sorted_tasks}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _set_scheduler_state_task_status(state_path: Path, task_id: str, *, status: str) -> bool:
    tasks = _read_scheduler_state_tasks(state_path)
    changed = False
    for task in tasks:
        if task.get("task_id") != task_id:
            continue
        task["status"] = status
        if status == "completed":
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
        changed = True
        break
    if changed:
        _write_scheduler_state_tasks(state_path, tasks)
    return changed


def _remove_scheduler_state_task(state_path: Path, task_id: str) -> bool:
    tasks = _read_scheduler_state_tasks(state_path)
    remaining = [task for task in tasks if task.get("task_id") != task_id]
    if len(remaining) == len(tasks):
        return False
    _write_scheduler_state_tasks(state_path, remaining)
    return True


def _slash_command_toml(description: str, prompt: str) -> str:
    escaped_description = description.replace("\\", "\\\\").replace('"', '\\"')
    escaped_prompt = prompt.replace('"""', '\\"\\"\\"')
    return f'description="{escaped_description}"\nprompt = """\n{escaped_prompt}\n"""\n'


def _parser_available() -> bool:
    try:
        parser = ConfigParser()
        text = parser.format(SystemConfig(), ConfigFormat.JSON)
        parser.parse_text(text, config_format=ConfigFormat.JSON)
    except Exception:
        return False
    return True


if __name__ == "__main__":
    app()
