import type { ReactNode } from "react";

/**
 * Evidence Workspace 三栏外壳（spec §7.1）：
 * Project Explorer 260px | 中央工作区 | Inspector 320px，三栏独立滚动。
 */
export function WorkspaceShell({
  explorer,
  children,
  inspector,
}: {
  explorer: ReactNode;
  children: ReactNode;
  inspector: ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-[260px] shrink-0 overflow-y-auto border-r border-border bg-surface">
        {explorer}
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto bg-page">{children}</main>
      <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-border bg-surface">
        {inspector}
      </aside>
    </div>
  );
}
