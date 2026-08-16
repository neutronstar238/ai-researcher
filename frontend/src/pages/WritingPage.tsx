import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import {
  useCreateDocument,
  useCreateSuggestion,
  useCreateVersion,
  useDecideSuggestion,
  useDocuments,
  useExportDocument,
  useIntegrityCheck,
  useSuggestions,
  useVersions,
} from "../features/writing/api";
import { useCycles } from "../features/projects/api";

const TYPE_LABELS: Record<string, string> = {
  manuscript: "论文手稿",
  reflection: "复盘报告",
  report: "报告",
};

export function WritingPage() {
  const { projectId } = useParams();
  const { data: documents } = useDocuments(projectId);
  const { data: cycles } = useCycles(projectId);
  const createDocument = useCreateDocument(projectId);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("manuscript");
  const [showVersion, setShowVersion] = useState(false);
  const [content, setContent] = useState("# 方法\n\n## 数据\n待补引用\n");
  const [changeSummary, setChangeSummary] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [showSuggest, setShowSuggest] = useState(false);
  const [proposed, setProposed] = useState("# 方法\n\n## 数据\n待补引用\n");

  const versions = useVersions(projectId, selectedId ?? undefined);
  const createVersion = useCreateVersion(projectId, selectedId ?? undefined);
  const integrity = useIntegrityCheck(projectId, selectedId ?? undefined);
  const exportDoc = useExportDocument(projectId, selectedId ?? undefined);
  const suggestions = useSuggestions(projectId, selectedId ?? undefined);
  const createSuggestion = useCreateSuggestion(projectId, selectedId ?? undefined);
  const decideSuggestion = useDecideSuggestion(projectId, selectedId ?? undefined);

  const activeCycleId = cycles?.find((c) => c.status === "active")?.id ?? cycles?.[0]?.id;

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!activeCycleId) return;
    try {
      const doc = await createDocument.mutateAsync({ cycle_id: activeCycleId, title, document_type: docType });
      setSelectedId(doc.id);
      setShowCreate(false);
      setTitle("");
      setFeedback(`已创建文档「${doc.title}」`);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function handleVersion(event: FormEvent) {
    event.preventDefault();
    try {
      await createVersion.mutateAsync({ content_markdown: content, change_summary: changeSummary || undefined });
      setShowVersion(false);
      setChangeSummary("");
      setFeedback("已保存新版本");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "保存版本失败");
    }
  }

  async function handleIntegrity() {
    setFeedback(null);
    const result = await integrity.mutateAsync();
    if (result.passed) setFeedback("完整性检查通过");
    else setFeedback(`完整性检查未通过：${result.errors.map((e) => e.code).join("、") || "无错误"}；警告 ${result.warnings.length} 条`);
  }

  async function handleExport() {
    setFeedback(null);
    try {
      const result = await exportDoc.mutateAsync();
      window.open(result.download_url, "_blank", "noopener");
      setFeedback(`已导出 Markdown（SHA-256 ${result.sha256.slice(0, 12)}…）`);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "导出失败");
    }
  }

  async function handleSuggest(event: FormEvent) {
    event.preventDefault();
    if (!selected?.current_version_id) {
      setFeedback("文档尚无版本，无法生成建议");
      return;
    }
    setFeedback(null);
    try {
      await createSuggestion.mutateAsync({ base_version_id: selected.current_version_id, proposed_markdown: proposed });
      setShowSuggest(false);
      setFeedback("已生成写作建议（待处理）");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "生成建议失败");
    }
  }

  async function handleDecide(suggestionId: string, decision: "accept" | "reject") {
    setFeedback(null);
    try {
      await decideSuggestion.mutateAsync({ suggestionId, decision });
      setFeedback(decision === "accept" ? "已采纳建议并创建新版本" : "已拒绝建议");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "处理建议失败");
    }
  }

  const selected = documents?.find((d) => d.id === selectedId);

  return (
    <div className="flex gap-4">
      <aside className="w-[280px] shrink-0 space-y-3">
        <div className="card">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text">文档</h3>
            <button type="button" onClick={() => setShowCreate((v) => !v)} className="rounded-md bg-primary-soft px-2.5 py-1 text-xs text-primary hover:bg-primary hover:text-white">新建</button>
          </div>
          {showCreate && (
            <form onSubmit={handleCreate} className="mt-3 space-y-2">
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题" className="w-full rounded-md border border-border-strong px-2.5 py-1.5 text-sm" required />
              <select value={docType} onChange={(e) => setDocType(e.target.value)} className="w-full rounded-md border border-border-strong px-2.5 py-1.5 text-sm">
                <option value="manuscript">论文手稿</option>
                <option value="report">报告</option>
              </select>
              <button type="submit" disabled={createDocument.isPending} className="w-full rounded-md bg-primary px-3 py-1.5 text-xs text-white disabled:opacity-50">创建</button>
            </form>
          )}
        </div>

        <div className="card space-y-1 p-2">
          {documents?.map((doc) => (
            <button
              key={doc.id}
              type="button"
              onClick={() => setSelectedId(doc.id)}
              className={`w-full rounded-md px-3 py-2 text-left text-sm ${selectedId === doc.id ? "bg-primary-soft text-primary" : "text-text-secondary hover:bg-surface-subtle"}`}
            >
              <div className="truncate">{doc.title}</div>
              <div className="text-xs text-text-muted">{TYPE_LABELS[doc.document_type] ?? doc.document_type} · {doc.status}</div>
            </button>
          ))}
          {documents?.length === 0 && <p className="py-6 text-center text-xs text-text-muted">暂无文档</p>}
        </div>
      </aside>

      <section className="min-w-0 flex-1 space-y-4">
        {feedback && <div className="rounded-md bg-surface-subtle px-3 py-2 text-sm text-text-secondary">{feedback}</div>}

        {selected ? (
          <>
            <div className="card">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-text">{selected.title}</h2>
                  <div className="text-xs text-text-muted">类型 {TYPE_LABELS[selected.document_type] ?? selected.document_type} · 状态 {selected.status}</div>
                </div>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setShowVersion((v) => !v)} className="rounded-md bg-primary px-3 py-1.5 text-xs text-white hover:bg-primary-hover">新建版本</button>
                  <button type="button" onClick={() => setShowSuggest((v) => !v)} className="rounded-md bg-primary-soft px-3 py-1.5 text-xs text-primary hover:bg-primary hover:text-white">写作建议</button>
                  <button type="button" onClick={handleIntegrity} disabled={integrity.isPending} className="rounded-md border border-border-strong px-3 py-1.5 text-xs text-text-secondary disabled:opacity-50">完整性检查</button>
                  <button type="button" onClick={handleExport} disabled={exportDoc.isPending} className="rounded-md bg-primary-soft px-3 py-1.5 text-xs text-primary hover:bg-primary hover:text-white disabled:opacity-50">导出</button>
                </div>
              </div>
              {showVersion && (
                <form onSubmit={handleVersion} className="mt-3 space-y-2">
                  <textarea value={content} onChange={(e) => setContent(e.target.value)} className="w-full rounded-md border border-border-strong px-3 py-2 font-mono text-sm" rows={8} required />
                  <input value={changeSummary} onChange={(e) => setChangeSummary(e.target.value)} placeholder="变更说明（可选）" className="w-full rounded-md border border-border-strong px-3 py-2 text-sm" />
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => setShowVersion(false)} className="rounded-md px-3 py-1.5 text-xs text-text-secondary">取消</button>
                    <button type="submit" disabled={createVersion.isPending} className="rounded-md bg-primary px-3 py-1.5 text-xs text-white disabled:opacity-50">保存版本</button>
                  </div>
                </form>
              )}
              {showSuggest && (
                <form onSubmit={handleSuggest} className="mt-3 space-y-2">
                  <textarea value={proposed} onChange={(e) => setProposed(e.target.value)} className="w-full rounded-md border border-border-strong px-3 py-2 font-mono text-sm" rows={6} required />
                  <p className="text-xs text-text-muted">在提案文本中修改内容，生成建议后可在下方接受（创建新版本，不覆盖当前）或拒绝。</p>
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => setShowSuggest(false)} className="rounded-md px-3 py-1.5 text-xs text-text-secondary">取消</button>
                    <button type="submit" disabled={createSuggestion.isPending || !selected.current_version_id} className="rounded-md bg-primary px-3 py-1.5 text-xs text-white disabled:opacity-50">生成建议</button>
                  </div>
                </form>
              )}
            </div>

            <div className="card">
              <h3 className="text-sm font-semibold text-text">写作建议（{suggestions.data?.length ?? 0}）</h3>
              <div className="mt-2 space-y-2">
                {suggestions.data?.map((suggestion) => (
                  <div key={suggestion.id} className="rounded-md border border-border px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-text-muted">
                        {new Date(suggestion.created_at).toLocaleString()} · +{suggestion.patch?.additions ?? 0}/-{suggestion.patch?.deletions ?? 0}
                      </span>
                      <span className={`rounded px-1.5 py-0.5 text-xs ${suggestion.status === "pending" ? "bg-warning-soft text-warning" : suggestion.status === "accepted" ? "bg-success-soft text-success" : "bg-surface-subtle text-text-muted"}`}>
                        {suggestion.status}
                      </span>
                    </div>
                    {suggestion.rendered_preview && (
                      <pre className="mt-2 max-h-28 overflow-auto rounded bg-surface-subtle px-2 py-1 font-mono text-xs text-text-secondary">{suggestion.rendered_preview}</pre>
                    )}
                    {suggestion.status === "pending" && (
                      <div className="mt-2 flex gap-2">
                        <button type="button" onClick={() => handleDecide(suggestion.id, "accept")} disabled={decideSuggestion.isPending} className="rounded-md bg-success px-2.5 py-1 text-xs text-white disabled:opacity-50">接受</button>
                        <button type="button" onClick={() => handleDecide(suggestion.id, "reject")} disabled={decideSuggestion.isPending} className="rounded-md border border-danger px-2.5 py-1 text-xs text-danger hover:bg-danger-soft disabled:opacity-50">拒绝</button>
                      </div>
                    )}
                  </div>
                ))}
                {suggestions.data?.length === 0 && <p className="py-4 text-center text-xs text-text-muted">暂无建议，点击「写作建议」生成</p>}
              </div>
            </div>

            <div className="card">
              <h3 className="text-sm font-semibold text-text">版本历史（{versions.data?.length ?? 0}）</h3>
              <div className="mt-2 space-y-2">
                {versions.data?.map((version) => (
                  <div key={version.id} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
                    <span className="font-medium text-text">v{version.version_no}</span>
                    <span className="text-xs text-text-muted">{version.change_summary ?? "—"}</span>
                    <span className="font-mono text-xs text-text-muted">{version.content_sha256.slice(0, 12)}…</span>
                    <span className="text-xs text-text-muted">{new Date(version.created_at).toLocaleString()}</span>
                  </div>
                ))}
                {versions.data?.length === 0 && <p className="py-4 text-center text-xs text-text-muted">尚无版本</p>}
              </div>
            </div>
          </>
        ) : (
          <div className="card py-16 text-center text-sm text-text-muted">选择左侧文档开始写作</div>
        )}
      </section>
    </div>
  );
}
