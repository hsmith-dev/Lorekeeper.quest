import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, completeTutorial } from "../services/api";
import { useTour } from "../contexts/TourContext";

export function TutorialWelcomePrompt() {
  const token = localStorage.getItem("lk_token");
  const { data: profile } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    enabled: !!token,
    staleTime: 60_000,
  });
  const { start, active } = useTour();
  const qc = useQueryClient();
  const [dismissed, setDismissed] = useState(false);

  // access_granted matters as much as has_completed_tutorial here — without
  // it, a freshly registered account with no promo code (correctly routed
  // to /subscribe with zero access yet) got shown the tour immediately,
  // before ever reaching the dashboard it's supposed to be touring. The
  // prompt should wait for the same "actually has access" gate every
  // feature route already enforces.
  const shouldShow = !!profile && profile.access_granted && !profile.has_completed_tutorial && !active && !dismissed;
  if (!shouldShow) return null;

  const handleSkip = () => {
    setDismissed(true);
    completeTutorial()
      .then(() => qc.invalidateQueries({ queryKey: ["me"] }))
      .catch(() => {});
  };

  const handleStart = () => {
    setDismissed(true);
    start();
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-xl flex flex-col gap-4 text-center">
        <p className="text-3xl">📜</p>
        <div>
          <h2 className="text-lg font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Welcome to Lorekeeper!
          </h2>
          <p className="text-sm text-muted-foreground mt-1.5">
            Want a quick tour of how it all fits together? Takes about a minute.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSkip}
            className="flex-1 rounded-md border border-input px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          >
            Skip
          </button>
          <button
            onClick={handleStart}
            className="flex-1 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity"
          >
            Start Tour
          </button>
        </div>
      </div>
    </div>
  );
}
