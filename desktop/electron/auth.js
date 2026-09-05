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
import { registerAgent, getCloudConnection } from "./cloud.js";

const store = new Store({ name: "auth" });

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
  store.set("session", session);

  // Only register if this machine isn't already connected to some brand --
  // re-signing in on an already-registered device shouldn't mint a new
  // agent row or rotate its token every time. Sign-in itself still
  // succeeds even if registration fails here (e.g. console unreachable) --
  // `registerDevice` below is also called on every app launch while
  // signed in but not yet connected, so a transient failure here isn't
  // the only chance to recover.
  if (!getCloudConnection()) {
    try {
      await registerAgent(session.accessToken);
    } catch (err) {
      console.error(`[auth] device registration failed: ${err.message}`);
    }
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
  return registerAgent(token);
}

export async function signOut() {
  const session = store.get("session");
  if (session?.accessToken) {
    // Best-effort -- an already-expired or already-revoked token 400s here,
    // which shouldn't block clearing the local session either way.
    await fetch(`${SUPABASE_URL}/auth/v1/logout`, {
      method: "POST",
      headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${session.accessToken}` },
    }).catch(() => {});
  }
  store.delete("session");
  return null;
}

export function getSession() {
  return publicSession(store.get("session", null));
}

// Refreshes 60s ahead of real expiry so a call that's mid-flight when the
// token turns over doesn't race a 401. Clears the stored session on a
// failed refresh (revoked/expired refresh token) rather than leaving a
// dead session getSession() would keep reporting as signed-in.
async function getValidAccessToken() {
  const session = store.get("session");
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
    store.set("session", refreshed);
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
