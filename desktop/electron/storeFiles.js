// Locks down the electron-store JSON files and re-encrypts anything left
// plaintext by a version that predates ADR-082.
//
// Two gaps found by auditing the real files on 2026-09-07, both of the
// same shape -- the fix was applied to new writes and never to what was
// already on disk:
//
//   1. auth.json still held a plaintext Supabase access/refresh token
//      pair. auth.js has encrypted on save since 2026-09-06 01:22, but
//      that file was last written at 00:39, 43 minutes earlier, and
//      nothing rewrites it until the next sign-in. A refresh token is a
//      full account credential.
//
//   2. All the store files were mode 664 -- readable by every other user
//      account on the machine. The repo's own .env was locked to 600 the
//      day before; these were missed. Encryption makes that survivable
//      for the encrypted fields and not for the plaintext ones.
//
// Runs once at startup, before anything reads a credential.
import { chmodSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { app } from "electron";
import { encryptField, isEncrypted } from "./secureField.js";

// Which fields in which files hold secrets. Kept as data rather than
// spread across each module's own save path, because the point here is to
// repair files those save paths never touch.
const SECRET_FIELDS = {
  "auth.json": [["session", "accessToken"], ["session", "refreshToken"]],
  "cloud.json": [["connection", "apiToken"]],
  // cameras.json holds an array, handled separately below.
};

function tighten(file) {
  try {
    // 0600: owner read/write only. electron-store writes 0664 and offers
    // no option to change it, so this is applied after the fact -- and
    // again on every launch, since a later write recreates the file with
    // the default mode.
    chmodSync(file, 0o600);
  } catch {
    // A filesystem without POSIX modes (some Windows setups). Nothing to
    // do, and not worth failing startup over.
  }
}

function reencryptFile(file, name) {
  let data;
  try {
    data = JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return 0; // unreadable or not yet written
  }

  let changed = 0;
  const fix = (obj, key) => {
    if (obj && typeof obj[key] === "string" && !isEncrypted(obj[key])) {
      const encrypted = encryptField(obj[key]);
      // encryptField returns the value unchanged when the OS vault isn't
      // available -- don't count that as a migration or we'd rewrite the
      // file on every launch for nothing.
      if (isEncrypted(encrypted)) {
        obj[key] = encrypted;
        changed++;
      }
    }
  };

  if (name === "cameras.json") {
    for (const camera of data.cameras ?? []) {
      fix(camera, "password");
      fix(camera, "streamUri");
    }
  } else {
    for (const [parent, key] of SECRET_FIELDS[name] ?? []) fix(data[parent], key);
  }

  if (changed > 0) writeFileSync(file, JSON.stringify(data, null, "\t"), { mode: 0o600 });
  return changed;
}

export function secureStoreFiles() {
  const dir = app.getPath("userData");
  let migrated = 0;

  for (const name of ["auth.json", "cloud.json", "cameras.json", "activityLog.json", "schedules.json", "scanSettings.json"]) {
    const file = path.join(dir, name);
    if (!existsSync(file)) continue;
    // Permissions first: a file about to be rewritten with re-encrypted
    // contents shouldn't be world-readable for even that moment.
    tighten(file);
    if (name in SECRET_FIELDS || name === "cameras.json") migrated += reencryptFile(file, name);
  }

  if (migrated > 0) {
    console.log(`[store] re-encrypted ${migrated} secret(s) left in plaintext by an older version`);
  }
}
