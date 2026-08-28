import { createContext, useContext, useEffect, useState, useCallback } from "react";
import type { ReactNode } from "react";
import type { Theme } from "../types/theme";
import { themes as builtinThemes, defaultTheme } from "../themes";

interface ThemeContextValue {
  theme: Theme;
  themes: Theme[];
  setTheme: (id: string) => void;
  addTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "lorekeeper-theme-id";
const CUSTOM_STORAGE_KEY = "lorekeeper-custom-themes";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  for (const [key, value] of Object.entries(theme.colors)) {
    root.style.setProperty(`--${key}`, value);
  }
  if (theme.radius) {
    root.style.setProperty("--radius", theme.radius);
  }
  root.setAttribute("data-theme", theme.id);
  // Font vars (consumed by index.css)
  root.style.setProperty("--font-heading", theme.fonts?.heading ?? "inherit");
  root.style.setProperty("--font-body", theme.fonts?.body ?? "inherit");
}

function loadCustomThemes(): Theme[] {
  try {
    const raw = localStorage.getItem(CUSTOM_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [customThemes, setCustomThemes] = useState<Theme[]>(loadCustomThemes);
  const allThemes = [...builtinThemes, ...customThemes];

  const [activeTheme, setActiveTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return allThemes.find((t) => t.id === saved) ?? defaultTheme;
  });

  useEffect(() => {
    applyTheme(activeTheme);
  }, [activeTheme]);

  const setTheme = useCallback(
    (id: string) => {
      const found = allThemes.find((t) => t.id === id);
      if (!found) return;
      setActiveTheme(found);
      localStorage.setItem(STORAGE_KEY, id);
    },
    [allThemes]
  );

  const addTheme = useCallback((theme: Theme) => {
    setCustomThemes((prev) => {
      const filtered = prev.filter((t) => t.id !== theme.id);
      const next = [...filtered, theme];
      localStorage.setItem(CUSTOM_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
    setActiveTheme(theme);
    localStorage.setItem(STORAGE_KEY, theme.id);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme: activeTheme, themes: allThemes, setTheme, addTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
