export type RunStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "canceled"
  | "completed"
  | "failed"
  | "interrupted"
  | "dry_run";

export type StageStatus = "completed" | "running" | "pending" | "invalid";

export interface StageRecord {
  ordinal: number;
  stage_name: string;
  label_zh: string;
  status: StageStatus;
  artifact_count: number;
  checkpoint_hash: string | null;
}

export interface ArtifactRecord {
  relative_path: string;
  category: string;
  bytes: number;
  sha256: string;
  media_type: string;
  url: string;
}

export interface RunRecord {
  schema_version: string;
  run_id: string;
  kind: "single";
  direction: string;
  status: RunStatus;
  dry_run: boolean;
  preexperiment_policy: "required" | "if_supported";
  dreaming_recall_enabled: boolean;
  output_dir: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  resume_count: number;
  cancel_requested: boolean;
  error: { type: string; message: string } | null;
  result: Record<string, unknown> | null;
  delivery_validation: Record<string, unknown> | null;
  stages?: StageRecord[];
  artifacts?: ArtifactRecord[];
  cancellation_boundary?: string;
}

export interface RunCreateInput {
  direction: string;
  dry_run?: boolean;
  preexperiment_policy?: "required" | "if_supported";
  dreaming_recall_enabled?: boolean;
}

export interface HealthResponse {
  status: "ok";
  service: string;
  deployment_scope: string;
  authentication_enabled: boolean;
  formal_experiment_enabled: boolean;
  result_paper_enabled: boolean;
  self_evolution_execution_enabled: boolean;
  self_evolution_service_configured: boolean;
  automatic_skill_activation_enabled: boolean;
  batch_execution_configured: boolean;
}

export interface BatchCreateInput {
  question_pdf: string;
  start?: number;
  limit?: number;
  include_question_ids?: number[];
  resume?: boolean;
  dry_run?: boolean;
  preexperiment_policy?: "required" | "plan_only_on_unsupported";
  dreaming_recall_enabled?: boolean;
}

export interface BatchRecord {
  schema_version: string;
  batch_id: string;
  status: string;
  dry_run: boolean;
  question_count: number;
  created_at: string;
  items?: unknown[];
  batch_service_configured?: boolean;
  question_pdf?: string;
  start?: number;
  limit?: number;
  include_question_ids?: number[];
  batch_service_receipt?: Record<string, unknown>;
}

export interface SkillCandidate {
  candidate_skill_id: string;
  parent_skill: string | null;
  candidate_status: string;
  relative_path: string;
  promotion_authorized: false;
  promotion_boundary: string;
}

export interface SelectedSkillsResponse {
  run_id: string;
  source_artifact: string | null;
  selection: unknown;
  skill_content_is_scientific_evidence: false;
}

export interface EvolutionStatus {
  run_id: string;
  execution_enabled: boolean;
  mode: "frozen_service_available" | "query_only";
  selected_skills: SelectedSkillsResponse;
  skill_candidates: SkillCandidate[];
  run_evolution_receipt: Record<string, unknown> | null;
  promotion_authorized: false;
  boundary: string;
}

export interface EvolutionReceipt {
  schema_version: string;
  run_id: string;
  status: string;
  result: Record<string, unknown>;
  promotion_authorized: false;
  created_at: string;
}
