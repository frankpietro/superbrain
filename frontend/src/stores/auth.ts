import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface AuthState {
  token: string | null;
  setToken: (token: string | null) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      setToken: (token) => set({ token }),
      clear: () => set({ token: null }),
    }),
    {
      name: "superbrain.auth",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);

export function getAuthToken(): string | null {
  return useAuth.getState().token;
}
