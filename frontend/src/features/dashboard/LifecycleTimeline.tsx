import {
  BookOpenCheck,
  ChartNoAxesCombined,
  FilePenLine,
  FlaskConical,
  Lightbulb,
  Rocket,
  ShieldCheck,
  Target,
  type LucideIcon,
} from "lucide-react";
import type { ProductStage } from "../../lib/domain/lifecycle";
import { AsyncState } from "../../components/ui/AsyncState";

const STAGE_ICONS: Record<string, LucideIcon> = {
  evolution: Rocket,
  experiment: FlaskConical,
  hypothesis: Lightbulb,
  literature: BookOpenCheck,
  reflection: ChartNoAxesCombined,
  topic: Target,
  validation: ShieldCheck,
  writing: FilePenLine,
};

const STATE_LABELS: Record<ProductStage["state"], string> = {
  active: "进行中",
  blocked: "阻塞",
  completed: "已完成",
  pending: "待开始",
};

interface LifecycleTimelineProps {
  stages: ProductStage[];
  loading?: boolean;
  error?: Error | null;
  onRetry?(): void;
}

export function LifecycleTimeline({
  stages,
  loading = false,
  error = null,
  onRetry = () => undefined,
}: LifecycleTimelineProps) {
  return (
    <section className="dashboard-card lifecycle-card" aria-labelledby="lifecycle-heading">
      <h2 id="lifecycle-heading">研究生命周期</h2>
      <AsyncState loading={loading} error={error} empty={false} onRetry={onRetry}>
        <ol className="lifecycle-list" aria-label="研究生命周期">
          {stages.map((stage) => {
            const Icon = STAGE_ICONS[stage.key] ?? Target;
            return (
              <li className="lifecycle-stage" data-state={stage.state} key={stage.key}>
                <span className="lifecycle-icon" aria-hidden="true"><Icon /></span>
                <strong>{stage.label}</strong>
                <span className="lifecycle-state">{STATE_LABELS[stage.state]}</span>
                <span className="lifecycle-progress">{stage.completed}/{stage.total}</span>
              </li>
            );
          })}
        </ol>
      </AsyncState>
    </section>
  );
}
