import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import {
  LITERATURE_PROVIDERS,
  useCreateSearchRun,
  usePapers,
  useSavePaper,
  useSearchRun,
  type PaperResult,
} from "../features/literature/api";
import { useJobSocket } from "../features/jobs/useJobSocket";

export function LiteraturePage() {
  const { projectId } = useParams();
  const { data: papers } = usePapers(projectId);
  const createRun = useCreateSearchRun(projectId);
  const save = useSavePaper(projectId);

  const [query, setQuery] = useState("multimodal protein ligand interaction");
  const [provider, setProvider] = useState<string>("arxiv");
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<PaperResult[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useSearchRun(projectId, runId ?? undefined);
  const queryClient = useQueryClient();

  // WebSocket 实时刷新（§22.6）：收到 Job 终态事件立即 refetch，REST 轮询兜底
  useJobSocket(projectId, (event) => {
    if (event.kind === "literature_search" && event.run_id === runId && event.status && ["succeeded", "failed"].includes(event.status)) {
      queryClient.invalidateQueries({ queryKey: ["literature-run", projectId, runId] });
    }
  });

  useEffect(() => {
    if (run.data?.status === "succeeded") {
      setResults(run.data.result?.results ?? []);
      setNote(run.data.result?.note ?? null);
    } else if (run.data?.status === "failed") {
      setError(run.data.error ? JSON.stringify(run.data.error) : "检索失败");
    }
  }, [run.data]);

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNote(null);
    setResults([]);
    try {
      const { run_id } = await createRun.mutateAsync({ query, provider });
      setRunId(run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "检索失败");
    }
  }

  const searching = runId !== null && run.data && !["succeeded", "failed"].includes(run.data.status);

  return (
    <div className="space-y-4">
      <section className="card">
        <h2 className="text-lg font-semibold text-text">文献检索</h2>
        <form onSubmit={handleSearch} className="mt-3 flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 rounded-md border border-border-strong px-3 py-2 text-sm"
            placeholder="输入科研问题检索文献…"
          />
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="rounded-md border border-border-strong bg-surface px-2 py-2 text-sm"
            aria-label="文献源"
          >
            {LITERATURE_PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <button type="submit" disabled={searching || createRun.isPending} className="rounded-md bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover disabled:opacity-50">
            {searching || createRun.isPending ? "检索中…" : "检索"}
          </button>
        </form>
        {error && <div className="mt-2 text-sm text-danger">{error}</div>}
        {note && <div className="mt-2 text-sm text-text-muted">{note}</div>}
        {searching && (
          <div className="mt-2 text-sm text-text-muted">异步检索 Job 运行中（{run.data?.status}）…</div>
        )}
        {results.length > 0 && (
          <div className="mt-3 divide-y divide-border">
            {results.map((paper, i) => (
              <div key={i} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm text-text">{paper.title}</div>
                  <div className="text-xs text-text-muted">{paper.source} · {paper.publication_year ?? "—"}</div>
                </div>
                <button
                  type="button"
                  onClick={() => save.mutate({ title: paper.title, doi: paper.doi, publication_year: paper.publication_year, abstract: paper.abstract, external_id: paper.external_id, source: paper.source })}
                  className="shrink-0 rounded-md bg-primary-soft px-2.5 py-1 text-xs text-primary hover:bg-primary hover:text-white"
                >
                  加入项目
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="text-lg font-semibold text-text">项目论文（{papers?.length ?? 0}）</h2>
        <div className="mt-3 space-y-2">
          {papers?.map((paper) => (
            <div key={paper.id} className="rounded-md border border-border px-3 py-2">
              <div className="text-sm text-text">{paper.title}</div>
              <div className="text-xs text-text-muted">{paper.publication_year ?? "—"} · {paper.doi ?? paper.metadata_source ?? "—"}</div>
            </div>
          ))}
          {papers?.length === 0 && <p className="py-4 text-center text-sm text-text-muted">暂无论文</p>}
        </div>
      </section>
    </div>
  );
}
