// How long one segment's upload keeps trying before the part is given up.
//
// It used to be 3 tries a few seconds apart (2026-10-28, first real
// production run). The office uplink is about as fast as the camera's
// bitrate, so the upload itself filled it, the transfer stalled ("no data
// moved for 60s") three times inside two minutes, and part 1 was abandoned
// for good: no clips for those 5 minutes until the operator pressed Retry
// 20 minutes later. A venue's Wi-Fi dropping out for a minute or two does
// the same. So keep trying for a while, waiting longer between tries, and
// give up only on an outage long enough that a person should look.
export const UPLOAD_RETRY_WINDOW_MS = 15 * 60_000;

/** Wait before try `attempt + 1`: 5 s, 10 s, 20 s, 40 s, then every 60 s. */
export function retryDelayMs(attempt) {
  return Math.min(60_000, 5_000 * 2 ** (attempt - 1));
}

/**
 * Run `attempt` until it resolves, the window runs out, or `shouldStop(err)`
 * says this failure isn't worth retrying (a cancel). `beforeRetry(err)` runs
 * before each new try, e.g. to fetch a fresh upload address; a failure there
 * is treated like any other failed try.
 */
export async function retryWithinWindow(attempt, {
  windowMs = UPLOAD_RETRY_WINDOW_MS,
  shouldStop = () => false,
  beforeRetry = async () => {},
  onRetry = () => {},
  now = Date.now,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
} = {}) {
  const started = now();
  for (let n = 1; ; n++) {
    try {
      return await attempt();
    } catch (err) {
      if (shouldStop(err)) throw err;
      const delay = retryDelayMs(n);
      if (now() - started + delay > windowMs) throw err;
      onRetry(err, n, delay);
      await sleep(delay);
      if (shouldStop(err)) throw err;
      try {
        await beforeRetry(err);
      } catch {
        // The next try fails the same way and is counted, or works anyway.
      }
    }
  }
}
