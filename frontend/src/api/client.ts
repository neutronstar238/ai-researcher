import { AppError } from "./errors";
import { tokenStorage } from "./tokenStorage";

const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    trace_id?: string;
    field_errors?: { field: string; message: string }[];
  };
}

export interface RequestOptions {
  /** 为 false 时跳过鉴权头与 401 自动刷新（用于 login/refresh）。 */
  auth?: boolean;
}

function requestId(): string {
  return typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : "";
}

/** 401 时用 HttpOnly Cookie 里的 refresh token 换新 access token，最多一次（spec §9.4/§18.3）。 */
async function tryRefresh(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Request-ID": requestId() },
    });
    if (!response.ok) return false;
    const body = (await response.json()) as { access_token: string };
    tokenStorage.set(body.access_token);
    return true;
  } catch {
    return false;
  }
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const { auth = true } = options;
  const headers: Record<string, string> = {
    "X-Request-ID": requestId(),
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...(init.headers as Record<string, string> | undefined),
  };
  if (auth) {
    const access = tokenStorage.getAccess();
    if (access) headers.Authorization = `Bearer ${access}`;
  }

  let response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });

  if (response.status === 401 && auth) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const access = tokenStorage.getAccess();
      headers.Authorization = `Bearer ${access}`;
      response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
    } else {
      tokenStorage.clear();
      window.dispatchEvent(new Event("ar:session-expired"));
    }
  }

  return handle<T>(response);
}

async function handle<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => null)) as (T & ErrorEnvelope) | null;
  if (!response.ok) {
    const err = (body as ErrorEnvelope | null)?.error;
    throw new AppError(
      err?.message ?? `请求失败 (HTTP ${response.status})`,
      err?.code ?? "HTTP_ERROR",
      response.status,
      err?.trace_id,
      err?.field_errors ?? [],
    );
  }
  return body as T;
}
