import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { RequireAuth } from "../components/common/RequireAuth";
import { AppShell } from "../components/layout/AppShell";

// 路由级按需加载（spec §9.9）：ECharts / React Flow 不进入首页主包。
const LoginPage = lazy(() => import("../pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const ProjectsPage = lazy(() => import("../pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage })));
const DashboardPage = lazy(() => import("../pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const EvidenceWorkspacePage = lazy(() =>
  import("../pages/EvidenceWorkspacePage").then((m) => ({ default: m.EvidenceWorkspacePage })),
);
const LiteraturePage = lazy(() =>
  import("../pages/LiteraturePage").then((m) => ({ default: m.LiteraturePage })),
);
const ExperimentsPage = lazy(() =>
  import("../pages/ExperimentsPage").then((m) => ({ default: m.ExperimentsPage })),
);
const AssetsPage = lazy(() => import("../pages/AssetsPage").then((m) => ({ default: m.AssetsPage })));
const ApprovalsPage = lazy(() =>
  import("../pages/ApprovalsPage").then((m) => ({ default: m.ApprovalsPage })),
);
const WritingPage = lazy(() => import("../pages/WritingPage").then((m) => ({ default: m.WritingPage })));
const ReflectionsPage = lazy(() =>
  import("../pages/ReflectionsPage").then((m) => ({ default: m.ReflectionsPage })),
);
const AgentsPage = lazy(() => import("../pages/AgentsPage").then((m) => ({ default: m.AgentsPage })));
const KnowledgeGraphPage = lazy(() =>
  import("../pages/KnowledgeGraphPage").then((m) => ({ default: m.KnowledgeGraphPage })),
);
const SettingsPage = lazy(() => import("../pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

function page(node: ReactNode) {
  return (
    <Suspense
      fallback={<div className="flex h-40 items-center justify-center text-sm text-text-muted">加载中…</div>}
    >
      {node}
    </Suspense>
  );
}

export const router = createBrowserRouter([
  { path: "/login", element: page(<LoginPage />) },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/projects" replace /> },
      { path: "projects", element: page(<ProjectsPage />) },
      { path: "projects/:projectId/overview", element: page(<DashboardPage />) },
      { path: "projects/:projectId/literature", element: page(<LiteraturePage />) },
      { path: "projects/:projectId/experiments", element: page(<ExperimentsPage />) },
      { path: "projects/:projectId/assets", element: page(<AssetsPage />) },
      { path: "projects/:projectId/knowledge-graph", element: page(<KnowledgeGraphPage />) },
      { path: "projects/:projectId/writing", element: page(<WritingPage />) },
      { path: "projects/:projectId/reflections", element: page(<ReflectionsPage />) },
      { path: "projects/:projectId/agents", element: page(<AgentsPage />) },
      { path: "projects/:projectId/approvals", element: page(<ApprovalsPage />) },
      { path: "settings", element: page(<SettingsPage />) },
    ],
  },
  {
    path: "/projects/:projectId/cycles/:cycleId/evidence",
    element: (
      <RequireAuth>{page(<EvidenceWorkspacePage />)}</RequireAuth>
    ),
  },
]);
