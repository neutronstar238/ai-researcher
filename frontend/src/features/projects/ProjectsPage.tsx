import { keepPreviousData, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AsyncState } from "../../components/ui/AsyncState";
import { BatchDrawer } from "../batches/BatchDrawer";
import { apiClient } from "../../lib/api/client";
import type { BatchRecord, RunRecord, RunStatus, StageRecord } from "../../lib/api/types";
import { coveragePercent } from "../../lib/domain/selectors";
import { CreateRunDrawer } from "./CreateRunDrawer";
import { RunDetailsDrawer } from "./RunDetailsDrawer";

const ACTIVE_RUN_STATUSES = new Set<RunStatus>(["queued", "running", "cancel_requested"]);
const VISIBLE_RUN_LIMIT = 20;
const STATUS_OPTIONS: readonly RunStatus[] = [
  "queued",
  "running",
  "cancel_requested",
  "canceled",
  "completed",
  "failed",
  "interrupted",
  "dry_run",
];

interface RunRow {
  run: RunRecord;
  stages: StageRecord[] | undefined;
  stageError: Error | null;
  retryStages(): void;
}

export function ProjectsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const latestSearchParams = useRef(searchParams);
  latestSearchParams.current = searchParams;
  const queryClient = useQueryClient();
  const [batchOpen, setBatchOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const previousStatuses = useRef(new Map<string, RunStatus>());
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: apiClient.listRuns,
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const currentRuns = query.state.data as RunRecord[] | undefined;
      return currentRuns?.some((run) => ACTIVE_RUN_STATUSES.has(run.status)) ? 15_000 : false;
    },
  });
  const runs = runsQuery.data ?? [];
  const batchesQuery = useQuery({ queryKey: ["batches"], queryFn: apiClient.listBatches });
  const batches = batchesQuery.data ?? [];
  const query = searchParams.get("q") ?? "";
  const statusParam = searchParams.get("status") ?? "all";
  const selectedStatus = STATUS_OPTIONS.includes(statusParam as RunStatus) ? statusParam : "all";
  const selectedRunId = searchParams.get("run");
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const filteredRuns = runs.filter((run) => (
    (!normalizedQuery || run.direction.toLocaleLowerCase("zh-CN").includes(normalizedQuery))
    && (selectedStatus === "all" || run.status === selectedStatus)
  ));
  const visibleRuns = filteredRuns.slice(0, VISIBLE_RUN_LIMIT);
  const stageQueries = useQueries({
    queries: visibleRuns.map((run) => ({
      queryKey: ["run-stages", run.run_id],
      queryFn: () => apiClient.getStages(run.run_id),
      refetchInterval: ACTIVE_RUN_STATUSES.has(run.status) ? 5_000 : false,
    })),
  });
  const rows = useMemo<RunRow[]>(() => visibleRuns.map((run, index) => ({
    run,
    stages: stageQueries[index]?.data,
    stageError: stageQueries[index]?.error ?? null,
    retryStages: () => void stageQueries[index]?.refetch(),
  })), [visibleRuns, stageQueries]);

  useEffect(() => {
    const nextStatuses = new Map(visibleRuns.map((run) => [run.run_id, run.status]));
    for (const run of visibleRuns) {
      const previous = previousStatuses.current.get(run.run_id);
      if (previous && ACTIVE_RUN_STATUSES.has(previous) && !ACTIVE_RUN_STATUSES.has(run.status)) {
        void queryClient.refetchQueries({ queryKey: ["run-stages", run.run_id], exact: true, type: "active" });
      }
    }
    previousStatuses.current = nextStatuses;
  }, [queryClient, visibleRuns]);

  const updateSearchParam = (name: string, value: string, emptyValue: string) => {
    const next = new URLSearchParams(latestSearchParams.current);
    if (value === emptyValue) next.delete(name);
    else next.set(name, value);
    setSearchParams(next);
  };
  const selectRun = (runId: string) => {
    const next = new URLSearchParams(latestSearchParams.current);
    next.set("run", runId);
    setSearchParams(next);
  };
  const closeRun = () => {
    const next = new URLSearchParams(latestSearchParams.current);
    next.delete("run");
    setSearchParams(next);
  };

  return (
    <section className="projects-page" aria-labelledby="projects-heading">
      <div className="projects-heading-row">
        <div>
          <h1 id="projects-heading">项目空间</h1>
          <p>查看真实研究运行、阶段进度与公开产物。</p>
        </div>
        <div className="projects-primary-actions">
          <button className="button-secondary" type="button" onClick={() => setBatchOpen(true)}>
            批量任务
          </button>
          <button className="button-primary" type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" />
            新建研究
          </button>
        </div>
      </div>

      <div className="project-filters" role="search" aria-label="筛选研究运行">
        <label className="search-field">
          <span className="sr-only">搜索科学问题</span>
          <Search aria-hidden="true" />
          <input
            type="search"
            aria-label="搜索科学问题"
            placeholder="搜索科学问题"
            value={query}
            onChange={(event) => updateSearchParam("q", event.target.value, "")}
          />
        </label>
        <label className="status-filter">
          <span>运行状态</span>
          <select
            value={selectedStatus}
            onChange={(event) => updateSearchParam("status", event.target.value, "all")}
          >
            <option value="all">全部状态</option>
            {STATUS_OPTIONS.map((status) => <option value={status} key={status}>{status}</option>)}
          </select>
        </label>
      </div>

      <div className="projects-table-card">
        <AsyncState
          loading={runsQuery.isPending}
          error={runsQuery.error}
          empty={false}
          onRetry={() => void runsQuery.refetch()}
        >
          {runs.length === 0 ? (
            <div className="projects-empty">
              <strong>还没有研究运行</strong>
              <p>创建一个科学问题，服务端返回后会出现在这里。</p>
              <button className="button-primary" type="button" onClick={() => setCreateOpen(true)}>新建研究</button>
            </div>
          ) : filteredRuns.length === 0 ? (
            <div className="projects-empty"><strong>没有符合当前筛选条件的运行</strong></div>
          ) : (
            <div className="table-scroll">
              <table className="projects-table" aria-label="研究运行">
                <thead>
                  <tr>
                    <th scope="col">科学问题</th>
                    <th scope="col">状态</th>
                    <th scope="col">进度</th>
                    <th scope="col">创建时间</th>
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ run, stages, stageError, retryStages }) => (
                    <tr key={run.run_id}>
                      <th scope="row">{run.direction}</th>
                      <td><span className="status-badge" data-status={run.status}>{run.status}</span></td>
                      <td>{stageError ? (
                        <span className="progress-unavailable">
                          进度不可用
                          <button type="button" onClick={retryStages} aria-label={`重试${run.direction}的进度`}>重试</button>
                        </span>
                      ) : stages ? formatProgress(stages) : <span className="progress-pending">读取中…</span>}</td>
                      <td><time dateTime={run.created_at}>{formatDate(run.created_at)}</time></td>
                      <td><button className="table-action" type="button" onClick={() => selectRun(run.run_id)} aria-label={`查看${run.direction}`}>查看</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filteredRuns.length > VISIBLE_RUN_LIMIT ? (
                <p className="projects-result-limit">当前显示前 20 项匹配运行</p>
              ) : null}
            </div>
          )}
        </AsyncState>
      </div>

      <section className="batch-list-section" aria-label="批量任务记录">
        <div className="batch-list-heading">
          <div>
            <h2>批量任务</h2>
            <p>来自本地研究服务的公开批量回执。</p>
          </div>
        </div>
        <div className="projects-table-card batch-table-card">
          <AsyncState
            loading={batchesQuery.isPending}
            error={batchesQuery.error}
            empty={false}
            onRetry={() => void batchesQuery.refetch()}
          >
            {batches.length === 0 ? (
              <div className="projects-empty">
                <strong>尚无批量任务</strong>
                <p>创建后，服务端回执会按返回顺序显示在这里。</p>
              </div>
            ) : (
              <div className="table-scroll">
                <table className="projects-table batch-table" aria-label="批量任务记录">
                  <thead>
                    <tr>
                      <th scope="col">批量 ID</th>
                      <th scope="col">状态</th>
                      <th scope="col">题目数</th>
                      <th scope="col">创建时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {batches.map((batch) => <BatchRow batch={batch} key={batch.batch_id} />)}
                  </tbody>
                </table>
              </div>
            )}
          </AsyncState>
        </div>
      </section>

      {batchOpen ? <BatchDrawer open onClose={() => setBatchOpen(false)} /> : null}
      {createOpen ? (
        <CreateRunDrawer
          open
          onClose={() => setCreateOpen(false)}
          onCreated={(run) => {
            setCreateOpen(false);
            selectRun(run.run_id);
          }}
        />
      ) : null}
      {selectedRunId !== null ? <RunDetailsDrawer key={selectedRunId} runId={selectedRunId} onClose={closeRun} /> : null}
    </section>
  );
}

function BatchRow({ batch }: { batch: BatchRecord }) {
  return (
    <tr>
      <th scope="row">{batch.batch_id}</th>
      <td><span className="status-badge" data-status={batch.status}>{batch.status}</span></td>
      <td>{batch.question_count}</td>
      <td><time dateTime={batch.created_at}>{formatDate(batch.created_at)}</time></td>
    </tr>
  );
}

function formatProgress(stages: StageRecord[]): string {
  const progress = coveragePercent(stages);
  return progress === null ? "进度不可用" : `${progress}%`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "时间不可用"
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
