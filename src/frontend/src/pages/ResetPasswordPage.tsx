import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { resetPassword } from "../services/api";
import { apiErrorMessage } from "../utils/apiError";

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    try {
      await resetPassword(token, password);
      navigate("/login", { replace: true, state: { justReset: true } });
    } catch (err) {
      setError(apiErrorMessage(err, "This reset link is invalid or has expired."));
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
          <p className="text-sm text-muted-foreground">Choose a new password.</p>
        </div>

        <div className="rounded-lg border border-border bg-card p-6 flex flex-col gap-5 shadow-lg">
          {!token ? (
            <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
              This link is missing its reset token. Request a new one from{" "}
              <Link to="/forgot-password" className="underline underline-offset-4">Forgot Password</Link>.
            </p>
          ) : (
            <>
              <h2
                className="text-base font-semibold text-card-foreground tracking-wide"
                style={{ fontFamily: "var(--font-heading)" }}
              >
                Reset Password
              </h2>
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <input
                  type="password"
                  placeholder="New password (10+ characters)"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={10}
                  className="w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
                />
                <input
                  type="password"
                  placeholder="Confirm new password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  minLength={10}
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
                  {loading ? "Resetting…" : "Reset Password"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
