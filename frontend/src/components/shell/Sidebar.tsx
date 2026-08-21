import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { NavLink } from "react-router-dom";
import logoUrl from "../../assets/ai-researcher-logo.png";
import { NAV_ITEMS } from "../../app/router";

interface SidebarNavigationProps {
  ariaLabel?: string;
  collapsed?: boolean;
  onNavigate?(): void;
}

export function SidebarNavigation({
  ariaLabel = "主导航",
  collapsed = false,
  onNavigate,
}: SidebarNavigationProps) {
  return (
    <nav className="sidebar-nav" aria-label={ariaLabel}>
      {NAV_ITEMS.map(([path, label, Icon]) => (
        <NavLink
          key={path}
          to={path}
          end={path === "/"}
          aria-label={collapsed ? label : undefined}
          className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}
          onClick={onNavigate}
        >
          <Icon aria-hidden="true" size={20} strokeWidth={1.8} />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

interface SidebarProps {
  collapsed: boolean;
  onCollapseChange(): void;
}

export function Sidebar({ collapsed, onCollapseChange }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="应用侧栏">
      <div className="brand-block">
        <img className="brand-logo" src={logoUrl} alt="" width="88" height="88" />
        <div className="brand-name" aria-hidden={collapsed}>研启智链</div>
      </div>
      <SidebarNavigation collapsed={collapsed} />
      <button
        className="sidebar-collapse"
        type="button"
        aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
        onClick={onCollapseChange}
      >
        {collapsed ? <ChevronsRight aria-hidden="true" /> : <ChevronsLeft aria-hidden="true" />}
        <span>{collapsed ? "展开" : "收起"}</span>
      </button>
    </aside>
  );
}
