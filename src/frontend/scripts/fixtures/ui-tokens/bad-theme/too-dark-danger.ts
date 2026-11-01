// Self-test fixture for scripts/check-ui-tokens.mjs --contrast. Not compiled.
// dnd surfaces with a `danger` as dark as dnd's `destructive` (the E0-UX.2
// defect). --self-test asserts it fails danger on card, background, its own
// wash and the destructive/20 wash.

export const tooDarkDangerTheme = {
  id: "too-dark-danger",
  colors: {
    background:             "25 15% 6%",
    card:                   "25 12% 10%",
    destructive:            "0 62% 30%",
    "destructive-foreground": "43 35% 88%",
    success:                "130 40% 55%",
    warning:                "32 85% 58%",
    info:                   "205 55% 65%",
    gm:                     "285 45% 70%",
    live:                   "4 80% 68%",
    danger:                 "0 62% 30%",
  },
};
