// Self-test fixture for scripts/check-ui-tokens.mjs --contrast. Not compiled.
// Light surfaces with a black `destructive`: `danger` (35% grey) passes card
// (6.98:1), background and its own 14% wash (5.68:1), but fails on the
// destructive/20 wash (4.35:1; it would pass at /15 with 4.93:1).
// --self-test asserts that destructive-wash row is this theme's only failure.

export const washOnlyDangerTheme = {
  id: "wash-only-danger",
  colors: {
    background:             "0 0% 100%",
    card:                   "0 0% 100%",
    destructive:            "0 0% 0%",
    "destructive-foreground": "0 0% 100%",
    success:                "142 70% 26%",
    warning:                "28 90% 32%",
    info:                   "205 80% 34%",
    gm:                     "275 55% 40%",
    live:                   "0 72% 42%",
    danger:                 "0 0% 35%",
  },
};
