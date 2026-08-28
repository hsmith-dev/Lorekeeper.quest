import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { loginFn, loading, error } = useAuth();
  const location = useLocation();
  const justReset = Boolean((location.state as { justReset?: boolean } | null)?.justReset);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loginFn(email, password);
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
            Chronicle your adventures. Preserve your legend.
          </p>
        </div>

        {/* Card */}
        <div className="rounded-lg border border-border bg-card p-6 flex flex-col gap-5 shadow-lg">
          <h2
            className="text-base font-semibold text-card-foreground tracking-wide"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Sign In
          </h2>
          {justReset && (
            <p className="text-sm text-primary bg-primary/10 rounded-md px-3 py-2">
              Password reset — sign in with your new password.
            </p>
          )}
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
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
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
              {loading ? "Signing in…" : "Enter the Realm"}
            </button>
          </form>
          <p className="text-center text-sm">
            <Link to="/forgot-password" className="text-muted-foreground hover:text-foreground hover:underline underline-offset-4">
              Forgot password?
            </Link>
          </p>
          <p className="text-center text-sm text-muted-foreground">
            New adventurer?{" "}
            <Link to="/register" className="text-primary hover:underline underline-offset-4">
              Create account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
