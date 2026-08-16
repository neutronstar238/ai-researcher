import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { useCreateExperiment, useCreateRun, useExperiments } from "../features/experiments/api";
import { useCycles } from "../features/projects/api";

export function ExperimentsPage() {
  const { projectId } = useParams();
  const { data: experiments } = useExperiments(projectId);
  const { data: cycles } = useCycles(projectId);
  const createExperiment = useCreateExperiment(projectId);
  const createRun = useCreateRun(projectId);

  const [showForm, setShowForm] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [entrypoint, setEntrypoint] = useState('python -c "print(1)"');
  const [runResults, setRunResults] = useState<Record<string, { status: string; exit_code: number | null; log: string }>>({});

  const activeCycleId = cycles?.find((c) => c.status === "active")?.id ?? cycles?.[0]?.id;

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!activeCycleId) return;
    createExperiment.mutate({ cycle_id: activeCycleId, code, name, entrypoint });
    setShowForm(false);
    setCode("");
    setName("");
  }

  async function handleRun(experimentId: string) {
    const run = await createRun.mutateAsync(experimentId);
    setRunResults((prev) => ({
      ...prev,
      [experimentId]: { status: run.status, exit_code: run.exit_code, log: run.log_output ?? "" },
    }));
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text">实验管理</h2>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover"
        >
          新建实验
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="card mb-4 space-y-3">
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="code（如 E2）" className="w-full rounded-md border border-border-strong px-3 py-2 text-sm" required />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="实验名称" className="w-full rounded-md border border-border-strong px-3 py-2 text-sm" required />
          <input value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} placeholder="入口命令" className="w-full rounded-md border border-border-strong px-3 py-2 text-sm font-mono" required />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowForm(false)} className="rounded-md px-4 py-2 text-sm text-text-secondary">取消</button>
            <button type="submit" disabled={createExperiment.isPending} className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50">创建</button>
          </div>
        </form>
      )}

      <div className="space-y-3">
        {experiments?.map((experiment) => {
          const result = runResults[experiment.id];
          return (
            <div key={experiment.id} className="card">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-mono text-xs text-text-muted">{experiment.code}</div>
                  <div className="text-sm font-medium text-text">{experiment.name}</div>
                  <div className="mt-1 truncate font-mono text-xs text-text-muted">{experiment.entrypoint}</div>
                </div>
                <button
                  type="button"
                  onClick={() => handleRun(experiment.id)}
                  disabled={createRun.isPending}
                  className="rounded-md bg-primary-soft px-3 py-1.5 text-xs text-primary hover:bg-primary hover:text-white disabled:opacity-50"
                >
                  运行
                </button>
              </div>
              {result && (
                <div className="mt-2 rounded-md bg-surface-subtle px-3 py-2 text-xs">
                  <span className={result.status === "succeeded" ? "text-success" : "text-danger"}>
                    {result.status} · exit {result.exit_code}
                  </span>
                  {result.log && <pre className="mt-1 whitespace-pre-wrap text-text-muted">{result.log}</pre>}
                </div>
              )}
            </div>
          );
        })}
        {experiments?.length === 0 && <p className="card py-8 text-center text-sm text-text-muted">暂无实验</p>}
      </div>
    </div>
  );
}
