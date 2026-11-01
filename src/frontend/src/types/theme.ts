export interface ThemeColors {
  background: string;
  foreground: string;
  card: string;
  "card-foreground": string;
  popover: string;
  "popover-foreground": string;
  primary: string;
  "primary-foreground": string;
  secondary: string;
  "secondary-foreground": string;
  muted: string;
  "muted-foreground": string;
  accent: string;
  "accent-foreground": string;
  destructive: string;
  "destructive-foreground": string;
  border: string;
  input: string;
  ring: string;
  /* Semantic tokens (DESIGN.md): text/icon-safe hues, stable in meaning across themes. */
  success: string;
  warning: string;
  info: string;
  gm: string;
  live: string;
  danger: string;
}

export interface Theme {
  id: string;
  name: string;
  description?: string;
  colors: ThemeColors;
  radius?: string;
  fonts?: {
    heading?: string;
    body?: string;
  };
}
