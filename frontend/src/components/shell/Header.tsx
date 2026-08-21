import { Bell, CircleHelp, Menu, UserRound } from "lucide-react";
import { useLocation } from "react-router-dom";
import { NAV_ITEMS } from "../../app/router";

function currentTitle(pathname: string): string {
  return NAV_ITEMS.find(([path]) => path === pathname)?.[1] ?? "AI-Researcher";
}

function todayLabel(): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(new Date());
}

export function Header({ onOpenNavigation }: { onOpenNavigation(): void }) {
  const { pathname } = useLocation();

  return (
    <header className="app-header">
      <div className="header-context">
        <button
          className="icon-button mobile-menu-button"
          type="button"
          aria-label="打开导航菜单"
          onClick={onOpenNavigation}
        >
          <Menu aria-hidden="true" />
        </button>
        <div>
          <p className="header-eyebrow">AI-Researcher · 研究指挥中心</p>
          <p className="header-title">{currentTitle(pathname)}</p>
        </div>
        <time className="header-date" dateTime={new Date().toISOString().slice(0, 10)}>{todayLabel()}</time>
      </div>
      <div className="header-actions" aria-label="全局操作">
        <button className="icon-button unavailable-control" type="button" aria-label="通知（暂不可用）" title="暂不可用" disabled><Bell aria-hidden="true" /></button>
        <button className="icon-button unavailable-control" type="button" aria-label="帮助（暂不可用）" title="暂不可用" disabled><CircleHelp aria-hidden="true" /></button>
        <button className="operator-button unavailable-control" type="button" aria-label="本地研究者（暂不可用）" title="暂不可用" disabled>
          <UserRound aria-hidden="true" />
          <span>本地研究者</span>
        </button>
      </div>
    </header>
  );
}
