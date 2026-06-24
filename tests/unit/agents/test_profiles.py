import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.agents import (
    AgentCapabilityError,
    AgentMcpServerBinding,
    AgentProfile,
    AgentProfileReadinessReport,
    AgentRegistry,
    AgentResult,
    AgentResultStatus,
    AgentSkillBinding,
    AgentSkillMaterializationStatus,
    AgentTask,
    BaseAgent,
    McpApprovalPolicy,
    SkillImportPolicy,
    build_agent_profile_from_bundle,
    build_agent_profiles_from_set_bundle,
    build_agent_stage_assignment_manifest,
    build_agent_stage_context_packet,
    evaluate_agent_profile_readiness,
    evaluate_agent_profile_set,
    load_agent_profile_bundle,
    load_agent_profile_set_bundle,
    materialize_agent_skill_contexts,
    parse_mcp_approval_policy_specs,
    parse_mcp_env_key_specs,
    parse_mcp_spec,
    parse_server_tool_specs,
    parse_skill_policy_specs,
    parse_skill_spec,
    profile_contexts_by_stage,
    profile_contexts_for_stage,
    render_agent_stage_runtime_prompt,
    write_agent_profile,
    write_agent_profile_note,
)
from autoresearch.knowledge import AgentRole


class DummyAgent(BaseAgent):
    def execute_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=AgentResultStatus.SUCCESS,
            output=self.runtime_context(),
        )


def test_agent_profile_round_trips_and_renders_runtime_context(tmp_path: Path) -> None:
    profile = AgentProfile(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        assigned_stages=("literature", "research-plan"),
        skills=(
            AgentSkillBinding(
                skill_id="source-tracing",
                source="autoresearch-vault/_system/skills/source-tracing.md",
                allowed_tasks=("literature_refresh",),
            ),
        ),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="obsidian",
                command=("npx", "-y", "obsidian-mcp"),
                allowed_tools=("search_notes", "read_note"),
                env_keys=("OBSIDIAN_API_KEY",),
            ),
        ),
    )

    path = write_agent_profile(profile, tmp_path / "profile.json")
    restored = AgentProfile.model_validate_json(path.read_text(encoding="utf-8"))
    context = restored.to_runtime_context()

    assert context["thinking_mode"] == "scientific"
    assert context["context_kind"] == "agent_profile_process_metadata"
    assert context["evidence_policy"]["can_support"] == [
        "agent responsibility boundaries",
        "available custom skill context",
        "available MCP tool context",
    ]
    assert "scientific results" in context["evidence_policy"]["cannot_support"]
    assert "publication readiness" in context["evidence_policy"]["cannot_support"]
    assert context["assigned_stages"] == ["literature", "research_plan"]
    assert context["skills"][0]["skill_id"] == "source-tracing"
    assert context["mcp_servers"][0]["allowed_tools"] == ["search_notes", "read_note"]
    contract = context["mcp_runtime_contracts"][0]
    assert contract["server_id"] == "obsidian"
    assert contract["contract_kind"] == "mcp_runtime_contract_process_metadata"
    assert contract["allowed_tools"] == ["search_notes", "read_note"]
    assert contract["allowed_tool_count"] == 2
    assert contract["env_keys"] == ["OBSIDIAN_API_KEY"]
    assert contract["env_values_recorded"] is False
    assert contract["runtime_approval_required"] is True
    assert contract["operator_isolation_required"] is False
    assert contract["tool_invocation_evidence_required"] is True
    assert contract["command_sha256"]
    assert "do not prove a tool was invoked" in contract["evidence_policy"]


def test_agent_profile_mcp_runtime_contract_marks_allow_all_isolation() -> None:
    profile = AgentProfile(
        agent_id="operator-agent",
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="local-admin",
                command=("npx", "-y", "local-admin-mcp"),
                allowed_tools=("run_task",),
                approval_policy=McpApprovalPolicy.ALLOW_ALL,
                evidence_refs=("[[tools/local-admin]]",),
            ),
        ),
    )

    contract = profile.to_runtime_context()["mcp_runtime_contracts"][0]

    assert contract["approval_policy"] == "allow_all"
    assert contract["runtime_approval_required"] is False
    assert contract["operator_isolation_required"] is True
    assert contract["readiness_check_ids"] == [
        "mcp_env_keys:local-admin",
        "mcp_approval_policy:local-admin",
    ]
    assert contract["evidence_refs"] == ["[[tools/local-admin]]"]


def test_agent_profile_materializes_bounded_local_skill_context(tmp_path: Path) -> None:
    skill_path = tmp_path / "skills" / "source-tracing.md"
    skill_path.parent.mkdir(parents=True)
    skill_text = "# Source Tracing\nAlways bind claims to source records.\n"
    skill_path.write_text(skill_text, encoding="utf-8")
    stored_skill_bytes = skill_path.read_bytes()
    stored_skill_text = stored_skill_bytes.decode("utf-8")
    profile = AgentProfile(
        agent_id="literature-agent",
        skills=(AgentSkillBinding(skill_id="source-tracing", source="skills/source-tracing.md"),),
    )

    contexts = materialize_agent_skill_contexts(profile, base_dir=tmp_path, max_chars=200)
    runtime_context = profile.to_runtime_context(
        base_dir=tmp_path,
        materialize_skills=True,
        max_skill_chars=200,
    )

    assert contexts[0].status == AgentSkillMaterializationStatus.LOADED
    assert contexts[0].content == stored_skill_text
    assert contexts[0].sha256 == hashlib.sha256(stored_skill_bytes).hexdigest()
    assert contexts[0].byte_count == len(stored_skill_bytes)
    assert contexts[0].char_count == len(stored_skill_text)
    assert contexts[0].truncated is False
    assert runtime_context["materialized_skills"][0]["status"] == "loaded"
    assert runtime_context["materialized_skills"][0]["content"] == stored_skill_text
    assert "scientific results" in runtime_context["materialized_skills"][0]["evidence_policy"]


def test_agent_profile_materialization_truncates_and_blocks_secretish_text(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills" / "long-skill"
    skill_dir.mkdir(parents=True)
    skill_text = "# Long Skill\n" + ("evidence-backed step\n" * 10)
    (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
    stored_skill_text = (skill_dir / "SKILL.md").read_bytes().decode("utf-8")
    secret_path = tmp_path / "skills" / "secret.md"
    secret_path.write_text("token=do-not-record\n", encoding="utf-8")
    stored_secret_bytes = secret_path.read_bytes()
    profile = AgentProfile(
        agent_id="review-agent",
        skills=(
            AgentSkillBinding(skill_id="long-skill", source="skills/long-skill"),
            AgentSkillBinding(skill_id="secret-skill", source="skills/secret.md"),
        ),
    )

    contexts = materialize_agent_skill_contexts(profile, base_dir=tmp_path, max_chars=24)

    assert contexts[0].status == AgentSkillMaterializationStatus.TRUNCATED
    assert contexts[0].content == stored_skill_text[:24]
    assert contexts[0].truncated is True
    assert contexts[0].resolved_path is not None
    assert contexts[0].resolved_path.endswith("skills/long-skill/SKILL.md")
    assert contexts[1].status == AgentSkillMaterializationStatus.BLOCKED
    assert contexts[1].content is None
    assert contexts[1].sha256 == hashlib.sha256(stored_secret_bytes).hexdigest()


def test_profile_contexts_group_by_assigned_stage() -> None:
    literature_profile = AgentProfile(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        assigned_stages=("literature", "research-plan"),
        skills=(AgentSkillBinding(skill_id="source-tracing", source="skills/source.md"),),
    )
    reviewer_profile = AgentProfile(
        agent_id="reviewer",
        role=AgentRole.VALIDATOR_AGENT,
        assigned_stages=("review",),
        skills=(AgentSkillBinding(skill_id="question-validator", source="[[Question-Validator]]"),),
    )
    contexts = (
        literature_profile.to_runtime_context(),
        reviewer_profile.to_runtime_context(),
    )

    assert profile_contexts_for_stage(contexts, "research-plan")[0]["agent_id"] == (
        "literature-agent"
    )
    grouped = profile_contexts_by_stage(contexts, ("literature", "research_plan", "review"))

    assert grouped["literature"][0]["skills"][0]["skill_id"] == "source-tracing"
    assert grouped["literature"][0]["context_kind"] == "agent_profile_process_metadata"
    assert grouped["research_plan"][0]["agent_id"] == "literature-agent"
    assert grouped["review"][0]["agent_id"] == "reviewer"


def test_agent_stage_context_packet_routes_only_assigned_agents(tmp_path: Path) -> None:
    skill_path = tmp_path / "skills" / "review-skill.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Review Skill\nCheck claims against local evidence.\n", encoding="utf-8")
    literature_profile = AgentProfile(
        agent_id="literature-agent",
        assigned_stages=("literature",),
        skills=(AgentSkillBinding(skill_id="source-tracing", source="skills/source.md"),),
    )
    reviewer_profile = AgentProfile(
        agent_id="reviewer",
        role=AgentRole.VALIDATOR_AGENT,
        assigned_stages=("review",),
        skills=(AgentSkillBinding(skill_id="review-skill", source="skills/review-skill.md"),),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="opencode",
                command=("opencode", "run"),
                allowed_tools=("code.review",),
                approval_policy=McpApprovalPolicy.READ_ONLY,
            ),
        ),
    )
    contexts = (
        literature_profile.to_runtime_context(base_dir=tmp_path, materialize_skills=True),
        reviewer_profile.to_runtime_context(base_dir=tmp_path, materialize_skills=True),
    )

    packet = build_agent_stage_context_packet(
        contexts,
        "review",
        project_id="project_1",
        cycle_id="cycle_1",
    )

    assert packet["packet_kind"] == "agent_stage_context_packet_process_metadata"
    assert packet["stage"] == "review"
    assert packet["project_id"] == "project_1"
    assert packet["cycle_id"] == "cycle_1"
    assert packet["agent_ids"] == ["reviewer"]
    assert packet["agent_count"] == 1
    assert packet["skill_ids"] == ["review-skill"]
    assert packet["materialized_skill_ids"] == ["review-skill"]
    assert packet["mcp_server_ids"] == ["opencode"]
    assert packet["scientific_focus"].startswith("Review as a skeptical scientific referee")
    assert packet["readiness"]["passed"] is True
    assert packet["missing_assignment"] is False
    assert packet["agents"][0]["materialized_skills"][0]["content"].startswith(
        "# Review Skill"
    )
    assert packet["agents"][0]["mcp_runtime_contracts"][0]["server_id"] == "opencode"
    assert "cannot prove scientific results" in packet["evidence_policy"]
    assert packet["runtime_prompt"] == render_agent_stage_runtime_prompt(packet)
    assert "Agent Runtime Context: review" in packet["runtime_prompt"]
    assert "Keep the scientific question" in packet["runtime_prompt"]
    assert "Agent: reviewer" in packet["runtime_prompt"]
    assert "# Review Skill" in packet["runtime_prompt"]
    assert "`code.review`" in packet["runtime_prompt"]
    assert "tool evidence required: `true`" in packet["runtime_prompt"]
    assert "cannot prove scientific results" in packet["runtime_prompt"]


def test_agent_stage_assignment_manifest_summarizes_skill_and_mcp_routing(
    tmp_path: Path,
) -> None:
    skill_path = tmp_path / "skills" / "experiment.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Experiment\nRun ablations with evidence.\n", encoding="utf-8")
    experiment_profile = AgentProfile(
        agent_id="experiment-agent",
        assigned_stages=("experiment", "reproduction"),
        skills=(
            AgentSkillBinding(
                skill_id="empirical-paper",
                source="skills/experiment.md",
            ),
        ),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="opencode",
                command=("opencode", "run"),
                allowed_tools=("code.write",),
                approval_policy=McpApprovalPolicy.APPROVE_DANGEROUS,
            ),
        ),
    )
    review_profile = AgentProfile(
        agent_id="reviewer",
        role=AgentRole.VALIDATOR_AGENT,
        assigned_stages=("review",),
        skills=(AgentSkillBinding(skill_id="question-validator", source="[[Question]]"),),
    )
    contexts = (
        experiment_profile.to_runtime_context(
            base_dir=tmp_path,
            materialize_skills=True,
        ),
        review_profile.to_runtime_context(),
    )

    manifest = build_agent_stage_assignment_manifest(
        contexts,
        ("experiment", "reproduction", "review"),
        project_id="project_1",
        cycle_id="cycle_1",
    )

    assert manifest["manifest_kind"] == "agent_stage_assignment_manifest_process_metadata"
    assert manifest["project_id"] == "project_1"
    assert manifest["cycle_id"] == "cycle_1"
    assert manifest["stage_count"] == 3
    rows = {row["stage"]: row for row in manifest["stages"]}
    assert rows["experiment"]["agent_ids"] == ["experiment-agent"]
    assert rows["experiment"]["skill_ids"] == ["empirical-paper"]
    assert rows["experiment"]["materialized_skills"][0]["skill_id"] == "empirical-paper"
    assert rows["experiment"]["materialized_skills"][0]["sha256"]
    assert "content" not in rows["experiment"]["materialized_skills"][0]
    assert rows["experiment"]["mcp_server_ids"] == ["opencode"]
    assert rows["experiment"]["mcp_runtime_contracts"][0]["server_id"] == "opencode"
    assert rows["experiment"]["mcp_runtime_contracts"][0][
        "tool_invocation_evidence_required"
    ] is True
    assert manifest["agent_assignments"][0]["assigned_stages"] == [
        "experiment",
        "reproduction",
    ]
    assert manifest["unassigned_agent_ids"] == []
    assert "cannot prove scientific results" in manifest["evidence_policy"]


def test_agent_profile_set_validation_requires_stage_coverage_and_scientific_contract() -> None:
    literature_profile = AgentProfile(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        assigned_stages=("literature", "research_plan"),
        skills=(AgentSkillBinding(skill_id="source-tracing", source="skills/source.md"),),
    )
    experiment_profile = AgentProfile(
        agent_id="experiment-agent",
        role=AgentRole.PROJECT_AGENT,
        assigned_stages=("experiment", "reproduction"),
        skills=(AgentSkillBinding(skill_id="empirical-paper", source="skills/empirical.md"),),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="opencode",
                command=("opencode", "run"),
                allowed_tools=("code.write",),
            ),
        ),
    )
    reviewer_profile = AgentProfile(
        agent_id="reviewer",
        role=AgentRole.VALIDATOR_AGENT,
        assigned_stages=("review", "evidence_gate"),
        skills=(AgentSkillBinding(skill_id="question-validator", source="[[Question-Validator]]"),),
    )

    validation = evaluate_agent_profile_set(
        (literature_profile, experiment_profile, reviewer_profile),
        required_stages=(
            "literature",
            "research-plan",
            "experiment",
            "reproduction",
            "review",
            "evidence-gate",
        ),
    )

    assert validation.passed is True
    assert validation.validation_kind == "agent_profile_set_process_metadata"
    assert validation.covered_stage_count == 6
    assert validation.missing_stages == ()
    assert validation.stage_coverage[0].agent_ids == ("literature-agent",)
    assert validation.stage_coverage[2].skill_ids == ("empirical-paper",)
    assert validation.stage_coverage[2].mcp_server_ids == ("opencode",)
    assert "cannot support scientific results" in validation.evidence_policy


def test_agent_profile_set_validation_blocks_missing_readiness_and_bad_contract() -> None:
    profile = AgentProfile(
        agent_id="builder",
        role=AgentRole.PROJECT_AGENT,
        assigned_stages=("experiment",),
        thinking_contract=("Ship implementation fast.",),
        skills=(AgentSkillBinding(skill_id="code-skill", source="skills/code.md"),),
    )
    readiness = AgentProfileReadinessReport(
        agent_id="builder",
        passed=False,
        check_count=1,
        failed_check_count=1,
        warning_count=0,
        checks=(),
    )

    validation = evaluate_agent_profile_set(
        (profile,),
        required_stages=("literature", "experiment", "review"),
        readiness_reports=(readiness,),
    )

    assert validation.passed is False
    assert validation.missing_stages == ("literature", "review")
    assert validation.readiness_failed_agent_ids == ("builder",)
    assert validation.non_scientific_contract_agent_ids == ("builder",)
    assert any("missing required stage coverage" in failure for failure in validation.failures)
    assert any("not research/evidence-first" in failure for failure in validation.failures)


def test_agent_profile_requires_mcp_allowlist() -> None:
    with pytest.raises(ValidationError):
        AgentMcpServerBinding(server_id="browser", command=("npx", "browser-mcp"), allowed_tools=())


def test_registry_assigns_profile_to_matching_agent() -> None:
    profile = AgentProfile(
        agent_id="validator",
        role=AgentRole.VALIDATOR_AGENT,
        skills=(AgentSkillBinding(skill_id="question-validator", source="[[Question-Validator]]"),),
    )
    agent = DummyAgent(
        agent_id="validator",
        role=AgentRole.VALIDATOR_AGENT,
        capabilities=frozenset({"review"}),
    )
    registry = AgentRegistry()
    registry.add(agent)

    assigned = registry.assign_profile("validator", profile)
    result = assigned.run_task(AgentTask(task_id="t1", task_type="review"))

    assert result.output["skills"][0]["skill_id"] == "question-validator"
    assert result.output["role"] == "validator_agent"


def test_registry_routes_by_bound_skill_and_mcp_without_bypassing_capability() -> None:
    profile = AgentProfile(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        skills=(
            AgentSkillBinding(
                skill_id="source-tracing",
                source="skills/source.md",
                allowed_tasks=("literature_refresh",),
            ),
        ),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="page-agent",
                command=("npx", "-y", "page-agent"),
                allowed_tools=("browser.search", "browser.open"),
            ),
        ),
    )
    agent = DummyAgent(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        capabilities=frozenset({"review"}),
    )
    registry = AgentRegistry()
    registry.add(agent)
    registry.assign_profile("literature-agent", profile)

    assert agent.bound_skill_ids() == frozenset({"source-tracing"})
    assert agent.bound_mcp_server_ids() == frozenset({"page-agent"})
    assert agent.bound_mcp_tool_refs() == frozenset(
        {"page-agent:browser.search", "page-agent:browser.open"}
    )
    assert agent.supports_skill("source-tracing", task_type="literature_refresh") is True
    assert agent.supports_skill("source-tracing", task_type="experiment") is False
    assert agent.supports_mcp_tool("browser.search", server_id="page-agent") is True
    assert agent.supports_mcp_tool("page-agent:browser.open") is True

    assert registry.find_by_skill("source-tracing", task_type="literature_refresh") == [
        agent
    ]
    assert registry.find_by_skill("source-tracing", task_type="experiment") == []
    assert registry.find_by_mcp_server("page-agent") == [agent]
    assert registry.find_by_mcp_tool("browser.search", server_id="page-agent") == [agent]

    with pytest.raises(AgentCapabilityError, match="lacks capability literature_refresh"):
        agent.run_task(AgentTask(task_id="t1", task_type="literature_refresh"))

    result = agent.run_task(AgentTask(task_id="t2", task_type="review"))
    runtime_capabilities = result.output["profile_runtime_capabilities"]
    assert runtime_capabilities["skill_ids"] == ["source-tracing"]
    assert runtime_capabilities["mcp_server_ids"] == ["page-agent"]
    assert runtime_capabilities["mcp_tool_refs"] == [
        "page-agent:browser.open",
        "page-agent:browser.search",
    ]
    assert "routing metadata only" in runtime_capabilities["evidence_policy"]


def test_parse_specs_and_write_vault_note(tmp_path: Path) -> None:
    tools = parse_server_tool_specs(("browser:open_page", "browser:extract_text"))
    skill = parse_skill_spec("paper-skill=skills/paper.md")
    mcp = parse_mcp_spec("browser=npx -y browser-mcp", tools_by_server=tools)
    profile = AgentProfile(
        agent_id="planner",
        role=AgentRole.PROJECT_AGENT,
        skills=(skill,),
        mcp_servers=(mcp,),
    )

    note = write_agent_profile_note(profile, vault_root=tmp_path / "vault", project_id="project-x")

    assert mcp.allowed_tools == ("open_page", "extract_text")
    assert note.is_file()
    assert "Paper" not in note.read_text(encoding="utf-8")
    assert "paper-skill" in note.read_text(encoding="utf-8")


def test_parse_profile_policy_specs() -> None:
    skill_policies = parse_skill_policy_specs(
        ("source-tracing:approved_runtime", "reviewer:shadow_evaluation")
    )
    mcp_policies = parse_mcp_approval_policy_specs(("browser:approve_dangerous",))
    env_keys = parse_mcp_env_key_specs(("browser:PAGE_AGENT_TOKEN", "browser:PAGE_AGENT_TOKEN"))

    assert skill_policies["source-tracing"] == SkillImportPolicy.APPROVED_RUNTIME
    assert skill_policies["reviewer"] == SkillImportPolicy.SHADOW_EVALUATION
    assert mcp_policies["browser"] == McpApprovalPolicy.APPROVE_DANGEROUS
    assert env_keys["browser"] == ("PAGE_AGENT_TOKEN",)


def test_parse_profile_policy_specs_reject_invalid_env_key() -> None:
    with pytest.raises(ValueError, match="uppercase environment variable"):
        parse_mcp_env_key_specs(("browser:page_agent_token",))


def test_agent_profile_bundle_import_keeps_scientific_contract(tmp_path: Path) -> None:
    skill_path = tmp_path / "skills" / "source-tracing.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Source tracing\nBind claims to retrieved evidence.\n", encoding="utf-8")
    bundle_path = tmp_path / "literature-agent.yaml"
    bundle_path.write_text(
        "\n".join(
            [
                "agent_id: literature-agent",
                "role: project_agent",
                "thinking_mode: scientific",
                "publication_target: ccf-b-or-sci-q2",
                "description: Source-backed literature and plan agent.",
                "assigned_stages:",
                "  - literature",
                "  - research-plan",
                "thinking_contract_additions:",
                "  - Prefer falsifiable research claims over software architecture metaphors.",
                "skills:",
                "  - skill_id: source-tracing",
                "    source: skills/source-tracing.md",
                "    import_policy: approved_runtime",
                "    allowed_tasks:",
                "      - literature_refresh",
                "mcp_servers:",
                "  - server_id: page-agent",
                "    command: npx -y page-agent",
                "    allowed_tools:",
                "      - browser.search",
                "      - browser.open",
                "    approval_policy: approve_dangerous",
                "    env_keys:",
                "      - PAGE_AGENT_TOKEN",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile = build_agent_profile_from_bundle(load_agent_profile_bundle(bundle_path))
    context = profile.to_runtime_context(
        base_dir=tmp_path,
        materialize_skills=True,
        max_skill_chars=400,
    )

    assert profile.agent_id == "literature-agent"
    assert profile.assigned_stages == ("literature", "research_plan")
    assert profile.skills[0].import_policy == SkillImportPolicy.APPROVED_RUNTIME
    assert profile.mcp_servers[0].command == ("npx", "-y", "page-agent")
    assert profile.mcp_servers[0].allowed_tools == ("browser.search", "browser.open")
    assert "Start from the research question" in profile.thinking_contract[0]
    assert any("falsifiable research claims" in item for item in profile.thinking_contract)
    assert context["materialized_skills"][0]["status"] == "loaded"
    assert context["mcp_runtime_contracts"][0]["tool_invocation_evidence_required"] is True


def test_agent_profile_set_bundle_builds_multiple_profiles(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    (skill_dir / "source-tracing.md").write_text("# Source\nBind sources.\n", encoding="utf-8")
    (skill_dir / "review.md").write_text("# Review\nBlock unsupported claims.\n", encoding="utf-8")
    bundle_path = tmp_path / "bundles" / "ccfb-team.yaml"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(
        "\n".join(
            [
                "profile_set_id: ccfb-team",
                "required_stages:",
                "  - literature",
                "  - review",
                "profiles:",
                "  - agent_id: literature-agent",
                "    assigned_stages:",
                "      - literature",
                "    skills:",
                "      - skill_id: source-tracing",
                "        source: skills/source-tracing.md",
                "        import_policy: read_only_context",
                "  - agent_id: review-agent",
                "    role: validator_agent",
                "    thinking_mode: reviewer",
                "    assigned_stages:",
                "      - review",
                "    thinking_contract_additions:",
                "      - Reject prose that outruns experiment evidence.",
                "    skills:",
                "      - skill_id: review-skill",
                "        source: skills/review.md",
                "        import_policy: read_only_context",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = load_agent_profile_set_bundle(bundle_path)
    profiles = build_agent_profiles_from_set_bundle(bundle)

    assert bundle.profile_set_id == "ccfb-team"
    assert bundle.required_stages == ("literature", "review")
    assert [profile.agent_id for profile in profiles] == [
        "literature-agent",
        "review-agent",
    ]
    assert profiles[1].role == AgentRole.VALIDATOR_AGENT
    assert profiles[1].thinking_mode.value == "reviewer"
    assert profiles[1].assigned_stages == ("review",)
    assert any("outruns experiment evidence" in item for item in profiles[1].thinking_contract)


def test_agent_profile_set_bundle_rejects_duplicate_agent_ids(tmp_path: Path) -> None:
    bundle_path = tmp_path / "duplicate-team.yaml"
    bundle_path.write_text(
        "\n".join(
            [
                "profile_set_id: duplicate-team",
                "profiles:",
                "  - agent_id: reviewer",
                "    assigned_stages: [review]",
                "    skills:",
                "      - skill_id: review-skill",
                "        source: '[[Review Skill]]'",
                "  - agent_id: reviewer",
                "    assigned_stages: [publication-audit]",
                "    skills:",
                "      - skill_id: audit-skill",
                "        source: '[[Audit Skill]]'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate agent profile bundles: reviewer"):
        load_agent_profile_set_bundle(bundle_path)


def test_agent_profile_readiness_passes_for_existing_local_skill_and_env(
    tmp_path: Path,
) -> None:
    skill_path = tmp_path / "skills" / "source-tracing" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Source Tracing\n", encoding="utf-8")
    profile = AgentProfile(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        skills=(
            AgentSkillBinding(
                skill_id="source-tracing",
                source="skills/source-tracing/SKILL.md",
            ),
        ),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="page-agent",
                command=("npx", "-y", "page-agent"),
                allowed_tools=("browser.search",),
                env_keys=("PAGE_AGENT_TOKEN",),
            ),
        ),
    )

    report = evaluate_agent_profile_readiness(
        profile,
        base_dir=tmp_path,
        env={"PAGE_AGENT_TOKEN": "set-outside-repo"},
    )

    assert report.passed is True
    assert report.failed_check_count == 0
    assert {check.check_id for check in report.checks} == {
        "skill_source_exists:source-tracing",
        "mcp_env_keys:page-agent",
    }


def test_agent_profile_readiness_fails_for_missing_local_skill_and_env(
    tmp_path: Path,
) -> None:
    profile = AgentProfile(
        agent_id="literature-agent",
        role=AgentRole.PROJECT_AGENT,
        skills=(
            AgentSkillBinding(
                skill_id="source-tracing",
                source="skills/source-tracing/SKILL.md",
            ),
        ),
        mcp_servers=(
            AgentMcpServerBinding(
                server_id="page-agent",
                command=("npx", "-y", "page-agent"),
                allowed_tools=("browser.search",),
                env_keys=("PAGE_AGENT_TOKEN",),
            ),
        ),
    )

    report = evaluate_agent_profile_readiness(profile, base_dir=tmp_path, env={})

    assert report.passed is False
    assert report.failed_check_count == 2
    assert [check.status.value for check in report.checks] == ["fail", "fail"]
    assert "PAGE_AGENT_TOKEN" in report.checks[1].message
