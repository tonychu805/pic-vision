import { cardVisuals } from "../lib/cameraView.js";

// Row layout, not a card grid (2026-09-05: dropped in favor of a list --
// these never showed a real video thumbnail anyway, just a status icon on a
// gradient placeholder, so the card's biggest visual element was dead
// space). Same fields as before (icon, name, subtitle, state tag, dismiss),
// just laid out horizontally instead of stacked over a thumbnail.
export default function CameraCard({ card, selectMode, picked, onOpen, onDismiss }) {
  const v = cardVisuals(card);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "10px 14px",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        background: "var(--color-surface)",
        boxShadow: picked && selectMode ? "0 0 0 2px var(--color-accent)" : "var(--shadow-sm)",
      }}
      onClick={onOpen}
    >
      <div
        style={{
          flex: "none",
          width: 36,
          height: 36,
          borderRadius: "50%",
          display: "grid",
          placeItems: "center",
          background: v.live ? "var(--color-accent-900)" : "var(--color-neutral-900)",
        }}
      >
        <i
          className={v.thumbIcon}
          style={{ fontSize: 16, color: v.live ? "var(--color-accent-300)" : "color-mix(in srgb, var(--color-text) 40%, transparent)" }}
        />
      </div>

      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 7, height: 7, flex: "none", borderRadius: "50%", background: v.dot }} />
        <div style={{ minWidth: 0, display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontWeight: 500, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {v.name}
          </span>
          {/* v.subtitle is the operator's label's counterpart: vendor/model
              for a real camera, "Sample clip" for a sample clip, or an
              action prompt ("Tap to sign in") for a not-yet-configured
              card -- the label alone ("Court 1") doesn't say what the
              camera actually is. Shown for every row (reversing the
              2026-09-01 card-view decision to hide it, per operator
              feedback 2026-09-05 that Court 1/2's rows gave no way to
              tell them apart from real device identity). */}
          <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {v.subtitle}
          </span>
        </div>
      </div>

      <span className={v.stateTagClass} style={{ flex: "none" }}>{v.stateLabel}</span>

      {selectMode ? (
        <i
          className={picked ? "ph-fill ph-check-circle" : "ph ph-circle"}
          style={{ flex: "none", fontSize: 20, color: picked ? "var(--color-accent)" : "color-mix(in srgb, var(--color-text) 45%, transparent)" }}
        />
      ) : (
        // A not-yet-configured card (found by discovery/sweep, never saved
        // anywhere) shouldn't require signing in just to get rid of it --
        // e.g. a device that turned out not to be the operator's camera at
        // all. Dismisses from this scan's results only (session-local, not
        // persisted) -- it can reappear on the next "Scan again" since the
        // device is still really there.
        card.kind !== "configured" && (
          <button
            className="btn btn-ghost"
            style={{ flex: "none", padding: 4, minHeight: 0 }}
            title="Not my camera — remove from this list"
            onClick={(e) => { e.stopPropagation(); onDismiss?.(); }}
          >
            <i className="ph ph-x" style={{ fontSize: 13 }} />
          </button>
        )
      )}
    </div>
  );
}
