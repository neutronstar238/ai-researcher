import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { AsyncState } from "../../components/ui/AsyncState";
import { useToast } from "../../components/ui/ToastRegion";
import { apiClient } from "../../lib/api/client";

export function AgentsPage() {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: apiClient.skillCandidates });
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: apiClient.listRuns });
  const completedRuns = useMemo(() => (runsQuery.data ?? [])
    .filter((run) => run.status === "completed")
    .sort((left, right) => timestamp(right.created_at) - timestamp(left.created_at) || left.run_id.localeCompare(right.run_id)), [runsQuery.data]);
  const [requestedRunId, setRequestedRunId] = useState<string | null>(null);
  const selectedRunId = requestedRunId !== null && completedRuns.some((run) => run.run_id === requestedRunId)
    ? requestedRunId
    : completedRuns[0]?.run_id ?? null;
  const evolutionQuery = useQuery({
    queryKey: ["evolution", selectedRunId ?? null],
    queryFn: () => apiClient.evolution(selectedRunId!),
    enabled: selectedRunId !== null,
  });
  const evolution = evolutionQuery.data?.run_id === selectedRunId ? evolutionQuery.data : null;
  const identityError = evolutionQuery.data && evolutionQuery.data.run_id !== selectedRunId
    ? new Error("进化状态与所选运行 ID 不一致")
    : null;
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const selectedRunIdRef = useRef(selectedRunId);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  const startEvolution = async () => {
    const runId = selectedRunId;
    if (runId === null || pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    setActionError(null);
    try {
      await apiClient.startEvolution(runId);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["evolution", runId], exact: true }),
        queryClient.invalidateQueries({ queryKey: ["skills"], exact: true }),
      ]);
      if (mountedRef.current && selectedRunIdRef.current === runId) {
        notify({ tone: "success", message: "进化候选任务已发起" });
      }
    } catch (error) {
      if (mountedRef.current && selectedRunIdRef.current === runId) setActionError(errorMessage(error));
    } finally {
      pendingRef.current = false;
      if (mountedRef.current) setPending(false);
    }
  };

  return (
    <section className="feature-page">
      <div className="feature-heading">
        <h1>智能体中心</h1>
        <p>查询 Skill 候选与已持久化进化状态；此界面不授权候选晋级。</p>
      </div>
      <div className="agents-grid">
        <section className="feature-card" aria-labelledby="skill-candidate-heading">
          <h2 id="skill-candidate-heading">Skill 候选</h2>
          {skillsQuery.isPending ? <div className="async-state" role="status">正在加载候选…</div> : skillsQuery.error ? (
            <div className="async-state async-error" role="alert">
              <p>{skillsQuery.error.message}</p>
              <button className="button-secondary" type="button" onClick={() => void skillsQuery.refetch()}>重试候选列表</button>
            </div>
          ) : skillsQuery.data?.length ? (
            <ul className="candidate-list" aria-label="Skill 候选">
              {skillsQuery.data.map((candidate) => (
                <li key={candidate.candidate_skill_id}>
                  <strong>{candidate.candidate_skill_id}</strong>
                  <span>{candidate.candidate_status}</span>
                  <span>父 Skill：{candidate.parent_skill ?? "无"}</span>
                  <code>{candidate.relative_path}</code>
                </li>
              ))}
            </ul>
          ) : <p className="detail-empty">当前没有 Skill 候选</p>}
          <p className="boundary-note">promotion_authorized: false</p>
        </section>

        <section className="feature-card" aria-labelledby="evolution-heading">
          <h2 id="evolution-heading">运行进化状态</h2>
          <AsyncState loading={runsQuery.isPending} error={runsQuery.error} empty={false} onRetry={() => void runsQuery.refetch()}>
            {completedRuns.length === 0 ? <p className="detail-empty">当前没有可查询的已完成运行</p> : (
              <>
                <label className="run-selector">
                  <span>已完成运行</span>
                  <select value={selectedRunId ?? ""} onChange={(event) => {
                    selectedRunIdRef.current = event.target.value;
                    setRequestedRunId(event.target.value);
                    setActionError(null);
                  }}>
                    {completedRuns.map((run) => <option key={run.run_id} value={run.run_id}>{run.direction}</option>)}
                  </select>
                </label>
                <AsyncState
                  loading={evolutionQuery.isPending}
                  error={evolutionQuery.error ?? identityError}
                  empty={false}
                  onRetry={() => void evolutionQuery.refetch()}
                >
                  {evolution ? (
                    <div className="evolution-status">
                      <dl className="compact-facts">
                        <div><dt>模式</dt><dd>{evolution.mode}</dd></div>
                        <div><dt>执行已启用</dt><dd>{evolution.execution_enabled ? "是" : "否"}</dd></div>
                        <div><dt>选择来源</dt><dd>{evolution.selected_skills.source_artifact ?? "未提供"}</dd></div>
                        <div><dt>运行回执</dt><dd>{evolution.run_evolution_receipt ? "已持久化" : "未提供"}</dd></div>
                      </dl>
                      <p className="boundary-note">{evolution.boundary}</p>
                      {actionError ? <p className="form-error" role="alert">{actionError}</p> : null}
                      {evolution.execution_enabled ? (
                        <button className="button-primary" type="button" disabled={pending} onClick={() => void startEvolution()}>
                          {pending ? "发起中…" : "发起进化"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </AsyncState>
              </>
            )}
          </AsyncState>
        </section>
      </div>
    </section>
  );
}

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim() ? error.message : "进化请求失败，请重试。";
}
