import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import {
  applyThemePreference,
  readThemePreference,
  THEME_CHANGE_EVENT,
  type ThemePreference,
} from "../../lib/theme";
import { Drawer } from "../ui/Drawer";
import { Header } from "./Header";
import { Sidebar, SidebarNavigation } from "./Sidebar";

const SIDEBAR_STORAGE_KEY = "ai-researcher.sidebar.collapsed";

type SidebarState = "expanded" | "collapsed";

function readSidebarState(): SidebarState {
  try {
    const storedValue = window.localStorage?.getItem(SIDEBAR_STORAGE_KEY);
    return storedValue === "collapsed" ? "collapsed" : "expanded";
  } catch {
    return "expanded";
  }
}

function writeSidebarState(state: SidebarState): void {
  try {
    window.localStorage?.setItem(SIDEBAR_STORAGE_KEY, state);
  } catch {
    // Storage is an optional enhancement; the in-memory UI remains usable.
  }
}

export function AppShell() {
  const [sidebarState, setSidebarState] = useState<SidebarState>(readSidebarState);
  const [theme, setTheme] = useState<ThemePreference>(readThemePreference);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const collapsed = sidebarState === "collapsed";

  useEffect(() => {
    writeSidebarState(sidebarState);
  }, [sidebarState]);

  useEffect(() => {
    applyThemePreference(theme);
    const onThemeChange = (event: Event) => {
      const preference = (event as CustomEvent<ThemePreference>).detail;
      if (preference === "light" || preference === "dark" || preference === "system") {
        setTheme(preference);
      }
    };
    window.addEventListener(THEME_CHANGE_EVENT, onThemeChange);

    let media: MediaQueryList | null = null;
    const onColorSchemeChange = (event: MediaQueryListEvent) => {
      document.documentElement.dataset.theme = event.matches ? "dark" : "light";
    };
    if (theme === "system") {
      try {
        media = typeof window.matchMedia === "function"
          ? window.matchMedia("(prefers-color-scheme: dark)")
          : null;
        media?.addEventListener?.("change", onColorSchemeChange);
      } catch {
        media = null;
      }
    }

    return () => {
      window.removeEventListener(THEME_CHANGE_EVENT, onThemeChange);
      media?.removeEventListener?.("change", onColorSchemeChange);
    };
  }, [theme]);

  return (
    <div
      className="app-shell"
      data-sidebar={collapsed ? "collapsed" : "expanded"}
      data-testid="app-shell"
    >
      <Sidebar
        collapsed={collapsed}
        onCollapseChange={() => setSidebarState((current) => current === "collapsed" ? "expanded" : "collapsed")}
      />
      <div className="app-main">
        <Header onOpenNavigation={() => setMobileNavigationOpen(true)} />
        <main className="page-content" id="main-content">
          <Outlet />
        </main>
      </div>
      <Drawer
        open={mobileNavigationOpen}
        title="导航菜单"
        onClose={() => setMobileNavigationOpen(false)}
      >
        <SidebarNavigation
          ariaLabel="移动主导航"
          onNavigate={() => setMobileNavigationOpen(false)}
        />
      </Drawer>
    </div>
  );
}
