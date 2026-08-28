import { useState } from "react";
import { Link } from "react-router-dom";
import { forgotPassword } from "../services/api";
import { apiErrorMessage } from "../utils/apiError";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await forgotPassword(email);
      // Backend always returns this same response regardless of whether the
      // email is registered (see auth.py's forgot_password) — the frontend
      // shouldn't second-guess that by showing anything more specific.
      setSent(true);
    } catch (err) {
      setError(apiErrorMessage(err, "Couldn't send reset link. Try again."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm flex flex-col gap-8">
        <div className="text-center flex flex-col gap-2">
          <h1
            className="text-4xl font-bold text-primary tracking-wide"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            <Link to="/" className="hover:opacity-80 transition-opacity">Lorekeeper</Link>
          </h1>
          <p className="text-sm text-muted-foreground">Reset your password.</p>
        </div>

        <div className="rounded-lg border border-border bg-card p-6 flex flex-col gap-5 shadow-lg">
          {sent ? (
            <div className="text-center flex flex-col gap-3">
              <p className="text-2xl">📬</p>
              <p className="text-sm text-card-foreground">
                If that email has an account, a reset link is on its way.
              </p>
              <Link to="/login" className="text-sm text-primary hover:underline underline-offset-4">
                Back to Sign In
              </Link>
            </div>
          ) : (
            <>
              <h2
                className="text-base font-semibold text-card-foreground tracking-wide"
                style={{ fontFamily: "var(--font-heading)" }}
              >
                Forgot Password
              </h2>
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <input
                  type="email"
                  placeholder="Email address"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
                />
                {error && (
                  <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{error}</p>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="mt-1 w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
                  style={{ fontFamily: "var(--font-heading)" }}
                >
                  {loading ? "Sending…" : "Send Reset Link"}
                </button>
              </form>
              <p className="text-center text-sm text-muted-foreground">
                <Link to="/login" className="text-primary hover:underline underline-offset-4">
                  Back to Sign In
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
