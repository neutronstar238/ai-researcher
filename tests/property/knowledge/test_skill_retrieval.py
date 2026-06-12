from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from autoresearch.knowledge import (
    SkillRetrievalQuery,
    SuccessfulPatternExample,
    extract_reusable_skill_card,
    retrieve_relevant_skills,
)

SKILL_TOKEN = st.from_regex(r"[a-z][a-z0-9]{2,8}", fullmatch=True)


@given(skill_token=SKILL_TOKEN)
def test_retrieve_relevant_skills_returns_expected_skill_for_similar_task(
    skill_token: str,
) -> None:
    with TemporaryDirectory() as temp_dir:
        vault_root = Path(temp_dir) / "autoresearch-vault"
        expected = extract_reusable_skill_card(
            vault_root=vault_root,
            name=f"{skill_token} experiment skill",
            examples=(
                SuccessfulPatternExample(
                    project_id="project_a",
                    experience_ref=f"projects/project_a/experience/{skill_token}",
                    summary=f"{skill_token} workflow succeeded once.",
                    trigger_conditions=(f"{skill_token} trigger",),
                    actions=(f"{skill_token} action",),
                    success_metrics=(f"{skill_token} metric improves",),
                    tags=(skill_token,),
                ),
                SuccessfulPatternExample(
                    project_id="project_b",
                    experience_ref=f"projects/project_b/experience/{skill_token}",
                    summary=f"{skill_token} workflow transferred.",
                    trigger_conditions=(f"{skill_token} trigger",),
                    actions=(f"{skill_token} action",),
                    success_metrics=(f"{skill_token} metric improves",),
                    tags=(skill_token,),
                ),
            ),
            tags=(skill_token,),
            keywords=(skill_token,),
        )
        extract_reusable_skill_card(
            vault_root=vault_root,
            name="unrelated control skill",
            examples=(
                SuccessfulPatternExample(
                    project_id="project_c",
                    experience_ref="projects/project_c/experience/unrelated",
                    summary="Unrelated workflow succeeded once.",
                    trigger_conditions=("unrelated trigger",),
                    actions=("unrelated action",),
                    success_metrics=("unrelated metric improves",),
                    tags=("unrelated",),
                ),
                SuccessfulPatternExample(
                    project_id="project_d",
                    experience_ref="projects/project_d/experience/unrelated",
                    summary="Unrelated workflow transferred.",
                    trigger_conditions=("unrelated trigger",),
                    actions=("unrelated action",),
                    success_metrics=("unrelated metric improves",),
                    tags=("unrelated",),
                ),
            ),
            tags=("unrelated",),
            keywords=("unrelated",),
        )

        matches = retrieve_relevant_skills(
            vault_root=vault_root,
            query=SkillRetrievalQuery(
                title=f"{skill_token} task",
                description=f"Need to apply {skill_token} trigger and action.",
                metadata={"trigger": skill_token, "metric": f"{skill_token} metric improves"},
                tags=(skill_token,),
                keywords=(skill_token,),
            ),
        )

    assert matches
    assert matches[0].skill_id == expected.skill_id
