import json
import os
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import autoresearch.cli.main as cli_main
from autoresearch import __version__
from autoresearch.cli.main import app
from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    SuccessfulPatternExample,
    extract_reusable_skill_card,
)
from autoresearch.llm import LLMReviewResult, LLMSmokeResult
from autoresearch.schemas import ResearchCandidate


def test_version_command_prints_package_version() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_doctor_command_checks_local_scaffold() -> None:
    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "[OK] python >= 3.10" in result.stdout
    assert "[OK] config parser" in result.stdout
    assert "[OK] knowledge vault" in result.stdout


def test_init_demo_creates_readme_and_config(tmp_path: Path) -> None:
    demo_path = tmp_path / "demo"

    result = CliRunner().invoke(app, ["init-demo", "--path", str(demo_path)])

    assert result.exit_code == 0
    assert (demo_path / "README.md").is_file()
    assert (demo_path / "config.yaml").is_file()


def test_obsidian_setup_creates_vault_assets_and_local_snippet(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"

    result = CliRunner().invoke(
        app,
        [
            "obsidian-setup",
            "--vault",
            str(vault_root),
            "--project-id",
            "project_1",
            "--write-local-snippet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] vault_home:" in result.stdout
    assert "[OK] templates: 6" in result.stdout
    assert (vault_root / "Home.md").is_file()
    assert (vault_root / "_system" / "dashboards" / "research-loop.md").is_file()
    assert (vault_root / "_system" / "plugins" / "recommended-plugins.md").is_file()
    assert (vault_root / "_system" / "templates" / "skill-card.md").is_file()
    assert (vault_root / ".obsidian" / "snippets" / "ai-researcher.css").is_file()
    assert "enabledCssSnippets" in (vault_root / ".obsidian" / "appearance.json").read_text(
        encoding="utf-8"
    )


def test_skill_evolve_creates_bounded_candidate_from_issue_ref(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    parent = extract_reusable_skill_card(
        vault_root=vault_root,
        name="Evidence-first demo review",
        examples=(
            SuccessfulPatternExample(
                project_id="project_a",
                experience_ref="projects/project_a/experience/review_a",
                summary="Review passed after adding run record evidence.",
                trigger_conditions=("demo report review",),
                actions=("attach run record evidence",),
                success_metrics=("review_quality_score >= 0.85",),
            ),
            SuccessfulPatternExample(
                project_id="project_b",
                experience_ref="projects/project_b/experience/review_b",
                summary="Unsupported reproduction claims were blocked.",
                trigger_conditions=("demo report review",),
                actions=("attach run record evidence",),
                success_metrics=("unsupported_claims = 0",),
            ),
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "skill-evolve",
            "--vault",
            str(vault_root),
            "--parent-skill-id",
            parent.skill_id,
            "--change-summary",
            "Require run-record evidence before promoting a demo report.",
            "--issue-ref",
            "projects/project_a/issues/llm_review_missing_evidence",
            "--proposed-action",
            "attach run record before live review",
            "--validation-check",
            "real LLM review score >= 0.85",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] candidate_skill_id:" in result.stdout
    assert "[OK] rejected_edit_buffer:" in result.stdout
    assert list((vault_root / "exploration" / "skills" / "candidates").glob("*.md"))


def test_deploy_setup_writes_provider_config_and_env_without_committing_secret(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    env_example_path = tmp_path / ".env.example"

    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--wechat",
            "--wechat-webhook-url",
            "https://wechat.example.test/hook",
            "--feishu",
            "--feishu-webhook-url",
            "https://feishu.example.test/hook",
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    config = ConfigParser().parse_file(config_path)
    assert isinstance(config, SystemConfig)
    assert config.deployment.llm.base_url == "https://llm.example.test/v1"
    assert config.deployment.llm.model_name == "research-model"
    assert config.deployment.llm.api_key_env == "AUTORESEARCH_LLM_API_KEY"
    assert config.deployment.wechat.enabled is True
    assert config.deployment.feishu.enabled is True

    config_text = config_path.read_text(encoding="utf-8")
    env_text = env_path.read_text(encoding="utf-8")
    env_example_text = env_example_path.read_text(encoding="utf-8")
    assert "sk-test" not in config_text
    assert "AUTORESEARCH_LLM_API_KEY=sk-test" in env_text
    assert "AUTORESEARCH_WECHAT_WEBHOOK_URL=https://wechat.example.test/hook" in env_text
    assert "AUTORESEARCH_FEISHU_WEBHOOK_URL=https://feishu.example.test/hook" in env_text
    assert "env template created" in result.stdout
    assert "AUTORESEARCH_LLM_API_KEY=" in env_example_text
    assert "SEMANTIC_SCHOLAR_API_KEY=" in env_example_text
    assert "SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS=" in env_example_text
    assert "SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS=" in env_example_text
    assert "sk-test" not in env_example_text


def test_deploy_setup_keeps_existing_env_example_template(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    env_example_path = tmp_path / ".env.example"
    env_example_path.write_text("CUSTOM_TEMPLATE=1\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--no-wechat",
            "--no-feishu",
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert env_path.is_file()
    assert env_example_path.read_text(encoding="utf-8") == "CUSTOM_TEMPLATE=1\n"
    assert "env template ready" in result.stdout


def test_deploy_setup_requires_enabled_channel_credentials(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(tmp_path / ".env"),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--wechat",
            "--non-interactive",
        ],
    )

    assert result.exit_code != 0
    assert "WeChat requires" in result.output


def test_slash_commands_init_and_list_project_templates(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["slash-commands", "init", "--directory", str(commands_dir)],
    )
    list_result = runner.invoke(
        app,
        ["slash-commands", "list", "--directory", str(commands_dir)],
    )

    assert init_result.exit_code == 0, init_result.output
    autopilot_template = (commands_dir / "research" / "autopilot.toml").read_text(
        encoding="utf-8"
    )
    assert (commands_dir / "research" / "refresh-literature.toml").is_file()
    assert (commands_dir / "research" / "similarity-check.toml").is_file()
    assert (commands_dir / "research" / "run-demo.toml").is_file()
    assert (commands_dir / "research" / "autopilot.toml").is_file()
    assert (commands_dir / "research" / "serve.toml").is_file()
    assert (commands_dir / "research" / "publication-audit.toml").is_file()
    assert (commands_dir / "research" / "approve.toml").is_file()
    assert (commands_dir / "research" / "openclaw-channels.toml").is_file()
    assert (commands_dir / "research" / "code-agent-backends.toml").is_file()
    assert (commands_dir / "research" / "obsidian-setup.toml").is_file()
    assert (commands_dir / "research" / "skill-evolve.toml").is_file()
    assert (commands_dir / "research" / "issue-followups.toml").is_file()
    assert (commands_dir / "research" / "status.toml").is_file()
    assert list_result.exit_code == 0, list_result.output
    assert "/research:autopilot" in list_result.stdout
    assert "/research:serve" in list_result.stdout
    assert "/research:publication-audit" in list_result.stdout
    assert "/research:approve" in list_result.stdout
    assert "/research:openclaw-channels" in list_result.stdout
    assert "/research:code-agent-backends" in list_result.stdout
    assert "/research:obsidian-setup" in list_result.stdout
    assert "/research:skill-evolve" in list_result.stdout
    assert "/research:refresh-literature" in list_result.stdout
    assert "/research:issue-followups" in list_result.stdout
    assert "/research:similarity-check" in list_result.stdout
    assert "airesearcher autopilot" in autopilot_template
    assert "autoresearch autopilot" not in autopilot_template
    assert "airesearcher serve" in (
        commands_dir / "research" / "serve.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher runtime approve" in (
        commands_dir / "research" / "approve.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher publication-audit" in (
        commands_dir / "research" / "publication-audit.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher channels openclaw init" in (
        commands_dir / "research" / "openclaw-channels.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher code-agents cc-switch init" in (
        commands_dir / "research" / "code-agent-backends.toml"
    ).read_text(encoding="utf-8")


def test_publication_audit_command_reports_and_can_fail_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "cycle-summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_audit(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            verdict=SimpleNamespace(value="fail"),
            publishable=False,
            score=0.25,
            markdown_path="audit.md",
            output_path="audit.json",
            vault_review_path=None,
            vault_issue_path="vault/issues/publication-audit.md",
        )

    monkeypatch.setattr(cli_main, "audit_publication_quality", fake_audit)

    ok_result = CliRunner().invoke(
        app,
        [
            "publication-audit",
            str(summary_path),
            "--target",
            "ccf-b",
            "--no-fail-on-not-publishable",
        ],
    )
    fail_result = CliRunner().invoke(app, ["publication-audit", str(summary_path)])

    assert ok_result.exit_code == 0, ok_result.output
    assert "[OK] publication_audit: fail" in ok_result.stdout
    assert "[OK] vault_issue: vault/issues/publication-audit.md" in ok_result.stdout
    assert fail_result.exit_code == 1
    assert captured["cycle_summary_path"] == summary_path
    assert captured["target"] == "ccf-b"


def test_literature_refresh_command_reports_source_backed_documents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "vault" / "exploration" / "topics" / "summary.md"
    env_path = tmp_path / ".env"
    env_path.write_text("SEMANTIC_SCHOLAR_API_KEY=semantic-test\n", encoding="utf-8")
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    captured: dict[str, object] = {}

    def fake_refresh(**kwargs):
        captured.update(kwargs)
        assert os.getenv("SEMANTIC_SCHOLAR_API_KEY") == "semantic-test"
        return SimpleNamespace(
            queries=(object(),),
            fetches=(
                SimpleNamespace(
                    source="arxiv",
                    query="machine learning benchmark",
                    paper_count=1,
                    cache_hit=False,
                    error=None,
                ),
            ),
            documents=(object(),),
            summary_path=summary_path,
        )

    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_refresh)

    result = CliRunner().invoke(
        app,
        [
            "literature-refresh",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--max-queries",
            "1",
            "--max-results-per-source",
            "1",
            "--env-path",
            str(env_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[FETCH] source=arxiv papers=1" in result.stdout
    assert "[OK] documents: 1" in result.stdout
    assert captured["vault_root"] == tmp_path / "vault"
    assert captured["cache_root"] == tmp_path / "cache"


def test_similarity_check_command_loads_candidate_and_links_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate = ResearchCandidate(
        id="candidate_cli_similarity",
        title="Machine Learning Benchmark Evidence",
        description="Check adjacent work before project start.",
        research_gap="Benchmark evidence needs source-backed checks.",
        novelty_score=0.6,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["seed"],
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    summary_path = tmp_path / "vault" / "exploration" / "topics" / "similarity.md"
    project_link = tmp_path / "vault" / "projects" / "project_1" / "knowledge" / "similarity.md"
    captured: dict[str, object] = {}

    def fake_similarity(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            candidate_id=candidate.id,
            queries=(object(),),
            fetches=(
                SimpleNamespace(
                    source="semantic_scholar",
                    query="benchmark evidence",
                    paper_count=1,
                    cache_hit=False,
                    error=None,
                ),
            ),
            findings=(object(),),
            summary_path=summary_path,
        )

    def fake_link(**kwargs):
        captured["link_kwargs"] = kwargs
        return project_link

    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity)
    monkeypatch.setattr(cli_main, "link_similarity_report_to_project", fake_link)

    result = CliRunner().invoke(
        app,
        [
            "similarity-check",
            "--candidate-file",
            str(candidate_path),
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--max-queries",
            "1",
            "--max-results-per-source",
            "1",
            "--project-id",
            "project_1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[FETCH] source=semantic_scholar papers=1" in result.stdout
    assert "[OK] candidate: candidate_cli_similarity" in result.stdout
    assert "[OK] project_link:" in result.stdout
    assert captured["candidate"] == candidate
    assert captured["vault_root"] == tmp_path / "vault"
    assert captured["cache_root"] == tmp_path / "cache"
    assert captured["link_kwargs"]["project_id"] == "project_1"


def test_similarity_check_accepts_windows_utf8_bom_candidate_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate = ResearchCandidate(
        id="candidate_cli_bom",
        title="Machine Learning Benchmark Evidence",
        description="Check adjacent work before project start.",
        research_gap="Benchmark evidence needs source-backed checks.",
        novelty_score=0.6,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["seed"],
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8-sig")

    def fake_similarity(**kwargs):
        assert kwargs["candidate"] == candidate
        return SimpleNamespace(
            candidate_id=candidate.id,
            queries=(object(),),
            fetches=(
                SimpleNamespace(
                    source="arxiv",
                    query="benchmark evidence",
                    paper_count=1,
                    cache_hit=False,
                    error=None,
                ),
            ),
            findings=(object(),),
            summary_path=tmp_path / "summary.md",
        )

    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity)

    result = CliRunner().invoke(
        app,
        [
            "similarity-check",
            "--candidate-file",
            str(candidate_path),
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--max-queries",
            "1",
            "--max-results-per-source",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] candidate: candidate_cli_bom" in result.stdout


def test_run_demo_command_creates_end_to_end_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "mvp-demo"

    result = CliRunner().invoke(
        app,
        [
            "run-demo",
            "--demo",
            "tabular_baseline",
            "--output-dir",
            str(output_dir),
            "--timeout-seconds",
            "5",
        ],
    )

    experiment_dir = output_dir / "tabular-baseline"
    evidence_map_path = experiment_dir / "evidence" / "evidence-map.json"
    report_path = experiment_dir / "report" / "report.md"

    assert result.exit_code == 0
    assert "[OK] demo: tabular_baseline" in result.stdout
    assert (experiment_dir / "run.py").is_file()
    assert (experiment_dir / "logs" / "run.log").is_file()
    assert (experiment_dir / "metrics.json").is_file()
    assert (experiment_dir / "validation" / "validation-report.json").is_file()
    assert (experiment_dir / "validation" / "validation-report.md").is_file()
    assert evidence_map_path.is_file()
    assert report_path.is_file()

    evidence_map = json.loads(evidence_map_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    assert evidence_map["task_id"] == "tabular_baseline"
    assert evidence_map["evidence_edges"]
    assert "## Reproducibility" in report
    assert "## Results" in report


def test_autopilot_command_runs_one_non_review_cycle(tmp_path: Path, monkeypatch) -> None:
    literature_summary = tmp_path / "vault" / "exploration" / "literature.md"
    similarity_summary = tmp_path / "vault" / "exploration" / "similarity.md"
    project_similarity = tmp_path / "vault" / "projects" / "project_1" / "knowledge" / "similarity.md"
    for path in (literature_summary, similarity_summary, project_similarity):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("summary", encoding="utf-8")

    seed_document = SimpleNamespace(
        id="doc_seed",
        title="Evidence Graphs for Autonomous Research",
        source_uri="https://example.test/paper",
    )
    fetch = SimpleNamespace(
        source="semantic_scholar",
        query="evidence graph autonomous research",
        paper_count=1,
        cache_hit=False,
        rate_limit_seconds=3.0,
        error=None,
    )

    def fake_literature_refresh(**kwargs: object) -> SimpleNamespace:
        config = kwargs["config"]
        assert config.max_queries == cli_main.PUBLICATION_SEARCH_QUERIES
        assert config.max_results_per_source == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        return SimpleNamespace(
            queries=(SimpleNamespace(text="evidence graph autonomous research"),),
            fetches=(fetch,),
            documents=(seed_document,),
            summary_path=literature_summary,
        )

    def fake_similarity_check(**kwargs: object) -> SimpleNamespace:
        config = kwargs["config"]
        assert config.max_queries == cli_main.PUBLICATION_SEARCH_QUERIES
        assert config.max_results_per_source == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        return SimpleNamespace(
            fetches=(fetch,),
            findings=(SimpleNamespace(source_uri="https://example.test/paper"),),
            summary_path=similarity_summary,
        )

    def fake_link_similarity_report_to_project(**_kwargs: object) -> Path:
        return project_similarity

    def fake_demo(**kwargs: object) -> SimpleNamespace:
        output_dir = Path(kwargs["output_dir"])
        experiment_dir = output_dir / "tabular-baseline"
        report_path = experiment_dir / "report" / "report.md"
        validation_path = experiment_dir / "validation" / "validation-report.json"
        evidence_path = experiment_dir / "evidence" / "evidence-map.json"
        run_record_path = experiment_dir / "run" / "run-record.json"
        for path in (report_path, validation_path, evidence_path, run_record_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            demo="tabular_baseline",
            experiment_dir=experiment_dir,
            report_path=report_path,
            evidence_map_path=evidence_path,
            run_record_path=run_record_path,
            validation_json_path=validation_path,
            validation_markdown_path=experiment_dir / "validation" / "validation-report.md",
            run_id="run_autopilot_test",
        )

    def fake_publication_audit(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            to_dict=lambda: {
                "verdict": "needs_revision",
                "publishable": False,
                "score": 0.5,
            }
        )

    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_literature_refresh)
    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity_check)
    monkeypatch.setattr(cli_main, "link_similarity_report_to_project", fake_link_similarity_report_to_project)
    monkeypatch.setattr(cli_main, "run_scientistbench_demo", fake_demo)
    monkeypatch.setattr(cli_main, "audit_publication_quality", fake_publication_audit)

    output_dir = tmp_path / "runs" / "autopilot"
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--output-dir",
            str(output_dir),
            "--state",
            str(state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] autopilot_cycle:" in result.stdout
    assert "[OK] review_status: skipped" in result.stdout
    assert "[OK] publication_audit: needs_revision" in result.stdout
    summaries = list(output_dir.glob("cycle-*/cycle-summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert payload["candidate"]["related_document_ids"] == ["doc_seed"]
    assert payload["literature"]["document_count"] == 1
    assert payload["similarity"]["finding_count"] == 1
    assert payload["demo"]["run_id"] == "run_autopilot_test"
    assert payload["publication_audit"]["verdict"] == "needs_revision"
    assert json.loads(state.read_text(encoding="utf-8")) == {"tasks": []}


def test_autopilot_command_reports_empty_literature_result(tmp_path: Path, monkeypatch) -> None:
    literature_summary = tmp_path / "vault" / "exploration" / "literature.md"
    literature_summary.parent.mkdir(parents=True, exist_ok=True)
    literature_summary.write_text("summary", encoding="utf-8")

    def fake_literature_refresh(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            queries=(SimpleNamespace(text="evidence graph autonomous research"),),
            fetches=(),
            documents=(),
            summary_path=literature_summary,
        )

    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_literature_refresh)

    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--output-dir",
            str(tmp_path / "runs" / "autopilot"),
            "--state",
            str(tmp_path / ".airesearcher" / "scheduler-state.json"),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 1
    assert "[FAIL] autopilot_cycle: autopilot requires at least one retrieved literature document" in result.output


def test_serve_queues_dangerous_action_until_runtime_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approvals_state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    runner = CliRunner()

    def fail_cycle(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("serve should not run before approval")

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fail_cycle)
    pending_result = runner.invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "approve-dangerous",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert pending_result.exit_code == 2, pending_result.output
    assert "[WAITING] approval_required:" in pending_result.stdout
    payload = json.loads(approvals_state.read_text(encoding="utf-8"))
    request_id = payload["requests"][0]["request_id"]
    assert payload["requests"][0]["status"] == "pending"
    assert payload["requests"][0]["action_id"] == "serve:autopilot-cycle:project_1:tabular_baseline"

    approve_result = runner.invoke(
        app,
        [
            "runtime",
            "approve",
            request_id,
            "--state",
            str(approvals_state),
            "--approved-by",
            "tester",
        ],
    )

    assert approve_result.exit_code == 0, approve_result.output
    assert f"[OK] approved: {request_id}" in approve_result.stdout

    def fake_cycle(**kwargs: object) -> dict[str, object]:
        assert kwargs["project_id"] == "project_1"
        assert kwargs["review"] is False
        return {
            "cycle_id": "cycle-test",
            "summary_path": "runs/autopilot/cycle-test/cycle-summary.json",
            "review": {"status": "skipped"},
            "followups": {"task_count": 0},
        }

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fake_cycle)
    allowed_result = runner.invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "approve-dangerous",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert allowed_result.exit_code == 0, allowed_result.output
    assert "[OK] serve_cycle: cycle-test" in allowed_result.stdout


def test_serve_allow_all_runs_without_approval_state(tmp_path: Path, monkeypatch) -> None:
    approvals_state = tmp_path / ".airesearcher" / "runtime-approvals.json"

    def fake_cycle(**kwargs: object) -> dict[str, object]:
        assert kwargs["project_id"] == "project_1"
        assert kwargs["max_queries"] == cli_main.PUBLICATION_SEARCH_QUERIES
        assert kwargs["max_results_per_source"] == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        return {
            "cycle_id": "cycle-allow-all",
            "summary_path": "runs/autopilot/cycle-allow-all/cycle-summary.json",
            "review": {"status": "skipped"},
            "followups": {"task_count": 0},
        }

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fake_cycle)
    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "allow-all",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] runtime_mode: allow-all" in result.stdout
    assert "[OK] serve_cycle: cycle-allow-all" in result.stdout
    assert not approvals_state.exists()


def test_runtime_list_defaults_to_pending_requests(tmp_path: Path, monkeypatch) -> None:
    approvals_state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    runner = CliRunner()

    def fail_cycle(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("serve should only queue")

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fail_cycle)
    pending_result = runner.invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "approve-dangerous",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )
    list_pending_result = runner.invoke(
        app,
        ["runtime", "list", "--state", str(approvals_state)],
    )
    approve_result = runner.invoke(
        app,
        ["runtime", "approve", "latest", "--state", str(approvals_state)],
    )
    list_after_result = runner.invoke(
        app,
        ["runtime", "list", "--state", str(approvals_state)],
    )
    list_all_result = runner.invoke(
        app,
        ["runtime", "list", "--state", str(approvals_state), "--include-completed"],
    )

    assert pending_result.exit_code == 2, pending_result.output
    assert list_pending_result.exit_code == 0, list_pending_result.output
    assert "[OK] runtime_approval_requests: 1" in list_pending_result.stdout
    assert "[REQUEST] status=pending" in list_pending_result.stdout
    assert approve_result.exit_code == 0, approve_result.output
    assert list_after_result.exit_code == 0, list_after_result.output
    assert "[OK] runtime_approval_requests: 0" in list_after_result.stdout
    assert list_all_result.exit_code == 0, list_all_result.output
    assert "[OK] runtime_approval_requests: 1" in list_all_result.stdout
    assert "[REQUEST] status=approved" in list_all_result.stdout


def test_openclaw_channel_manifest_cli_writes_official_plugin_mounts(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "openclaw" / "channels.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["channels", "openclaw", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["channels", "openclaw", "list"])
    feishu_result = runner.invoke(
        app,
        ["channels", "openclaw", "list", "--channel", "openclaw-lark"],
    )

    assert init_result.exit_code == 0, init_result.output
    assert "[OK] openclaw_channels: 11" in init_result.stdout
    assert "[OK] approval_bridge: airesearcher runtime approve latest" in init_result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    channels = {channel["channel_id"]: channel for channel in payload["channels"]}
    assert channels["feishu"]["package_name"] == "@larksuite/openclaw-lark"
    assert channels["openclaw-weixin"]["package_name"] == "@tencent-weixin/openclaw-weixin"
    assert channels["wecom"]["package_name"] == "@wecom/wecom-openclaw-plugin"
    assert payload["approval_bridge"]["runtime_command"] == (
        "airesearcher serve --permission-mode approve-dangerous"
    )
    assert list_result.exit_code == 0, list_result.output
    assert "[CHANNEL] channel=feishu plugin=openclaw-lark" in list_result.stdout
    assert "[CHANNEL] channel=qqbot plugin=qqbot" in list_result.stdout
    assert feishu_result.exit_code == 0, feishu_result.output
    assert "[OK] openclaw_channels: 1" in feishu_result.stdout
    assert "package=@larksuite/openclaw-lark" in feishu_result.stdout


def test_ccswitch_code_agent_manifest_cli_writes_validation_contract(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "cc-switch" / "code-agent.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["code-agents", "cc-switch", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["code-agents", "cc-switch", "list"])
    backend_result = runner.invoke(
        app,
        [
            "code-agents",
            "cc-switch",
            "list",
            "--backend",
            "claude-code-via-cc-switch",
        ],
    )

    assert init_result.exit_code == 0, init_result.output
    assert "[OK] ccswitch_code_agent_backends: 1" in init_result.stdout
    assert "[OK] validation_owner: AI-Researcher" in init_result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution_contract"]["validation_owner"] == "AI-Researcher"
    assert payload["approval_bridge"]["approve_command"].startswith(
        "airesearcher runtime approve latest"
    )
    assert payload["backends"][0]["runner_command"] == "claude"
    assert list_result.exit_code == 0, list_result.output
    assert "[BACKEND] backend=claude-code-via-cc-switch" in list_result.stdout
    assert "validator=AI-Researcher" in list_result.stdout
    assert backend_result.exit_code == 0, backend_result.output
    assert "[OK] ccswitch_code_agent_backends: 1" in backend_result.stdout


def test_validate_package_command_reports_missing_artifact(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "package_path": "code/run.py",
                        "sha256": "missing-hash",
                    }
                ],
                "run_commands": ["python code/run.py"],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["validate-package", "--manifest", str(manifest_path)],
    )

    assert result.exit_code == 1
    assert "[FAIL] package validation failed" in result.stdout
    assert "artifact_exists" in result.stdout
    assert "code/run.py" in result.stdout


def test_llm_smoke_command_writes_quality_report(tmp_path: Path, monkeypatch) -> None:
    quality = LLMSmokeResult.model_validate(
        {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model_name": "deepseek-v4-flash",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "response_text": '{"status":"ok"}',
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "quality": {
                "score": 1.0,
                "checks": {
                    "non_empty": True,
                    "valid_json": True,
                    "status_ok": True,
                    "summary_present": True,
                    "evidence_policy_present": True,
                    "risks_present": True,
                    "next_steps_present": True,
                    "no_secret_leak": True,
                    "no_fake_urls": True,
                },
                "issues": [],
                "parsed_output": {
                    "status": "ok",
                    "summary": "Unverified research outcomes remain pending verification.",
                    "evidence_policy": "Use source-backed evidence and keep unknowns pending.",
                    "risks": ["missing evidence", "configuration drift"],
                    "next_steps": ["run live literature search", "inspect validation report"],
                },
            },
        }
    )

    def fake_run_llm_smoke_test(**_kwargs: object) -> LLMSmokeResult:
        return quality

    monkeypatch.setattr(cli_main, "run_llm_smoke_test", fake_run_llm_smoke_test)
    output = tmp_path / "llm-smoke.json"

    result = CliRunner().invoke(
        app,
        [
            "llm-smoke",
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(tmp_path / ".env"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] model: deepseek-v4-flash" in result.stdout
    assert "[CHECK] valid_json: pass" in result.stdout
    assert output.is_file()


def test_llm_review_command_writes_local_evidence_report(tmp_path: Path, monkeypatch) -> None:
    subject_path = tmp_path / "report.md"
    evidence_path = tmp_path / "validation.json"
    subject_path.write_text("# Report\n\nClaim backed by validation.", encoding="utf-8")
    evidence_path.write_text('{"status":"passed"}', encoding="utf-8")
    review = LLMReviewResult.model_validate(
        {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model_name": "deepseek-v4-flash",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "subject_path": subject_path.as_posix(),
            "subject_sha256": "sha-subject",
            "evidence": [
                {
                    "evidence_id": "evidence_1",
                    "path": evidence_path.as_posix(),
                    "sha256": "sha-evidence",
                    "excerpt": '{"status":"passed"}',
                }
            ],
            "response_text": '{"verdict":"pass"}',
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "quality": {
                "score": 1.0,
                "checks": {
                    "non_empty": True,
                    "valid_json": True,
                    "verdict_present": True,
                    "summary_present": True,
                    "findings_present": True,
                    "finding_refs_present": True,
                    "finding_refs_known": True,
                    "unsupported_claims_present": True,
                    "next_steps_present": True,
                    "no_secret_leak": True,
                    "no_fake_urls": True,
                },
                "issues": [],
                "parsed_output": {
                    "verdict": "pass",
                    "summary": "The report is grounded in local evidence.",
                    "findings": [
                        {
                            "severity": "info",
                            "claim": "Validation passed.",
                            "evidence_refs": ["evidence_1"],
                        }
                    ],
                    "unsupported_claims": [],
                    "next_steps": ["Keep evidence attached."],
                },
            },
        }
    )

    def fake_review(**_kwargs: object) -> LLMReviewResult:
        return review

    captured_note: dict[str, object] = {}
    vault_note = tmp_path / "vault" / "projects" / "project_1" / "review" / "llm-review.md"

    def fake_write_note(**kwargs: object) -> Path:
        captured_note.update(kwargs)
        return vault_note

    captured_issues: dict[str, object] = {}

    def fake_write_issues(**kwargs: object) -> tuple[Path, ...]:
        captured_issues.update(kwargs)
        return (tmp_path / "vault" / "projects" / "project_1" / "issues" / "issue.md",)

    monkeypatch.setattr(cli_main, "run_llm_evidence_review", fake_review)
    monkeypatch.setattr(cli_main, "write_llm_review_note", fake_write_note)
    monkeypatch.setattr(cli_main, "write_llm_review_issue_notes", fake_write_issues)
    output = tmp_path / "llm-review.json"

    result = CliRunner().invoke(
        app,
        [
            "llm-review",
            "--subject",
            str(subject_path),
            "--evidence",
            str(evidence_path),
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(tmp_path / ".env"),
            "--output",
            str(output),
            "--vault",
            str(tmp_path / "vault"),
            "--project-id",
            "project_1",
            "--source-task-id",
            "44.1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] review_quality_score: 1.000" in result.stdout
    assert "[CHECK] finding_refs_known: pass" in result.stdout
    assert "[VERDICT] pass" in result.stdout
    assert "[OK] vault_review:" in result.stdout
    assert "[OK] vault_issues: 1" in result.stdout
    assert output.is_file()
    assert captured_note["result"] == review
    assert captured_note["vault_root"] == tmp_path / "vault"
    assert captured_note["project_id"] == "project_1"
    assert captured_note["source_task_id"] == "44.1"
    assert captured_issues["result"] == review
    assert captured_issues["review_note_path"] == vault_note


def test_issue_followups_command_lists_open_project_issue_tasks(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    issue_dir = vault_root / "projects" / "project_1" / "issues"
    issue_dir.mkdir(parents=True)
    open_issue = KnowledgeEntry(
        entry_id="llm_review_issue_project_1_abc",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="LLM review issue: missing evidence",
        project_id="project_1",
        related_task_ids=["48.1"],
        body="\n".join(
            [
                "# LLM Review Follow-Up",
                "",
                "- Status: Open",
                "- Issue fingerprint: `abc123def4567890`",
            ]
        ),
    )
    closed_issue = KnowledgeEntry(
        entry_id="closed_issue",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="Closed issue",
        project_id="project_1",
        body="- Status: Closed\n",
    )
    (issue_dir / "open.md").write_text(open_issue.to_markdown(), encoding="utf-8")
    (issue_dir / "closed.md").write_text(closed_issue.to_markdown(), encoding="utf-8")
    output = tmp_path / "followups.json"
    state = tmp_path / ".airesearcher" / "scheduler-state.json"

    result = CliRunner().invoke(
        app,
        [
            "issue-followups",
            "--vault",
            str(vault_root),
            "--project-id",
            "project_1",
            "--output",
            str(output),
            "--state",
            str(state),
        ],
    )
    second_result = CliRunner().invoke(
        app,
        [
            "issue-followups",
            "--vault",
            str(vault_root),
            "--project-id",
            "project_1",
            "--state",
            str(state),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert second_result.exit_code == 0, second_result.stdout
    assert "[OK] issue_followups: 1" in result.stdout
    assert "[OK] state:" in result.stdout
    assert "[TASK] task_id=issue-follow-up-project_1-abc123def4567890" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["tasks"][0]["metadata"]["issue_path"] == "projects/project_1/issues/open.md"
    assert payload["tasks"][0]["metadata"]["related_task_ids"] == ["48.1"]
    state_payload = json.loads(state.read_text(encoding="utf-8"))
    assert len(state_payload["tasks"]) == 1
    assert state_payload["tasks"][0]["task_id"] == "issue-follow-up-project_1-abc123def4567890"
    assert state_payload["tasks"][0]["status"] == "open"


def test_scheduler_state_commands_list_complete_and_remove_tasks(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task_open",
                        "name": "open task",
                        "queued_at": "2026-06-12T09:00:00+00:00",
                        "status": "open",
                        "metadata": {"issue_path": "projects/project_1/issues/open.md"},
                    },
                    {
                        "task_id": "task_done",
                        "name": "done task",
                        "queued_at": "2026-06-12T08:00:00+00:00",
                        "status": "completed",
                        "completed_at": "2026-06-12T08:30:00+00:00",
                        "metadata": {"issue_path": "projects/project_1/issues/done.md"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    list_result = runner.invoke(app, ["scheduler-state", "list", "--state", str(state)])
    list_all_result = runner.invoke(
        app,
        ["scheduler-state", "list", "--state", str(state), "--include-completed"],
    )
    complete_result = runner.invoke(
        app,
        ["scheduler-state", "complete", "task_open", "--state", str(state)],
    )
    missing_complete_result = runner.invoke(
        app,
        ["scheduler-state", "complete", "missing", "--state", str(state)],
    )
    remove_result = runner.invoke(
        app,
        ["scheduler-state", "remove", "task_done", "--state", str(state)],
    )

    assert list_result.exit_code == 0, list_result.stdout
    assert "[OK] scheduler_state_tasks: 1" in list_result.stdout
    assert "task_id=task_open" in list_result.stdout
    assert "task_id=task_done" not in list_result.stdout
    assert list_all_result.exit_code == 0, list_all_result.stdout
    assert "[OK] scheduler_state_tasks: 2" in list_all_result.stdout
    assert complete_result.exit_code == 0, complete_result.stdout
    assert missing_complete_result.exit_code == 1
    assert "task not found: missing" in missing_complete_result.output
    assert remove_result.exit_code == 0, remove_result.stdout

    payload = json.loads(state.read_text(encoding="utf-8"))
    assert [task["task_id"] for task in payload["tasks"]] == ["task_open"]
    assert payload["tasks"][0]["status"] == "completed"
    assert "completed_at" in payload["tasks"][0]


def test_issue_followups_state_merge_preserves_completed_tasks(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    issue_dir = vault_root / "projects" / "project_1" / "issues"
    issue_dir.mkdir(parents=True)
    issue = KnowledgeEntry(
        entry_id="llm_review_issue_project_1_abc",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="LLM review issue: missing evidence",
        project_id="project_1",
        body="- Status: Open\n- Issue fingerprint: `abc123def4567890`\n",
    )
    (issue_dir / "open.md").write_text(issue.to_markdown(), encoding="utf-8")
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    runner = CliRunner()
    args = [
        "issue-followups",
        "--vault",
        str(vault_root),
        "--project-id",
        "project_1",
        "--state",
        str(state),
    ]

    first_result = runner.invoke(app, args)
    complete_result = runner.invoke(
        app,
        [
            "scheduler-state",
            "complete",
            "issue-follow-up-project_1-abc123def4567890",
            "--state",
            str(state),
        ],
    )
    second_result = runner.invoke(app, args)

    assert first_result.exit_code == 0, first_result.stdout
    assert complete_result.exit_code == 0, complete_result.stdout
    assert second_result.exit_code == 0, second_result.stdout
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["status"] == "completed"
