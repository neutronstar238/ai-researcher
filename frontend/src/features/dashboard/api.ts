import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface HealthCheck {
  status: string;
  error?: string;
}

export interface HealthReady {
  status: "ready" | "degraded";
  checks: Record<string, HealthCheck>;
}

export interface HealthSummary {
  status: string;
  checks: Record<string, HealthCheck>;
  llm_configured: boolean;
  embedding_configured: boolean;
  experiment_runner_configured: boolean;
}

export function useHealthReady() {
  return useQuery<HealthReady>({
    queryKey: ["health", "ready"],
    queryFn: () => request<HealthReady>("/health/ready"),
    refetchInterval: 30_000,
  });
}

export function useHealthSummary() {
  return useQuery<HealthSummary>({
    queryKey: ["system", "health", "summary"],
    queryFn: () => request<HealthSummary>("/api/v1/system/health/summary"),
    refetchInterval: 30_000,
  });
}

export interface StageOut {
  ordinal: number;
  stage_key: string;
  label_zh: string;
  status: string;
  progress: number;
  evidence_count: number;
  blocked_reason: string | null;
  version: number;
}

export interface Dashboard {
  project: {
    name: string;
    current_cycle_id: string | null;
    current_stage: string | null;
    progress_percent: number;
    next_action: { id: string; title: string; stage_key: string | null } | null;
    research_domain: string | null;
    objective: string | null;
    status: string;
  };
  statistics: { papers: number; experiment_runs: number; datasets: number; figures: number };
  lifecycle: StageOut[];
  updated_at: string;
}

export function useDashboard(projectId: string | undefined) {
  return useQuery<Dashboard>({
    queryKey: ["dashboard", projectId],
    queryFn: () => request<Dashboard>(`/api/v1/projects/${projectId}/dashboard`),
    enabled: Boolean(projectId),
  });
}

export interface Approval {
  id: string;
  project_id: string;
  approval_type: string;
  subject_type: string | null;
  status: string;
  risk_level: string;
  request_reason: string | null;
  requested_by: string;
  created_at: string;
}

export interface TopicCandidate {
  id: string;
  title: string;
  evidence_strength: number | null;
  status: string;
  research_question: string | null;
  rationale: string | null;
}

export interface CoveragePoint {
  label: string;
  coverage: number;
}

export function useApprovals(projectId: string | undefined, status = "pending") {
  return useQuery<Approval[]>({
    queryKey: ["approvals", projectId, status],
    queryFn: () => request<Approval[]>(`/api/v1/projects/${projectId}/approvals?status=${status}`),
    enabled: Boolean(projectId),
  });
}

export function useTopicCandidates(projectId: string | undefined) {
  return useQuery<TopicCandidate[]>({
    queryKey: ["topic-candidates", projectId],
    queryFn: () => request<TopicCandidate[]>(`/api/v1/projects/${projectId}/topic-candidates`),
    enabled: Boolean(projectId),
  });
}

export function useCoverage(projectId: string | undefined, cycles = 6) {
  return useQuery<CoveragePoint[]>({
    queryKey: ["evidence-coverage", projectId, cycles],
    queryFn: () => request<CoveragePoint[]>(`/api/v1/projects/${projectId}/evidence-coverage?cycles=${cycles}`),
    enabled: Boolean(projectId),
  });
}

export function useApproveApproval(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: string; comment?: string }) =>
      request(`/api/v1/projects/${projectId}/approvals/${id}:approve`, {
        method: "POST",
        body: JSON.stringify({ comment }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals", projectId] }),
  });
}

export function useRejectApproval(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: string; comment: string }) =>
      request(`/api/v1/projects/${projectId}/approvals/${id}:reject`, {
        method: "POST",
        body: JSON.stringify({ comment }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals", projectId] }),
  });
}

export function useAcceptCandidate(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      request(`/api/v1/projects/${projectId}/topic-candidates/${id}:accept`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["topic-candidates", projectId] }),
  });
}
