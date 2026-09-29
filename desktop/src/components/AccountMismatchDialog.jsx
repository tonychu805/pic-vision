import { useState } from "react";

// Shown when this machine is registered to one venue and someone signs in
// from another account (ADR-094).
//
// Since 2026-09-29 connecting to the new account no longer moves anything:
// the console gives this machine a separate record under that account and
// leaves the old account's record -- its calibrations, reels and history --
// exactly where it was (that move-by-device-id was a cross-account takeover
// path). Cameras reappear under the new account by themselves, because they
// live on this machine; calibrations do not, because they live on the old
// account's record. Switching back later finds that record again.
//
// It still asks rather than acting: which account records tonight's games is
// a person's call, not a launch sequence's. Deliberately blocking -- until
// it's answered this machine keeps reporting to the old account.

// Electron wraps anything a handler throws as "Error invoking remote
// method 'x': Error: <the real message>". The venue owner reading this
// dialog does not need our IPC channel names (PIC-93).
function readable(err) {
  return String(err?.message ?? err).replace(/^Error invoking remote method '[^']*':\s*(Error:\s*)?/, "");
}

export default function AccountMismatchDialog({ status, onMoved, onSignedOut }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const move = async () => {
    setBusy("move");
    setError(null);
    try {
      const connection = await window.cloudAPI.register();
      onMoved?.(connection);
    } catch (err) {
      setError(readable(err));
      setBusy(null);
    }
  };

  const signOut = async () => {
    setBusy("signout");
    setError(null);
    try {
      await window.authAPI.signOut();
      onSignedOut?.();
    } catch (err) {
      setError(readable(err));
      setBusy(null);
    }
  };

  const from = status.currentBrandName ?? "another venue";
  const to = status.sessionBrandName ?? "your account";

  return (
    <div className="dialog-backdrop">
      <div className="dialog" style={{ maxWidth: 480 }}>
        <div className="dialog-title">This machine is connected to a different account</div>
        <div className="dialog-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={{ margin: 0 }}>
            It's recording for <strong>{from}</strong>, but you're signed in as{" "}
            <strong>{status.email}</strong>
            {status.sessionBrandName ? <> — <strong>{to}</strong></> : null}.
          </p>
          <div className="notice notice-warning" style={{ display: "block" }}>
            If you connect it to {to}, its cameras will show up there, but camera calibrations made
            under {from} stay with {from} — calibrate again before recording. Past reels stay with the
            account that made them, and {from} will see this machine as offline.
          </div>
          <p style={{ margin: 0 }}>
            If this machine should keep recording for {from}, sign out and sign back in with that
            account instead.
          </p>
          {error && (
            <div className="notice notice-danger" style={{ display: "block" }}>{error}</div>
          )}
        </div>
        <div className="dialog-actions">
          <button className="btn btn-secondary" disabled={busy !== null} onClick={signOut}>
            {busy === "signout" ? "Signing out…" : "Sign out"}
          </button>
          <button className="btn btn-primary" disabled={busy !== null} onClick={move}>
            {busy === "move" ? "Connecting…" : `Connect it to ${to}`}
          </button>
        </div>
      </div>
    </div>
  );
}
