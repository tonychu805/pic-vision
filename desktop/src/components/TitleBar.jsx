// The mockup drew all three mac dots in flat --color-neutral-700 (an
// unfocused/decorative look, consistent with Nocturne's understated mono
// accent). Deliberately deviated from here: since the window is frameless,
// these are the ONLY way to close/minimize/maximize it -- real macOS
// red/yellow/green semantics are load-bearing for discoverability, not
// just decoration, once the buttons are wired to real window control.
const isMac = window.platformAPI?.platform === "darwin";

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
      {isMac && (
        <div style={{ display: "flex", gap: 7, WebkitAppRegion: "no-drag" }}>
          <button
            onClick={() => window.windowAPI.close()}
            style={dotStyle("#ff5f57")}
            aria-label="Close"
          />
          <button
            onClick={() => window.windowAPI.minimize()}
            style={dotStyle("#febc2e")}
            aria-label="Minimize"
          />
          <button
            onClick={() => window.windowAPI.maximize()}
            style={dotStyle("#28c840")}
            aria-label="Maximize"
          />
        </div>
      )}
      <div
        style={{
          flex: 1,
          fontSize: 12,
          fontWeight: 500,
          color: "color-mix(in srgb, var(--color-text) 55%, transparent)",
          textAlign: "center",
        }}
      >
        picvision ai — Court Cameras
      </div>
      {!isMac && (
        <div style={{ display: "flex", gap: 2, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", WebkitAppRegion: "no-drag" }}>
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
      {isMac && <div style={{ width: 52 }} />}
    </div>
  );
}

function dotStyle(color) {
  return {
    width: 11,
    height: 11,
    borderRadius: "50%",
    background: color,
    border: "none",
    padding: 0,
    cursor: "pointer",
  };
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
