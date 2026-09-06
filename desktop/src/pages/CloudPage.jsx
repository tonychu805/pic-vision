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

// A read-only fact: label, plain value, optional trailing action. Deliberately
// not an <input readOnly> -- that's what made the page read as a form of
// fields you could type into when only the agent name is actually editable.
function DetailRow({ label, value, mono, hint, children }) {
  return (
    <div style={{ padding: "7px 0", borderTop: "1px solid var(--hairline)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontSize: "var(--fs-fine)", color: "var(--text-4)", flex: "none", width: 92 }}>
          {label}
        </span>
        <span
          style={{
            flex: 1,
            minWidth: 0,
            fontSize: mono ? 12 : 12.5,
            fontFamily: mono ? "var(--font-mono)" : undefined,
            color: "color-mix(in srgb, var(--color-text) 80%, transparent)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            userSelect: "text",
          }}
          title={value}
        >
          {value}
        </span>
        {children}
      </div>
      {hint && (
        <p style={{ fontSize: "var(--fs-fine)", color: "var(--text-4)", margin: "4px 0 0 102px", lineHeight: 1.5 }}>
          {hint}
        </p>
      )}
    </div>
  );
}

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
      <div className="page">
        <div className="page-title" style={{ marginBottom: 14 }}>Cloud console</div>
        <p style={{ fontSize: "var(--fs-body)", color: "var(--color-danger)" }}>
          This feature isn't loaded yet -- fully quit and restart the app (not just reload the window).
        </p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-title" style={{ marginBottom: 4 }}>Cloud console</div>
      <p className="page-sub" style={{ marginBottom: 16 }}>
        This machine reports its status to the console on its own. The top of this page is what you can change;
        everything under "Details" is read-only.
      </p>

      {/* One error line for the whole page. It used to live inside the
          disconnected branch only, so a failure from Save / Disconnect /
          Sign out set the state but rendered nothing. */}
      {error && (
        <p style={{ maxWidth: 420, color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: "0 0 12px" }}>{error}</p>
      )}

      <div className="card" style={{ maxWidth: 420, marginBottom: 12 }}>
        <div className="section-label">Connection</div>
        {connection === undefined ? (
          <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: 0 }}>Checking connection…</p>
        ) : connection ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <i className="ph-fill ph-check-circle" style={{ fontSize: 16, color: "var(--color-accent)" }} />
              <span style={{ fontWeight: 500 }}>Connected as {connection.brandName}</span>
            </div>
            <button type="button" className="btn btn-secondary" onClick={disconnect}>Disconnect</button>
          </>
        ) : (
          <>
            <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: "0 0 12px" }}>
              This device usually registers itself automatically right after you sign in. If it hasn't yet (e.g. the
              console was unreachable at the time), try again below.
            </p>
            <button type="button" className="btn btn-primary" onClick={retryRegister} disabled={registering}>
              {registering ? "Connecting…" : "Connect to the cloud console"}
            </button>
          </>
        )}
      </div>

      <div className="card" style={{ maxWidth: 420, marginBottom: 20 }}>
        <div className="section-label">Agent name</div>
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
        <p style={{ fontSize: "var(--fs-fine)", color: "var(--text-4)", margin: "8px 0 0", lineHeight: 1.5 }}>
          What this machine is called on the console's "Connected agents" list. Naming it after where it sits
          ("Front desk Mac") makes it easier to tell apart once a venue has more than one.
        </p>
      </div>

      {/* Read-only from here down. No surface fill and no input boxes --
          a readOnly <input> is what made the Device ID look editable. */}
      <div className="card-quiet" style={{ maxWidth: 420 }}>
        <div className="section-label section-label-quiet">Details</div>
        {session?.user && (
          <DetailRow label="Signed in as" value={session.user.email}>
            <button type="button" className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)", padding: 0 }} onClick={signOut} disabled={signingOut}>
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </DetailRow>
        )}
        <DetailRow label="Device ID" value={deviceId} mono hint="Fixed — identifies this machine to the console across re-registrations." />
        {connection && (
          <>
            {/* pairedAt fallback: a connection saved before today's ADR-079
                rename (this field used to be called that) still has the
                old name in its local electron-store JSON -- there's no
                migration step for it, so both names need to keep working. */}
            <DetailRow label="Registered" value={new Date(connection.connectedAt ?? connection.pairedAt).toLocaleString()} />
            <DetailRow label="Reporting to" value={connection.consoleUrl} mono />
          </>
        )}
      </div>
    </div>
  );
}
