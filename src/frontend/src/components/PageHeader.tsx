import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  /** Right-aligned slot for a page-level action (a button, a status pill) —
      keeps title/description on the left without every page hand-rolling
      its own flex wrapper for the common "heading + one button" layout. */
  actions?: ReactNode;
  /** Passed through to the wrapping div as data-tour="..." — a few pages
      (Timeline, Character Sheets) are onboarding-tour spotlight targets and
      need this preserved exactly. */
  dataTour?: string;
}

// The exact heading style (text-2xl font-bold + heading font) was already
// independently duplicated near-identically across ~18 pages before this —
// consolidated here so it can't silently drift per-page anymore, not
// because any of those pages looked wrong.
export function PageHeader({ title, description, actions, dataTour }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-4 flex-wrap" data-tour={dataTour}>
      <div>
        <h1 className="text-2xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {title}
        </h1>
        {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </div>
  );
}
