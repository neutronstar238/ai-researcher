import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface Paper {
  id: string;
  title: string;
  doi: string | null;
  publication_year: number | null;
  venue: string | null;
  abstract: string | null;
  metadata_source: string | null;
}

export interface PaperResult {
  title: string;
  doi: string | null;
  publication_year: number | null;
  venue: string | null;
  abstract: string | null;
  external_id: string | null;
  source: string;
}

export interface SearchRun {
  id: string;
  project_id: string;
  query: string;
  provider: string;
  status: string;
  result: { count: number; results: PaperResult[] } | null;
  error: Record<string, unknown> | null;
}

export function usePapers(projectId: string | undefined) {
  return useQuery<Paper[]>({
    queryKey: ["papers", projectId],
    queryFn: () => request<Paper[]>(`/api/v1/projects/${projectId}/papers`),
    enabled: Boolean(projectId),
  });
}

export function useCreateSearchRun(projectId: string | undefined) {
  return useMutation({
    mutationFn: ({ query, provider, max_results }: { query: string; provider?: string; max_results?: number }) =>
      request<{ run_id: string; status: string }>(`/api/v1/projects/${projectId}/literature-search-runs`, {
        method: "POST",
        body: JSON.stringify({ query, provider: provider ?? "arxiv", max_results: max_results ?? 10 }),
      }),
  });
}

/** 轮询检索 Job（§3.3 202+Job）：终态前每 2s 刷新。 */
export function useSearchRun(projectId: string | undefined, runId: string | undefined) {
  return useQuery<SearchRun>({
    queryKey: ["literature-run", projectId, runId],
    queryFn: () => request<SearchRun>(`/api/v1/projects/${projectId}/literature-search-runs/${runId}`),
    enabled: Boolean(projectId) && Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["succeeded", "failed"].includes(status) ? false : 2000;
    },
  });
}

export function useSavePaper(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paper: Partial<PaperResult>) =>
      request<Paper>(`/api/v1/projects/${projectId}/papers`, {
        method: "POST",
        body: JSON.stringify(paper),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["papers", projectId] }),
  });
}
