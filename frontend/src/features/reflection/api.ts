import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface ReflectionMetrics {
  cycle_id: string;
  goal_completion_rate: number;
  stage_completed: number;
  stage_total: number;
  failed_experiment_runs: number;
  evidence_nodes: number;
  unresolved_contradictions: number;
  generated_at: string;
}

export interface Recommendation {
  id: string;
  title: string;
  reason: string;
}

export interface Reflection {
  document_id: string | null;
  metrics: ReflectionMetrics | null;
  recommendations: Recommendation[];
}

export function useReflection(projectId: string | undefined, cycleId: string | undefined) {
  return useQuery<Reflection>({
    queryKey: ["reflection", projectId, cycleId],
    queryFn: () => request<Reflection>(`/api/v1/projects/${projectId}/cycles/${cycleId}/reflection`),
    enabled: Boolean(projectId) && Boolean(cycleId),
  });
}

export function useRunReflection(projectId: string | undefined, cycleId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<Reflection>(`/api/v1/projects/${projectId}/cycles/${cycleId}/reflection-runs`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reflection", projectId, cycleId] }),
  });
}

export function useAcceptRecommendation(projectId: string | undefined, cycleId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (recId: string) =>
      request<{ action_id: string; title: string }>(
        `/api/v1/projects/${projectId}/cycles/${cycleId}/reflection/recommendations/${recId}:accept`,
        { method: "POST", body: JSON.stringify({}) },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reflection", projectId, cycleId] }),
  });
}
