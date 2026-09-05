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

const PREFIX = "enc:v1:";

export function encryptField(value) {
  if (value == null) return value;
  if (!safeStorage.isEncryptionAvailable()) return value;
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
