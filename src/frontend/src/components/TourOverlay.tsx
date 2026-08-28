import { useEffect, useState } from "react";
import { useTour } from "../contexts/TourContext";

export function TourOverlay() {
  const { active, stepIndex, currentStep, totalSteps, next, back, skip } = useTour();
  const [rect, setRect] = useState<DOMRect | null>(null);

  // The target element may not exist yet right after a step-driven
  // navigation (route still mounting) — poll a few frames until it shows up
  // rather than assuming it's there the instant the path changes.
  useEffect(() => {
    if (!active || !currentStep) { setRect(null); return; }
    setRect(null);
    let cancelled = false;
    let raf = 0;
    const poll = () => {
      if (cancelled) return;
      const el = document.querySelector(currentStep.selector);
      if (el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        window.setTimeout(() => {
          if (!cancelled) setRect(el.getBoundingClientRect());
        }, 280);
      } else {
        raf = requestAnimationFrame(poll);
      }
    };
    raf = requestAnimationFrame(poll);
    return () => { cancelled = true; cancelAnimationFrame(raf); };
  }, [active, currentStep]);

  useEffect(() => {
    if (!active || !currentStep) return;
    const update = () => {
      const el = document.querySelector(currentStep.selector);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [active, currentStep]);

  if (!active || !currentStep) return null;

  const pad = 8;
  const spotlightStyle: React.CSSProperties = rect
    ? {
        position: "fixed",
        top: rect.top - pad,
        left: rect.left - pad,
        width: rect.width + pad * 2,
        height: rect.height + pad * 2,
        borderRadius: 12,
        boxShadow: "0 0 0 9999px rgba(0,0,0,0.65)",
        pointerEvents: "none",
        transition: "top 0.25s ease, left 0.25s ease, width 0.25s ease, height 0.25s ease",
        zIndex: 100,
      }
    : { position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)", zIndex: 100 };

  // Capped to the viewport width (minus margins) rather than a flat 320 —
  // on a narrow phone (~320-360px wide) a fixed 320px card left almost no
  // room to clamp into, pushing tooltipLeft negative and clipping the card
  // off the left edge of the screen.
  const cardWidth = Math.min(320, window.innerWidth - 32);
  const tooltipTop = rect
    ? Math.min(Math.max(rect.bottom + pad + 12, 16), window.innerHeight - 200)
    : window.innerHeight / 2 - 90;
  const tooltipLeft = rect
    ? Math.min(Math.max(rect.left, 16), Math.max(16, window.innerWidth - cardWidth - 16))
    : window.innerWidth / 2 - cardWidth / 2;

  return (
    <>
      <div style={spotlightStyle} />
      <div
        className="fixed z-[101] rounded-xl border border-border bg-card p-4 shadow-xl flex flex-col gap-3"
        style={{ top: tooltipTop, left: tooltipLeft, width: cardWidth }}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Step {stepIndex + 1} of {totalSteps}
          </span>
          <button onClick={skip} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Skip tour
          </button>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            {currentStep.title}
          </h3>
          <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{currentStep.body}</p>
        </div>
        <div className="flex items-center justify-between pt-1">
          <button
            onClick={back}
            disabled={stepIndex === 0}
            className="text-xs px-3 py-1.5 rounded-md border border-input text-muted-foreground hover:text-foreground disabled:opacity-40 transition-colors"
          >
            ← Back
          </button>
          <button
            onClick={next}
            className="text-xs px-4 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
          >
            {stepIndex + 1 === totalSteps ? "Finish" : "Next →"}
          </button>
        </div>
      </div>
    </>
  );
}
