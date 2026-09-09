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

// Version, and a manual check for a newer one.
//
// Manual on purpose: the venue builds aren't signed by Apple, and
// automatic updating needs a signature, so the honest thing is to say
// what's available and let the operator install it. It sits in Details
// because that's the "about this install" block -- and because the first
// thing a support conversation needs is which version they're on.
function UpdateRow() {
  const [version, setVersion] = useState("");
  const [result, setResult] = useState(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    window.updatesAPI?.check?.().then((r) => {
      setVersion(r.current);
      setResult(r);
    }).catch(() => {});
  }, []);

  const check = async () => {
    setChecking(true);
    try {
      const r = await window.updatesAPI.check();
      setVersion(r.current);
      setResult(r);
    } catch {
      setResult({ status: "unknown" });
    }
    setChecking(false);
  };

  const hint =
    result?.status === "outdated" ? `Version ${result.latest} is available`
    : result?.status === "current" ? "This is the latest version"
    : result?.status === "unknown" ? "Couldn't check for updates just now"
    : undefined;

  return (
    <DetailRow label="Version" value={version || "…"} mono hint={hint}>
      {result?.status === "outdated" ? (
        <button
          type="button"
          className="btn btn-ghost"
          style={{ fontSize: "var(--fs-fine)", padding: 0, color: "var(--color-accent)" }}
          onClick={() => window.systemAPI?.openExternal?.(result.downloadUrl)}
        >
          Download<i className="ph ph-arrow-square-out" style={{ fontSize: 12 }} />
        </button>
      ) : (
        <button
          type="button"
          className="btn btn-ghost"
          style={{ fontSize: "var(--fs-fine)", padding: 0 }}
          onClick={check}
          disabled={checking}
        >
          {checking ? "Checking…" : "Check for updates"}
        </button>
      )}
    </DetailRow>
  );
}

export default function CloudPage({ session, onSignedOut, connectionEpoch = 0, onConnectionChanged }) {
  const [connection, setConnection] = useState(undefined); // undefined = loading
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState("");
  const [agentName, setAgentNameField] = useState("");
  const [savedName, setSavedName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const [signingOut, setSigningOut] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

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
    // Re-reads when the connection is replaced elsewhere in the app --
    // the account-mismatch dialog moving this machine to another venue.
  }, [connectionEpoch]);

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
      onConnectionChanged?.();
    } catch (err) {
      setError(err.message);
    }
    setRegistering(false);
  };

  const disconnect = async () => {
    try {
      await window.cloudAPI.disconnect();
      setConnection(null);
      onConnectionChanged?.();
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
      <div className="page-title" style={{ marginBottom: 4 }}>This machine</div>
      <p className="page-sub" style={{ marginBottom: 16 }}>
        Signing in is what connects this machine to a venue — there is no separate step. It keeps reporting on its
        own from then on, including while nobody is signed in here.
      </p>

      {/* One error line for the whole page. It used to live inside the
          disconnected branch only, so a failure from Save / Disconnect /
          Sign out set the state but rendered nothing. */}
      {error && (
        <p style={{ maxWidth: 420, color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: "0 0 12px" }}>{error}</p>
      )}

      {/* One status, not two. Sign-in and the machine's registration used
          to sit in separate cards -- a "Connection" card above a "Signed
          in as" row -- which read as two independent connections you had
          to establish. They aren't: signing in registers the machine
          (ADR-079), and the two exist separately underneath only because
          the machine's identity has to outlive any one person's session,
          or an unattended venue Mac would stop recording the moment
          somebody signed out (ADR-094/096). So: one line saying what this
          machine is doing and who is signed in, and the rarer "hand the
          machine to another venue" action kept away from the everyday
          sign-out. */}
      <div className="card" style={{ maxWidth: 420, marginBottom: 12 }}>
        {connection === undefined ? (
          <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: 0 }}>Checking connection…</p>
        ) : connection ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <i className="ph-fill ph-check-circle" style={{ fontSize: 16, color: "var(--color-success)" }} />
              <span style={{ fontWeight: 500 }}>Recording for {connection.brandName}</span>
            </div>
            {session?.user && (
              <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: "6px 0 0" }}>
                Signed in as {session.user.email}
              </p>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
              <button type="button" className="btn btn-secondary" onClick={signOut} disabled={signingOut}>
                {signingOut ? "Signing out…" : "Sign out"}
              </button>
              <span style={{ fontSize: "var(--fs-fine)", color: "var(--text-4)", lineHeight: 1.45 }}>
                This machine keeps recording and reporting.
              </span>
            </div>
          </>
        ) : (
          <>
            <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: "0 0 12px" }}>
              This machine isn't attached to a venue. That normally happens by itself when you sign in — if it
              didn't (the console was unreachable), or you removed it from a venue on purpose, connect it here.
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
        <DetailRow label="Device ID" value={deviceId} mono hint="Fixed — identifies this machine to the console across re-registrations." />
        <UpdateRow />
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

      {/* Deliberately down here and two-step. This is the handover action
          -- the machine stops reporting to this venue until someone
          reconnects it -- not the everyday sign-out it used to sit next
          to as an equal-looking "Disconnect" button. */}
      {connection && (
        <div style={{ maxWidth: 420, marginTop: 14 }}>
          {confirmingRemove ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className="text-3" style={{ fontSize: "var(--fs-body)" }}>
                Stop this machine reporting to {connection.brandName}?
              </span>
              <button className="btn btn-secondary" style={{ fontSize: "var(--fs-fine)" }} onClick={() => setConfirmingRemove(false)}>Cancel</button>
              <button
                className="btn btn-primary"
                style={{ fontSize: "var(--fs-fine)", color: "var(--color-danger)", borderColor: "var(--color-danger)" }}
                onClick={async () => { await disconnect(); setConfirmingRemove(false); }}
              >
                Remove it
              </button>
            </div>
          ) : (
            <button className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)", padding: 0 }} onClick={() => setConfirmingRemove(true)}>
              Remove this machine from {connection.brandName}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
