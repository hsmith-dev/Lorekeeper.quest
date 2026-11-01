import { useEffect } from "react";
import { Eye } from "lucide-react";

import { usePreview } from "@/contexts/PreviewContext";

// The "Viewing as Player" band (E0-UX.6). Topmost (z 60) above the sticky nav
// on every route while preview is on. While shown it sets --lk-preview-offset
// on <html> so the nav and the SlideOver panel sit below it.
//
// Esc deliberately does not exit preview, so the banner registers no layer:
// leaving preview is always an explicit "Exit preview". The preview itself is
// cosmetic; what Players may see is enforced server-side (AD-13).

const OFFSET_VAR = "--lk-preview-offset";

export function PreviewBanner() {
  const { active, exit } = usePreview();

  useEffect(() => {
    if (!active) return;
    const root = document.documentElement;
    root.style.setProperty(OFFSET_VAR, "2.5rem");
    return () => {
      root.style.removeProperty(OFFSET_VAR);
    };
  }, [active]);

  if (!active) return null;

  return (
    <div
      role="region"
      aria-label="Player preview"
      className="sticky top-0 z-[60] flex h-10 items-center justify-center gap-3 bg-info px-4 text-sm text-background"
    >
      <Eye aria-hidden="true" className="size-4 shrink-0" />
      <p className="min-w-0 truncate">
        <span className="font-semibold">Viewing as Player</span>
        <span className="max-sm:sr-only"> · You're seeing exactly what players see.</span>
      </p>
      <button
        type="button"
        onClick={exit}
        className="relative inline-flex h-7 shrink-0 items-center rounded-md border border-background px-3 text-xs font-medium text-background transition-colors before:absolute before:-inset-x-1 before:-inset-y-2 hover:bg-background hover:text-info focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background md:before:hidden"
      >
        Exit preview
      </button>
    </div>
  );
}
