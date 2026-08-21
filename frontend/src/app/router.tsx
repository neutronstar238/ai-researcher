import {
  BookOpen,
  Bot,
  ClipboardCheck,
  Database,
  FileText,
  FlaskConical,
  FolderOpen,
  LayoutDashboard,
  Network,
  RefreshCcw,
  Settings,
} from "lucide-react";
import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { AppShell } from "../components/shell/AppShell";
import { AgentsPage } from "../features/agents/AgentsPage";
import { CapabilityPage } from "../features/capabilities/CapabilityPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { ReflectionsPage } from "../features/reflections/ReflectionsPage";
import { ArtifactWorkspacePage } from "../features/resources/ArtifactWorkspacePage";
import { SettingsPage } from "../features/settings/SettingsPage";

export const NAV_ITEMS = [
  ["/", "研究总览", LayoutDashboard],
  ["/projects", "项目空间", FolderOpen],
  ["/literature", "文献库", BookOpen],
  ["/experiments", "实验管理", FlaskConical],
  ["/assets", "数据资产", Database],
  ["/knowledge", "知识图谱", Network],
  ["/writing", "写作中心", FileText],
  ["/reflections", "复盘洞察", RefreshCcw],
  ["/agents", "智能体中心", Bot],
  ["/approvals", "审批中心", ClipboardCheck],
  ["/settings", "系统设置", Settings],
] as const;

export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "literature", element: <ArtifactWorkspacePage workspace="literature" title="文献库" /> },
      { path: "experiments", element: <ArtifactWorkspacePage workspace="experiments" title="实验管理" /> },
      { path: "assets", element: <ArtifactWorkspacePage workspace="assets" title="数据资产" /> },
      { path: "knowledge", element: <CapabilityPage kind="knowledge" title="知识图谱" description="当前服务未提供知识图谱查询接口" /> },
      { path: "writing", element: <ArtifactWorkspacePage workspace="writing" title="写作中心" /> },
      { path: "reflections", element: <ReflectionsPage /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "approvals", element: <CapabilityPage kind="approvals" title="审批中心" description="当前服务未提供审批队列接口" /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
];

export const router = createBrowserRouter(appRoutes);
