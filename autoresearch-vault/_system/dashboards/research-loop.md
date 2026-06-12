# Research Loop Dashboard

## Loop Contract

1. Retrieve external evidence.
2. Write source-backed notes into the vault.
3. Generate or update a candidate.
4. Run a reproducible local experiment.
5. Validate metrics and citations.
6. Review against local evidence only.
7. Convert findings into issues, skills, or strategy candidates.

## Queues

- Open issues: `projects/autoresearch-system/issues/`
- Review notes: `projects/autoresearch-system/review/`
- Experiment records: `projects/autoresearch-system/experiments/`
- Skill library: `exploration/skills/`
- Strategy library: `exploration/strategy_cards/`

## Dataview Ideas

Install Dataview manually in Obsidian, then use these snippets in a local dashboard:

```dataview
TABLE entry_type, updated_at, tags
FROM "projects/autoresearch-system/issues"
WHERE status != "closed"
SORT updated_at DESC
```

```dataview
TABLE entry_type, updated_at, keywords
FROM "exploration/skills"
SORT updated_at DESC
```
