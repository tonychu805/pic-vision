// Which Supabase project the app talks to directly: Auth (sign-in, token
// renewal), the brand read and the Realtime command channel. Everything else
// goes through the console.
//
// The console names it in every heartbeat reply (2026-11-20, the database's
// move to Tokyo), so moving the database or rotating its public key needs no
// new release: a copy built before the move adopts the new project on its
// next heartbeat. The built-in project is only the first-launch default.
import Store from "electron-store";

const store = new Store({ name: "database", configFileMode: 0o600 });

export const BUILT_IN_DATABASE = {
  url: "https://evceszapbiuwdmqfisqx.supabase.co",
  key: "sb_publishable_vx_czTeMEFsky1w0qf2xVQ_IH-Ekstq",
};

const PROJECT_URL_RE = /^https:\/\/[a-z0-9]{20}\.supabase\.co$/;

/** A project the console may point at: a Supabase project URL and its public key, or null. */
export function parseDatabase(value) {
  const url = typeof value?.url === "string" ? value.url.replace(/\/$/, "") : "";
  const key = typeof value?.key === "string" ? value.key.trim() : "";
  if (!PROJECT_URL_RE.test(url) || key.length < 20 || key.length > 512) return null;
  return { url, key };
}

/** Local development overrides everything; then what the console last said; then the built-in project. */
export function chooseDatabase(env, stored) {
  if (env.PIC_VISION_SUPABASE_URL) {
    return { url: env.PIC_VISION_SUPABASE_URL, key: env.PIC_VISION_SUPABASE_ANON_KEY || BUILT_IN_DATABASE.key };
  }
  return parseDatabase(stored) ?? BUILT_IN_DATABASE;
}

export function currentDatabase() {
  return chooseDatabase(process.env, store.get("database"));
}

/**
 * Remembers the project a heartbeat reply named. True only when that changes
 * what the app talks to, so the caller can reconnect; a missing, malformed or
 * unchanged value, or a local override, changes nothing.
 */
export function adoptDatabase(fromConsole) {
  const next = parseDatabase(fromConsole);
  if (!next || process.env.PIC_VISION_SUPABASE_URL) return false;
  const now = currentDatabase();
  if (next.url === now.url && next.key === now.key) return false;
  store.set("database", next);
  return true;
}

/**
 * At launch, before anyone signs in: a fresh install has only the built-in
 * project, so after a move it would sign in to the old one. True when the
 * console's answer changed the project. Any failure keeps what we have; the
 * heartbeat repeats the same answer once the machine is connected.
 */
export async function askConsoleForDatabase(consoleUrl, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${consoleUrl.replace(/\/$/, "")}/api/desktop/database`, { signal: AbortSignal.timeout(10_000) });
    if (!res.ok) return false;
    return adoptDatabase(await res.json());
  } catch {
    return false;
  }
}
