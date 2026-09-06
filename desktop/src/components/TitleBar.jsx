// No custom window buttons on macOS (2026-09-07).
//
// This used to draw its own red/yellow/green dots, on the reasoning that
// "the window is frameless, so these are the ONLY way to close it". That
// was true when written and stopped being true when main.js gained
// `titleBarStyle: "hiddenInset"` -- hiddenInset hides the title bar but
// KEEPS macOS's own traffic lights. Both sets then drew, overlapping, and
// the first packaged build showed four-ish dots in the corner.
//
// The native ones win: they get the hover glyphs, the green button's
// fullscreen menu, correct spacing for the OS version, and accessibility,
// none of which three <button>s reproduce. What's left here is a spacer so
// the centred title isn't sitting under them.
//
// windowAPI.close/minimize/maximize stay exposed in the preload -- a
// Windows or Linux build has no native controls with frame:false and would
// need them back.
const isMac = window.platformAPI?.platform === "darwin";

// Width of macOS's traffic lights plus their inset, measured against the
// hiddenInset layout. Only needs to be close: it's reserving space, not
// aligning to anything.
const MAC_TRAFFIC_LIGHT_WIDTH = 78;

export default function TitleBar() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        height: 40,
        flex: "none",
        padding: "0 12px",
        background: "var(--color-neutral-900)",
        WebkitAppRegion: "drag",
      }}
    >
      {isMac && <div style={{ width: MAC_TRAFFIC_LIGHT_WIDTH, flex: "none" }} aria-hidden="true" />}
      <div
        style={{
          flex: 1,
          fontSize: "var(--fs-fine)",
          fontWeight: 500,
          color: "var(--text-3)",
          textAlign: "center",
        }}
      >
        picvision ai — Court Cameras
      </div>
      {!isMac && (
        <div style={{ display: "flex", gap: 2, color: "var(--text-3)", WebkitAppRegion: "no-drag" }}>
          <button onClick={() => window.windowAPI.minimize()} style={winBtnStyle} aria-label="Minimize">
            <i className="ph ph-minus" style={{ fontSize: 13 }} />
          </button>
          <button onClick={() => window.windowAPI.maximize()} style={winBtnStyle} aria-label="Maximize">
            <i className="ph ph-square" style={{ fontSize: 11 }} />
          </button>
          <button onClick={() => window.windowAPI.close()} style={winBtnStyle} aria-label="Close">
            <i className="ph ph-x" style={{ fontSize: 13 }} />
          </button>
        </div>
      )}
      {/* Same width as the left spacer so the centred title is centred in
          the WINDOW, not in the space left over. The old value (52) balanced
          the custom dots that used to sit on the left; the native traffic
          lights are wider. */}
      {isMac && <div style={{ width: MAC_TRAFFIC_LIGHT_WIDTH, flex: "none" }} aria-hidden="true" />}
    </div>
  );
}

const winBtnStyle = {
  width: 34,
  height: 40,
  display: "grid",
  placeItems: "center",
  background: "transparent",
  border: "none",
  color: "inherit",
  cursor: "pointer",
};
