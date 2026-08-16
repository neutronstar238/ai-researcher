import { Bell, ChevronDown, CircleHelp, LogOut } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../../stores/authStore";
import { useProjectStore } from "../../stores/projectStore";
import { NAV_ITEMS, resolveNavPath } from "./nav";

export function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const currentProjectId = useProjectStore((state) => state.currentProjectId);
  const [menuOpen, setMenuOpen] = useState(false);

  const current = NAV_ITEMS.find(
    (item) => resolveNavPath(item.path, currentProjectId) === location.pathname,
  );
  const title = current?.label ?? "研究总览";

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <header className="flex h-[72px] items-center justify-between border-b border-border bg-surface px-6">
      <h1 className="text-[32px] font-bold leading-[40px] text-text">{title}</h1>

      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label="通知"
          className="grid h-9 w-9 place-items-center rounded-[10px] text-text-muted hover:bg-surface-subtle"
        >
          <Bell className="h-[18px] w-[18px]" strokeWidth={1.75} />
        </button>
        <button
          type="button"
          aria-label="帮助"
          className="grid h-9 w-9 place-items-center rounded-[10px] text-text-muted hover:bg-surface-subtle"
        >
          <CircleHelp className="h-[18px] w-[18px]" strokeWidth={1.75} />
        </button>

        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center gap-1 rounded-[10px] p-1 hover:bg-surface-subtle"
          >
            <span className="grid h-8 w-8 place-items-center rounded-full bg-primary text-white">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <circle cx="12" cy="8.6" r="3.4" />
                <path d="M5.2 19.4c1.5-3.4 3.9-5 6.8-5s5.3 1.6 6.8 5" />
              </svg>
            </span>
            <ChevronDown className="h-4 w-4 text-text-muted" strokeWidth={1.75} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-11 z-10 w-56 rounded-lg border border-border bg-surface p-1 shadow-popover">
              <div className="border-b border-border px-3 py-2">
                <div className="text-sm font-medium text-text">{user?.display_name}</div>
                <div className="truncate text-xs text-text-muted">{user?.email}</div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-danger hover:bg-danger-soft"
              >
                <LogOut className="h-4 w-4" /> 退出登录
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
