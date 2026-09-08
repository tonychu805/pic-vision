// Account sign-in. Originally shipped alongside cloud.js's pairing-code
// flow (ADR-078, 2026-09-05), then that flow was replaced the same day
// (ADR-079) once the multi-location discussion made the redundancy
// obvious: `brands.owner_user_id` is unique (one brand per account), so
// signing in already identifies which brand this device belongs to --
// there was nothing left for a manually-typed code to prove. Signing in
// now also registers this device (`registerDevice`, calling cloud.js's
// `registerAgent`) automatically, right when it happens.
// Talks to Supabase directly (Auth + PostgREST), the same way
// pic-vision-cloud-console's own browser client does (lib/supabase/client.ts)
// -- no server-side proxy needed since brands.owner_user_id's RLS policy
// already scopes a `brands` select to the signed-in user, whether the JWT
// arrived via a cookie session (the console) or a bearer header (here).
import Store from "electron-store";
import { registerAgent, getCloudConnection, adoptConnection } from "./cloud.js";
import { logEvent } from "./activityLog.js";
import { encryptField, decryptField } from "./secureField.js";

// configFileMode 0600: owner-only, and set here rather than chmod-ed
// afterwards -- see activityLog.js for why that distinction matters.
const store = new Store({ name: "auth", configFileMode: 0o600 });

// A Supabase access/refresh token pair is a full user-session credential
// (unlike cloud.js's long-lived agent apiToken, this can sign in as the
// account owner). Centralized the same way cameras/store.js's password/
// streamUri are: every writer already builds a full session object and
// calls store.set once, so encrypting there and decrypting in the one
// place sessions get read back covers every caller.
function saveSession(session) {
  store.set("session", { ...session, accessToken: encryptField(session.accessToken), refreshToken: encryptField(session.refreshToken) });
}
function loadSession() {
  const session = store.get("session");
  if (!session) return null;
  const accessToken = decryptField(session.accessToken);
  // A stored (non-null) token that comes back null failed to decrypt --
  // vault cleared, or moved to a different machine/OS user, since keys
  // aren't portable. Treat the whole session as gone rather than handing
  // back a null token that would just fail confusingly further down;
  // this forces a normal re-sign-in, the same recovery a user already
  // has for an expired refresh token.
  if (session.accessToken && !accessToken) {
    store.delete("session");
    return null;
  }
  // The same rule for the REFRESH token, and for the same reason. Without
  // it the two readers of a session disagreed: getSession() reported
  // signed-out for a session with no usable refresh token but left it on
  // disk, while getValidAccessToken() went on returning its still-valid
  // access token -- so the UI showed the sign-in page while the heartbeat,
  // registerDevice() and getBrand() kept talking to the console as that
  // user until the hour ran out. A session that can't be renewed is over;
  // deciding that once, here, is what keeps every caller agreeing.
  const refreshToken = decryptField(session.refreshToken);
  if (!refreshToken) {
    store.delete("session");
    return null;
  }
  return { ...session, accessToken, refreshToken };
}

// Same project/public anon key already committed in
// pic-vision-cloud-console/.env.local.example (NEXT_PUBLIC_-prefixed
// values are baked into that app's client bundle, so they're public by
// design, not a secret this file is newly exposing). Overridable for
// local dev against a different Supabase project.
const SUPABASE_URL = process.env.PIC_VISION_SUPABASE_URL || "https://evceszapbiuwdmqfisqx.supabase.co";
const SUPABASE_ANON_KEY = process.env.PIC_VISION_SUPABASE_ANON_KEY || "sb_publishable_vx_czTeMEFsky1w0qf2xVQ_IH-Ekstq";

// Strips the tokens before anything crosses back to the renderer -- unlike
// cloud.js's `connection` (whose apiToken is a long-lived agent credential
// already returned via cloud:status), a Supabase access/refresh token pair
// is a full user-session credential, and nothing in the UI ever needs to
// read it directly.
function publicSession(session) {
  if (!session) return null;
  return { user: session.user, expiresAt: session.expiresAt };
}

async function requestToken(body) {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=${body.grant_type}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", apikey: SUPABASE_ANON_KEY },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error_description || data.msg || `sign-in failed (HTTP ${res.status})`);
  return data;
}

export async function signIn(email, password) {
  const data = await requestToken({ grant_type: "password", email, password });
  const session = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    expiresAt: Date.now() + data.expires_in * 1000,
    user: { id: data.user.id, email: data.user.email },
  };
  saveSession(session);
  logEvent("signed_in", `Signed in as ${session.user.email}`);

  // Registers a device that isn't connected yet; leaves a device
  // connected as somebody ELSE alone, for the UI to ask about (ADR-094).
  // Re-signing in as the same account does nothing at all, which is what
  // this step was originally for: no new agent row, no token rotation.
  //
  // Sign-in itself still succeeds even if this fails (e.g. console
  // unreachable) -- it runs again on every launch.
  try {
    await resolveRegistration(session.accessToken, session.user.id);
  } catch (err) {
    console.error(`[auth] device registration failed: ${err.message}`);
  }

  return publicSession(session);
}

// Re-attempts registration for an already-signed-in device that isn't
// connected yet (a failed first attempt, or an app relaunch that happened
// before the first one ever ran) -- called from main.js at startup and
// from CloudPage.jsx's manual retry, sharing the exact same path signIn()
// uses so there's only one place that decides how a device gets
// registered.
export async function registerDevice() {
  const token = await getValidAccessToken();
  if (!token) throw new Error("not signed in");
  const session = loadSession();
  return registerAgent(token, session?.user?.id);
}

/** Launch-time equivalent of what sign-in does. */
export async function resolveRegistrationForSession() {
  const token = await getValidAccessToken();
  if (!token) throw new Error("not signed in");
  const session = loadSession();
  return resolveRegistration(token, session?.user?.id);
}

/**
 * What, if anything, this device should do about who it's registered as.
 *
 *   "none"     -- not connected to anything: register, silently. A fresh
 *                 machine has nothing to lose and nobody to ask.
 *   "ok"       -- already registered as this account. Do nothing.
 *   "adopt"    -- a connection written before `userId` was recorded (any
 *                 build before 2026-09-09) whose brand still matches the
 *                 signed-in account's. Nothing changed hands; the record
 *                 was just missing a field. Stamp it and move on, so
 *                 upgrading doesn't interrogate every existing user.
 *   "mismatch" -- registered as a DIFFERENT account. Never resolved
 *                 silently: moving a machine hands its cameras (and
 *                 everything they record) to another venue, so a person
 *                 decides, not a launch sequence (ADR-094).
 *
 * Pure, so every branch is testable without a store or a network.
 */
export function registrationState(connection, userId, sessionBrandName) {
  if (!connection) return "none";
  if (connection.userId === userId) return "ok";
  if (!connection.userId && connection.brandName && connection.brandName === sessionBrandName) return "adopt";
  return "mismatch";
}

/**
 * Acts on the above, and returns what it did so the caller (and the UI)
 * can tell a settled device from one waiting on a decision.
 */
export async function resolveRegistration(accessToken, userId) {
  const connection = getCloudConnection();
  // Only fetched when it could matter -- a settled device makes no
  // network call on every launch just to confirm what it already knows.
  const brand = connection && !connection.userId ? await getBrand().catch(() => null) : null;
  const state = registrationState(connection, userId, brand?.name);

  if (state === "none") {
    await registerAgent(accessToken, userId);
  } else if (state === "adopt") {
    adoptConnection(userId);
  }
  return state;
}

/** The same question, for the renderer: is this device waiting on a decision? */
export async function registrationStatus() {
  const session = loadSession();
  if (!session) return { state: "signed-out" };
  const connection = getCloudConnection();
  const state = registrationState(connection, session.user.id, null);
  if (state !== "mismatch") return { state, email: session.user?.email };
  const brand = await getBrand().catch(() => null);
  // Re-ask with the brand in hand: a legacy connection on the same brand
  // is an "adopt", not a mismatch, and shouldn't raise a dialog.
  const settled = registrationState(connection, session.user.id, brand?.name);
  if (settled === "adopt") {
    adoptConnection(session.user.id);
    return { state: "adopt", email: session.user?.email };
  }
  return {
    state: "mismatch",
    email: session.user?.email,
    currentBrandName: connection?.brandName ?? null,
    sessionBrandName: brand?.name ?? null,
  };
}

export async function signOut() {
  const session = loadSession();
  if (session?.accessToken) {
    // Best-effort -- an already-expired or already-revoked token 400s here,
    // which shouldn't block clearing the local session either way.
    await fetch(`${SUPABASE_URL}/auth/v1/logout`, {
      method: "POST",
      headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${session.accessToken}` },
    }).catch(() => {});
  }
  // Logged before clearing -- session.user.email won't exist to read afterward.
  if (session?.user?.email) logEvent("signed_out", `Signed out (${session.user.email})`);
  store.delete("session");
  return null;
}

export function getSession() {
  // An access token lasts about an hour and is renewed by the refresh
  // token, so "expired" on its own is normal and not a problem. A session
  // whose REFRESH token is gone is genuinely over, and loadSession() now
  // clears it -- for every caller at once, not just this one. The access
  // token's own expiry is left to getValidAccessToken(), which refreshes
  // it on demand.
  return publicSession(loadSession());
}

// Refreshes 60s ahead of real expiry so a call that's mid-flight when the
// token turns over doesn't race a 401. Clears the stored session on a
// failed refresh (revoked/expired refresh token) rather than leaving a
// dead session getSession() would keep reporting as signed-in.
async function getValidAccessToken() {
  const session = loadSession();
  if (!session) return null;
  if (Date.now() < session.expiresAt - 60_000) return session.accessToken;
  try {
    const data = await requestToken({ grant_type: "refresh_token", refresh_token: session.refreshToken });
    const refreshed = {
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt: Date.now() + data.expires_in * 1000,
      user: { id: data.user.id, email: data.user.email },
    };
    saveSession(refreshed);
    return refreshed.accessToken;
  } catch {
    store.delete("session");
    return null;
  }
}

// The signed-in operator's own brand (owner_user_id is unique -- exactly
// one brand per account, see DECISIONS.md ADR-071). This is genuinely new
// data sign-in unlocks: cloud.js's pairing/heartbeat only ever learns a
// brand name *after* this specific device is paired to an agent row, so a
// freshly signed-in, not-yet-paired machine had no way to show it before.
export async function getBrand() {
  const token = await getValidAccessToken();
  if (!token) return null;
  const res = await fetch(`${SUPABASE_URL}/rest/v1/brands?select=id,name,timezone`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return null;
  const rows = await res.json().catch(() => []);
  return rows[0] ?? null;
}
