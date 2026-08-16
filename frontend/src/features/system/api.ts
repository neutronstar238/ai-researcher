import { useQuery } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface HealthCheck {
  status: string;
  error?: string;
}

export interface HealthSummary {
  status: string;
  checks: Record<string, HealthCheck>;
  llm_configured: boolean;
  embedding_configured: boolean;
  experiment_runner_configured: boolean;
}

export function useHealthSummary() {
  return useQuery<HealthSummary>({
    queryKey: ["system", "health-summary"],
    queryFn: () => request<HealthSummary>("/api/v1/system/health/summary"),
  });
}
