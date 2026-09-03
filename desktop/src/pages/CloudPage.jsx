import { useEffect, useState } from "react";

// Pairing UI for cloud.js's first real outbound link to
// pic-vision-cloud-console (ADR-071) -- a real page, not a PreviewBanner
// mockup like SettingsPage.jsx/CredentialsPage.jsx. Only proves the pipe
// works (pairing + a heartbeat the console shows as "online"); no
// camera/court/reel data crosses this yet.
// A main-process/preload change (like cloudAPI itself) only takes effect
// after a full quit-and-relaunch, not a renderer reload -- the same gap
// that silently broke ManualAddDialog's pickVideoFile button 2026-09-03
// (see CameraDetailPage.jsx's importFile). There, the call was behind a
// click handler so the failure was invisible; here refresh() runs
// unconditionally on mount, so calling window.cloudAPI.status() while
// it's still undefined throws synchronously inside an effect with no
// error boundary -- crashes the page instead of failing visibly. Checked
// once, up front, so the whole component can render a real message
// instead of any of that.
const CLOUD_API_MISSING = typeof window !== "undefined" && typeof window.cloudAPI?.status !== "function";

export default function CloudPage() {
  const [connection, setConnection] = useState(undefined); // undefined = loading
  const [code, setCode] = useState("");
  const [pairing, setPairing] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => window.cloudAPI.status().then(setConnection).catch((err) => setError(err.message));
  useEffect(() => {
    if (!CLOUD_API_MISSING) refresh();
  }, []);

  const connect = async (e) => {
    e.preventDefault();
    setPairing(true);
    setError("");
    try {
      const conn = await window.cloudAPI.pair(code.trim());
      setConnection(conn);
      setCode("");
    } catch (err) {
      setError(err.message);
    }
    setPairing(false);
  };

  const disconnect = async () => {
    try {
      await window.cloudAPI.disconnect();
      setConnection(null);
    } catch (err) {
      setError(err.message);
    }
  };

  if (CLOUD_API_MISSING) {
    return (
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "16px 22px 26px" }}>
        <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2, marginBottom: 14 }}>Cloud console</div>
        <p style={{ fontSize: 13, color: "var(--color-accent-2-400)" }}>
          This feature isn't loaded yet -- fully quit and restart the app (not just reload the window).
        </p>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "16px 22px 26px" }}>
      <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2, marginBottom: 14 }}>Cloud console</div>

      <div style={{ maxWidth: 420, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
        {connection === undefined ? (
          <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Checking connection…</p>
        ) : connection ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <i className="ph-fill ph-check-circle" style={{ fontSize: 16, color: "var(--color-accent)" }} />
              <span style={{ fontWeight: 500 }}>Connected as {connection.venueName}</span>
            </div>
            <p style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: "0 0 12px" }}>
              Paired {new Date(connection.pairedAt).toLocaleString()} · reporting status to {connection.consoleUrl}
            </p>
            <button type="button" className="btn btn-secondary" onClick={disconnect}>Disconnect</button>
          </>
        ) : (
          <>
            <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", margin: "0 0 12px" }}>
              Generate a pairing code on the cloud console's dashboard, then enter it here.
            </p>
            <form onSubmit={connect} style={{ display: "flex", gap: 8 }}>
              <input
                className="input"
                placeholder="Pairing code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                style={{ flex: 1, fontFamily: "ui-monospace, Menlo, monospace", letterSpacing: "0.1em", textTransform: "uppercase" }}
                maxLength={8}
                required
              />
              <button className="btn btn-primary" disabled={pairing || !code.trim()}>
                {pairing ? "Connecting…" : "Connect"}
              </button>
            </form>
            {error && <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: "10px 0 0" }}>{error}</p>}
          </>
        )}
      </div>
    </div>
  );
}
