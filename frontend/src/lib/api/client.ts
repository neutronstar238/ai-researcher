import type {
  ArtifactRecord,
  BatchCreateInput,
  BatchRecord,
  EvolutionReceipt,
  EvolutionStatus,
  HealthResponse,
  RunCreateInput,
  RunRecord,
  SelectedSkillsResponse,
  SkillCandidate,
  StageRecord,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code = "request_failed",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  new Headers(init?.headers).forEach((value, name) => {
    headers.set(name, value);
  });

  const response = await fetch(path, { ...init, headers });
  const payload = await readJson(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      errorMessage(payload, response.statusText),
      errorCode(payload),
    );
  }
  return payload as T;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return {};
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (isRecord(payload) && typeof payload.message === "string") {
    return payload.message;
  }
  return fallback;
}

function errorCode(payload: unknown): string {
  return isRecord(payload) && typeof payload.error === "string"
    ? payload.error
    : "request_failed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export const apiClient = {
  health: () => request<HealthResponse>("/api/health"),
  listRuns: async () => (await request<{ runs: RunRecord[] }>("/api/runs")).runs,
  getRun: (id: string) => request<RunRecord>(`/api/runs/${encodeURIComponent(id)}`),
  getStages: async (id: string) =>
    (await request<{ run_id: string; stages: StageRecord[] }>(`/api/runs/${encodeURIComponent(id)}/stages`)).stages,
  getArtifacts: async (id: string) =>
    (await request<{ run_id: string; artifacts: ArtifactRecord[] }>(`/api/runs/${encodeURIComponent(id)}/artifacts`)).artifacts,
  selectedSkills: (id: string) =>
    request<SelectedSkillsResponse>(`/api/runs/${encodeURIComponent(id)}/skills`),
  createRun: (input: RunCreateInput) =>
    request<RunRecord>("/api/runs", { method: "POST", body: JSON.stringify(input) }),
  resumeRun: (id: string) =>
    request<RunRecord>(`/api/runs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  cancelRun: (id: string) =>
    request<RunRecord>(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  listBatches: async () =>
    (await request<{ batches: BatchRecord[] }>("/api/batches")).batches,
  getBatch: (id: string) => request<BatchRecord>(`/api/batches/${encodeURIComponent(id)}`),
  createBatch: (input: BatchCreateInput) =>
    request<BatchRecord>("/api/batches", { method: "POST", body: JSON.stringify(input) }),
  skillCandidates: async () =>
    (await request<{ candidates: SkillCandidate[] }>("/api/skills/candidates")).candidates,
  evolution: (id: string) =>
    request<EvolutionStatus>(`/api/runs/${encodeURIComponent(id)}/evolution`),
  startEvolution: (id: string) =>
    request<EvolutionReceipt>(`/api/runs/${encodeURIComponent(id)}/evolution`, { method: "POST" }),
};
