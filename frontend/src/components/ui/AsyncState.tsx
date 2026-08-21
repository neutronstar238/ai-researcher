import type { ReactNode } from "react";

export interface AsyncStateProps {
  loading: boolean;
  error: Error | null;
  empty: boolean;
  onRetry(): void;
  children: ReactNode;
}

export function AsyncState({ loading, error, empty, onRetry, children }: AsyncStateProps) {
  if (loading) {
    return <div className="async-state async-loading" role="status">正在加载…</div>;
  }
  if (error) {
    return (
      <div className="async-state async-error" role="alert">
        <p>{error.message || "加载失败"}</p>
        <button className="button-secondary" type="button" onClick={onRetry}>重试</button>
      </div>
    );
  }
  if (empty) {
    return <div className="async-state async-empty">暂无数据</div>;
  }
  return children;
}
