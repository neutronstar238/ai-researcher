import { create } from "zustand";

import { fetchMe, login as loginApi, logout as logoutApi, type User } from "../api/auth";
import { tokenStorage } from "../api/tokenStorage";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthState {
  user: User | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  restore: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: "loading",

  login: async (email, password) => {
    await loginApi(email, password);
    const user = await fetchMe();
    set({ user, status: "authenticated" });
  },

  logout: async () => {
    await logoutApi();
    set({ user: null, status: "anonymous" });
  },

  restore: async () => {
    if (!tokenStorage.getAccess()) {
      set({ status: "anonymous" });
      return;
    }
    try {
      const user = await fetchMe();
      set({ user, status: "authenticated" });
    } catch {
      tokenStorage.clear();
      set({ user: null, status: "anonymous" });
    }
  },
}));

if (typeof window !== "undefined") {
  window.addEventListener("ar:session-expired", () => {
    useAuthStore.setState({ user: null, status: "anonymous" });
  });
}
