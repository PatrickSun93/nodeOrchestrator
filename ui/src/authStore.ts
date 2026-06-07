import { create } from "zustand";

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

interface AuthStore {
  status: AuthStatus;
  userId: string | null;
  setAuthenticated: (userId: string) => void;
  setUnauthenticated: () => void;
}

const UID_KEY = "orch_uid";

export const useAuthStore = create<AuthStore>((set) => ({
  status: "checking",
  userId: null,

  setAuthenticated: (userId: string) => {
    // Store userId in localStorage for display after page refresh.
    // This is display-only — auth is always verified server-side.
    const display = userId || (localStorage.getItem(UID_KEY) ?? null);
    if (userId) localStorage.setItem(UID_KEY, userId);
    set({ status: "authenticated", userId: display });
  },

  setUnauthenticated: () => {
    set({ status: "unauthenticated", userId: null });
  },
}));
