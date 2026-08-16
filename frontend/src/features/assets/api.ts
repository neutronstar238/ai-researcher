import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";

export interface Asset {
  id: string;
  kind: string;
  original_name: string | null;
  mime_type: string | null;
  size_bytes: number;
  sha256: string;
  status: string;
  created_at: string;
}

interface InitiateUpload {
  upload_id: string;
  object_key: string;
  upload_url: string | null;
  upload_urls: string[];
  bucket: string;
  mode: "single" | "multipart";
}

const MULTIPART_PART_SIZE = 5 * 1024 * 1024; // 5 MiB（除最后一片外 S3 最小分片）

async function uploadSingle(file: File, projectId: string, onProgress: (ratio: number) => void) {
  const mimeType = file.type || "application/octet-stream";
  const initiate = await request<InitiateUpload>(`/api/v1/projects/${projectId}/assets/uploads:initiate`, {
    method: "POST",
    body: JSON.stringify({ original_name: file.name, mime_type: mimeType, kind: "other" }),
  });
  const putResponse = await fetch(initiate.upload_url!, { method: "PUT", body: file });
  if (!putResponse.ok) throw new Error(`直传失败 (HTTP ${putResponse.status})`);
  onProgress(1);
  return request<Asset>(`/api/v1/projects/${projectId}/assets/uploads/${initiate.upload_id}:complete`, {
    method: "POST",
    body: JSON.stringify({ original_name: file.name, mime_type: mimeType, kind: "other" }),
  });
}

async function uploadMultipart(file: File, projectId: string, onProgress: (ratio: number) => void) {
  const mimeType = file.type || "application/octet-stream";
  const partCount = Math.ceil(file.size / MULTIPART_PART_SIZE);
  const initiate = await request<InitiateUpload>(`/api/v1/projects/${projectId}/assets/uploads:initiate`, {
    method: "POST",
    body: JSON.stringify({ original_name: file.name, mime_type: mimeType, kind: "other", part_count: partCount }),
  });

  const parts: { part_number: number; etag: string }[] = [];
  let uploaded = 0;
  for (let index = 0; index < partCount; index += 1) {
    const start = index * MULTIPART_PART_SIZE;
    const chunk = file.slice(start, Math.min(file.size, start + MULTIPART_PART_SIZE));
    const putResponse = await fetch(initiate.upload_urls[index], { method: "PUT", body: chunk });
    if (!putResponse.ok) throw new Error(`分片 ${index + 1} 上传失败 (HTTP ${putResponse.status})`);
    parts.push({ part_number: index + 1, etag: (putResponse.headers.get("ETag") ?? "").replace(/"/g, "") });
    uploaded += chunk.size;
    onProgress(uploaded / file.size);
  }

  return request<Asset>(`/api/v1/projects/${projectId}/assets/uploads/${initiate.upload_id}:complete`, {
    method: "POST",
    body: JSON.stringify({
      original_name: file.name,
      mime_type: mimeType,
      kind: "other",
      object_key: initiate.object_key,
      parts,
    }),
  });
}

export function useAssets(projectId: string | undefined) {
  return useQuery<Asset[]>({
    queryKey: ["assets", projectId],
    queryFn: () => request<Asset[]>(`/api/v1/projects/${projectId}/assets`),
    enabled: Boolean(projectId),
  });
}

/** 上传：< 5 MiB 走单分片，≥ 5 MiB 走分片上传（spec §9.7）。 */
export function useUploadAsset(projectId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress: (ratio: number) => void }) =>
      file.size >= MULTIPART_PART_SIZE
        ? uploadMultipart(file, projectId!, onProgress)
        : uploadSingle(file, projectId!, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assets", projectId] }),
  });
}

export function useDownloadUrl(projectId: string | undefined) {
  return useMutation({
    mutationFn: (assetId: string) =>
      request<{ download_url: string; expires_in: number }>(
        `/api/v1/projects/${projectId}/assets/${assetId}/download-url`,
      ),
  });
}
