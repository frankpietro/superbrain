import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { sanitizeBearerToken } from "@/lib/auth-token";

export interface AuthState {
  token: string | null;
  setToken: (token: string | null) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      setToken: (token) => {
        if (token === null) {
          set({ token: null });
          return;
        }
        const result = sanitizeBearerToken(token);
        set({ token: result.ok ? result.token : null });
      },
      clear: () => set({ token: null }),
    }),
    {
      name: "superbrain.auth",
      storage: createJSONStorage(() => localStorage),
      // Scrub tokens left behind by prior broken sessions (e.g. pasted smart
      // quotes or zero-width characters) so a reload is enough to recover
      // without a manual localStorage purge.
      onRehydrateStorage: () => (state) => {
        if (!state || state.token === null) return;
        const result = sanitizeBearerToken(state.token);
        if (!result.ok) {
          state.token = null;
        } else if (result.token !== state.token) {
          state.token = result.token;
        }
      },
    },
  ),
);

export function getAuthToken(): string | null {
  return useAuth.getState().token;
}
