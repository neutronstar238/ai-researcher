import { useQuery } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface Team {
  id: string;
  name: string;
  slug: string;
  owner_user_id: string;
  status: string;
}

export interface Project {
  id: string;
  team_id: string;
  name: string;
  slug: string;
  description: string | null;
  research_domain: string | null;
  objective: string | null;
  status: string;
  current_cycle_id: string | null;
  visibility: string;
  version: number;
}

export interface Cycle {
  id: string;
  project_id: string;
  sequence_no: number;
  name: string;
  status: string;
}

export function useTeams() {
  return useQuery<Team[]>({ queryKey: ["teams"], queryFn: () => request<Team[]>("/api/v1/teams") });
}

export function useProjects(teamId: string | undefined) {
  return useQuery<Project[]>({
    queryKey: ["projects", teamId],
    queryFn: () => request<Project[]>(`/api/v1/projects?team_id=${teamId}`),
    enabled: Boolean(teamId),
  });
}

export function useProject(projectId: string | undefined) {
  return useQuery<Project>({
    queryKey: ["project", projectId],
    queryFn: () => request<Project>(`/api/v1/projects/${projectId}`),
    enabled: Boolean(projectId),
  });
}

export function useCycles(projectId: string | undefined) {
  return useQuery<Cycle[]>({
    queryKey: ["cycles", projectId],
    queryFn: () => request<Cycle[]>(`/api/v1/projects/${projectId}/cycles`),
    enabled: Boolean(projectId),
  });
}

export async function createProject(input: {
  team_id: string;
  name: string;
  slug: string;
  research_domain?: string;
  objective?: string;
}): Promise<Project> {
  return request<Project>("/api/v1/projects", { method: "POST", body: JSON.stringify(input) });
}
