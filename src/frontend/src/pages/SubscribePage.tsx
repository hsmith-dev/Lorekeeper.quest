import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useBillingStatus, useStartCheckout, useRedeemPromoCode } from "../hooks/useSettings";
import type { SubscriptionPlan } from "../types";

function PlanCard({
  name,
  price,
  bullets,
  onSubscribe,
  pending,
  disabled,
  current,
  highlighted,
}: {
  name: string;
  price: string;
  bullets: string[];
  onSubscribe: () => void;
  pending: boolean;
  disabled: boolean;
  current: boolean;
  highlighted?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-5 flex flex-col gap-4 ${
        highlighted ? "border-primary bg-primary/5" : "border-border bg-card"
      }`}
    >
      <div>
        <h3 className="text-base font-semibold text-card-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {name}
        </h3>
        <div className="flex items-baseline gap-1 mt-1">
          <span className="text-2xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            {price}
          </span>
          <span className="text-xs text-muted-foreground">/month</span>
        </div>
      </div>
      <ul className="flex flex-col gap-1.5 text-xs text-foreground flex-1">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-1.5">
            <span className="text-primary shrink-0">•</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>
      <button
        onClick={onSubscribe}
        disabled={disabled || pending || current}
        className={`rounded-md px-4 py-2 text-sm font-semibold transition-opacity hover:opacity-90 disabled:opacity-50 ${
          highlighted ? "bg-primary text-primary-foreground" : "border border-input bg-background text-foreground"
        }`}
        style={{ fontFamily: "var(--font-heading)" }}
      >
        {current ? "Current plan" : pending ? "Redirecting…" : "Subscribe"}
      </button>
    </div>
  );
}

export function SubscribePage() {
  const { data: status, isLoading } = useBillingStatus();
  const checkout = useStartCheckout();
  const redeem = useRedeemPromoCode();
  const [promoCode, setPromoCode] = useState("");
  const [pendingPlan, setPendingPlan] = useState<SubscriptionPlan | null>(null);
  const navigate = useNavigate();

  const alreadyHasAccess = status?.access_granted;
  const isSubscriber = status?.access_source === "subscription";
  // Only a *real* paid Stripe subscription should dead-end this page — promo
  // and grandfathered access are both "free access", not "already a paying
  // subscriber", and both should still be able to reach the plan cards below
  // to actually subscribe (e.g. to unlock hosted-model quota, or just to
  // start paying). Gating on `alreadyHasAccess` alone stranded every
  // promo/grandfathered user here with no way to ever pick a plan.
  const blockPlanSelection = isSubscriber;

  const handleRedeem = (e: React.FormEvent) => {
    e.preventDefault();
    if (!promoCode.trim()) return;
    redeem.mutate(promoCode.trim(), {
      onSuccess: ({ data }) => {
        if (data.access_granted) navigate("/dashboard");
      },
    });
  };

  const handleSubscribe = (plan: SubscriptionPlan) => {
    setPendingPlan(plan);
    checkout.mutate(plan);
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-2xl flex flex-col gap-6">
        <div className="text-center flex flex-col gap-2">
          <h1
            className="text-3xl font-bold text-primary tracking-wide"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Subscribe to Lorekeeper
          </h1>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            {blockPlanSelection
              ? "Manage your plan below, or head back to your chronicle."
              : alreadyHasAccess
              ? "Pick a plan below to start a paid subscription, or keep using your free access as-is."
              : "Your account exists, but doesn't have access yet. Pick a plan, or redeem a promo code below."}
          </p>
        </div>

        {blockPlanSelection ? (
          <div className="rounded-lg border border-border bg-card p-6 text-center flex flex-col gap-3">
            <p className="text-sm text-foreground">You already have access to Lorekeeper.</p>
            <div className="flex items-center justify-center gap-3">
              <Link
                to="/settings#billing"
                className="rounded-md border border-input bg-background px-4 py-2.5 text-sm font-semibold text-foreground hover:bg-accent transition-colors"
              >
                Manage Subscription
              </Link>
              <Link
                to="/dashboard"
                className="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity"
              >
                Go to Dashboard
              </Link>
            </div>
          </div>
        ) : (
          <>
            {alreadyHasAccess && (
              <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
                <p className="text-xs text-muted-foreground">
                  {status?.access_source === "promo"
                    ? "You currently have free access via a promo code, using your own LLM API key."
                    : "You currently have free access granted by an admin."}{" "}
                  Subscribing below starts a real paid plan billed by Stripe — it won't change what you're
                  charged based on your promo code either way.
                </p>
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <PlanCard
                name="Bring Your Own Key"
                price="$5"
                bullets={[
                  "Full app access — journals, campaigns, chat, sharing",
                  "Connect OpenAI, Anthropic, Gemini, or a custom endpoint",
                  "No usage caps from us",
                ]}
                onSubscribe={() => handleSubscribe("byok")}
                pending={checkout.isPending && pendingPlan === "byok"}
                disabled={isLoading || (status ? !status.stripe_configured : false)}
                current={status?.plan === "byok" && isSubscriber}
              />
              <PlanCard
                name="Hosted Model"
                price="$15"
                bullets={[
                  "Everything in Bring Your Own Key",
                  "No API key needed — metered use of Lorekeeper's hosted model",
                  "Quota resets every billing period",
                ]}
                onSubscribe={() => handleSubscribe("hosted")}
                pending={checkout.isPending && pendingPlan === "hosted"}
                disabled={isLoading || (status ? !status.stripe_configured : false)}
                current={status?.plan === "hosted" && isSubscriber}
                highlighted
              />
            </div>

            <p className="text-xs text-muted-foreground text-center">
              By subscribing, you agree to Lorekeeper's{" "}
              <Link to="/terms" target="_blank" className="text-primary hover:underline underline-offset-4">
                Terms of Use
              </Link>{" "}
              and{" "}
              <Link to="/privacy" target="_blank" className="text-primary hover:underline underline-offset-4">
                Privacy Policy
              </Link>
              .
            </p>

            {status && !status.stripe_configured && (
              <p className="text-xs text-muted-foreground text-center">
                Billing isn't configured on this server yet.
              </p>
            )}
            {checkout.isError && (
              <p className="text-sm text-destructive text-center">
                {(checkout.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
                  "Couldn't start checkout. Try again in a moment."}
              </p>
            )}

            <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-2">
              <p className="text-xs text-muted-foreground text-center">Have a promo code instead?</p>
              <form onSubmit={handleRedeem} className="flex gap-2 max-w-sm mx-auto w-full">
                <input
                  type="text"
                  placeholder="Promo code"
                  value={promoCode}
                  onChange={(e) => setPromoCode(e.target.value)}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
                <button
                  type="submit"
                  disabled={redeem.isPending || !promoCode.trim()}
                  className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent transition-colors disabled:opacity-50"
                >
                  {redeem.isPending ? "Checking…" : "Redeem"}
                </button>
              </form>
              {redeem.isError && (
                <p className="text-xs text-destructive text-center">
                  {(redeem.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
                    "That code isn't valid."}
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
