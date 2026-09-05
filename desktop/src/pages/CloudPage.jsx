import { useEffect, useState } from "react";

// Connection status UI for cloud.js's first real outbound link to
// pic-vision-cloud-console (ADR-071) -- a real page, not a PreviewBanner
// mockup like SettingsPage.jsx. Registration itself
// now happens automatically right after sign-in (ADR-079's replacement
// for the pairing-code flow this page used to host); this page just shows
// the result and offers a manual retry if that didn't succeed.
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

export default function CloudPage({ session, onSignedOut }) {
  const [connection, setConnection] = useState(undefined); // undefined = loading
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState("");
  const [agentName, setAgentNameField] = useState("");
  const [savedName, setSavedName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const [signingOut, setSigningOut] = useState(false);

  const refresh = () => window.cloudAPI.status().then(setConnection).catch((err) => setError(err.message));
  useEffect(() => {
    if (!CLOUD_API_MISSING) {
      refresh();
      window.cloudAPI.getAgentName().then((name) => {
        setAgentNameField(name);
        setSavedName(name);
      });
      window.cloudAPI.getDeviceId().then(setDeviceId);
    }
  }, []);

  const saveAgentName = async () => {
    const trimmed = agentName.trim();
    if (!trimmed || trimmed === savedName) return;
    setSavingName(true);
    try {
      const saved = await window.cloudAPI.setAgentName(trimmed);
      setAgentNameField(saved);
      setSavedName(saved);
    } catch (err) {
      setError(err.message);
    }
    setSavingName(false);
  };

  const retryRegister = async () => {
    setRegistering(true);
    setError("");
    try {
      const conn = await window.cloudAPI.register();
      setConnection(conn);
    } catch (err) {
      setError(err.message);
    }
    setRegistering(false);
  };

  const disconnect = async () => {
    try {
      await window.cloudAPI.disconnect();
      setConnection(null);
    } catch (err) {
      setError(err.message);
    }
  };

  const signOut = async () => {
    setSigningOut(true);
    try {
      await window.authAPI.signOut();
      onSignedOut?.();
    } catch (err) {
      setError(err.message);
      setSigningOut(false);
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

      {session?.user && (
        <div style={{ maxWidth: 420, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", marginBottom: 12, display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <label style={{ display: "block", fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", marginBottom: 4 }}>
              Signed in as
            </label>
            <span style={{ fontWeight: 500, fontSize: 13.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {session.user.email}
            </span>
          </div>
          <button type="button" className="btn btn-secondary" onClick={signOut} disabled={signingOut}>
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}

      <div style={{ maxWidth: 420, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", marginBottom: 12 }}>
        <label style={{ display: "block", fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", marginBottom: 8 }}>
          Device ID <span style={{ opacity: 0.7 }}>— fixed, identifies this machine to the console across re-registrations</span>
        </label>
        <input className="input" value={deviceId} readOnly style={{ fontFamily: "ui-monospace, Menlo, monospace", opacity: 0.85 }} />
      </div>

      <div style={{ maxWidth: 420, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", marginBottom: 12 }}>
        <label style={{ display: "block", fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", marginBottom: 8 }}>
          Agent name <span style={{ opacity: 0.7 }}>— shown on the console's "Connected agents" list</span>
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="input"
            value={agentName}
            onChange={(e) => setAgentNameField(e.target.value)}
            onBlur={saveAgentName}
            onKeyDown={(e) => e.key === "Enter" && saveAgentName()}
            style={{ flex: 1 }}
          />
          <button
            type="button"
            className="btn btn-secondary"
            onClick={saveAgentName}
            disabled={savingName || !agentName.trim() || agentName.trim() === savedName}
          >
            {savingName ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 420, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
        {connection === undefined ? (
          <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Checking connection…</p>
        ) : connection ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <i className="ph-fill ph-check-circle" style={{ fontSize: 16, color: "var(--color-accent)" }} />
              <span style={{ fontWeight: 500 }}>Connected as {connection.brandName}</span>
            </div>
            <p style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: "0 0 12px" }}>
              {/* pairedAt fallback: a connection saved before today's ADR-079
                  rename (this field used to be called that) still has the
                  old name in its local electron-store JSON -- there's no
                  migration step for it, so both names need to keep working. */}
              Registered {new Date(connection.connectedAt ?? connection.pairedAt).toLocaleString()} · reporting status to {connection.consoleUrl}
            </p>
            <button type="button" className="btn btn-secondary" onClick={disconnect}>Disconnect</button>
          </>
        ) : (
          <>
            <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", margin: "0 0 12px" }}>
              This device usually registers itself automatically right after you sign in. If it hasn't yet (e.g. the
              console was unreachable at the time), try again below.
            </p>
            <button type="button" className="btn btn-primary" onClick={retryRegister} disabled={registering}>
              {registering ? "Connecting…" : "Connect to the cloud console"}
            </button>
            {error && <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: "10px 0 0" }}>{error}</p>}
          </>
        )}
      </div>
    </div>
  );
}
