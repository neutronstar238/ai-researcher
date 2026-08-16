import { useHealthSummary } from "../features/system/api";
import { useAuthStore } from "../stores/authStore";

const DEP_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
};

function ConfigRow({ label, configured }: { label: string; configured: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
      <span className="text-sm text-text">{label}</span>
      <span className={`rounded px-1.5 py-0.5 text-xs ${configured ? "bg-success-soft text-success" : "bg-warning-soft text-warning"}`}>
        {configured ? "已配置" : "未配置"}
      </span>
    </div>
  );
}

export function SettingsPage() {
  const { data: health } = useHealthSummary();
  const user = useAuthStore((s) => s.user);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h2 className="text-lg font-semibold text-text">系统设置</h2>

      <section className="card">
        <h3 className="text-sm font-semibold text-text">当前账户</h3>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between"><dt className="text-text-muted">邮箱</dt><dd className="text-text">{user?.email ?? "—"}</dd></div>
          <div className="flex justify-between"><dt className="text-text-muted">显示名</dt><dd className="text-text">{user?.display_name ?? "—"}</dd></div>
          <div className="flex justify-between"><dt className="text-text-muted">时区</dt><dd className="text-text">{user?.timezone ?? "—"}</dd></div>
          <div className="flex justify-between"><dt className="text-text-muted">状态</dt><dd className="text-text">{user?.status ?? "—"}</dd></div>
        </dl>
      </section>

      <section className="card">
        <h3 className="text-sm font-semibold text-text">依赖状态</h3>
        <div className="mt-3 space-y-2">
          {Object.entries(health?.checks ?? {}).map(([key, check]) => (
            <div key={key} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
              <span className="text-sm text-text">{DEP_LABELS[key] ?? key}</span>
              <span className={`rounded px-1.5 py-0.5 text-xs ${check.status === "healthy" ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`}>
                {check.status === "healthy" ? "健康" : `异常${check.error ? `（${check.error}）` : ""}`}
              </span>
            </div>
          ))}
          {!health && <p className="py-4 text-center text-xs text-text-muted">加载中…</p>}
        </div>
      </section>

      <section className="card">
        <h3 className="text-sm font-semibold text-text">外部 Provider</h3>
        <div className="mt-3 space-y-2">
          <ConfigRow label="LLM 编排（§16）" configured={health?.llm_configured ?? false} />
          <ConfigRow label="语义 Embedding（§13）" configured={health?.embedding_configured ?? false} />
          <ConfigRow label="隔离实验 Runner（§15.3）" configured={health?.experiment_runner_configured ?? false} />
        </div>
        <p className="mt-3 text-xs text-text-muted">
          未配置的 Provider 会以明确的「未配置」状态降级，绝不伪造结果（spec §23.4）。
        </p>
      </section>
    </div>
  );
}
