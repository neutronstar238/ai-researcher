import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface Agent {
  id: string;
  key: string;
  display_name: string;
  description: string | null;
  status: string;
  active_version_id: string | null;
}

export interface AgentTask {
  id: string;
  agent_version_id: string;
  task_type: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  token_usage: Record<string, unknown> | null;
  attempt: number;
  created_at: string;
}

export function useAgents(projectId: string | undefined, teamId: string | undefined) {
  return useQuery<Agent[]>({
    queryKey: ["agents", teamId],
    queryFn: () => request<Agent[]>(`/api/v1/projects/${projectId}/agents?team_id=${teamId}`),
    enabled: Boolean(projectId) && Boolean(teamId),
  });
}

export function useAgentTasks(projectId: string | undefined) {
  return useQuery<AgentTask[]>({
    queryKey: ["agent-tasks", projectId],
    queryFn: () => request<AgentTask[]>(`/api/v1/projects/${projectId}/agent-tasks`),
    enabled: Boolean(projectId),
  });
}

export function useCreateTask(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { agent_version_id: string; task_type: string; input?: Record<string, unknown> }) =>
      request<AgentTask>(`/api/v1/projects/${projectId}/agent-tasks`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent-tasks", projectId] }),
  });
}

export function useTaskAction(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, action }: { taskId: string; action: "cancel" | "retry" }) =>
      request<AgentTask>(`/api/v1/projects/${projectId}/agent-tasks/${taskId}:${action}`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent-tasks", projectId] }),
  });
}

export function useRunTask(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      request<AgentTask>(`/api/v1/projects/${projectId}/agent-tasks/${taskId}:run`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent-tasks", projectId] }),
  });
}
