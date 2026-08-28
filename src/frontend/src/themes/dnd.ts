import type { Theme } from "../types/theme";

export const dndTheme: Theme = {
  id: "dnd",
  name: "Dungeons & Dragons",
  description: "Dark dungeon stone with gold accents and crimson highlights.",
  radius: "0.2rem",
  fonts: {
    heading: "'Cinzel', 'Times New Roman', serif",
    body: "'Crimson Text', Georgia, serif",
  },
  colors: {
    background:             "25 15% 6%",
    foreground:             "43 35% 88%",
    card:                   "25 12% 10%",
    "card-foreground":      "43 35% 88%",
    popover:                "25 12% 10%",
    "popover-foreground":   "43 35% 88%",
    primary:                "43 72% 48%",
    "primary-foreground":   "25 15% 6%",
    secondary:              "0 45% 20%",
    "secondary-foreground": "43 35% 88%",
    muted:                  "25 10% 16%",
    "muted-foreground":     "43 20% 58%",
    accent:                 "0 52% 30%",
    "accent-foreground":    "43 35% 88%",
    destructive:            "0 62% 30%",
    "destructive-foreground": "43 35% 88%",
    border:                 "43 28% 20%",
    input:                  "25 12% 13%",
    ring:                   "43 72% 48%",
  },
};
