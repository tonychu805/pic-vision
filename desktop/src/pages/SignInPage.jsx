import { useState } from "react";
import { cleanIpcError } from "../lib/ipcError.js";
import { useI18n } from "../i18n.jsx";
import LanguageSwitch from "../components/LanguageSwitch.jsx";
// Same logo Sidebar.jsx already uses -- pic-vision-cloud-console/app/sign-in
// uses this identical file at public/pic-vision-logo-white.png, so both
// surfaces show the same mark.
import logo from "../assets/pic-vision-logo-white.png";

// Where an account is created (the console's sign-in page has a "Create one"
// switch). Production, the same default electron/cloud.js uses; nobody is
// signed in here yet, so there is no stored console address to use instead.
const CONSOLE_SIGN_UP_URL = "https://console.picvisionai.com/sign-in";

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
  const { t } = useI18n();
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
      setError(cleanIpcError(err, t));
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
            {t("signin.headline")}
          </h1>
          <p className="text-muted" style={{ fontSize: "var(--fs-strong)", lineHeight: 1.6 }}>
            {t("signin.lead")}
          </p>
        </div>
        <div style={{ display: "flex", gap: 20, fontSize: "var(--fs-fine)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-4)" }}>
          <span>{t("signin.tag1")}</span>
          <span>{t("signin.tag2")}</span>
          <span>{t("signin.tag3")}</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40, position: "relative" }}>
        {/* The first screen anyone sees, and the default is Chinese: someone who
            reads English needs the switch BEFORE they can sign in. */}
        <div style={{ position: "absolute", top: 16, right: 16 }}>
          <LanguageSwitch />
        </div>
        <div style={{ width: "min(340px, 100%)" }}>
          <div style={{ fontSize: "var(--fs-fine)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--color-accent-300)", marginBottom: 8 }}>
            {t("signin.eyebrow")}
          </div>
          <h2 style={{ fontFamily: "var(--font-heading)", fontWeight: 500, fontSize: 24, margin: "0 0 6px" }}>{t("signin.title")}</h2>
          <p className="text-muted" style={{ fontSize: "var(--fs-strong)", margin: "0 0 24px" }}>
            {t("signin.sub")}
          </p>

          {AUTH_API_MISSING ? (
            <p style={{ fontSize: "var(--fs-body)", color: "var(--color-danger)" }}>
              {t("signin.notLoaded")}
            </p>
          ) : (
            <form onSubmit={submit}>
              <div className="field" style={{ marginBottom: 14 }}>
                <label>{t("signin.email")}</label>
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
                <label>{t("signin.password")}</label>
                <input
                  className="input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              {/* "Keep me signed in" stood here until 2026-09-20. It came in
                  with the design mockup and was never wired to anything --
                  permanently greyed out, with its only explanation in a
                  tooltip nobody hovers, which reads as broken rather than
                  as deliberate. It was reported as "doesn't work", fairly.

                  Removed rather than wired up because the behaviour it
                  promised is simply what the app does: the session is
                  saved and renewed in the background. What made that
                  untrue was a bug in the renewal, not a missing option --
                  any failure at all used to throw the login away (see
                  auth.js's sessionIsOver). Fixed in the same change.

                  Worth building for real only if venues start sharing a
                  machine, where "don't save my login here" is a genuine
                  request. It is not one today. */}
              {/* "Forgot password" stood here, greyed out with an "isn't built
                  yet" tooltip -- the same never-wired mockup leftover as "Keep
                  me signed in" above, and a dead end for exactly the person
                  who needs help. Removed 2026-09-29: there is no password
                  reset anywhere yet, the console included. */}
              <div style={{ marginBottom: 18 }} />

              {error && <p className="text-muted" style={{ fontSize: "var(--fs-body)", marginBottom: 14 }}>{error}</p>}

              <button type="submit" className="btn btn-primary" disabled={submitting || !email.trim() || !password} style={{ width: "100%", marginBottom: 8 }}>
                {submitting ? t("signin.submitting") : t("signin.submit")}
              </button>
              {/* "Continue with single sign-on" stood here, permanently
                  disabled -- a mockup control for a feature that doesn't
                  exist. Removed 2026-09-29. */}
            </form>
          )}

          <p className="text-muted" style={{ fontSize: "var(--fs-fine)", marginTop: 20 }}>
            {t("signin.noAccount")}{" "}
            {/* A real link now (2026-09-29); it was plain text. */}
            <a
              href={CONSOLE_SIGN_UP_URL}
              onClick={(e) => { e.preventDefault(); window.systemAPI?.openExternal?.(CONSOLE_SIGN_UP_URL); }}
              style={{ color: "var(--color-accent-300)" }}
            >
              {t("signin.createLink")}
            </a>
          </p>
          <p className="text-muted" style={{ fontSize: "var(--fs-fine)", marginTop: 6 }}>
            {t("signin.autoConnect")}
          </p>
        </div>
      </div>
    </div>
  );
}
