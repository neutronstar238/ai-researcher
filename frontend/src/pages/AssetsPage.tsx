import { useRef, useState, type ChangeEvent } from "react";
import { useParams } from "react-router-dom";

import { useAssets, useDownloadUrl, useUploadAsset } from "../features/assets/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function AssetsPage() {
  const { projectId } = useParams();
  const { data: assets } = useAssets(projectId);
  const upload = useUploadAsset(projectId);
  const download = useDownloadUrl(projectId);
  const fileInput = useRef<HTMLInputElement>(null);

  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      await upload.mutateAsync({ file, onProgress: (ratio) => setProgress(Math.round(ratio * 100)) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setProgress(0);
    }
  }

  async function handleDownload(assetId: string, name: string) {
    try {
      const { download_url } = await download.mutateAsync(assetId);
      window.open(download_url, "_blank", "noopener");
    } catch (err) {
      setError(err instanceof Error ? err.message : `下载 ${name} 失败`);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text">数据资产</h2>
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={upload.isPending}
          className="rounded-md bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {upload.isPending ? `上传中… ${progress}%` : "上传文件"}
        </button>
        <input ref={fileInput} type="file" className="hidden" onChange={handleFile} />
      </div>

      {upload.isPending && (
        <div className="mb-3 h-2 w-full overflow-hidden rounded-full bg-track">
          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} />
        </div>
      )}

      {error && <div className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</div>}

      <div className="card overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface-subtle text-xs text-text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">名称</th>
              <th className="px-4 py-2 font-medium">类型</th>
              <th className="px-4 py-2 font-medium">大小</th>
              <th className="px-4 py-2 font-medium">SHA-256</th>
              <th className="px-4 py-2 font-medium">状态</th>
              <th className="px-4 py-2 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {assets?.map((asset) => (
              <tr key={asset.id} className="hover:bg-surface-subtle">
                <td className="max-w-[220px] truncate px-4 py-2.5 text-text">{asset.original_name ?? "—"}</td>
                <td className="px-4 py-2.5 text-text-secondary">{asset.mime_type ?? asset.kind}</td>
                <td className="px-4 py-2.5 tabular-nums text-text-secondary">{formatBytes(asset.size_bytes)}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-text-muted">
                  {asset.sha256.slice(0, 12)}…
                </td>
                <td className="px-4 py-2.5">
                  <span className="rounded bg-success-soft px-1.5 py-0.5 text-xs text-success">{asset.status}</span>
                </td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    type="button"
                    onClick={() => handleDownload(asset.id, asset.original_name ?? "asset")}
                    className="rounded-md bg-primary-soft px-2.5 py-1 text-xs text-primary hover:bg-primary hover:text-white"
                  >
                    下载
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {assets?.length === 0 && <p className="py-10 text-center text-sm text-text-muted">暂无资产，点击「上传文件」添加</p>}
      </div>
    </div>
  );
}
