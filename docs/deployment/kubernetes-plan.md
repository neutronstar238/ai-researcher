# Kubernetes Deployment Plan

Status: planning only. Do not add a Helm chart until the Docker Compose package from task `34.1` stays stable and the runtime surface is clearer.

## Scope

This plan covers a future private Kubernetes deployment for AI-Researcher. The current deployable runtime is still the CLI-centered app image that can run `autoresearch doctor`; it is not yet a full web platform.

## Prerequisites

- Docker Compose verification passes with `docker compose build app` and `docker compose run --rm app`.
- A tagged image is pushed to a private registry, for example `registry.example.com/ai-researcher:<git-sha>`.
- The cluster has Kubernetes `1.29` or newer, a default `StorageClass`, and access to image pull secrets.
- Operators have decided whether PostgreSQL is external managed infrastructure or an in-cluster development service.
- Secrets are available through Kubernetes Secrets or an external secret controller.
- The `autoresearch-vault/` persistence strategy is approved, including backup and restore ownership.

## Proposed Workloads

| Workload | Kubernetes primitive | Purpose |
| --- | --- | --- |
| App runtime | Deployment or Job | Run CLI tasks, health checks, and later API/dashboard commands from the app image. |
| Scheduled refresh | CronJob | Run daily literature refresh only when live-source configuration is approved. |
| Optional database | External service preferred; StatefulSet only for development | Store future product metadata when local Markdown/JSON is no longer enough. |
| Artifact storage | PersistentVolumeClaim or object storage gateway | Persist run logs, reports, validation outputs, figures, and packages. |
| Knowledge vault | PersistentVolumeClaim backed by network storage | Preserve the Obsidian-compatible `autoresearch-vault/` memory substrate. |

## Resource Limits

Initial app runtime request and limit:

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "1Gi"
  limits:
    cpu: "2"
    memory: "4Gi"
```

Initial database request and limit, if using the development StatefulSet:

```yaml
resources:
  requests:
    cpu: "250m"
    memory: "512Mi"
  limits:
    cpu: "1"
    memory: "2Gi"
```

Large experiment execution, GPU scheduling, and full-permission runs stay outside this Kubernetes MVP until a separate compute-provider design is approved.

## Secrets Handling

- Store provider-agnostic LLM fields as secrets: `AUTORESEARCH_LLM_BASE_URL`, `AUTORESEARCH_LLM_API_KEY`, and `AUTORESEARCH_LLM_MODEL_NAME`.
- Store database credentials, API tokens, SSH keys, and notification credentials only in Kubernetes Secrets or an external secret manager.
- Mount secrets as environment variables or read-only files; never write them to `autoresearch-vault/`, run artifacts, reports, or logs.
- Keep ConfigMaps limited to non-secret configuration such as log level, vault path, run path, and feature flags.
- Require human approval before enabling secrets that allow paid model calls, full-permission execution, cloud compute, or publication workflows.

## Persistent Volumes

| Volume | Mount path | Access mode | Backup requirement |
| --- | --- | --- | --- |
| Knowledge vault | `/workspace/autoresearch-vault` | `ReadWriteOnce` for MVP | Snapshot plus Git backup before upgrades. |
| Runs | `/workspace/runs` | `ReadWriteOnce` for MVP | Retain logs, metrics, and validation reports by run ID. |
| Artifacts | `/workspace/artifacts` | `ReadWriteOnce` or object storage | Retain reproducibility packages and generated reports. |
| PostgreSQL data | `/var/lib/postgresql/data` | `ReadWriteOnce` | Snapshot before migration or chart upgrade. |

Use object storage for large raw datasets instead of storing them directly in the app PVC unless a task explicitly approves that cost and retention model.

## Health Checks

- Use an init check equivalent to `autoresearch doctor` to verify package import, config parser availability, project root, and knowledge vault path.
- Use a readiness probe that runs a lightweight command until a real HTTP server exists.
- Use a liveness probe only for long-running services; do not restart one-shot research Jobs just because a long experiment is active.
- CronJobs must surface failed runs through logs and audit records rather than silently retrying without provenance.
- External literature and LLM live checks remain opt-in and must respect rate limits and `.env` or Secret-provided credentials.

## Rollout And Rollback

- Deploy immutable image tags; do not deploy floating `latest` in production.
- Use `helm upgrade --install --atomic` only after a chart exists and has passed dry-run validation.
- Keep previous image tags available for immediate `helm rollback` or Deployment image rollback.
- Take PVC snapshots for the knowledge vault, artifact store, and database before any schema, layout, or migration change.
- For Obsidian vault changes, preserve Git history and record rollback metadata in the vault and audit log.
- Roll back the app image first, then restore PVC or database snapshots only if data compatibility checks fail.
- Any rollback touching safety policy, approval gates, license policy, publication rules, or strategy promotion rules requires human review.

## Helm Chart Entry Criteria

Do not create the Helm chart until all of the following are true:

- Docker Compose app verification is repeatable on a clean machine.
- The app runtime command contract is stable enough for Kubernetes Jobs or Deployments.
- Secrets and persistent paths have documented owners.
- A rollback test has been rehearsed against a non-production namespace.
- Health checks are meaningful for the runtime mode being deployed.

## First Chart Acceptance Checks

- `helm template` renders Deployment or Job, optional database profile, Secrets references, PVCs, probes, and resource limits.
- `helm install --dry-run --debug` passes in a test namespace.
- A test deployment runs `autoresearch doctor` successfully inside the cluster.
- Rollback instructions identify the previous image tag, release revision, PVC snapshot, and Obsidian Git revision.
