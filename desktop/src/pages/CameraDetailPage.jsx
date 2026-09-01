import { useState } from "react";
import { cardVisuals, detailPanels } from "../lib/cameraView.js";

function InfoPanel({ title, rows }) {
  return (
    <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
      <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>{title}</div>
      {rows.map((row) => (
        <div key={row.k} style={{ display: "flex", gap: 10, padding: "5px 0", fontSize: 13, borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
          <span style={{ width: 96, flex: "none", color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>{row.k}</span>
          <span style={{ minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5 }}>{row.v}</span>
        </div>
      ))}
    </div>
  );
}

// Click the name to rename it in place -- name only, not connection
// details (hostname/port/path/credentials aren't editable yet, that
// would need the same re-verification addCamera/addCameraViaRtsp do
// before saving, which renameCamera doesn't attempt).
function EditableCameraName({ camera, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(camera.label);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const label = value.trim();
    if (!label || label === camera.label) {
      setEditing(false);
      setValue(camera.label);
      return;
    }
    setSaving(true);
    const updated = await window.cameraAPI.rename(camera.id, label);
    setSaving(false);
    setEditing(false);
    onRenamed(updated);
  };

  if (editing) {
    return (
      <input
        className="input"
        autoFocus
        style={{ fontSize: 20, fontFamily: "var(--font-heading)", height: "auto", padding: "2px 8px", maxWidth: 320 }}
        value={value}
        disabled={saving}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") { setValue(camera.label); setEditing(false); }
        }}
      />
    );
  }

  return (
    <button
      className="btn btn-ghost"
      style={{ padding: 0, fontFamily: "var(--font-heading)", fontSize: 24, lineHeight: 1.2, color: "var(--color-text)", justifyContent: "flex-start", gap: 8 }}
      onClick={() => setEditing(true)}
      title="Rename this camera"
    >
      {camera.label}
      <i className="ph ph-pencil-simple" style={{ fontSize: 15, color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }} />
    </button>
  );
}

// Two-step: "Remove camera" first shows an inline confirm rather than
// removing on the first click (a real camera + its schedule are both
// gone for good -- electron-store, no undo) or using window.confirm's
// native OS dialog, which would look inconsistent against this app's own
// custom-drawn chrome.
function RemoveCameraControl({ camera, onRemoved }) {
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);

  const remove = async () => {
    setRemoving(true);
    await window.cameraAPI.remove(camera.id);
    onRemoved();
  };

  if (!confirming) {
    return (
      <button className="btn btn-ghost" style={{ fontSize: 12.5, flex: "none" }} onClick={() => setConfirming(true)}>
        <i className="ph ph-trash" style={{ fontSize: 14 }} />Remove camera
      </button>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
      <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Remove this camera and its schedule?</span>
      <button className="btn btn-secondary" style={{ fontSize: 12 }} disabled={removing} onClick={() => setConfirming(false)}>Cancel</button>
      <button className="btn btn-primary" style={{ fontSize: 12, color: "var(--color-accent-2-400)", borderColor: "var(--color-accent-2-400)" }} disabled={removing} onClick={remove}>
        {removing ? "Removing…" : "Remove"}
      </button>
    </div>
  );
}

// A configured camera's detail page only, now -- an unconfigured card
// (found via WS-Discovery or the RTSP sweep, `kind !== "configured"`)
// goes straight to ManualAddDialog from the grid instead (CamerasPage.jsx,
// 2026-09-01: one workflow to connect a camera regardless of how it was
// found, replacing this page's own separate, weaker inline sign-in form
// -- ONVIF-only, no RTSP fallback if it failed).
export default function CameraDetailPage({ card, onBack, onCameraRemoved, onCameraRenamed }) {
  const v = cardVisuals(card);
  const panels = detailPanels(card.camera);

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "18px 22px 26px" }}>
      <button className="btn btn-ghost" style={{ fontSize: 12.5, marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />All cameras
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <EditableCameraName camera={card.camera} onRenamed={onCameraRenamed} />
          <div style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", marginTop: 2 }}>{v.subtitle} · {v.ip}</div>
        </div>
        <RemoveCameraControl camera={card.camera} onRemoved={onCameraRemoved} />
      </div>

      <div style={{ position: "relative", aspectRatio: "16/9", borderRadius: "var(--radius-md)", overflow: "hidden", background: v.live ? "linear-gradient(160deg, var(--color-neutral-800), var(--color-neutral-900))" : "var(--color-neutral-900)", boxShadow: "var(--shadow-sm)" }}>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", alignContent: "center", gap: 8 }}>
          <i className={v.thumbIcon} style={{ fontSize: 44, color: v.live ? "var(--color-accent-300)" : "color-mix(in srgb, var(--color-text) 30%, transparent)" }} />
          <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 45%, transparent)" }}>
            No live preview yet — this app cuts highlight clips from footage, it doesn't decode RTSP for a viewer.
          </span>
        </div>
        <div style={{ position: "absolute", top: 10, left: 10 }}>
          <span className={v.stateTagClass}>{v.stateLabel}</span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 16 }}>
        <InfoPanel title="Identity" rows={panels.identity} />
        <InfoPanel title="Network" rows={panels.network} />
      </div>

      <div style={{ marginTop: 14, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
        <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Streams</div>
        {panels.streams.length === 0 ? (
          <p style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: 0 }}>
            No stream URI on record for this camera.
          </p>
        ) : (
          panels.streams.map((s) => (
            <div key={s.label} style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
              <span className="tag tag-outline">{s.label}</span>
              <span style={{ flex: 1, minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.url}</span>
              <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>{s.spec}</span>
              <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => navigator.clipboard.writeText(s.url)}>
                <i className="ph ph-copy" style={{ fontSize: 14 }} />Copy
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
