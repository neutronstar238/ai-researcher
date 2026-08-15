# autoresearch-vault

This directory is the canonical Obsidian-compatible knowledge vault for AI-Researcher.

Future implementation work should store the project's unified research memory here:

- `Home.md`: human starting page for the vault.
- `_system/`: dashboards, templates, CSS snippets, and optional plugin setup notes.
- `_private/raw-memory/`: local-only, Git-ignored, append-only original bytes and capture manifests.
- `exploration/`: global topics, methods, datasets, failure patterns, skill cards, strategy cards, and indexes.
- `projects/`: project-specific literature notes, progress, issues, experience, experiments, results, evidence, and paper drafts.

Keep tracked files human-readable Markdown with Obsidian wiki-links and machine-readable frontmatter where needed. Dreaming notes, summaries, embeddings, and indexes are derived views: they must retain raw-record hashes and remain rebuildable. Never overwrite an original record to apply a correction; append a superseding record instead. Do not store credentials, private keys, or other secrets anywhere in this directory, including the private raw-memory area.
