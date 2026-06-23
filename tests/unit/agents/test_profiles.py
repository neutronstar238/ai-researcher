import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.agents import (
    AgentMcpServerBinding,
    AgentProfile,
    AgentRegistry,
    AgentResult,
    AgentResultStatus,
    AgentSkillBinding,
    AgentSkillMaterializationStatus,
    AgentTask,
    BaseAgent,
    McpApprovalPolicy,
    SkillImportPolicy,
    evaluate_agent_profile_readiness,
    materialize_agent_skill_contexts,
    parse_mcp_approval_policy_specs,
    parse_mcp_env_key_specs,
    parse_mcp_spec,
    parse_server_tool_specs,
    parse_skill_policy_specs,
    parse_skill_spec,
    profile_contexts_by_stage,
    profile_contexts_for_stage,
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
