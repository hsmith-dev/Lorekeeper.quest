import { Link } from "react-router-dom";

// Rendered once, site-wide, in App.tsx (below <Routes>, inside the
// min-h-screen flex column so it sticks to the bottom of short pages).
// HomePage used to render its own inline footer with just the credit link —
// that's now folded into this shared one so every page (marketing, app,
// public share views) gets the same Terms/Privacy links instead of only the
// homepage having them.
export function Footer() {
  return (
    <footer className="border-t border-border mt-auto">
      <div className="max-w-5xl mx-auto px-4 py-6 flex flex-col items-center gap-2 text-center text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5">
          <span>
            Created by{" "}
            <a
              href="https://harrisonsmith.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline underline-offset-4"
            >
              HarrisonSmith.AI
            </a>
          </span>
          <span className="text-border">·</span>
          <Link to="/terms" className="hover:text-foreground hover:underline underline-offset-4 transition-colors">
            Terms of Use
          </Link>
          <Link to="/privacy" className="hover:text-foreground hover:underline underline-offset-4 transition-colors">
            Privacy Policy
          </Link>
        </div>
        {/* See Terms of Use → "AI-Assisted Development" for the full
            disclosure this line is summarizing. */}
        <p className="max-w-md">
          Built with the assistance of AI tools, including Anthropic's Claude and Google's Gemini.
        </p>
      </div>
    </footer>
  );
}
