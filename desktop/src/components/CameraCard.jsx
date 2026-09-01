import { cardVisuals } from "../lib/cameraView.js";

export default function CameraCard({ card, selectMode, picked, onOpen }) {
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
              ? "live sub-stream"
              : v.state === "auth"
                ? "preview locked"
                : v.state === "checking"
                  ? "checking…"
                  : v.state === "rtsp"
                    ? "RTSP responded, ONVIF unknown"
                    : v.state === "unconfirmed"
                      ? "port open, protocol unknown"
                      : "not answering"}
          </span>
        </div>
        <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6 }}>
          <span
            style={{
              padding: "2px 7px",
              borderRadius: "var(--radius-sm)",
              font: "600 9.5px ui-monospace, Menlo, monospace",
              letterSpacing: "0.08em",
              background: v.live ? "color-mix(in srgb, var(--color-accent) 85%, transparent)" : "color-mix(in srgb, #000 55%, transparent)",
              color: v.live ? "#161826" : "color-mix(in srgb, var(--color-text) 60%, transparent)",
            }}
          >
            {v.live ? "LIVE" : v.proto}
          </span>
        </div>
        {selectMode && (
          <div style={{ position: "absolute", top: 8, right: 8 }}>
            <i
              className={picked ? "ph-fill ph-check-circle" : "ph ph-circle"}
              style={{ fontSize: 20, color: picked ? "var(--color-accent)" : "color-mix(in srgb, var(--color-text) 45%, transparent)" }}
            />
          </div>
        )}
      </div>
      <div style={{ padding: "10px 12px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 7, height: 7, flex: "none", borderRadius: "50%", background: v.dot }} />
          <span style={{ fontWeight: 500, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {v.name}
          </span>
          <span style={{ marginLeft: "auto", fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
            {v.ip}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>{v.subtitle}</div>
        <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
          <span className={v.stateTagClass}>{v.stateLabel}</span>
          <span className="tag tag-neutral">{v.proto}</span>
        </div>
      </div>
    </div>
  );
}
