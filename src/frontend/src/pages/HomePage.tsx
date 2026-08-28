import type { ReactNode } from "react";
import { Navigate, Link } from "react-router-dom";

const FEATURES: { title: string; description: string; icon: ReactNode }[] = [
  {
    title: "AI-Written Journal Entries",
    description:
      "Jot down shorthand session notes — Lorekeeper turns them into a polished narrative in your campaign's voice.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    ),
  },
  {
    title: "Canon-Grounded Chat Companion",
    description:
      "Ask your campaign anything — answers are grounded in your own journal entries and uploaded source material via RAG, not generic guesses.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
  {
    title: "NPCs, Quests & Timeline",
    description:
      "Characters and quests are extracted from your entries automatically, with a searchable timeline tying every session together.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        <path d="M1 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
      </svg>
    ),
  },
  {
    title: "Collaborative Campaigns",
    description:
      "Share a read-only link so friends can follow along, or invite the whole party to co-write the chronicle together.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    title: "Record & Summarize Sessions",
    description: "Record the table live — Lorekeeper transcribes and drafts session notes for you to review and save.",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
      </svg>
    ),
  },
];

function FeatureCard({ title, description, icon }: { title: string; description: string; icon: ReactNode }) {
  return (
    <div className="w-full sm:w-[calc(50%-0.5rem)] lg:w-[calc(33.333%-0.667rem)] rounded-lg border border-border bg-card p-5 flex flex-col gap-3">
      <div className="w-10 h-10 rounded-md bg-primary/15 text-primary flex items-center justify-center">{icon}</div>
      <h3 className="text-base font-semibold text-card-foreground" style={{ fontFamily: "var(--font-heading)" }}>
        {title}
      </h3>
      <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
    </div>
  );
}

function PricingCard({
  name,
  price,
  cadence,
  description,
  bullets,
  cta,
  highlighted,
}: {
  name: string;
  price: string;
  cadence?: string;
  description: string;
  bullets: string[];
  cta: string;
  highlighted?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-6 flex flex-col gap-4 ${
        highlighted ? "border-primary bg-primary/5 shadow-lg" : "border-border bg-card"
      }`}
    >
      <div>
        <h3 className="text-lg font-semibold text-card-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {name}
        </h3>
        <p className="text-sm text-muted-foreground mt-1">{description}</p>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-3xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {price}
        </span>
        {cadence && <span className="text-sm text-muted-foreground">{cadence}</span>}
      </div>
      <ul className="flex flex-col gap-2 text-sm text-foreground flex-1">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary shrink-0 mt-0.5">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <span>{b}</span>
          </li>
        ))}
      </ul>
      <Link
        to="/register"
        className={`text-center rounded-md px-4 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90 ${
          highlighted ? "bg-primary text-primary-foreground" : "border border-input bg-background text-foreground"
        }`}
        style={{ fontFamily: "var(--font-heading)" }}
      >
        {cta}
      </Link>
    </div>
  );
}

export function HomePage() {
  const token = localStorage.getItem("lk_token");
  if (token) return <Navigate to="/dashboard" replace />;

  return (
    <div className="min-h-screen flex flex-col">
      {/* Public header */}
      <header className="border-b border-border">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
          <span
            className="text-xl font-bold tracking-wide text-primary"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Lorekeeper
          </span>
          <div className="flex items-center gap-3">
            <Link to="/login" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Sign in
            </Link>
            <Link
              to="/register"
              className="rounded-md bg-primary px-3.5 py-1.5 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-4 pt-16 pb-14 text-center flex flex-col items-center gap-6">
        <h1
          className="text-4xl md:text-5xl font-bold text-foreground max-w-2xl leading-tight"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          Your tabletop campaign, chronicled by AI.
        </h1>
        <p className="text-lg text-muted-foreground max-w-xl">
          Turn shorthand session notes into a real narrative, chat with an assistant that actually
          knows your campaign, and keep the whole party's chronicle in one place — solo or
          together.
        </p>
        <div className="flex items-center gap-3 mt-2">
          <Link
            to="/register"
            className="rounded-md bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Begin Your Journey
          </Link>
          <Link
            to="/login"
            className="rounded-md border border-input bg-background px-6 py-3 text-sm font-semibold text-foreground hover:bg-accent/10 transition-colors"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Sign In
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-4 py-10 w-full">
        <h2 className="text-2xl font-bold text-foreground text-center mb-8" style={{ fontFamily: "var(--font-heading)" }}>
          Everything your table needs, in one chronicle
        </h2>
        {/* flex-wrap + justify-center (not a grid) so a trailing incomplete
            row — e.g. 5 cards at 3-per-row leaves 2 — centers itself instead
            of sitting flush left the way CSS grid would leave it */}
        <div className="flex flex-wrap justify-center gap-4">
          {FEATURES.map((f) => (
            <FeatureCard key={f.title} {...f} />
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="max-w-5xl mx-auto px-4 py-14 w-full">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Simple, honest pricing
          </h2>
          <p className="text-sm text-muted-foreground mt-2">
            Every plan gets the full app — journals, chat, NPCs, quests, sharing, offline mode.
            The only difference is which AI model powers it.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          <PricingCard
            name="Free (Invite Only)"
            price="$0"
            description="For beta testers and invited players with a promo code."
            bullets={[
              "Full app access",
              "Bring your own OpenAI, Anthropic, Gemini, or custom API key",
              "Requires a promo code to sign up",
            ]}
            cta="Have a code? Sign up"
          />
          <PricingCard
            name="Bring Your Own Key"
            price="$5"
            cadence="/month"
            description="Use your own AI provider — you control the model and the API costs."
            bullets={[
              "Full app access",
              "Connect OpenAI, Anthropic Claude, Google Gemini, or any custom OpenAI-compatible endpoint",
              "No usage caps from us — your provider bills you directly",
              "Cancel anytime",
            ]}
            cta="Get Started — $5/mo"
          />
          <PricingCard
            name="Hosted Model"
            price="$15"
            cadence="/month"
            description="Skip the API key — use Lorekeeper's own fine-tuned model, self-hosted on Oracle Cloud."
            bullets={[
              "Everything in Bring Your Own Key",
              "No API key needed — metered access to our hosted, fine-tuned model",
              "Generous monthly quota, resets every billing period",
              "Cancel anytime",
            ]}
            cta="Get Started — $15/mo"
            highlighted
          />
        </div>
      </section>

    </div>
  );
}
