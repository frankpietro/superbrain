import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { League } from "@/lib/types";

export type Theme = "light" | "dark" | "system";

export interface PreferencesState {
  theme: Theme;
  timezone: string;
  selectedLeagues: League[];
  setTheme: (theme: Theme) => void;
  setTimezone: (tz: string) => void;
  setSelectedLeagues: (leagues: League[]) => void;
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: "system",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC",
      selectedLeagues: [],
      setTheme: (theme) => set({ theme }),
      setTimezone: (timezone) => set({ timezone }),
      setSelectedLeagues: (selectedLeagues) => set({ selectedLeagues }),
    }),
    {
      name: "superbrain.prefs",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  const prefersDark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", prefersDark);
}
