import { cardVisuals } from "../lib/cameraView.js";

export default function CameraCard({ card, selectMode, picked, onOpen, onDismiss }) {
  const v = cardVisuals(card);
  return (
    <div
      style={{
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        cursor: "pointer",
        background: "var(--color-surface)",
        boxShadow: picked && selectMode ? "0 0 0 2px var(--color-accent)" : "var(--shadow-sm)",
      }}
      onClick={onOpen}
    >
      <div
        style={{
          position: "relative",
          aspectRatio: "16/9",
          background: v.live
            ? "linear-gradient(160deg, var(--color-neutral-800), var(--color-neutral-900))"
            : "var(--color-neutral-900)",
          overflow: "hidden",
        }}
      >
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", gap: 6, alignContent: "center" }}>
          <i
            className={v.thumbIcon}
            style={{ fontSize: 26, color: v.live ? "var(--color-accent-300)" : "color-mix(in srgb, var(--color-text) 30%, transparent)" }}
          />
          <span style={{ fontSize: 11, color: "color-mix(in srgb, var(--color-text) 45%, transparent)" }}>
            {v.live
              ? "connected"
              : v.state === "auth"
                ? "needs sign-in"
                : v.state === "checking"
                  ? "checking…"
                  : v.state === "rtsp"
                    ? "not set up yet"
                    : v.state === "unconfirmed"
                      ? "not sure what this is yet"
                      : "not responding"}
          </span>
        </div>
        {v.live && (
          <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6 }}>
            <span
              style={{
                padding: "2px 7px",
                borderRadius: "var(--radius-sm)",
                font: "600 9.5px ui-monospace, Menlo, monospace",
                letterSpacing: "0.08em",
                background: "color-mix(in srgb, var(--color-accent) 85%, transparent)",
                color: "#161826",
              }}
            >
              LIVE
            </span>
          </div>
        )}
        {selectMode ? (
          <div style={{ position: "absolute", top: 8, right: 8 }}>
            <i
              className={picked ? "ph-fill ph-check-circle" : "ph ph-circle"}
              style={{ fontSize: 20, color: picked ? "var(--color-accent)" : "color-mix(in srgb, var(--color-text) 45%, transparent)" }}
            />
          </div>
        ) : (
          // A not-yet-configured card (found by discovery/sweep, never
          // saved anywhere) shouldn't require signing in just to get rid
          // of it -- e.g. a device that turned out not to be the
          // operator's camera at all. Dismisses from this scan's results
          // only (session-local, not persisted) -- it can reappear on the
          // next "Scan again" since the device is still really there.
          card.kind !== "configured" && (
            <button
              className="btn btn-ghost"
              style={{ position: "absolute", top: 6, right: 6, padding: 4, minHeight: 0, background: "color-mix(in srgb, #000 45%, transparent)" }}
              title="Not my camera — remove from this list"
              onClick={(e) => { e.stopPropagation(); onDismiss?.(); }}
            >
              <i className="ph ph-x" style={{ fontSize: 13 }} />
            </button>
          )
        )}
      </div>
      <div style={{ padding: "10px 12px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 7, height: 7, flex: "none", borderRadius: "50%", background: v.dot }} />
          <span style={{ fontWeight: 500, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {v.name}
          </span>
        </div>
        {/* IP address and vendor/model dropped from the card entirely
            2026-09-01 ("hide ip and camera information on the card too",
            following the detail page's own collapse-by-default) -- that
            detail still lives on the camera's detail page, behind "Show
            camera details" there. Kept for discovered/sweep cards: their
            subtitle is an action prompt ("Tap to sign in"), not device
            info, and removing it would leave a card with no explanation
            of what tapping it does. */}
        {card.kind !== "configured" && (
          <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>{v.subtitle}</div>
        )}
        <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
          <span className={v.stateTagClass}>{v.stateLabel}</span>
        </div>
      </div>
    </div>
  );
}
