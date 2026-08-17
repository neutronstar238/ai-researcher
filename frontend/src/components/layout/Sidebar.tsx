import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink, useParams } from "react-router-dom";

import { useProjectStore } from "../../stores/projectStore";
import { useUIStore } from "../../stores/uiStore";
import { NAV_ITEMS, resolveNavPath } from "./nav";

export function Sidebar() {
  const collapsed = useUIStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUIStore((state) => state.toggleSidebar);
  // 优先取 URL 里的真实项目 ID（store 只在 Dashboard 页设置、离开即清空，不可靠）
  const { projectId: urlProjectId } = useParams();
  const storeProjectId = useProjectStore((state) => state.currentProjectId);
  const currentProjectId = urlProjectId ?? storeProjectId;

  return (
    <aside
      className={`flex h-screen flex-col border-r border-border bg-surface-subtle transition-[width] ${
        collapsed ? "w-[72px]" : "w-[220px]"
      }`}
    >
      <div className="flex h-[90px] items-center gap-3 px-5">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary text-white">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
            <circle cx="6" cy="12" r="1.6" fill="currentColor" />
            <circle cx="12" cy="6" r="1.6" fill="currentColor" />
            <circle cx="12" cy="18" r="1.6" fill="currentColor" />
            <circle cx="18" cy="12" r="1.6" fill="currentColor" />
            <path d="M7.2 10.8 10.8 7.2M13.2 16.8l3.6-3.6M7.2 13.2l3.6 3.6M13.2 7.2l3.6 3.6" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="text-[22px] font-bold leading-[30px] text-brand-dark">研启智链</div>
            <div className="text-xs leading-[18px] text-text-muted">AI-Researcher / 研究辅助中心</div>
          </div>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-2 overflow-y-auto px-3 py-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const to = resolveNavPath(item.path, currentProjectId);
          return (
            <NavLink
              key={item.key}
              to={to}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) =>
                `flex h-11 shrink-0 items-center gap-3 rounded-lg px-4 text-sm text-text-secondary hover:bg-[#eef2f7] ${
                  isActive ? "bg-nav-active text-white hover:bg-nav-active" : ""
                } ${collapsed ? "justify-center px-0" : ""}`
              }
            >
              <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-border px-3 py-2">
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? "展开导航" : "收起导航"}
          className="flex h-11 w-full items-center gap-3 rounded-lg px-4 text-sm text-text-secondary hover:bg-[#eef2f7]"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-[18px] w-[18px]" strokeWidth={1.75} />
          ) : (
            <PanelLeftClose className="h-[18px] w-[18px]" strokeWidth={1.75} />
          )}
          {!collapsed && <span>收起导航</span>}
        </button>
      </div>
    </aside>
  );
}
