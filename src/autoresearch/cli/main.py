"""Minimal Typer CLI for the AI-Researcher Phase 0 scaffold."""

import json
import os
import re
import shutil
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
from autoresearch.schemas import CandidateStatus, ResearchCandidate, ResearchPlan, ValidationStatus

app = typer.Typer(
    help="AI-Researcher command line interface.",
    no_args_is_help=True,
)
slash_app = typer.Typer(help="Manage project slash command templates.")
scheduler_state_app = typer.Typer(help="Manage local scheduler state records.")
runtime_app = typer.Typer(help="Manage always-on runtime approvals.")
sessions_app = typer.Typer(help="Coordinate concurrent agent file claims.")
channels_app = typer.Typer(help="Manage communication channel integration manifests.")
channel_adapters_app = typer.Typer(help="Manage optional messaging channel adapter runbooks.")
openclaw_channels_app = typer.Typer(help="Manage optional upstream OpenClaw plugin runbooks.")
code_agents_app = typer.Typer(help="Manage external code-agent integration manifests.")
ccswitch_code_agents_app = typer.Typer(help="Manage cc-switch / Claude Code backend manifests.")
opencode_code_agents_app = typer.Typer(help="Manage OpenCode direct backend manifests.")
pdf_sources_app = typer.Typer(help="Manage optional PDF retrieval integration manifests.")
scansci_pdf_app = typer.Typer(help="Manage ScanSci PDF source metadata.")
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

DEFAULT_SCHEDULER_STATE_PATH = Path(".airesearcher/scheduler-state.json")
DEFAULT_RUNTIME_APPROVALS_PATH = Path(".airesearcher/runtime-approvals.json")
DEFAULT_AGENT_SESSIONS_PATH = Path(".airesearcher/agent-sessions.json")
PUBLICATION_SEARCH_QUERIES = 4
PUBLICATION_RESULTS_PER_SOURCE = 10
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
WECHAT_QR_SESSION_PATH = ".airesearcher/channels/wechat/session.json"
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
AUTORESEARCH_WECHAT_SESSION_PATH=

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
        "AUTORESEARCH_WECHAT_SESSION_PATH": WECHAT_QR_SESSION_PATH
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
            _run_wechat_qr_setup()


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
            run_wechat_qr_setup=run_wechat_qr_setup,
            feishu=feishu,
            feishu_webhook_url=feishu_webhook_url,
            feishu_app_id=feishu_app_id,
            feishu_app_secret=feishu_app_secret,
            feishu_connection_mode=feishu_connection_mode,
            feishu_home_chat_id=feishu_home_chat_id,
            feishu_allowed_users=feishu_allowed_users,
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
        run_wechat_qr_setup = bool(wizard["run_wechat_qr_setup"])
        feishu = wizard["feishu"]
        feishu_webhook_url = wizard["feishu_webhook_url"]
        feishu_app_id = wizard["feishu_app_id"]
        feishu_app_secret = wizard["feishu_app_secret"]
        feishu_connection_mode = str(wizard["feishu_connection_mode"] or "")
        feishu_home_chat_id = wizard["feishu_home_chat_id"]
        feishu_allowed_users = wizard["feishu_allowed_users"]
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
        run_wechat_qr_setup=run_wechat_qr_setup,
        feishu=feishu,
        feishu_webhook_url=feishu_webhook_url,
        feishu_app_id=feishu_app_id,
        feishu_app_secret=feishu_app_secret,
        feishu_connection_mode=feishu_connection_mode,
        feishu_home_chat_id=feishu_home_chat_id,
        feishu_allowed_users=feishu_allowed_users,
        non_interactive=non_interactive,
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
    typer.echo("[OK] next: airesearcher serve --permission-mode approve-dangerous")
    typer.echo("[OK] deliverables: outputs/<project-id>/")


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
                deliverables_dir=deliverables_dir,
                state=state,
                project_id=project_id,
                demo=demo,
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
                timeout_seconds=timeout_seconds,
                max_tokens=_validate_optional_max_tokens(max_tokens, minimum=256),
                min_quality_score=min_quality_score,
                review=review,
                paper_template_id=paper_template_id,
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
        _echo_research_plan_status(summary)
        typer.echo(f"[OK] review_status: {summary['review']['status']}")
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
        paper_template_id=paper_template_id,
        push_inspiration=push_inspiration,
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
                deliverables_dir=deliverables_dir,
                state=state,
                project_id=project_id,
                demo=demo,
                max_queries=max_queries,
                max_results_per_source=max_results_per_source,
                timeout_seconds=timeout_seconds,
                max_tokens=_validate_optional_max_tokens(max_tokens, minimum=256),
                min_quality_score=min_quality_score,
                review=review,
                paper_template_id=paper_template_id,
                push_inspiration=push_inspiration,
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
        _echo_research_plan_status(summary)
        typer.echo(f"[OK] review_status: {summary['review']['status']}")
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
    typer.echo("[OK] approval_bridge: airesearcher runtime approve latest")


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
    project_id: str,
    demo: str,
    max_queries: int,
    max_results_per_source: int,
    timeout_seconds: int,
    max_tokens: int | None,
    min_quality_score: float,
    review: bool,
    paper_template_id: str,
    push_inspiration: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cycle_id = f"cycle-{now.strftime('%Y%m%dT%H%M%SZ')}"
    cycle_dir = output_dir / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)
    _load_optional_env(env_path)
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
    if (
        not research_plan_artifact.audit.passed
        or research_plan_artifact.compile_status != "compiled"
    ):
        followup_records = _issue_followup_records(vault, project_id)
        _merge_scheduler_state(state, followup_records)
        blocked_summary = {
            "cycle_id": cycle_id,
            "status": "blocked",
            "blocked_reason": "research_plan_gate",
            "started_at": now.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
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
            "research_plan": research_plan_payload,
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

    demo_result = run_scientistbench_demo(
        demo=demo,
        output_dir=cycle_dir / "demo",
        timeout_seconds=timeout_seconds,
    )
    reproduction_check = _run_cycle_reproduction_check(
        cycle_dir=cycle_dir,
        demo=demo,
        timeout_seconds=timeout_seconds,
    )
    citations = _generate_cycle_citations(
        literature_report=literature_report,
        cycle_dir=cycle_dir,
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
    summary_path = cycle_dir / "cycle-summary.json"
    summary["summary_path"] = summary_path.as_posix()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    related_work_inspection = inspect_related_work(
        cycle_summary_path=summary_path,
        output_dir=cycle_dir / "related-work",
    )
    summary["related_work_inspection"] = related_work_inspection.to_dict()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    paper_manuscript = compose_publication_manuscript(
        cycle_summary_path=summary_path,
        output_dir=cycle_dir / "paper-manuscript",
        vault_root=vault,
        project_id=project_id,
    )
    summary["paper_manuscript"] = paper_manuscript.to_dict()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    paper_build = build_latex_paper_from_markdown(
        markdown_path=Path(paper_manuscript.markdown_path),
        output_dir=cycle_dir / "paper-build",
        template_id=paper_template_id,
        vault_root=vault,
        project_id=project_id,
    )
    summary["paper_build"] = paper_build.to_dict()
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
        "candidate": summary["candidate"],
        "literature": summary["literature"],
        "similarity": summary["similarity"],
        "research_plan": summary["research_plan"],
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
        paper_build.to_dict().get("json_path"),
        paper_build.to_dict().get("markdown_path"),
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
    summary["deliverables"] = _export_cycle_deliverables(
        summary=summary,
        summary_path=summary_path,
        output_root=deliverables_dir,
        project_id=project_id,
    )
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
    locator_match = re.search(
        r"(doi:\S+|https?://[^\s.]+|source URL recorded in artifact)",
        tail,
    )
    if locator_match is not None:
        locator = locator_match.group(1).rstrip(".")
    return tail.rstrip(".").strip(), locator


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


def _validate_optional_max_tokens(value: int | None, *, minimum: int) -> int | None:
    if value is None:
        return None
    if value < minimum:
        msg = f"--max-tokens must be at least {minimum} when provided"
        raise typer.BadParameter(msg)
    return value


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


def _echo_research_plan_status(summary: Mapping[str, object]) -> None:
    research_plan = summary.get("research_plan")
    if not isinstance(research_plan, Mapping):
        return
    plan_audit = research_plan.get("audit")
    verdict = plan_audit.get("verdict") if isinstance(plan_audit, Mapping) else "unknown"
    prefix = "[OK]" if verdict == "passed" else "[BLOCKED]"
    typer.echo(f"{prefix} research_plan: {verdict}")


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
    run_wechat_qr_setup: bool | None,
    feishu: bool | None,
    feishu_webhook_url: str | None,
    feishu_app_id: str | None,
    feishu_app_secret: str | None,
    feishu_connection_mode: str | None,
    feishu_home_chat_id: str | None,
    feishu_allowed_users: str | None,
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
        home_chat_id=None,
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
        "run_wechat_qr_setup": wechat_values["run_qr_setup"],
        "feishu": feishu_values["enabled"],
        "feishu_webhook_url": feishu_values["webhook_url"],
        "feishu_app_id": feishu_values["app_id"],
        "feishu_app_secret": feishu_values["app_secret"],
        "feishu_connection_mode": feishu_values["connection_mode"],
        "feishu_home_chat_id": feishu_values["home_chat_id"],
        "feishu_allowed_users": feishu_values["allowed_users"],
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
                "home_chat_id": None,
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
    for line in agent_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^### \d{4}-\d{2}-\d{2}", line):
            if current:
                entries.append(current)
            current = [line.removeprefix("### ").strip()]
            continue
        if current and (
            line.startswith("- Request:")
            or line.startswith("- Summary:")
            or line.startswith("- Verification:")
            or line.startswith("- Problems:")
            or line.startswith("- Follow-up:")
        ):
            current.append(line.strip())
    if current:
        entries.append(current)
    if not entries:
        return "Agent.md exists, but no change-log entries were found."
    rendered: list[str] = []
    for entry in entries[:max_entries]:
        rendered.append("\n".join(entry[:7]))
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
        table.add_column(column)
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
    table.add_column("stage")
    table.add_column("status")
    table.add_column("evidence")
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
    evidence_name = summary_path.name
    rows = [
        ("source discovery", _nested_status(payload, "source_preflight"), evidence_name),
        ("similarity check", _nested_status(payload, "similarity"), evidence_name),
        ("experiment", _nested_status(payload, "demo"), evidence_name),
        ("review", _nested_status(payload, "review"), evidence_name),
        ("publication audit", _nested_status(payload, "publication_audit"), evidence_name),
        ("paper build", _nested_status(payload, "paper_build"), evidence_name),
        ("evidence gate", _nested_status(payload, "evidence_gate"), evidence_name),
    ]
    for stage, status, evidence in rows:
        table.add_row(stage, status, evidence)
    return table


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
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
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
        lines.append(f"{path.name} [{marker}]: {_relative_path_text(path)} ({size} bytes)")
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
        data = json.loads(path.read_text(encoding="utf-8"))
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


def _run_wechat_qr_setup() -> None:
    try:
        result = subprocess.run(
            ["npx", "-y", "@tencent-weixin/openclaw-weixin-cli", "install"],
            check=False,
        )
    except OSError as exc:
        typer.echo(f"[FAIL] wechat_qr_setup: {exc}", err=True)
        raise typer.Exit(1) from exc
    if result.returncode != 0:
        typer.echo(f"[FAIL] wechat_qr_setup exited {result.returncode}", err=True)
        raise typer.Exit(result.returncode)
    typer.echo("[OK] wechat_qr_setup: completed")


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
