import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

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

export function useApprovals(projectId: string | undefined, status?: string) {
  return useQuery<Approval[]>({
    queryKey: ["approvals", projectId, status ?? "all"],
    queryFn: () =>
      request<Approval[]>(
        `/api/v1/projects/${projectId}/approvals${status ? `?status=${status}` : ""}`,
      ),
    enabled: Boolean(projectId),
  });
}

export function useDecideApproval(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ approvalId, decision, comment }: { approvalId: string; decision: "approved" | "rejected"; comment?: string }) =>
      request<Approval>(`/api/v1/projects/${projectId}/approvals/${approvalId}:${decision}`, {
        method: "POST",
        body: JSON.stringify({ comment: comment ?? "" }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals", projectId] }),
  });
}
