// Desktop-side PostHog capture (US Cloud project, same one
// pic-vision-cloud-console uses -- one shared PostHog project across
// both surfaces). Uses posthog-node rather than posthog-js in the
// renderer: this is a desktop app, not a browser page, and main.js
// already owns the one identity worth keying events on (deviceId,
// getOrCreateDeviceId() in cloud.js -- stable across app restarts,
// independent of pairing state, so events land under the same identity
// whether or not the agent is currently paired to a console). A project
// API key is meant to be embedded in client code (same trust level as
// the console's NEXT_PUBLIC_POSTHOG_KEY), so it's a plain default here
// rather than routed through a build-time secret mechanism this app
// doesn't otherwise have.
import { PostHog } from "posthog-node";
import { getOrCreateDeviceId } from "./cloud.js";

const POSTHOG_KEY = process.env.PIC_VISION_POSTHOG_KEY || "phc_yFZ9XpfLSFhVRphmi4cAVf9rdxfrBPjTnLJpi4ZnAACn";
const POSTHOG_HOST = process.env.PIC_VISION_POSTHOG_HOST || "https://us.i.posthog.com";

let client = null;

function getClient() {
  if (!client) client = new PostHog(POSTHOG_KEY, { host: POSTHOG_HOST });
  return client;
}

export function capture(event, properties = {}) {
  getClient().capture({ distinctId: getOrCreateDeviceId(), event, properties });
}

// posthog-node batches and flushes on an interval -- call this from
// main.js's before-quit so a capture right before exit isn't dropped.
export function shutdownAnalytics() {
  return client?.shutdown();
}
