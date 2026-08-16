import { create } from "zustand";

/** 当前项目上下文（spec §5.2「当前项目 ID 由项目上下文提供」）。 */
interface ProjectState {
  currentProjectId: string | null;
  setCurrentProject: (id: string | null) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  currentProjectId: null,
  setCurrentProject: (id) => set({ currentProjectId: id }),
}));
