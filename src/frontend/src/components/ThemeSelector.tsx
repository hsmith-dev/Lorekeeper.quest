import { useRef } from "react";
import { useTheme } from "../contexts/ThemeContext";
import type { Theme } from "../types/theme";

const REQUIRED_COLOR_KEYS = [
  "background", "foreground", "card", "card-foreground", "popover",
  "popover-foreground", "primary", "primary-foreground", "secondary",
  "secondary-foreground", "muted", "muted-foreground", "accent",
  "accent-foreground", "destructive", "destructive-foreground",
  "border", "input", "ring",
] as const;

function validateTheme(raw: unknown): Theme {
  if (!raw || typeof raw !== "object") throw new Error("Theme must be a JSON object.");
  const obj = raw as Record<string, unknown>;
  if (typeof obj.id !== "string" || !obj.id) throw new Error("Theme must have an 'id' string.");
  if (typeof obj.name !== "string" || !obj.name) throw new Error("Theme must have a 'name' string.");
  if (!obj.colors || typeof obj.colors !== "object") throw new Error("Theme must have a 'colors' object.");
  const colors = obj.colors as Record<string, unknown>;
  for (const key of REQUIRED_COLOR_KEYS) {
    if (typeof colors[key] !== "string") throw new Error(`Missing required color key: '${key}'.`);
  }
  return obj as unknown as Theme;
}

export function ThemeSelector({ compact = false }: { compact?: boolean }) {
  const { theme, themes, setTheme, addTheme } = useTheme();
  const fileRef = useRef<HTMLInputElement>(null);

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(ev.target?.result as string);
        const validated = validateTheme(parsed);
        addTheme(validated);
      } catch (err) {
        alert(`Invalid theme file:\n${err instanceof Error ? err.message : err}`);
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleExport = () => {
    const json = JSON.stringify(theme, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `lorekeeper-theme-${theme.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (compact) {
    return (
      <select
        value={theme.id}
        onChange={(e) => setTheme(e.target.value)}
        className="text-xs rounded border border-input bg-background text-foreground px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring"
      >
        {themes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <select
        value={theme.id}
        onChange={(e) => setTheme(e.target.value)}
        className="text-xs rounded border border-input bg-background text-foreground px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring"
        title="Switch theme"
      >
        {themes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>

      <button
        onClick={handleExport}
        title="Export current theme as JSON"
        className="text-xs px-2 py-1 rounded border border-input text-muted-foreground hover:text-foreground transition-colors"
      >
        ↓
      </button>

      <button
        onClick={() => fileRef.current?.click()}
        title="Import theme from JSON file"
        className="text-xs px-2 py-1 rounded border border-input text-muted-foreground hover:text-foreground transition-colors"
      >
        ↑
      </button>
      <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={handleImport} />
    </div>
  );
}
