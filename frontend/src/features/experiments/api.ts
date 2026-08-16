import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface Experiment {
  id: string;
  cycle_id: string;
  code: string;
  name: string;
  objective: string | null;
  entrypoint: string;
  status: string;
  version: number;
}

export interface Run {
  id: string;
  experiment_id: string;
  run_no: number;
  status: string;
  exit_code: number | null;
  log_output: string | null;
  error: Record<string, unknown> | null;
}

export function useExperiments(projectId: string | undefined) {
  return useQuery<Experiment[]>({
    queryKey: ["experiments", projectId],
    queryFn: () => request<Experiment[]>(`/api/v1/projects/${projectId}/experiments`),
    enabled: Boolean(projectId),
  });
}

export function useCreateExperiment(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { cycle_id: string; code: string; name: string; entrypoint: string }) =>
      request<Experiment>(`/api/v1/projects/${projectId}/experiments`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiments", projectId] }),
  });
}

export function useCreateRun(projectId: string | undefined) {
  return useMutation({
    mutationFn: (experimentId: string) =>
      request<Run>(`/api/v1/projects/${projectId}/experiments/${experimentId}/runs`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
  });
}
