import { create } from "zustand";

/** 短期 UI 状态：Sidebar 收起、Inspector 开关、视口等（spec §9.3）。 */
interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
