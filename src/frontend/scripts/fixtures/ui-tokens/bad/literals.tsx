// Self-test fixture for scripts/check-ui-tokens.mjs (grep mode). Not compiled.
// Colour literals in Tailwind arbitrary values, style props and SVG attributes.

export function Literals() {
  return (
    <div>
      <p style={{ color: "#fff" }}>White</p> {/* @expect style-color */}
      <div style={{ background: "rgba(0,0,0,.5)" }} /> {/* @expect style-color */}
      <div style={{ backgroundColor: 'hsl(0 50% 50%)' }} /> {/* @expect style-color */}
      <div style={{ boxShadow: "0 0 0 9999px rgba(0,0,0,0.65)" }} /> {/* @expect style-color */}
      <div style={{ borderTopColor: "#A1B2C3D4" }} /> {/* @expect style-color */}
      <div className="bg-[#123456]" /> {/* @expect arbitrary-color */}
      <div className="hover:text-[rgb(255,0,0)]" /> {/* @expect arbitrary-color */}
      <div className="shadow-[0_0_0_4px_rgba(0,0,0,.4)]" /> {/* @expect arbitrary-color */}
      <div className="border-[hsl(10,50%,50%)]" /> {/* @expect arbitrary-color */}
      <svg><path fill="#abc" /></svg> {/* @expect svg-color */}
      <svg><path stroke={"rgb(1,2,3)"} /></svg> {/* @expect svg-color */}
      <svg><stop stopColor="#00ff00" /></svg> {/* @expect svg-color */}
    </div>
  );
}

const overlay = {
  position: "fixed",
  background: "#000000", // @expect style-color
  "border-color": "rgb(0, 0, 0)", // @expect style-color
};
