// A push channel for cloud->agent commands, so "Calibrate" doesn't sit
// there for half a minute.
//
// Measured 2026-09-09 on the operator's own two attempts: 28.7s and 31.4s
// from clicking Calibrate in the console to the snapshot command
// completing. The camera grab and the upload are a few seconds of that;
// the rest is the agent's 30-second heartbeat coming round to notice.
// ADR-071 called this out when it chose polling: "a persistent channel is
// a reasonable later upgrade if command latency becomes a real problem,
// not a day-one requirement". It became one.
//
// This is a fast path, NOT a replacement for the poll:
//
//   - It authenticates with the operator's Supabase session, so a machine
//     whose operator signed out has no subscription. That machine must
//     keep obeying commands (it may be recording tonight), so the 30s
//     heartbeat poll stays exactly as it was and remains the floor.
//   - A dropped websocket, a token that couldn't refresh, Realtime being
//     unavailable -- every one of those degrades to the same 30s poll.
//
// Row visibility is the database's, not ours: `agent_commands` has an RLS
// SELECT policy scoping rows to the brand owner (checked in pg_policies,
// not inferred from a comment), and Realtime enforces it per subscriber.
// The filter below is a narrowing, not the security boundary.
import { createClient } from "@supabase/supabase-js";

// Re-auth well inside a Supabase access token's ~1h life, so a long-lived
// subscription doesn't quietly stop receiving after the token behind it
// expires.
const REAUTH_INTERVAL_MS = 30 * 60 * 1000;

let client = null;
let channel = null;
let reauthTimer = null;
let live = false;

/** Is the push channel actually connected right now? */
export function isCommandChannelLive() {
  return live;
}

/**
 * Subscribe to this agent's commands.
 *
 * `getAccessToken` is async and may return null (signed out, or a refresh
 * that failed) -- in that case nothing is started and the caller keeps
 * polling, which is the whole fallback story.
 */
export async function startCommandChannel({ url, anonKey, agentId, getAccessToken, onCommand, onStatus }) {
  await stopCommandChannel();
  if (!agentId) return false;

  const token = await getAccessToken();
  if (!token) return false;

  client = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    realtime: { params: { eventsPerSecond: 2 } },
  });
  client.realtime.setAuth(token);

  channel = client
    .channel(`agent-commands-${agentId}`)
    .on(
      "postgres_changes",
      { event: "INSERT", schema: "public", table: "agent_commands", filter: `agent_id=eq.${agentId}` },
      (payload) => {
        // The row itself isn't trusted as the command to run: this only
        // says "there is work". The agent still fetches its pending
        // commands over its own authenticated route, so what it executes
        // has been through the same server-side check as before.
        onCommand?.(payload?.new?.type ?? null);
      },
    )
    .subscribe((status) => {
      live = status === "SUBSCRIBED";
      onStatus?.(status);
    });

  // Refresh the token behind the socket periodically. setAuth on an open
  // connection is enough -- no resubscribe needed.
  reauthTimer = setInterval(async () => {
    try {
      const fresh = await getAccessToken();
      if (fresh) client?.realtime.setAuth(fresh);
    } catch {
      // Leave the existing socket alone; if it does drop, the poll covers it.
    }
  }, REAUTH_INTERVAL_MS);

  return true;
}

export async function stopCommandChannel() {
  live = false;
  if (reauthTimer) {
    clearInterval(reauthTimer);
    reauthTimer = null;
  }
  if (channel) {
    try {
      await channel.unsubscribe();
    } catch { /* already gone */ }
    channel = null;
  }
  if (client) {
    try {
      client.realtime.disconnect();
    } catch { /* already gone */ }
    client = null;
  }
}
