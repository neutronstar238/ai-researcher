import type {
  ArtifactRecord,
  HealthResponse,
  RunRecord,
  StageRecord,
} from "../lib/api/types";

export const BACKEND_STAGE_NAMES = [
  "broad-literature-query",
  "focus-selection",
  "targeted-literature-query",
  "planning-literature-lock",
  "skill-routing",
  "hypothesis-brainstorm",
  "provisional-plan",
  "real-pilot",
  "postpilot-objective-review",
  "final-plan-revision",
  "render-plan",
  "independent-scientific-review",
] as const;

export function stageFixtures(completed = 0): StageRecord[] {
  return BACKEND_STAGE_NAMES.map((stage_name, index) => ({
    ordinal: index + 1,
    stage_name,
    label_zh: stage_name,
    status: index < completed ? "completed" : "pending",
    artifact_count: index < completed ? 1 : 0,
    checkpoint_hash: index < completed ? String(index + 1).repeat(64).slice(0, 64) : null,
  }));
}

export function runFixture(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    schema_version: "autoresearch-api-run-v1",
    run_id: "run-fixture123",
    kind: "single",
    direction: "测试研究",
    status: "completed",
    dry_run: false,
    preexperiment_policy: "if_supported",
    dreaming_recall_enabled: true,
    output_dir: "runs/research-api/run-fixture123/delivery",
    created_at: "2026-08-20T06:00:00Z",
    started_at: "2026-08-20T06:01:00Z",
    finished_at: "2026-08-20T06:20:00Z",
    resume_count: 0,
    cancel_requested: false,
    error: null,
    result: { status: "completed" },
    delivery_validation: { status: "passed" },
    stages: stageFixtures(12),
    artifacts: [],
    ...overrides,
  };
}

export function healthFixture(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: "ok",
    service: "autoresearch-local-api",
    deployment_scope: "local_single_user",
    authentication_enabled: false,
    formal_experiment_enabled: false,
    result_paper_enabled: false,
    self_evolution_execution_enabled: false,
    self_evolution_service_configured: false,
    automatic_skill_activation_enabled: false,
    batch_execution_configured: true,
    ...overrides,
  };
}

export function artifactFixtures(): ArtifactRecord[] {
  return [
    {
      relative_path: "literature/broad/source.json",
      category: "literature",
      bytes: 640,
      sha256: "a".repeat(64),
      media_type: "application/json",
      url: "/api/runs/run-fixture123/artifacts/literature/broad/source.json",
    },
    {
      relative_path: "pilot/metrics.json",
      category: "experiment",
      bytes: 512,
      sha256: "b".repeat(64),
      media_type: "application/json",
      url: "/api/runs/run-fixture123/artifacts/pilot/metrics.json",
    },
    {
      relative_path: "plan/research-plan.pdf",
      category: "plan",
      bytes: 4096,
      sha256: "c".repeat(64),
      media_type: "application/pdf",
      url: "/api/runs/run-fixture123/artifacts/plan/research-plan.pdf",
    },
  ];
}
