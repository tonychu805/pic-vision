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

function SignInInline({ device, onSignedIn }) {
  const [form, setForm] = useState({ label: "", username: "", password: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      const camera = await window.cameraAPI.add({
        label: form.label,
        hostname: device.hostname,
        port: device.port,
        username: form.username,
        password: form.password,
      });
      onSignedIn(camera);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginTop: 14, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-accent-900)" }}>
      <div style={{ flex: "none", width: 210 }}>
        <div style={{ fontSize: 13.5, fontWeight: 500, color: "var(--color-accent-100)" }}>Sign in to see this camera</div>
        <div style={{ fontSize: 11.5, color: "var(--color-accent-300)" }}>It answered discovery but hasn't been signed in to yet.</div>
        {error && <div style={{ fontSize: 11.5, color: "var(--color-accent-2-400)", marginTop: 4 }}>{error}</div>}
      </div>
      <div className="field" style={{ flex: 1 }}><label>User</label><input className="input" value={form.username} onChange={update("username")} /></div>
      <div className="field" style={{ flex: 1 }}><label>Password</label><input className="input" type="password" value={form.password} onChange={update("password")} /></div>
      <button className="btn btn-primary" style={{ flex: "none" }} disabled={saving} onClick={submit}>
        {saving ? "Signing in…" : "Sign in"}
      </button>
    </div>
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

export default function CameraDetailPage({ card, onBack, onCameraRemoved, onCameraSignedIn }) {
  const v = cardVisuals(card);
  const isDiscoveredOnly = card.kind === "discovered";
  const panels = isDiscoveredOnly ? null : detailPanels(card.camera);

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "18px 22px 26px" }}>
      <button className="btn btn-ghost" style={{ fontSize: 12.5, marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />All cameras
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 24, lineHeight: 1.2 }}>{v.name}</div>
          <div style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>{v.subtitle} · {v.ip}</div>
        </div>
        {!isDiscoveredOnly && <RemoveCameraControl camera={card.camera} onRemoved={onCameraRemoved} />}
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

      {isDiscoveredOnly && <SignInInline device={card.device} onSignedIn={onCameraSignedIn} />}

      {panels && (
        <>
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
        </>
      )}
    </div>
  );
}
