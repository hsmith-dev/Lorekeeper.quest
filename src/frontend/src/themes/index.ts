export { dndTheme } from "./dnd";
export { lightTheme } from "./light";
export { arcaneTheme } from "./arcane";
export { cyberpunkTheme } from "./cyberpunk";
export { forestTheme } from "./forest";
export { highSeasTheme } from "./highseas";

import { dndTheme } from "./dnd";
import { lightTheme } from "./light";
import { arcaneTheme } from "./arcane";
import { cyberpunkTheme } from "./cyberpunk";
import { forestTheme } from "./forest";
import { highSeasTheme } from "./highseas";
import type { Theme } from "../types/theme";

export const themes: Theme[] = [dndTheme, arcaneTheme, highSeasTheme, forestTheme, cyberpunkTheme, lightTheme];
export const defaultTheme: Theme = dndTheme;
