import type { RunRecord, RunStatus, StageRecord } from "../api/types";

const ACTIVE_RUN_STATUSES = new Set<RunStatus>([
  "queued",
  "running",
  "cancel_requested",
]);

function runTimestamp(run: RunRecord): number {
  const timestamp = Date.parse(run.finished_at ?? run.created_at);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function newestRun(runs: RunRecord[]): RunRecord | null {
  return [...runs].sort((left, right) => {
    const timestampDifference = runTimestamp(right) - runTimestamp(left);
    return timestampDifference || left.run_id.localeCompare(right.run_id);
  })[0] ?? null;
}

export function selectCurrentRun(runs: RunRecord[]): RunRecord | null {
  return newestRun(runs.filter((run) => ACTIVE_RUN_STATUSES.has(run.status))) ?? newestRun(runs);
}

export function coveragePercent(stages: StageRecord[]): number | null {
  if (stages.length === 0) return null;

  const completed = stages.filter((stage) => stage.status === "completed").length;
  return Math.round((completed / stages.length) * 100);
}
