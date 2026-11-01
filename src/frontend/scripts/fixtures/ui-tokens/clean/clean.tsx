// Self-test fixture for scripts/check-ui-tokens.mjs (grep mode). Not compiled.
// Everything here is theme-aware and must pass.

export function Clean({ index }: { index: number }) {
  return (
    <div className="bg-card text-foreground">
      <p className="text-sm text-danger bg-destructive/10 rounded-md px-3 py-2">Something went wrong.</p>
      <a className="hover:text-danger/80">Delete</a>
      <button className="bg-destructive text-destructive-foreground hover:bg-destructive/90">Delete</button>
      <span className="bg-destructive/15 text-danger border-destructive/30">Faction</span>
      <span className="text-success bg-success/14 border-success/40">Alive</span>
      <span className="text-warning bg-warning/14 border-warning/40">Queued</span>
      <span className="border-live text-live bg-live/14">REC</span>
      <span className="ring-[9999px] ring-black/65 z-[101] w-[42px]" />
      <span className="text-[hsl(var(--danger))] bg-[hsl(var(--card)/0.5)]" />
      <p style={{ color: "hsl(var(--danger))", background: "hsl(var(--card) / 0.5)" }}>Token</p>
      <p style={{ borderRadius: 12, inset: 0, zIndex: 100 }}>Layout only</p>
      <svg fill="none" stroke="currentColor"><path fill="currentColor" /></svg>
      <svg><rect fill="url(#fade)" stroke="url('#edge')" /></svg>
      <span title="#1 of 3">#{index + 1} done</span>
      <a href="#top">Back to top</a>
      <p>Credits: red-team, green-field, amber-alert, 100% redesign.</p>
    </div>
  );
}

const ROLE_COLORS = {
  monster: "bg-destructive/15 text-danger border-destructive/30",
  faction: "bg-secondary/20 text-secondary-foreground border-secondary/30",
};
