import { cardVisuals } from "../lib/cameraView.js";

// Row layout, not a card grid (2026-09-05: dropped in favor of a list --
// these never showed a real video thumbnail anyway, just a status icon on a
// gradient placeholder, so the card's biggest visual element was dead
// space). Same fields as before (icon, name, subtitle, state tag, dismiss),
// just laid out horizontally instead of stacked over a thumbnail.
//
// A real <button>, not a <div onClick> (2026-09-06): opening a camera is
// the main screen's primary action and it could not be reached by keyboard
// at all -- no tab stop, no Enter/Space, no focus ring, and no hover state
// to say it was clickable. `.row-button` in index.css is the button reset
// plus the hover/active states.
//
// The dismiss control has to stay outside that button -- a <button> inside
// a <button> is invalid HTML and browsers do not agree on what to do with
// it -- so the row is a flex container holding the big button plus, when
// relevant, the dismiss button as a sibling.
export default function CameraCard({ card, selectMode, picked, onOpen, onDismiss }) {
  const v = cardVisuals(card);
  const dismissable = !selectMode && card.kind !== "configured";

  return (
    <div style={{ display: "flex", alignItems: "stretch", gap: 6 }}>
      <button
        type="button"
        className="row-button"
        style={{ flex: 1, minWidth: 0, boxShadow: picked && selectMode ? "0 0 0 2px var(--color-accent)" : "var(--shadow-sm)" }}
        onClick={onOpen}
      >
        <span
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
            style={{ fontSize: 16, color: v.live ? "var(--color-accent-300)" : "var(--text-4)" }}
          />
        </span>

        <span style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "baseline", gap: 8 }}>
          <span className="truncate" style={{ fontWeight: 500, fontSize: "var(--fs-strong)" }}>
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
          <span className="truncate text-3" style={{ fontSize: "var(--fs-body)" }}>
            {v.subtitle}
          </span>
        </span>

        <span className={v.stateTagClass} style={{ flex: "none" }}>{v.stateLabel}</span>

        {selectMode && (
          <i
            className={picked ? "ph-fill ph-check-circle" : "ph ph-circle"}
            style={{ flex: "none", fontSize: 20, color: picked ? "var(--color-accent)" : "var(--text-4)" }}
          />
        )}
      </button>

      {/* A not-yet-configured card (found by discovery/sweep, never saved
          anywhere) shouldn't require signing in just to get rid of it --
          e.g. a device that turned out not to be the operator's camera at
          all. Dismisses from this scan's results only (session-local, not
          persisted) -- it can reappear on the next "Scan again" since the
          device is still really there. */}
      {dismissable && (
        <button
          className="btn btn-ghost"
          style={{ flex: "none", padding: "0 6px", minHeight: 0 }}
          title="Not my camera — remove from this list"
          aria-label={`Remove ${v.name} from this list`}
          onClick={onDismiss}
        >
          <i className="ph ph-x" style={{ fontSize: 13 }} />
        </button>
      )}
    </div>
  );
}
