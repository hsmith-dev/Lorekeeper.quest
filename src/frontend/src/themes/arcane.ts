import type { Theme } from "../types/theme";

export const arcaneTheme: Theme = {
  id: "arcane",
  name: "Arcane Sanctum",
  description: "Deep purple and silver — the study of a high wizard.",
  radius: "0.375rem",
  fonts: {
    heading: "'Cinzel', serif",
    body: "inherit",
  },
  colors: {
    background:             "260 20% 6%",
    foreground:             "220 30% 92%",
    card:                   "260 18% 10%",
    "card-foreground":      "220 30% 92%",
    popover:                "260 18% 10%",
    "popover-foreground":   "220 30% 92%",
    primary:                "270 60% 58%",
    "primary-foreground":   "260 20% 6%",
    secondary:              "200 50% 22%",
    "secondary-foreground": "220 30% 92%",
    muted:                  "260 12% 16%",
    "muted-foreground":     "220 15% 58%",
    accent:                 "200 55% 35%",
    "accent-foreground":    "220 30% 92%",
    destructive:            "0 55% 35%",
    "destructive-foreground": "220 30% 92%",
    border:                 "270 25% 22%",
    input:                  "260 18% 13%",
    ring:                   "270 60% 58%",
  },
};
