import { type ClassValue, clsx } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// Register the DESIGN.md type-role utilities (index.css) as font sizes, so a
// text colour class does not strip them while text-sm etc. still override.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        "text-entity-title",
        "text-quote",
        "text-caption-live",
        "text-caption-table",
        "text-recap-table",
      ],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
