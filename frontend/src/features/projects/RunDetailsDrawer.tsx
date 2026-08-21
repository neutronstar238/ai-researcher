import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AsyncState } from "../../components/ui/AsyncState";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Drawer } from "../../components/ui/Drawer";
import { useToast } from "../../components/ui/ToastRegion";
import { apiClient } from "../../lib/api/client";
import type { ArtifactRecord, RunRecord, RunStatus, StageRecord } from "../../lib/api/types";

export interface RunDetailsDrawerProps {
  runId: string;
  onClose(): void;
}

const CANCELABLE_STATUSES = new Set<RunStatus>(["queued", "running"]);
const RESUMABLE_STATUSES = new Set<RunStatus>(["canceled", "completed", "failed", "interrupted"]);
const ACTIVE_STATUSES = new Set<RunStatus>(["queued", "running", "cancel_requested"]);

export function RunDetailsDrawer({ runId, onClose }: RunDetailsDrawerProps) {
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedOutput, setSelectedOutput] = useState<ArtifactRecord | null>(null);
  const actionPendingRef = useRef(false);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => apiClient.getRun(runId),
    refetchInterval: (query) => {
      const status = (query.state.data as RunRecord | undefined)?.status;
      return status && ACTIVE_STATUSES.has(status)
        ? 5_000
        : false;
    },
  });
  const resumeMutation = useMutation({ mutationFn: () => apiClient.resumeRun(runId) });
  const cancelMutation = useMutation({ mutationFn: () => apiClient.cancelRun(runId) });
  const evolutionMutation = useMutation({ mutationFn: () => apiClient.startEvolution(runId) });
  const run = runQuery.data?.run_id === runId ? runQuery.data : null;
  const identityError = runQuery.data && runQuery.data.run_id !== runId
    ? new Error("运行详情与所选 ID 不一致")
    : null;
  const previewQuery = useQuery({
    queryKey: ["artifact-preview", runId, selectedOutput?.url],
    queryFn: async () => parseModelPreview(await apiClient.getArtifactText(selectedOutput!.url)),
    enabled: selectedOutput !== null,
    staleTime: Infinity,
  });
  const visibleStages = run ? inferActiveStage(run.stages ?? [], run.status) : [];

  const invalidateRunData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["runs"] }),
      queryClient.invalidateQueries({ queryKey: ["run", runId] }),
      queryClient.invalidateQueries({ queryKey: ["run-stages", runId] }),
    ]);
  };

  const runAction = async (action: () => Promise<unknown>, successMessage: string) => {
    if (actionPendingRef.current) return;
    actionPendingRef.current = true;
    setActionError(null);
    try {
      await action();
      await invalidateRunData();
      if (mountedRef.current) notify({ tone: "success", message: successMessage });
    } catch (error) {
      if (mountedRef.current) setActionError(errorMessage(error));
    } finally {
      actionPendingRef.current = false;
    }
  };

  const handleEvolution = async () => {
    if (actionPendingRef.current) return;
    actionPendingRef.current = true;
    setActionError(null);
    try {
      await evolutionMutation.mutateAsync();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["evolution", runId] }),
        queryClient.invalidateQueries({ queryKey: ["skills"] }),
      ]);
      if (mountedRef.current) notify({ tone: "success", message: "进化候选任务已发起" });
    } catch (error) {
      if (mountedRef.current) setActionError(errorMessage(error));
    } finally {
      actionPendingRef.current = false;
    }
  };

  const confirmCancel = async () => {
    await cancelMutation.mutateAsync();
    await invalidateRunData();
    if (mountedRef.current) notify({ tone: "success", message: "取消请求已提交" });
  };

  return (
    <Drawer open wide title="运行详情" onClose={onClose}>
      <AsyncState
        loading={runQuery.isPending}
        error={runQuery.error ?? identityError}
        empty={!runQuery.isPending && !runQuery.error && !identityError && run === null}
        onRetry={() => void runQuery.refetch()}
      >
        {run ? (
          <div className="run-details">
            <div className="run-detail-heading">
              <p className="run-direction">{run.direction}</p>
              <span className="status-badge" data-status={run.status}>{run.status}</span>
            </div>
            {run.error ? <p className="run-error" role="alert">{run.error.message}</p> : null}
            <dl className="run-detail-facts">
              <div><dt>运行 ID</dt><dd><code>{run.run_id}</code></dd></div>
              <div><dt>创建时间</dt><dd><time dateTime={run.created_at}>{formatDate(run.created_at)}</time></dd></div>
              <div><dt>恢复次数</dt><dd>{run.resume_count}</dd></div>
            </dl>

            <section className="run-detail-section" aria-labelledby="run-stage-heading">
              <h3 id="run-stage-heading">十二阶段</h3>
              {visibleStages.length ? (
                <ol className="run-stage-list" aria-label="研究阶段">
                  {visibleStages.map((stage) => (
                    <li key={`${stage.ordinal}-${stage.stage_name}`} aria-label={`阶段 ${stage.ordinal} ${stage.label_zh}`}>
                      <span>{stage.ordinal}. {stage.label_zh}</span>
                      <span className="stage-status" data-status={stage.status}>{stageStatusLabel(stage.status)}</span>
                      <span>{stage.artifact_count} 个产物</span>
                      <code>{stage.checkpoint_hash?.slice(0, 10) ?? "无检查点"}</code>
                    </li>
                  ))}
                </ol>
              ) : <p className="detail-empty">服务未返回阶段数据</p>}
            </section>

            <PlanDeliverablesSection artifacts={run.artifacts ?? []} />

            <ModelOutputsSection
              artifacts={run.artifacts ?? []}
              selected={selectedOutput}
              preview={previewQuery.data}
              previewError={previewQuery.error}
              previewLoading={previewQuery.isFetching}
              onSelect={setSelectedOutput}
            />

            <CallTraceSection artifacts={run.artifacts ?? []} stages={visibleStages} />

            <ArtifactGroupsSection artifacts={run.artifacts ?? []} />

            {actionError ? <p className="form-error" role="alert">{actionError}</p> : null}
            <div className="run-actions" aria-label="运行操作">
              {CANCELABLE_STATUSES.has(run.status) ? (
                <button className="button-danger" type="button" onClick={() => setCancelOpen(true)}>请求取消</button>
              ) : null}
              {RESUMABLE_STATUSES.has(run.status) ? (
                <button
                  className="button-secondary"
                  type="button"
                  disabled={resumeMutation.isPending || evolutionMutation.isPending}
                  onClick={() => void runAction(() => resumeMutation.mutateAsync(), "研究运行已恢复")}
                >
                  {resumeMutation.isPending ? "恢复中…" : "恢复运行"}
                </button>
              ) : null}
              {run.status === "completed" ? (
                <div className="evolution-action">
                  <button
                    className="button-primary"
                    type="button"
                    disabled={evolutionMutation.isPending || resumeMutation.isPending}
                    onClick={() => void handleEvolution()}
                  >
                    {evolutionMutation.isPending ? "发起中…" : "发起进化"}
                  </button>
                  <small>仅生成候选并验证，不授权 Skill 晋级</small>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </AsyncState>
      <ConfirmDialog
        open={cancelOpen}
        title="取消运行"
        description="取消只会请求后端在安全边界停止；运行中的同步任务可能继续到当前边界。"
        confirmLabel="确认取消"
        danger
        onConfirm={confirmCancel}
        onClose={() => setCancelOpen(false)}
      />
    </Drawer>
  );
}

function PlanDeliverablesSection({ artifacts }: { artifacts: ArtifactRecord[] }) {
  const deliverables = artifacts.filter(isPrimaryPlanArtifact);
  if (!deliverables.length) return null;
  return (
    <section className="run-detail-section" aria-labelledby="plan-deliverable-heading">
      <div className="run-section-heading">
        <h3 id="plan-deliverable-heading">研究计划交付件</h3>
        <span>{deliverables.length} 份</span>
      </div>
      <div className="plan-deliverables">
        {deliverables.map((artifact) => {
          const pdf = artifact.relative_path.toLowerCase().endsWith(".pdf");
          return (
            <a key={artifact.url} href={artifact.url} target="_blank" rel="noreferrer">
              <span className="plan-file-badge">{pdf ? "PDF" : "MD"}</span>
              <span>
                <strong>{pdf ? "PDF 研究计划" : "Markdown 研究计划"}</strong>
                <small>{formatBytes(artifact.bytes)} · 点击查看或下载</small>
              </span>
            </a>
          );
        })}
      </div>
    </section>
  );
}

interface ModelPreview {
  modelName: string | null;
  content: string;
}

function ModelOutputsSection({
  artifacts,
  selected,
  preview,
  previewError,
  previewLoading,
  onSelect,
}: {
  artifacts: ArtifactRecord[];
  selected: ArtifactRecord | null;
  preview: ModelPreview | undefined;
  previewError: Error | null;
  previewLoading: boolean;
  onSelect(artifact: ArtifactRecord): void;
}) {
  const outputs = artifacts.filter(isModelOutput);
  return (
    <section className="run-detail-section" aria-labelledby="model-output-heading">
      <div className="run-section-heading">
        <h3 id="model-output-heading">模型实际输出</h3>
        <span>{outputs.length} 份</span>
      </div>
      {outputs.length ? (
        <>
          <div className="model-output-picker" role="list" aria-label="模型输出">
            {outputs.map((artifact) => (
              <button
                className={selected?.url === artifact.url ? "is-selected" : ""}
                key={artifact.url}
                type="button"
                onClick={() => onSelect(artifact)}
              >
                <strong>{fileName(artifact.relative_path)}</strong>
                <span>{formatBytes(artifact.bytes)}</span>
              </button>
            ))}
          </div>
          {selected ? (
            <div className="model-output-preview" aria-live="polite">
              <div>
                <strong>{fileName(selected.relative_path)}</strong>
                <a href={selected.url} target="_blank" rel="noreferrer">打开原始产物</a>
              </div>
              {previewLoading ? <p className="detail-empty">正在读取模型输出…</p> : null}
              {previewError ? <p className="form-error" role="alert">模型输出读取失败</p> : null}
              {preview ? (
                <>
                  {preview.modelName ? <small>调用模型：{preview.modelName}</small> : null}
                  <pre>{preview.content}</pre>
                </>
              ) : null}
            </div>
          ) : <p className="detail-empty">选择一份响应即可在此查看模型返回的结构化正文。</p>}
        </>
      ) : <p className="detail-empty">当前阶段尚未生成可公开展示的模型响应。</p>}
    </section>
  );
}

function CallTraceSection({ artifacts, stages }: { artifacts: ArtifactRecord[]; stages: StageRecord[] }) {
  const traces = buildCallTraces(artifacts, stages);
  return (
    <section className="run-detail-section" aria-labelledby="call-trace-heading">
      <div className="run-section-heading">
        <h3 id="call-trace-heading">模型调用路径</h3>
        <span>{traces.length} 个阶段</span>
      </div>
      {traces.length ? (
        <ol className="call-trace-list">
          {traces.map((trace) => (
            <li key={trace.stage.stage_name}>
              <div>
                <strong>{trace.stage.ordinal}. {trace.stage.label_zh}</strong>
                <span className="stage-status" data-status={trace.stage.status}>{stageStatusLabel(trace.stage.status)}</span>
              </div>
              <p>研究阶段 → 模型请求 × {trace.attempts} → 可查看响应 × {trace.outputs} → 阶段检查点</p>
              <code>{trace.stage.stage_name}</code>
            </li>
          ))}
        </ol>
      ) : <p className="detail-empty">当前尚无模型调用记录。</p>}
    </section>
  );
}

function ArtifactGroupsSection({ artifacts }: { artifacts: ArtifactRecord[] }) {
  const remaining = artifacts.filter((artifact) => (
    !isModelOutput(artifact)
    && !isProviderTraceArtifact(artifact)
    && !isPrimaryPlanArtifact(artifact)
  ));
  const grouped = remaining.reduce<Record<string, ArtifactRecord[]>>((result, artifact) => {
    (result[artifact.category] ??= []).push(artifact);
    return result;
  }, {});
  const groups = Object.entries(grouped)
    .sort(([left], [right]) => left.localeCompare(right));
  return (
    <section className="run-detail-section" aria-labelledby="run-artifact-heading">
      <div className="run-section-heading">
        <h3 id="run-artifact-heading">其他公开产物</h3>
        <span>{remaining.length} 份</span>
      </div>
      {groups.length ? groups.map(([category, items]) => (
        <details className="artifact-group" key={category}>
          <summary>{artifactCategoryLabel(category)}（{items.length}）</summary>
          <ul className="artifact-list">
            {items.map((artifact) => (
              <li key={`${artifact.relative_path}-${artifact.url}`}>
                <a href={artifact.url} target="_blank" rel="noreferrer">{artifact.relative_path}</a>
                <span>{formatBytes(artifact.bytes)} · {artifact.media_type}</span>
              </li>
            ))}
          </ul>
        </details>
      )) : <p className="detail-empty">暂无其他公开产物</p>}
    </section>
  );
}

function buildCallTraces(artifacts: ArtifactRecord[], stages: StageRecord[]) {
  const attempts = new Map<string, number>();
  const outputs = new Map<string, number>();
  for (const artifact of artifacts) {
    const attempt = artifact.relative_path.match(/^checkpoints\/provider-call-attempts\/([^/]+)\/.*reservation\.json$/i);
    if (attempt?.[1]) attempts.set(attempt[1], (attempts.get(attempt[1]) ?? 0) + 1);
    const outputStage = isModelOutput(artifact) ? modelOutputStage(artifact.relative_path) : null;
    if (outputStage) outputs.set(outputStage, (outputs.get(outputStage) ?? 0) + 1);
  }
  return stages
    .filter((stage) => attempts.has(stage.stage_name) || outputs.has(stage.stage_name))
    .map((stage) => ({
      stage,
      attempts: attempts.get(stage.stage_name) ?? 0,
      outputs: outputs.get(stage.stage_name) ?? 0,
    }));
}

function inferActiveStage(stages: StageRecord[], runStatus: RunStatus): StageRecord[] {
  if (!["running", "cancel_requested"].includes(runStatus) || stages.some((stage) => stage.status === "running")) {
    return stages;
  }
  let assigned = false;
  return stages.map((stage) => {
    if (!assigned && stage.status === "pending") {
      assigned = true;
      return { ...stage, status: "running" };
    }
    return stage;
  });
}

function isModelOutput(artifact: ArtifactRecord): boolean {
  return /(?:^|\/)[^/]+-response\.json$/i.test(artifact.relative_path);
}

function isProviderTraceArtifact(artifact: ArtifactRecord): boolean {
  return /^checkpoints\/provider-call-(?:attempts|reservations)\//i.test(artifact.relative_path);
}

function isPrimaryPlanArtifact(artifact: ArtifactRecord): boolean {
  return /^plan\/research-plan\.(?:md|pdf)$/i.test(artifact.relative_path);
}

function modelOutputStage(path: string): string | null {
  const lowered = path.toLowerCase();
  if (lowered.includes("gap-repair")) return "planning-literature-lock";
  if (lowered.includes("targeted")) return "targeted-literature-query";
  if (lowered.includes("focus")) return "focus-selection";
  if (lowered.includes("broad")) return "broad-literature-query";
  return null;
}

function parseModelPreview(raw: string): ModelPreview {
  const payload = JSON.parse(raw) as Record<string, unknown>;
  const completion = isRecord(payload.completion) ? payload.completion : payload;
  const modelName = typeof completion.model_name === "string" ? completion.model_name : null;
  const value = completion.parsed_json
    ?? completion.content
    ?? completion.response
    ?? completion.text
    ?? payload.output
    ?? payload.response;
  const content = typeof value === "string" ? value : value === undefined
    ? "该响应没有可显示的结构化正文，请打开原始产物查看。"
    : JSON.stringify(value, null, 2);
  const limit = 40_000;
  return {
    modelName,
    content: content.length > limit ? `${content.slice(0, limit)}\n\n……预览已截断，请打开原始产物查看完整内容。` : content,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function fileName(path: string): string {
  return path.split("/").at(-1) ?? path;
}

function stageStatusLabel(status: StageRecord["status"]): string {
  return { completed: "已完成", running: "执行中", pending: "待执行", invalid: "检查点异常" }[status];
}

function artifactCategoryLabel(category: string): string {
  return {
    evidence: "证据与检索",
    plan: "研究计划",
    review: "评审记录",
    runtime: "运行记录",
    internal: "系统产物",
    evolution: "进化候选",
    other: "其他",
  }[category] ?? category;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "操作失败，请重试。";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "时间不可用"
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatBytes(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  return `${(bytes / 1_024).toFixed(1)} KB`;
}
