import { Activity, Blocks, FlaskConical, ScrollText } from "lucide-react";
import type { HealthResponse } from "../../lib/api/types";
import { AsyncState } from "../../components/ui/AsyncState";

interface SystemHealthBarProps {
  health: HealthResponse | undefined;
  loading: boolean;
  error: Error | null;
  onRetry(): void;
}

export function SystemHealthBar({ health, loading, error, onRetry }: SystemHealthBarProps) {
  return (
    <section className="dashboard-card system-health-bar" aria-labelledby="system-health-heading">
      <h2 id="system-health-heading">系统健康</h2>
      {loading ? (
        <p className="health-loading" aria-live="polite">正在检查服务…</p>
      ) : (
        <AsyncState loading={false} error={error} empty={!health} onRetry={onRetry}>
          {health ? (
            <ul className="health-facts">
              <li><Activity aria-hidden="true" /><span>服务</span><strong>服务正常</strong></li>
              <li><FlaskConical aria-hidden="true" /><span>正式实验</span><strong>{health.formal_experiment_enabled ? "正式实验已启用" : "正式实验未启用"}</strong></li>
              <li><ScrollText aria-hidden="true" /><span>结果论文</span><strong>{health.result_paper_enabled ? "结果论文已启用" : "结果论文未启用"}</strong></li>
              <li><Blocks aria-hidden="true" /><span>批量执行</span><strong>{health.batch_execution_configured ? "批量执行已配置" : "批量执行未配置"}</strong></li>
              <li><Blocks aria-hidden="true" /><span>自进化</span><strong>{health.self_evolution_service_configured ? "自进化已配置" : "自进化未配置"}</strong></li>
            </ul>
          ) : null}
        </AsyncState>
      )}
    </section>
  );
}
