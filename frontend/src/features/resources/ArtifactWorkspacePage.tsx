import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../../lib/api/client";
import type { RunRecord } from "../../lib/api/types";
import { filterArtifacts, type ArtifactWorkspace } from "../../lib/domain/artifacts";
import { selectCurrentRun } from "../../lib/domain/selectors";

export interface ArtifactWorkspacePageProps {
  workspace: ArtifactWorkspace;
  title: string;
}

export function ArtifactWorkspacePage({ workspace, title }: ArtifactWorkspacePageProps) {
  const [requestedRunId, setRequestedRunId] = useState<string | null>(null);
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: apiClient.listRuns });
  const runs = runsQuery.data ?? [];
  const defaultRunId = selectCurrentRun(runs)?.run_id ?? null;
  const selectedRunId = requestedRunId !== null && runs.some((run) => run.run_id === requestedRunId)
    ? requestedRunId
    : defaultRunId;
  const detailQuery = useQuery({
    queryKey: ["run", selectedRunId ?? null],
    queryFn: () => apiClient.getRun(selectedRunId!),
    enabled: selectedRunId !== null,
  });
  const detail = detailQuery.data?.run_id === selectedRunId ? detailQuery.data : null;
  const identityError = detailQuery.data && detailQuery.data.run_id !== selectedRunId
    ? new Error("运行详情与所选 ID 不一致")
    : null;
  const artifacts = filterArtifacts(detail?.artifacts ?? [], workspace);

  return (
    <section className="feature-page artifact-workspace">
      <div className="feature-heading">
        <h1>{title}</h1>
        <p>仅展示所选服务端运行返回的公开产物。</p>
      </div>

      {runsQuery.isPending ? (
        <div className="async-state" role="status" aria-label="正在加载运行列表">正在加载运行列表…</div>
      ) : runsQuery.error ? (
        <ErrorState error={runsQuery.error} onRetry={() => void runsQuery.refetch()} />
      ) : runs.length === 0 ? (
        <div className="feature-empty">
          <strong>还没有研究运行</strong>
          <p>创建运行后，公开产物会按领域出现在这里。</p>
          <Link to="/projects">前往项目空间</Link>
        </div>
      ) : (
        <>
          <label className="run-selector">
            <span>研究运行</span>
            <select value={selectedRunId ?? ""} onChange={(event) => setRequestedRunId(event.target.value)}>
              {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.direction}</option>)}
            </select>
          </label>
          <div className="feature-card">
            {detailQuery.isPending ? (
              <div className="async-state" role="status" aria-label="正在加载运行详情">正在加载运行详情…</div>
            ) : detailQuery.error || identityError ? (
              <ErrorState error={detailQuery.error ?? identityError!} onRetry={() => void detailQuery.refetch()} />
            ) : artifacts.length === 0 ? (
              <div className="feature-empty">
                <strong>{title}暂无可用产物</strong>
                <p>当前运行的公开详情中没有匹配该领域的文件。</p>
                <Link to={`/projects?run=${encodeURIComponent(selectedRunId!)}`}>查看运行详情</Link>
              </div>
            ) : (
              <ul className="resource-list" aria-label={`${title}产物`}>
                {artifacts.map((artifact) => (
                  <li key={`${artifact.relative_path}-${artifact.url}`}>
                    <a href={artifact.url} target="_blank" rel="noreferrer">{artifact.relative_path}</a>
                    <span>{artifact.category} · {artifact.bytes} bytes · {artifact.media_type} · {artifact.sha256.slice(0, 12)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function ErrorState({ error, onRetry }: { error: Error; onRetry(): void }) {
  return (
    <div className="async-state async-error" role="alert">
      <p>{error.message || "加载失败"}</p>
      <button className="button-secondary" type="button" onClick={onRetry}>重试</button>
    </div>
  );
}
