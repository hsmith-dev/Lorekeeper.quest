import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [promoCode, setPromoCode] = useState("");
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const { registerFn, loading, error } = useAuth();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    registerFn(email, password, displayName, promoCode.trim() || undefined);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm flex flex-col gap-8">

        {/* Brand — links to the public landing page, since anyone seeing this
            form isn't signed in yet */}
        <div className="text-center flex flex-col gap-2">
          <h1
            className="text-4xl font-bold text-primary tracking-wide"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            <Link to="/" className="hover:opacity-80 transition-opacity">Lorekeeper</Link>
          </h1>
          <p className="text-sm text-muted-foreground">
            Begin your chronicle. Your legend starts here.
          </p>
        </div>

        {/* Card */}
        <div className="rounded-lg border border-border bg-card p-6 flex flex-col gap-5 shadow-lg">
          <h2
            className="text-base font-semibold text-card-foreground tracking-wide"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Create Account
          </h2>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              type="text"
              placeholder="Adventurer name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
            />
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
            />
            <input
              type="password"
              placeholder="Password (10+ characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={10}
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
            />
            <input
              type="text"
              placeholder="Promo code (optional)"
              value={promoCode}
              onChange={(e) => setPromoCode(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
            />
            <p className="text-xs text-muted-foreground -mt-1.5 px-0.5">
              Have a promo code? Enter it for free access. Otherwise you'll be asked to
              subscribe after creating your account.
            </p>
            <label className="flex items-start gap-2 px-0.5 text-xs text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={agreedToTerms}
                onChange={(e) => setAgreedToTerms(e.target.checked)}
                required
                className="mt-0.5 shrink-0 accent-primary"
              />
              <span>
                I agree to the{" "}
                <Link to="/terms" target="_blank" className="text-primary hover:underline underline-offset-4">
                  Terms of Use
                </Link>{" "}
                and{" "}
                <Link to="/privacy" target="_blank" className="text-primary hover:underline underline-offset-4">
                  Privacy Policy
                </Link>
                .
              </span>
            </label>
            {error && (
              <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{error}</p>
            )}
            <button
              type="submit"
              disabled={loading}
              className="mt-1 w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              {loading ? "Creating account…" : "Begin Your Journey"}
            </button>
          </form>
          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link to="/login" className="text-primary hover:underline underline-offset-4">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
