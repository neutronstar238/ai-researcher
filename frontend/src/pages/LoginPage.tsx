import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../stores/authStore";

export function LoginPage() {
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("owner@airesearcher.local");
  const [password, setPassword] = useState("demo-password");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? "/";

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page">
      <form onSubmit={handleSubmit} className="card w-[380px]">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-primary text-white">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
              <circle cx="6" cy="12" r="1.6" fill="currentColor" />
              <circle cx="12" cy="6" r="1.6" fill="currentColor" />
              <circle cx="12" cy="18" r="1.6" fill="currentColor" />
              <circle cx="18" cy="12" r="1.6" fill="currentColor" />
              <path d="M7.2 10.8 10.8 7.2M13.2 16.8l3.6-3.6M7.2 13.2l3.6 3.6M13.2 7.2l3.6 3.6" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </div>
          <div>
            <div className="text-[22px] font-bold leading-[30px] text-brand-dark">研启智链</div>
            <div className="text-xs text-text-muted">AI-Researcher 自动科研平台</div>
          </div>
        </div>

        <label className="mb-1 block text-sm text-text-secondary">邮箱</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mb-4 w-full rounded-md border border-border-strong px-3 py-2 text-sm"
          autoComplete="username"
        />

        <label className="mb-1 block text-sm text-text-secondary">密码</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-4 w-full rounded-md border border-border-strong px-3 py-2 text-sm"
          autoComplete="current-password"
        />

        {error && <div className="mb-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</div>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-primary py-2.5 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {submitting ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}
