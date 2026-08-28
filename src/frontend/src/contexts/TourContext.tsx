import { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { completeTutorial } from "../services/api";

export interface TourStep {
  path: string;
  // CSS selector for the element to spotlight — matched against a
  // data-tour="..." attribute placed on the real element, kept out of any
  // className/id so it's obviously tour-only wiring, not styling.
  selector: string;
  title: string;
  body: string;
}

// One flat sequence spanning several pages — the provider navigates between
// them as the tour advances (see the effect below). Selectors correspond to
// data-tour attributes placed on the actual elements across the app.
export const TOUR_STEPS: TourStep[] = [
  {
    path: "/dashboard",
    selector: '[data-tour="campaign-picker"]',
    title: "Pick a Campaign",
    body: "Everything starts here — select an existing campaign or create a new one to begin journaling.",
  },
  {
    path: "/dashboard",
    selector: '[data-tour="journal-input"]',
    title: "Three Ways to Write an Entry",
    body: "Quick Entry expands short notes with AI, Session Form fills in structured fields, and Write It Yourself skips AI entirely — type the whole entry exactly as you want it.",
  },
  {
    path: "/timeline",
    selector: '[data-tour="timeline-heading"]',
    title: "Your Timeline",
    body: "Every session in a campaign, grouped by month and numbered in order — the story so far, at a glance.",
  },
  {
    path: "/character-sheets",
    selector: '[data-tour="character-sheets-heading"]',
    title: "Character Sheets",
    body: "Build a custom sheet template for your game system — any fields you want — then fill one in per character.",
  },
  {
    path: "/sharing",
    selector: '[data-tour="sharing-tabs"]',
    title: "Share & Collaborate",
    body: "Share a campaign read-only, invite party members to write into it directly, or see what others have shared with you.",
  },
  {
    path: "/settings",
    selector: '[data-tour="ai-settings-section"]',
    title: "Choose Your AI",
    body: "Use Lorekeeper's hosted model, point at a server you host yourself, or bring your own API key.",
  },
  {
    path: "/settings",
    selector: '[data-tour="tutorial-replay"]',
    title: "Come Back Anytime",
    body: "You can replay this tour whenever you want from right here in Settings.",
  },
];

interface TourContextValue {
  active: boolean;
  stepIndex: number;
  currentStep: TourStep | null;
  totalSteps: number;
  start: () => void;
  next: () => void;
  back: () => void;
  skip: () => void;
}

const TourContext = createContext<TourContextValue | null>(null);

export function TourProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();

  const currentStep = active ? TOUR_STEPS[stepIndex] ?? null : null;

  // Drive navigation from the tour's current step — each step declares the
  // page its target element lives on, so advancing across pages is just
  // part of the same Next button rather than a separate mechanism.
  useEffect(() => {
    if (!active || !currentStep) return;
    if (location.pathname !== currentStep.path) {
      navigate(currentStep.path);
    }
    // Only re-run when the step itself changes — location changing as a
    // *result* of this navigate() must not immediately re-trigger it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, currentStep]);

  const finish = useCallback(() => {
    setActive(false);
    setStepIndex(0);
    // Best-effort — a failed request here just means the tour might offer
    // to auto-launch again next login, not a broken tour experience now.
    completeTutorial()
      .then(() => qc.invalidateQueries({ queryKey: ["me"] }))
      .catch(() => {});
  }, [qc]);

  const start = useCallback(() => {
    setStepIndex(0);
    setActive(true);
  }, []);

  const next = useCallback(() => {
    setStepIndex((i) => {
      if (i + 1 >= TOUR_STEPS.length) {
        finish();
        return i;
      }
      return i + 1;
    });
  }, [finish]);

  const back = useCallback(() => setStepIndex((i) => Math.max(0, i - 1)), []);
  const skip = useCallback(() => finish(), [finish]);

  return (
    <TourContext.Provider
      value={{ active, stepIndex, currentStep, totalSteps: TOUR_STEPS.length, start, next, back, skip }}
    >
      {children}
    </TourContext.Provider>
  );
}

export function useTour() {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within TourProvider");
  return ctx;
}
