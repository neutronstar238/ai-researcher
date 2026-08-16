import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuthStore } from "../../stores/authStore";

export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-text-muted">加载中…</div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}
