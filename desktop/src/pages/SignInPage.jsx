import { useState } from "react";
// Same logo Sidebar.jsx already uses -- pic-vision-cloud-console/app/sign-in
// uses this identical file at public/pic-vision-logo-white.png, so both
// surfaces show the same mark.
import logo from "../assets/pic-vision-logo-white.png";

// Gates App.jsx's render until an operator signs in with the same account
// used on the cloud console (Supabase auth, electron/auth.js). Signing in
// also registers this device with the console automatically (ADR-079) --
// a brand with multiple venues just signs in with the same account on
// every machine, and each one shows up as its own row on the console
// (keyed by its own local device id), no code to generate or type.
//
// Deliberately mirrors pic-vision-cloud-console/app/sign-in/page.tsx's
// layout and copy (operator request, 2026-09-05: "i want the login to
// look like the cloud console log in") -- same split screen, same eyebrow/
// heading/field structure, same disabled "Keep me signed in"/"Forgot
// password"/SSO placeholders for one-to-one visual parity. Two deliberate
// differences, not oversights: no sign-up mode (an account is created on
// the cloud console, never on this device -- desktop only ever signs in
// to an existing one), and the left panel's gradient uses a real token
// (--color-accent-900) instead of the console page's `--color-section-
// glow`, which isn't defined anywhere in that app's CSS -- copying it
// here would silently render no gradient at all, the same dead style the
// console has right now.
//
// Same preload-not-reloaded guard as CloudPage.jsx's CLOUD_API_MISSING --
// a main-process-only change needs a full quit-and-relaunch, not a
// renderer reload, to take effect.
const AUTH_API_MISSING = typeof window !== "undefined" && typeof window.authAPI?.signIn !== "function";

export default function SignInPage({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const session = await window.authAPI.signIn(email.trim(), password);
      onSignedIn(session);
    } catch (err) {
      setError(err.message);
      setSubmitting(false);
    }
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 40,
          background: "radial-gradient(circle at 20% 0%, var(--color-accent-900), var(--color-bg) 60%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 22, height: 22, flex: "none", overflow: "hidden" }}>
            <img src={logo} alt="picvision ai" style={{ height: 22, width: "auto", maxWidth: "none" }} />
          </div>
          <span style={{ fontFamily: "var(--font-heading)", fontWeight: 500, fontSize: 15 }}>picvision ai</span>
        </div>
        <div style={{ maxWidth: 380 }}>
          <div style={{ width: 40, height: 2, background: "var(--color-accent)", marginBottom: 20 }} />
          <h1 style={{ fontFamily: "var(--font-heading)", fontWeight: 500, fontSize: 38, lineHeight: 1.15, margin: "0 0 16px" }}>
            Every rally, cut by morning.
          </h1>
          <p className="text-muted" style={{ fontSize: 14, lineHeight: 1.6 }}>
            This machine handles the cameras at your court. Sign in with your brand's account to connect it.
          </p>
        </div>
        <div style={{ display: "flex", gap: 20, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }}>
          <span>Brand operations</span>
          <span>Camera fleet</span>
          <span>Reel delivery</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
        <div style={{ width: "min(340px, 100%)" }}>
          <div style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--color-accent-300)", marginBottom: 8 }}>
            Desktop sign in
          </div>
          <h2 style={{ fontFamily: "var(--font-heading)", fontWeight: 500, fontSize: 24, margin: "0 0 6px" }}>Sign in to your brand</h2>
          <p className="text-muted" style={{ fontSize: 13.5, margin: "0 0 24px" }}>
            Use the same email and password as your picvision cloud console account.
          </p>

          {AUTH_API_MISSING ? (
            <p style={{ fontSize: 13, color: "var(--color-accent-2-400)" }}>
              This feature isn't loaded yet -- fully quit and restart the app (not just reload the window).
            </p>
          ) : (
            <form onSubmit={submit}>
              <div className="field" style={{ marginBottom: 14 }}>
                <label>Work email</label>
                <input
                  className="input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoFocus
                  required
                />
              </div>
              <div className="field" style={{ marginBottom: 12 }}>
                <label>Password</label>
                <input
                  className="input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                <label className="radio" style={{ fontSize: 12.5 }} title="Sessions already stay signed in by default">
                  <input type="checkbox" disabled />
                  <span className="dot" style={{ borderRadius: 4 }} />
                  Keep me signed in
                </label>
                <span style={{ fontSize: 12.5, opacity: 0.5, cursor: "not-allowed" }} title="Password reset isn't built yet">
                  Forgot password
                </span>
              </div>

              {error && <p className="text-muted" style={{ fontSize: 13, marginBottom: 14 }}>{error}</p>}

              <button type="submit" className="btn btn-primary" disabled={submitting || !email.trim() || !password} style={{ width: "100%", marginBottom: 8 }}>
                {submitting ? "Signing in…" : "Sign in"}
              </button>
              <button type="button" className="btn btn-secondary" disabled style={{ width: "100%" }} title="Single sign-on isn't built yet">
                Continue with single sign-on
              </button>
            </form>
          )}

          <p className="text-muted" style={{ fontSize: 12, marginTop: 20 }}>
            Don't have an account yet? Create one on the cloud console.
          </p>
          <p className="text-muted" style={{ fontSize: 11.5, marginTop: 6 }}>
            Once signed in, this device connects to the Cloud console automatically.
          </p>
        </div>
      </div>
    </div>
  );
}
