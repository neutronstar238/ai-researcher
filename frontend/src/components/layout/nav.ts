import {
  BookOpen,
  Bot,
  BrainCircuit,
  ClipboardCheck,
  Database,
  FileText,
  FlaskConical,
  FolderOpen,
  LayoutDashboard,
  Network,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  key: string;
  label: string;
  path: string; // 含 :projectId 占位符，由 Sidebar 解析
  icon: LucideIcon;
  phase: string;
}

export const NAV_ITEMS: NavItem[] = [
  { key: "overview", label: "研究总览", path: "/projects/:projectId/overview", icon: LayoutDashboard, phase: "Phase 2" },
  { key: "projects", label: "项目空间", path: "/projects", icon: FolderOpen, phase: "Phase 1" },
  { key: "literature", label: "文献库", path: "/projects/:projectId/literature", icon: BookOpen, phase: "Phase 3" },
  { key: "experiments", label: "实验管理", path: "/projects/:projectId/experiments", icon: FlaskConical, phase: "Phase 4" },
  { key: "assets", label: "数据资产", path: "/projects/:projectId/assets", icon: Database, phase: "Phase 3" },
  { key: "knowledge-graph", label: "知识图谱", path: "/projects/:projectId/knowledge-graph", icon: Network, phase: "Phase 3" },
  { key: "writing", label: "写作中心", path: "/projects/:projectId/writing", icon: FileText, phase: "Phase 6" },
  { key: "reflections", label: "复盘洞察", path: "/projects/:projectId/reflections", icon: BrainCircuit, phase: "Phase 6" },
  { key: "agents", label: "智能体中心", path: "/projects/:projectId/agents", icon: Bot, phase: "Phase 5" },
  { key: "approvals", label: "审批中心", path: "/projects/:projectId/approvals", icon: ClipboardCheck, phase: "Phase 2" },
  { key: "settings", label: "系统设置", path: "/settings", icon: Settings, phase: "Phase 2" },
];

export function resolveNavPath(path: string, projectId: string | null): string {
  return path.replace(":projectId", projectId ?? "demo");
}
