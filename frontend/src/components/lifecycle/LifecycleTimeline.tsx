import type { StageOut } from "../../features/dashboard/api";

const STAGE_STATE: Record<string, { label: string; color: string; bg: string }> = {
  completed: { label: "已完成", color: "text-success", bg: "bg-success" },
  running: { label: "进行中", color: "text-primary", bg: "bg-primary" },
  waiting_approval: { label: "待审批", color: "text-warning", bg: "bg-warning" },
  blocked: { label: "已阻塞", color: "text-danger", bg: "bg-danger" },
  failed: { label: "失败", color: "text-danger", bg: "bg-danger" },
  ready: { label: "就绪", color: "text-primary", bg: "bg-primary" },
  pending: { label: "待开始", color: "text-disabled", bg: "bg-disabled" },
};

export function LifecycleTimeline({ stages }: { stages: StageOut[] }) {
  return (
    <div className="relative flex justify-between">
      <div className="absolute left-[6%] right-[6%] top-[27px] h-0.5 bg-border-strong" />
      {stages.map((stage) => {
        const state = STAGE_STATE[stage.status] ?? STAGE_STATE.pending;
        const active = stage.status === "running";
        return (
          <div key={stage.stage_key} className="relative flex w-[110px] flex-col items-center text-center">
            <div
              className={`relative z-10 grid h-14 w-14 place-items-center rounded-full text-white ${
                active ? "ring-4 ring-primary-soft" : ""
              } ${state.bg}`}
            >
              {stage.status === "completed" ? (
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.6">
                  <path d="M6.5 12.5l3.8 3.8 7.2-8" />
                </svg>
              ) : (
                <span className="tabular-nums text-sm font-semibold">{stage.progress > 0 ? `${Math.round(stage.progress)}` : ""}</span>
              )}
            </div>
            <div className="mt-2 text-sm font-semibold text-text">{stage.label_zh}</div>
            <div className={`text-xs ${state.color}`}>{state.label}</div>
            {stage.evidence_count > 0 && (
              <div className="text-xs text-text-muted">{stage.evidence_count} 证据</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
