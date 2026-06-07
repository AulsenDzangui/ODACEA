"use client";

import { create } from "zustand";

export type Theme = "light" | "dark" | "system";

export const THEME_KEY = "odacea-theme";

type ThemeState = {
  theme: Theme;
  setTheme: (t: Theme) => void;
};

export const useThemeStore = create<ThemeState>((set) => ({
  theme: "system",
  setTheme: (theme) => {
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(THEME_KEY, theme);
      } catch {}
    }
    set({ theme });
  },
}));
