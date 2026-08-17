import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { createProject, useProjects, useTeams } from "../features/projects/api";

/** 生成合法的项目 slug（小写字母数字+连字符，字母数字开头，≥2 位）。 */
function slugify(input: string): string {
  const s = input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s.length >= 2 ? s : `project-${Math.random().toString(36).slice(2, 8)}`;
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: teams } = useTeams();
  const [teamId, setTeamId] = useState<string | undefined>(undefined);
  const activeTeamId = teamId ?? teams?.[0]?.id;
  const { data: projects, isLoading } = useProjects(activeTeamId);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [domain, setDomain] = useState("");

  const createMutation = useMutation({
    mutationFn: createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowForm(false);
      setName("");
      setSlug("");
      setDomain("");
    },
  });

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!activeTeamId) return;
    createMutation.mutate({
      team_id: activeTeamId,
      name,
      slug: slugify(slug || name),
      research_domain: domain || undefined,
    });
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text">项目空间</h2>
          <p className="text-sm text-text-muted">管理研究项目与周期</p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
        >
          <Plus className="h-4 w-4" /> 新建项目
        </button>
      </div>

      {teams && teams.length > 1 && (
        <select
          value={activeTeamId}
          onChange={(e) => setTeamId(e.target.value)}
          className="mb-4 rounded-md border border-border-strong px-3 py-2 text-sm"
        >
          {teams.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </select>
      )}

      {showForm && (
        <form onSubmit={handleCreate} className="card mb-4 space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="项目名称"
            required
            className="w-full rounded-md border border-border-strong px-3 py-2 text-sm"
          />
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="slug（留空自动生成）"
            className="w-full rounded-md border border-border-strong px-3 py-2 text-sm"
          />
          <input
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="研究领域"
            className="w-full rounded-md border border-border-strong px-3 py-2 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md px-4 py-2 text-sm text-text-secondary hover:bg-surface-subtle"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="rounded-md bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover disabled:opacity-50"
            >
              创建
            </button>
          </div>
          {createMutation.isError && (
            <div className="text-sm text-danger">{(createMutation.error as Error).message}</div>
          )}
        </form>
      )}

      {isLoading ? (
        <div className="grid grid-cols-2 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card h-28 animate-pulse bg-surface-subtle" />
          ))}
        </div>
      ) : projects && projects.length ? (
        <div className="grid grid-cols-2 gap-4">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              onClick={() => navigate(`/projects/${project.id}/overview`)}
              className="card text-left transition-shadow hover:shadow-popover"
            >
              <div className="flex items-center justify-between">
                <span className="text-[15px] font-semibold text-text">{project.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs ${
                    project.status === "active" ? "bg-success-soft text-success" : "bg-surface-subtle text-text-muted"
                  }`}
                >
                  {project.status === "active" ? "进行中" : project.status}
                </span>
              </div>
              <div className="mt-2 text-sm text-text-muted">
                {project.research_domain ?? "未设置研究领域"}
              </div>
              <div className="mt-1 text-xs text-text-muted">slug: {project.slug}</div>
            </button>
          ))}
        </div>
      ) : (
        <div className="card py-16 text-center text-sm text-text-muted">尚无项目，点击右上角新建。</div>
      )}
    </div>
  );
}
