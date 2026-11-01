// Self-test fixture for scripts/check-ui-tokens.mjs (grep mode). Not compiled:
// it lives outside src/, so tsc and Vite never see it. Every line marked
// `@expect <rule>` must be flagged with that rule; no other line may be.

export function HardcodedClasses() {
  return (
    <div>
      <p className="text-red-500">Failed</p> {/* @expect hardcoded-color */}
      <button className="hover:bg-green-500/10">Ok</button> {/* @expect hardcoded-color */}
      <div className="border-t-amber-400" /> {/* @expect hardcoded-color */}
      <div className="md:dark:text-amber-400" /> {/* @expect hardcoded-color */}
      <div className="ring-red-600 ring-offset-green-200" /> {/* @expect hardcoded-color */}
      <svg className="fill-green-500 stroke-red-700" /> {/* @expect hardcoded-color */}
      <div className="bg-gradient-to-r from-amber-300 via-red-400 to-green-500" /> {/* @expect hardcoded-color */}
      <div className={`px-2 ${ok ? "text-green-600" : ""}`} /> {/* @expect hardcoded-color */}
      <p className="text-destructive">Error</p> {/* @expect destructive-text */}
      <a className="hover:text-destructive/80">Delete</a> {/* @expect destructive-text */}
      <span className="bg-destructive/15 text-destructive border-destructive/30" /> {/* @expect destructive-text */}
    </div>
  );
}

const STATUS = {
  dead: "text-red-500 bg-red-500/10 border-red-500/20", // @expect hardcoded-color
  error: "text-destructive", // @expect destructive-text
};
