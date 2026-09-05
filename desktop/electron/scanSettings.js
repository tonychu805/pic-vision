// Real scan configuration (2026-09-05, replacing SettingsPage.jsx's mock
// "Ranges"/"Behaviour" panels) -- persisted extra network ranges and the
// per-address probe timeout, both of which networkSweep.js's sweepNetwork
// already accepted as real parameters; nothing here is new detection
// capability, just exposing knobs that already existed.
//
// Deliberately narrower than the original mockup's 4 panels: the "How
// scanning works" protocol checkboxes and the "Scan when picvision
// opens"/cadence radios are gone, not just left disabled -- see
// desktop/README.md for why (4 of 7 "protocols" don't exist in code at
// all, and auto-scan-on-launch was already explicitly removed once,
// 2026-09-03, "operator's call").
import Store from "electron-store";
import { hostsInCidr, MAX_HOSTS } from "./cameras/networkSweep.js";

const store = new Store({ name: "scanSettings" });

const DEFAULT_TIMEOUT_MS = 400;
const MIN_TIMEOUT_MS = 50;
const MAX_TIMEOUT_MS = 10_000;
const CIDR_RE = /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/;
const BARE_IP_RE = /^(\d{1,3}\.){3}\d{1,3}$/;

// Extra ranges only ever extend the RTSP port sweep (networkSweep.js) --
// ONVIF WS-Discovery is multicast and can't reach a genuinely separate
// subnet no matter what range is configured here. Callers surfacing this
// setting to the operator should say so, not imply it helps both methods.
export function getExtraRanges() {
  return store.get("extraRanges", []);
}

// Accepts a full CIDR ("10.20.5.0/24") or a bare IP ("10.20.5.37"),
// auto-expanded to a /24 around it -- most people know one camera's
// actual address (its own settings screen, or the vendor's app), not the
// CIDR notation for the block it lives in. /24 is a guess, but it's the
// dominant real-world default for a venue-sized network, and a wrong
// guess still shows up in the scan results to correct.
//
// Also rejects a too-big range at add-time (reusing networkSweep.js's own
// MAX_HOSTS/hostsInCidr rather than a second cap) instead of only at scan
// time -- catches a typo'd prefix (or a vendor's whole /16 pasted as-is)
// immediately, not several clicks later.
export function addExtraRange(input) {
  let trimmed = String(input ?? "").trim();
  if (BARE_IP_RE.test(trimmed)) {
    trimmed = trimmed.replace(/\.\d{1,3}$/, ".0") + "/24";
  }
  if (!CIDR_RE.test(trimmed)) throw new Error("Enter an address like 192.168.1.50 or a range like 192.168.1.0/24");
  const hostCount = hostsInCidr(trimmed).length;
  if (hostCount > MAX_HOSTS) {
    throw new Error(`${trimmed} covers ${hostCount} addresses (cap is ${MAX_HOSTS}) -- narrow it to the block your cameras actually sit on`);
  }
  const ranges = getExtraRanges();
  if (ranges.includes(trimmed)) return ranges;
  const updated = [...ranges, trimmed];
  store.set("extraRanges", updated);
  return updated;
}

export function removeExtraRange(cidr) {
  const updated = getExtraRanges().filter((r) => r !== cidr);
  store.set("extraRanges", updated);
  return updated;
}

export function getTimeoutMs() {
  return store.get("timeoutMs", DEFAULT_TIMEOUT_MS);
}

export function setTimeoutMs(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < MIN_TIMEOUT_MS || n > MAX_TIMEOUT_MS) {
    throw new Error(`Timeout must be between ${MIN_TIMEOUT_MS} and ${MAX_TIMEOUT_MS} ms`);
  }
  store.set("timeoutMs", n);
  return n;
}
