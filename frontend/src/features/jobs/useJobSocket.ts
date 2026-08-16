import { useEffect, useRef } from "react";

export interface JobEvent {
  type: string;
  kind?: string;
  run_id?: string;
  status?: string;
}

/**
 * 订阅项目 Job 状态 WebSocket（spec §13.x/§22.6）。
 * 断线后指数退避重连；REST 轮询作为最终兜底（由调用方保留）。
 */
export function useJobSocket(
  projectId: string | undefined,
  onEvent: (event: JobEvent) => void,
) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!projectId) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let retry = 0;

    function connect() {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/api/v1/ws/projects/${projectId}/jobs`);
      socket.onmessage = (event) => {
        try {
          handlerRef.current(JSON.parse(event.data) as JobEvent);
        } catch {
          // 忽略非 JSON 帧
        }
      };
      socket.onclose = () => {
        if (!closed && retry < 5) {
          retry += 1;
          window.setTimeout(connect, 1000 * Math.min(retry, 5));
        }
      };
    }

    connect();
    return () => {
      closed = true;
      socket?.close();
    };
  }, [projectId]);
}
