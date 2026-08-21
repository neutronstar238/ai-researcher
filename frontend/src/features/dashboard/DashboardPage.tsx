import { keepPreviousData, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { AsyncState } from "../../components/ui/AsyncState";
import { apiClient } from "../../lib/api/client";
import { toProductLifecycle } from "../../lib/domain/lifecycle";
import { selectCurrentRun } from "../../lib/domain/selectors";
import { CoverageChart } from "./CoverageChart";
import { CurrentProjectCard } from "./CurrentProjectCard";
import { LifecycleTimeline } from "./LifecycleTimeline";
import { RecentResearchCard } from "./RecentResearchCard";
import { SystemHealthBar } from "./SystemHealthBar";

export interface DashboardPageProps {
  onCreateRun?(): void;
  onOpenRun?(runId: string): void;
}

function CapabilityCard({ title, message }: { title: string; message: string }) {
  const headingId = "dashboard-capability-heading";
  return (
    <section className="dashboard-card dashboard-secondary-card capability-card" aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      <p>{message}</p>
    </section>
  );
}

const ACTIVE_RUN_STATUSES = new Set(["queued", "running", "cancel_requested"]);

function runTimestamp(run: { created_at: string; finished_at: string | null; started_at: string | null }): number {
  const timestamp = Date.parse(run.finished_at ?? run.started_at ?? run.created_at);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function latestSixRuns<T extends { run_id: string; created_at: string; finished_at: string | null; started_at: string | null }>(runs: T[]): T[] {
  return [...runs]
    .sort((left, right) => runTimestamp(right) - runTimestamp(left) || left.run_id.localeCompare(right.run_id))
    .slice(0, 6);
}

export function DashboardPage({ onCreateRun, onOpenRun }: DashboardPageProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const previousStageStatuses = useRef(new Map<string, string>());
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: apiClient.listRuns,
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: apiClient.health,
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const runs = runsQuery.data ?? [];
  const currentRun = selectCurrentRun(runs);
  const currentRunId = currentRun?.run_id;
  const detailQuery = useQuery({
    queryKey: ["run", currentRunId ?? null],
    queryFn: () => apiClient.getRun(currentRunId!),
    enabled: currentRunId !== undefined,
    refetchInterval: (query) => {
      const detailStatus = (query.state.data as typeof currentRun | undefined)?.status;
      const status = detailStatus ?? currentRun?.status;
      return status && ACTIVE_RUN_STATUSES.has(status) ? 5_000 : false;
    },
  });
  const detail = detailQuery.data?.run_id === currentRunId
    ? detailQuery.data
    : null;
  const selectedRuns = useMemo(() => latestSixRuns(runs), [runs]);
  const stageQueries = useQueries({
    queries: selectedRuns.map((run) => ({
      queryKey: ["run-stages", run.run_id],
      queryFn: () => apiClient.getStages(run.run_id),
      refetchInterval: ACTIVE_RUN_STATUSES.has(run.status) ? 5_000 : false,
    })),
  });
  useEffect(() => {
    const nextStatuses = new Map(selectedRuns.map((run) => [run.run_id, run.status]));
    for (const run of selectedRuns) {
      const previousStatus = previousStageStatuses.current.get(run.run_id);
      if (previousStatus && ACTIVE_RUN_STATUSES.has(previousStatus) && !ACTIVE_RUN_STATUSES.has(run.status)) {
        void queryClient.refetchQueries({ queryKey: ["run-stages", run.run_id], exact: true, type: "active" });
      }
    }
    previousStageStatuses.current = nextStatuses;
  }, [queryClient, selectedRuns]);
  const enrichedRuns = selectedRuns.map((run, index) => ({
    ...run,
    stages: detail?.run_id === run.run_id && detail.stages !== undefined
      ? detail.stages
      : stageQueries[index]?.data,
  }));
  const currentStages = enrichedRuns.find((run) => run.run_id === currentRunId)?.stages;
  const currentView = detail ?? (currentRun ? { ...currentRun, stages: currentStages } : null);
  const lifecycle = toProductLifecycle(
    currentView?.stages ?? [],
    currentView?.status ?? "completed",
    null,
  );
  const openRun = onOpenRun ?? ((runId: string) => navigate(`/projects?run=${encodeURIComponent(runId)}`));
  const createRun = onCreateRun ?? (() => navigate("/projects"));

  return (
    <div
      className="dashboard-page"
      data-loading={runsQuery.isPending || runsQuery.isFetching || healthQuery.isPending || healthQuery.isFetching}
    >
      <h1 className="sr-only">研究总览</h1>
      <AsyncState
        loading={runsQuery.isPending}
        error={runsQuery.error}
        empty={false}
        onRetry={() => void runsQuery.refetch()}
      >
        <LifecycleTimeline
          stages={lifecycle}
          loading={Boolean(currentRun) && detailQuery.isPending && currentView?.stages === undefined}
          onRetry={() => void detailQuery.refetch()}
        />
        <div className="dashboard-grid" data-testid="dashboard-primary-grid">
          <CurrentProjectCard
            run={currentView}
            refreshError={detailQuery.error}
            onCreateRun={createRun}
            onOpenRun={openRun}
            onRetryDetails={() => void detailQuery.refetch()}
          />
          <RecentResearchCard runs={enrichedRuns} onOpenRun={openRun} />
        </div>
        <div className="dashboard-grid" data-testid="dashboard-secondary-grid">
          <CoverageChart runs={enrichedRuns} />
          <CapabilityCard title="待审批" message="当前服务未提供审批队列接口" />
        </div>
      </AsyncState>
      <SystemHealthBar
        health={healthQuery.data}
        loading={healthQuery.isPending}
        error={healthQuery.error}
        onRetry={() => void healthQuery.refetch()}
      />
    </div>
  );
}
