import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import { useSubmitFeedback } from "../hooks/useFeedback";
import { PageHeader } from "../components/PageHeader";
import { apiErrorMessage } from "../utils/apiError";
import type { FeedbackCategory } from "../types";

const CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: "bug", label: "Something's broken" },
  { value: "model_quality", label: "AI response quality" },
  { value: "feature_request", label: "Feature request" },
  { value: "other", label: "Other" },
];

export function FeedbackPage() {
  const { data: campaigns } = useCampaigns();
  const [category, setCategory] = useState<FeedbackCategory>("other");
  const [message, setMessage] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = useSubmitFeedback();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    submit.mutate(
      { category, message: message.trim(), campaign_id: campaignId || undefined },
      {
        onSuccess: () => {
          setMessage("");
          setCampaignId("");
          setCategory("other");
        },
        onError: (err) => setError(apiErrorMessage(err, "Couldn't submit feedback. Try again.")),
      }
    );
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Feedback"
        description="Found a bug, want a feature, or the AI said something off? Tell us — if it's about a specific campaign, link it below so we can dig into what it actually saw."
      />

      {submit.isSuccess ? (
        <div className="rounded-lg border border-border bg-card p-6 text-center flex flex-col gap-2">
          <p className="text-2xl">✅</p>
          <p className="text-sm font-medium text-card-foreground">Thanks — feedback sent.</p>
          <button
            onClick={() => submit.reset()}
            className="text-sm text-primary hover:underline underline-offset-4 mt-1"
          >
            Submit more feedback
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-5 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-card-foreground">Category</label>
            <div className="flex gap-1.5 flex-wrap">
              {CATEGORIES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setCategory(c.value)}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                    category === c.value
                      ? "bg-primary text-primary-foreground font-medium"
                      : "border border-input bg-background text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          {campaigns && campaigns.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-card-foreground">
                Related campaign <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <select
                value={campaignId}
                onChange={(e) => setCampaignId(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">None — general feedback</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-card-foreground">Message</label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              required
              minLength={1}
              maxLength={5000}
              rows={6}
              placeholder="What happened, what did you expect, anything else useful..."
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y"
            />
          </div>

          {error && <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{error}</p>}

          <button
            type="submit"
            disabled={submit.isPending || !message.trim()}
            className="self-start rounded-md bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            {submit.isPending ? "Sending…" : "Send Feedback"}
          </button>
        </form>
      )}

      <p className="text-xs text-muted-foreground">
        Feedback submitted here goes to this server's admin inbox. Self-hosting and want to reach
        the developer directly — a bug in Lorekeeper itself, a feature idea? Email{" "}
        <a href="mailto:hello@harrisonsmith.ai" className="underline">hello@harrisonsmith.ai</a> or
        open a{" "}
        <a
          href="https://github.com/hsmith-dev/Lorekeeper.quest/issues/new"
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          GitHub issue
        </a>
        {" "}(admins can attach the support bundle from Admin → System).
      </p>
    </div>
  );
}
