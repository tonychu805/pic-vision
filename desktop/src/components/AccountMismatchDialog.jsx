import { useState } from "react";

// Shown when this machine is registered to one venue and someone signs in
// from another account (ADR-094).
//
// It asks rather than acting because moving a machine is not a cosmetic
// change: the cameras attached to it move too, along with everything they
// go on to record, and the venue that had it loses it without being told.
// A launch sequence should not make that call on someone's behalf.
//
// Deliberately blocking — it sits over the app until answered. A device in
// this state is already reporting to the wrong venue every 30 seconds, so
// "remind me later" is not a safe option to offer.

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
        <div className="dialog-title">This machine belongs to a different venue</div>
        <div className="dialog-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={{ margin: 0 }}>
            It's set up as part of <strong>{from}</strong>, but you're signed in as{" "}
            <strong>{status.email}</strong>
            {status.sessionBrandName ? <> — <strong>{to}</strong></> : null}.
          </p>
          <div className="notice notice-warning" style={{ display: "block" }}>
            Moving it to {to} takes its cameras with it, along with any recordings they make from
            now on. {from} will no longer see this machine, and won't be told.
          </div>
          <p style={{ margin: 0 }}>
            If this machine really does sit at {from}, don't move it — sign out and sign back in with
            that venue's account instead.
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
            {busy === "move" ? "Moving…" : `Move it to ${to}`}
          </button>
        </div>
      </div>
    </div>
  );
}
