// Encrypts individual secret strings before they reach electron-store's
// plaintext JSON files (see cameras/store.js's original POC-note comment
// -- "fine for local dev, not for a client shipped to real venues"),
// using Electron's safeStorage, which hands off to the OS's own vault
// (macOS Keychain / Windows Credential Manager / Linux Secret Service).
// This only changes what gets written for the specific fields callers
// mark, not the electron-store mechanism itself.
//
// safeStorage.isEncryptionAvailable() can be false even on a supported
// OS -- no Secret Service/keyring daemon running is common on a
// headless or minimal Linux box. Falls back to storing the value as-is
// rather than throwing: this app already shipped a while with
// everything in plaintext, so "no worse than before" is the floor here,
// not a regression to guard against.
import { safeStorage } from "electron";
import { logEvent } from "./activityLog.js";

export const PREFIX = "enc:v1:";

// True for a value this code encrypted. Used by the migration in
// store.js/auth.js/cloud.js to tell "already done" from "written before
// encryption shipped".
export function isEncrypted(value) {
  return typeof value === "string" && value.startsWith(PREFIX);
}

// Was silent -- encryptField() previously just returned the plaintext
// value with no signal anywhere (PIC-146, security audit 2026-09-10:
// "worth explicitly deciding whether that's still the right call, or
// whether it should warn the operator instead of failing silently").
// The fallback ITSELF is still the right call, unchanged: there is no
// other place to put a camera password on a box with no vault, and this
// app already shipped a while with everything in plaintext, so "no worse
// than before" is still the honest floor. What was wrong was that an
// operator on an affected machine -- a headless or minimal Linux box with
// no keyring daemon running, the one real case this was written for --
// had no way to know their camera passwords and API tokens are sitting in
// plain JSON, ever.
//
// encryptField is called on nearly every save (a camera add, a session
// refresh, a heartbeat-driven rename) -- logging every call on an affected
// machine would flood the Log tab and bury everything else in it. Logged
// once per launch instead, the same "state change, not every poll" idiom
// cloud.js's own lastHeartbeatOk already uses for the heartbeat's
// connected/disconnected line.
let warnedThisLaunch = false;

export function encryptField(value) {
  if (value == null) return value;
  if (!safeStorage.isEncryptionAvailable()) {
    if (!warnedThisLaunch) {
      warnedThisLaunch = true;
      logEvent(
        "secure_storage_unavailable",
        "This machine's secure storage isn't available -- saved passwords and tokens are not encrypted",
        "safeStorage.isEncryptionAvailable() returned false (no OS keyring/Secret Service running is common on a headless or minimal Linux box)",
      );
    }
    return value;
  }
  return PREFIX + safeStorage.encryptString(value).toString("base64");
}

// Three cases collapse into the same "give back the original string"
// behavior: a value this code encrypted (has the prefix), a legacy
// plaintext value written before this shipped, and a value written
// while encryption was unavailable (also plain) -- so the only real
// branch is whether to decrypt at all.
export function decryptField(value) {
  if (typeof value !== "string" || !value.startsWith(PREFIX)) return value;
  try {
    return safeStorage.decryptString(Buffer.from(value.slice(PREFIX.length), "base64"));
  } catch {
    // Encrypted under a different OS user/machine (vault keys don't
    // travel with the file) or the vault's been cleared since -- the
    // original value can't be recovered. Returning null rather than the
    // still-encrypted blob so callers fail the same normal way they
    // already handle a missing credential (e.g. a camera whose password
    // is wrong just fails testConnection with a regular user-visible
    // error), not by silently using a garbage string.
    return null;
  }
}
