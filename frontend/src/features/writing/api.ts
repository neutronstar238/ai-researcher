import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface Document {
  id: string;
  title: string;
  document_type: string;
  status: string;
  current_version_id: string | null;
}

export interface Version {
  id: string;
  document_id: string;
  version_no: number;
  content_sha256: string;
  change_summary: string | null;
  created_at: string;
}

export function useDocuments(projectId: string | undefined) {
  return useQuery<Document[]>({
    queryKey: ["documents", projectId],
    queryFn: () => request<Document[]>(`/api/v1/projects/${projectId}/documents`),
    enabled: Boolean(projectId),
  });
}

export function useCreateDocument(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { cycle_id: string; title: string; document_type: string }) =>
      request<Document>(`/api/v1/projects/${projectId}/documents`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", projectId] }),
  });
}

export function useVersions(projectId: string | undefined, documentId: string | undefined) {
  return useQuery<Version[]>({
    queryKey: ["document-versions", projectId, documentId],
    queryFn: () => request<Version[]>(`/api/v1/projects/${projectId}/documents/${documentId}/versions`),
    enabled: Boolean(projectId) && Boolean(documentId),
  });
}

export function useCreateVersion(projectId: string | undefined, documentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { content_markdown: string; change_summary?: string }) =>
      request<Version>(`/api/v1/projects/${projectId}/documents/${documentId}/versions`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["document-versions", projectId, documentId] }),
  });
}

export function useIntegrityCheck(projectId: string | undefined, documentId: string | undefined) {
  return useMutation({
    mutationFn: () =>
      request<{
        passed: boolean;
        errors: { code: string; message?: string }[];
        warnings: { code: string; message?: string; marker?: string; citation_key?: string }[];
      }>(
        `/api/v1/projects/${projectId}/documents/${documentId}:integrity-check`,
        { method: "POST", body: JSON.stringify({}) },
      ),
  });
}

export interface Suggestion {
  id: string;
  document_id: string;
  base_version_id: string;
  target_section_key: string | null;
  status: string;
  patch: { additions: number; deletions: number; ops: unknown[] } | null;
  rendered_preview: string | null;
  created_at: string;
}

export function useExportDocument(projectId: string | undefined, documentId: string | undefined) {
  return useMutation({
    mutationFn: () =>
      request<{ asset_id: string; download_url: string; sha256: string; manifest: Record<string, unknown> }>(
        `/api/v1/projects/${projectId}/documents/${documentId}:export`,
        { method: "POST", body: JSON.stringify({}) },
      ),
  });
}

export function useSuggestions(projectId: string | undefined, documentId: string | undefined) {
  return useQuery<Suggestion[]>({
    queryKey: ["document-suggestions", projectId, documentId],
    queryFn: () => request<Suggestion[]>(`/api/v1/projects/${projectId}/documents/${documentId}/suggestions`),
    enabled: Boolean(projectId) && Boolean(documentId),
  });
}

export function useCreateSuggestion(projectId: string | undefined, documentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { base_version_id: string; proposed_markdown: string; target_section_key?: string }) =>
      request<Suggestion>(`/api/v1/projects/${projectId}/documents/${documentId}:suggestions`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["document-suggestions", projectId, documentId] }),
  });
}

export function useDecideSuggestion(projectId: string | undefined, documentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ suggestionId, decision }: { suggestionId: string; decision: "accept" | "reject" }) =>
      request<unknown>(`/api/v1/projects/${projectId}/documents/${documentId}/suggestions/${suggestionId}:${decision}`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document-suggestions", projectId, documentId] });
      queryClient.invalidateQueries({ queryKey: ["document-versions", projectId, documentId] });
      queryClient.invalidateQueries({ queryKey: ["documents", projectId] });
    },
  });
}
