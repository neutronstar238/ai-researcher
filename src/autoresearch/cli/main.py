"""Minimal Typer CLI for the AI-Researcher Phase 0 scaffold."""

import json
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv

from autoresearch import __version__
from autoresearch.config import (
    ConfigFormat,
    ConfigParser,
    DeploymentConfig,
    MessagingChannelConfig,
    ModelProviderConfig,
    SystemConfig,
)
from autoresearch.experiments import run_scientistbench_demo
from autoresearch.inspiration import InspirationRefreshConfig, run_inspiration_refresh
from autoresearch.integrations import (
    CCSwitchCodeAgentBackend,
    OpenClawChannelPlugin,
    OpenCodeCodeAgentBackend,
    get_ccswitch_code_agent_backend,
    get_openclaw_channel_plugin,
    get_opencode_code_agent_backend,
    iter_ccswitch_code_agent_backends,
    iter_openclaw_channel_plugins,
    iter_opencode_code_agent_backends,
    write_ccswitch_code_agent_manifest,
    write_openclaw_channel_manifest,
    write_opencode_code_agent_manifest,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    audit_skill_polish_candidate,
    create_obsidian_vault_assets,
    create_skill_evolution_candidate,
)
from autoresearch.literature import (
    ArxivClient,
    LiteratureRefreshConfig,
    LiteratureSearchClient,
    OpenAlexClient,
    SemanticScholarClient,
    SourceCircuitStateLockError,
    run_daily_literature_refresh,
)
from autoresearch.llm import (
    LLMClientError,
    run_llm_evidence_review,
    run_llm_smoke_test,
    write_llm_review_issue_notes,
    write_llm_review_note,
)
from autoresearch.reports import (
    EvidenceGateVerdict,
    LatexPaperBuildStatus,
    audit_publication_quality,
    build_latex_paper_from_markdown,
    run_evidence_gate,
    validate_reproducibility_package,
)
from autoresearch.research import (
    SimilarityCheckConfig,
    link_similarity_report_to_project,
    run_project_similarity_check,
)
from autoresearch.runtime import (
    AgentSessionError,
    RuntimeActionRisk,
    RuntimeApprovalError,
    RuntimePermissionMode,
    approve_runtime_request,
    claim_agent_session,
    ensure_runtime_approval,
    list_agent_sessions,
    list_runtime_approval_requests,
    release_agent_session,
)
from autoresearch.scheduler import queued_issue_followups_from_vault
from autoresearch.schemas import CandidateStatus, ResearchCandidate, ValidationStatus

app = typer.Typer(
    help="AI-Researcher command line interface.",
    no_args_is_help=True,
)
slash_app = typer.Typer(help="Manage project slash command templates.")
scheduler_state_app = typer.Typer(help="Manage local scheduler state records.")
runtime_app = typer.Typer(help="Manage always-on runtime approvals.")
sessions_app = typer.Typer(help="Coordinate concurrent agent file claims.")
channels_app = typer.Typer(help="Manage communication channel integration manifests.")
openclaw_channels_app = typer.Typer(help="Manage OpenClaw channel plugin manifests.")
code_agents_app = typer.Typer(help="Manage external code-agent integration manifests.")
ccswitch_code_agents_app = typer.Typer(help="Manage cc-switch / Claude Code backend manifests.")
opencode_code_agents_app = typer.Typer(help="Manage OpenCode direct backend manifests.")
app.add_typer(slash_app, name="slash-commands")
app.add_typer(scheduler_state_app, name="scheduler-state")
app.add_typer(runtime_app, name="runtime")
app.add_typer(sessions_app, name="sessions")
app.add_typer(channels_app, name="channels")
app.add_typer(code_agents_app, name="code-agents")
channels_app.add_typer(openclaw_channels_app, name="openclaw")
code_agents_app.add_typer(ccswitch_code_agents_app, name="cc-switch")
code_agents_app.add_typer(opencode_code_agents_app, name="opencode")

DEFAULT_SCHEDULER_STATE_PATH = Path(".airesearcher/scheduler-state.json")
DEFAULT_RUNTIME_APPROVALS_PATH = Path(".airesearcher/runtime-approvals.json")
DEFAULT_AGENT_SESSIONS_PATH = Path(".airesearcher/agent-sessions.json")
PUBLICATION_SEARCH_QUERIES = 4
PUBLICATION_RESULTS_PER_SOURCE = 10

DEFAULT_SLASH_COMMANDS = {
    "research/refresh-literature.toml": (
        "Fetch real literature sources and write a guarded Obsidian summary.",
        "Run `airesearcher literature-refresh --live --vault autoresearch-vault --cache .cache/literature` "
        "and summarize source-backed new papers only. Do not infer paper results, code "
        "availability, or benchmark scores unless the fetched source explicitly provides them.",
    ),
    "research/inspiration-refresh.toml": (
        "Search broad non-scholarly inspiration sources without treating them as paper evidence.",
        "Run `airesearcher inspiration-refresh --query \"{{args}}\" --vault autoresearch-vault "
        "--output runs/inspiration/latest.json`. Results from Hugging Face datasets and Hacker News "
        "are dataset/community signals only; validate them separately before using them as research evidence.",
    ),
    "research/similarity-check.toml": (
        "Cross-check a candidate against adjacent online work before project approval.",
        "Run `airesearcher similarity-check --candidate-file <candidate.json> --live` for {{args}}. "
        "Use source URLs and DOI evidence only; unsupported outcomes must remain pending verification.",
    ),
    "research/run-demo.toml": (
        "Run a local demo or public benchmark and inspect evidence outputs.",
        "Run `airesearcher run-demo --demo {{args}}` or default to tabular_baseline. "
        "Review the validation report, evidence map, and Markdown report before making claims.",
    ),
    "research/autopilot.toml": (
        "Start the local autonomous research loop with evidence and review gates.",
        "Run `airesearcher autopilot --watch --cycles 0 --interval-seconds 86400` "
        "after deploy-setup. The loop performs live literature refresh, similarity "
        "checking, local experiment execution, evidence review, and Obsidian issue "
        "follow-up discovery using publication-grade default search breadth; inspect "
        "cycle-summary.json before claiming publication quality.",
    ),
    "research/serve.toml": (
        "Start the always-on operator service with dangerous-action approval gates.",
        "Run `airesearcher serve --permission-mode approve-dangerous` after deploy-setup. "
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
    "research/approve.toml": (
        "Approve the latest pending dangerous runtime action.",
        "Run `airesearcher runtime approve {{args}} --state .airesearcher/runtime-approvals.json "
        "--approved-by operator`. Use `latest` when approving the newest pending request "
        "from a WeChat/Feishu `/approve` message.",
    ),
    "research/openclaw-channels.toml": (
        "Write the OpenClaw communication channel integration manifest.",
        "Run `airesearcher channels openclaw init --output integrations/openclaw/channels.json` "
        "to create the repository runbook for official Lark/Feishu, Weixin, WeCom, "
        "Telegram, Discord, Slack, WhatsApp, Teams, QQ, Signal, and Zalo channel plugins. "
        "Review upstream permissions and secrets before installing any plugin.",
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

# Optional Semantic Scholar Graph API key for higher rate limits.
SEMANTIC_SCHOLAR_API_KEY=
SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS=
SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS=

# Optional OpenAlex key/contact for broader source fallback.
OPENALEX_API_KEY=
OPENALEX_MAILTO=
OPENALEX_MIN_INTERVAL_SECONDS=
OPENALEX_CIRCUIT_RESET_SECONDS=

# Optional WeChat channel.
AUTORESEARCH_WECHAT_WEBHOOK_URL=
AUTORESEARCH_WECHAT_APP_ID=
AUTORESEARCH_WECHAT_APP_SECRET=

# Optional Feishu channel.
AUTORESEARCH_FEISHU_WEBHOOK_URL=
AUTORESEARCH_FEISHU_APP_ID=
AUTORESEARCH_FEISHU_APP_SECRET=
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

    failed = False
    for name, ok, detail in checks:
        label = "OK" if ok else "FAIL"
        typer.echo(f"[{label}] {name}: {detail}")
        failed = failed or not ok

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
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Fail on missing required inputs instead of prompting."),
    ] = False,
) -> None:
    """Run first-deploy setup for model API credentials and chat channels."""

    provider_value = _required_value(
        provider,
        prompt="LLM provider label",
        default="openai-compatible",
        non_interactive=non_interactive,
    )
    base_url_value = _required_value(
        base_url,
        prompt="LLM API base URL",
        default="https://api.openai.com/v1",
        non_interactive=non_interactive,
    )
    model_name_value = _required_value(
        model_name,
        prompt="LLM model name",
        default="gpt-4o-mini",
        non_interactive=non_interactive,
    )
    api_key_value = _required_value(
        api_key,
        prompt="LLM API key",
        default=None,
        hide_input=True,
        non_interactive=non_interactive,
    )

    wechat_enabled = _confirm_if_missing(
        wechat,
        prompt="Configure WeChat channel?",
        non_interactive=non_interactive,
    )
    feishu_enabled = _confirm_if_missing(
        feishu,
        prompt="Configure Feishu channel?",
        non_interactive=non_interactive,
    )

    wechat_values = _channel_values(
        enabled=wechat_enabled,
        channel_name="WeChat",
        webhook_url=wechat_webhook_url,
        app_id=wechat_app_id,
        app_secret=wechat_app_secret,
        non_interactive=non_interactive,
    )
    feishu_values = _channel_values(
        enabled=feishu_enabled,
        channel_name="Feishu",
        webhook_url=feishu_webhook_url,
        app_id=feishu_app_id,
        app_secret=feishu_app_secret,
        non_interactive=non_interactive,
    )

    config = _load_or_default_config(config_path)
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
                    webhook_url_env="AUTORESEARCH_WECHAT_WEBHOOK_URL"
                    if wechat_values["webhook_url"]
                    else None,
                    app_id_env="AUTORESEARCH_WECHAT_APP_ID" if wechat_values["app_id"] else None,
                    app_secret_env=(
                        "AUTORESEARCH_WECHAT_APP_SECRET"
                        if wechat_values["app_secret"]
                        else None
                    ),
                ),
                feishu=MessagingChannelConfig(
                    enabled=feishu_enabled,
                    webhook_url_env="AUTORESEARCH_FEISHU_WEBHOOK_URL"
                    if feishu_values["webhook_url"]
                    else None,
                    app_id_env="AUTORESEARCH_FEISHU_APP_ID" if feishu_values["app_id"] else None,
                    app_secret_env=(
                        "AUTORESEARCH_FEISHU_APP_SECRET"
                        if feishu_values["app_secret"]
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
        "AUTORESEARCH_WECHAT_WEBHOOK_URL": wechat_values["webhook_url"],
        "AUTORESEARCH_WECHAT_APP_ID": wechat_values["app_id"],
        "AUTORESEARCH_WECHAT_APP_SECRET": wechat_values["app_secret"],
        "AUTORESEARCH_FEISHU_WEBHOOK_URL": feishu_values["webhook_url"],
        "AUTORESEARCH_FEISHU_APP_ID": feishu_values["app_id"],
        "AUTORESEARCH_FEISHU_APP_SECRET": feishu_values["app_secret"],
    }
    env_example_path, env_example_created = _ensure_env_example(env_path)
    _merge_env_file(env_path, env_values)

    typer.echo(f"[OK] config written: {config_path}")
    typer.echo(f"[OK] env written: {env_path}")
    typer.echo(
        f"[OK] env template {'created' if env_example_created else 'ready'}: {env_example_path}"
    )
    typer.echo(f"[OK] model: {provider_value} / {model_name_value}")
    typer.echo(f"[OK] wechat: {'enabled' if wechat_enabled else 'disabled'}")
    typer.echo(f"[OK] feishu: {'enabled' if feishu_enabled else 'disabled'}")


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
) -> None:
    """Search broad dataset/community sources and write an Obsidian-safe summary."""

    try:
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

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_json_dict(), indent=2, sort_keys=True), encoding="utf-8")
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
    if not report.items:
        typer.echo("[FAIL] inspiration refresh returned no source-backed items", err=True)
        raise typer.Exit(code=1)


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
    typer.echo(f"[OK] experiment_dir: {result.experiment_dir}")
    typer.echo(f"[OK] run_id: {result.run_id}")
    typer.echo(f"[OK] validation: {result.validation_json_path}")
    typer.echo(f"[OK] evidence_map: {result.evidence_map_path}")
    typer.echo(f"[OK] report: {result.report_path}")


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
        int,
        typer.Option("--max-tokens", min=128, help="Maximum output tokens for the smoke request."),
    ] = 600,
) -> None:
    """Call the configured live LLM API and run a structured output quality gate."""

    try:
        result = run_llm_smoke_test(
            config_path=config_path,
            env_path=env_path,
            max_tokens=max_tokens,
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
        int,
        typer.Option("--max-tokens", min=256, help="Maximum output tokens for the review request."),
    ] = 4096,
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
            max_tokens=max_tokens,
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
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Project ID for Obsidian review and issue notes."),
    ] = "autopilot-demo",
    demo: Annotated[
        str,
        typer.Option("--demo", help="Demo or public benchmark to execute in each cycle."),
    ] = "tabular_baseline",
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
        int,
        typer.Option("--max-tokens", min=256, help="LLM reviewer completion token budget."),
    ] = 4096,
    min_quality_score: Annotated[
        float,
        typer.Option("--min-quality-score", min=0.0, max=1.0, help="Minimum LLM review score."),
    ] = 0.85,
    review: Annotated[
        bool,
        typer.Option("--review/--no-review", help="Run the live LLM evidence reviewer."),
    ] = True,
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
    completed = 0
    while True:
        completed += 1
        try:
            summary = _run_autopilot_cycle(
                config_path=config_path,
                env_path=env_path,
                vault=vault,
                cache=cache,
                output_dir=output_dir,
                state=state,
                project_id=project_id,
                demo=demo,
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                min_quality_score=min_quality_score,
                review=review,
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
        typer.echo(f"[OK] review_status: {summary['review']['status']}")
        if "publication_audit" in summary:
            typer.echo(
                "[OK] publication_audit: "
                f"{summary['publication_audit']['verdict']}"
            )
        if "evidence_gate" in summary:
            typer.echo(f"[OK] evidence_gate: {summary['evidence_gate']['verdict']}")
        typer.echo(f"[OK] followup_tasks: {summary['followups']['task_count']}")
        if not watch:
            break
        if cycles > 0 and completed >= cycles:
            break
        time.sleep(interval_seconds)


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
    state: Annotated[
        Path,
        typer.Option("--state", help="Local scheduler state JSON file."),
    ] = DEFAULT_SCHEDULER_STATE_PATH,
    approvals_state: Annotated[
        Path,
        typer.Option("--approvals-state", help="Local runtime approval queue JSON file."),
    ] = DEFAULT_RUNTIME_APPROVALS_PATH,
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
    ] = "tabular_baseline",
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
        int,
        typer.Option("--max-tokens", min=256, help="LLM reviewer completion token budget."),
    ] = 4096,
    min_quality_score: Annotated[
        float,
        typer.Option("--min-quality-score", min=0.0, max=1.0, help="Minimum LLM review score."),
    ] = 0.85,
    review: Annotated[
        bool,
        typer.Option("--review/--no-review", help="Run the live LLM evidence reviewer."),
    ] = True,
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
) -> None:
    """Run AI-Researcher as an always-on local/server operator service."""

    _load_optional_env(env_path)
    completed = 0
    action_id = f"serve:autopilot-cycle:{project_id}:{demo}"
    command_text = _serve_command_text(
        project_id=project_id,
        demo=demo,
        permission_mode=permission_mode,
        review=review,
    )
    typer.echo(f"[OK] runtime_mode: {permission_mode.value}")
    while True:
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
            typer.echo(f"[WAITING] approval_required: {request_id}")
            typer.echo(f"[WAITING] state: {approvals_state}")
            typer.echo(
                "[WAITING] approve: "
                f"airesearcher runtime approve {request_id} --state {approvals_state}"
            )
            if not watch:
                raise typer.Exit(code=2)
            time.sleep(interval_seconds)
            continue

        completed += 1
        try:
            summary = _run_autopilot_cycle(
                config_path=config_path,
                env_path=env_path,
                vault=vault,
                cache=cache,
                output_dir=output_dir,
                state=state,
                project_id=project_id,
                demo=demo,
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                min_quality_score=min_quality_score,
                review=review,
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
        typer.echo(f"[OK] review_status: {summary['review']['status']}")
        if "publication_audit" in summary:
            typer.echo(
                "[OK] publication_audit: "
                f"{summary['publication_audit']['verdict']}"
            )
        if "evidence_gate" in summary:
            typer.echo(f"[OK] evidence_gate: {summary['evidence_gate']['verdict']}")
        typer.echo(f"[OK] followup_tasks: {summary['followups']['task_count']}")
        if not watch:
            break
        if cycles > 0 and completed >= cycles:
            break
        time.sleep(interval_seconds)


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
    typer.echo("[OK] approval_bridge: airesearcher runtime approve latest")


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


def _autopilot_literature_clients(cache_root: Path) -> dict[str, LiteratureSearchClient]:
    circuit_state_path = cache_root / "source-circuit-breakers.json"
    return {
        "arxiv": ArxivClient(),
        "semantic_scholar": SemanticScholarClient(circuit_state_path=circuit_state_path),
        "openalex": OpenAlexClient(circuit_state_path=circuit_state_path),
    }


def _run_autopilot_cycle(
    *,
    config_path: Path,
    env_path: Path,
    vault: Path,
    cache: Path,
    output_dir: Path,
    state: Path,
    project_id: str,
    demo: str,
    max_queries: int,
    max_results_per_source: int,
    timeout_seconds: int,
    max_tokens: int,
    min_quality_score: float,
    review: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cycle_id = f"cycle-{now.strftime('%Y%m%dT%H%M%SZ')}"
    cycle_dir = output_dir / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)
    literature_clients = _autopilot_literature_clients(cache)
    source_preflight = _run_source_preflight_gate(
        clients=literature_clients,
        cycle_dir=cycle_dir,
        vault=vault,
        project_id=project_id,
        cycle_id=cycle_id,
    )
    if bool(source_preflight["blocked"]):
        followup_records = _issue_followup_records(vault, project_id)
        _merge_scheduler_state(state, followup_records)
        blocked_summary: dict[str, Any] = {
            "cycle_id": cycle_id,
            "status": "blocked",
            "started_at": now.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "vault": vault.as_posix(),
            "cache": cache.as_posix(),
            "source_preflight": source_preflight,
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
    candidate = _autopilot_candidate_from_literature(
        literature_report,
        project_id=project_id,
        demo=demo,
        now=now,
    )
    candidate_path = cycle_dir / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")

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

    inspiration_report = run_inspiration_refresh(
        vault_root=vault,
        queries=_autopilot_inspiration_queries(candidate, demo=demo),
        config=InspirationRefreshConfig(
            max_queries=max_queries,
            max_results_per_source=max_results_per_source,
        ),
    )

    demo_result = run_scientistbench_demo(
        demo=demo,
        output_dir=cycle_dir / "demo",
        timeout_seconds=timeout_seconds,
    )
    review_result = _run_autopilot_review(
        enabled=review,
        config_path=config_path,
        env_path=env_path,
        vault=vault,
        project_id=project_id,
        source_task_id="autopilot",
        cycle_dir=cycle_dir,
        report_path=Path(demo_result.report_path),
        evidence_paths=[
            Path(demo_result.validation_json_path),
            Path(demo_result.evidence_map_path),
            Path(demo_result.run_record_path),
        ],
        max_tokens=max_tokens,
        min_quality_score=min_quality_score,
    )
    reproduction_check = _run_cycle_reproduction_check(
        cycle_dir=cycle_dir,
        demo=demo,
        timeout_seconds=timeout_seconds,
    )

    summary: dict[str, Any] = {
        "cycle_id": cycle_id,
        "started_at": now.isoformat(),
        "completed_at": None,
        "project_id": project_id,
        "vault": vault.as_posix(),
        "cache": cache.as_posix(),
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
        "inspiration": {
            "query_count": len(getattr(inspiration_report, "queries", ())),
            "fetches": _serialise_inspiration_fetches(
                getattr(inspiration_report, "fetches", ())
            ),
            "item_count": len(getattr(inspiration_report, "items", ())),
            "summary_path": _path_text(getattr(inspiration_report, "summary_path", None)),
            "evidence_policy": "dataset/community/news signals only; not scholarly evidence",
        },
        "demo": {
            "demo": demo_result.demo,
            "run_id": demo_result.run_id,
            "experiment_dir": Path(demo_result.experiment_dir).as_posix(),
            "report_path": Path(demo_result.report_path).as_posix(),
            "validation_json_path": Path(demo_result.validation_json_path).as_posix(),
            "evidence_map_path": Path(demo_result.evidence_map_path).as_posix(),
        },
        "review": review_result,
        "reproduction_check": reproduction_check,
        "followups": {
            "state_path": state.as_posix(),
            "task_count": 0,
            "tasks": [],
        },
    }
    summary_path = cycle_dir / "cycle-summary.json"
    summary["summary_path"] = summary_path.as_posix()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    publication_audit = audit_publication_quality(
        cycle_summary_path=summary_path,
        target="ccf-b",
        output_dir=cycle_dir,
        vault_root=vault,
        project_id=project_id,
    )
    summary["publication_audit"] = publication_audit.to_dict()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    paper_build = build_latex_paper_from_markdown(
        markdown_path=Path(demo_result.report_path),
        output_dir=cycle_dir / "paper-build",
        template_id="generic-article-one-column",
        vault_root=vault,
        project_id=project_id,
    )
    summary["paper_build"] = paper_build.to_dict()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    evidence_gate = run_evidence_gate(
        cycle_summary_path=summary_path,
        output_dir=cycle_dir / "evidence-gate",
        vault_root=vault,
        project_id=project_id,
    )
    summary["evidence_gate"] = evidence_gate.to_dict()

    followup_records = _issue_followup_records(vault, project_id)
    _merge_scheduler_state(state, followup_records)
    summary["followups"] = {
        "state_path": state.as_posix(),
        "task_count": len(followup_records),
        "tasks": followup_records,
    }
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


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
    ]
    blocked = bool(blocked_sources)
    report: dict[str, Any] = {
        "verdict": "blocked" if blocked else "pass",
        "blocked": blocked,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "blocked_sources": blocked_sources,
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
            "",
        ]
    )
    return "\n".join(lines)


def _autopilot_literature_seed_queries(demo: str) -> tuple[str, ...]:
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
    seed = documents[0]
    seed_title = str(getattr(seed, "title", "retrieved literature")).strip()
    seed_uri = str(getattr(seed, "source_uri", seed_title)).strip()
    seed_id = str(getattr(seed, "id", seed_uri)).strip()
    candidate_id = f"autopilot_{project_id}_{now.strftime('%Y%m%d%H%M%S')}"
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
            evidence_refs=[seed_id, seed_uri],
            related_document_ids=[seed_id],
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
            evidence_refs=[seed_id, seed_uri],
            related_document_ids=[seed_id],
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
            evidence_refs=[seed_id, seed_uri],
            related_document_ids=[seed_id],
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
        evidence_refs=[seed_id, seed_uri],
        related_document_ids=[seed_id],
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
    max_tokens: int,
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
    result: dict[str, Any] = {
        "status": "passed" if passed else "failed",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "command": command,
        "timeout_seconds": timeout,
        "exit_code": exit_code,
        "output_dir": reproduction_output_dir.as_posix(),
        "run_record_paths": [path.as_posix() for path in run_records],
        "validation_json_paths": [path.as_posix() for path in validation_reports],
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "error": error,
    }
    json_path = check_dir / "reproduction-check.json"
    markdown_path = check_dir / "reproduction-check.md"
    result["json_path"] = json_path.as_posix()
    result["markdown_path"] = markdown_path.as_posix()
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
        return path.as_posix()
    if isinstance(path, str):
        return Path(path).as_posix()
    return str(path)


def _serve_command_text(
    *,
    project_id: str,
    demo: str,
    permission_mode: RuntimePermissionMode,
    review: bool,
) -> str:
    review_flag = "--review" if review else "--no-review"
    return (
        "airesearcher serve "
        f"--permission-mode {permission_mode.value} "
        f"--project-id {project_id} "
        f"--demo {demo} "
        f"{review_flag}"
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


def _channel_values(
    *,
    enabled: bool,
    channel_name: str,
    webhook_url: str | None,
    app_id: str | None,
    app_secret: str | None,
    non_interactive: bool,
) -> dict[str, str | None]:
    if not enabled:
        return {"webhook_url": None, "app_id": None, "app_secret": None}
    values = {
        "webhook_url": webhook_url,
        "app_id": app_id,
        "app_secret": app_secret,
    }
    if non_interactive:
        if not values["webhook_url"] and not (values["app_id"] and values["app_secret"]):
            msg = (
                f"{channel_name} requires --{channel_name.lower()}-webhook-url or both "
                f"--{channel_name.lower()}-app-id and --{channel_name.lower()}-app-secret"
            )
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
    if not values["webhook_url"] and not (values["app_id"] and values["app_secret"]):
        msg = f"{channel_name} channel needs a webhook URL or app ID plus app secret"
        raise typer.BadParameter(msg)
    return values


def _merge_env_file(env_path: Path, values: dict[str, str | None]) -> None:
    existing = _read_env_file(env_path)
    for key, value in values.items():
        if value is not None:
            existing[key] = value
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


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
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
