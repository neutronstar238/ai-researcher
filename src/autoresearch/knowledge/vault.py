"""Filesystem layout helpers for the Obsidian knowledge vault."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

EXPLORATION_DIRECTORIES = (
    "topics",
    "skills",
    "methodologies",
    "datasets",
    "failure_patterns",
    "strategy_cards",
)

PROJECT_DIRECTORIES = (
    "knowledge",
    "progress",
    "issues",
    "experience",
    "experiments",
    "results",
    "evidence",
    "paper",
    "review",
)

OBSIDIAN_SYSTEM_DIRECTORIES = (
    "dashboards",
    "templates",
    "snippets",
    "plugins",
)

RECOMMENDED_OBSIDIAN_PLUGINS = (
    ("Dataview", "Structured tables and dashboards from YAML frontmatter."),
    ("Tasks", "Queryable issue and follow-up task views."),
    ("Templater", "Reusable paper, experiment, issue, skill, and strategy templates."),
    ("Periodic Notes", "Daily research cycle notes."),
    ("Advanced Tables", "Cleaner evidence and experiment tables."),
    ("Omnisearch", "Fast local search across the research vault."),
    ("Style Settings", "Optional visual controls for CSS snippets and themes."),
)


@dataclass(frozen=True)
class VaultLayout:
    """Created Obsidian vault paths for one project."""

    root: Path
    exploration: Path
    project: Path


@dataclass(frozen=True)
class ObsidianVaultAssets:
    """Generated Obsidian helper assets."""

    root: Path
    home_path: Path
    dashboard_path: Path
    plugin_recommendations_path: Path
    template_paths: tuple[Path, ...]
    snippet_path: Path
    local_snippet_path: Path | None


def _validate_project_id(project_id: str) -> None:
    if not project_id or project_id in {".", ".."}:
        msg = "project_id must be a non-empty path-safe name"
        raise ValueError(msg)

    project_path = Path(project_id)
    if project_path.name != project_id:
        msg = "project_id must not contain path separators"
        raise ValueError(msg)


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def create_vault_layout(vault_root: Path | str, project_id: str) -> VaultLayout:
    """Create the required Obsidian-compatible vault directories."""

    _validate_project_id(project_id)

    root = Path(vault_root)
    exploration = root / "exploration"
    project = root / "projects" / project_id

    root.mkdir(parents=True, exist_ok=True)
    exploration.mkdir(parents=True, exist_ok=True)
    for directory in EXPLORATION_DIRECTORIES:
        (exploration / directory).mkdir(parents=True, exist_ok=True)

    projects_root = root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    for directory in PROJECT_DIRECTORIES:
        (project / directory).mkdir(parents=True, exist_ok=True)

    _write_if_missing(
        exploration / "index.md",
        "# Exploration Index\n\nGlobal cross-project knowledge index for AutoResearch.\n",
    )
    _write_if_missing(
        project / "index.md",
        f"# {project_id}\n\nProject knowledge index for AutoResearch.\n",
    )

    return VaultLayout(root=root, exploration=exploration, project=project)


def create_obsidian_vault_assets(
    vault_root: Path | str,
    project_id: str,
    *,
    write_local_snippet: bool = False,
) -> ObsidianVaultAssets:
    """Create readable dashboards, templates, and styling assets for Obsidian."""

    layout = create_vault_layout(vault_root, project_id)
    root = layout.root
    system_root = root / "_system"
    for directory in OBSIDIAN_SYSTEM_DIRECTORIES:
        (system_root / directory).mkdir(parents=True, exist_ok=True)

    home_path = root / "Home.md"
    dashboard_path = system_root / "dashboards" / "research-loop.md"
    plugin_recommendations_path = system_root / "plugins" / "recommended-plugins.md"
    snippet_path = system_root / "snippets" / "ai-researcher.css"

    _write_if_missing(home_path, _home_markdown(project_id))
    _write_if_missing(dashboard_path, _dashboard_markdown(project_id))
    _write_if_missing(plugin_recommendations_path, _plugin_recommendations_markdown())
    _write_text(snippet_path, _css_snippet())

    template_paths: list[Path] = []
    for name, content in _template_markdown(project_id).items():
        template_path = system_root / "templates" / name
        _write_if_missing(template_path, content)
        template_paths.append(template_path)

    local_snippet_path = None
    if write_local_snippet:
        local_snippet_path = root / ".obsidian" / "snippets" / "ai-researcher.css"
        _write_text(local_snippet_path, _css_snippet())
        _enable_local_snippet(root / ".obsidian" / "appearance.json", "ai-researcher")

    return ObsidianVaultAssets(
        root=root,
        home_path=home_path,
        dashboard_path=dashboard_path,
        plugin_recommendations_path=plugin_recommendations_path,
        template_paths=tuple(template_paths),
        snippet_path=snippet_path,
        local_snippet_path=local_snippet_path,
    )


def _home_markdown(project_id: str) -> str:
    return f"""# AI-Researcher Home

> Evidence first. A claim is not ready until it links to retrieval, validation, and review evidence.

## Start Here

- [[_system/dashboards/research-loop|Research Loop Dashboard]]
- [[exploration/index|Global Topic Index]]
- [[projects/{project_id}/index|Current Project]]
- [[_system/plugins/recommended-plugins|Recommended Obsidian Plugins]]

## Active Memory Zones

| Zone | Purpose |
|---|---|
| `exploration/topics/` | Live literature refreshes and cross-project discovery. |
| `exploration/skills/` | Reusable skill cards distilled from successful or failed runs. |
| `exploration/strategy_cards/` | Strategy candidates, shadow evaluations, and rollback notes. |
| `projects/{project_id}/issues/` | Reviewer findings and self-loop follow-up tasks. |
| `projects/{project_id}/review/` | Evidence-constrained LLM or human review notes. |
| `projects/{project_id}/paper/` | Drafts that must cite local evidence. |

## Operator Commands

```bash
poetry run airesearcher autopilot --watch --cycles 0 --interval-seconds 86400
poetry run airesearcher issue-followups --vault autoresearch-vault --project-id {project_id}
```
"""


def _dashboard_markdown(project_id: str) -> str:
    return f"""# Research Loop Dashboard

## Loop Contract

1. Retrieve external evidence.
2. Write source-backed notes into the vault.
3. Generate or update a candidate.
4. Run a reproducible local experiment.
5. Validate metrics and citations.
6. Review against local evidence only.
7. Convert findings into issues, skills, or strategy candidates.

## Queues

- Open issues: `projects/{project_id}/issues/`
- Review notes: `projects/{project_id}/review/`
- Experiment records: `projects/{project_id}/experiments/`
- Skill library: `exploration/skills/`
- Strategy library: `exploration/strategy_cards/`

## Dataview Ideas

Install Dataview manually in Obsidian, then use these snippets in a local dashboard:

```dataview
TABLE entry_type, updated_at, tags
FROM "projects/{project_id}/issues"
WHERE status != "closed"
SORT updated_at DESC
```

```dataview
TABLE entry_type, updated_at, keywords
FROM "exploration/skills"
SORT updated_at DESC
```
"""


def _plugin_recommendations_markdown() -> str:
    rows = "\n".join(
        f"| {name} | {purpose} |"
        for name, purpose in RECOMMENDED_OBSIDIAN_PLUGINS
    )
    return f"""# Recommended Obsidian Plugins

These plugins are optional. The CLI and tests do not depend on them, and no API keys should ever be stored in the vault or Obsidian plugin settings.

| Plugin | Why it helps AI-Researcher |
|---|---|
{rows}

## Safe Setup Notes

- Install plugins manually from Obsidian Community Plugins.
- Keep `.env`, model API keys, and provider secrets outside the vault.
- Treat generated issue notes as tasks to inspect, not as automatic approval.
- Keep `.obsidian/` local unless a team intentionally creates a shared vault profile.
"""


def _template_markdown(project_id: str) -> dict[str, str]:
    return {
        "paper-note.md": """---
entry_type: paper_note
zone: exploration
title: "{{title}}"
tags:
  - literature
keywords: []
source_refs:
  - "{{source_url}}"
---

# {{title}}

## Source

- URL:
- Retrieved:
- Database:

## Claims

| Claim | Evidence | Status |
|---|---|---|
|  |  | unverified |

## Relevance

## Open Questions
""",
        "experiment-record.md": f"""---
entry_type: experiment_record
zone: project
project_id: {project_id}
title: "{{experiment_name}}"
tags:
  - experiment
keywords: []
---

# {{experiment_name}}

## Run

- Run ID:
- Command:
- Commit:
- Config hash:
- Data hash:

## Metrics

| Metric | Value | Evidence |
|---|---:|---|

## Validation

## Reproducibility Notes
""",
        "issue-note.md": f"""---
entry_type: issue_note
zone: project
project_id: {project_id}
title: "{{issue_title}}"
tags:
  - issue
keywords: []
---

# {{issue_title}}

- Status: open
- Severity:
- Source:
- Evidence:

## Problem

## Next Action
""",
        "skill-card.md": """---
entry_type: skill_card
zone: exploration
title: "{{skill_name}}"
tags:
  - skill
keywords: []
---

# {{skill_name}}

## Trigger

## Procedure

## Evidence That It Works

## Failure Modes

## Validation Gate
""",
        "strategy-card.md": """---
entry_type: strategy_card
zone: exploration
title: "{{strategy_name}}"
tags:
  - strategy
keywords: []
---

# {{strategy_name}}

## Proposed Change

## Shadow Evaluation Plan

## Promotion Gate

## Rollback Trigger
""",
        "daily-cycle.md": f"""# Daily Research Cycle

Project: [[projects/{project_id}/index|{project_id}]]

## Inputs

- Literature refresh:
- Open issues:
- Candidate:

## Actions

## Evidence Written

## Follow-ups
""",
    }


def _css_snippet() -> str:
    return """/* AI-Researcher Obsidian snippet */
.markdown-preview-view h1,
.markdown-source-view.mod-cm6 .cm-header-1 {
  letter-spacing: 0;
}

.markdown-preview-view table {
  border-collapse: collapse;
}

.markdown-preview-view table th {
  background: var(--background-secondary);
}

.callout[data-callout="evidence"] {
  --callout-color: 48, 117, 191;
  --callout-icon: lucide-shield-check;
}

.callout[data-callout="risk"] {
  --callout-color: 192, 86, 33;
  --callout-icon: lucide-alert-triangle;
}

.callout[data-callout="skill"] {
  --callout-color: 61, 131, 97;
  --callout-icon: lucide-wand-sparkles;
}
"""


def _enable_local_snippet(appearance_path: Path, snippet_name: str) -> None:
    appearance_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {}
    if appearance_path.exists():
        try:
            loaded = json.loads(appearance_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}
    snippets = payload.get("enabledCssSnippets")
    if not isinstance(snippets, list):
        snippets = []
    if snippet_name not in snippets:
        snippets.append(snippet_name)
    payload["enabledCssSnippets"] = snippets
    appearance_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
