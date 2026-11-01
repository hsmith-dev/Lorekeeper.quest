import { createElement, type ReactElement } from "react"

/** Remaining-time copy for long jobs. Always a range or "about", never a bare
 *  number (EXPERIENCE.md voice rules). */
export function formatEta(seconds: number): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    return "estimating time left"
  }
  if (seconds < 15) return "almost done"
  const minutes = seconds / 60
  if (minutes <= 1) return "about 1 min left"
  if (minutes < 2) return "about 1–2 min left"
  if (minutes < 59.5) return `about ${Math.round(minutes)} min left`
  const hours = seconds / 3600
  if (hours <= 1) return "about 1 hour left"
  if (hours < 2) return "about 1–2 hours left"
  return `about ${Math.round(hours)} hours left`
}

/** An entry's name as UI shows it: italic title, never a raw id. */
export function entryTitle(title: string | null | undefined): ReactElement {
  const text = typeof title === "string" ? title.trim() : ""
  return createElement("em", null, text || "Untitled entry")
}
